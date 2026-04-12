source backend/.venv/bin/activate

python3 backend/scripts/gen_seed.py \
  --end-hour 2026-04-05T03 \
  --hours 72 \
  --count 3 \
  --marketdata marketdata

pip3

don't run bull shit test