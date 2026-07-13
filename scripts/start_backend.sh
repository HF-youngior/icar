#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/backend/.vendor:$PROJECT_ROOT/backend"
HOST_VALUE="${ICAR_HOST:-0.0.0.0}"
PORT_VALUE="${ICAR_PORT:-8000}"

echo
echo "iCar backend starting..."
echo "Bind host: $HOST_VALUE"
echo "Bind port: $PORT_VALUE"
echo

if [[ "$HOST_VALUE" == "0.0.0.0" ]]; then
  echo "Local access:"
  echo "  Dashboard: http://127.0.0.1:$PORT_VALUE/dashboard"
  echo "  Control:   http://127.0.0.1:$PORT_VALUE/control"
  echo "  SLAM Nav:  http://127.0.0.1:$PORT_VALUE/navigation"
  echo "  Cruise:    http://127.0.0.1:$PORT_VALUE/cruise"
  echo
  echo "Shareable LAN URLs:"
  LAN_IPS="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | grep -v '^127\.' || true)"
  if [[ -n "$LAN_IPS" ]]; then
    while read -r IP; do
      [[ -z "$IP" ]] && continue
      echo "  http://$IP:$PORT_VALUE/control"
      echo "  http://$IP:$PORT_VALUE/navigation"
      echo "  http://$IP:$PORT_VALUE/cruise"
    done <<< "$LAN_IPS"
  else
    echo "  No LAN IPv4 address detected yet."
  fi
elif [[ "$HOST_VALUE" == "127.0.0.1" || "$HOST_VALUE" == "localhost" ]]; then
  echo "Local access only:"
  echo "  Dashboard: http://127.0.0.1:$PORT_VALUE/dashboard"
  echo "  Control:   http://127.0.0.1:$PORT_VALUE/control"
  echo "  SLAM Nav:  http://127.0.0.1:$PORT_VALUE/navigation"
  echo "  Cruise:    http://127.0.0.1:$PORT_VALUE/cruise"
else
  echo "Access URLs:"
  echo "  Dashboard: http://$HOST_VALUE:$PORT_VALUE/dashboard"
  echo "  Control:   http://$HOST_VALUE:$PORT_VALUE/control"
  echo "  SLAM Nav:  http://$HOST_VALUE:$PORT_VALUE/navigation"
  echo "  Cruise:    http://$HOST_VALUE:$PORT_VALUE/cruise"
fi

echo
if [[ "${ICAR_RELOAD:-0}" == "1" ]]; then
  python3 -m uvicorn app.main:app --host "$HOST_VALUE" --port "$PORT_VALUE" --reload
else
  python3 -m uvicorn app.main:app --host "$HOST_VALUE" --port "$PORT_VALUE"
fi
