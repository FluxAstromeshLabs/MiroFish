"""
Simulation config intelligent generator
Use the LLM to generate detailed simulation parameters automatically from the requirement, document content, and graph information.
Provide end-to-end automation without manual parameter tuning.

Use a staged generation strategy to avoid failures from generating too much content in one shot:
1. Generate time configuration
2. Generate event configuration
3. Generate Agent configurations in batches
4. Generate platform configuration
"""

import json
import math
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from openai import OpenAI

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.simulation_config')

# China schedule configuration (Beijing time)
CHINA_TIMEZONE_CONFIG = {
    # late-night hours (almost no activity)
    "dead_hours": [0, 1, 2, 3, 4, 5],
    # morning hours (waking up gradually)
    "morning_hours": [6, 7, 8],
    # working hours
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    # evening peak hours (most active)
    "peak_hours": [19, 20, 21, 22],
    # night hours (activity drops)
    "night_hours": [23],
    # activity multipliers
    "activity_multipliers": {
        "dead": 0.05,      # almost no one active in the early morning
        "morning": 0.4,    # activity gradually increases in the morning
        "work": 0.7,       # moderate during working hours
        "peak": 1.5,       # evening peak
        "night": 0.5       # decline late at night
    }
}


@dataclass
class AgentActivityConfig:
    """Activity config for a single Agent"""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str
    
    # Activity level config (0.0-1.0)
    activity_level: float = 0.5  # overall activity level
    
    # posting frequency (expected number of actions per hour)
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0
    
    # active hours (24-hour clock, 0-23)
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))
    
    # response speed (delay for reacting to hot events, in simulated minutes)
    response_delay_min: int = 5
    response_delay_max: int = 60
    
    # sentiment bias (-1.0 to 1.0, negative to positive)
    sentiment_bias: float = 0.0
    
    # stance (attitude toward specific topics)
    stance: str = "neutral"  # supportive, opposing, neutral, observer
    
    # influence weight (affects the probability that other Agents see this Agent's posts)
    influence_weight: float = 1.0


@dataclass  
class TimeSimulationConfig:
    """Time simulation config based on typical China schedules"""
    # total simulation duration (simulated hours)
    total_simulation_hours: int = 72  # default to 72 simulated hours (3 days)
    
    # time represented by each round (simulated minutes) - default 60 minutes (1 hour) to speed up time flow
    minutes_per_round: int = 60
    
    # range of Agents activated per hour
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20
    
    # peak period (19:00-22:00, the most active time for typical China schedules)
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5
    
    # off-peak period (00:00-05:00, almost no activity)
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05  # very low activity in the early morning
    
    # morning hours
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4
    
    # working hours
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """event config"""
    # initial events triggered at simulation start
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)
    
    # scheduled events triggered at specific times
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # hot-topic keywords
    hot_topics: List[str] = field(default_factory=list)
    
    # narrative direction
    narrative_direction: str = ""


@dataclass
class PlatformConfig:
    """platform-specific configuration"""
    platform: str  # twitter or reddit
    
    # recommendation algorithm weights
    recency_weight: float = 0.4  # recency
    popularity_weight: float = 0.3  # popularity
    relevance_weight: float = 0.3  # relevance
    
    # viral spread threshold (interactions required before amplification starts)
    viral_threshold: int = 10
    
    # echo-chamber strength (how strongly similar viewpoints cluster)
    echo_chamber_strength: float = 0.5


@dataclass
class SimulationParameters:
    """Complete simulation parameter configuration"""
    # basic info
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str
    
    # time config
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)
    
    # Agent config list
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)
    
    # event config
    event_config: EventConfig = field(default_factory=EventConfig)
    
    # platform config
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None
    
    # LLM config
    llm_model: str = ""
    llm_base_url: str = ""
    
    # generation metadata
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    generation_reasoning: str = ""  # LLM reasoning summary
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict"""
        time_dict = asdict(self.time_config)
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "time_config": time_dict,
            "agent_configs": [asdict(a) for a in self.agent_configs],
            "event_config": asdict(self.event_config),
            "twitter_config": asdict(self.twitter_config) if self.twitter_config else None,
            "reddit_config": asdict(self.reddit_config) if self.reddit_config else None,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "generated_at": self.generated_at,
            "generation_reasoning": self.generation_reasoning,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class SimulationConfigGenerator:
    """
    Simulation config intelligent generator
    
    Use the LLM to analyze the simulation requirement, document content, and graph entities,
    and automatically generate the best simulation parameter configuration.
    
    Staged generation:
    1. Generate time config and event config first
    2. Generate Agent configurations in batches
    3. Generate platform configuration
    """
    
    # maximum context length
    MAX_CONTEXT_LENGTH = 50000
    # number of Agents generated per batch
    AGENTS_PER_BATCH = 15
    
    # context truncation lengths for each step (characters)
    TIME_CONFIG_CONTEXT_LENGTH = 10000   # time config
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # event config
    ENTITY_SUMMARY_LENGTH = 300          # entity summary
    AGENT_SUMMARY_LENGTH = 300           # Entity summary used in Agent config
    ENTITIES_PER_TYPE_DISPLAY = 20       # number of entities to display per type
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY is not configured")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def generate_config(
        self,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SimulationParameters:
        """
        Generate the full simulation config intelligently in multiple steps
        
        Args:
            simulation_id: simulation ID
            project_id: project ID
            graph_id: graph ID
            simulation_requirement: simulation requirement description
            document_text: raw document content
            entities: filtered entity list
            enable_twitter: whether to enable Twitter
            enable_reddit: whether to enable Reddit
            progress_callback: progress callback function `(current_step, total_steps, message)`
            
        Returns:
            SimulationParameters: complete simulation parameters
        """
        logger.info(f"Start generating simulation config intelligently: simulation_id={simulation_id}, entity_count={len(entities)}")
        
        # Calculate the total number of steps
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches  # time config + event config + N Agent batches + platform config
        current_step = 0
        
        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")
        
        # 1. Build base context information
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )
        
        reasoning_parts = []
        
        # ========== Step 1: Generate time configuration ==========
        report_progress(1, "Generate time configuration...")
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"time config: {time_config_result.get('reasoning', 'success')}")
        
        # ========== Step 2: Generate event configuration ==========
        report_progress(2, "Generating event configuration and hot topics...")
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(event_config_result)
        reasoning_parts.append(f"event config: {event_config_result.get('reasoning', 'success')}")
        
        # ========== Steps 3-N: Generate Agent configurations in batches ==========
        all_agent_configs = []
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.AGENTS_PER_BATCH
            end_idx = min(start_idx + self.AGENTS_PER_BATCH, len(entities))
            batch_entities = entities[start_idx:end_idx]
            
            report_progress(
                3 + batch_idx,
                f"Generating Agent config ({start_idx + 1}-{end_idx}/{len(entities)})..."
            )
            
            batch_configs = self._generate_agent_configs_batch(
                context=context,
                entities=batch_entities,
                start_idx=start_idx,
                simulation_requirement=simulation_requirement
            )
            all_agent_configs.extend(batch_configs)
        
        reasoning_parts.append(f"agent config: successfully generated {len(all_agent_configs)}")
        
        # ========== Assign poster Agents for initial posts ==========
        logger.info("Assigning appropriate poster Agents for initial posts...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(f"initial post assignment: {assigned_count} posts assigned")
        
        # ========== Final step: Generate platform configuration ==========
        report_progress(total_steps, "Generate platform configuration...")
        twitter_config = None
        reddit_config = None
        
        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,
                echo_chamber_strength=0.5
            )
        
        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,
                popularity_weight=0.4,
                relevance_weight=0.3,
                viral_threshold=15,
                echo_chamber_strength=0.6
            )
        
        # Build final parameters
        params = SimulationParameters(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            time_config=time_config,
            agent_configs=all_agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            llm_model=self.model_name,
            llm_base_url=self.base_url,
            generation_reasoning=" | ".join(reasoning_parts)
        )
        
        logger.info(f"Simulation config generation completed: {len(params.agent_configs)} agent configs")
        
        return params
    
    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode]
    ) -> str:
        """Build LLM context and truncate it to the maximum length"""
        
        # entity summary
        entity_summary = self._summarize_entities(entities)
        
        # Build context
        context_parts = [
            f"## Simulation requirement\n{simulation_requirement}",
            f"\n## Entity information ({len(entities)})\n{entity_summary}",
        ]
        
        current_length = sum(len(p) for p in context_parts)
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500  # leave 500 characters of margin
        
        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(document truncated)"
            context_parts.append(f"\n## raw document content\n{doc_text}")
        
        return "\n".join(context_parts)
    
    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """Generate an entity summary."""
        lines = []
        
        # Group by type
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)
        
        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)} items)")
            # Use the configured display count and summary length.
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... and {len(type_entities) - display_count} ")
        
        return "\n".join(lines)
    
    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """LLM call with retries, including JSON repair logic"""
        import re
        
        max_attempts = 3
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1)  # lower the temperature on each retry
                    # do not set max_tokens so the LLM can respond freely
                )
                
                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason
                
                # Check whether output was truncated
                if finish_reason == 'length':
                    logger.warning(f"LLM output was truncated (attempt {attempt+1})")
                    content = self._fix_truncated_json(content)
                
                # Try to parse JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parsing failed (attempt {attempt+1}): {str(e)[:80]}")
                    
                    # Try to repair JSON
                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed
                    
                    last_error = e
                    
            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))
        
        raise last_error or Exception("LLM call failed")
    
    def _fix_truncated_json(self, content: str) -> str:
        """Repair truncated JSON"""
        content = content.strip()
        
        # Count unclosed brackets
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # Check for unclosed strings
        if content and content[-1] not in '",}]':
            content += '"'
        
        # Close brackets
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Try to repair config JSON"""
        import re
        
        # Repair truncated output
        content = self._fix_truncated_json(content)
        
        # Extract the JSON fragment
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # Remove newlines inside strings
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s
            
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)
            
            try:
                return json.loads(json_str)
            except:
                # Try removing all control characters
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
        
        return None
    
    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """Generate time configuration"""
        # Use the configured context truncation length
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]
        
        # Calculate the maximum allowed value (90% of total Agents)
        max_agents_allowed = max(1, int(num_entities * 0.9))
        
        prompt = f"""Generate a time simulation configuration based on the following simulation requirement.

{context_truncated}

## Task
Generate time configuration JSON.

### Basic principles (for reference only; adjust based on the event and participating groups):
- The user population is assumed to follow Beijing-time daily routines.
- Almost no activity from 00:00-05:00 (activity multiplier 0.05)
- Activity ramps up from 06:00-08:00 (activity multiplier 0.4)
- Moderate activity from 09:00-18:00 (activity multiplier 0.7)
- Peak activity from 19:00-22:00 (activity multiplier 1.5)
- Activity declines after 23:00 (activity multiplier 0.5)
- Typical pattern: low overnight, rising in the morning, moderate during work hours, peak in the evening
- **Important**：The example values below are only references. Adjust the concrete time ranges based on the event and participant characteristics.
  - For example: student groups may peak at 21:00-23:00; media may stay active all day; official institutions may only be active during work hours.
  - For example: a breaking event may trigger discussion late at night, so `off_peak_hours` can be shortened.

### Return JSON only (no markdown)

Example:
{{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 50,
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "morning_hours": [6, 7, 8],
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    "reasoning": "Reasoning for this event-specific time configuration"
}}

Field notes:
- total_simulation_hours (int): total duration, 24-168 hours; shorter for breaking events, longer for ongoing topics
- minutes_per_round (int): per-round duration, 30-120 minutes; 60 minutes recommended
- agents_per_hour_min (int): minimum active Agents per hour (range: 1-{max_agents_allowed})
- agents_per_hour_max (int): maximum active Agents per hour (range: 1-{max_agents_allowed})
- peak_hours (int array): peak hours, adjusted for the groups involved in the event
- off_peak_hours (int array): off-peak hours, usually late night and early morning
- morning_hours (int array): morning hours
- work_hours (int array): working hours
- reasoning (string): briefly explain why this configuration was chosen"""

        system_prompt = "You are a social media simulation expert. Return pure JSON. The time configuration should follow typical China daily routines."
        
        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Time config LLM generation failed: {e}, using the default config")
            return self._get_default_time_config(num_entities)
    
    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """Get the default time config for typical China daily routines"""
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,  # 1 hour per round to speed up simulated time
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Use the default China routine configuration (1 hour per round)"
        }
    
    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """Parse the time config result and ensure agents_per_hour does not exceed the total Agent count"""
        # Get the raw values
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))
        
        # Validate and adjust to ensure the values do not exceed the total Agent count
        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) exceeds the total Agent count ({num_entities}); corrected")
            agents_per_hour_min = max(1, num_entities // 10)
        
        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) exceeds the total Agent count ({num_entities}); corrected")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)
        
        # Ensure min < max
        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max; corrected to {agents_per_hour_min}")
        
        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),  # default to 1 hour per round
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,  # almost no one active in the early morning
            morning_hours=result.get("morning_hours", [6, 7, 8]),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(range(9, 19))),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )
    
    def _generate_event_config(
        self, 
        context: str, 
        simulation_requirement: str,
        entities: List[EntityNode]
    ) -> Dict[str, Any]:
        """Generate event configuration"""
        
        # Get the list of available entity types for LLM reference
        entity_types_available = list(set(
            e.get_entity_type() or "Unknown" for e in entities
        ))
        
        # List representative entity names for each type
        type_examples = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.name)
        
        type_info = "\n".join([
            f"- {t}: {', '.join(examples)}" 
            for t, examples in type_examples.items()
        ])
        
        # Use the configured context truncation length
        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]
        
        prompt = f"""Generate event configuration based on the following simulation requirement.

Simulation requirement: {simulation_requirement}

{context_truncated}

## Available entity types and examples
{type_info}

## Task
Generate event configuration JSON:
- extract hot-topic keywords
- describe the narrative direction
- design initial post content, and **each post must specify `poster_type`**

**Important**: `poster_type` must be chosen from the available entity types above so each initial post can be assigned to a suitable Agent.
For example: official statements should be posted by Official/University, news by MediaOutlet, and student viewpoints by Student.

Return JSON only (no markdown):
{{
    "hot_topics": ["keyword1", "keyword2", ...],
    "narrative_direction": "<description of narrative direction>",
    "initial_posts": [
        {{"content": "post content", "poster_type": "entity type (must be selected from the available types)"}},
        ...
    ],
    "reasoning": "<brief explanation>"
}}"""

        system_prompt = "You are a narrative analysis expert. Return pure JSON. `poster_type` must match an available entity type exactly."
        
        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Event config LLM generation failed: {e}, using the default config")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "use the default config"
            }
    
    def _parse_event_config(self, result: Dict[str, Any]) -> EventConfig:
        """Parse the event config result"""
        return EventConfig(
            initial_posts=result.get("initial_posts", []),
            scheduled_events=[],
            hot_topics=result.get("hot_topics", []),
            narrative_direction=result.get("narrative_direction", "")
        )
    
    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        Assign suitable poster Agents for initial posts.

        Match each post's `poster_type` to the most suitable `agent_id`.
        """
        if not event_config.initial_posts:
            return event_config
        
        # Build agent indices by entity type
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)
        
        # Type alias map for handling different LLM output variants
        type_aliases = {
            "official": ["official", "university", "governmentagency", "government"],
            "university": ["university", "official"],
            "mediaoutlet": ["mediaoutlet", "media"],
            "student": ["student", "person"],
            "professor": ["professor", "expert", "teacher"],
            "alumni": ["alumni", "person"],
            "organization": ["organization", "ngo", "company", "group"],
            "person": ["person", "student", "alumni"],
        }
        
        # Track used agent indices per type to avoid repeated assignment
        used_indices: Dict[str, int] = {}
        
        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")
            
            # Try to find a matching agent
            matched_agent_id = None
            
            # 1. Direct match
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            else:
                # 2. Alias match
                for alias_key, aliases in type_aliases.items():
                    if poster_type in aliases or alias_key == poster_type:
                        for alias in aliases:
                            if alias in agents_by_type:
                                agents = agents_by_type[alias]
                                idx = used_indices.get(alias, 0) % len(agents)
                                matched_agent_id = agents[idx].agent_id
                                used_indices[alias] = idx + 1
                                break
                    if matched_agent_id is not None:
                        break
            
            # 3. If still not found, use the most influential agent
            if matched_agent_id is None:
                logger.warning(f"No matching Agent found for type '{poster_type}'; using the most influential Agent")
                if agent_configs:
                    # Sort by influence and pick the highest
                    sorted_agents = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)
                    matched_agent_id = sorted_agents[0].agent_id
                else:
                    matched_agent_id = 0
            
            updated_posts.append({
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id
            })
            
            logger.info(f"Initial post assignment: poster_type='{poster_type}' -> agent_id={matched_agent_id}")
        
        event_config.initial_posts = updated_posts
        return event_config
    
    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """Generate Agent configurations in batches"""
        
        # Build entity information using the configured summary length
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })
        
        prompt = f"""Generate social media activity configuration for each entity using the information below.

Simulation requirement: {simulation_requirement}

## Entity list
```json
{json.dumps(entity_list, ensure_ascii=False, indent=2)}
```

## Task
Generate an activity configuration for each entity. Keep in mind:
- **Time behavior should follow typical China routines**: almost no activity from 00:00-05:00, peak activity from 19:00-22:00
- **Official institutions** (University/GovernmentAgency): low activity (0.1-0.3), active during work hours (9-17), slow response (60-240 min), high influence (2.5-3.0)
- **Media** (MediaOutlet): medium activity (0.4-0.6), active all day (8-23), fast response (5-30 min), high influence (2.0-2.5)
- **Individuals** (Student/Person/Alumni): high activity (0.6-0.9), mainly active in the evening (18-23), fast response (1-15 min), lower influence (0.8-1.2)
- **Public figures / experts**: medium activity (0.4-0.6), medium-high influence (1.5-2.0)

Return JSON only (no markdown):
{{
    "agent_configs": [
        {{
            "agent_id": <must match the input exactly>,
            "activity_level": <0.0-1.0>,
            "posts_per_hour": <posting frequency>,
            "comments_per_hour": <comment frequency>,
            "active_hours": [<active hour list, considering typical China routines>],
            "response_delay_min": <minimum response delay in minutes>,
            "response_delay_max": <maximum response delay in minutes>,
            "sentiment_bias": <-1.0 to 1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <influence weight>
        }},
        ...
    ]
}}"""

        system_prompt = "You are a social media behavior analysis expert. Return pure JSON. The configuration should follow typical China daily routines."
        
        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
            llm_configs = {cfg["agent_id"]: cfg for cfg in result.get("agent_configs", [])}
        except Exception as e:
            logger.warning(f"Agent config batch LLM generation failed: {e}, falling back to rule-based generation")
            llm_configs = {}
        
        # Build the AgentActivityConfig object.
        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})
            
            # Fall back to rule-based generation if the LLM does not return a config.
            if not cfg:
                cfg = self._generate_agent_config_by_rule(entity)
            
            config = AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=entity.uuid,
                entity_name=entity.name,
                entity_type=entity.get_entity_type() or "Unknown",
                activity_level=cfg.get("activity_level", 0.5),
                posts_per_hour=cfg.get("posts_per_hour", 0.5),
                comments_per_hour=cfg.get("comments_per_hour", 1.0),
                active_hours=cfg.get("active_hours", list(range(9, 23))),
                response_delay_min=cfg.get("response_delay_min", 5),
                response_delay_max=cfg.get("response_delay_max", 60),
                sentiment_bias=cfg.get("sentiment_bias", 0.0),
                stance=cfg.get("stance", "neutral"),
                influence_weight=cfg.get("influence_weight", 1.0)
            )
            configs.append(config)
        
        return configs
    
    def _generate_agent_config_by_rule(self, entity: EntityNode) -> Dict[str, Any]:
        """Generate a single Agent config with rule-based defaults aligned to common China schedules."""
        entity_type = (entity.get_entity_type() or "Unknown").lower()
        
        if entity_type in ["university", "governmentagency", "ngo"]:
            # Official institutions: active during work hours, low frequency, high influence.
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # Media: active throughout the day, medium frequency, high influence.
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),  # 7:00-23:59
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # Experts / professors: active during work hours and evenings, medium frequency.
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),  # 8:00-21:59
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # Students: mainly active in the evening, high frequency.
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Morning + evening.
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # Alumni: mainly active in the evening.
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],  # Lunch break + evening.
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # General public: evening peak.
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Daytime + evening.
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
    
