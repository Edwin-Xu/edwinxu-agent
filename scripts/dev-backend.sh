#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PORT="${PORT:-8080}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found. Please install conda first."
  exit 1
fi

cd "${ROOT_DIR}/services/agent-api"

if [ ! -f .env ]; then
  cp .env.example .env
fi

echo "[backend] starting on http://localhost:${PORT}"
exec conda run -n p310 uvicorn app.main:app --port "${PORT}" --reload

