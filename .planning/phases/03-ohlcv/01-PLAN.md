---
phase: 03-ohlcv
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/services/ohlcv_processor.py   # new
  - backend/app/api/ohlcv.py                  # new
  - backend/app/api/__init__.py               # add ohlcv_bp (lines 7-13 pattern)
  - backend/app/__init__.py                   # register blueprint (lines 66-69 pattern)
autonomous: true
must_haves:
  truths:
    - OHLCV CSV rows (T,O,H,L,C,V Unix-ms timestamps) are converted to readable narrative text
    - Narrative text is chunked and ingested into Zep via GraphBuilderService.add_text_batches() (graph_builder.py:288)
    - POST /api/ohlcv/ingest accepts {graph_id, file_path OR candles[], asset, interval}
  artifacts:
    - ohlcv_processor.py with OHLCVProcessor class
    - ohlcv.py blueprint with /ingest endpoint
    - blueprint registered
  key_links:
    - OHLCVProcessor.to_episodes() → list of narrative strings
    - GraphBuilderService.add_text_batches(graph_id, episodes) at graph_builder.py:288,312-315
    - EpisodeData(data=chunk, type="text") — graph_builder.py:313
---

<objective>
Build the data bridge: OHLCV candles → narrative text → Zep knowledge graph episodes.

Purpose: Agents can now "know" price history and use it to form opinions.
Output: New service + API endpoint. GraphBuilderService unchanged.
</objective>

<context>
@.planning/ROADMAP.md
@.planning/research/PHASE-RESEARCH.md
@backend/app/services/graph_builder.py
@backend/app/api/__init__.py
@backend/app/__init__.py
</context>

<tasks>

<task type="auto">
  <name>Task 3.1: Create OHLCVProcessor service</name>
  <files>backend/app/services/ohlcv_processor.py</files>
  <action>
Create backend/app/services/ohlcv_processor.py.

Key method: `to_episodes(candles, asset, interval_minutes) -> List[str]`
- Groups candles into windows (e.g. 4 candles → 4h window for 1h interval)
- For each window, produces a narrative string like:
  "BTC price action 14:00-18:00 UTC 2026-04-01: opened at $95,200, high $97,800, low $94,100, closed at $97,400 (+2.3%). Volume: 1,842 BTC (1.8x 7-day average). Notable: new local high established."
- Calculates % change, volume ratio vs rolling average, flags significant moves (>2%)

```python
import csv, io
from datetime import datetime, timezone
from typing import List, Tuple

class OHLCVProcessor:
    SIGNIFICANT_MOVE_PCT = 2.0  # flag moves larger than this

    def candles_from_csv(self, csv_text: str) -> List[Tuple]:
        """Parse CSV string with header T,O,H,L,C,V → list of (ts_ms, o, h, l, c, v) tuples."""
        reader = csv.DictReader(io.StringIO(csv_text))
        candles = []
        for row in reader:
            candles.append((
                int(row['T']),
                float(row['O']),
                float(row['H']),
                float(row['L']),
                float(row['C']),
                float(row['V']),
            ))
        return sorted(candles, key=lambda x: x[0])

    def to_episodes(self, candles: List[Tuple], asset: str = "BTC",
                    window_size: int = 4) -> List[str]:
        """
        Convert candles into narrative text episodes.
        window_size: number of candles to group per episode (default 4 → 4h windows for 1h candles)
        """
        if not candles:
            return []

        # Compute rolling volume average for context
        volumes = [c[5] for c in candles]
        avg_volume = sum(volumes) / len(volumes) if volumes else 1.0

        episodes = []
        for i in range(0, len(candles), window_size):
            window = candles[i:i + window_size]
            if not window:
                continue

            ts_start = datetime.fromtimestamp(window[0][0] / 1000, tz=timezone.utc)
            ts_end = datetime.fromtimestamp(window[-1][0] / 1000, tz=timezone.utc)
            open_price = window[0][1]
            close_price = window[-1][4]
            high = max(c[2] for c in window)
            low = min(c[3] for c in window)
            total_volume = sum(c[5] for c in window)
            pct_change = ((close_price - open_price) / open_price) * 100
            vol_ratio = total_volume / (avg_volume * window_size) if avg_volume > 0 else 1.0

            direction = "up" if pct_change >= 0 else "down"
            sign = "+" if pct_change >= 0 else ""

            notes = []
            if abs(pct_change) >= self.SIGNIFICANT_MOVE_PCT:
                notes.append(f"significant {direction}move of {sign}{pct_change:.1f}%")
            if vol_ratio >= 2.0:
                notes.append(f"very high volume ({vol_ratio:.1f}x average)")
            elif vol_ratio <= 0.5:
                notes.append("unusually low volume")

            note_str = f" Notable: {'; '.join(notes)}." if notes else ""

            episode = (
                f"{asset} price action "
                f"{ts_start.strftime('%H:%M')}-{ts_end.strftime('%H:%M')} UTC "
                f"{ts_start.strftime('%Y-%m-%d')}: "
                f"opened at ${open_price:,.0f}, "
                f"high ${high:,.0f}, low ${low:,.0f}, "
                f"closed at ${close_price:,.0f} ({sign}{pct_change:.1f}%). "
                f"Volume: {total_volume:,.0f} {asset} ({vol_ratio:.1f}x average).{note_str}"
            )
            episodes.append(episode)

        return episodes
```
  </action>
  <verify>
python3 -c "
from backend.app.services.ohlcv_processor import OHLCVProcessor
p = OHLCVProcessor()
candles = [(1000*60*i, 100+i, 102+i, 99+i, 101+i, 500.0) for i in range(8)]
eps = p.to_episodes(candles, 'BTC', 4)
print(f'Episodes: {len(eps)}')
print(eps[0][:80])
"
# Expected: Episodes: 2, first episode starts with "BTC price action"
  </verify>
  <done>OHLCVProcessor.to_episodes() returns narrative strings for each window of candles.</done>
</task>

<task type="auto">
  <name>Task 3.2: Create /api/ohlcv/ingest endpoint</name>
  <files>backend/app/api/ohlcv.py, backend/app/api/__init__.py, backend/app/__init__.py</files>
  <action>
Create backend/app/api/ohlcv.py:

```python
from flask import Blueprint, request, jsonify
from ..services.ohlcv_processor import OHLCVProcessor
from ..services.graph_builder import GraphBuilderService
from ..utils.logger import get_logger

ohlcv_bp = Blueprint('ohlcv', __name__)
logger = get_logger('mirofish.ohlcv')

@ohlcv_bp.route('/ingest', methods=['POST'])
def ingest_ohlcv():
    """
    Ingest OHLCV data into Zep knowledge graph.
    Body: {
        "graph_id": str,           # required
        "asset": str,              # e.g. "BTC", default "BTC"
        "csv_text": str,           # raw CSV string with T,O,H,L,C,V header
        "window_size": int,        # candles per episode, default 4
    }
    """
    data = request.get_json() or {}
    graph_id = data.get('graph_id')
    csv_text = data.get('csv_text')
    if not graph_id or not csv_text:
        return jsonify({"success": False, "error": "graph_id and csv_text are required"}), 400

    asset = data.get('asset', 'BTC')
    window_size = data.get('window_size', 4)

    try:
        processor = OHLCVProcessor()
        candles = processor.candles_from_csv(csv_text)
        episodes = processor.to_episodes(candles, asset=asset, window_size=window_size)

        if not episodes:
            return jsonify({"success": False, "error": "No candles parsed from CSV"}), 400

        builder = GraphBuilderService(graph_id=graph_id)
        # add_text_batches() at graph_builder.py:288 — ingests list of text strings as Zep episodes
        builder.add_text_batches(episodes)

        logger.info(f"Ingested {len(episodes)} OHLCV episodes for {asset} into graph {graph_id}")
        return jsonify({
            "success": True,
            "data": {
                "episodes_ingested": len(episodes),
                "candles_processed": len(candles),
                "asset": asset,
            }
        })
    except Exception as e:
        logger.error(f"OHLCV ingest failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
```

In backend/app/api/__init__.py, add after existing imports (line 13):
```python
from .ohlcv import ohlcv_bp
```

In backend/app/__init__.py, add after existing blueprint registrations (line 69):
```python
from .api import ohlcv_bp
app.register_blueprint(ohlcv_bp, url_prefix='/api/ohlcv')
```
  </action>
  <verify>
grep -n "ohlcv_bp" backend/app/api/__init__.py backend/app/__init__.py backend/app/api/ohlcv.py
# Expected: 1 match per file (3 total)
  </verify>
  <done>POST /api/ohlcv/ingest returns 400 without body (route is live). With valid graph_id + csv_text returns episodes_ingested count.</done>
</task>

</tasks>

<success_criteria>
1. OHLCVProcessor.to_episodes() converts candles to human-readable narrative strings
2. POST /api/ohlcv/ingest with graph_id + csv_text returns {"success": true, "data": {"episodes_ingested": N}}
3. Episodes appear in Zep graph (verify by calling GET /api/graph/nodes?graph_id=X and checking for price-related content)
</success_criteria>
