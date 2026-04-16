"""
OASIS simulation runner.
Runs simulations in the background, records each Agent action, and supports real-time status monitoring.
"""

import os
import sys
import json
import time
import asyncio
import threading
import subprocess
import signal
import atexit
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from queue import Queue

from ..config import Config
from ..utils.logger import get_logger
from .zep_graph_memory_updater import ZepGraphMemoryManager
from .simulation_ipc import SimulationIPCClient, CommandType, IPCResponse

logger = get_logger('mirofish.simulation_runner')

# Whether the cleanup handler has already been registered.
_cleanup_registered = False

# Platform detection.
IS_WINDOWS = sys.platform == 'win32'


class RunnerStatus(str, Enum):
    """Runner status."""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentAction:
    """Recorded Agent action."""
    round_num: int
    timestamp: str
    platform: str  # twitter / reddit
    agent_id: int
    agent_name: str
    action_type: str  # CREATE_POST, LIKE_POST, etc.
    action_args: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    success: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_num": self.round_num,
            "timestamp": self.timestamp,
            "platform": self.platform,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "action_type": self.action_type,
            "action_args": self.action_args,
            "result": self.result,
            "success": self.success,
        }


@dataclass
class RoundSummary:
    """Summary for one round."""
    round_num: int
    start_time: str
    end_time: Optional[str] = None
    simulated_hour: int = 0
    twitter_actions: int = 0
    reddit_actions: int = 0
    active_agents: List[int] = field(default_factory=list)
    actions: List[AgentAction] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_num": self.round_num,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "simulated_hour": self.simulated_hour,
            "twitter_actions": self.twitter_actions,
            "reddit_actions": self.reddit_actions,
            "active_agents": self.active_agents,
            "actions_count": len(self.actions),
            "actions": [a.to_dict() for a in self.actions],
        }


@dataclass
class SimulationRunState:
    """Real-time simulation run state."""
    simulation_id: str
    runner_status: RunnerStatus = RunnerStatus.IDLE
    
    # Progress information.
    current_round: int = 0
    total_rounds: int = 0
    simulated_hours: int = 0
    total_simulation_hours: int = 0
    
    # Per-platform round counters and simulated time for dual-platform display.
    twitter_current_round: int = 0
    reddit_current_round: int = 0
    twitter_simulated_hours: int = 0
    reddit_simulated_hours: int = 0
    
    # Platform status.
    twitter_running: bool = False
    reddit_running: bool = False
    twitter_actions_count: int = 0
    reddit_actions_count: int = 0
    
    # Platform completion flags, detected through `simulation_end` events in `actions.jsonl`.
    twitter_completed: bool = False
    reddit_completed: bool = False
    
    # Per-round summaries.
    rounds: List[RoundSummary] = field(default_factory=list)
    
    # Recent actions for frontend display.
    recent_actions: List[AgentAction] = field(default_factory=list)
    max_recent_actions: int = 50
    
    # Timestamps.
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    
    # Error information.
    error: Optional[str] = None
    
    # Process ID used for termination.
    process_pid: Optional[int] = None
    
    def add_action(self, action: AgentAction):
        """Add an action to the recent-action list."""
        self.recent_actions.insert(0, action)
        if len(self.recent_actions) > self.max_recent_actions:
            self.recent_actions = self.recent_actions[:self.max_recent_actions]
        
        if action.platform == "twitter":
            self.twitter_actions_count += 1
        else:
            self.reddit_actions_count += 1
        
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "runner_status": self.runner_status.value,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "simulated_hours": self.simulated_hours,
            "total_simulation_hours": self.total_simulation_hours,
            "progress_percent": round(self.current_round / max(self.total_rounds, 1) * 100, 1),
            # Per-platform rounds and time.
            "twitter_current_round": self.twitter_current_round,
            "reddit_current_round": self.reddit_current_round,
            "twitter_simulated_hours": self.twitter_simulated_hours,
            "reddit_simulated_hours": self.reddit_simulated_hours,
            "twitter_running": self.twitter_running,
            "reddit_running": self.reddit_running,
            "twitter_completed": self.twitter_completed,
            "reddit_completed": self.reddit_completed,
            "twitter_actions_count": self.twitter_actions_count,
            "reddit_actions_count": self.reddit_actions_count,
            "total_actions_count": self.twitter_actions_count + self.reddit_actions_count,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "process_pid": self.process_pid,
        }
    
    def to_detail_dict(self) -> Dict[str, Any]:
        """Return the detailed state including recent actions."""
        result = self.to_dict()
        result["recent_actions"] = [a.to_dict() for a in self.recent_actions]
        result["rounds_count"] = len(self.rounds)
        return result


class SimulationRunner:
    """
    Simulation runner.

    Responsibilities:
    1. Run OASIS simulations in a background process
    2. Parse runtime logs and record Agent actions
    3. Provide real-time state query APIs
    4. Support pause / stop / resume operations
    """
    
    # Run-state storage directory.
    RUN_STATE_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/simulations'
    )
    
    # Scripts directory.
    SCRIPTS_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../scripts'
    )
    
    # In-memory run state.
    _run_states: Dict[str, SimulationRunState] = {}
    _processes: Dict[str, subprocess.Popen] = {}
    _action_queues: Dict[str, Queue] = {}
    _monitor_threads: Dict[str, threading.Thread] = {}
    _stdout_files: Dict[str, Any] = {}  # Stored stdout file handles.
    _stderr_files: Dict[str, Any] = {}  # Stored stderr file handles.
    
    # Graph-memory update configuration.
    _graph_memory_enabled: Dict[str, bool] = {}  # simulation_id -> enabled
    
    @classmethod
    def get_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """Get the current run state."""
        if simulation_id in cls._run_states:
            return cls._run_states[simulation_id]
        
        # Attempt to load from disk.
        state = cls._load_run_state(simulation_id)
        if state:
            cls._run_states[simulation_id] = state
        return state
    
    @classmethod
    def _load_run_state(cls, simulation_id: str) -> Optional[SimulationRunState]:
        """Load the run state from disk."""
        state_file = os.path.join(cls.RUN_STATE_DIR, simulation_id, "run_state.json")
        if not os.path.exists(state_file):
            return None
        
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            state = SimulationRunState(
                simulation_id=simulation_id,
                runner_status=RunnerStatus(data.get("runner_status", "idle")),
                current_round=data.get("current_round", 0),
                total_rounds=data.get("total_rounds", 0),
                simulated_hours=data.get("simulated_hours", 0),
                total_simulation_hours=data.get("total_simulation_hours", 0),
                # Per-platform rounds and time.
                twitter_current_round=data.get("twitter_current_round", 0),
                reddit_current_round=data.get("reddit_current_round", 0),
                twitter_simulated_hours=data.get("twitter_simulated_hours", 0),
                reddit_simulated_hours=data.get("reddit_simulated_hours", 0),
                twitter_running=data.get("twitter_running", False),
                reddit_running=data.get("reddit_running", False),
                twitter_completed=data.get("twitter_completed", False),
                reddit_completed=data.get("reddit_completed", False),
                twitter_actions_count=data.get("twitter_actions_count", 0),
                reddit_actions_count=data.get("reddit_actions_count", 0),
                started_at=data.get("started_at"),
                updated_at=data.get("updated_at", datetime.now().isoformat()),
                completed_at=data.get("completed_at"),
                error=data.get("error"),
                process_pid=data.get("process_pid"),
            )
            
            # Load recent actions.
            actions_data = data.get("recent_actions", [])
            for a in actions_data:
                state.recent_actions.append(AgentAction(
                    round_num=a.get("round_num", 0),
                    timestamp=a.get("timestamp", ""),
                    platform=a.get("platform", ""),
                    agent_id=a.get("agent_id", 0),
                    agent_name=a.get("agent_name", ""),
                    action_type=a.get("action_type", ""),
                    action_args=a.get("action_args", {}),
                    result=a.get("result"),
                    success=a.get("success", True),
                ))
            
            return state
        except Exception as e:
            logger.error(f"Failed to load run state: {str(e)}")
            return None
    
    @classmethod
    def _save_run_state(cls, state: SimulationRunState):
        """Persist the run state to disk."""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        state_file = os.path.join(sim_dir, "run_state.json")
        
        data = state.to_detail_dict()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        cls._run_states[state.simulation_id] = state
    
    @classmethod
    def start_simulation(
        cls,
        simulation_id: str,
        platform: str = "parallel",  # twitter / reddit / parallel
        max_rounds: int = None,  # Maximum simulation rounds, optional.
        enable_graph_memory_update: bool = False,  # Whether to stream activities into the Zep graph.
        graph_id: str = None  # Zep graph ID, required when graph-memory updates are enabled.
    ) -> SimulationRunState:
        """
        Start a simulation.
        
        Args:
            simulation_id: simulation ID
            platform: Execution platform (`twitter`, `reddit`, or `parallel`)
            max_rounds: Optional maximum round count, used to cap long simulations
            enable_graph_memory_update: Whether to stream Agent activity into the Zep graph
            graph_id: Zep graph ID, required when graph-memory updates are enabled
            
        Returns:
            SimulationRunState
        """
        # Check whether the simulation is already running.
        existing = cls.get_run_state(simulation_id)
        if existing and existing.runner_status in [RunnerStatus.RUNNING, RunnerStatus.STARTING]:
            raise ValueError(f"Simulation is already running: {simulation_id}")
        
        # Load the simulation config.
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            raise ValueError("Simulation config does not exist. Call `/prepare` first.")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Initialize the run state.
        time_config = config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        total_rounds = int(total_hours * 60 / minutes_per_round)
        
        # Cap the simulation if a maximum round count is provided.
        if max_rounds is not None and max_rounds > 0:
            original_rounds = total_rounds
            total_rounds = min(total_rounds, max_rounds)
            if total_rounds < original_rounds:
                logger.info(f"Round count truncated: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
        
        state = SimulationRunState(
            simulation_id=simulation_id,
            runner_status=RunnerStatus.STARTING,
            total_rounds=total_rounds,
            total_simulation_hours=total_hours,
            started_at=datetime.now().isoformat(),
        )
        
        cls._save_run_state(state)
        
        # Create the graph-memory updater if enabled.
        if enable_graph_memory_update:
            if not graph_id:
                raise ValueError("`graph_id` is required when graph-memory updates are enabled")
            
            try:
                ZepGraphMemoryManager.create_updater(simulation_id, graph_id)
                cls._graph_memory_enabled[simulation_id] = True
                logger.info(f"Graph-memory updates enabled: simulation_id={simulation_id}, graph_id={graph_id}")
            except Exception as e:
                logger.error(f"Failed to create graph-memory updater: {e}")
                cls._graph_memory_enabled[simulation_id] = False
        else:
            cls._graph_memory_enabled[simulation_id] = False
        
        # Determine which runtime script to execute from `backend/scripts/`.
        if platform == "twitter":
            script_name = "run_twitter_simulation.py"
            state.twitter_running = True
        elif platform == "reddit":
            script_name = "run_reddit_simulation.py"
            state.reddit_running = True
        else:
            script_name = "run_parallel_simulation.py"
            state.twitter_running = True
            state.reddit_running = True
        
        script_path = os.path.join(cls.SCRIPTS_DIR, script_name)
        
        if not os.path.exists(script_path):
            raise ValueError(f"Script does not exist: {script_path}")
        
        # Create the action queue.
        action_queue = Queue()
        cls._action_queues[simulation_id] = action_queue
        
        # Start the simulation process.
        try:
            # Build the command using full paths.
            # New log structure:
            #   twitter/actions.jsonl - Twitter action log
            #   reddit/actions.jsonl  - Reddit action log
            #   simulation.log        - Main process log
            
            cmd = [
                sys.executable,  # Python interpreter.
                script_path,
                "--config", config_path,  # Use the full config file path.
            ]
            
            # Add the round cap to CLI args when provided.
            if max_rounds is not None and max_rounds > 0:
                cmd.extend(["--max-rounds", str(max_rounds)])
            
            # Write directly to a log file to avoid stdout/stderr pipe backpressure.
            main_log_path = os.path.join(sim_dir, "simulation.log")
            main_log_file = open(main_log_path, 'w', encoding='utf-8')
            
            # Set subprocess environment variables so Windows also uses UTF-8.
            # This helps with third-party libraries such as OASIS that open files without explicit encodings.
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'  # Python 3.7+ support: default `open()` to UTF-8.
            env['PYTHONIOENCODING'] = 'utf-8'  # Ensure stdout/stderr use UTF-8.
            
            # Use the simulation directory as cwd so generated DBs and artifacts land there.
            # `start_new_session=True` creates a process group so `os.killpg` can stop all children.
            process = subprocess.Popen(
                cmd,
                cwd=sim_dir,
                stdout=main_log_file,
                stderr=subprocess.STDOUT,  # Write stderr into the same log file.
                text=True,
                encoding='utf-8',  # Explicit encoding.
                bufsize=1,
                env=env,  # Pass the UTF-8 environment settings through.
                start_new_session=True,  # Create a new process group so all child processes can be terminated.
            )
            
            # Keep file handles so they can be closed later.
            cls._stdout_files[simulation_id] = main_log_file
            cls._stderr_files[simulation_id] = None  # Separate stderr is no longer needed.
            
            state.process_pid = process.pid
            state.runner_status = RunnerStatus.RUNNING
            cls._processes[simulation_id] = process
            cls._save_run_state(state)
            
            # Start the monitoring thread.
            monitor_thread = threading.Thread(
                target=cls._monitor_simulation,
                args=(simulation_id,),
                daemon=True
            )
            monitor_thread.start()
            cls._monitor_threads[simulation_id] = monitor_thread
            
            logger.info(f"Simulation started successfully: {simulation_id}, pid={process.pid}, platform={platform}")
            
        except Exception as e:
            state.runner_status = RunnerStatus.FAILED
            state.error = str(e)
            cls._save_run_state(state)
            raise
        
        return state
    
    @classmethod
    def _monitor_simulation(cls, simulation_id: str):
        """Monitor the simulation process and parse action logs."""
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        # New log structure: per-platform action logs.
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        process = cls._processes.get(simulation_id)
        state = cls.get_run_state(simulation_id)
        
        if not process or not state:
            return
        
        twitter_position = 0
        reddit_position = 0
        
        try:
            while process.poll() is None:  # Process is still running.
                # Read Twitter action logs.
                if os.path.exists(twitter_actions_log):
                    twitter_position = cls._read_action_log(
                        twitter_actions_log, twitter_position, state, "twitter"
                    )
                
                # Read Reddit action logs.
                if os.path.exists(reddit_actions_log):
                    reddit_position = cls._read_action_log(
                        reddit_actions_log, reddit_position, state, "reddit"
                    )
                
                # Persist updated state.
                cls._save_run_state(state)
                time.sleep(2)
            
            # One final log read after process exit.
            if os.path.exists(twitter_actions_log):
                cls._read_action_log(twitter_actions_log, twitter_position, state, "twitter")
            if os.path.exists(reddit_actions_log):
                cls._read_action_log(reddit_actions_log, reddit_position, state, "reddit")
            
            # Process exited.
            exit_code = process.returncode
            
            if exit_code == 0:
                state.runner_status = RunnerStatus.COMPLETED
                state.completed_at = datetime.now().isoformat()
                logger.info(f"Simulation completed: {simulation_id}")
            else:
                state.runner_status = RunnerStatus.FAILED
                # Read the trailing error text from the main log file.
                main_log_path = os.path.join(sim_dir, "simulation.log")
                error_info = ""
                try:
                    if os.path.exists(main_log_path):
                        with open(main_log_path, 'r', encoding='utf-8') as f:
                            error_info = f.read()[-2000:]  # Keep the final 2000 characters.
                except Exception:
                    pass
                state.error = f"Process exit code: {exit_code}, error: {error_info}"
                logger.error(f"Simulation failed: {simulation_id}, error={state.error}")
            
            state.twitter_running = False
            state.reddit_running = False
            cls._save_run_state(state)
            
        except Exception as e:
            logger.error(f"Monitoring thread failed: {simulation_id}, error={str(e)}")
            state.runner_status = RunnerStatus.FAILED
            state.error = str(e)
            cls._save_run_state(state)
        
        finally:
            # Stop the graph-memory updater.
            if cls._graph_memory_enabled.get(simulation_id, False):
                try:
                    ZepGraphMemoryManager.stop_updater(simulation_id)
                    logger.info(f"Stopped graph-memory updates: simulation_id={simulation_id}")
                except Exception as e:
                    logger.error(f"Failed to stop graph-memory updater: {e}")
                cls._graph_memory_enabled.pop(simulation_id, None)
            
            # Clean up process resources.
            cls._processes.pop(simulation_id, None)
            cls._action_queues.pop(simulation_id, None)
            
            # Close log file handles.
            if simulation_id in cls._stdout_files:
                try:
                    cls._stdout_files[simulation_id].close()
                except Exception:
                    pass
                cls._stdout_files.pop(simulation_id, None)
            if simulation_id in cls._stderr_files and cls._stderr_files[simulation_id]:
                try:
                    cls._stderr_files[simulation_id].close()
                except Exception:
                    pass
                cls._stderr_files.pop(simulation_id, None)
    
    @classmethod
    def _read_action_log(
        cls, 
        log_path: str, 
        position: int, 
        state: SimulationRunState,
        platform: str
    ) -> int:
        """
        Read an action log file.
        
        Args:
            log_path: Log file path
            position: Previous read offset
            state: Run state object
            platform: Platform name (`twitter` / `reddit`)
            
        Returns:
            New read offset
        """
        # Check whether graph-memory updates are enabled.
        graph_memory_enabled = cls._graph_memory_enabled.get(state.simulation_id, False)
        graph_updater = None
        if graph_memory_enabled:
            graph_updater = ZepGraphMemoryManager.get_updater(state.simulation_id)
        
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                f.seek(position)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            action_data = json.loads(line)
                            
                            # Handle event-style log entries.
                            if "event_type" in action_data:
                                event_type = action_data.get("event_type")
                                
                                # Detect `simulation_end` and mark the platform as complete.
                                if event_type == "simulation_end":
                                    if platform == "twitter":
                                        state.twitter_completed = True
                                        state.twitter_running = False
                                        logger.info(f"Twitter simulation completed: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    elif platform == "reddit":
                                        state.reddit_completed = True
                                        state.reddit_running = False
                                        logger.info(f"Reddit simulation completed: {state.simulation_id}, total_rounds={action_data.get('total_rounds')}, total_actions={action_data.get('total_actions')}")
                                    
                                    # Check whether all enabled platforms have completed.
                                    # In single-platform mode, only that platform matters.
                                    # In dual-platform mode, both must finish.
                                    all_completed = cls._check_all_platforms_completed(state)
                                    if all_completed:
                                        state.runner_status = RunnerStatus.COMPLETED
                                        state.completed_at = datetime.now().isoformat()
                                        logger.info(f"All enabled platform simulations completed: {state.simulation_id}")
                                
                                # Update round information from `round_end`.
                                elif event_type == "round_end":
                                    round_num = action_data.get("round", 0)
                                    simulated_hours = action_data.get("simulated_hours", 0)
                                    
                                    # Update per-platform rounds and simulated time.
                                    if platform == "twitter":
                                        if round_num > state.twitter_current_round:
                                            state.twitter_current_round = round_num
                                        state.twitter_simulated_hours = simulated_hours
                                    elif platform == "reddit":
                                        if round_num > state.reddit_current_round:
                                            state.reddit_current_round = round_num
                                        state.reddit_simulated_hours = simulated_hours
                                    
                                    # The overall round is the max of the two platforms.
                                    if round_num > state.current_round:
                                        state.current_round = round_num
                                    # The overall simulated time is the max of the two platforms.
                                    state.simulated_hours = max(state.twitter_simulated_hours, state.reddit_simulated_hours)
                                
                                continue
                            
                            action = AgentAction(
                                round_num=action_data.get("round", 0),
                                timestamp=action_data.get("timestamp", datetime.now().isoformat()),
                                platform=platform,
                                agent_id=action_data.get("agent_id", 0),
                                agent_name=action_data.get("agent_name", ""),
                                action_type=action_data.get("action_type", ""),
                                action_args=action_data.get("action_args", {}),
                                result=action_data.get("result"),
                                success=action_data.get("success", True),
                            )
                            state.add_action(action)
                            
                            # Update the overall round counter.
                            if action.round_num and action.round_num > state.current_round:
                                state.current_round = action.round_num
                            
                            # If graph-memory updates are enabled, forward the activity to Zep.
                            if graph_updater:
                                graph_updater.add_activity_from_dict(action_data, platform)
                            
                        except json.JSONDecodeError:
                            pass
                return f.tell()
        except Exception as e:
            logger.warning(f"Failed to read action log: {log_path}, error={e}")
            return position
    
    @classmethod
    def _check_all_platforms_completed(cls, state: SimulationRunState) -> bool:
        """
        Check whether all enabled platforms have completed.

        Platform enablement is inferred from whether each `actions.jsonl` file exists.
        
        Returns:
            True if all enabled platforms have completed
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, state.simulation_id)
        twitter_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        reddit_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        
        # Detect which platforms were enabled by checking whether their files exist.
        twitter_enabled = os.path.exists(twitter_log)
        reddit_enabled = os.path.exists(reddit_log)
        
        # If any enabled platform is unfinished, return False.
        if twitter_enabled and not state.twitter_completed:
            return False
        if reddit_enabled and not state.reddit_completed:
            return False
        
        # At least one platform was enabled and all enabled platforms have completed.
        return twitter_enabled or reddit_enabled
    
    @classmethod
    def _terminate_process(cls, process: subprocess.Popen, simulation_id: str, timeout: int = 10):
        """
        Terminate a process and its children across platforms.
        
        Args:
            process: Process to terminate
            simulation_id: Simulation ID, used for logs
            timeout: Timeout in seconds while waiting for process exit
        """
        if IS_WINDOWS:
            # Windows: use `taskkill` to terminate the whole process tree.
            # `/F` = force, `/T` = include child processes.
            logger.info(f"Terminating process tree (Windows): simulation={simulation_id}, pid={process.pid}")
            try:
                # Try graceful termination first.
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T'],
                    capture_output=True,
                    timeout=5
                )
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Force termination if the process did not exit.
                    logger.warning(f"Process did not respond; forcing termination: {simulation_id}")
                    subprocess.run(
                        ['taskkill', '/F', '/PID', str(process.pid), '/T'],
                        capture_output=True,
                        timeout=5
                    )
                    process.wait(timeout=5)
            except Exception as e:
                logger.warning(f"`taskkill` failed; falling back to `terminate()`: {e}")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        else:
            # Unix: terminate the process group.
            # Because `start_new_session=True` is used, the process group ID equals the main PID.
            pgid = os.getpgid(process.pid)
            logger.info(f"Terminating process group (Unix): simulation={simulation_id}, pgid={pgid}")
            
            # Send SIGTERM to the entire process group first.
            os.killpg(pgid, signal.SIGTERM)
            
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Fall back to SIGKILL if the group still hasn't exited.
                logger.warning(f"Process group did not respond to SIGTERM; forcing termination: {simulation_id}")
                os.killpg(pgid, signal.SIGKILL)
                process.wait(timeout=5)
    
    @classmethod
    def stop_simulation(cls, simulation_id: str) -> SimulationRunState:
        """Stop a running simulation."""
        state = cls.get_run_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation not found: {simulation_id}")
        
        if state.runner_status not in [RunnerStatus.RUNNING, RunnerStatus.PAUSED]:
            raise ValueError(f"Simulation is not running: {simulation_id}, status={state.runner_status}")
        
        state.runner_status = RunnerStatus.STOPPING
        cls._save_run_state(state)
        
        # Terminate the process.
        process = cls._processes.get(simulation_id)
        if process and process.poll() is None:
            try:
                cls._terminate_process(process, simulation_id)
            except ProcessLookupError:
                # The process no longer exists.
                pass
            except Exception as e:
                logger.error(f"Failed to terminate process group: {simulation_id}, error={e}")
                # Fall back to terminating the main process directly.
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
        
        state.runner_status = RunnerStatus.STOPPED
        state.twitter_running = False
        state.reddit_running = False
        state.completed_at = datetime.now().isoformat()
        cls._save_run_state(state)
        
        # Stop the graph-memory updater.
        if cls._graph_memory_enabled.get(simulation_id, False):
            try:
                ZepGraphMemoryManager.stop_updater(simulation_id)
                logger.info(f"Stopped graph-memory updates: simulation_id={simulation_id}")
            except Exception as e:
                logger.error(f"Failed to stop graph-memory updater: {e}")
            cls._graph_memory_enabled.pop(simulation_id, None)
        
        logger.info(f"Simulation stopped: {simulation_id}")
        return state
    
    @classmethod
    def _read_actions_from_file(
        cls,
        file_path: str,
        default_platform: Optional[str] = None,
        platform_filter: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        Read actions from a single action file.
        
        Args:
            file_path: Action log file path
            default_platform: Default platform if a record has no `platform` field
            platform_filter: Platform filter
            agent_id: Agent ID filter
            round_num: Round filter
        """
        if not os.path.exists(file_path):
            return []
        
        actions = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    
                    # Skip non-action records such as `simulation_start`, `round_start`, and `round_end`.
                    if "event_type" in data:
                        continue
                    
                    # Skip records without `agent_id`, because they are not Agent actions.
                    if "agent_id" not in data:
                        continue
                    
                    # Determine the platform, preferring the record field over the default.
                    record_platform = data.get("platform") or default_platform or ""
                    
                    # Apply filters.
                    if platform_filter and record_platform != platform_filter:
                        continue
                    if agent_id is not None and data.get("agent_id") != agent_id:
                        continue
                    if round_num is not None and data.get("round") != round_num:
                        continue
                    
                    actions.append(AgentAction(
                        round_num=data.get("round", 0),
                        timestamp=data.get("timestamp", ""),
                        platform=record_platform,
                        agent_id=data.get("agent_id", 0),
                        agent_name=data.get("agent_name", ""),
                        action_type=data.get("action_type", ""),
                        action_args=data.get("action_args", {}),
                        result=data.get("result"),
                        success=data.get("success", True),
                    ))
                    
                except json.JSONDecodeError:
                    continue
        
        return actions
    
    @classmethod
    def get_all_actions(
        cls,
        simulation_id: str,
        platform: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        Get the complete action history across all platforms, without pagination.
        
        Args:
            simulation_id: simulation ID
            platform: Platform filter (`twitter` / `reddit`)
            agent_id: Agent filter
            round_num: Round filter
            
        Returns:
            Full action list, sorted by timestamp descending
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        actions = []
        
        # Read the Twitter action file and automatically set `platform="twitter"`.
        twitter_actions_log = os.path.join(sim_dir, "twitter", "actions.jsonl")
        if not platform or platform == "twitter":
            actions.extend(cls._read_actions_from_file(
                twitter_actions_log,
                default_platform="twitter",  # Auto-fill the `platform` field.
                platform_filter=platform,
                agent_id=agent_id, 
                round_num=round_num
            ))
        
        # Read the Reddit action file and automatically set `platform="reddit"`.
        reddit_actions_log = os.path.join(sim_dir, "reddit", "actions.jsonl")
        if not platform or platform == "reddit":
            actions.extend(cls._read_actions_from_file(
                reddit_actions_log,
                default_platform="reddit",  # Auto-fill the `platform` field.
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            ))
        
        # Fall back to the old single-file format if per-platform logs do not exist.
        if not actions:
            actions_log = os.path.join(sim_dir, "actions.jsonl")
            actions = cls._read_actions_from_file(
                actions_log,
                default_platform=None,  # Old-format files should already include `platform`.
                platform_filter=platform,
                agent_id=agent_id,
                round_num=round_num
            )
        
        # Sort by timestamp descending.
        actions.sort(key=lambda x: x.timestamp, reverse=True)
        
        return actions
    
    @classmethod
    def get_actions(
        cls,
        simulation_id: str,
        limit: int = 100,
        offset: int = 0,
        platform: Optional[str] = None,
        agent_id: Optional[int] = None,
        round_num: Optional[int] = None
    ) -> List[AgentAction]:
        """
        Get paginated action history.
        
        Args:
            simulation_id: simulation ID
            limit: Max number of records to return
            offset: Offset
            platform: Platform filter
            agent_id: Agent filter
            round_num: Round filter
            
        Returns:
            Action list
        """
        actions = cls.get_all_actions(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )
        
        # Apply pagination.
        return actions[offset:offset + limit]
    
    @classmethod
    def get_timeline(
        cls,
        simulation_id: str,
        start_round: int = 0,
        end_round: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get the simulation timeline summarized by round.
        
        Args:
            simulation_id: simulation ID
            start_round: Starting round
            end_round: Ending round
            
        Returns:
            Summary information for each round
        """
        actions = cls.get_actions(simulation_id, limit=10000)
        
        # Group by round.
        rounds: Dict[int, Dict[str, Any]] = {}
        
        for action in actions:
            round_num = action.round_num
            
            if round_num < start_round:
                continue
            if end_round is not None and round_num > end_round:
                continue
            
            if round_num not in rounds:
                rounds[round_num] = {
                    "round_num": round_num,
                    "twitter_actions": 0,
                    "reddit_actions": 0,
                    "active_agents": set(),
                    "action_types": {},
                    "first_action_time": action.timestamp,
                    "last_action_time": action.timestamp,
                }
            
            r = rounds[round_num]
            
            if action.platform == "twitter":
                r["twitter_actions"] += 1
            else:
                r["reddit_actions"] += 1
            
            r["active_agents"].add(action.agent_id)
            r["action_types"][action.action_type] = r["action_types"].get(action.action_type, 0) + 1
            r["last_action_time"] = action.timestamp
        
        # Convert to a list.
        result = []
        for round_num in sorted(rounds.keys()):
            r = rounds[round_num]
            result.append({
                "round_num": round_num,
                "twitter_actions": r["twitter_actions"],
                "reddit_actions": r["reddit_actions"],
                "total_actions": r["twitter_actions"] + r["reddit_actions"],
                "active_agents_count": len(r["active_agents"]),
                "active_agents": list(r["active_agents"]),
                "action_types": r["action_types"],
                "first_action_time": r["first_action_time"],
                "last_action_time": r["last_action_time"],
            })
        
        return result
    
    @classmethod
    def get_agent_stats(cls, simulation_id: str) -> List[Dict[str, Any]]:
        """
        Get per-Agent statistics.
        
        Returns:
            Agent statistics list
        """
        actions = cls.get_actions(simulation_id, limit=10000)
        
        agent_stats: Dict[int, Dict[str, Any]] = {}
        
        for action in actions:
            agent_id = action.agent_id
            
            if agent_id not in agent_stats:
                agent_stats[agent_id] = {
                    "agent_id": agent_id,
                    "agent_name": action.agent_name,
                    "total_actions": 0,
                    "twitter_actions": 0,
                    "reddit_actions": 0,
                    "action_types": {},
                    "first_action_time": action.timestamp,
                    "last_action_time": action.timestamp,
                }
            
            stats = agent_stats[agent_id]
            stats["total_actions"] += 1
            
            if action.platform == "twitter":
                stats["twitter_actions"] += 1
            else:
                stats["reddit_actions"] += 1
            
            stats["action_types"][action.action_type] = stats["action_types"].get(action.action_type, 0) + 1
            stats["last_action_time"] = action.timestamp
        
        # Sort by total action count.
        result = sorted(agent_stats.values(), key=lambda x: x["total_actions"], reverse=True)
        
        return result
    
    @classmethod
    def cleanup_simulation_logs(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Clean simulation runtime logs so a fresh run can start from a clean state.

        Deletes the following files:
        - run_state.json
        - twitter/actions.jsonl
        - reddit/actions.jsonl
        - simulation.log
        - stdout.log / stderr.log
        - `twitter_simulation.db` (simulation database)
        - `reddit_simulation.db` (simulation database)
        - `env_status.json` (environment state)
        
        Note: this does not delete the config file (`simulation_config.json`) or profile files.
        
        Args:
            simulation_id: simulation ID
            
        Returns:
            Cleanup result information
        """
        import shutil
        
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return {"success": True, "message": "Simulation directory does not exist; nothing to clean"}
        
        cleaned_files = []
        errors = []
        
        # Files to delete, including database files.
        files_to_delete = [
            "run_state.json",
            "simulation.log",
            "stdout.log",
            "stderr.log",
            "twitter_simulation.db",  # Twitter database
            "reddit_simulation.db",   # Reddit database
            "env_status.json",        # Environment status file
        ]
        
        # Directories to clean, containing action logs.
        dirs_to_clean = ["twitter", "reddit"]
        
        # Delete files.
        for filename in files_to_delete:
            file_path = os.path.join(sim_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    cleaned_files.append(filename)
                except Exception as e:
                    errors.append(f"Failed to delete {filename}: {str(e)}")
        
        # Clean action logs from platform directories.
        for dir_name in dirs_to_clean:
            dir_path = os.path.join(sim_dir, dir_name)
            if os.path.exists(dir_path):
                actions_file = os.path.join(dir_path, "actions.jsonl")
                if os.path.exists(actions_file):
                    try:
                        os.remove(actions_file)
                        cleaned_files.append(f"{dir_name}/actions.jsonl")
                    except Exception as e:
                        errors.append(f"Failed to delete {dir_name}/actions.jsonl: {str(e)}")
        
        # Clean in-memory run state.
        if simulation_id in cls._run_states:
            del cls._run_states[simulation_id]
        
        logger.info(f"Simulation log cleanup completed: {simulation_id}, deleted files: {cleaned_files}")
        
        return {
            "success": len(errors) == 0,
            "cleaned_files": cleaned_files,
            "errors": errors if errors else None
        }
    
    # Guard against duplicate cleanup.
    _cleanup_done = False
    
    @classmethod
    def cleanup_all_simulations(cls):
        """
        Clean up all running simulation processes.

        Called during server shutdown to ensure all child processes are terminated.
        """
        # Avoid duplicate cleanup.
        if cls._cleanup_done:
            return
        cls._cleanup_done = True
        
        # Check whether anything actually needs cleanup to avoid noisy no-op logs.
        has_processes = bool(cls._processes)
        has_updaters = bool(cls._graph_memory_enabled)
        
        if not has_processes and not has_updaters:
            return  # Nothing to clean; exit quietly.
        
        logger.info("Cleaning up all simulation processes...")
        
        # Stop all graph-memory updaters first; `stop_all()` logs internally.
        try:
            ZepGraphMemoryManager.stop_all()
        except Exception as e:
            logger.error(f"Failed to stop graph-memory updaters: {e}")
        cls._graph_memory_enabled.clear()
        
        # Copy the dict so iteration is safe during mutation.
        processes = list(cls._processes.items())
        
        for simulation_id, process in processes:
            try:
                if process.poll() is None:  # Process is still running.
                    logger.info(f"Terminating simulation process: {simulation_id}, pid={process.pid}")
                    
                    try:
                        # Use the cross-platform termination helper.
                        cls._terminate_process(process, simulation_id, timeout=5)
                    except (ProcessLookupError, OSError):
                        # The process may already be gone; fall back to direct termination.
                        try:
                            process.terminate()
                            process.wait(timeout=3)
                        except Exception:
                            process.kill()
                    
                    # Update `run_state.json`.
                    state = cls.get_run_state(simulation_id)
                    if state:
                        state.runner_status = RunnerStatus.STOPPED
                        state.twitter_running = False
                        state.reddit_running = False
                        state.completed_at = datetime.now().isoformat()
                        state.error = "Server shutdown terminated the simulation"
                        cls._save_run_state(state)
                    
                    # Also update `state.json` and mark the status as `stopped`.
                    try:
                        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
                        state_file = os.path.join(sim_dir, "state.json")
                        logger.info(f"Attempting to update state.json: {state_file}")
                        if os.path.exists(state_file):
                            with open(state_file, 'r', encoding='utf-8') as f:
                                state_data = json.load(f)
                            state_data['status'] = 'stopped'
                            state_data['updated_at'] = datetime.now().isoformat()
                            with open(state_file, 'w', encoding='utf-8') as f:
                                json.dump(state_data, f, indent=2, ensure_ascii=False)
                            logger.info(f"Updated state.json status to `stopped`: {simulation_id}")
                        else:
                            logger.warning(f"`state.json` does not exist: {state_file}")
                    except Exception as state_err:
                        logger.warning(f"Failed to update state.json: {simulation_id}, error={state_err}")
                        
            except Exception as e:
                logger.error(f"Failed to clean process: {simulation_id}, error={e}")
        
        # Clean up file handles.
        for simulation_id, file_handle in list(cls._stdout_files.items()):
            try:
                if file_handle:
                    file_handle.close()
            except Exception:
                pass
        cls._stdout_files.clear()
        
        for simulation_id, file_handle in list(cls._stderr_files.items()):
            try:
                if file_handle:
                    file_handle.close()
            except Exception:
                pass
        cls._stderr_files.clear()
        
        # Clear in-memory state.
        cls._processes.clear()
        cls._action_queues.clear()
        
        logger.info("Simulation process cleanup completed")
    
    @classmethod
    def register_cleanup(cls):
        """
        Register cleanup handlers.

        Called during Flask app startup so all simulation processes are cleaned up on shutdown.
        """
        global _cleanup_registered
        
        if _cleanup_registered:
            return
        
        # In Flask debug mode, register cleanup only in the reloader child process,
        # which is the process that actually runs the app.
        # `WERKZEUG_RUN_MAIN=true` indicates the reloader child.
        # In non-debug mode that env var is absent, and cleanup should still be registered.
        is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        is_debug_mode = os.environ.get('FLASK_DEBUG') == '1' or os.environ.get('WERKZEUG_RUN_MAIN') is not None
        
        # In debug mode register only in the reloader child; in non-debug mode always register.
        if is_debug_mode and not is_reloader_process:
            _cleanup_registered = True  # Mark as registered so the child does not retry.
            return
        
        # Preserve existing signal handlers.
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        # SIGHUP exists only on Unix platforms such as macOS and Linux.
        original_sighup = None
        has_sighup = hasattr(signal, 'SIGHUP')
        if has_sighup:
            original_sighup = signal.getsignal(signal.SIGHUP)
        
        def cleanup_handler(signum=None, frame=None):
            """Signal handler: clean simulation processes first, then invoke the original handler."""
            # Log only when there is something to clean.
            if cls._processes or cls._graph_memory_enabled:
                logger.info(f"Received signal {signum}; starting cleanup...")
            cls.cleanup_all_simulations()
            
            # Invoke the original signal handler so Flask exits normally.
            if signum == signal.SIGINT and callable(original_sigint):
                original_sigint(signum, frame)
            elif signum == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(signum, frame)
            elif has_sighup and signum == signal.SIGHUP:
                # SIGHUP: sent when the terminal closes.
                if callable(original_sighup):
                    original_sighup(signum, frame)
                else:
                    # Default behavior: exit normally.
                    sys.exit(0)
            else:
                # If the original handler is not callable (for example `SIG_DFL`), use default behavior.
                raise KeyboardInterrupt
        
        # Register an `atexit` handler as a fallback.
        atexit.register(cls.cleanup_all_simulations)
        
        # Register signal handlers, but only from the main thread.
        try:
            # SIGTERM: default signal sent by `kill`.
            signal.signal(signal.SIGTERM, cleanup_handler)
            # SIGINT: Ctrl+C
            signal.signal(signal.SIGINT, cleanup_handler)
            # SIGHUP: terminal closed, Unix only.
            if has_sighup:
                signal.signal(signal.SIGHUP, cleanup_handler)
        except ValueError:
            # Not in the main thread, so only `atexit` can be used.
            logger.warning("Could not register signal handlers because this is not the main thread; using `atexit` only")
        
        _cleanup_registered = True
    
    @classmethod
    def get_running_simulations(cls) -> List[str]:
        """
        Get the IDs of all currently running simulations.
        """
        running = []
        for sim_id, process in cls._processes.items():
            if process.poll() is None:
                running.append(sim_id)
        return running
    
    # ============== Interview Features ==============
    
    @classmethod
    def check_env_alive(cls, simulation_id: str) -> bool:
        """
        Check whether the simulation environment is alive and able to receive interview commands.

        Args:
            simulation_id: simulation ID

        Returns:
            `True` if the environment is alive; `False` if it has already shut down
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            return False

        ipc_client = SimulationIPCClient(sim_dir)
        return ipc_client.check_env_alive()

    @classmethod
    def get_env_status_detail(cls, simulation_id: str) -> Dict[str, Any]:
        """
        Get detailed status information for the simulation environment.

        Args:
            simulation_id: simulation ID

        Returns:
            A status dictionary containing `status`, `twitter_available`, `reddit_available`, and `timestamp`
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        status_file = os.path.join(sim_dir, "env_status.json")
        
        default_status = {
            "status": "stopped",
            "twitter_available": False,
            "reddit_available": False,
            "timestamp": None
        }
        
        if not os.path.exists(status_file):
            return default_status
        
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
            return {
                "status": status.get("status", "stopped"),
                "twitter_available": status.get("twitter_available", False),
                "reddit_available": status.get("reddit_available", False),
                "timestamp": status.get("timestamp")
            }
        except (json.JSONDecodeError, OSError):
            return default_status

    @classmethod
    def interview_agent(
        cls,
        simulation_id: str,
        agent_id: int,
        prompt: str,
        platform: str = None,
        timeout: float = 60.0
    ) -> Dict[str, Any]:
        """
        Interview a single Agent.

        Args:
            simulation_id: simulation ID
            agent_id: Agent ID
            prompt: Interview question
            platform: Optional target platform
                - "twitter": interview only on Twitter
                - "reddit": interview only on Reddit
                - None: in dual-platform mode, interview both and return a combined result
            timeout: Timeout in seconds

        Returns:
            Interview result dictionary

        Raises:
            ValueError: The simulation does not exist or the environment is not running
            TimeoutError: The response wait timed out
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation not found: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running or has already shut down; cannot perform interview: {simulation_id}")

        logger.info(f"Sending interview command: simulation_id={simulation_id}, agent_id={agent_id}, platform={platform}")

        response = ipc_client.send_interview(
            agent_id=agent_id,
            prompt=prompt,
            platform=platform,
            timeout=timeout
        )

        if response.status.value == "completed":
            return {
                "success": True,
                "agent_id": agent_id,
                "prompt": prompt,
                "result": response.result,
                "timestamp": response.timestamp
            }
        else:
            return {
                "success": False,
                "agent_id": agent_id,
                "prompt": prompt,
                "error": response.error,
                "timestamp": response.timestamp
            }
    
    @classmethod
    def interview_agents_batch(
        cls,
        simulation_id: str,
        interviews: List[Dict[str, Any]],
        platform: str = None,
        timeout: float = 120.0
    ) -> Dict[str, Any]:
        """
        Interview multiple Agents in batch.

        Args:
            simulation_id: simulation ID
            interviews: Interview list, where each item contains `{"agent_id": int, "prompt": str, "platform": str (optional)}`
            platform: Optional default platform; overridden by each interview item's `platform`
                - "twitter": default to Twitter only
                - "reddit": default to Reddit only
                - None: in dual-platform mode, interview each Agent on both platforms
            timeout: Timeout in seconds

        Returns:
            Batch interview result dictionary

        Raises:
            ValueError: The simulation does not exist or the environment is not running
            TimeoutError: The response wait timed out
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation not found: {simulation_id}")

        ipc_client = SimulationIPCClient(sim_dir)

        if not ipc_client.check_env_alive():
            raise ValueError(f"Simulation environment is not running or has already shut down; cannot perform interview: {simulation_id}")

        logger.info(f"Sending batch interview command: simulation_id={simulation_id}, count={len(interviews)}, platform={platform}")

        response = ipc_client.send_batch_interview(
            interviews=interviews,
            platform=platform,
            timeout=timeout
        )

        if response.status.value == "completed":
            return {
                "success": True,
                "interviews_count": len(interviews),
                "result": response.result,
                "timestamp": response.timestamp
            }
        else:
            return {
                "success": False,
                "interviews_count": len(interviews),
                "error": response.error,
                "timestamp": response.timestamp
            }
    
    @classmethod
    def interview_all_agents(
        cls,
        simulation_id: str,
        prompt: str,
        platform: str = None,
        timeout: float = 180.0
    ) -> Dict[str, Any]:
        """
        Interview all Agents in the simulation with the same prompt.

        Args:
            simulation_id: simulation ID
            prompt: Interview question used for every Agent
            platform: Optional target platform
                - "twitter": interview only on Twitter
                - "reddit": interview only on Reddit
                - None: in dual-platform mode, interview each Agent on both platforms
            timeout: Timeout in seconds

        Returns:
            Global interview result dictionary
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation not found: {simulation_id}")

        # Load all Agent information from the config file.
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            raise ValueError(f"Simulation config does not exist: {simulation_id}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        agent_configs = config.get("agent_configs", [])
        if not agent_configs:
            raise ValueError(f"No Agents were found in the simulation config: {simulation_id}")

        # Build the batch interview list.
        interviews = []
        for agent_config in agent_configs:
            agent_id = agent_config.get("agent_id")
            if agent_id is not None:
                interviews.append({
                    "agent_id": agent_id,
                    "prompt": prompt
                })

        logger.info(f"Sending global interview command: simulation_id={simulation_id}, agent_count={len(interviews)}, platform={platform}")

        return cls.interview_agents_batch(
            simulation_id=simulation_id,
            interviews=interviews,
            platform=platform,
            timeout=timeout
        )
    
    @classmethod
    def close_simulation_env(
        cls,
        simulation_id: str,
        timeout: float = 30.0
    ) -> Dict[str, Any]:
        """
        Close the simulation environment without stopping the simulation process itself.

        Sends a shutdown command so the environment exits its command-wait loop gracefully.
        
        Args:
            simulation_id: simulation ID
            timeout: Timeout in seconds
            
        Returns:
            Result dictionary
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        if not os.path.exists(sim_dir):
            raise ValueError(f"Simulation not found: {simulation_id}")
        
        ipc_client = SimulationIPCClient(sim_dir)
        
        if not ipc_client.check_env_alive():
            return {
                "success": True,
                "message": "The environment is already closed"
            }
        
        logger.info(f"Sending close-environment command: simulation_id={simulation_id}")
        
        try:
            response = ipc_client.send_close_env(timeout=timeout)
            
            return {
                "success": response.status.value == "completed",
                "message": "Close-environment command sent",
                "result": response.result,
                "timestamp": response.timestamp
            }
        except TimeoutError:
            # A timeout may simply mean the environment is already shutting down.
            return {
                "success": True,
                "message": "Close-environment command sent (response timed out; the environment may already be shutting down)"
            }
    
    @classmethod
    def _get_interview_history_from_db(
        cls,
        db_path: str,
        platform_name: str,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get interview history from a single database."""
        import sqlite3
        
        if not os.path.exists(db_path):
            return []
        
        results = []
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            if agent_id is not None:
                cursor.execute("""
                    SELECT user_id, info, created_at
                    FROM trace
                    WHERE action = 'interview' AND user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (agent_id, limit))
            else:
                cursor.execute("""
                    SELECT user_id, info, created_at
                    FROM trace
                    WHERE action = 'interview'
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
            
            for user_id, info_json, created_at in cursor.fetchall():
                try:
                    info = json.loads(info_json) if info_json else {}
                except json.JSONDecodeError:
                    info = {"raw": info_json}
                
                results.append({
                    "agent_id": user_id,
                    "response": info.get("response", info),
                    "prompt": info.get("prompt", ""),
                    "timestamp": created_at,
                    "platform": platform_name
                })
            
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to read interview history ({platform_name}): {e}")
        
        return results

    @classmethod
    def get_interview_history(
        cls,
        simulation_id: str,
        platform: str = None,
        agent_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get interview history from the databases.
        
        Args:
            simulation_id: simulation ID
            platform: Platform type (`reddit`, `twitter`, or `None`)
                - "reddit": get only Reddit history
                - "twitter": get only Twitter history
                - None: get history from both platforms
            agent_id: Optional Agent ID filter
            limit: Per-platform result limit
            
        Returns:
            Interview history record list
        """
        sim_dir = os.path.join(cls.RUN_STATE_DIR, simulation_id)
        
        results = []
        
        # Determine which platforms to query.
        if platform in ("reddit", "twitter"):
            platforms = [platform]
        else:
            # Query both platforms when no platform is specified.
            platforms = ["twitter", "reddit"]
        
        for p in platforms:
            db_path = os.path.join(sim_dir, f"{p}_simulation.db")
            platform_results = cls._get_interview_history_from_db(
                db_path=db_path,
                platform_name=p,
                agent_id=agent_id,
                limit=limit
            )
            results.extend(platform_results)
        
        # Sort by time descending.
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # If multiple platforms were queried, cap the combined result count.
        if len(platforms) > 1 and len(results) > limit:
            results = results[:limit]
        
        return results
