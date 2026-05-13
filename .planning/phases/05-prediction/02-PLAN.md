---
phase: 05-prediction
plan: 02
type: execute
wave: 2
depends_on: [05-prediction/01-PLAN.md]
files_modified:
  - backend/app/services/backtester.py        # new
  - backend/app/api/pipeline.py               # add /backtest endpoint
  - backend/scripts/run_pipeline.py           # add --backtest flag
autonomous: true
must_haves:
  truths:
    - Backtester scores prediction {low, high} against actual OHLCV CSV
    - Scores: pct_in_range, max_deviation_pct, direction_correct, grade (A/B/C/F)
    - POST /api/pipeline/backtest accepts prediction + csv_text, returns score
    - run_pipeline.py --backtest flag calls /predict then /backtest and prints result
  artifacts:
    - backend/app/services/backtester.py with Backtester class
    - POST /api/pipeline/backtest in pipeline.py
    - --backtest flag in run_pipeline.py
  key_links:
    - OHLCVProcessor.candles_from_csv(): ohlcv_processor.py (Phase 3)
    - PredictionExtractor.extract(): prediction_extractor.py (Plan 01 of this phase)
    - pipeline.py: /api/pipeline/run (Phase 2 Plan 01)
---

<objective>
Score simulation predictions against real price data.
Lets us answer: "Was the simulation right?" and iterate on what makes it better.
Output: Backtester service + endpoint + CLI flag.
</objective>

<context>
@.planning/ROADMAP.md
@.planning/phases/05-prediction/01-PLAN.md
@backend/app/services/ohlcv_processor.py
@backend/app/api/pipeline.py
@backend/scripts/run_pipeline.py
</context>

<tasks>

<task type="auto">
  <name>Task 5.3: Create Backtester service</name>
  <files>backend/app/services/backtester.py</files>
  <action>
Create backend/app/services/backtester.py:

```python
"""
Backtester — scores a price prediction against actual OHLCV candles.

Metrics:
  pct_in_range    — % of candles whose close was within [low, high]
  max_deviation   — worst close deviation from nearest range boundary (%)
  direction_correct — True if close > open matches prediction direction
  grade           — A (≥80% in range), B (60-79%), C (40-59%), F (<40%)
"""
from typing import Tuple
from .ohlcv_processor import OHLCVProcessor


class Backtester:
    def __init__(self, prediction: dict):
        """
        prediction: dict with at minimum {"low": float, "high": float}
        Typically from PredictionExtractor.extract() output.
        """
        self.low = float(prediction["low"])
        self.high = float(prediction["high"])
        self.asset = prediction.get("asset", "BTC")
        self.prediction = prediction

    def score_csv(self, csv_text: str) -> dict:
        """
        Score against raw CSV string (T,O,H,L,C,V format, same as OHLCVProcessor).
        Returns backtest result dict.
        """
        processor = OHLCVProcessor()
        candles = processor.candles_from_csv(csv_text)
        return self.score_candles(candles)

    def score_candles(self, candles: list) -> dict:
        """
        Score against list of (ts_ms, o, h, l, c, v) tuples.
        """
        if not candles:
            return {"error": "No candles provided"}

        in_range = 0
        max_dev = 0.0
        closes = [c[4] for c in candles]

        for close in closes:
            if self.low <= close <= self.high:
                in_range += 1
            else:
                # How far outside the range?
                if close < self.low:
                    dev = (self.low - close) / self.low * 100
                else:
                    dev = (close - self.high) / self.high * 100
                max_dev = max(max_dev, dev)

        pct_in_range = in_range / len(closes) * 100

        # Direction: did the asset go up or down overall?
        open_price = candles[0][1]
        final_close = candles[-1][4]
        actual_direction = "up" if final_close >= open_price else "down"
        pred_direction = "up" if self.high >= open_price else "down"
        direction_correct = actual_direction == pred_direction

        # Grade
        if pct_in_range >= 80:
            grade = "A"
        elif pct_in_range >= 60:
            grade = "B"
        elif pct_in_range >= 40:
            grade = "C"
        else:
            grade = "F"

        return {
            "asset": self.asset,
            "prediction_low": self.low,
            "prediction_high": self.high,
            "actual_open": round(open_price, 2),
            "actual_final_close": round(final_close, 2),
            "candles_total": len(closes),
            "candles_in_range": in_range,
            "pct_in_range": round(pct_in_range, 1),
            "max_deviation_pct": round(max_dev, 2),
            "direction_correct": direction_correct,
            "actual_direction": actual_direction,
            "grade": grade,
            "summary": (
                f"Prediction: ${self.low:,.0f}-${self.high:,.0f} | "
                f"Actual: ${final_close:,.2f} | "
                f"In range: {pct_in_range:.0f}% | "
                f"Grade: {grade} {'✓' if grade in ('A','B') else '✗'}"
            ),
        }
```
  </action>
  <verify>
python3 -c "
from backend.app.services.backtester import Backtester
pred = {'low': 95000, 'high': 102000, 'asset': 'BTC'}
b = Backtester(pred)
# Synthetic candles: all closes inside range
candles = [(i*60000, 98000, 99000, 97000, 98500, 10.0) for i in range(24)]
r = b.score_candles(candles)
print(r['grade'], r['pct_in_range'])
"
# Expected: A 100.0
  </verify>
  <done>Backtester.score_candles() returns grade/pct_in_range/direction_correct/summary.</done>
</task>

<task type="auto">
  <name>Task 5.4: Add POST /api/pipeline/backtest endpoint</name>
  <files>backend/app/api/pipeline.py</files>
  <action>
In backend/app/api/pipeline.py, add imports at the top:
```python
from ..services.prediction_extractor import PredictionExtractor
from ..services.backtester import Backtester
```

Add route after the existing `/status/<id>` route:

```python
@pipeline_bp.route('/backtest', methods=['POST'])
def pipeline_backtest():
    """
    Run prediction extraction then score against actual OHLCV.
    Body: {
        "simulation_id": str,   # required — completed sim to extract prediction from
        "csv_text": str,        # required — actual OHLCV CSV (T,O,H,L,C,V)
        "asset": str,           # default "BTC"
        "open_price": float,    # asset price at sim start, default 0
    }
    Returns: {
        "success": true,
        "data": { ...prediction..., ...backtest_score... }
    }
    """
    data = request.get_json() or {}
    simulation_id = data.get('simulation_id')
    csv_text = data.get('csv_text')
    if not simulation_id or not csv_text:
        return jsonify({"success": False, "error": "simulation_id and csv_text required"}), 400

    asset = data.get('asset', 'BTC')
    open_price = float(data.get('open_price', 0))

    # Extract prediction
    extractor = PredictionExtractor(simulation_id, asset=asset, open_price=open_price)
    prediction = extractor.extract()
    if "error" in prediction:
        return jsonify({"success": False, "error": prediction["error"]}), 500

    # Score against actual candles
    backtester = Backtester(prediction)
    score = backtester.score_csv(csv_text)
    if "error" in score:
        return jsonify({"success": False, "error": score["error"]}), 400

    return jsonify({"success": True, "data": {**prediction, **score}})
```
  </action>
  <verify>
grep -n "def pipeline_backtest\|PredictionExtractor\|Backtester" backend/app/api/pipeline.py
# Expected: 3 matches
  </verify>
  <done>POST /api/pipeline/backtest is live.</done>
</task>

<task type="auto">
  <name>Task 5.5: Add --backtest flag to run_pipeline.py</name>
  <files>backend/scripts/run_pipeline.py</files>
  <action>
In backend/scripts/run_pipeline.py, add these args to the argparse block:
```python
    parser.add_argument("--backtest", action="store_true",
                        help="After simulation, extract prediction and score against --ohlcv-file")
    parser.add_argument("--ohlcv-file", default=None,
                        help="Path to actual OHLCV CSV for backtesting")
    parser.add_argument("--open-price", type=float, default=0.0,
                        help="Asset open price at simulation start")
    parser.add_argument("--asset", default="BTC",
                        help="Asset ticker (e.g. BTC, ETH, SOL)")
```

After the simulation completes (after the `print("[pipeline] ✓ Done")` line), add:
```python
    # Optional backtest
    if args.backtest:
        if not args.ohlcv_file:
            print("[backtest] --ohlcv-file required for --backtest")
            sys.exit(1)
        with open(args.ohlcv_file) as f:
            csv_text = f.read()
        print(f"[backtest] Scoring prediction for {args.asset}...")
        r = requests.post(f"{base}/api/pipeline/backtest", json={
            "simulation_id": args.simulation_id,
            "csv_text": csv_text,
            "asset": args.asset,
            "open_price": args.open_price,
        }, timeout=60)
        bt = r.json()
        if bt.get("success"):
            d = bt["data"]
            print(f"[backtest] {d.get('summary', 'No summary')}")
            print(f"[backtest] Direction correct: {d.get('direction_correct')}")
        else:
            print(f"[backtest] Failed: {bt.get('error')}")
```
  </action>
  <verify>
python3 backend/scripts/run_pipeline.py --help | grep -E "backtest|ohlcv-file|open-price|asset"
# Expected: 4 lines (one per flag)
  </verify>
  <done>run_pipeline.py --backtest --ohlcv-file path/to/actual.csv prints prediction score and grade.</done>
</task>

</tasks>

<success_criteria>
1. Backtester({"low": 95000, "high": 102000}).score_candles([...]) returns grade A for all-in-range candles
2. POST /api/pipeline/backtest returns {"success": true, "data": {"grade": "A"|"B"|..., "summary": "..."}}
3. python3 run_pipeline.py --help shows --backtest, --ohlcv-file, --open-price, --asset flags
4. Full loop: run_pipeline.py --backtest --ohlcv-file actual.csv prints "Prediction: $X-$Y | Grade: B ✓"
</success_criteria>
