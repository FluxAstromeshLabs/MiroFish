"""
OASIS simulation manager.
Handles parallel Twitter and Reddit simulations using preset scripts plus LLM-generated configuration.
"""

import os
import json
import shutil
import concurrent.futures
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import ZepEntityReader, FilteredEntities
from .oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from .simulation_config_generator import SimulationConfigGenerator, SimulationParameters

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """Simulation status."""
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"      # Simulation stopped manually.
    COMPLETED = "completed"  # Simulation completed naturally.
    FAILED = "failed"


class PlatformType(str, Enum):
    """Platform type."""
    TWITTER = "twitter"
    REDDIT = "reddit"


@dataclass
class SimulationState:
    """Simulation state."""
    simulation_id: str
    project_id: str
    graph_id: str
    
    # Platform enablement.
    enable_twitter: bool = True
    enable_reddit: bool = True
    
    # State.
    status: SimulationStatus = SimulationStatus.CREATED
    
    # Preparation-stage data.
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)
    
    # Configuration generation details.
    config_generated: bool = False
    config_reasoning: str = ""
    
    # Runtime data.
    current_round: int = 0
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"
    
    # Timestamps.
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Error details.
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Full state dictionary for internal use."""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "config_reasoning": self.config_reasoning,
            "current_round": self.current_round,
            "twitter_status": self.twitter_status,
            "reddit_status": self.reddit_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }
    
    def to_simple_dict(self) -> Dict[str, Any]:
        """Simplified state dictionary for API responses."""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "error": self.error,
        }


class SimulationManager:
    """
    Simulation manager.

    Core responsibilities:
    1. Read and filter entities from the Zep graph.
    2. Generate OASIS agent profiles.
    3. Use the LLM to generate simulation configuration parameters.
    4. Prepare all files required by the preset scripts.
    """
    
    # Simulation data directory.
    SIMULATION_DATA_DIR = os.path.join(
        os.path.dirname(__file__), 
        '../../uploads/simulations'
    )
    
    def __init__(self):
        # Ensure the directory exists.
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)
        
        # In-memory cache of simulation states.
        self._simulations: Dict[str, SimulationState] = {}
    
    def _get_simulation_dir(self, simulation_id: str) -> str:
        """Get the simulation data directory."""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir
    
    def _save_simulation_state(self, state: SimulationState):
        """Persist simulation state to disk."""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        state.updated_at = datetime.now().isoformat()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        
        self._simulations[state.simulation_id] = state
    
    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """Load simulation state from disk."""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]
        
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            status=SimulationStatus(data.get("status", "created")),
            entities_count=data.get("entities_count", 0),
            profiles_count=data.get("profiles_count", 0),
            entity_types=data.get("entity_types", []),
            config_generated=data.get("config_generated", False),
            config_reasoning=data.get("config_reasoning", ""),
            current_round=data.get("current_round", 0),
            twitter_status=data.get("twitter_status", "not_started"),
            reddit_status=data.get("reddit_status", "not_started"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
        )
        
        self._simulations[simulation_id] = state
        return state
    
    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> SimulationState:
        """
        Create a new simulation.
        
        Args:
            project_id: Project ID.
            graph_id: Zep graph ID.
            enable_twitter: Whether to enable the Twitter simulation.
            enable_reddit: Whether to enable the Reddit simulation.
            
        Returns:
            SimulationState
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )
        
        self._save_simulation_state(state)
        logger.info(f"Created simulation: {simulation_id}, project={project_id}, graph={graph_id}")
        
        return state
    
    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[callable] = None,
        parallel_profile_count: int = 3,
        max_agents: Optional[int] = None
    ) -> SimulationState:
        """
        Prepare the simulation environment end-to-end.
        
        Steps:
        1. Read and filter entities from the Zep graph.
        2. Generate an OASIS agent profile for each entity, optionally with LLM enrichment and parallelism.
        3. Use the LLM to generate simulation configuration parameters such as time, activity level, and posting frequency.
        4. Save the config and profile files.
        5. Copy the preset scripts into the simulation directory.
        
        Args:
            simulation_id: Simulation ID.
            simulation_requirement: Simulation requirement description used for LLM configuration generation.
            document_text: Original document text used for background understanding.
            defined_entity_types: Optional predefined entity types.
            use_llm_for_profiles: Whether to use the LLM to generate detailed personas.
            progress_callback: Progress callback as `(stage, progress, message)`.
            parallel_profile_count: Number of profiles to generate in parallel, default 3.
            
        Returns:
            SimulationState
        """
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation does not exist: {simulation_id}")
        
        try:
            state.status = SimulationStatus.PREPARING
            self._save_simulation_state(state)
            
            sim_dir = self._get_simulation_dir(simulation_id)
            
            # ========== Stage 1: read and filter entities ==========
            if progress_callback:
                progress_callback("reading", 0, "Connecting to the Zep graph...")
            
            reader = ZepEntityReader()
            
            if progress_callback:
                progress_callback("reading", 30, "Reading node data...")
            
            filtered = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=defined_entity_types,
                enrich_with_edges=True
            )
            
            if max_agents and max_agents > 0:
                filtered.entities = filtered.entities[:max_agents]
                filtered.filtered_count = len(filtered.entities)

            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)

            if progress_callback:
                progress_callback(
                    "reading", 100,
                    f"Done, found {filtered.filtered_count} entities",
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )

            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "No matching entities were found. Check whether the graph was built correctly."
                self._save_simulation_state(state)
                return state
            
            # ========== Stage 2 + 3: generate agent profiles and config in parallel ==========
            total_entities = len(filtered.entities)

            if progress_callback:
                progress_callback(
                    "generating_profiles", 0,
                    "Starting generation...",
                    current=0,
                    total=total_entities
                )

            # --- Profile generation task ---
            # Pass graph_id to enable Zep retrieval and provide richer context.
            def _generate_profiles():
                generator = OasisProfileGenerator(graph_id=state.graph_id)

                def profile_progress(current, total, msg):
                    if progress_callback:
                        progress_callback(
                            "generating_profiles",
                            int(current / total * 100),
                            msg,
                            current=current,
                            total=total,
                            item_name=msg
                        )

                # Set the realtime-save output path, preferring Reddit JSON format.
                realtime_output_path = None
                realtime_platform = "reddit"
                if state.enable_reddit:
                    realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                    realtime_platform = "reddit"
                elif state.enable_twitter:
                    realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                    realtime_platform = "twitter"

                profiles = generator.generate_profiles_from_entities(
                    entities=filtered.entities,
                    use_llm=use_llm_for_profiles,
                    progress_callback=profile_progress,
                    graph_id=state.graph_id,  # pass `graph_id` for Zep retrieval
                    parallel_count=parallel_profile_count,  # parallel generation count
                    realtime_output_path=realtime_output_path,  # realtime output path
                    output_platform=realtime_platform  # output format
                )

                # Save profile files (Twitter uses CSV, Reddit uses JSON).
                # Reddit was already saved incrementally during generation; save once more here for completeness.
                if state.enable_reddit:
                    generator.save_profiles(
                        profiles=profiles,
                        file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                        platform="reddit"
                    )
                if state.enable_twitter:
                    # Twitter must use CSV format. This is required by OASIS.
                    generator.save_profiles(
                        profiles=profiles,
                        file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                        platform="twitter"
                    )
                return profiles

            # --- Config generation task ---
            def _generate_config():
                if progress_callback:
                    progress_callback(
                        "generating_config", 0,
                        "Analyzing simulation requirements...",
                        current=0,
                        total=3
                    )
                config_generator = SimulationConfigGenerator()
                return config_generator.generate_config(
                    simulation_id=simulation_id,
                    project_id=state.project_id,
                    graph_id=state.graph_id,
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    entities=filtered.entities,
                    enable_twitter=state.enable_twitter,
                    enable_reddit=state.enable_reddit
                )

            # Run both in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                profile_future = pool.submit(_generate_profiles)
                config_future = pool.submit(_generate_config)

                profiles = profile_future.result()
                sim_params = config_future.result()

            state.profiles_count = len(profiles)

            if progress_callback:
                progress_callback(
                    "generating_profiles", 100,
                    f"Completed, total {len(profiles)} Profiles",
                    current=len(profiles),
                    total=len(profiles)
                )

            # Save the config file
            config_path = os.path.join(sim_dir, "simulation_config.json")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())

            state.config_generated = True
            state.config_reasoning = sim_params.generation_reasoning

            if progress_callback:
                progress_callback(
                    "generating_config", 100,
                    "Config generation completed",
                    current=3,
                    total=3
                )
            
            # Keep runtime scripts in `backend/scripts/`; do not copy them into the simulation directory.
            # When starting the simulation, `simulation_runner` runs scripts from the scripts directory.
            
            # Update state
            state.status = SimulationStatus.READY
            self._save_simulation_state(state)
            
            logger.info(f"Simulation preparation completed: {simulation_id}, "
                       f"entities={state.entities_count}, profiles={state.profiles_count}")
            
            return state
            
        except Exception as e:
            logger.error(f"Simulation preparation failed: {simulation_id}, error={str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise
    
    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """Get simulation state"""
        return self._load_simulation_state(simulation_id)
    
    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """List all simulations"""
        simulations = []
        
        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # Skip hidden files (such as .DS_Store) and non-directory entries
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue
                
                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)
        
        return simulations
    
    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """Get simulation Agent Profiles"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"Simulation does not exist: {simulation_id}")
        
        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")
        
        if not os.path.exists(profile_path):
            return []
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """Get simulation config"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """Get run instructions"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
            "instructions": (
                f"1. Activate the conda environment: conda activate MiroFish\n"
                f"2. Run the simulation (scripts are located at {scripts_dir}):\n"
                f"   - Run Twitter only: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - Run Reddit only: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - Run both platforms in parallel: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }
