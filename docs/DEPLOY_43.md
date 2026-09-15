# Deploy to http://43.166.2.31/

The live app is the same FastAPI process in this repo (`stock_pm.api:app`).
Do not stand up a second product. After merging, ship **this branch tip**.

## Worker count (hang mitigation)

Dockerfile / `stock_pm.api:run` start **uvicorn `--workers 2`**.

Desk assemble (`/api/desk/overview`, stock, review) also:

- runs in a threadpool so the event loop can still serve `/health`
- budgets live event discovery at ~4s/provider and ~7s overall (desk hard cap 8s)
- degrades to an empty event book (`data_mode=degraded`, `gaps.events=true`) on timeout

Do not drop back to a single worker: one stuck official-feed fetch previously blocked the only worker and produced site-wide 502s.

## Tip (what “done” means)

- Pages: `/` 总览 · `/stock/{symbol}` 个股五段 · `/review` 正式预测/观察分家
- Data: `/api/desk/overview` · `/api/desk/stock/{symbol}` · `/api/desk/review`
- Watchlist, news, quotes, trusted events, environment, tape, and predictions
  stay on the existing Postgres + job timers.

## Credentials that create honest gaps (do not fake certainty)

Set these in gitignored `/opt/stock-pm/.env.server` (see `.env.server.example`):

| Variable | If missing |
| --- | --- |
| `DATABASE_URL` / `POSTGRES_PASSWORD` | `/health` reports DB unavailable; pages degrade |
| `ALPACA_API_KEY_ID` + `ALPACA_API_SECRET_KEY` | quotes/bars delayed or empty |
| `FRED_API_KEY` | macro series stay named-missing |
| `FMP_API_KEY` | fundamentals/earnings named-missing |
| `ALPHA_VANTAGE_API_KEY` | earnings/gold live coverage incomplete |
| `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_ID` | discovery-only; official feeds still run |
| `SEC_EDGAR_USER_AGENT` | SEC Atom skipped |
| `LLM_API_KEY` | review explanations stay missing; no invented copy |
| `STOCK_PM_EVENTS_MODE` | empty = live official feeds (production default) |

The UI must show 「数据暂缺」 / hide the card rather than invent a deep-green featured event.

## Tip-tar pattern (private git / server cannot `git pull`)

On the build machine, from the merged commit:

```bash
git archive --format=tar --prefix=stock-pm/ HEAD | gzip > stock-pm-tip.tar.gz
scp stock-pm-tip.tar.gz root@43.166.2.31:/tmp/
ssh root@43.166.2.31
```

On the server (layout already used: `/opt/stock-pm` + docker compose + `.env.server`):

```bash
cd /opt
cp -a stock-pm/stock-pm/.env.server /tmp/stock-pm.env.server
# keep postgres volume; replace code only
rm -rf /opt/stock-pm
mkdir -p /opt/stock-pm
tar -xzf /tmp/stock-pm-tip.tar.gz -C /opt
# git archive prefix=stock-pm/ extracts into /opt/stock-pm
cp /tmp/stock-pm.env.server /opt/stock-pm/.env.server
cd /opt/stock-pm
docker compose --env-file .env.server build app
docker compose --env-file .env.server up -d postgres app
python -m stock_pm.migrate   # or: docker compose run --rm app python -m stock_pm.migrate
docker compose --env-file .env.server restart app
```

If the host already reverse-proxies `127.0.0.1:8000` to `http://43.166.2.31/`,
leave `BIND_ADDRESS=127.0.0.1` and `WEB_PORT=8000` unchanged.

Re-enable timers (unchanged unit names; daily job now also runs `stock-pm-events`):

```bash
sudo cp deploy/stock-pm-daily.service deploy/stock-pm-daily.timer /etc/systemd/system/
sudo cp deploy/stock-pm-intraday.service deploy/stock-pm-intraday.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stock-pm-daily.timer stock-pm-intraday.timer
```

Smoke:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/desk/overview | head
curl -fsS http://43.166.2.31/
```

Existing `alert_id` supersede path is unchanged: `POST /api/stock/{symbol}/predictions/{id}/supersede`.
