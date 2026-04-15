"""
Report Agent service.
Uses LangChain + Zep to generate simulation reports with a ReACT-style workflow.

Capabilities:
1. Generate reports from the simulation requirement and Zep graph data
2. Plan the report structure first, then generate sections incrementally
3. Use multi-step ReACT reasoning and reflection for each section
4. Support user conversation while invoking retrieval tools as needed
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .zep_tools import (
    ZepToolsService, 
    SearchResult, 
    InsightForgeResult, 
    PanoramaResult,
    InterviewResult
)

logger = get_logger('mirofish.report_agent')


class ReportLogger:
    """
    Detailed logger for the Report Agent.

    Writes `agent_log.jsonl` into the report folder and records each detailed step.
    Every line is one complete JSON object with timestamps, action type, payload, and so on.
    """
    
    def __init__(self, report_id: str):
        """
        Initialize the logger.
        
        Args:
            report_id: Report ID used to determine the log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """Ensure the parent directory for the log file exists."""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_elapsed_time(self) -> float:
        """Return elapsed time in seconds since the logger started."""
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        Record one log entry.
        
        Args:
            action: Action type such as `start`, `tool_call`, `llm_response`, or `section_complete`
            stage: Current stage such as `planning`, `generating`, or `completed`
            details: Detailed payload dictionary, not truncated
            section_title: Current section title, optional
            section_index: Current section index, optional
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # Append to the JSONL file.
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """Record report generation start."""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": "Report generation task started"
            }
        )
    
    def log_planning_start(self):
        """Record outline planning start."""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": "Starting report outline planning"}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """Record context collected during planning."""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": "Collected simulation context information",
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """Record outline planning completion."""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": "Outline planning completed",
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """Record section generation start."""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": f"Starting section generation: {section_title}"}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """Record a ReACT thought step."""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": f"ReACT thought iteration {iteration}"
            }
        )
    
    def log_tool_call(
        self, 
        section_title: str, 
        section_index: int,
        tool_name: str, 
        parameters: Dict[str, Any],
        iteration: int
    ):
        """Record a tool call."""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": f"Called tool: {tool_name}"
            }
        )
    
    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """Record the full tool result without truncation."""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # Full result, not truncated.
                "result_length": len(result),
                "message": f"Tool {tool_name} returned a result"
            }
        )
    
    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """Record the full LLM response without truncation."""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # Full response, not truncated.
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": f"LLM response (tool calls: {has_tool_calls}, final answer: {has_final_answer})"
            }
        )
    
    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """Record that section content generation completed, without marking the whole section complete."""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # Full content, not truncated.
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": f"Section content generated for {section_title}"
            }
        )
    
    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        Record final completion of a section.

        The frontend can listen for this log entry to know a section is truly finished and retrieve the full content.
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": f"Section completed: {section_title}"
            }
        )
    
    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """Record report generation completion."""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": "Report generation completed"
            }
        )
    
    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """Record an error."""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": f"Error occurred: {error_message}"
            }
        )


class ReportConsoleLogger:
    """
    Console-style logger for the Report Agent.

    Writes console-style log lines such as INFO and WARNING into `console_log.txt` inside the report folder.
    Unlike `agent_log.jsonl`, these are plain-text console logs.
    """
    
    def __init__(self, report_id: str):
        """
        Initialize the console logger.
        
        Args:
            report_id: Report ID used to determine the log file path
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """Ensure the parent directory for the log file exists."""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """Create and attach a file handler so logs are also written to disk."""
        import logging
        
        # Create the file handler.
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        
        # Use the same compact format as the console.
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        
        # Attach to the relevant report-related loggers.
        loggers_to_attach = [
            'mirofish.report_agent',
            'mirofish.zep_tools',
        ]
        
        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # Avoid duplicate attachment.
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)
    
    def close(self):
        """Close the file handler and detach it from the loggers."""
        import logging
        
        if self._file_handler:
            loggers_to_detach = [
                'mirofish.report_agent',
                'mirofish.zep_tools',
            ]
            
            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)
            
            self._file_handler.close()
            self._file_handler = None
    
    def __del__(self):
        """Ensure the file handler is closed on destruction."""
        self.close()


class ReportStatus(str, Enum):
    """Report status."""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """Report section."""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """Convert to Markdown."""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """Report outline."""
    title: str
    summary: str
    sections: List[ReportSection]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }
    
    def to_markdown(self) -> str:
        """Convert to Markdown."""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """Full report."""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Prompt template constants.
# ═══════════════════════════════════════════════════════════════

# ── Tool descriptions ──

TOOL_DESC_INSIGHT_FORGE = """\
[InsightForge - Deep Retrieval]
This is the most powerful retrieval function, designed for deep analysis. It:
1. Automatically breaks your question into sub-questions
2. Retrieves information from multiple angles in the simulation graph
3. Combines semantic search, entity analysis, and relationship-chain tracing
4. Returns the richest and deepest retrieval output

[Use Cases]
- You need deep analysis of a topic
- You need to understand multiple facets of an event
- You need rich source material for a report section

[Returns]
- Relevant raw facts that can be quoted
- Core entity insights
- Relationship-chain analysis"""

TOOL_DESC_PANORAMA_SEARCH = """\
[Panorama Search - Full View]
This tool gives a complete view of simulation results and is especially useful for understanding how an event evolved. It:
1. Fetches all relevant nodes and relationships
2. Distinguishes active facts from historical or expired ones
3. Helps you understand how the public narrative evolved

[Use Cases]
- You need the full development timeline of an event
- You need to compare different stages of the narrative
- You need broad entity and relationship coverage

[Returns]
- Active facts from the latest simulation state
- Historical or expired facts that show the evolution
- All involved entities"""

TOOL_DESC_QUICK_SEARCH = """\
[Quick Search - Fast Retrieval]
Lightweight retrieval for simple, direct information lookup.

[Use Cases]
- You need to quickly find one specific piece of information
- You need to verify a fact
- You need basic information retrieval

[Returns]
- A list of facts most relevant to the query"""

TOOL_DESC_INTERVIEW_AGENTS = """\
[Deep Interview - Live Agent Interviews Across Two Platforms]
Call the OASIS simulation interview API to interview running simulated Agents.
This is not an LLM roleplay. It invokes the real interview interface and gets the Agents' original answers.
By default it interviews on both Twitter and Reddit to gather a fuller set of viewpoints.

Workflow:
1. Read the generated profile files
2. Select the Agents most relevant to the interview topic
3. Generate interview questions automatically
4. Call `/api/simulation/interview/batch` on both platforms
5. Combine the results into a multi-perspective analysis

[Use Cases]
- You need to understand how different roles view the event
- You need to collect positions and opinions from multiple sides
- You need real responses from simulated Agents
- You want the report to include interview-style excerpts

[Returns]
- Identity information for interviewed Agents
- Interview answers from Twitter and Reddit
- Key quotes that can be cited directly
- A comparison summary of viewpoints

[Important] The OASIS simulation environment must still be running for this tool to work."""

# ── Outline planning prompt ──

PLAN_SYSTEM_PROMPT = """\
You are an expert writer of future-prediction reports, with a god's-eye view of the simulated world. You can observe every Agent's behavior, speech, and interactions.

[Core Idea]
We built a simulated world and injected a specific `Simulation requirement` into it as the variable. The resulting evolution of the world is a prediction of what may happen in the future. You are not looking at "experimental data". You are observing a "preview of the future".

[Your Task]
Write a future-prediction report that answers:
1. Under the configured condition, what happened in the future?
2. How did different kinds of Agents react and act?
3. What trends and risks does the simulation reveal?

[Report Positioning]
- This is a future-prediction report based on simulation: "if this happens, what does the future look like?"
- Focus on predictive results: event trajectory, group reactions, emergent phenomena, and potential risks
- Agent behavior in the simulated world is treated as a prediction of future human behavior
- This is not an analysis of current real-world conditions
- This is not a generic public-opinion overview

[Section Count]
- Minimum 2 sections, maximum 5 sections
- No subsections are needed; each section should stand on its own
- Keep the content concise and focused on key predictive findings
- Design the section structure yourself based on the results

Return the report outline as JSON in the following format:
{
    "title": "Report title",
    "summary": "Report summary, one sentence capturing the core predictive finding",
    "sections": [
        {
            "title": "Section title",
            "description": "Description of the section content"
        }
    ]
}

Remember: `sections` must contain at least 2 items and at most 5."""

PLAN_USER_PROMPT_TEMPLATE = """\
[Prediction Scenario]
Injected simulation variable (`Simulation requirement`): {simulation_requirement}

[World Size]
- Number of simulated entities: {total_nodes}
- Number of generated relationships: {total_edges}
- Entity type distribution: {entity_types}
- Active Agent count: {total_entities}

[Sample Future Facts Predicted by the Simulation]
{related_facts_json}

Review this future preview from a god's-eye perspective:
1. Under the configured condition, what state did the future take on?
2. How did different groups of Agents react and act?
3. What future trends are worth attention?

Design the most appropriate section structure based on the predictive results.

Reminder: the report must contain between 2 and 5 sections, and the content should stay focused on the core predictive findings."""

# ── Section generation prompt ──

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert writer of future-prediction reports and you are writing one section of the report.

Report title: {report_title}
Report summary: {report_summary}
Prediction scenario (`Simulation requirement`): {simulation_requirement}

Current section to write: {section_title}

═══════════════════════════════════════════════════════════════
[Core Idea]
═══════════════════════════════════════════════════════════════

The simulated world is a preview of the future. We injected a specific condition (`Simulation requirement`) into the world, and the behavior and interactions of its Agents are treated as predictions of future human behavior.

Your task is to:
- Reveal what happened in the future under the configured condition
- Predict how different kinds of Agents reacted and acted
- Identify important future trends, risks, and opportunities

Do not write this as an analysis of current real-world conditions.
Focus on "what the future looks like" because the simulation result is the predicted future.

═══════════════════════════════════════════════════════════════
[Most Important Rules - must be followed]
═══════════════════════════════════════════════════════════════

1. You must call tools to observe the simulated world.
   - You are observing this future preview from a god's-eye perspective
   - All report content must come from events and Agent behavior that actually appeared in the simulation
   - Do not use your own outside knowledge to write the report
   - Call tools at least 3 times and at most 5 times for each section

2. You must quote original Agent statements and behavior.
   - Agent speech and behavior are predictions of future human behavior
   - Use quoted evidence in the report, for example:
     > "One group would say: original content..."
   - These quotes are core evidence for the prediction

3. Keep language consistent.
   - Tool outputs may contain English or mixed-language text
   - If the simulation requirement and source material are in Chinese, the report must be fully written in Chinese
   - If you quote English or mixed-language tool output, translate it into fluent Chinese before writing it into the report
   - Preserve the original meaning and keep the wording natural
   - This rule applies to both body text and quote blocks

4. Present the predictive result faithfully.
   - Report content must reflect the future-representing simulation output
   - Do not add information that does not exist in the simulation
   - If some area is under-supported, say so directly

═══════════════════════════════════════════════════════════════
[Formatting Rules - extremely important]
═══════════════════════════════════════════════════════════════

[One Section = the smallest output unit]
- Each section is the smallest report block
- Do not use any Markdown headings inside the section (`#`, `##`, `###`, `####`, etc.)
- Do not repeat the section title at the start of the content
- The system adds the section title automatically, so you should write body content only
- Use **bold**, paragraph breaks, quotes, and lists to organize the content, but do not use headings

[Correct Example]
```
This section analyzes the spread of the narrative around the event. Through deep analysis of the simulated data, we found...

**Initial ignition stage**

The first platform to ignite the narrative served as the main source of initial distribution:

> "The first platform contributed 68% of the initial volume..."

**Emotion amplification stage**

The short-video platform further amplified the impact:

- Strong visual impact
- High emotional resonance
```

[Incorrect Example]
```
## Executive Summary          ← Wrong: do not add any heading
### Stage One                ← Wrong: do not use `###` subsections
#### 1.1 Detailed Analysis   ← Wrong: do not use `####` headings

This section analyzes...
```

═══════════════════════════════════════════════════════════════
[Available Retrieval Tools] (call them 3-5 times per section)
═══════════════════════════════════════════════════════════════

{tools_description}

[Tool Usage Guidance - mix tools instead of relying on only one]
- `insight_forge`: deep insight analysis with automatic decomposition and multi-angle fact retrieval
- `panorama_search`: wide-angle retrieval for the whole event, timeline, and evolution
- `quick_search`: fast verification of one specific point
- `interview_agents`: interview simulated Agents for first-person viewpoints and reactions

═══════════════════════════════════════════════════════════════
[Workflow]
═══════════════════════════════════════════════════════════════

Each response can do only one of the following, never both:

Option A - call a tool:
Output your thought, then call one tool using this format:
<tool_call>
{{"name": "tool_name", "parameters": {{"parameter_name": "parameter_value"}}}}
</tool_call>
The system will execute the tool and return the result. You do not need to and must not invent the tool result yourself.

Option B - output final content:
When you have enough information, output the section beginning with `Final Answer:`.

Strictly forbidden:
- Do not include both a tool call and `Final Answer` in the same reply
- Do not fabricate tool output or observations; all tool results are injected by the system
- Call at most one tool per reply

═══════════════════════════════════════════════════════════════
[Section Content Requirements]
═══════════════════════════════════════════════════════════════

1. The content must be grounded in simulated data retrieved through tools
2. Quote original content heavily enough to demonstrate the simulation output
3. Use Markdown, but never use headings:
   - Use **bold** for emphasis instead of subheadings
   - Use lists such as `-` or `1. 2. 3.` to organize points
   - Separate paragraphs with blank lines
   - Never use `#`, `##`, `###`, or `####`
4. Quote formatting rule: quotes must be in their own paragraphs, with blank lines before and after them

   Correct format:
   ```
   The institutional response was widely seen as lacking substance.

   > "The institution's response looked rigid and slow in a fast-changing social-media environment."

   This assessment reflects broad dissatisfaction.
   ```

   Incorrect format:
   ```
   The institutional response lacked substance. > "The response model..." This assessment reflects...
   ```
5. Keep the section logically consistent with the rest of the report
6. Avoid repetition by reading the completed section content provided below
7. Again: do not add any headings. Use **bold** instead of subheadings."""

SECTION_USER_PROMPT_TEMPLATE = """\
Completed section content (read carefully to avoid repetition):
{previous_content}

═══════════════════════════════════════════════════════════════
[Current Task] Write section: {section_title}
═══════════════════════════════════════════════════════════════

[Important Reminders]
1. Read the completed section content above carefully and avoid repeating the same information
2. Before you start writing, you must call tools to retrieve simulation data
3. Mix different tools instead of relying on only one
4. All report content must come from retrieved results, not your own knowledge

[Formatting Warnings - must be followed]
- Do not write any headings (`#`, `##`, `###`, `####`, etc.)
- Do not start with "{section_title}"
- The section title is added automatically by the system
- Write body content directly, and use **bold** instead of subheadings

Please begin:
1. First think about what information this section needs
2. Then call tools to retrieve simulation data
3. Once you have enough information, output `Final Answer:` followed by pure body text with no headings"""

# ── ReACT loop message templates ──

REACT_OBSERVATION_TEMPLATE = """\
Observation (retrieved result):

═══ Tool {tool_name} returned ═══
{result}

═══════════════════════════════════════════════════════════════
Tool calls so far: {tool_calls_count}/{max_tool_calls} (used: {used_tools_str}){unused_hint}
- If the information is sufficient, output the section beginning with `Final Answer:` and quote the evidence above
- If you need more information, call one more tool
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "Note: you have called tools only {tool_calls_count} times; at least {min_tool_calls} calls are required. "
    "Call another tool to gather more simulation data before outputting `Final Answer:`.{unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "You have called tools only {tool_calls_count} times; at least {min_tool_calls} are required. "
    "Please call a tool to retrieve simulation data.{unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "You have reached the tool-call limit ({tool_calls_count}/{max_tool_calls}) and cannot call more tools. "
    'Use the information already gathered and output the section starting with "Final Answer:".'
)

REACT_UNUSED_TOOLS_HINT = "\nTip: you have not used these tools yet: {unused_list}. Consider using different tools to gather information from multiple angles."

REACT_FORCE_FINAL_MSG = "The tool-call limit has been reached. Please output `Final Answer:` directly and generate the section content."

# ── Chat prompt ──

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
You are a concise and efficient simulation prediction assistant.

[Background]
Prediction scenario: {simulation_requirement}

[Existing analysis report]
{report_content}

[Rules]
1. Prefer answering based on the existing report content above.
2. Answer directly and avoid long internal reasoning.
3. Only call tools when the report content is insufficient to answer.
4. Keep the answer concise, clear, and well-structured.

[Available tools]
Only use them when needed, and at most 1-2 times.
{tools_description}

[Tool call format]
<tool_call>
{{"name": "tool_name", "parameters": {{"param_name": "param_value"}}}}
</tool_call>

[Answer style]
- Be concise and direct
- Use `>` to quote key content when helpful
- Lead with the conclusion, then explain briefly"""

CHAT_OBSERVATION_SUFFIX = "\n\nPlease answer the question concisely."


# ═══════════════════════════════════════════════════════════════
# ReportAgent main class
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent for simulation report generation.

    Uses the ReACT (Reasoning + Acting) pattern:
    1. Planning stage: analyze the simulation requirement and plan the report outline
    2. Generation stage: generate each section, calling tools when needed
    3. Reflection stage: check content completeness and accuracy
    """
    
    # Maximum tool calls per section
    MAX_TOOL_CALLS_PER_SECTION = 5
    
    # Maximum reflection rounds
    MAX_REFLECTION_ROUNDS = 3
    
    # Maximum tool calls in chat mode
    MAX_TOOL_CALLS_PER_CHAT = 2
    
    def __init__(
        self, 
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None
    ):
        """
        Initialize the Report Agent
        
        Args:
            graph_id: graph ID
            simulation_id: simulation ID
            simulation_requirement: simulation requirement description
            llm_client: optional LLM client
            zep_tools: optional Zep tools service
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement
        
        self.llm = llm_client or LLMClient()
        self.zep_tools = zep_tools or ZepToolsService()
        
        # Tool definitions
        self.tools = self._define_tools()
        
        # Log recorder, initialized in generate_report
        self.report_logger: Optional[ReportLogger] = None
        # Console log recorder, initialized in generate_report
        self.console_logger: Optional[ReportConsoleLogger] = None
        
        logger.info(f"ReportAgent initialized: graph_id={graph_id}, simulation_id={simulation_id}")
    
    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """Define available tools"""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "question or topic to analyze deeply",
                    "report_context": "current report-section context (optional, helps generate more precise sub-questions)"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "search query used for relevance sorting",
                    "include_expired": "whether to include expired/historical content (default: True)"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "search query string",
                    "limit": "number of results to return (optional, default: 10)"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "interview topic or requirement description",
                    "max_agents": "maximum number of Agents to interview (optional, default: 5, max: 10)"
                }
            }
        }
    
    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        Execute a tool call
        
        Args:
            tool_name: tool name
            parameters: tool parameters
            report_context: report context for InsightForge
            
        Returns:
            tool execution result as text
        """
        logger.info(f"Executing tool: {tool_name}, parameters: {parameters}")
        
        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                return result.to_text()
            
            elif tool_name == "panorama_search":
                # Panorama search - get the full picture
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()
            
            elif tool_name == "quick_search":
                # Quick search - fast retrieval
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()
            
            elif tool_name == "interview_agents":
                # Deep interview - call the real OASIS interview API to get Agent responses
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 10)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                return result.to_text()
            
            # ========== Backward-compatible legacy tools (internally redirected) ==========
            
            elif tool_name == "search_graph":
                # Redirect to quick_search
                logger.info("search_graph redirected to quick_search")
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                # Redirect to insight_forge because it is more capable
                logger.info("get_simulation_context redirected to insight_forge")
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                return f"Unknown tool: {tool_name}. Use one of: insight_forge, panorama_search, quick_search"
                
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}, error: {str(e)}")
            return f"Tool execution failed: {str(e)}"
    
    # Valid tool names, used when validating fallback bare-JSON parsing
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        Parse tool calls from an LLM response.

        Supported formats, in priority order:
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. Bare JSON where the whole response, or one line, is a tool-call object
        """
        tool_calls = []

        # Format 1: XML-style wrapper (preferred)
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # Format 2: fallback bare JSON with no <tool_call> wrapper
        # Only try this if format 1 did not match, to avoid false positives in prose
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # The response may contain prose plus bare JSON, so try extracting the last JSON object
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """Validate that parsed JSON is a legal tool call"""
        # Supports both {"name": ..., "parameters": ...} and {"tool": ..., "params": ...}
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # Normalize keys to name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """Generate tool description text"""
        desc_parts = ["Available tools:"]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  Parameters: {params_desc}")
        return "\n".join(desc_parts)
    
    def plan_outline(
        self, 
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        Plan the report outline.

        Uses the LLM to analyze the simulation requirement and plan the report structure.
        
        Args:
            progress_callback: progress callback function
            
        Returns:
            ReportOutline: report outline
        """
        logger.info("Starting report outline planning...")
        
        if progress_callback:
            progress_callback("planning", 0, "Analyzing the simulation requirement...")
        
        # Fetch simulation context first
        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )
        
        if progress_callback:
            progress_callback("planning", 30, "Generating the report outline...")
        
        system_prompt = PLAN_SYSTEM_PROMPT
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            if progress_callback:
                progress_callback("planning", 80, "Parsing the outline structure...")
            
            # Parse the outline
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))
            
            outline = ReportOutline(
                title=response.get("title", "Simulation Analysis Report"),
                summary=response.get("summary", ""),
                sections=sections
            )
            
            if progress_callback:
                progress_callback("planning", 100, "Outline planning completed")
            
            logger.info(f"Outline planning completed: {len(sections)} sections")
            return outline
            
        except Exception as e:
            logger.error(f"Outline planning failed: {str(e)}")
            # Return a default outline with 3 sections as fallback
            return ReportOutline(
                title="Future Prediction Report",
                summary="Future trend and risk analysis based on the simulation",
                sections=[
                    ReportSection(title="Prediction Scenario and Key Findings"),
                    ReportSection(title="Behavioral Forecast Analysis"),
                    ReportSection(title="Trend Outlook and Risk Notes")
                ]
            )
    
    def _generate_section_react(
        self, 
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        Generate one section using the ReACT pattern.

        ReACT loop:
        1. Thought - determine what information is needed
        2. Action - call a tool
        3. Observation - analyze the tool result
        4. Repeat until enough information is gathered or the limit is reached
        5. Final Answer - produce the section content
        
        Args:
            section: section to generate
            outline: full outline
            previous_sections: previous section content for continuity
            progress_callback: progress callback
            section_index: section index for logging
            
        Returns:
            section content in Markdown
        """
        logger.info(f"Generating section with ReACT: {section.title}")
        
        # Record section-start log.
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)
        
        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )

        # Build the user prompt - pass up to 4000 characters from each completed section
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                # Each section is capped at 4000 characters
                truncated = sec[:4000] + "..." if len(sec) > 4000 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "(This is the first section)"
        
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # ReACT loop
        tool_calls_count = 0
        max_iterations = 5  # maximum number of iterations
        min_tool_calls = 3  # minimum number of tool calls
        conflict_retries = 0  # consecutive conflicts where tool calls and Final Answer appear together
        used_tools = set()  # record the names of tools that have already been called
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # Report context, used for InsightForge sub-question generation
        report_context = f"Section title: {section.title}\nSimulation requirement: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    f"Retrieving deeply and drafting ({tool_calls_count}/{self.MAX_TOOL_CALLS_PER_SECTION})"
                )
            
            # Call the LLM
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=4096
            )

            # Check whether the LLM returned None (API error or empty content)
            if response is None:
                logger.warning(f"Section {section.title}  iteration {iteration + 1}  : LLM returned None")
                # If iterations remain, add a message and retry
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "(empty response)"})
                    messages.append({"role": "user", "content": "Please continue generating content."})
                    continue
                # If the final iteration also returns None, break out and force completion
                break

            logger.debug(f"LLM response: {response[:200]}...")

            # Parse once and reuse the result
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # -- Conflict handling: the LLM output both tool calls and Final Answer --
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    f"Section {section.title}, iteration {iteration+1}: "
                    f"the LLM produced both a tool call and Final Answer (conflict retry {conflict_retries})"
                )

                if conflict_retries <= 2:
                    # First two times: discard the response and ask the LLM to reply again
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[Format error] Your response contained both a tool call and Final Answer, which is not allowed.\n"
                            "Each response may do only one of the following:\n"
                            "- Call one tool (output a single <tool_call> block and do not write Final Answer)\n"
                            "- Output the final content (start with 'Final Answer:' and do not include <tool_call>)\n"
                            "Reply again and do only one of them."
                        ),
                    })
                    continue
                else:
                    # Third time: degrade gracefully, truncate to the first tool call, and force execution
                    logger.warning(
                        f"Section {section.title}: {conflict_retries} consecutive conflicts, "
                        "degrading to truncating and executing only the first tool call"
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # Record the LLM response log
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # -- Case 1: the LLM produced Final Answer --
            if has_final_answer:
                # Tool usage is insufficient; reject and request more tool calls
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"(These tools have not been used yet. Consider using: {', '.join(unused_tools)} )" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # Finish normally
                final_answer = response.split("Final Answer:")[-1].strip()
                logger.info(f"Section {section.title} generated successfully (tool calls: {tool_calls_count})")

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # -- Case 2: the LLM is attempting to call tools --
            if has_tool_calls:
                # Tool budget exhausted -> tell the model clearly and require Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # Execute only the first tool call
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(f"LLM attempted to call {len(tool_calls)} tools; only the first was executed: {call['name']}")

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # Build the unused-tool hint
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list="、".join(unused_tools))

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # -- Case 3: neither tool calls nor Final Answer were produced --
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                # Tool usage is still insufficient; recommend unused tools
                unused_tools = all_tools - used_tools
                unused_hint = f"(These tools have not been used yet. Consider using: {', '.join(unused_tools)} )" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # Tool usage is sufficient, but the LLM produced content without the "Final Answer:" prefix
            # Treat the content directly as the final answer instead of looping further
            logger.info(f"Section {section.title} had no 'Final Answer:' prefix; using the raw LLM output as final content (tool calls: {tool_calls_count})")
            final_answer = response.strip()

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # Maximum iteration count reached; force-generate the final content
        logger.warning(f"Section {section.title} reached the maximum iteration count; forcing generation")
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})
        
        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            max_tokens=4096
        )

        # Check whether the LLM returned None during forced completion
        if response is None:
            logger.error(f"Section {section.title} LLM returned None during forced completion; using the default error message")
            final_answer = "Section generation failed: the LLM returned an empty response. Please retry later."
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response
        
        # Record the section-content completion log
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )
        
        return final_answer
    
    def generate_report(
        self, 
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        Generate the full report with real-time section-by-section output.
        
        Save each section to disk as soon as it is generated; no need to wait for the full report.
        File structure:
        reports/{report_id}/
            meta.json       - report metadata
            outline.json    - report outline
            progress.json   - generation progress
            section_01.md   - section 1
            section_02.md   - section 2
            ...
            full_report.md  - full report
        
        Args:
            progress_callback: progress callback function (stage, progress, message)
            report_id: Optional report ID; auto-generated when omitted
            
        Returns:
            Report: full report
        """
        import uuid
        
        # Auto-generate report_id if one was not provided
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        # List of completed section titles, used for progress tracking.
        completed_section_titles = []
        
        try:
            # Initialization: create the report folder and save the initial state
            ReportManager._ensure_report_folder(report_id)
            
            # Initialize the structured logger (`agent_log.jsonl`).
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # Initialize the console logger (`console_log.txt`).
            self.console_logger = ReportConsoleLogger(report_id)
            
            ReportManager.update_progress(
                report_id, "pending", 0, "Initializing report...",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            # Stage 1: plan the outline
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, "Starting report outline planning...",
                completed_sections=[]
            )
            
            # Record the planning-start log
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, "Starting report outline planning...")
            
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg: 
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline
            
            # Record the planning-complete log
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # Save the outline to file
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, f"Outline planning completed with {len(outline.sections)} sections",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(f"Outline saved to file: {report_id}/outline.json")
            
            # Stage 2: generate sections one by one and save them incrementally.
            report.status = ReportStatus.GENERATING
            
            total_sections = len(outline.sections)
            generated_sections = []  # save content for later context
            
            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # Update progress
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    f"Generating section: {section.title} ({section_num}/{total_sections})",
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )
                
                if progress_callback:
                    progress_callback(
                        "generating", 
                        base_progress, 
                        f"Generating section: {section.title} ({section_num}/{total_sections})"
                    )
                
                # Generate the main section content
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage, 
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )
                
                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # Save the section
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # Record the section-complete log
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(f"Section saved: {report_id}/section_{section_num:02d}.md")
                
                # Update progress
                ReportManager.update_progress(
                    report_id, "generating", 
                    base_progress + int(70 / total_sections),
                    f"Section {section.title} completed",
                    current_section=None,
                    completed_sections=completed_section_titles
                )
            
            # Stage 3: assemble the full report.
            if progress_callback:
                progress_callback("generating", 95, "Assembling full report...")
            
            ReportManager.update_progress(
                report_id, "generating", 95, "Assembling full report...",
                completed_sections=completed_section_titles
            )
            
            # Use ReportManager to assemble the full report.
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            # Compute total elapsed time
            total_time_seconds = (datetime.now() - start_time).total_seconds()
            
            # Record the report-complete log
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )
            
            # Save the final report
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, "Report generation completed",
                completed_sections=completed_section_titles
            )
            
            if progress_callback:
                progress_callback("completed", 100, "Report generation completed")
            
            logger.info(f"Report generation completed: {report_id}")
            
            # Close the console log recorder
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
            
        except Exception as e:
            logger.error(f"Report generation failed: {str(e)}")
            report.status = ReportStatus.FAILED
            report.error = str(e)
            
            # Record the error log
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # Save the failed state
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, f"Report generation failed: {str(e)}",
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # ignore errors while saving the failed state
            
            # Close the console log recorder
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
    
    def chat(
        self, 
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Chat with the Report Agent
        
        During chat, the Agent may call retrieval tools autonomously to answer questions.
        
        Args:
            message: user message
            chat_history: chat history
            
        Returns:
            {
                "response": "Agent response",
                "tool_calls": [list of called tools],
                "sources": [sources]
            }
        """
        logger.info(f"Report Agent chat: {message[:50]}...")
        
        chat_history = chat_history or []
        
        # Get generated report content
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # Limit report length to avoid excessive context
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [report content truncated] ..."
        except Exception as e:
            logger.warning(f"Failed to get report content: {e}")
        
        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "(no report yet)",
            tools_description=self._get_tools_description(),
        )

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add chat history
        for h in chat_history[-10:]:  # limit history length
            messages.append(h)
        
        # Add the user message.
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # Simplified ReACT loop.
        tool_calls_made = []
        max_iterations = 2  # reduce iteration count
        
        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )
            
            # Parse tool calls
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # No tool calls; return the response directly
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # Execute tool calls, subject to limits.
            tool_results = []
            for call in tool_calls[:1]:  # execute at most 1 tool call per round
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # limit result length
                })
                tool_calls_made.append(call)
            
            # Add tool results to the message list
            messages.append({"role": "assistant", "content": response})
            observation = "\n".join([f"[{r['tool']} result]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # Maximum iterations reached; fetch the final response
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )
        
        # Clean the response
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    Report manager.

    Responsible for persistent storage and retrieval of reports.

    File structure for section-by-section output:
    reports/
      {report_id}/
        meta.json          - report metadata and status
        outline.json       - report outline
        progress.json      - generation progress
        section_01.md      - section 1
        section_02.md      - section 2
        ...
        full_report.md     - full report
    """
    
    # Root directory for report storage.
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """Ensure the report root directory exists."""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """Get the report folder path."""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """Ensure the report folder exists and return its path."""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """Get the report metadata file path."""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """Get the full-report Markdown file path."""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """Get the outline file path."""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """Get the progress file path."""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """Get the section Markdown file path."""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """Get the Agent log file path."""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """Get the console log file path."""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Get console log content.

        These are the plain-text console logs emitted during report generation,
        such as INFO and WARNING lines, and they differ from the structured `agent_log.jsonl`.
        
        Args:
            report_id: Report ID
            from_line: Start reading from this line for incremental fetching; `0` means from the beginning
            
        Returns:
            {
                "logs": [list of log lines],
                "total_lines": total line count,
                "from_line": starting line number,
                "has_more": whether more logs remain
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # Keep the raw log line but remove the trailing newline.
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Reached the end.
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        Get the complete console logs in one call
        
        Args:
            report_id: Report ID
            
        Returns:
            Log line list
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Get Agent log content.
        
        Args:
            report_id: Report ID
            from_line: Start reading from this line for incremental fetching; `0` means from the beginning
            
        Returns:
            {
                "logs": [list of log entries],
                "total_lines": total line count,
                "from_line": starting line number,
                "has_more": whether more logs remain
            }
        """
        log_path = cls._get_agent_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # Skip lines that fail to parse.
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Reached the end.
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Get the full Agent log in one call.
        
        Args:
            report_id: Report ID
            
        Returns:
            Log entry list
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        Save the report outline.

        Call this immediately after the planning stage completes.
        """
        cls._ensure_report_folder(report_id)
        
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"Outline saved: {report_id}")
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        Save one section.

        Call this immediately after each section is generated to support incremental output.

        Args:
            report_id: Report ID
            section_index: Section index, starting at 1
            section: Section object

        Returns:
            Saved file path
        """
        cls._ensure_report_folder(report_id)

        # Build section Markdown content and clean duplicate headings if needed.
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # Save the file.
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"Section saved: {report_id}/{file_suffix}")
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        Clean section content.

        1. Remove heading lines at the beginning if they duplicate the section title
        2. Convert all headings at level `###` or deeper into bold text
        
        Args:
            content: Raw content
            section_title: Section title
            
        Returns:
            Cleaned content
        """
        import re
        
        if not content:
            return content
        
        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Check whether the line is a Markdown heading.
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # Detect headings that duplicate the section title within the first five lines.
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # Convert all heading levels to bold text.
                # The system adds the section title, so no headings should remain in the content.
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # Add a blank line.
                continue
            
            # If the previous line was a skipped heading, also skip the following blank line.
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # Remove leading blank lines.
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # Remove leading dividers.
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # Also remove blank lines immediately after a divider.
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls, 
        report_id: str, 
        status: str, 
        progress: int, 
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        Update report generation progress.

        The frontend can read `progress.json` for live progress updates.
        """
        cls._ensure_report_folder(report_id)
        
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        
        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """Get report generation progress."""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Get the list of generated sections.

        Returns information for all saved section files.
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Parse the section index from the file name.
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        Assemble the full report.

        Build the full report from the saved section files and clean heading issues.
        """
        folder = cls._get_report_folder(report_id)
        
        # Build the report header.
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # Read all section files in order.
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # Post-process the full report to clean heading issues.
        md_content = cls._post_process_report(md_content, outline)
        
        # Save the full report.
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(f"Full report assembled: {report_id}")
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        Post-process report content.

        1. Remove duplicate headings
        2. Keep the report title (`#`) and section titles (`##`), and convert deeper headings into bold text
        3. Clean extra blank lines and dividers
        
        Args:
            content: Raw report content
            outline: report outline
            
        Returns:
            Processed content
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # Collect all section titles from the outline.
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Check whether the line is a heading.
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # Detect duplicate headings that repeat within a 5-line window.
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # Skip the duplicate heading and any blank lines that follow it.
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # Heading-level handling:
                # - `#` (level 1): keep only the report title
                # - `##` (level 2): keep section titles
                # - `###` and deeper: convert to bold text
                
                if level == 1:
                    if title == outline.title:
                        # Keep the main report title.
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # Fix section titles that incorrectly used `#` by converting them to `##`.
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # Convert other level-1 headings into bold text.
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # Keep the section title.
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # Convert non-section level-2 headings into bold text.
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # Convert `###` and deeper headings into bold text.
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # Skip dividers that directly follow headings.
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # Keep only one blank line after a heading.
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # Collapse repeated blank lines, keeping at most 2.
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """Save report metadata and the full report."""
        cls._ensure_report_folder(report.report_id)
        
        # Save the metadata JSON.
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # Save the outline.
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # Save the full Markdown report.
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(f"Report saved: {report.report_id}")
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """Get a report."""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # Backward compatibility: check for files stored directly under `reports/`.
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Rebuild the Report object.
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # If `markdown_content` is empty, try reading it from `full_report.md`.
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """Get a report by simulation ID"""
        cls._ensure_reports_dir()
        
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # New format: folder-based storage.
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # Backward compatibility: JSON-file format.
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        
        return None
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """List reports."""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # New format: folder-based storage.
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # Backward compatibility: JSON-file format.
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # Sort by creation time descending.
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """Delete a report, including its whole folder."""
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # New format: delete the entire folder.
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(f"Report folder deleted: {report_id}")
            return True
        
        # Backward compatibility: delete the legacy standalone files.
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")
        
        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True
        
        return deleted
