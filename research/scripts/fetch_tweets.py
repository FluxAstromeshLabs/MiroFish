"""
fetch_tweets — Fetch top tweets per day via twitterapi.io
Writes output to CSV file (default: output.csv), merging and deduplicating.

Usage:
    python3 research/scripts/fetch_tweets.py --start-date "2026-04-01 00:00:00" --end-date "2026-04-07 23:59:59" -o tweets.csv
    python3 research/scripts/fetch_tweets.py --latest-time 2026-04-19-04-00 -o tweets.csv
    python3 research/scripts/fetch_tweets.py -o output.csv  # fetches current interval window
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from common import project_root

load_dotenv()

API_KEY  = os.getenv("TWEET_API_KEY", "")
BASE_URL = os.getenv("TWEET_BASE_URL", "https://api.twitterapi.io/twitter/tweet/advanced_search")
ACCOUNTS = [a.strip() for a in os.getenv("ACCOUNTS", "").split(",") if a.strip()]
QUERY    = os.getenv("QUERY", "")


def build_query(accounts: list[str], query: str, since_time: int, until_time: int) -> str:
    from_clause = " OR ".join(f"from:{a}" for a in accounts)
    return f"({query}) ({from_clause}) since_time:{since_time} until_time:{until_time}"


def fetch_tweets(full_query: str) -> list[dict]:
    headers = {"X-API-Key": API_KEY}
    params  = {"queryType": "Top", "query": full_query}
    response = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
    if response.status_code in (402, 429):
        print("  rate limited, skipping")
        return []
    response.raise_for_status()
    batch = response.json().get("tweets", [])
    print(f"  fetched {len(batch)} tweets")
    return batch


def clean_text(text: str) -> str:
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[\U0001F000-\U0001FFFF]', '', text)
    text = re.sub(r'[\u2600-\u27BF]', '', text)
    text = re.sub(r'\uFE0F', '', text)
    text = re.sub(r'@[\w]+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_created_at(raw: str) -> str:
    try:
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S +0000 %Y").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M")
    except (ValueError, TypeError):
        return ""


def extract(tweet: dict) -> dict:
    return {
        "userName":  tweet.get("author", {}).get("userName", ""),
        "text":      clean_text(tweet.get("text", "")),
        "likeCount": tweet.get("likeCount", 0),
        "createdAt": parse_created_at(tweet.get("createdAt", "")),
    }


def merge_into_file(tweets: list[dict], out_path: str) -> None:
    existing = []
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            existing = list(reader) if reader else []

    seen = {(t.get("createdAt"), t.get("text")) for t in existing}
    added = 0
    for t in tweets:
        key = (t.get("createdAt"), t.get("text"))
        if key not in seen:
            seen.add(key)
            existing.append({"timestamp": t.get("createdAt"), "tweet": t.get("text")})
            added += 1

    existing.sort(key=lambda t: t.get("timestamp", ""))
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "tweet"])
        writer.writeheader()
        writer.writerows(existing)
    print(f"  {out_path} — {len(existing)} tweets (+{added} new)")


def fetch_day(start_dt: datetime, out_path: str) -> None:
    until_dt = start_dt + timedelta(days=1)
    since_time = int(start_dt.timestamp())
    until_time = int(until_dt.timestamp())

    date_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{date_str} (since={since_time} until={until_time})")

    full_query = build_query(ACCOUNTS, QUERY, since_time, until_time)
    tweets_raw = fetch_tweets(full_query)
    tweets = [extract(t) for t in tweets_raw]
    merge_into_file(tweets, out_path)


def main():
    parser = argparse.ArgumentParser(description="Fetch top tweets in a time window")
    parser.add_argument("--start-date", default=None, help="Start UTC datetime (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end-date", default=None, help="End UTC datetime (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--latest-time", default=None,
                        help="Single window mode: latest candle time YYYY-MM-DD-HH-MM")
    parser.add_argument("-o", "--output", default="output.csv", help="Output CSV file path (default: output.csv)")
    args = parser.parse_args()

    out_path = args.output
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if args.start_date:
        if not args.end_date:
            parser.error("--end-date is required when --start-date is provided")

        start = datetime.strptime(args.start_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        end = datetime.strptime(args.end_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if end <= start:
            parser.error("--end-date must be later than --start-date")

        since_time = int(start.timestamp())
        until_time = int(end.timestamp())
        print(f"Fetching custom window since={since_time} until={until_time}...")

        full_query = build_query(ACCOUNTS, QUERY, since_time, until_time)
        tweets_raw = fetch_tweets(full_query)
        tweets = [extract(t) for t in tweets_raw]
        merge_into_file(tweets, out_path)
    else:
        if args.latest_time:
            latest_time = datetime.strptime(args.latest_time, "%Y-%m-%d-%H-%M").replace(tzinfo=timezone.utc)
        else:
            latest_time = datetime.now(timezone.utc)

        interval = os.getenv("INTERVAL", "1h")
        if interval.endswith("h"):
            interval_secs = int(interval[:-1]) * 3600
        elif interval.endswith("m"):
            interval_secs = int(interval[:-1]) * 60
        else:
            raise ValueError(f"Unknown interval: {interval}")

        since_time = int(latest_time.timestamp())
        until_time = int((latest_time + timedelta(seconds=interval_secs)).timestamp())

        print(f"Fetching window since={since_time} until={until_time}...")
        full_query = build_query(ACCOUNTS, QUERY, since_time, until_time)
        tweets_raw = fetch_tweets(full_query)
        tweets = [extract(t) for t in tweets_raw]

        merge_into_file(tweets, out_path)


if __name__ == "__main__":
    main()
