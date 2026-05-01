#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PORT="${PORT:-80}"

cd "${ROOT_DIR}/apps/web"

if [ ! -f .env.local ]; then
  cp .env.local.example .env.local
fi

mkdir -p .npm-cache

echo "[web] installing deps (if needed)"
npm install --cache .npm-cache

echo "[web] starting on http://localhost:${PORT}"
exec npm run dev -- -p "${PORT}"

