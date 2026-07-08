#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/backend/.vendor:$PROJECT_ROOT/backend"
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
