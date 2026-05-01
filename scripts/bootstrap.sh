#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found. Please install conda first."
  exit 1
fi

echo "[bootstrap] updating conda env p310 from environment.yml"
conda env update -n p310 -f "${ROOT_DIR}/environment.yml"

echo "[bootstrap] installing backend deps (pip)"
conda run -n p310 python -m pip install -r "${ROOT_DIR}/services/agent-api/requirements.txt"

echo "[bootstrap] installing cli deps (pip)"
conda run -n p310 python -m pip install -r "${ROOT_DIR}/apps/cli/requirements.txt"
conda run -n p310 python -m pip install -e "${ROOT_DIR}/apps/cli"

echo "[bootstrap] installing web deps (npm with local cache)"
cd "${ROOT_DIR}/apps/web"
mkdir -p .npm-cache
npm install --cache .npm-cache

echo "[bootstrap] done"

