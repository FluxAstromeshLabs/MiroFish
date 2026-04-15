# Prepare virtual evironment

```
python3 -m venv .venv && source ./.venv/bin/activate
python3 -m pip install -r backend/requirements.txt
```

# Prepare data

python3 research/scripts/aggregate_ohlcv.py --start-date "2026-03-28 00:00:00" --end-date "2026-04-13 23:59:59" --interval 1h -o research/data/ohlcv_1h.csv
