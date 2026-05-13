---
phase: 01-cleanup
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/services/oasis_profile_generator.py
  - backend/app/services/simulation_config_generator.py
autonomous: true
must_haves:
  truths:
    - _normalize_gender in oasis_profile_generator.py contains four dead Chinese key entries that can never be hit (LLM is already instructed to emit English values only)
    - simulation_config_generator.py hardcodes Beijing timezone in CHINA_TIMEZONE_CONFIG, TimeSimulationConfig defaults, LLM prompts, system prompts, and _generate_agent_config_by_rule — these must all be replaced with the SIMULATION_TIMEZONE env var (default UTC)
    - Platform weights (viral_threshold, echo_chamber_strength, recency/popularity/relevance weights) for Twitter and Reddit are magic numbers in generate_config() — they must be pulled into Config
  artifacts:
    - oasis_profile_generator.py with dead Chinese mappings removed from _normalize_gender
    - simulation_config_generator.py with timezone references replaced and platform weights driven by Config
  key_links: []
---

<objective>
Remove dead Chinese string mappings from `_normalize_gender`, replace the hardcoded Beijing timezone
throughout `simulation_config_generator.py` with a `SIMULATION_TIMEZONE` env var, and extract the
Twitter/Reddit platform weight magic numbers into `Config`.

Purpose: No dead Chinese code, no silent geographic assumptions baked into the simulation engine.
Output: Two backend service files edited in place; no behavior change for callers using default UTC.
</objective>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@backend/app/services/oasis_profile_generator.py
@backend/app/services/simulation_config_generator.py
@backend/app/config.py
</context>

<tasks>

<task type="auto">
  <name>Task 1.1: Remove dead Chinese mappings from _normalize_gender</name>
  <files>backend/app/services/oasis_profile_generator.py</files>
  <action>
In `_normalize_gender` (line 1122), the `gender_map` dict contains four dead entries whose keys are
Chinese Unicode escape sequences that can never be produced by the LLM (which is already prompted to
emit English values). Remove exactly these four lines from the dict:

Find (lines 1135–1138):
```python
        gender_map = {
            "男": "male",
            "女": "female",
            "机构": "other",
            "其他": "other",
            # Already valid English values.
            "male": "male",
            "female": "female",
            "other": "other",
        }
```

Replace with:
```python
        gender_map = {
            "male": "male",
            "female": "female",
            "other": "other",
        }
```

Also update the comment above the dict from `# English-to-English mapping.` to `# Normalize to the
three accepted values; default to "other" for anything unrecognized.`
  </action>
  <verify>
Run: `grep -n "\\\\u7537\|\\\\u5973\|\\\\u673a\|\\\\u5176" backend/app/services/oasis_profile_generator.py`
Expected: no output (all four Unicode escapes are gone).
  </verify>
  <done>
- `_normalize_gender` contains exactly three entries: `"male"`, `"female"`, `"other"`.
- No Chinese Unicode escape sequences remain in the file.
  </done>
</task>

<task type="auto">
  <name>Task 1.2: Replace hardcoded Beijing timezone with SIMULATION_TIMEZONE env var</name>
  <files>backend/app/services/simulation_config_generator.py</files>
  <action>
There are multiple places where "Beijing time", "China routines", or "China daily routines" are
hardcoded as behavioral constraints. The fix is NOT to remove the sensible activity-hour defaults
(they are good defaults) but to:
1. Rename the module-level constant from `CHINA_TIMEZONE_CONFIG` to `DEFAULT_TIMEZONE_CONFIG`.
2. Update its docstring comment from `# China schedule configuration (Beijing time)` to
   `# Default timezone activity configuration — override via SIMULATION_TIMEZONE env var`.
3. In `Config` (backend/app/config.py), add:
   `SIMULATION_TIMEZONE = os.environ.get('SIMULATION_TIMEZONE', 'UTC')`
4. In `simulation_config_generator.py`, read timezone at the top of `__init__` or at module level:
   After the existing `from ..config import Config` import add:
   ```python
   import pytz  # already available in the environment via tzdata/pytz
   ```
   Then at the top of `SimulationConfigGenerator.__init__`, add:
   ```python
   self.timezone = Config.SIMULATION_TIMEZONE  # e.g. "UTC", "Asia/Shanghai"
   ```
5. In `_generate_time_config`, replace all occurrences of "Beijing-time daily routines" and
   "China daily routines" in the `prompt` string with:
   `"the configured timezone ({self.timezone}) and local daily routines"`
   Specifically replace these two prompt strings:
   - `"- The user population is assumed to follow Beijing-time daily routines."` →
     `"- The user population is assumed to follow local daily routines (timezone: {self.timezone})."`
   - In `system_prompt`: `"The time configuration should follow typical China daily routines."` →
     `"The time configuration should follow typical local daily routines (timezone: {self.timezone})."`
6. In `_get_default_time_config`, update the reasoning string:
   `"reasoning": "Use the default China routine configuration (1 hour per round)"` →
   `"reasoning": f"Default activity pattern for timezone {Config.SIMULATION_TIMEZONE} (1 hour per round)"`
7. In `_generate_agent_configs_batch`, replace:
   - `"- **Time behavior should follow typical China routines**"` →
     `"- **Time behavior should follow typical local routines (timezone: {self.timezone})**"`
   - `system_prompt = "... The configuration should follow typical China daily routines."` →
     `system_prompt = f"... The configuration should reflect local daily routines (timezone: {self.timezone})."`
8. In `_generate_agent_config_by_rule`, the docstring says "aligned to common China schedules" —
   update to `"aligned to default daily-activity patterns"`.
  </action>
  <verify>
Run: `grep -n "Beijing\|China routine\|China daily\|China schedule" backend/app/services/simulation_config_generator.py`
Expected: no matches (all hardcoded references replaced).
Run: `grep -n "SIMULATION_TIMEZONE" backend/app/config.py`
Expected: one line showing the new config entry.
  </verify>
  <done>
- `CHINA_TIMEZONE_CONFIG` is renamed to `DEFAULT_TIMEZONE_CONFIG`.
- No literal "Beijing" or "China routine" strings remain in prompts, comments, or system_prompt strings.
- `Config.SIMULATION_TIMEZONE` exists and defaults to `'UTC'`.
- `SimulationConfigGenerator` reads and uses `self.timezone` from Config.
  </done>
</task>

<task type="auto">
  <name>Task 1.7: Extract platform weights into Config</name>
  <files>backend/app/services/simulation_config_generator.py, backend/app/config.py</files>
  <action>
In `generate_config()` (lines 357–374), Twitter and Reddit `PlatformConfig` objects are built with
six magic numbers. Extract them into `Config` as class attributes with env-var overrides.

In `backend/app/config.py`, add a new section after the report agent settings block:

```python
    # Simulation platform configuration defaults.
    TWITTER_RECENCY_WEIGHT = float(os.environ.get('TWITTER_RECENCY_WEIGHT', '0.4'))
    TWITTER_POPULARITY_WEIGHT = float(os.environ.get('TWITTER_POPULARITY_WEIGHT', '0.3'))
    TWITTER_RELEVANCE_WEIGHT = float(os.environ.get('TWITTER_RELEVANCE_WEIGHT', '0.3'))
    TWITTER_VIRAL_THRESHOLD = int(os.environ.get('TWITTER_VIRAL_THRESHOLD', '10'))
    TWITTER_ECHO_CHAMBER_STRENGTH = float(os.environ.get('TWITTER_ECHO_CHAMBER_STRENGTH', '0.5'))

    REDDIT_RECENCY_WEIGHT = float(os.environ.get('REDDIT_RECENCY_WEIGHT', '0.3'))
    REDDIT_POPULARITY_WEIGHT = float(os.environ.get('REDDIT_POPULARITY_WEIGHT', '0.4'))
    REDDIT_RELEVANCE_WEIGHT = float(os.environ.get('REDDIT_RELEVANCE_WEIGHT', '0.3'))
    REDDIT_VIRAL_THRESHOLD = int(os.environ.get('REDDIT_VIRAL_THRESHOLD', '15'))
    REDDIT_ECHO_CHAMBER_STRENGTH = float(os.environ.get('REDDIT_ECHO_CHAMBER_STRENGTH', '0.6'))
```

In `generate_config()` in `simulation_config_generator.py`, replace the hardcoded `PlatformConfig`
constructor calls:

Find:
```python
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
```

Replace with:
```python
        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=Config.TWITTER_RECENCY_WEIGHT,
                popularity_weight=Config.TWITTER_POPULARITY_WEIGHT,
                relevance_weight=Config.TWITTER_RELEVANCE_WEIGHT,
                viral_threshold=Config.TWITTER_VIRAL_THRESHOLD,
                echo_chamber_strength=Config.TWITTER_ECHO_CHAMBER_STRENGTH,
            )

        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=Config.REDDIT_RECENCY_WEIGHT,
                popularity_weight=Config.REDDIT_POPULARITY_WEIGHT,
                relevance_weight=Config.REDDIT_RELEVANCE_WEIGHT,
                viral_threshold=Config.REDDIT_VIRAL_THRESHOLD,
                echo_chamber_strength=Config.REDDIT_ECHO_CHAMBER_STRENGTH,
            )
```
  </action>
  <verify>
Run: `grep -n "recency_weight=0\.\|popularity_weight=0\.\|viral_threshold=1[05]\|echo_chamber_strength=0\." backend/app/services/simulation_config_generator.py`
Expected: no output (all magic floats/ints replaced by Config references).
Run: `grep -c "TWITTER_VIRAL_THRESHOLD\|REDDIT_VIRAL_THRESHOLD" backend/app/config.py`
Expected: 2
  </verify>
  <done>
- `PlatformConfig` in `generate_config()` uses only `Config.*` references, no literal floats.
- Ten new Config attributes exist covering both platforms' five configurable parameters each.
- Defaults reproduce the original values exactly.
  </done>
</task>

</tasks>

<success_criteria>
1. `grep -n "\\\\u7537\|\\\\u5973\|\\\\u673a\|\\\\u5176" backend/app/services/oasis_profile_generator.py` returns nothing.
2. `grep -n "Beijing\|China routine\|China daily\|China schedule" backend/app/services/simulation_config_generator.py` returns nothing.
3. `grep -n "SIMULATION_TIMEZONE" backend/app/config.py` returns one match.
4. `grep -n "recency_weight=0\.\|viral_threshold=1[05]" backend/app/services/simulation_config_generator.py` returns nothing.
5. Backend imports without error: `cd backend && python -c "from app.services.simulation_config_generator import SimulationConfigGenerator; from app.services.oasis_profile_generator import OasisProfileGenerator; print('OK')"`.
</success_criteria>
