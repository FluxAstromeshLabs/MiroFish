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
