"""
get_tweets — Fetch top tweets for a query via twitterapi.io
Writes output to tweets/YYYY-MM-DD.json under project root.

Usage:
    python3 backend/scripts/get_tweets.py --query bitcoin --date 2026-04-16
    python3 backend/scripts/get_tweets.py --query bitcoin  # defaults to today
"""

import argparse
import json
import os
from datetime import datetime, timezone

import requests

from common import project_root

API_KEY = "new1_d70f06a445f84c62ae8e73899eeff94e"
BASE_URL = "https://api.twitterapi.io/twitter/tweet/advanced_search"


def fetch_tweets(query: str) -> list[dict]:
    headers = {"X-API-Key": API_KEY}
    params = {"queryType": "Top", "query": query}
    response = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data.get("tweets", [])


def extract(tweet: dict) -> dict:
    return {
        "userName": tweet.get("author", {}).get("userName", ""),
        "text": tweet.get("text", ""),
        "likeCount": tweet.get("likeCount", 0),
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch top tweets for a query")
    parser.add_argument("--query", required=True, help="Search query (e.g. bitcoin)")
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Output date label YYYY-MM-DD (default: today)",
    )
    args = parser.parse_args()

    tweets = fetch_tweets(args.query)
    extracted = [extract(t) for t in tweets]

    out_dir = os.path.join(project_root, "tweets")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{args.date}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(extracted, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(extracted)} tweets → {out_path}")


if __name__ == "__main__":
    main()
