# PostgreSQL (phase 4B)

Real persistence for daily bars, earnings, and macro events. Overlay fetches
are not a substitute for a reachable database.

## Start

```bash
bash scripts/start-postgres.sh
```

The script:

1. Reads `DATABASE_URL` / `POSTGRES_PASSWORD` from the environment, then
   gitignored `.env` / `.env.server`.
2. Starts `postgres:17-alpine` via Docker Compose when Docker is available.
3. Otherwise starts/configures a local PostgreSQL cluster with the documented
   local-dev role `stock_pm`.
4. Prints only a redacted DSN. It never writes secrets into the repo.

## Migrate

```bash
python -m stock_pm.migrate
python -m stock_pm.migrate --verify-only
```

`0001_initial` is `src/stock_pm/sql/schema.sql`. Additional files go in
`src/stock_pm/sql/migrations/`. Applied versions are stored in
`schema_migrations`.

## Persist live prints

```bash
python -m stock_pm.persist_live --symbol NVDA
```

Writes Alpaca SIP daily bars, FMP earnings, official FRED series (including
NFP from PAYEMS monthly change), then reads them back. Requires a reachable
database; overlay-only success is treated as a failure for this command.

## Health

`GET /health` is `ok` only when `SELECT 1` succeeds. A down database is
`status=error`, `database=unavailable`, `reason_code=query_error`. Core pages
keep rendering and degrade per chain instead of returning a global 503.
