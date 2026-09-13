#!/usr/bin/env bash
# Start a local/cloud PostgreSQL for stock-pm. Never writes secrets to the repo.
# Reads DATABASE_URL / POSTGRES_PASSWORD from the environment or gitignored files.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Optional local env files. Both are gitignored. Load only DB keys; never echo.
load_db_env() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      DATABASE_URL=*|POSTGRES_PASSWORD=*|POSTGRES_USER=*|POSTGRES_DB=*|POSTGRES_PORT=*)
        export "${line?}"
        ;;
    esac
  done < "$file"
}
load_db_env .env
if [[ -z "${DATABASE_URL:-}" ]]; then
  load_db_env .env.server
fi

LOCAL_USER="${POSTGRES_USER:-stock_pm}"
LOCAL_DB="${POSTGRES_DB:-stock_pm}"
LOCAL_PASSWORD="${POSTGRES_PASSWORD:-stock_pm_dev}"
LOCAL_PORT="${POSTGRES_PORT:-5432}"
export DATABASE_URL="${DATABASE_URL:-postgresql://${LOCAL_USER}:${LOCAL_PASSWORD}@127.0.0.1:${LOCAL_PORT}/${LOCAL_DB}}"

redact() {
  python3 - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit
url = os.environ.get("DATABASE_URL", "")
parts = urlsplit(url)
user = parts.username or ""
host = parts.hostname or ""
port = f":{parts.port}" if parts.port else ""
auth = f"{user}:***@" if user else ""
print(urlunsplit((parts.scheme, f"{auth}{host}{port}", parts.path, parts.query, parts.fragment)))
PY
}

wait_ready() {
  python3 - <<'PY'
import os, time
import psycopg
url = os.environ["DATABASE_URL"]
deadline = time.time() + 45
last = None
while time.time() < deadline:
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        print("postgres_ready")
        raise SystemExit(0)
    except Exception as exc:
        last = exc
        time.sleep(1)
print(f"postgres_not_ready: {last}")
raise SystemExit(1)
PY
}

if command -v docker >/dev/null 2>&1; then
  if [[ -f .env.server ]]; then
    docker compose --env-file .env.server up -d postgres
  else
    POSTGRES_PASSWORD="$LOCAL_PASSWORD" docker compose up -d postgres
  fi
  wait_ready
  echo "started=docker database=$(redact)"
  exit 0
fi

if command -v pg_isready >/dev/null 2>&1 || command -v psql >/dev/null 2>&1; then
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -h 127.0.0.1 -p "$LOCAL_PORT" >/dev/null 2>&1 || {
      if command -v service >/dev/null 2>&1; then
        sudo -n service postgresql start >/dev/null 2>&1 || service postgresql start >/dev/null 2>&1 || true
      fi
      if command -v pg_ctlcluster >/dev/null 2>&1; then
        sudo -n pg_ctlcluster 16 main start >/dev/null 2>&1 \
          || sudo -n pg_ctlcluster 17 main start >/dev/null 2>&1 \
          || pg_ctlcluster 16 main start >/dev/null 2>&1 \
          || pg_ctlcluster 17 main start >/dev/null 2>&1 \
          || true
      fi
    }
  fi
  python3 - <<PY
import os, subprocess, sys
url = os.environ["DATABASE_URL"]
user = "${LOCAL_USER}"
db = "${LOCAL_DB}"
password = """${LOCAL_PASSWORD}"""
try:
    import psycopg
    with psycopg.connect(url, connect_timeout=3) as conn:
        conn.execute("SELECT 1")
    print("postgres_already_configured")
    sys.exit(0)
except Exception:
    pass
sql = f"""
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN
    CREATE ROLE {user} LOGIN PASSWORD '{password}';
  END IF;
END
\$\$;
SELECT 'ok';
"""
cmds = [
    ["sudo", "-n", "-u", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-c", sql],
    ["sudo", "-n", "-u", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-c",
     f"SELECT 'create' FROM pg_database WHERE datname='{db}'"],
]
for cmd in cmds:
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        continue
    if cmd[-1].startswith("SELECT 'create'") and "create" not in (result.stdout or ""):
        subprocess.run(
            ["sudo", "-n", "-u", "postgres", "createdb", "-O", user, db],
            check=False,
        )
PY
  wait_ready
  echo "started=local database=$(redact)"
  exit 0
fi

echo "No Docker or local PostgreSQL client found. Install postgres:17 or postgresql." >&2
exit 1
