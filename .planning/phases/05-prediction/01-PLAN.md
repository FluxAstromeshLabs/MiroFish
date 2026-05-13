---
phase: 05-prediction
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/services/prediction_extractor.py   # new
  - backend/app/api/report.py                      # add /predict endpoint (after line 24)
autonomous: true
must_haves:
  truths:
    - POST /api/report/predict returns {asset, horizon_hours, low, high, confidence, reasoning}
    - PredictionExtractor reads actions.jsonl via SimulationRunner.get_all_actions() (simulation_runner.py:889)
    - LLM extracts consensus price range from agent posts
  artifacts:
    - backend/app/services/prediction_extractor.py
    - POST /api/report/predict endpoint in report.py
  key_links:
    - SimulationRunner.get_all_actions(): simulation_runner.py:889
    - ReportAgent._define_tools(): report_agent.py:917
    - report.py blueprint: report.py:24
---

<objective>
Extract a structured price prediction from simulation output.
Agents discuss markets — this distills their posts into a low/high price range with confidence.
Output: New service + endpoint. No changes to simulation or ReportAgent.
</objective>

<context>
@.planning/ROADMAP.md
@.planning/research/PHASE-RESEARCH.md
@backend/app/services/simulation_runner.py
@backend/app/api/report.py
@backend/app/services/graph_builder.py
</context>

<tasks>

<task type="auto">
  <name>Task 5.1: Create PredictionExtractor service</name>
  <files>backend/app/services/prediction_extractor.py</files>
  <action>
Create backend/app/services/prediction_extractor.py:

```python
"""
PredictionExtractor — reads agent actions from a completed simulation,
uses an LLM to extract consensus price prediction (low, high, confidence).
"""
import json
from typing import Optional
from ..services.simulation_runner import SimulationRunner
from ..utils.logger import get_logger
from ..config import Config

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = get_logger('mirofish.prediction')


class PredictionExtractor:
    """Extract structured price prediction from simulation agent actions."""

    EXTRACT_PROMPT = """You are analyzing social media posts from a multi-agent crypto market simulation.
Your job is to extract the consensus price prediction from these agent posts.

Agent posts (newest last):
{posts}

Return ONLY valid JSON (no markdown) with this exact structure:
{{
  "low": <number>,
  "high": <number>,
  "confidence": <0.0-1.0>,
  "horizon_hours": <24 or 48 or 72>,
  "reasoning": "<one sentence summary of agent consensus>",
  "dissenting_views": "<brief note on minority opinion, or null>"
}}

Rules:
- low/high are USD prices (e.g. 95000, 102000)
- confidence: 0.9 = strong consensus, 0.5 = split, 0.3 = chaotic
- If agents mention no specific prices, infer from percentage moves and opening price
- Opening price context: {asset} opened at approximately ${open_price:,.0f}
"""

    def __init__(self, simulation_id: str, asset: str = "BTC", open_price: float = 0.0):
        self.simulation_id = simulation_id
        self.asset = asset
        self.open_price = open_price
        self._client = None

    def _get_llm_client(self):
        if self._client is None and OpenAI is not None:
            self._client = OpenAI(
                base_url=Config.LLM_BASE_URL if hasattr(Config, 'LLM_BASE_URL') else None,
                api_key=Config.OPENAI_API_KEY if hasattr(Config, 'OPENAI_API_KEY') else "sk-placeholder",
            )
        return self._client

    def _collect_posts(self, max_posts: int = 200) -> list[str]:
        """Collect agent post content from actions.jsonl via SimulationRunner."""
        try:
            actions = SimulationRunner.get_all_actions(self.simulation_id)
        except Exception as e:
            logger.warning(f"Could not load actions for {self.simulation_id}: {e}")
            return []

        posts = []
        for action in actions:
            # action_type: "post", "comment", "repost" etc.
            action_type = getattr(action, 'action_type', '')
            if action_type not in ('post', 'comment', 'CREATE_POST', 'CREATE_COMMENT'):
                continue
            args = getattr(action, 'action_args', {}) or {}
            content = args.get('content') or args.get('text') or args.get('body') or ''
            if content:
                agent_name = getattr(action, 'agent_name', 'agent')
                posts.append(f"[{agent_name}]: {content}")

        # Most recent posts are most relevant — take last max_posts
        return posts[-max_posts:]

    def extract(self) -> dict:
        """
        Run extraction. Returns prediction dict or error dict.
        """
        posts = self._collect_posts()
        if not posts:
            return {"error": "No agent posts found", "simulation_id": self.simulation_id}

        post_text = "\n".join(posts)
        prompt = self.EXTRACT_PROMPT.format(
            posts=post_text,
            asset=self.asset,
            open_price=self.open_price,
        )

        client = self._get_llm_client()
        if client is None:
            return {"error": "OpenAI client unavailable — install openai package"}

        try:
            model = Config.LLM_MODEL if hasattr(Config, 'LLM_MODEL') else "gpt-4o-mini"
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=400,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            prediction = json.loads(raw)
            prediction["asset"] = self.asset
            prediction["simulation_id"] = self.simulation_id
            prediction["posts_analyzed"] = len(posts)
            return prediction
        except Exception as e:
            logger.error(f"Prediction extraction failed: {e}")
            return {"error": str(e), "simulation_id": self.simulation_id}
```
  </action>
  <verify>
python3 -c "
from backend.app.services.prediction_extractor import PredictionExtractor
p = PredictionExtractor('test-sim-id', 'BTC', 95000.0)
print('PredictionExtractor OK')
print(p.EXTRACT_PROMPT[:60])
"
# Expected: PredictionExtractor OK, then first 60 chars of prompt
  </verify>
  <done>PredictionExtractor.extract() collects agent posts via get_all_actions() and calls LLM to return structured prediction dict.</done>
</task>

<task type="auto">
  <name>Task 5.2: Add POST /api/report/predict endpoint</name>
  <files>backend/app/api/report.py</files>
  <action>
In backend/app/api/report.py, after the existing imports (top of file), add:
```python
from ..services.prediction_extractor import PredictionExtractor
```

Then add a new route after the existing routes (find the last `@report_bp.route` block and add
after its function body ends):

```python
@report_bp.route('/predict', methods=['POST'])
def predict():
    """
    Extract structured price prediction from a completed simulation.
    Body: {
        "simulation_id": str,      # required
        "asset": str,              # e.g. "BTC", default "BTC"
        "open_price": float,       # asset price at simulation start, default 0
    }
    Returns: {
        "success": true,
        "data": {
            "low": float, "high": float, "confidence": float,
            "horizon_hours": int, "reasoning": str,
            "dissenting_views": str|null,
            "asset": str, "simulation_id": str, "posts_analyzed": int
        }
    }
    """
    data = request.get_json() or {}
    simulation_id = data.get('simulation_id')
    if not simulation_id:
        return jsonify({"success": False, "error": "simulation_id is required"}), 400

    asset = data.get('asset', 'BTC')
    open_price = float(data.get('open_price', 0))

    extractor = PredictionExtractor(simulation_id, asset=asset, open_price=open_price)
    result = extractor.extract()

    if "error" in result:
        return jsonify({"success": False, "error": result["error"]}), 500

    return jsonify({"success": True, "data": result})
```
  </action>
  <verify>
grep -n "def predict\|report/predict\|PredictionExtractor" backend/app/api/report.py
# Expected: 3 matches
  </verify>
  <done>POST /api/report/predict is live; returns 400 without body (proves route is registered).</done>
</task>

</tasks>

<success_criteria>
1. PredictionExtractor imports and instantiates without error
2. POST /api/report/predict with valid simulation_id returns {"success": true, "data": {"low": N, "high": N, ...}}
3. posts_analyzed > 0 when called after a completed simulation
</success_criteria>
