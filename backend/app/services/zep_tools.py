"""
Zep retrieval tools service.
Wraps graph search, node reads, and edge queries for the Report Agent.

Core retrieval tools:
1. InsightForge - the deepest hybrid retrieval flow, with automatic sub-questions
2. PanoramaSearch - broad retrieval for a full view, including expired content
3. QuickSearch - lightweight direct retrieval
"""

import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges

logger = get_logger('mirofish.zep_tools')


@dataclass
class SearchResult:
    """Search result."""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count
        }
    
    def to_text(self) -> str:
        """Convert to text for LLM consumption."""
        text_parts = [f"search query: {self.query}", f"found {self.total_count} relevant items"]
        
        if self.facts:
            text_parts.append("\n### Relevant Facts:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        
        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """Node information."""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }
    
    def to_text(self) -> str:
        """Convert to text."""
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "UnknownType")
        return f"Entity: {self.name} (Type: {entity_type})\nSummary: {self.summary}"


@dataclass
class EdgeInfo:
    """Edge information."""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    # Temporal information.
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at
        }
    
    def to_text(self, include_temporal: bool = False) -> str:
        """Convert to text."""
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"Relationship: {source} --[{self.name}]--> {target}\nFact: {self.fact}"
        
        if include_temporal:
            valid_at = self.valid_at or "unknown"
            invalid_at = self.invalid_at or "present"
            base_text += f"\nValidity: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (expired: {self.expired_at})"
        
        return base_text
    
    @property
    def is_expired(self) -> bool:
        """Whether this edge has expired."""
        return self.expired_at is not None
    
    @property
    def is_invalid(self) -> bool:
        """Whether this edge is no longer valid."""
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    """
    InsightForge retrieval result.
    Contains retrieval output for multiple sub-questions plus a combined analysis.
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    
    # Retrieval results across dimensions.
    semantic_facts: List[str] = field(default_factory=list)  # Semantic-search results.
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)  # Entity insights.
    relationship_chains: List[str] = field(default_factory=list)  # Relationship chains.
    
    # Statistics.
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships
        }
    
    def to_text(self) -> str:
        """Convert to a detailed text form for LLM consumption."""
        text_parts = [
            f"## Deep Forecast Analysis",
            f"Question: {self.query}",
            f"Scenario: {self.simulation_requirement}",
            f"\n### Retrieval Statistics",
            f"- Relevant forecast facts: {self.total_facts}",
            f"- Involved entities: {self.total_entities}",
            f"- Relationship chains: {self.total_relationships}"
        ]
        
        # Sub-questions.
        if self.sub_queries:
            text_parts.append(f"\n### Sub-Questions")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")
        
        # Semantic search results.
        if self.semantic_facts:
            text_parts.append(f"\n### Key Facts (quote these directly in the report when useful)")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Entity insights.
        if self.entity_insights:
            text_parts.append(f"\n### Core Entities")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', 'Unknown')}** ({entity.get('type', 'Entity')})")
                if entity.get('summary'):
                    text_parts.append(f"  Summary: \"{entity.get('summary')}\"")
                if entity.get('related_facts'):
                    text_parts.append(f"  Related facts: {len(entity.get('related_facts', []))}")
        
        # Relationship chains.
        if self.relationship_chains:
            text_parts.append(f"\n### Relationship Chains")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")
        
        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    Panorama search result.
    Contains all related information, including expired content.
    """
    query: str
    
    # All nodes.
    all_nodes: List[NodeInfo] = field(default_factory=list)
    # All edges, including expired ones.
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # Currently active facts.
    active_facts: List[str] = field(default_factory=list)
    # Historical facts that are expired or invalid.
    historical_facts: List[str] = field(default_factory=list)
    
    # Statistics.
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count
        }
    
    def to_text(self) -> str:
        """Convert to text in full, without truncation."""
        text_parts = [
            f"## Panorama Search Result",
            f"Query: {self.query}",
            f"\n### Statistics",
            f"- Total nodes: {self.total_nodes}",
            f"- Total edges: {self.total_edges}",
            f"- Active facts: {self.active_count}",
            f"- Historical / expired facts: {self.historical_count}"
        ]
        
        # Active facts in full.
        if self.active_facts:
            text_parts.append(f"\n### Active Facts (raw simulation output)")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Historical / expired facts in full.
        if self.historical_facts:
            text_parts.append(f"\n### Historical / Expired Facts (evolution record)")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Key entities in full.
        if self.all_nodes:
            text_parts.append(f"\n### Involved Entities")
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "Entity")
                text_parts.append(f"- **{node.name}** ({entity_type})")
        
        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """Interview result for a single Agent."""
    agent_name: str
    agent_role: str  # Role type such as student, teacher, or media.
    agent_bio: str  # Short bio.
    question: str  # Interview question.
    response: str  # Interview answer.
    key_quotes: List[str] = field(default_factory=list)  # Key quotes.
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes
        }
    
    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        # Show the full `agent_bio` without truncation.
        text += f"_Bio: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**Key Quotes:**\n"
            for quote in self.key_quotes:
                # Normalize different quote characters.
                clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
                clean_quote = clean_quote.replace('\u300c', '').replace('\u300d', '')
                clean_quote = clean_quote.strip()
                # Strip leading punctuation.
                while clean_quote and clean_quote[0] in '，,；;：:、。！？\n\r\t ':
                    clean_quote = clean_quote[1:]
                # Filter junk content that starts with question numbering.
                skip = False
                for d in '123456789':
                    if f'\u95ee\u9898{d}' in clean_quote:
                        skip = True
                        break
                if skip:
                    continue
                # Truncate overly long content by sentence boundary instead of hard slicing.
                if len(clean_quote) > 150:
                    dot_pos = clean_quote.find('\u3002', 80)
                    if dot_pos > 0:
                        clean_quote = clean_quote[:dot_pos + 1]
                    else:
                        clean_quote = clean_quote[:147] + "..."
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


@dataclass
class InterviewResult:
    """
    Interview result.
    Contains interview answers from multiple simulated Agents.
    """
    interview_topic: str  # Interview topic.
    interview_questions: List[str]  # Interview question list.
    
    # Selected Agents for the interview.
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # Per-Agent interview answers.
    interviews: List[AgentInterview] = field(default_factory=list)
    
    # Reason for selecting those Agents.
    selection_reasoning: str = ""
    # Combined interview summary.
    summary: str = ""
    
    # Statistics.
    total_agents: int = 0
    interviewed_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count
        }
    
    def to_text(self) -> str:
        """Convert to a detailed text form for LLM reasoning and report quoting."""
        text_parts = [
            "## Deep Interview Report",
            f"**Interview Topic:** {self.interview_topic}",
            f"**Interviewed Agents:** {self.interviewed_count} / {self.total_agents}",
            "\n### Selection Rationale",
            self.selection_reasoning or "(auto-selected)",
            "\n---",
            "\n### Transcript",
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### Interview #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append("(no interview records)\n\n---")

        text_parts.append("\n### Summary and Key Viewpoints")
        text_parts.append(self.summary or "(no summary)")

        return "\n".join(text_parts)


class ZepToolsService:
    """
    Zep retrieval tools service.

    Core retrieval tools:
    1. `insight_forge` - deep insight retrieval with automatic sub-questions and multi-angle search
    2. `panorama_search` - broad retrieval for a full view, including expired content
    3. `quick_search` - lightweight direct retrieval
    4. `interview_agents` - deep interview flow using live simulated Agents

    Base tools:
    - `search_graph` - semantic graph search
    - `get_all_nodes` - fetch all graph nodes
    - `get_all_edges` - fetch all graph edges, including temporal info
    - `get_node_detail` - fetch full node details
    - `get_node_edges` - fetch edges related to one node
    - `get_entities_by_type` - fetch entities by type
    - `get_entity_summary` - fetch relationship summary for an entity
    """
    
    # Retry configuration.
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured")
        
        self.client = Zep(api_key=self.api_key)
        # LLM client used by InsightForge to generate sub-questions.
        self._llm_client = llm_client
        logger.info("ZepToolsService initialized")
    
    @property
    def llm(self) -> LLMClient:
        """Lazily initialize the LLM client."""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client
    
    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """Call an API with retries."""
        max_retries = max_retries or self.MAX_RETRIES
        last_exception = None
        delay = self.RETRY_DELAY
        
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Zep {operation_name} failed on attempt {attempt + 1}: {str(e)[:100]}, "
                        f"retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error(f"Zep {operation_name} still failed after {max_retries} attempts: {str(e)}")
        
        raise last_exception
    
    def search_graph(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Perform semantic graph search.

        Uses hybrid search (semantic + BM25) against the graph.
        Falls back to local keyword matching if the Zep Cloud search API is unavailable.

        Args:
            graph_id: Graph ID (standalone graph)
            query: Search query
            limit: Max result count
            scope: Search scope, `"edges"` or `"nodes"`

        Returns:
            SearchResult: Search result
        """
        logger.info(f"Graph search: graph_id={graph_id}, query={query[:50]}...")
        
        # Try the Zep Cloud Search API first.
        try:
            search_results = self._call_with_retry(
                func=lambda: self.client.graph.search(
                    graph_id=graph_id,
                    query=query,
                    limit=limit,
                    scope=scope,
                    reranker="cross_encoder"
                ),
                operation_name=f"graph_search(graph={graph_id})"
            )
            
            facts = []
            edges = []
            nodes = []
            
            # Parse edge search results.
            if hasattr(search_results, 'edges') and search_results.edges:
                for edge in search_results.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        facts.append(edge.fact)
                    edges.append({
                        "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                        "name": getattr(edge, 'name', ''),
                        "fact": getattr(edge, 'fact', ''),
                        "source_node_uuid": getattr(edge, 'source_node_uuid', ''),
                        "target_node_uuid": getattr(edge, 'target_node_uuid', ''),
                    })
            
            # Parse node search results.
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for node in search_results.nodes:
                    nodes.append({
                        "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                        "name": getattr(node, 'name', ''),
                        "labels": getattr(node, 'labels', []),
                        "summary": getattr(node, 'summary', ''),
                    })
                    # Node summaries also count as facts.
                    if hasattr(node, 'summary') and node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(f"Search completed: found {len(facts)} relevant facts")
            
            return SearchResult(
                facts=facts,
                edges=edges,
                nodes=nodes,
                query=query,
                total_count=len(facts)
            )
            
        except Exception as e:
            logger.warning(f"Zep Search API failed; falling back to local search: {str(e)}")
            # Fallback to local keyword matching.
            return self._local_search(graph_id, query, limit, scope)
    
    def _local_search(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Local keyword-matching search used as a fallback when the Zep Search API is unavailable.

        Fetches all edges or nodes and ranks them locally by keyword match.

        Args:
            graph_id: Graph ID
            query: Search query
            limit: Max result count
            scope: Search scope

        Returns:
            SearchResult: Search result
        """
        logger.info(f"Using local search: query={query[:30]}...")
        
        facts = []
        edges_result = []
        nodes_result = []
        
        # Extract query keywords with a simple split.
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def match_score(text: str) -> int:
            """Compute a simple match score for the text against the query."""
            if not text:
                return 0
            text_lower = text.lower()
            # Exact query match.
            if query_lower in text_lower:
                return 100
            # Keyword matches.
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 10
            return score
        
        try:
            if scope in ["edges", "both"]:
                # Fetch and match all edges.
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    score = match_score(edge.fact) + match_score(edge.name)
                    if score > 0:
                        scored_edges.append((score, edge))
                
                # Sort by score.
                scored_edges.sort(key=lambda x: x[0], reverse=True)
                
                for score, edge in scored_edges[:limit]:
                    if edge.fact:
                        facts.append(edge.fact)
                    edges_result.append({
                        "uuid": edge.uuid,
                        "name": edge.name,
                        "fact": edge.fact,
                        "source_node_uuid": edge.source_node_uuid,
                        "target_node_uuid": edge.target_node_uuid,
                    })
            
            if scope in ["nodes", "both"]:
                # Fetch and match all nodes.
                all_nodes = self.get_all_nodes(graph_id)
                scored_nodes = []
                for node in all_nodes:
                    score = match_score(node.name) + match_score(node.summary)
                    if score > 0:
                        scored_nodes.append((score, node))
                
                scored_nodes.sort(key=lambda x: x[0], reverse=True)
                
                for score, node in scored_nodes[:limit]:
                    nodes_result.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "labels": node.labels,
                        "summary": node.summary,
                    })
                    if node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(f"Local search completed: found {len(facts)} relevant facts")
            
        except Exception as e:
            logger.error(f"Local search failed: {str(e)}")
        
        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts)
        )
    
    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """
        Get all graph nodes using pagination.

        Args:
            graph_id: Graph ID

        Returns:
            Node list
        """
        logger.info(f"Fetching all nodes for graph {graph_id}...")

        nodes = fetch_all_nodes(self.client, graph_id)

        result = []
        for node in nodes:
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', None) or ""
            result.append(NodeInfo(
                uuid=str(node_uuid) if node_uuid else "",
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            ))

        logger.info(f"Fetched {len(result)} nodes")
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """
        Get all graph edges using pagination, including temporal information.

        Args:
            graph_id: Graph ID
            include_temporal: Whether to include temporal fields, default `True`

        Returns:
            Edge list including `created_at`, `valid_at`, `invalid_at`, and `expired_at`
        """
        logger.info(f"Fetching all edges for graph {graph_id}...")

        edges = fetch_all_edges(self.client, graph_id)

        result = []
        for edge in edges:
            edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
            edge_info = EdgeInfo(
                uuid=str(edge_uuid) if edge_uuid else "",
                name=edge.name or "",
                fact=edge.fact or "",
                source_node_uuid=edge.source_node_uuid or "",
                target_node_uuid=edge.target_node_uuid or ""
            )

            # Add temporal fields.
            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(f"Fetched {len(result)} edges")
        return result
    
    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """
        Get detailed information for a single node.
        
        Args:
            node_uuid: Node UUID
            
        Returns:
            Node information or `None`
        """
        logger.info(f"Fetching node detail: {node_uuid[:8]}...")
        
        try:
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=node_uuid),
                operation_name=f"get_node_detail(uuid={node_uuid[:8]}...)"
            )
            
            if not node:
                return None
            
            return NodeInfo(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            )
        except Exception as e:
            logger.error(f"Failed to fetch node detail: {str(e)}")
            return None
    
    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """
        Get all edges related to one node.

        This fetches all graph edges and filters them for the requested node.
        
        Args:
            graph_id: Graph ID
            node_uuid: Node UUID
            
        Returns:
            Edge list
        """
        logger.info(f"Fetching edges related to node {node_uuid[:8]}...")
        
        try:
            # Fetch all graph edges and filter them.
            all_edges = self.get_all_edges(graph_id)
            
            result = []
            for edge in all_edges:
                # Keep edges where the node is either the source or the target.
                if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                    result.append(edge)
            
            logger.info(f"Found {len(result)} edges related to the node")
            return result
            
        except Exception as e:
            logger.warning(f"Failed to fetch node edges: {str(e)}")
            return []
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str
    ) -> List[NodeInfo]:
        """
        Get entities by type.
        
        Args:
            graph_id: Graph ID
            entity_type: Entity type, such as `Student` or `PublicFigure`
            
        Returns:
            List of matching entities
        """
        logger.info(f"Fetching entities of type {entity_type}...")
        
        all_nodes = self.get_all_nodes(graph_id)
        
        filtered = []
        for node in all_nodes:
            # Check whether the labels contain the requested type.
            if entity_type in node.labels:
                filtered.append(node)
        
        logger.info(f"Found {len(filtered)} entities of type {entity_type}")
        return filtered
    
    def get_entity_summary(
        self, 
        graph_id: str, 
        entity_name: str
    ) -> Dict[str, Any]:
        """
        Get a relationship summary for the requested entity.

        Searches all information related to the entity and assembles a summary.
        
        Args:
            graph_id: Graph ID
            entity_name: Entity name
            
        Returns:
            Entity summary information
        """
        logger.info(f"Fetching relationship summary for entity {entity_name}...")
        
        # First search for information related to this entity.
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )
        
        # Try to locate the entity among all nodes.
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break
        
        related_edges = []
        if entity_node:
            # Pass `graph_id` through.
            related_edges = self.get_node_edges(graph_id, entity_node.uuid)
        
        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges)
        }
    
    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """
        Get graph statistics.
        
        Args:
            graph_id: Graph ID
            
        Returns:
            Statistics
        """
        logger.info(f"Fetching statistics for graph {graph_id}...")
        
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        
        # Count entity types.
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        
        # Count relationship types.
        relation_types = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1
        
        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types
        }
    
    def get_simulation_context(
        self, 
        graph_id: str,
        simulation_requirement: str,
        limit: int = 30
    ) -> Dict[str, Any]:
        """
        Get context related to the simulation.

        Collects all information related to the simulation requirement.
        
        Args:
            graph_id: Graph ID
            simulation_requirement: Simulation requirement description
            limit: Per-category result limit
            
        Returns:
            Simulation context information
        """
        logger.info(f"Fetching simulation context: {simulation_requirement[:50]}...")
        
        # Search for information related to the simulation requirement.
        search_result = self.search_graph(
            graph_id=graph_id,
            query=simulation_requirement,
            limit=limit
        )
        
        # Get graph statistics.
        stats = self.get_graph_statistics(graph_id)
        
        # Get all entity nodes.
        all_nodes = self.get_all_nodes(graph_id)
        
        # Keep nodes with a real type, not just the generic `Entity` label.
        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.labels if l not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({
                    "name": node.name,
                    "type": custom_labels[0],
                    "summary": node.summary
                })
        
        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],  # Limit output count.
            "total_entities": len(entities)
        }
    
    # ========== Core Retrieval Tools ==========
    
    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> InsightForgeResult:
        """
        InsightForge: deep insight retrieval.

        This is the most comprehensive hybrid retrieval flow:
        1. Use the LLM to decompose the question into sub-questions
        2. Run semantic search for each sub-question
        3. Extract related entities and fetch their details
        4. Build relationship chains
        5. Combine everything into a deep insight result

        Args:
            graph_id: Graph ID
            query: User question
            simulation_requirement: Simulation requirement description
            report_context: Optional report context for more precise sub-question generation
            max_sub_queries: Maximum number of sub-questions

        Returns:
            InsightForgeResult: Deep insight retrieval result
        """
        logger.info(f"InsightForge retrieval: {query[:50]}...")
        
        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[]
        )
        
        # Step 1: Generate sub-questions with the LLM.
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries
        )
        result.sub_queries = sub_queries
        logger.info(f"Generated {len(sub_queries)} sub-questions")
        
        # Step 2: Run semantic search for each sub-question.
        all_facts = []
        all_edges = []
        seen_facts = set()
        
        for sub_query in sub_queries:
            search_result = self.search_graph(
                graph_id=graph_id,
                query=sub_query,
                limit=15,
                scope="edges"
            )
            
            for fact in search_result.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)
            
            all_edges.extend(search_result.edges)
        
        # Also search using the original question.
        main_search = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=20,
            scope="edges"
        )
        for fact in main_search.facts:
            if fact not in seen_facts:
                all_facts.append(fact)
                seen_facts.add(fact)
        
        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)
        
        # Step 3: Extract related entity UUIDs from edges and fetch only those nodes.
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                if source_uuid:
                    entity_uuids.add(source_uuid)
                if target_uuid:
                    entity_uuids.add(target_uuid)
        
        # Fetch details for all related entities without truncation.
        entity_insights = []
        node_map = {}  # Used later to build relationship chains.
        
        for uuid in list(entity_uuids):  # Process all entities without truncation.
            if not uuid:
                continue
            try:
                # Fetch each related node individually.
                node = self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "Entity")
                    
                    # Get all facts related to this entity without truncation.
                    related_facts = [
                        f for f in all_facts 
                        if node.name.lower() in f.lower()
                    ]
                    
                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts  # Full output, not truncated.
                    })
            except Exception as e:
                logger.debug(f"Failed to fetch node {uuid}: {e}")
                continue
        
        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)
        
        # Step 4: Build all relationship chains without truncation.
        relationship_chains = []
        for edge_data in all_edges:  # Process all edges without truncation.
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                relation_name = edge_data.get('name', '')
                
                source_name = node_map.get(source_uuid, NodeInfo('', '', [], '', {})).name or source_uuid[:8]
                target_name = node_map.get(target_uuid, NodeInfo('', '', [], '', {})).name or target_uuid[:8]
                
                chain = f"{source_name} --[{relation_name}]--> {target_name}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)
        
        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)
        
        logger.info(f"InsightForge completed: {result.total_facts} facts, {result.total_entities} entities, {result.total_relationships} relationships")
        return result
    
    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """
        Generate sub-questions with the LLM.

        Break a complex question into multiple independently retrievable sub-questions.
        """
        system_prompt = """You are an expert at decomposing questions. Break a complex question into multiple sub-questions that can be observed independently in the simulated world.

Requirements:
1. Each sub-question should be specific enough to map to Agent behavior or events in the simulation
2. The sub-questions should cover different dimensions of the original question, such as who, what, why, how, when, and where
3. Every sub-question should be relevant to the simulation scenario
4. Return JSON in this format: {"sub_queries": ["sub-question 1", "sub-question 2", ...]}"""

        user_prompt = f"""Simulation background:
{simulation_requirement}

{f"Report context: {report_context[:500]}" if report_context else ""}

Break the following question into {max_queries} sub-questions:
{query}

Return a JSON list of sub-questions."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            sub_queries = response.get("sub_queries", [])
            # Ensure the result is a list of strings.
            return [str(sq) for sq in sub_queries[:max_queries]]
            
        except Exception as e:
            logger.warning(f"Failed to generate sub-questions: {str(e)}. Using default variants.")
            # Fallback to simple variants of the original question.
            return [
                query,
                f"Main participants in {query}",
                f"Causes and impacts of {query}",
                f"How {query} develops over time"
            ][:max_queries]
    
    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50
    ) -> PanoramaResult:
        """
        PanoramaSearch: broad retrieval.

        Returns a wide-angle view including all relevant content and historical or expired information:
        1. Fetch all relevant nodes
        2. Fetch all edges, including expired or invalid ones
        3. Split the result into active and historical information

        This tool is useful when you need the full picture or want to trace how an event evolved.

        Args:
            graph_id: Graph ID
            query: Search query used for relevance ranking
            include_expired: Whether to include expired content, default `True`
            limit: Max number of returned facts

        Returns:
            PanoramaResult: Broad retrieval result
        """
        logger.info(f"PanoramaSearch retrieval: {query[:50]}...")
        
        result = PanoramaResult(query=query)
        
        # Fetch all nodes.
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)
        
        # Fetch all edges with temporal fields.
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)
        
        # Classify facts.
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            if not edge.fact:
                continue
            
            # Resolve entity names for the fact.
            source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name or edge.source_node_uuid[:8]
            target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name or edge.target_node_uuid[:8]
            
            # Determine whether the edge is historical.
            is_historical = edge.is_expired or edge.is_invalid
            
            if is_historical:
                # Historical or expired fact, annotated with its time range.
                valid_at = edge.valid_at or "unknown"
                invalid_at = edge.invalid_at or edge.expired_at or "unknown"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                # Active fact.
                active_facts.append(edge.fact)
        
        # Rank by relevance to the query.
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score
        
        # Sort and cap the output.
        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        
        logger.info(f"PanoramaSearch completed: {result.active_count} active facts, {result.historical_count} historical facts")
        return result
    
    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        QuickSearch: lightweight direct retrieval.

        This tool:
        1. Calls semantic graph search directly
        2. Returns the most relevant results
        3. Works well for simple and direct lookup tasks

        Args:
            graph_id: Graph ID
            query: Search query
            limit: Max result count

        Returns:
            SearchResult: Search result
        """
        logger.info(f"QuickSearch retrieval: {query[:50]}...")
        
        # Call the existing `search_graph` method directly.
        result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope="edges"
        )
        
        logger.info(f"QuickSearch completed: {result.total_count} results")
        return result
    
    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None
    ) -> InterviewResult:
        """
        InterviewAgents: deep interview flow.

        Calls the live OASIS interview API against running simulated Agents:
        1. Read the generated profile files
        2. Use the LLM to choose the most relevant Agents
        3. Use the LLM to generate interview questions
        4. Call `/api/simulation/interview/batch` for a real dual-platform interview
        5. Combine the responses into an interview report

        Important: the simulation environment must still be running for this feature to work.

        Args:
            simulation_id: Simulation ID, used to locate profile files and call the interview API
            interview_requirement: Interview requirement description, e.g. "understand how students view the event"
            simulation_requirement: Optional simulation background
            max_agents: Maximum number of Agents to interview
            custom_questions: Optional custom interview questions; generated automatically if omitted

        Returns:
            InterviewResult: Interview result
        """
        from .simulation_runner import SimulationRunner
        
        logger.info(f"InterviewAgents using live API: {interview_requirement[:50]}...")
        
        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or []
        )
        
        # Step 1: Load profile files.
        profiles = self._load_agent_profiles(simulation_id)
        
        if not profiles:
            logger.warning(f"No profile files found for simulation {simulation_id}")
            result.summary = "No interviewable Agent profile files were found"
            return result
        
        result.total_agents = len(profiles)
        logger.info(f"Loaded {len(profiles)} Agent profiles")
        
        # Step 2: Use the LLM to select Agents for interview.
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents
        )
        
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(f"Selected {len(selected_agents)} Agents for interview: {selected_indices}")
        
        # Step 3: Generate interview questions if none were provided.
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents
            )
            logger.info(f"Generated {len(result.interview_questions)} interview questions")
        
        # Combine the questions into one interview prompt.
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        
        # Add a prefix that constrains the Agent reply format.
        INTERVIEW_PROMPT_PREFIX = (
            "You are being interviewed. Answer the following questions directly in plain text, based on your persona, your memory, and your prior actions.\n"
            "Response requirements:\n"
            "1. Answer in natural language only and do not call any tools\n"
            "2. Do not return JSON or tool-call formats\n"
            "3. Do not use Markdown headings such as #, ##, or ###\n"
            "4. Answer each numbered question in order, prefixing each answer with `Question X:`\n"
            "5. Separate answers with blank lines\n"
            "6. Provide substantial content, with at least 2-3 sentences per question\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"
        
        # Step 4: Call the live interview API, defaulting to both platforms.
        try:
            # Build the batch request without specifying `platform`, so both are used.
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt  # Use the optimized prompt.
                    # Without `platform`, the API interviews on both Twitter and Reddit.
                })
            
            logger.info(f"Calling batch interview API on both platforms for {len(interviews_request)} Agents")
            
            # Call SimulationRunner's batch interview method with `platform=None`.
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,  # Dual-platform interview.
                timeout=180.0   # Longer timeout for dual-platform execution.
            )
            
            logger.info(f"Interview API returned {api_result.get('interviews_count', 0)} results, success={api_result.get('success')}")
            
            # Check whether the API call succeeded.
            if not api_result.get("success", False):
                error_msg = api_result.get("error", "unknown error")
                logger.warning(f"Interview API returned failure: {error_msg}")
                result.summary = f"Interview API call failed: {error_msg}. Check the OASIS simulation environment state."
                return result
            
            # Step 5: Parse API output and build AgentInterview objects.
            # Dual-platform mode returns keys like `twitter_0`, `reddit_0`, `twitter_1`, ...
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}
            
            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "Unknown")
                agent_bio = agent.get("bio", "")
                
                # Get the interview results for this Agent from both platforms.
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})
                
                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")

                # Strip any tool-call JSON wrapper if present.
                twitter_response = self._clean_tool_call_response(twitter_response)
                reddit_response = self._clean_tool_call_response(reddit_response)

                # Always label both platforms explicitly.
                twitter_text = twitter_response if twitter_response else "(no reply from this platform)"
                reddit_text = reddit_response if reddit_response else "(no reply from this platform)"
                response_text = f"[Twitter Answer]\n{twitter_text}\n\n[Reddit Answer]\n{reddit_text}"

                # Extract key quotes from the combined responses.
                import re
                combined_responses = f"{twitter_response} {reddit_response}"

                # Clean the response text by removing labels, numbering, and Markdown noise.
                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'Question\s*\d+[：:]\s*', '', clean_text, flags=re.IGNORECASE)
                clean_text = re.sub(r'【[^】]+】', '', clean_text)

                # Strategy 1: extract complete, substantial sentences.
                sentences = re.split(r'[。！？]', clean_text)
                meaningful = [
                    s.strip() for s in sentences
                    if 20 <= len(s.strip()) <= 150
                    and not re.match(r'^[\s\W，,；;：:、]+', s.strip())
                    and not s.strip().startswith(('{', 'Question'))
                ]
                meaningful.sort(key=len, reverse=True)
                key_quotes = [s + "。" for s in meaningful[:3]]

                # Strategy 2: look for longer quoted spans if Strategy 1 failed.
                if not key_quotes:
                    paired = re.findall(r'\u201c([^\u201c\u201d]{15,100})\u201d', clean_text)
                    paired += re.findall(r'\u300c([^\u300c\u300d]{15,100})\u300d', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[，,；;：:、]', q)][:3]
                
                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],  # Allow a larger bio excerpt.
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5]
                )
                result.interviews.append(interview)
            
            result.interviewed_count = len(result.interviews)
            
        except ValueError as e:
            # The simulation environment was likely not running.
            logger.warning(f"Interview API call failed (environment not running?): {e}")
            result.summary = f"Interview failed: {str(e)}. The simulation environment may already be closed. Ensure OASIS is still running."
            return result
        except Exception as e:
            logger.error(f"Interview API call raised an exception: {e}")
            import traceback
            logger.error(traceback.format_exc())
            result.summary = f"Interviewing failed with an error: {str(e)}"
            return result
        
        # Step 6: Generate the interview summary.
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement
            )
        
        logger.info(f"InterviewAgents completed: interviewed {result.interviewed_count} Agents across both platforms")
        return result
    
    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """Strip JSON tool-call wrappers from an Agent reply and extract the actual content."""
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        import re as _re
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = _re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """Load Agent profile files for the simulation."""
        import os
        import csv
        
        # Build the profile file path.
        sim_dir = os.path.join(
            os.path.dirname(__file__), 
            f'../../uploads/simulations/{simulation_id}'
        )
        
        profiles = []
        
        # Prefer Reddit JSON first.
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(f"Loaded {len(profiles)} profiles from reddit_profiles.json")
                return profiles
            except Exception as e:
                logger.warning(f"Failed to read reddit_profiles.json: {e}")
        
        # Fall back to Twitter CSV format.
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Convert CSV rows to the shared profile structure.
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "Unknown"
                        })
                logger.info(f"Loaded {len(profiles)} profiles from twitter_profiles.csv")
                return profiles
            except Exception as e:
                logger.warning(f"Failed to read twitter_profiles.csv: {e}")
        
        return profiles
    
    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int
    ) -> tuple:
        """
        Use the LLM to choose which Agents should be interviewed.

        Returns:
            tuple: `(selected_agents, selected_indices, reasoning)`
                - `selected_agents`: full information for the selected Agents
                - `selected_indices`: selected Agent indices, used for API calls
                - `reasoning`: explanation of the selection
        """
        
        # Build Agent summaries.
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession", "Unknown"),
                "bio": profile.get("bio", "")[:200],
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)
        
        system_prompt = """You are an expert interview planner. Choose the most suitable simulated Agents for interview based on the interview requirement.

Selection criteria:
1. The Agent's identity or profession should be relevant to the topic
2. The Agent may hold distinctive or valuable viewpoints
3. Favor diverse perspectives such as supportive, opposing, neutral, or professional voices
4. Prioritize roles directly connected to the event

Return JSON in this format:
{
    "selected_indices": [list of selected Agent indices],
    "reasoning": "selection rationale"
}"""

        user_prompt = f"""Interview requirement:
{interview_requirement}

Simulation background:
{simulation_requirement if simulation_requirement else "not provided"}

Available Agents ({len(agent_summaries)} total):
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

Select up to {max_agents} Agents that are best suited for interview, and explain why."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "Auto-selected based on relevance")
            
            # Fetch the selected Agents' full records.
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            
            return selected_agents, valid_indices, reasoning
            
        except Exception as e:
            logger.warning(f"LLM failed to select Agents; using the default selection: {e}")
            # Fallback: take the first N Agents.
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "Used the default selection strategy"
    
    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate interview questions with the LLM."""
        
        agent_roles = [a.get("profession", "Unknown") for a in selected_agents]
        
        system_prompt = """You are a professional journalist and interviewer. Generate 3-5 deep interview questions based on the interview requirement.

Question requirements:
1. Use open-ended questions that encourage detailed answers
2. The questions should allow different roles to answer differently
3. Cover multiple dimensions such as facts, opinions, and emotions
4. Keep the language natural, like a real interview
5. Each question should stay concise
6. Ask directly without extra preamble or background text

Return JSON in this format: {"questions": ["question 1", "question 2", ...]}"""

        user_prompt = f"""Interview requirement: {interview_requirement}

Simulation background: {simulation_requirement if simulation_requirement else "not provided"}

Interview subject roles: {', '.join(agent_roles)}

Generate 3-5 interview questions."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5
            )
            
            return response.get("questions", [f"What is your view on {interview_requirement}?"])
            
        except Exception as e:
            logger.warning(f"Failed to generate interview questions: {e}")
            return [
                f"What is your perspective on {interview_requirement}?",
                "How does this affect you or the group you represent?",
                "How do you think this issue should be addressed or improved?"
            ]
    
    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str
    ) -> str:
        """Generate an interview summary."""
        
        if not interviews:
            return "No interviews were completed"
        
        # Collect interview content.
        interview_texts = []
        for interview in interviews:
            interview_texts.append(f"[{interview.agent_name} ({interview.agent_role})]\n{interview.response[:500]}")
        
        system_prompt = """You are a professional news editor. Generate an interview summary based on answers from multiple interviewees.

Summary requirements:
1. Extract the main viewpoints from each side
2. Highlight areas of agreement and disagreement
3. Surface valuable quotes
4. Stay objective and neutral
5. Keep the summary under about 1000 English characters

Formatting constraints:
- Use plain-text paragraphs separated by blank lines
- Do not use Markdown headings such as #, ##, or ###
- Do not use dividers such as --- or ***
- When quoting interviewees, use English quotation marks 「」
- You may use **bold** to emphasize keywords, but avoid other Markdown features"""

        user_prompt = f"""Interview topic: {interview_requirement}

Interview content:
{"".join(interview_texts)}

Generate the interview summary."""

        try:
            summary = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            return summary
            
        except Exception as e:
            logger.warning(f"Failed to generate interview summary: {e}")
            # Fallback: simple concatenation.
            return f"Interviewed {len(interviews)} people, including: " + ", ".join([i.agent_name for i in interviews])
