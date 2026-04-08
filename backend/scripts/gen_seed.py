"""
gen_seed — Flux Exchange API → seed.md (BTC Futures)
Fetches OHLCV, liquidations, and news from the Flux exchange HTTP API,
then writes a structured Markdown seed file.
"""

import os
import argparse
from datetime import datetime, timezone, timedelta

import requests

from common import project_root, resolve_path


# ── Time helpers ───────────────────────────────────────────────────────────

def day_bounds_ms(date_str):
    """Return (start_ms, end_ms) for a YYYY-MM-DD day in UTC (inclusive ms)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = int(dt.timestamp() * 1000)
    end = int((dt + timedelta(days=1)).timestamp() * 1000) - 1
    return start, end


def offset_day(date_str, delta):
    """Return YYYY-MM-DD string shifted by delta days (negative = earlier)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return (dt + timedelta(days=delta)).strftime("%Y-%m-%d")


# ── Formatters ─────────────────────────────────────────────────────────────

def _fmt_dollar(val):
    """Format a numeric string/float as $X.XM / $X.XK / $X."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:,.0f}"


def format_ohlcv(items_1d, items_4h, items_1h):
    """
    Build the # OHLCV section with ## 1H, ## 4H, ## 1D subsections.
    All rows sorted newest-first within each subsection.
    """
    def _hdr_1d():
        return f"{'Date':<10} | {'Open':>10} | {'High':>10} | {'Low':>10} | {'Close':>10} | {'Volume':>12}"

    def _hdr_sub():
        return f"{'Date/Time':<16} | {'Open':>10} | {'High':>10} | {'Low':>10} | {'Close':>10} | {'Volume':>12}"

    def _row_1d(item):
        dt = datetime.fromtimestamp(item["open_time_ms"] / 1000, tz=timezone.utc)
        return (
            f"{dt.strftime('%Y-%m-%d'):<10} | "
            f"{float(item['open']):>10,.2f} | "
            f"{float(item['high']):>10,.2f} | "
            f"{float(item['low']):>10,.2f} | "
            f"{float(item['close']):>10,.2f} | "
            f"{float(item['volume']):>12,.2f}"
        )

    def _row_sub(item):
        dt = datetime.fromtimestamp(item["open_time_ms"] / 1000, tz=timezone.utc)
        return (
            f"{dt.strftime('%Y-%m-%d %H:%M'):<16} | "
            f"{float(item['open']):>10,.2f} | "
            f"{float(item['high']):>10,.2f} | "
            f"{float(item['low']):>10,.2f} | "
            f"{float(item['close']):>10,.2f} | "
            f"{float(item['volume']):>12,.2f}"
        )

    def _section(label, hdr_fn, row_fn, items):
        sorted_items = sorted(items, key=lambda x: x["open_time_ms"], reverse=True)
        rows = [row_fn(i) for i in sorted_items]
        return "\n".join([f"## {label}", hdr_fn()] + rows)

    return "\n\n".join([
        "# OHLCV",
        _section("1H", _hdr_sub, _row_sub, items_1h),
        _section("4H", _hdr_sub, _row_sub, items_4h),
        _section("1D", _hdr_1d, _row_1d, items_1d),
    ])


def format_liquidations(liq_by_window):
    """
    Build the # Liquidations table.
    liq_by_window: {"1h": resp_dict, "4h": resp_dict, "12h": resp_dict, "24h": resp_dict}
    """
    header = f"{'Last':<4} | {'Long liq':>9} | {'Short liq':>10}"
    rows = []
    for label in ("1h", "4h", "12h", "24h"):
        data = liq_by_window[label]
        rows.append(
            f"{label:<4} | {_fmt_dollar(data.get('total_long', 0)):>9} | "
            f"{_fmt_dollar(data.get('total_short', 0)):>10}"
        )
    return "\n".join(["# Liquidations", header] + rows)


def format_news(items):
    """Build the # News table, newest-first."""
    header = f"{'Time':<16} | News"
    sorted_items = sorted(items, key=lambda x: x.get("timestamp_ms", 0), reverse=True)
    rows = []
    for item in sorted_items:
        dt = datetime.fromtimestamp(item["timestamp_ms"] / 1000, tz=timezone.utc)
        content = item.get("content", "").replace("\n", " ").strip()
        rows.append(f"{dt.strftime('%Y-%m-%d %H:%M'):<16} | {content}")
    if not rows:
        rows.append("(no news)")
    return "\n".join(["# News", header] + rows)
