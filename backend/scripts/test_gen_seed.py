"""Tests for gen_seed CSV readers, aggregator, and formatters."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(__file__))

# ── Existing time-helper tests (keep unchanged) ────────────────────────────
from gen_seed import hour_bounds_ms, parse_hour
from datetime import datetime, timezone

def test_hour_bounds_ms():
    dt = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
    start, end = hour_bounds_ms(dt)
    assert start == 1775649600000
    assert end   == 1775653199999

def test_parse_hour_T():
    dt = parse_hour("2026-04-08T12")
    assert dt == datetime(2026, 4, 8, 12, tzinfo=timezone.utc)

def test_parse_hour_space():
    dt = parse_hour("2026-04-08 12")
    assert dt == datetime(2026, 4, 8, 12, tzinfo=timezone.utc)

# ── read_ohlcv_csv ─────────────────────────────────────────────────────────
from gen_seed import read_ohlcv_csv

def test_read_ohlcv_csv_basic():
    rows = "T,O,H,L,C,V\n1744113600000,69000,69500,68900,69100,5.5\n"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(rows)
        path = f.name
    result = read_ohlcv_csv(path)
    assert len(result) == 1
    assert result[0] == {
        "T": 1744113600000, "O": 69000.0, "H": 69500.0,
        "L": 68900.0, "C": 69100.0, "V": 5.5
    }
    os.unlink(path)

def test_read_ohlcv_csv_empty():
    rows = "T,O,H,L,C,V\n"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(rows)
        path = f.name
    assert read_ohlcv_csv(path) == []
    os.unlink(path)

def test_read_ohlcv_csv_missing_file():
    assert read_ohlcv_csv("/nonexistent/path.csv") == []

# ── read_liq_csv ───────────────────────────────────────────────────────────
from gen_seed import read_liq_csv

def test_read_liq_csv_basic():
    rows = "S,o,f,q,p,ap,X,l,z,T\nSELL,LIMIT,IOC,0.5,69000,69000,FILLED,0.5,0.5,1744113600000\n"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(rows)
        path = f.name
    result = read_liq_csv(path)
    assert len(result) == 1
    assert result[0] == {"S": "SELL", "q": 0.5, "p": 69000.0, "T": 1744113600000}
    os.unlink(path)

def test_read_liq_csv_missing_file():
    assert read_liq_csv("/nonexistent/path.csv") == []

# ── aggregate_1h ───────────────────────────────────────────────────────────
from gen_seed import aggregate_1h

# 3 one-minute candles: first two in 12:00 hour, one in 13:00 hour
# T values: 2026-04-08 12:00, 12:01, 13:00 UTC
_T_1200 = 1744113600000   # 2026-04-08 12:00 UTC
_T_1201 = 1744113660000   # 2026-04-08 12:01 UTC
_T_1300 = 1744117200000   # 2026-04-08 13:00 UTC

_RAW = [
    {"T": _T_1200, "O": 69000.0, "H": 69500.0, "L": 68900.0, "C": 69100.0, "V": 1.0},
    {"T": _T_1201, "O": 69100.0, "H": 69600.0, "L": 69000.0, "C": 69200.0, "V": 2.0},
    {"T": _T_1300, "O": 69200.0, "H": 69700.0, "L": 69100.0, "C": 69300.0, "V": 3.0},
]

def test_aggregate_1h_count():
    result = aggregate_1h(_RAW)
    assert len(result) == 2

def test_aggregate_1h_open_is_first():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["O"] == 69000.0

def test_aggregate_1h_close_is_last():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["C"] == 69200.0

def test_aggregate_1h_high_is_max():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["H"] == 69600.0

def test_aggregate_1h_low_is_min():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["L"] == 68900.0

def test_aggregate_1h_volume_is_sum():
    result = aggregate_1h(_RAW)
    candle_1200 = next(c for c in result if c["T"] == _T_1200)
    assert candle_1200["V"] == 3.0

def test_aggregate_1h_empty():
    assert aggregate_1h([]) == []


# ── load_ohlcv_window / load_liq_window ───────────────────────────────────
from gen_seed import load_ohlcv_window, load_liq_window

def _make_marketdata(tmp_path, day_str, ohlcv_rows=None, liq_rows=None):
    """Helper: create a marketdata/YYYY-MM-DD/ dir with optional CSV files."""
    day_dir = os.path.join(str(tmp_path), day_str)
    os.makedirs(day_dir, exist_ok=True)
    if ohlcv_rows is not None:
        with open(os.path.join(day_dir, "ohlcv.csv"), "w") as f:
            f.write("T,O,H,L,C,V\n")
            for r in ohlcv_rows:
                f.write(",".join(str(x) for x in r) + "\n")
    if liq_rows is not None:
        with open(os.path.join(day_dir, "liq.csv"), "w") as f:
            f.write("S,o,f,q,p,ap,X,l,z,T\n")
            for r in liq_rows:
                f.write(",".join(str(x) for x in r) + "\n")
    return tmp_path

# end_dt = 2026-04-08 12:00 UTC, hours=2 → window: 11:00–12:00
_END_DT = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
_T_1100 = 1775646000000   # 2026-04-08 11:00 UTC
_T_1200 = 1775649600000   # 2026-04-08 12:00 UTC

def test_load_ohlcv_window_filters_by_time(tmp_path):
    _make_marketdata(tmp_path, "2026-04-08", ohlcv_rows=[
        [_T_1100, 69000, 69500, 68900, 69100, 1.0],   # in window
        [_T_1200, 69100, 69600, 69000, 69200, 2.0],   # in window
        [1775656800000, 69200, 69700, 69100, 69300, 3.0],  # 14:00 — out of window
    ])
    result = load_ohlcv_window(str(tmp_path), _END_DT, hours=2)
    assert len(result) == 2

def test_load_ohlcv_window_missing_dir(tmp_path):
    result = load_ohlcv_window(str(tmp_path), _END_DT, hours=2)
    assert result == []

def test_load_liq_window_sums(tmp_path):
    _make_marketdata(tmp_path, "2026-04-08", liq_rows=[
        ["SELL", "LIMIT", "IOC", 0.5, 69000, 69000, "FILLED", 0.5, 0.5, _T_1100],  # long liq
        ["BUY",  "LIMIT", "IOC", 1.0, 68000, 68000, "FILLED", 1.0, 1.0, _T_1200],  # short liq
    ])
    result = load_liq_window(str(tmp_path), _END_DT, hours=2)
    assert abs(result["long"]  - 0.5 * 69000) < 0.01
    assert abs(result["short"] - 1.0 * 68000) < 0.01

def test_load_liq_window_empty(tmp_path):
    result = load_liq_window(str(tmp_path), _END_DT, hours=2)
    assert result == {"long": 0.0, "short": 0.0}


# ── new formatters ─────────────────────────────────────────────────────────
from gen_seed import format_chart_time, format_btc_price, format_ohlcv_json, format_liquidations_json

_CANDLES = [
    {"T": 1775649600000, "O": 69000.0, "H": 69500.0, "L": 68900.0, "C": 69100.0, "V": 5.5},
    {"T": 1775653200000, "O": 69100.0, "H": 69600.0, "L": 69000.0, "C": 69200.0, "V": 3.2},
]

def test_format_chart_time():
    dt = datetime(2026, 4, 8, 12, tzinfo=timezone.utc)
    assert format_chart_time(dt) == "# Latest Chart Time\n2026-04-08 12:00"

def test_format_btc_price():
    # last candle newest-first is _CANDLES[1] after sort, close=69200
    assert format_btc_price(_CANDLES) == "# Latest BTC Price\n69200.0"

def test_format_ohlcv_json_section_header():
    result = format_ohlcv_json(_CANDLES)
    assert result.startswith("# OHLCV 1H")

def test_format_ohlcv_json_is_valid_json():
    result = format_ohlcv_json(_CANDLES)
    json_part = result[result.index("["):]
    parsed = json.loads(json_part)
    assert len(parsed) == 2

def test_format_ohlcv_json_newest_first():
    result = format_ohlcv_json(_CANDLES)
    json_part = result[result.index("["):]
    parsed = json.loads(json_part)
    assert parsed[0]["time"] == "2026-04-08 13:00"
    assert parsed[1]["time"] == "2026-04-08 12:00"

def test_format_ohlcv_json_fields():
    result = format_ohlcv_json(_CANDLES)
    json_part = result[result.index("["):]
    parsed = json.loads(json_part)
    assert set(parsed[0].keys()) == {"time", "open", "high", "low", "close", "volume"}

def test_format_liquidations_json():
    result = format_liquidations_json({"long": 3_200_000.0, "short": 1_400_000.0})
    assert result.startswith("# Liquidations")
    json_part = result[result.index("{"):]
    parsed = json.loads(json_part)
    assert parsed["long"] == 3_200_000.0
    assert parsed["short"] == 1_400_000.0
