"""Tests for gen_seed time helpers and formatters."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from gen_seed import day_bounds_ms, offset_day


def test_day_bounds_ms_start():
    start, _ = day_bounds_ms("2026-04-06")
    assert start == 1775433600000  # 2026-04-06 00:00:00 UTC in ms


def test_day_bounds_ms_end():
    _, end = day_bounds_ms("2026-04-06")
    assert end == 1775519999999  # 2026-04-06 23:59:59.999 UTC in ms


def test_day_bounds_ms_span():
    start, end = day_bounds_ms("2026-04-06")
    assert end - start == 86_400_000 - 1


def test_offset_day_negative():
    assert offset_day("2026-04-06", -2) == "2026-04-04"


def test_offset_day_positive():
    assert offset_day("2026-04-06", 1) == "2026-04-07"


def test_offset_day_zero():
    assert offset_day("2026-04-06", 0) == "2026-04-06"
