#!/usr/bin/env bash
# Cloud Agent start: bring PostgreSQL up on every boot and reconcile schema.
# Must tolerate restarts; nothing here is a long-running foreground process.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Put the project venv first on PATH so scripts/start-postgres.sh — which shells
# out to `python3` for its psycopg readiness/provisioning probes — uses the
# interpreter that actually has psycopg installed (system python3 does not).
if [[ -d .venv/bin ]]; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi

# Start the local PostgreSQL cluster and ensure the role/db exist (idempotent).
bash scripts/start-postgres.sh

# Apply any pending migrations. On a snapshot-restored disk this is a no-op.
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python -m stock_pm.migrate >/dev/null
fi

echo "stock-pm start complete"
