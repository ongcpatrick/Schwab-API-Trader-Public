#!/bin/bash
# Start the Schwab API Trader dashboard
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PYTHONPATH=src .venv/bin/python3.13 -m uvicorn schwab_trader.server.app:app \
  --host 0.0.0.0 --port 8000 --reload
