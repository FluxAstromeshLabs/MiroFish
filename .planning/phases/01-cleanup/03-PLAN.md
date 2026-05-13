---
phase: 01-cleanup
plan: 03
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/config.py
  - backend/app/.env.example
  - backend/app/services/simulation_config_generator.py
  - backend/app/services/oasis_profile_generator.py
autonomous: true
must_haves:
  truths:
    - Agent count is currently fixed: simulation_config_generator.py uses AGENTS_PER_BATCH=15 hardcoded; oasis_profile_generator.py uses parallel_count=5 default in generate_profiles_from_entities(); neither is drivable from an env var today
    - The plan adds SIMULATION_AGENT_COUNT (total cap) and SIMULATION_PROFILE_PARALLEL_COUNT (parallelism) to Config and .env.example
    - simulation_config_generator.py also uses AGENTS_PER_BATCH as a class constant — this becomes Config-driven
    - oasis_profile_generator.py's generate_profiles_from_entities() already accepts parallel_count as a parameter; callers should default to Config.SIMULATION_PROFILE_PARALLEL_COUNT
    - Plan 01 also touches simulation_config_generator.py and config.py — wave-1 parallelism is safe because Plans 01 and 03 edit non-overlapping lines within those files (platform weights vs agent count)
  artifacts:
    - config.py with SIMULATION_AGENT_COUNT, SIMULATION_PROFILE_PARALLEL_COUNT added
    - .env.example updated with English comments and the two new vars
    - simulation_config_generator.py with AGENTS_PER_BATCH driven by Config
    - oasis_profile_generator.py default parallel_count driven by Config
  key_links: []
---

<objective>
Make agent count and profile-generation parallelism configurable via environment variables rather than
buried class constants and parameter defaults.

Purpose: Operators can tune simulation scale and throughput without touching Python source code.
Output: Two new env vars wired through Config into both service files; defaults reproduce current behavior.
</objective>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@backend/app/config.py
@backend/app/services/simulation_config_generator.py
@backend/app/services/oasis_profile_generator.py
</context>

<tasks>

<task type="auto">
  <name>Task 1.6a: Add SIMULATION_AGENT_COUNT and SIMULATION_PROFILE_PARALLEL_COUNT to Config and .env.example</name>
  <files>backend/app/config.py, .env.example</files>
  <action>
In `backend/app/config.py`, add two new config attributes in the "OASIS simulation settings" block,
immediately after the `OASIS_SIMULATION_DATA_DIR` line:

Find:
```python
    # OASIS simulation settings.
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
```

Replace with:
```python
    # OASIS simulation settings.
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    # Total agent count cap. Controls how many entities are retained after Zep filtering.
    # Also used as AGENTS_PER_BATCH upper bound in SimulationConfigGenerator.
    SIMULATION_AGENT_COUNT = int(os.environ.get('SIMULATION_AGENT_COUNT', '15'))
    # Number of agent profiles generated in parallel by OasisProfileGenerator.
    SIMULATION_PROFILE_PARALLEL_COUNT = int(os.environ.get('SIMULATION_PROFILE_PARALLEL_COUNT', '5'))
```

In `.env.example`, append an English-language section at the bottom of the file:

```
# ===== Simulation scale configuration =====
# Maximum number of agents (entities) to include in one simulation run.
# SIMULATION_AGENT_COUNT=15
# Number of agent profiles to generate in parallel.
# SIMULATION_PROFILE_PARALLEL_COUNT=5
```

Note: .env.example currently contains Chinese comments only. Do NOT translate the existing lines in
this task — that is handled by Plan 04. Only append the new English block.
  </action>
  <verify>
Run: `grep -n "SIMULATION_AGENT_COUNT\|SIMULATION_PROFILE_PARALLEL_COUNT" backend/app/config.py`
Expected: two matches.
Run: `grep -n "SIMULATION_AGENT_COUNT" .env.example`
Expected: one match (the commented-out example line).
  </verify>
  <done>
- `Config.SIMULATION_AGENT_COUNT` exists with default `15`.
- `Config.SIMULATION_PROFILE_PARALLEL_COUNT` exists with default `5`.
- Both appear commented-out in `.env.example` with English descriptions.
  </done>
</task>

<task type="auto">
  <name>Task 1.6b: Wire Config values into SimulationConfigGenerator and OasisProfileGenerator</name>
  <files>backend/app/services/simulation_config_generator.py, backend/app/services/oasis_profile_generator.py</files>
  <action>
**simulation_config_generator.py — AGENTS_PER_BATCH**

The class constant is defined at line ~216:
```python
    # number of Agents generated per batch
    AGENTS_PER_BATCH = 15
```

Replace this class-level constant with a runtime value read from Config. Change the line to:
```python
    # Number of agents per batch — set by SIMULATION_AGENT_COUNT env var (default 15).
    AGENTS_PER_BATCH: int  # assigned in __init__
```

Then in `SimulationConfigGenerator.__init__` (immediately after the `self.client = OpenAI(...)` block),
add:
```python
        self.AGENTS_PER_BATCH = Config.SIMULATION_AGENT_COUNT
```

This ensures the value is read once at construction time and remains stable for the lifetime of
a generator instance.

**oasis_profile_generator.py — parallel_count default**

`generate_profiles_from_entities()` has the signature:
```python
    def generate_profiles_from_entities(
        self,
        entities: List[EntityNode],
        use_llm: bool = True,
        progress_callback: Optional[callable] = None,
        graph_id: Optional[str] = None,
        parallel_count: int = 5,
        ...
    ) -> List[OasisAgentProfile]:
```

Change the default value of `parallel_count`:
Find:
```python
        parallel_count: int = 5,
```
Replace with:
```python
        parallel_count: int = Config.SIMULATION_PROFILE_PARALLEL_COUNT,
```
  </action>
  <verify>
Run: `grep -n "AGENTS_PER_BATCH = 15" backend/app/services/simulation_config_generator.py`
Expected: no output (literal 15 is gone).
Run: `grep -n "SIMULATION_AGENT_COUNT" backend/app/services/simulation_config_generator.py`
Expected: one match in __init__.
Run: `grep -n "parallel_count: int = 5" backend/app/services/oasis_profile_generator.py`
Expected: no output.
Run: `grep -n "SIMULATION_PROFILE_PARALLEL_COUNT" backend/app/services/oasis_profile_generator.py`
Expected: one match in the function signature.
  </verify>
  <done>
- `AGENTS_PER_BATCH = 15` (class-level literal) is gone from simulation_config_generator.py.
- `self.AGENTS_PER_BATCH = Config.SIMULATION_AGENT_COUNT` is present in `__init__`.
- `parallel_count` default in `generate_profiles_from_entities` is `Config.SIMULATION_PROFILE_PARALLEL_COUNT`.
- `python -c "from app.services.simulation_config_generator import SimulationConfigGenerator"` imports cleanly.
  </done>
</task>

</tasks>

<success_criteria>
1. `grep -n "SIMULATION_AGENT_COUNT\|SIMULATION_PROFILE_PARALLEL_COUNT" backend/app/config.py` returns two lines.
2. `grep -n "AGENTS_PER_BATCH = 15" backend/app/services/simulation_config_generator.py` returns nothing.
3. `grep -n "parallel_count: int = 5" backend/app/services/oasis_profile_generator.py` returns nothing.
4. `cd backend && python -c "from app.services.simulation_config_generator import SimulationConfigGenerator; from app.services.oasis_profile_generator import OasisProfileGenerator; print('OK')"` prints OK without error.
5. Default behavior is unchanged: SIMULATION_AGENT_COUNT=15, SIMULATION_PROFILE_PARALLEL_COUNT=5.
</success_criteria>
