"""
gen_seed — Market Data CSV → seed.md
Reads raw market data CSVs (bbo, liq, oi, trade), computes stats,
uses LLM to generate a Futures Market Report, and writes seed.md.
"""

import os
import sys
import json
import argparse
from datetime import datetime

import pandas as pd

from common import project_root, resolve_path, LLMClient


# ============== Default Agents ==============

DEFAULT_AGENTS = """\
1. master1 - Veteran quant trader, 10 years experience, manages a $5M crypto book. Calm, analytical, uses technical analysis and order book data.
2. master2 - Former institutional desk trader turned independent. Disciplined risk manager. Rarely trades on emotion.
3. fomo1 - 26-year-old crypto influencer with 200K followers. Constantly watching his phone. Jumps in on pumps based on Twitter hype.
4. fomo2 - Office worker who started trading in 2024. Follows crypto YouTubers. Panic-buys after seeing green candles on his phone notifications.
5. dummy1 - Retired electrician, first crypto trade. Heard about Bitcoin from his son. Completely random decisions.
6. dummy2 - Nurse, bought Bitcoin at the peak in 2021 and sold at a loss. Trying again. Emotional, uncertain."""


# ============== CSV Loading ==============

def load_csv(filepath, window_hours):
    """Load CSV and filter to rows within the time window."""
    df = pd.read_csv(filepath)
    total_rows = len(df)

    if total_rows == 0:
        return df, 0

    # Parse timestamp: unix ms or ISO format
    try:
        df['T'] = pd.to_datetime(pd.to_numeric(df['T']), unit='ms', utc=True)
    except (ValueError, TypeError):
        df['T'] = pd.to_datetime(df['T'], utc=True)

    # Filter by window
    cutoff = df['T'].max() - pd.Timedelta(hours=window_hours)
    filtered = df[df['T'] >= cutoff].copy()
    return filtered, total_rows


# ============== Preprocessing ==============

def _process_bbo(data_dir, _window_hours=None):
    """Extract best bid/offer stats from the latest bbo.csv row."""
    path = os.path.join(data_dir, 'bbo.csv')
    if not os.path.exists(path):
        return {}, None
    df = pd.read_csv(path)
    total = len(df)
    if total == 0:
        return {}, ('bbo.csv', (0, 1))
    last = df.dropna(subset=['a', 'b']).iloc[-1]
    stats = {
        'current_price': round((last['a'] + last['b']) / 2, 2),
        'best_ask': float(last['a']),
        'best_ask_qty': float(last['A']),
        'best_bid': float(last['b']),
        'best_bid_qty': float(last['B']),
        'spread': round(last['a'] - last['b'], 2),
    }
    return stats, ('bbo.csv', (total, 1))


def _process_trades(data_dir, window_hours):
    """Compute trade stats (volume, VWAP, taker ratio) from trade.csv."""
    path = os.path.join(data_dir, 'trade.csv')
    if not os.path.exists(path):
        return {}, None
    trade, total = load_csv(path, window_hours)
    if len(trade) == 0:
        return {}, ('trade.csv', (total, 0))

    trade['value'] = trade['p'] * trade['q']

    taker = trade[trade['m'].astype(str).str.lower() == 'false']
    taker_buy = taker[taker['s'].str.upper() == 'BUY']
    taker_sell = taker[taker['s'].str.upper() == 'SELL']

    buy_vol = round(taker_buy['value'].sum(), 2)
    sell_vol = round(taker_sell['value'].sum(), 2)
    total_qty = trade['q'].sum()

    largest = trade.loc[trade['value'].idxmax()]

    stats = {
        'taker_volume': round(taker['value'].sum(), 2),
        'taker_buy_volume': buy_vol,
        'taker_sell_volume': sell_vol,
        'taker_buy_sell_ratio': round(buy_vol / sell_vol, 2) if sell_vol > 0 else None,
        'vwap': round(trade['value'].sum() / total_qty, 2) if total_qty > 0 else None,
        'high': float(trade['p'].max()),
        'low': float(trade['p'].min()),
        'num_trades': len(trade),
        'largest_trade': {
            'price': float(largest['p']),
            'qty': float(largest['q']),
            'value': round(float(largest['value']), 2),
            'side': str(largest['s']).upper(),
        },
    }
    return stats, ('trade.csv', (total, len(trade)))


def _process_liquidations(data_dir, window_hours):
    """Compute liquidation stats from liq.csv."""
    path = os.path.join(data_dir, 'liq.csv')
    if not os.path.exists(path):
        return {}, None
    liq, total = load_csv(path, window_hours)
    if len(liq) == 0:
        return {}, ('liq.csv', (total, 0))

    liq['value'] = liq['p'] * liq['q']
    long_mask = liq['s'].str.upper() == 'LONG'
    largest = liq.loc[liq['value'].idxmax()]

    stats = {
        'total_liq_long': round(liq.loc[long_mask, 'value'].sum(), 2),
        'total_liq_short': round(liq.loc[~long_mask, 'value'].sum(), 2),
        'liq_events_count': len(liq),
        'largest_liq': {
            'price': float(largest['p']),
            'qty': float(largest['q']),
            'value': round(float(largest['value']), 2),
            'side': str(largest['s']).upper(),
        },
    }
    return stats, ('liq.csv', (total, len(liq)))


def _process_oi(data_dir, window_hours):
    """Compute open interest stats from oi.csv."""
    path = os.path.join(data_dir, 'oi.csv')
    if not os.path.exists(path):
        return {}, None
    oi, total = load_csv(path, window_hours)
    if len(oi) == 0:
        return {}, ('oi.csv', (total, 0))

    oi_start = float(oi['oi'].iloc[0])
    oi_current = float(oi['oi'].iloc[-1])
    stats = {
        'oi_current': oi_current,
        'oi_start': oi_start,
        'oi_change_pct': round((oi_current - oi_start) / abs(oi_start) * 100, 2) if oi_start != 0 else None,
    }
    return stats, ('oi.csv', (total, len(oi)))


_PROCESSORS = (_process_bbo, _process_trades, _process_liquidations, _process_oi)


def preprocess(data_dir, window_hours):
    """Compute stats from each CSV, return JSON-ready summary."""
    stats = {"window_hours": window_hours}
    csv_info = {}

    for processor in _PROCESSORS:
        partial_stats, info_entry = processor(data_dir, window_hours)
        stats.update(partial_stats)
        if info_entry:
            csv_info[info_entry[0]] = info_entry[1]

    return stats, csv_info


# ============== Report Generation ==============

SYSTEM_PROMPT = """\
You are a crypto futures market analyst. Given market statistics as JSON, \
write a concise market report in this exact format:
- First: 5-7 bullet points summarizing key metrics and events (start each with "- ")
- Then: 1-2 short paragraphs with deeper market analysis

Use specific numbers from the data. Be concise. Do not include a title."""


def generate_report(llm, stats):
    """Call LLM to generate the market report from stats."""
    response = llm.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(stats, indent=2)},
        ],
        temperature=0.5,
    )
    return response


# ============== Assembly ==============

def assemble_seed(report, agents_text):
    """Combine report and agents into seed.md content."""
    return f"# Futures Market Report\n{report}\n\n# Agents\n{agents_text}\n"


# ============== Formatting ==============

def fmt_number(n):
    """Format large numbers with K/M/B suffixes."""
    if n is None:
        return "N/A"
    sign = "-" if n < 0 else ""
    abs_n = abs(n)
    if abs_n >= 1_000_000_000:
        return f"{sign}${abs_n / 1_000_000_000:.1f}B"
    if abs_n >= 1_000_000:
        return f"{sign}${abs_n / 1_000_000:.1f}M"
    if abs_n >= 1_000:
        return f"{sign}${abs_n / 1_000:.1f}K"
    return f"{sign}${abs_n:,.2f}"


def print_stats_summary(stats, csv_info):
    """Print formatted stats summary to stdout."""
    for name, (total, filtered) in csv_info.items():
        if name == 'bbo.csv':
            print(f"  {name:12s} {total:,} rows → last row")
        else:
            print(f"  {name:12s} {total:,} rows → {filtered:,} in window")

    print()
    print("Stats:")
    print(f"  Price: {fmt_number(stats.get('current_price'))} | Spread: {fmt_number(stats.get('spread'))}")
    print(f"  Taker volume: {fmt_number(stats.get('taker_volume'))} | Taker buy/sell: {stats.get('taker_buy_sell_ratio', 'N/A')}")
    if 'total_liq_long' in stats:
        print(f"  Liquidations: {fmt_number(stats.get('total_liq_long'))} long / {fmt_number(stats.get('total_liq_short'))} short")
    if 'oi_current' in stats:
        oi_pct = stats.get('oi_change_pct')
        oi_pct_str = f"{oi_pct:+.1f}%" if oi_pct is not None else "N/A"
        print(f"  OI: {fmt_number(stats.get('oi_current'))} ({oi_pct_str})")


def load_agents(agents_path):
    """Load agent definitions from file, falling back to defaults."""
    if agents_path:
        with open(agents_path, 'r') as f:
            return f.read().strip()

    # Try agents.txt at project root
    default_path = os.path.join(project_root, 'agents.txt')
    if os.path.exists(default_path):
        with open(default_path, 'r') as f:
            return f.read().strip()

    return DEFAULT_AGENTS


# ============== Main ==============

def main():
    parser = argparse.ArgumentParser(description="gen_seed — Market Data CSV → seed.md")
    default_data_dir = os.path.join(
        project_root, '..', 'rust-connectors', 'mm-simulation', 'qm-lab', 'market-data',
        datetime.now().strftime('%Y-%m-%d')
    )
    parser.add_argument("--data-dir", default=default_data_dir, help="Directory containing CSVs (default: ../rust-connectors/.../market-data/YYYY-MM-DD)")
    parser.add_argument("--window", type=int, default=1, help="Hours of data to analyze (default: 1)")
    parser.add_argument("--agents", default=None, help="Optional agents.txt file")
    parser.add_argument("-o", "--output", default="seed.md", help="Output file path (default: seed.md)")
    args = parser.parse_args()

    args.output = resolve_path(args.output)
    args.data_dir = resolve_path(args.data_dir)

    print("gen_seed — Market Data → seed.md")
    print("=" * 40)
    print(f"Data: {args.data_dir} (window: {args.window}h)")

    if not os.path.isdir(args.data_dir):
        print(f"Error: data directory not found: {args.data_dir}")
        sys.exit(1)

    # Preprocess
    stats, csv_info = preprocess(args.data_dir, args.window)
    print_stats_summary(stats, csv_info)

    # Generate report via LLM
    print()
    print("Generating report...", end=" ", flush=True)
    llm = LLMClient()
    report = generate_report(llm, stats)
    print("✓")

    # Load agents and assemble
    agents_text = load_agents(args.agents)
    seed_content = assemble_seed(report, agents_text)
    with open(args.output, 'w') as f:
        f.write(seed_content)

    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
