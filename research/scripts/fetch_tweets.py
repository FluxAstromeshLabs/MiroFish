# Requires: TWITTERAPI_KEY in research/scripts/.env
# Usage:
#   python3 fetch_tweets.py --start-date "2026-04-10 00:00" --end-date "2026-04-15 00:00"
#   python3 fetch_tweets.py --start-date "2026-04-10 00:00" --end-date "2026-04-15 00:00" \
#       --accounts "TedPillows,CoinDesk" --query "BTC OR Bitcoin OR #BTC"
#
# Output: research/data/tweet_yyyy_mm_dd_hh_mm.txt


import re
import requests
import argparse
import os
import csv
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DEFAULT_ACCOUNTS = ["TedPillows", "CoinDesk", "Cointelegraph", "WatcherGuru"]
DEFAULT_QUERY = "BTC OR Bitcoin OR #BTC OR #Bitcoin"


def build_query(accounts: list[str], query: str, since_time: int, until_time: int) -> str:
    from_clause = " OR ".join(f"from:{a}" for a in accounts)
    return f"({query}) ({from_clause}) since_time:{since_time} until_time:{until_time}"


def dt_to_unix(dt_str: str) -> int:
    return int(datetime.strptime(dt_str, "%Y-%m-%d %H:%M").timestamp())


def fetch_tweets(full_query: str, api_key: str) -> list[dict]:
    url = "https://api.twitterapi.io/twitter/tweet/advanced_search"
    headers = {"X-API-Key": api_key}
    params = {"queryType": "Top", "query": full_query}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()

    tweets = data.get("tweets", [])
    next_cursor = data.get("next_cursor", "")
    if next_cursor:
        print(f"next_cursor: {next_cursor}")

    return tweets


def main():
    parser = argparse.ArgumentParser(description="Fetch historical Bitcoin tweets")
    parser.add_argument("--start-date", required=True, help='e.g. "2026-03-01 00:00"')
    parser.add_argument("--end-date", required=True, help='e.g. "2026-03-31 23:30"')
    parser.add_argument("--accounts", default=",".join(DEFAULT_ACCOUNTS), help="Comma-separated Twitter usernames")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Search query terms")
    args = parser.parse_args()

    api_key = os.getenv("TWITTERAPI_KEY")
    if not api_key:
        raise ValueError("TWITTERAPI_KEY not set in .env")

    accounts = [a.strip() for a in args.accounts.split(",")]
    since_time = dt_to_unix(args.start_date)
    until_time = dt_to_unix(args.end_date)

    full_query = build_query(accounts, args.query, since_time, until_time)
    print(f"Query: {full_query}")

    tweets = fetch_tweets(full_query, api_key)

    # Sort by timestamp ascending
    def parse_ts(t):
        try:
            return datetime.strptime(t.get("createdAt", ""), "%a %b %d %H:%M:%S +0000 %Y")
        except ValueError:
            return datetime.min

    tweets.sort(key=parse_ts)

    end_label = datetime.strptime(args.end_date, "%Y-%m-%d %H:%M").strftime("%Y_%m_%d_%H_%M")
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"tweet_{end_label}.txt")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        f.write("=== Historical BITCOIN tweet ===\n")
        writer = csv.writer(f)
        writer.writerow(["timestamp", "tweet"])
        for t in tweets:
            raw_ts = t.get("createdAt", "")
            try:
                ts = datetime.strptime(raw_ts, "%a %b %d %H:%M:%S +0000 %Y").strftime("%Y-%m-%dT%H:%M")
            except ValueError:
                ts = raw_ts
            text = t.get("text", "").replace("\n", " ")
            text = re.sub(r'https://t\.co/\S+', '', text)
            text = re.sub(r'^[\s\U0001F000-\U0001FFFF\U00010000-\U0010FFFF\u2000-\u27FF\uFE00-\uFEFF\u200d\u20E3\U0001FA00-\U0001FA9F\U0001F900-\U0001F9FF\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]+', '', text)
            text = text.strip()
            writer.writerow([ts, text])

    print(f"Saved {len(tweets)} tweets to {out_path}")


if __name__ == "__main__":
    main()
