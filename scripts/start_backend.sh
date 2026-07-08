#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/backend/.vendor:$PROJECT_ROOT/backend"
HOST_VALUE="${ICAR_HOST:-0.0.0.0}"
PORT_VALUE="${ICAR_PORT:-8000}"
if [[ "${ICAR_RELOAD:-0}" == "1" ]]; then
  python3 -m uvicorn app.main:app --host "$HOST_VALUE" --port "$PORT_VALUE" --reload
else
  python3 -m uvicorn app.main:app --host "$HOST_VALUE" --port "$PORT_VALUE"
fi
