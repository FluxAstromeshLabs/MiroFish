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
