---
phase: 04-agents
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/config.py                              # add WHALE_PCT, QUANT_PCT env vars
  - backend/app/services/oasis_profile_generator.py   # tier assignment in generate_profile_from_entity
  - backend/app/services/simulation_config_generator.py # influence_weight by tier
autonomous: true
must_haves:
  truths:
    - Agents are assigned WHALE / QUANT / RETAIL tier based on entity type
    - Tier drives karma, follower_count, and influence_weight — no random values in those fields
    - 10-agent sim has ≥1 WHALE (influence ~9.0), ≥1 QUANT (~5.0), rest RETAIL (~1.0)
  artifacts:
    - WHALE_PCT / QUANT_PCT in config.py
    - tier assignment logic in generate_profile_from_entity()
    - influence_weight tiers in _generate_agent_config_by_rule()
  key_links:
    - generate_profile_from_entity(): oasis_profile_generator.py:211
    - karma set: oasis_profile_generator.py:261
    - follower_count set: oasis_profile_generator.py:263
    - AgentActivityConfig.influence_weight field: simulation_config_generator.py:80
    - rule-based influence_weight block: simulation_config_generator.py:937-1002
---

<objective>
Make agents reflect real market structure: whales move markets, retail follows.
Equal-weight agents produce meaningless consensus. Capital weighting makes simulations realistic.
Output: Tier enum + tier-driven karma/follower_count/influence_weight. No new files needed.
</objective>

<context>
@.planning/ROADMAP.md
@backend/app/config.py
@backend/app/services/oasis_profile_generator.py
@backend/app/services/simulation_config_generator.py
</context>

<tasks>

<task type="auto">
  <name>Task 4.1: Add tier config to config.py</name>
  <files>backend/app/config.py</files>
  <action>
After the existing SIMULATION_* vars (around line 52), add:
```python
# Capital tier distribution
WHALE_PCT = float(os.environ.get('WHALE_PCT', '0.05'))   # 5% of agents
QUANT_PCT = float(os.environ.get('QUANT_PCT', '0.10'))   # 10% of agents
# RETAIL fills the remainder
```
  </action>
  <verify>
python3 -c "from backend.app.config import Config; print(Config.WHALE_PCT, Config.QUANT_PCT)"
# Expected: 0.05 0.1
  </verify>
  <done>Config.WHALE_PCT and Config.QUANT_PCT accessible.</done>
</task>

<task type="auto">
  <name>Task 4.2: Assign capital tier in generate_profile_from_entity()</name>
  <files>backend/app/services/oasis_profile_generator.py</files>
  <action>
At the top of the file (after existing imports), add the tier enum and range constants:

```python
import enum

class AgentTier(enum.Enum):
    WHALE  = "whale"
    QUANT  = "quant"
    RETAIL = "retail"

_TIER_RANGES = {
    AgentTier.WHALE:  {"karma": (10_000, 100_000), "followers": (50_000, 500_000)},
    AgentTier.QUANT:  {"karma": (2_000,  10_000),  "followers": (5_000,  50_000)},
    AgentTier.RETAIL: {"karma": (10,     500),     "followers": (10,     500)},
}

_HIGH_INFLUENCE_TYPES = {"University", "GovAgency", "MediaOutlet"}
_MID_INFLUENCE_TYPES  = {"NGO", "Professor", "Expert", "Official"}
```

Then add a helper just before `generate_profile_from_entity()` (line 211):

```python
def _assign_tier(self, entity_type: str) -> AgentTier:
    """Assign capital tier based on entity type."""
    from ..config import Config
    if entity_type in _HIGH_INFLUENCE_TYPES:
        return AgentTier.WHALE
    if entity_type in _MID_INFLUENCE_TYPES:
        return AgentTier.QUANT
    # Remaining slots: probabilistic WHALE/QUANT/RETAIL split
    import random
    r = random.random()
    if r < Config.WHALE_PCT:
        return AgentTier.WHALE
    if r < Config.WHALE_PCT + Config.QUANT_PCT:
        return AgentTier.QUANT
    return AgentTier.RETAIL
```

In `generate_profile_from_entity()` (line 211), replace the LLM karma/follower_count assignments
at lines 261-263 with tier-driven values:

**Before (lines 261-263):**
```python
            karma=profile_data.get("karma", random.randint(500, 5000)),
            ...
            follower_count=profile_data.get("follower_count", random.randint(100, 1000)),
```

**After:**
```python
            # --- Tier-driven social metrics ---
            _tier = self._assign_tier(entity.entity_type if hasattr(entity, 'entity_type') else "")
            _kr   = _TIER_RANGES[_tier]["karma"]
            _fr   = _TIER_RANGES[_tier]["followers"]
            karma=profile_data.get("karma") or random.randint(_kr[0], _kr[1]),
            ...
            follower_count=profile_data.get("follower_count") or random.randint(_fr[0], _fr[1]),
```

Also store the tier on the profile for downstream use. In the `OasisAgentProfile` dataclass (line 29),
add one field after the existing fields:
```python
    capital_tier: str = "retail"   # whale | quant | retail
```

And set it in `generate_profile_from_entity()` after karma/follower_count are set:
```python
            capital_tier=_tier.value,
```
  </action>
  <verify>
python3 -c "
from backend.app.services.oasis_profile_generator import OasisAgentProfile, AgentTier
p = OasisAgentProfile()
print(p.capital_tier)       # retail (default)
print(AgentTier.WHALE.value) # whale
"
# Expected: retail \n whale
  </verify>
  <done>AgentTier enum exists; OasisAgentProfile has capital_tier field; _assign_tier() sets karma/follower ranges by tier.</done>
</task>

<task type="auto">
  <name>Task 4.3: Wire influence_weight by tier in _generate_agent_config_by_rule()</name>
  <files>backend/app/services/simulation_config_generator.py</files>
  <action>
The rule-based influence_weight block is at lines 937-1002. It currently assigns by entity type.
Add a tier-based override BEFORE the entity-type checks:

Find the start of the rule-based influence section (around line 930, inside
`_generate_agent_config_by_rule()`). Add at the top of that function's influence assignment:

```python
        # Capital tier → influence weight (overrides entity-type defaults)
        capital_tier = getattr(entity, 'capital_tier', None) or \
                       getattr(profile, 'capital_tier', 'retail')
        _tier_weights = {"whale": 9.0, "quant": 5.0, "retail": 1.0}
        if capital_tier in _tier_weights:
            influence_weight = _tier_weights[capital_tier]
        else:
```
Then indent the existing entity-type block under the `else:`.

Also add `capital_tier` to `AgentActivityConfig` dataclass at line 80:
```python
    capital_tier: str = "retail"   # whale | quant | retail
```

And include it in `SimulationParameters.to_dict()` agent_configs serialization at line 185
(it will be included automatically via `asdict()` since it's a dataclass field).
  </action>
  <verify>
grep -n "capital_tier\|_tier_weights" backend/app/services/simulation_config_generator.py
# Expected: ≥3 matches (dataclass field + dict + assignment)
  </verify>
  <done>influence_weight is tier-driven: whale=9.0, quant=5.0, retail=1.0.</done>
</task>

</tasks>

<success_criteria>
1. Config.WHALE_PCT / Config.QUANT_PCT exist and default to 0.05 / 0.10
2. OasisAgentProfile.capital_tier field is set to "whale" / "quant" / "retail"
3. AgentActivityConfig.influence_weight is 9.0 for whale, 5.0 for quant, 1.0 for retail
4. 10-agent sim output shows whale agent with influence ~9.0 dominating sentiment in report
</success_criteria>
