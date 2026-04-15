"""
OASIS Agent Profile Generator
Convert entities from the Zep graph into the Agent Profile format required by the OASIS simulation platform.

Improvements:
1. Use Zep retrieval to enrich node information a second time.
2. Use improved prompts to generate highly detailed personas.
3. Distinguish individual entities from abstract group entities.
"""

import json
import random
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI
from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.oasis_profile')


@dataclass
class OasisAgentProfile:
    """OASIS Agent Profile data structure"""
    # Common fields
    user_id: int
    user_name: str
    name: str
    bio: str
    persona: str
    
    # Optional fields - Reddit style
    karma: int = 1000
    
    # Optional fields - Twitter style
    friend_count: int = 100
    follower_count: int = 150
    statuses_count: int = 500
    
    # Additional persona fields
    age: Optional[int] = None
    gender: Optional[str] = None
    mbti: Optional[str] = None
    country: Optional[str] = None
    profession: Optional[str] = None
    interested_topics: List[str] = field(default_factory=list)
    
    # Source entity information
    source_entity_uuid: Optional[str] = None
    source_entity_type: Optional[str] = None
    
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    
    def to_reddit_format(self) -> Dict[str, Any]:
        """Convert to Reddit format"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # The OASIS library requires the field name `username` (no underscore).
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "created_at": self.created_at,
        }
        
        # Add additional persona fields when available.
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics
        
        return profile
    
    def to_twitter_format(self) -> Dict[str, Any]:
        """Convert to Twitter format"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # The OASIS library requires the field name `username` (no underscore).
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "created_at": self.created_at,
        }
        
        # Add additional persona fields.
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics
        
        return profile
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to the full dictionary format"""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "age": self.age,
            "gender": self.gender,
            "mbti": self.mbti,
            "country": self.country,
            "profession": self.profession,
            "interested_topics": self.interested_topics,
            "source_entity_uuid": self.source_entity_uuid,
            "source_entity_type": self.source_entity_type,
            "created_at": self.created_at,
        }


class OasisProfileGenerator:
    """
    OASIS Profile Generator
    
    Convert entities from the Zep graph into Agent Profiles required by the OASIS simulation.
    
    Optimizations:
    1. Use Zep graph retrieval to obtain richer context.
    2. Generate highly detailed personas, including profile details, career history, personality, and social media behavior.
    3. Distinguish individual entities from abstract group entities.
    """
    
    # MBTI type list
    MBTI_TYPES = [
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP"
    ]
    
    # Common country list
    COUNTRIES = [
        "China", "US", "UK", "Japan", "Germany", "France", 
        "Canada", "Australia", "Brazil", "India", "South Korea"
    ]
    
    # Individual entity types that need concrete personas
    INDIVIDUAL_ENTITY_TYPES = [
        "student", "alumni", "professor", "person", "publicfigure", 
        "expert", "faculty", "official", "journalist", "activist"
    ]
    
    # Group/institution entity types that need representative personas
    GROUP_ENTITY_TYPES = [
        "university", "governmentagency", "organization", "ngo", 
        "mediaoutlet", "company", "institution", "group", "community"
    ]
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        zep_api_key: Optional[str] = None,
        graph_id: Optional[str] = None
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
        
        # Zep client used to retrieve richer context
        self.zep_api_key = zep_api_key or Config.ZEP_API_KEY
        self.zep_client = None
        self.graph_id = graph_id
        
        if self.zep_api_key:
            try:
                self.zep_client = Zep(api_key=self.zep_api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Zep client: {e}")
    
    def generate_profile_from_entity(
        self, 
        entity: EntityNode, 
        user_id: int,
        use_llm: bool = True
    ) -> OasisAgentProfile:
        """
        Generate an OASIS Agent Profile from a Zep entity
        
        Args:
            entity: Zep entity node
            user_id: user ID (for OASIS)
            use_llm: whether to use the LLM to generate a detailed persona
            
        Returns:
            OasisAgentProfile
        """
        entity_type = entity.get_entity_type() or "Entity"
        
        # Basic information
        name = entity.name
        user_name = self._generate_username(name)
        
        # Build context information
        context = self._build_entity_context(entity)
        
        if use_llm:
            # Use the LLM to generate a detailed persona
            profile_data = self._generate_profile_with_llm(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                context=context
            )
        else:
            # Use rules to generate a basic persona
            profile_data = self._generate_profile_rule_based(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes
            )
        
        return OasisAgentProfile(
            user_id=user_id,
            user_name=user_name,
            name=name,
            bio=profile_data.get("bio", f"{entity_type}: {name}"),
            persona=profile_data.get("persona", entity.summary or f"A {entity_type} named {name}."),
            karma=profile_data.get("karma", random.randint(500, 5000)),
            friend_count=profile_data.get("friend_count", random.randint(50, 500)),
            follower_count=profile_data.get("follower_count", random.randint(100, 1000)),
            statuses_count=profile_data.get("statuses_count", random.randint(100, 2000)),
            age=profile_data.get("age"),
            gender=profile_data.get("gender"),
            mbti=profile_data.get("mbti"),
            country=profile_data.get("country"),
            profession=profile_data.get("profession"),
            interested_topics=profile_data.get("interested_topics", []),
            source_entity_uuid=entity.uuid,
            source_entity_type=entity_type,
        )
    
    def _generate_username(self, name: str) -> str:
        """Generate a username."""
        # Remove special characters and normalize to lowercase.
        username = name.lower().replace(" ", "_")
        username = ''.join(c for c in username if c.isalnum() or c == '_')
        
        # Add a random suffix to avoid duplicates.
        suffix = random.randint(100, 999)
        return f"{username}_{suffix}"
    
    def _search_zep_for_entity(self, entity: EntityNode) -> Dict[str, Any]:
        """
        Use Zep graph hybrid retrieval to gather rich information related to an entity.

        Zep does not provide a built-in hybrid search endpoint, so edges and nodes
        are searched separately and then merged. Parallel requests are used for speed.
        
        Args:
            entity: Entity node object
            
        Returns:
            A dictionary containing `facts`, `node_summaries`, and `context`
        """
        import concurrent.futures
        
        if not self.zep_client:
            return {"facts": [], "node_summaries": [], "context": ""}
        
        entity_name = entity.name
        
        results = {
            "facts": [],
            "node_summaries": [],
            "context": ""
        }
        
        # A graph_id is required to perform retrieval.
        if not self.graph_id:
            logger.debug("Skipping Zep retrieval: graph_id is not set")
            return results
        
        comprehensive_query = f"All information, activities, events, relationships, and background related to {entity_name}"
        
        def search_edges():
            """Search edges (facts / relationships) with retries."""
            max_retries = 3
            last_exception = None
            delay = 2.0
            
            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=30,
                        scope="edges",
                        reranker="rrf"
                    )
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.debug(f"Zep edge search attempt {attempt + 1} failed: {str(e)[:80]}, retrying...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zep edge search still failed after {max_retries} attempts: {e}")
            return None
        
        def search_nodes():
            """Search nodes (entity summaries) with retries."""
            max_retries = 3
            last_exception = None
            delay = 2.0
            
            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=20,
                        scope="nodes",
                        reranker="rrf"
                    )
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.debug(f"Zep node search attempt {attempt + 1} failed: {str(e)[:80]}, retrying...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zep node search still failed after {max_retries} attempts: {e}")
            return None
        
        try:
            # Run edge and node searches in parallel.
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                edge_future = executor.submit(search_edges)
                node_future = executor.submit(search_nodes)
                
                # Collect results.
                edge_result = edge_future.result(timeout=30)
                node_result = node_future.result(timeout=30)
            
            # Process edge search results.
            all_facts = set()
            if edge_result and hasattr(edge_result, 'edges') and edge_result.edges:
                for edge in edge_result.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        all_facts.add(edge.fact)
            results["facts"] = list(all_facts)
            
            # Process node search results.
            all_summaries = set()
            if node_result and hasattr(node_result, 'nodes') and node_result.nodes:
                for node in node_result.nodes:
                    if hasattr(node, 'summary') and node.summary:
                        all_summaries.add(node.summary)
                    if hasattr(node, 'name') and node.name and node.name != entity_name:
                        all_summaries.add(f"Related entity: {node.name}")
            results["node_summaries"] = list(all_summaries)
            
            # Build combined context.
            context_parts = []
            if results["facts"]:
                context_parts.append("Facts:\n" + "\n".join(f"- {f}" for f in results["facts"][:20]))
            if results["node_summaries"]:
                context_parts.append("Related entities:\n" + "\n".join(f"- {s}" for s in results["node_summaries"][:10]))
            results["context"] = "\n\n".join(context_parts)
            
            logger.info(
                f"Zep hybrid retrieval completed: {entity_name}, "
                f"fetched {len(results['facts'])} facts and {len(results['node_summaries'])} related nodes"
            )
            
        except concurrent.futures.TimeoutError:
            logger.warning(f"Zep retrieval timed out ({entity_name})")
        except Exception as e:
            logger.warning(f"Zep retrieval failed ({entity_name}): {e}")
        
        return results
    
    def _build_entity_context(self, entity: EntityNode) -> str:
        """
        Build the full context for an entity.

        Includes:
        1. The entity's own edge information (facts)
        2. Detailed information about related nodes
        3. Rich information retrieved through Zep hybrid retrieval
        """
        context_parts = []
        
        # 1. Add entity attributes.
        if entity.attributes:
            attrs = []
            for key, value in entity.attributes.items():
                if value and str(value).strip():
                    attrs.append(f"- {key}: {value}")
            if attrs:
                context_parts.append("### Entity Attributes\n" + "\n".join(attrs))
        
        # 2. Add related edge information (facts / relationships).
        existing_facts = set()
        if entity.related_edges:
            relationships = []
            for edge in entity.related_edges:  # No item limit.
                fact = edge.get("fact", "")
                edge_name = edge.get("edge_name", "")
                direction = edge.get("direction", "")
                
                if fact:
                    relationships.append(f"- {fact}")
                    existing_facts.add(fact)
                elif edge_name:
                    if direction == "outgoing":
                        relationships.append(f"- {entity.name} --[{edge_name}]--> (related entity)")
                    else:
                        relationships.append(f"- (related entity) --[{edge_name}]--> {entity.name}")
            
            if relationships:
                context_parts.append("### Related Facts and Relationships\n" + "\n".join(relationships))
        
        # 3. Add detailed related-node information.
        if entity.related_nodes:
            related_info = []
            for node in entity.related_nodes:  # No item limit.
                node_name = node.get("name", "")
                node_labels = node.get("labels", [])
                node_summary = node.get("summary", "")
                
                # Filter out default labels.
                custom_labels = [l for l in node_labels if l not in ["Entity", "Node"]]
                label_str = f" ({', '.join(custom_labels)})" if custom_labels else ""
                
                if node_summary:
                    related_info.append(f"- **{node_name}**{label_str}: {node_summary}")
                else:
                    related_info.append(f"- **{node_name}**{label_str}")
            
            if related_info:
                context_parts.append("### Related Entity Information\n" + "\n".join(related_info))
        
        # 4. Use Zep hybrid retrieval to gather richer information.
        zep_results = self._search_zep_for_entity(entity)
        
        if zep_results.get("facts"):
            # De-duplicate facts that are already present.
            new_facts = [f for f in zep_results["facts"] if f not in existing_facts]
            if new_facts:
                context_parts.append("### Facts Retrieved from Zep\n" + "\n".join(f"- {f}" for f in new_facts[:15]))
        
        if zep_results.get("node_summaries"):
            context_parts.append("### Related Nodes Retrieved from Zep\n" + "\n".join(f"- {s}" for s in zep_results["node_summaries"][:10]))
        
        return "\n\n".join(context_parts)
    
    def _is_individual_entity(self, entity_type: str) -> bool:
        """Return whether the entity type is an individual-person type."""
        return entity_type.lower() in self.INDIVIDUAL_ENTITY_TYPES
    
    def _is_group_entity(self, entity_type: str) -> bool:
        """Return whether the entity type is a group / organization type."""
        return entity_type.lower() in self.GROUP_ENTITY_TYPES
    
    def _generate_profile_with_llm(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> Dict[str, Any]:
        """
        Use the LLM to generate a highly detailed persona.

        Entity-specific behavior:
        - Individual entities: generate a concrete personal persona
        - Group / organization entities: generate a representative account persona
        """
        
        is_individual = self._is_individual_entity(entity_type)
        
        if is_individual:
            prompt = self._build_individual_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context
            )
        else:
            prompt = self._build_group_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context
            )

        # Retry several times before falling back.
        max_attempts = 3
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": self._get_system_prompt(is_individual)},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1)  # Lower temperature on each retry.
                    # Do not cap max_tokens here; allow the LLM to respond freely.
                )
                
                content = response.choices[0].message.content
                
                # Check whether the response was truncated.
                finish_reason = response.choices[0].finish_reason
                if finish_reason == 'length':
                    logger.warning(f"LLM output was truncated (attempt {attempt+1}); attempting repair...")
                    content = self._fix_truncated_json(content)
                
                # Attempt to parse the JSON.
                try:
                    result = json.loads(content)
                    
                    # Validate required fields.
                    if "bio" not in result or not result["bio"]:
                        result["bio"] = entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}"
                    if "persona" not in result or not result["persona"]:
                        result["persona"] = entity_summary or f"{entity_name} is a {entity_type}."
                    
                    return result
                    
                except json.JSONDecodeError as je:
                    logger.warning(f"JSON parsing failed (attempt {attempt+1}): {str(je)[:80]}")
                    
                    # Attempt to repair the JSON.
                    result = self._try_fix_json(content, entity_name, entity_type, entity_summary)
                    if result.get("_fixed"):
                        del result["_fixed"]
                        return result
                    
                    last_error = je
                    
            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(1 * (attempt + 1))  # exponential backoff
        
        logger.warning(f"LLM persona generation failed after {max_attempts} attempts: {last_error}. Falling back to rule-based generation")
        return self._generate_profile_rule_based(
            entity_name, entity_type, entity_summary, entity_attributes
        )
    
    def _fix_truncated_json(self, content: str) -> str:
        """Repair truncated JSON, typically caused by token limits."""
        import re
        
        # If the JSON is truncated, try to close it.
        content = content.strip()
        
        # Count unclosed braces and brackets.
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # Check for an unclosed string.
        # Simple heuristic: if the last character is not a quote, comma, or closing brace/bracket,
        # the string may have been truncated.
        if content and content[-1] not in '",}]':
            # Attempt to close the string.
            content += '"'
        
        # Close brackets and braces.
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_json(self, content: str, entity_name: str, entity_type: str, entity_summary: str = "") -> Dict[str, Any]:
        """Attempt to repair malformed JSON."""
        import re
        
        # 1. First, try repairing truncation.
        content = self._fix_truncated_json(content)
        
        # 2. Try to extract the JSON portion.
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # 3. Normalize newlines inside string values.
            def fix_string_newlines(match):
                s = match.group(0)
                # Replace actual newlines inside strings with spaces.
                s = s.replace('\n', ' ').replace('\r', ' ')
                # Collapse repeated whitespace.
                s = re.sub(r'\s+', ' ', s)
                return s
            
            # Match JSON string values.
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string_newlines, json_str)
            
            # 4. Attempt parsing.
            try:
                result = json.loads(json_str)
                result["_fixed"] = True
                return result
            except json.JSONDecodeError as e:
                # 5. If that still fails, try a more aggressive repair.
                try:
                    # Remove control characters.
                    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                    # Collapse repeated whitespace.
                    json_str = re.sub(r'\s+', ' ', json_str)
                    result = json.loads(json_str)
                    result["_fixed"] = True
                    return result
                except:
                    pass
        
        # 6. Try extracting partial information directly from the content.
        bio_match = re.search(r'"bio"\s*:\s*"([^"]*)"', content)
        persona_match = re.search(r'"persona"\s*:\s*"([^"]*)', content)  # May be truncated.
        
        bio = bio_match.group(1) if bio_match else (entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}")
        persona = persona_match.group(1) if persona_match else (entity_summary or f"{entity_name} is a {entity_type}.")
        
        # If meaningful content was extracted, mark the result as repaired.
        if bio_match or persona_match:
            logger.info("Extracted partial information from malformed JSON")
            return {
                "bio": bio,
                "persona": persona,
                "_fixed": True
            }
        
        # 7. Full fallback: return a minimal valid structure.
        logger.warning("JSON repair failed; returning a minimal fallback structure")
        return {
            "bio": entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}",
            "persona": entity_summary or f"{entity_name} is a {entity_type}."
        }
    
    def _get_system_prompt(self, is_individual: bool) -> str:
        """Get the system prompt."""
        base_prompt = (
            "You are an expert in generating social-media user profiles. Generate a detailed, realistic persona for public-opinion simulation while staying as faithful as possible to known real-world context. "
            "You must return valid JSON, and string values must not contain unescaped newlines. Use Chinese."
        )
        return base_prompt
    
    def _build_individual_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """Build the detailed persona prompt for an individual entity."""
        
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "None"
        context_str = context[:3000] if context else "Noneadditional context"
        
        return f"""Generate a detailed social-media user persona for this entity while staying as faithful as possible to the known real-world context.

Entity name: {entity_name}
entity types: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context:
{context_str}

Please return JSON with the following fields:

1. bio: social-media bio, about 200 Chinese characters
2. persona: detailed persona description (plain text, about 2000 Chinese characters), including:
   - Basic information (age, occupation, education background, location)
   - Personal background (important experiences, connection to the event, social relationships)
   - Personality traits (MBTI, core traits, emotional style)
   - Social-media behavior (posting frequency, content preferences, interaction style, language style)
   - Stance and opinions (attitude toward the topic, what may anger or move this person)
   - Distinctive traits (catchphrases, special experiences, hobbies)
   - Personal memory (an important part of the persona: explain how this individual relates to the event and what actions or reactions they have already taken in it)
3. age: numeric age (must be an integer)
4. gender: must be in English: "male" or "female"
5. mbti: MBTI type (such as INTJ, ENFP)
6. country: country (use Chinese, e.g. "China")
7. profession: profession
8. interested_topics: array of interested topics

Important:
- All field values must be strings or numbers; do not use newline characters
- `persona` must be one coherent block of text
- Use Chinese for the content, except the `gender` field which must be English `male` or `female`
- Keep the content consistent with the entity information
- `age` must be a valid integer and `gender` must be "male" or "female"
"""

    def _build_group_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """Build the detailed persona prompt for a group or organization entity."""
        
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "None"
        context_str = context[:3000] if context else "Noneadditional context"
        
        return f"""Generate a detailed social-media account profile for this organization or group entity while staying as faithful as possible to the known real-world context.

Entity name: {entity_name}
entity types: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context:
{context_str}

Please return JSON with the following fields:

1. bio: official account bio, about 200 Chinese characters, professional and appropriate
2. persona: detailed account profile description (plain text, about 2000 Chinese characters), including:
   - Basic organizational information (official name, nature of the organization, founding background, main functions)
   - Account positioning (account type, target audience, core function)
   - Speaking style (language style, common phrasing, taboo topics)
   - Posting characteristics (content types, posting frequency, active time ranges)
   - Official stance (position on core topics, how the account handles controversy)
   - Special notes (representative group profile, operating habits)
   - Organizational memory (an important part of the persona: explain how this organization relates to the event and what actions or reactions it has already shown)
3. age: always set to 30 (virtual age for organization accounts)
4. gender: always set to "other" (organization accounts use `other`)
5. mbti: MBTI type describing account style, such as ISTJ for strict and conservative
6. country: country (use Chinese, e.g. "China")
7. profession: description of organizational function
8. interested_topics: array of followed domains

Important:
- All field values must be strings or numbers; null is not allowed
- `persona` must be one coherent block of text with no newline characters
- Use Chinese for the content, except the `gender` field which must be English `"other"`
- `age` must be integer `30`, and `gender` must be the string `"other"`
- The account's voice must match its institutional identity"""
    
    def _generate_profile_rule_based(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use rules to generate a basic persona"""
        
        # Generate different persona defaults based on the entity type.
        entity_type_lower = entity_type.lower()
        
        if entity_type_lower in ["student", "alumni"]:
            return {
                "bio": f"{entity_type} with interests in academics and social issues.",
                "persona": f"{entity_name} is a {entity_type.lower()} who is actively engaged in academic and social discussions. They enjoy sharing perspectives and connecting with peers.",
                "age": random.randint(18, 30),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": random.choice(self.COUNTRIES),
                "profession": "Student",
                "interested_topics": ["Education", "Social Issues", "Technology"],
            }
        
        elif entity_type_lower in ["publicfigure", "expert", "faculty"]:
            return {
                "bio": f"Expert and thought leader in their field.",
                "persona": f"{entity_name} is a recognized {entity_type.lower()} who shares insights and opinions on important matters. They are known for their expertise and influence in public discourse.",
                "age": random.randint(35, 60),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(["ENTJ", "INTJ", "ENTP", "INTP"]),
                "country": random.choice(self.COUNTRIES),
                "profession": entity_attributes.get("occupation", "Expert"),
                "interested_topics": ["Politics", "Economics", "Culture & Society"],
            }
        
        elif entity_type_lower in ["mediaoutlet", "socialmediaplatform"]:
            return {
                "bio": f"Official account for {entity_name}. News and updates.",
                "persona": f"{entity_name} is a media entity that reports news and facilitates public discourse. The account shares timely updates and engages with the audience on current events.",
                "age": 30,  # Virtual age for organization accounts.
                "gender": "other",  # Organizations use "other".
                "mbti": "ISTJ",  # Conservative and formal institutional style.
                "country": "China",
                "profession": "Media",
                "interested_topics": ["General News", "Current Events", "Public Affairs"],
            }
        
        elif entity_type_lower in ["university", "governmentagency", "ngo", "organization"]:
            return {
                "bio": f"Official account of {entity_name}.",
                "persona": f"{entity_name} is an institutional entity that communicates official positions, announcements, and engages with stakeholders on relevant matters.",
                "age": 30,  # Virtual age for organization accounts.
                "gender": "other",  # Organizations use "other".
                "mbti": "ISTJ",  # Conservative and formal institutional style.
                "country": "China",
                "profession": entity_type,
                "interested_topics": ["Public Policy", "Community", "Official Announcements"],
            }
        
        else:
            # Default fallback persona.
            return {
                "bio": entity_summary[:150] if entity_summary else f"{entity_type}: {entity_name}",
                "persona": entity_summary or f"{entity_name} is a {entity_type.lower()} participating in social discussions.",
                "age": random.randint(25, 50),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": random.choice(self.COUNTRIES),
                "profession": entity_type,
                "interested_topics": ["General", "Social Issues"],
            }
    
    def set_graph_id(self, graph_id: str):
        """Set the graph ID used for Zep retrieval."""
        self.graph_id = graph_id
    
    def generate_profiles_from_entities(
        self,
        entities: List[EntityNode],
        use_llm: bool = True,
        progress_callback: Optional[callable] = None,
        graph_id: Optional[str] = None,
        parallel_count: int = 5,
        realtime_output_path: Optional[str] = None,
        output_platform: str = "reddit"
    ) -> List[OasisAgentProfile]:
        """
        Generate Agent profiles from entities in batch, with optional parallelism.
        
        Args:
            entities: entity list
            use_llm: whether to use the LLM to generate a detailed persona
            progress_callback: Progress callback `(current, total, message)`
            graph_id: Graph ID used for Zep retrieval to obtain richer context
            parallel_count: Parallel generation count, default 5
            realtime_output_path: Path for incremental writes, if enabled
            output_platform: Output platform format (`"reddit"` or `"twitter"`)
            
        Returns:
            List of Agent profiles
        """
        import concurrent.futures
        from threading import Lock
        
        # Set the graph_id for Zep retrieval.
        if graph_id:
            self.graph_id = graph_id
        
        total = len(entities)
        profiles = [None] * total  # Pre-allocate to preserve order.
        completed_count = [0]  # Use a list so the closure can mutate the counter.
        lock = Lock()
        
        # Helper for incremental file writes.
        def save_profiles_realtime():
            """Persist generated profiles incrementally."""
            if not realtime_output_path:
                return
            
            with lock:
                # Keep only profiles that have already been generated.
                existing_profiles = [p for p in profiles if p is not None]
                if not existing_profiles:
                    return
                
                try:
                    if output_platform == "reddit":
                        # Reddit JSON format.
                        profiles_data = [p.to_reddit_format() for p in existing_profiles]
                        with open(realtime_output_path, 'w', encoding='utf-8') as f:
                            json.dump(profiles_data, f, ensure_ascii=False, indent=2)
                    else:
                        # Twitter CSV format.
                        import csv
                        profiles_data = [p.to_twitter_format() for p in existing_profiles]
                        if profiles_data:
                            fieldnames = list(profiles_data[0].keys())
                            with open(realtime_output_path, 'w', encoding='utf-8', newline='') as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames)
                                writer.writeheader()
                                writer.writerows(profiles_data)
                except Exception as e:
                    logger.warning(f"Incremental profile save failed: {e}")
        
        def generate_single_profile(idx: int, entity: EntityNode) -> tuple:
            """Worker function that generates one profile."""
            entity_type = entity.get_entity_type() or "Entity"
            
            try:
                profile = self.generate_profile_from_entity(
                    entity=entity,
                    user_id=idx,
                    use_llm=use_llm
                )
                
                # Print the generated persona to the console in real time.
                self._print_generated_profile(entity.name, entity_type, profile)
                
                return idx, profile, None
                
            except Exception as e:
                logger.error(f"Failed to generate persona for entity {entity.name}: {str(e)}")
                # Create a basic fallback profile.
                fallback_profile = OasisAgentProfile(
                    user_id=idx,
                    user_name=self._generate_username(entity.name),
                    name=entity.name,
                    bio=f"{entity_type}: {entity.name}",
                    persona=entity.summary or f"A participant in social discussions.",
                    source_entity_uuid=entity.uuid,
                    source_entity_type=entity_type,
                )
                return idx, fallback_profile, str(e)
        
        logger.info(f"Starting parallel generation for {total} Agent personas (parallelism: {parallel_count})...")
        print(f"\n{'='*60}")
        print(f"Generating Agent personas: {total} entities total, parallelism {parallel_count}")
        print(f"{'='*60}\n")
        
        # Execute in parallel with a thread pool.
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count) as executor:
            # Submit all tasks.
            future_to_entity = {
                executor.submit(generate_single_profile, idx, entity): (idx, entity)
                for idx, entity in enumerate(entities)
            }
            
            # Collect results.
            for future in concurrent.futures.as_completed(future_to_entity):
                idx, entity = future_to_entity[future]
                entity_type = entity.get_entity_type() or "Entity"
                
                try:
                    result_idx, profile, error = future.result()
                    profiles[result_idx] = profile
                    
                    with lock:
                        completed_count[0] += 1
                        current = completed_count[0]
                    
                    # Persist incremental output.
                    save_profiles_realtime()
                    
                    if progress_callback:
                        progress_callback(
                            current, 
                            total, 
                            f"Completed {current}/{total}: {entity.name} ({entity_type})"
                        )
                    
                    if error:
                        logger.warning(f"[{current}/{total}] {entity.name} used a fallback persona: {error}")
                    else:
                        logger.info(f"[{current}/{total}] Persona generated successfully: {entity.name} ({entity_type})")
                        
                except Exception as e:
                    logger.error(f"Unexpected error while processing entity {entity.name}: {str(e)}")
                    with lock:
                        completed_count[0] += 1
                    profiles[idx] = OasisAgentProfile(
                        user_id=idx,
                        user_name=self._generate_username(entity.name),
                        name=entity.name,
                        bio=f"{entity_type}: {entity.name}",
                        persona=entity.summary or "A participant in social discussions.",
                        source_entity_uuid=entity.uuid,
                        source_entity_type=entity_type,
                    )
                    # Persist output even for fallback personas.
                    save_profiles_realtime()
        
        print(f"\n{'='*60}")
        print(f"Persona generation complete. Generated {len([p for p in profiles if p])} Agents")
        print(f"{'='*60}\n")
        
        return profiles
    
    def _print_generated_profile(self, entity_name: str, entity_type: str, profile: OasisAgentProfile):
        """Print a generated persona to the console in full, without truncation."""
        separator = "-" * 70
        
        # Build the full console output without truncation.
        topics_str = ', '.join(profile.interested_topics) if profile.interested_topics else 'None'
        
        output_lines = [
            f"\n{separator}",
            f"[Generated] {entity_name} ({entity_type})",
            f"{separator}",
            f"Username: {profile.user_name}",
            f"",
            f"[Bio]",
            f"{profile.bio}",
            f"",
            f"[Detailed Persona]",
            f"{profile.persona}",
            f"",
            f"[Basic Attributes]",
            f"Age: {profile.age} | Gender: {profile.gender} | MBTI: {profile.mbti}",
            f"Profession: {profile.profession} | Country: {profile.country}",
            f"Interested topics: {topics_str}",
            separator
        ]
        
        output = "\n".join(output_lines)
        
        # Print only to stdout to avoid duplicate full-content logs.
        print(output)
    
    def save_profiles(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """
        Save profiles to disk using the platform-specific format.

        OASIS platform format requirements:
        - Twitter: CSV
        - Reddit: JSON
        
        Args:
            profiles: Profile list
            file_path: Target file path
            platform: Platform type (`"reddit"` or `"twitter"`)
        """
        if platform == "twitter":
            self._save_twitter_csv(profiles, file_path)
        else:
            self._save_reddit_json(profiles, file_path)
    
    def _save_twitter_csv(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        Save Twitter profiles in CSV format that matches OASIS requirements.

        Required CSV fields for OASIS Twitter:
        - user_id: User ID, starting from 0 in CSV order
        - name: Real name
        - username: Username used in the system
        - user_char: Detailed persona injected into the LLM system prompt
        - description: Short public bio shown on the profile page

        Difference between `user_char` and `description`:
        - `user_char`: Internal persona used by the LLM to shape behavior
        - `description`: Public-facing short bio visible to other users
        """
        import csv
        
        # Ensure the output file uses the `.csv` extension.
        if not file_path.endswith('.csv'):
            file_path = file_path.replace('.json', '.csv')
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write the OASIS-required header.
            headers = ['user_id', 'name', 'username', 'user_char', 'description']
            writer.writerow(headers)
            
            # Write data rows.
            for idx, profile in enumerate(profiles):
                # `user_char`: full persona (`bio` + `persona`) for the LLM system prompt.
                user_char = profile.bio
                if profile.persona and profile.persona != profile.bio:
                    user_char = f"{profile.bio} {profile.persona}"
                # Normalize newlines to spaces for CSV safety.
                user_char = user_char.replace('\n', ' ').replace('\r', ' ')
                
                # `description`: short public bio.
                description = profile.bio.replace('\n', ' ').replace('\r', ' ')
                
                row = [
                    idx,                    # user_id: sequential ID starting at 0
                    profile.name,           # name: real name
                    profile.user_name,      # username
                    user_char,              # user_char: full internal persona
                    description             # description: short public bio
                ]
                writer.writerow(row)
        
        logger.info(f"Saved {len(profiles)} Twitter profiles to {file_path} (OASIS CSV format)")
    
    def _normalize_gender(self, gender: Optional[str]) -> str:
        """
        Normalize the `gender` field to the English values required by OASIS.

        Required values: `male`, `female`, `other`
        """
        if not gender:
            return "other"
        
        gender_lower = gender.lower().strip()
        
        # Chinese-to-English mapping.
        gender_map = {
            "\u7537": "male",
            "\u5973": "female",
            "\u673a\u6784": "other",
            "\u5176\u4ed6": "other",
            # Already valid English values.
            "male": "male",
            "female": "female",
            "other": "other",
        }
        
        return gender_map.get(gender_lower, "other")
    
    def _save_reddit_json(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        Save Reddit profiles in JSON format.

        The output matches `to_reddit_format()` so OASIS can load it correctly.
        The `user_id` field is mandatory because OASIS uses it to match `initial_posts.poster_agent_id`.

        Required fields:
        - user_id: integer user ID used to match `poster_agent_id` in `initial_posts`
        - username: username
        - name: display name
        - bio: short bio
        - persona: detailed persona
        - age: integer age
        - gender: `"male"`, `"female"`, or `"other"`
        - mbti: MBTI type
        - country: country
        """
        data = []
        for idx, profile in enumerate(profiles):
            # Use the same format as `to_reddit_format()`.
            item = {
                "user_id": profile.user_id if profile.user_id is not None else idx,  # Critical: `user_id` must be present.
                "username": profile.user_name,
                "name": profile.name,
                "bio": profile.bio[:150] if profile.bio else f"{profile.name}",
                "persona": profile.persona or f"{profile.name} is a participant in social discussions.",
                "karma": profile.karma if profile.karma else 1000,
                "created_at": profile.created_at,
                # OASIS-required fields with safe defaults.
                "age": profile.age if profile.age else 30,
                "gender": self._normalize_gender(profile.gender),
                "mbti": profile.mbti if profile.mbti else "ISTJ",
                "country": profile.country if profile.country else "China",
            }
            
            # Optional fields.
            if profile.profession:
                item["profession"] = profile.profession
            if profile.interested_topics:
                item["interested_topics"] = profile.interested_topics
            
            data.append(item)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved {len(profiles)} Reddit profiles to {file_path} (JSON format with user_id)")
    
    # Keep the old method name as a backward-compatible alias.
    def save_profiles_to_json(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """[Deprecated] Use `save_profiles()` instead."""
        logger.warning("`save_profiles_to_json` is deprecated; use `save_profiles` instead")
        self.save_profiles(profiles, file_path, platform)
