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
