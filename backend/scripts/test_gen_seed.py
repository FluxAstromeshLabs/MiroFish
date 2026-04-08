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


from gen_seed import _fmt_dollar, format_ohlcv, format_liquidations, format_news


# ── _fmt_dollar ────────────────────────────────────────────────────────────

def test_fmt_dollar_millions():
    assert _fmt_dollar("2427609.985") == "$2.4M"


def test_fmt_dollar_thousands():
    assert _fmt_dollar("303436.72") == "$303.4K"


def test_fmt_dollar_small():
    assert _fmt_dollar("500") == "$500"


def test_fmt_dollar_zero():
    assert _fmt_dollar("0") == "$0"


def test_fmt_dollar_invalid():
    assert _fmt_dollar(None) == "N/A"


# ── format_ohlcv ───────────────────────────────────────────────────────────

OHLCV_ITEM_OLD = {
    "open_time_ms": 1775347200000,  # 2026-04-05 00:00 UTC
    "open": "82900", "high": "83600", "low": "82400", "close": "83100", "volume": "10800",
}
OHLCV_ITEM_NEW = {
    "open_time_ms": 1775433600000,  # 2026-04-06 00:00 UTC
    "open": "83100", "high": "84200", "low": "82800", "close": "83900", "volume": "11200",
}


def test_format_ohlcv_starts_with_header():
    result = format_ohlcv([OHLCV_ITEM_NEW], [], [])
    assert result.startswith("# OHLCV")


def test_format_ohlcv_1d_section():
    result = format_ohlcv([OHLCV_ITEM_NEW], [], [])
    assert "## 1D" in result
    assert "2026-04-06" in result


def test_format_ohlcv_1d_newest_first():
    result = format_ohlcv([OHLCV_ITEM_OLD, OHLCV_ITEM_NEW], [], [])
    idx_new = result.index("2026-04-06")
    idx_old = result.index("2026-04-05")
    assert idx_new < idx_old, "Newest row should appear before older row"


def test_format_ohlcv_section_order():
    result = format_ohlcv([], [], [])
    assert "## 1H" in result
    assert "## 4H" in result
    assert "## 1D" in result
    # 1H appears before 4H, 4H before 1D
    assert result.index("## 1H") < result.index("## 4H") < result.index("## 1D")


# ── format_liquidations ────────────────────────────────────────────────────

LIQ_DATA = {
    "1h":  {"total_long": "2427609.985", "total_short": "2085172.725", "count": 1, "items": []},
    "4h":  {"total_long": "9500000",     "total_short": "8200000",     "count": 5, "items": []},
    "12h": {"total_long": "28000000",    "total_short": "21000000",    "count": 18, "items": []},
    "24h": {"total_long": "55000000",    "total_short": "43000000",    "count": 32, "items": []},
}


def test_format_liquidations_header():
    result = format_liquidations(LIQ_DATA)
    assert result.startswith("# Liquidations")


def test_format_liquidations_all_windows():
    result = format_liquidations(LIQ_DATA)
    for label in ("1h", "4h", "12h", "24h"):
        assert label in result


def test_format_liquidations_values():
    result = format_liquidations(LIQ_DATA)
    assert "$2.4M" in result   # 1h long
    assert "$2.1M" in result   # 1h short


# ── format_news ────────────────────────────────────────────────────────────

NEWS_ITEMS = [
    {"timestamp_ms": 1775458200000, "content": "Fed signals pause in rate hikes"},   # ~08:30 UTC
    {"timestamp_ms": 1775480400000, "content": "MicroStrategy buys 500 BTC"},        # ~14:40 UTC
]


def test_format_news_header():
    result = format_news(NEWS_ITEMS)
    assert result.startswith("# News")
    assert "Time" in result


def test_format_news_newest_first():
    result = format_news(NEWS_ITEMS)
    idx_later = result.index("MicroStrategy")
    idx_earlier = result.index("Fed signals")
    assert idx_later < idx_earlier, "Newer news should appear before older news"


def test_format_news_empty():
    result = format_news([])
    assert "(no news)" in result
