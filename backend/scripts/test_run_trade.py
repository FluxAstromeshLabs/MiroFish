"""Tests for run_trade helpers."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from run_trade import strip_agents_section


def test_strip_agents_section_removes_section():
    seed = (
        "# OHLCV\n\n"
        "## 1H\n"
        "Date/Time        |       Open |\n"
        "2026-04-06 23:00 |  68,777.00 |\n\n"
        "# Liquidations\n"
        "Last |  Long liq |  Short liq\n"
        "1h   |   $231.0K |    $764.7K\n\n"
        "# Agents Population\n"
        "- quant1: Analytical, data-driven\n"
        "- scalper1: Hyper-focused\n"
    )
    result = strip_agents_section(seed)
    assert "# Agents Population" not in result
    assert "quant1" not in result
    assert "# OHLCV" in result
    assert "# Liquidations" in result
    assert "68,777.00" in result


def test_strip_agents_section_no_section():
    seed = "# OHLCV\n\n## 1H\nDate/Time | Open |\n2026-04-06 23:00 | 68777 |\n"
    result = strip_agents_section(seed)
    assert result == seed


def test_strip_agents_section_empty():
    assert strip_agents_section("") == ""


from run_trade import extract_latest_timestamp


def test_extract_latest_timestamp_from_ohlcv_table():
    # Rows are newest-first; first data row under ## 1H is the latest candle
    seed = (
        "# OHLCV\n\n"
        "## 1H\n"
        "Date/Time        |       Open |       High |        Low |      Close |       Volume\n"
        "2026-04-06 23:00 |  68,777.00 |  68,871.90 |  68,227.50 |  68,817.90 |    10,845.19\n"
        "2026-04-06 22:00 |  68,777.00 |  68,871.90 |  68,227.50 |  68,817.90 |     5,422.78\n"
    )
    # 2026-04-06 23:00 UTC = 1775516400
    assert extract_latest_timestamp(seed) == 1775516400


def test_extract_latest_timestamp_no_ohlcv_section():
    import time
    seed = "# Liquidations\nLast |  Long liq\n1h   |   $231.0K\n"
    result = extract_latest_timestamp(seed)
    assert abs(result - int(time.time())) < 5


def test_extract_latest_timestamp_single_row():
    seed = (
        "## 1H\n"
        "Date/Time        |       Open |\n"
        "2026-04-06 00:00 |  69,437.30 |\n"
    )
    # 2026-04-06 00:00 UTC = 1775433600
    assert extract_latest_timestamp(seed) == 1775433600


from run_trade import _parse_range, _fmt_forecast


def test_parse_range_valid():
    assert _parse_range("83000.5,85200.0") == (83000.5, 85200.0)


def test_parse_range_with_whitespace():
    assert _parse_range("  83000.5 , 85200.0  ") == (83000.5, 85200.0)


def test_parse_range_low_equals_high_invalid():
    assert _parse_range("83000.0,83000.0") is None


def test_parse_range_low_greater_than_high_invalid():
    assert _parse_range("85000.0,83000.0") is None


def test_parse_range_non_numeric_invalid():
    assert _parse_range("LONG,SHORT") is None


def test_parse_range_single_value_invalid():
    assert _parse_range("83000.5") is None


def test_parse_range_zero_invalid():
    assert _parse_range("0,85000.0") is None


def test_fmt_forecast():
    result = _fmt_forecast("quant1", 83000.5, 85200.0)
    assert "quant1" in result
    assert "83000.5" in result
    assert "85200.0" in result
