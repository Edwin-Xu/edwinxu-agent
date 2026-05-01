#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BACKEND_PORT="${BACKEND_PORT:-8080}"

echo "[all] starting backend + web"
echo "[all] backend: http://localhost:${BACKEND_PORT}"
echo "[all] web:     http://localhost:80"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${WEB_PID:-}" ]]; then
    kill "${WEB_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

PORT="${BACKEND_PORT}" "${ROOT_DIR}/scripts/dev-backend.sh" &
BACKEND_PID=$!

sleep 1

"${ROOT_DIR}/scripts/dev-web.sh" &
WEB_PID=$!

wait

