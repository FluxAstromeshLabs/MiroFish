#!/usr/bin/env bash
# trade.sh — gen_seed.py → run_trade.py → sleep → repeat
# Assumes Flask backend is already running in another terminal.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$ROOT/backend/.venv/bin/python3"
SLEEP_SECONDS="${1:-60}"

trap 'echo ""; echo "Shutting down..."; exit 0' INT TERM

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Error: Python venv not found at $VENV_PYTHON"
    echo "Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

while true; do
    echo ""
    echo "=========================================="
    echo "$(date '+%Y-%m-%d %H:%M:%S') — Starting pipeline"
    echo "=========================================="

    echo ">>> [1/2] Generating seed.md..."
    if ! "$VENV_PYTHON" "$ROOT/backend/scripts/gen_seed.py" -o "$ROOT/seed.md"; then
        echo ">>> gen_seed.py failed, skipping run_trade.py"
        echo ">>> Sleeping ${SLEEP_SECONDS}s..."
        sleep "$SLEEP_SECONDS"
        continue
    fi

    echo ">>> [2/2] Running MiroFish simulation..."
    "$VENV_PYTHON" "$ROOT/backend/scripts/run_trade.py" "$ROOT/seed.md"

    echo ">>> Done. Sleeping ${SLEEP_SECONDS}s..."
    sleep "$SLEEP_SECONDS"
done
