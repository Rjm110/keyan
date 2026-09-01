#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-1}"

if [[ "$RELOAD" == "1" || "$RELOAD" == "true" ]]; then
  exec uv run uvicorn app.server:app --host "$HOST" --port "$PORT" --reload
fi

exec uv run uvicorn app.server:app --host "$HOST" --port "$PORT"