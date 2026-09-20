# Deploy to http://43.166.2.31/

The live app is the same FastAPI process in this repo (`stock_pm.api:app`).
Do not stand up a second product. After merging, ship **this branch tip**.

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

## Deploy the Brain changes from the existing repository

The server has a code-only `/opt/stock-pm` directory and no `.git`. Connect as
`ubuntu` with the configured SSH key; `sudo` is available. After testing and
committing locally, archive the revision and transfer it. Extraction preserves
the untracked `/opt/stock-pm/.env.server` and the Postgres volume.

```bash
# On the local work machine, from the repository root:
git archive --format=tar.gz -o /tmp/stock-pm-release.tar.gz HEAD
scp /tmp/stock-pm-release.tar.gz ubuntu@43.166.2.31:/tmp/
ssh ubuntu@43.166.2.31

# On the server:
sudo tar -czf /tmp/stock-pm-pre-release.tar.gz -C /opt stock-pm
sudo tar -xzf /tmp/stock-pm-release.tar.gz -C /opt/stock-pm
cd /opt/stock-pm
sudo docker compose --env-file .env.server build app
sudo docker compose --env-file .env.server up -d app
sudo docker compose --env-file .env.server run --rm app python -m stock_pm.brain.materialize_from_research --tickers AVGO,LITE,AAPL
sudo docker compose --env-file .env.server run --rm app python -m stock_pm.brain.bootstrap_job --tickers AVGO,LITE,AAPL
```

The bootstrap command calls the existing evidence-gated Brain pipeline and can
consume LLM tokens. It reports each ticker as ready, incomplete, or missing
research; an incomplete run exits nonzero. Run it explicitly once. The
incremental runtime exists in code but is not yet attached to the daily timer;
page reads remain read-only.

The updated daily service materializes new research and market environment rows
without invoking an LLM. Install its unit as shown below. The intraday timer
continues to collect delayed price data every five minutes; it does not rerun
Market Brain. The web pages reread persisted API data every five minutes.

The current host publishes port 80 directly through Docker Compose. Preserve
its `.env.server` network settings during upgrades.

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
