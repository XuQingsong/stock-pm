#!/usr/bin/env bash
# Cloud Agent install: idempotent dependency + database bootstrap for stock-pm.
# Runs after the repository is checked out. Safe to run repeatedly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 1) System packages: PostgreSQL server + client (only if missing).
if ! command -v pg_ctlcluster >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    postgresql postgresql-client python3-venv
fi

# 2) Python virtualenv with the project installed in editable mode + dev deps.
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]"

# 3) Start PostgreSQL and provision the stock_pm role/database (idempotent).
#    scripts/start-postgres.sh prefers Docker, then a local cluster; here it
#    starts the apt-installed cluster and creates the role/db if absent.
bash scripts/start-postgres.sh

# 4) Apply and verify every SQL migration (re-runnable, IF NOT EXISTS).
python -m stock_pm.migrate

echo "stock-pm install complete"
