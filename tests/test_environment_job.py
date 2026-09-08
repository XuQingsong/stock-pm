from pathlib import Path

from fastapi.testclient import TestClient

from stock_pm import api
from stock_pm.environment import failed_snapshot
from stock_pm.environment_job import publish_environment_snapshots, publish_if_missing
from stock_pm.errors import DatabaseError
from stock_pm.queries import QueryMixin


class MemoryStore:
    def __init__(self, *, fail_symbols=None, fail_append=None, symbols=None):
        self.fail_symbols = set(fail_symbols or [])
        self.fail_append = set(fail_append or [])
        self.symbols = list(symbols or ["NVDA", "INTC"])
        self.snapshots: list[dict] = []
        self.jobs: list[dict] = []

    def ping(self):
        return True

    def initialize(self):
        return None

    def close(self):
        return None

    def market_session(self, trade_date=None):
        return {
            "date": trade_date or "2026-09-04",
            "is_trading_day": True,
            "default_review_date": "2026-09-04",
        }

    def active_symbols(self):
        return list(self.symbols)

    def briefing(self, date=None):
        return {
            "date": date or "2026-09-04",
            "session": self.market_session(date),
            "rows": [{"symbol": "NVDA", "health": "趋势健康"}],
            "environment": {
                "as_of_date": date or "2026-09-04",
                "scope": "market",
                "one_liner": "市场半句",
                "publishState": "published",
                "missingFlags": [],
                "struct": {},
            },
        }

    def cboe_option_stats(self, trade_date=None):
        return {"trade_date": trade_date, "total_put_call": 0.8}

    def market_impact(self):
        return {"macro": []}

    def build_live_environment(self, symbol, as_of_date=None, **kwargs):
        if symbol in self.fail_symbols:
            raise RuntimeError("thesis exploded")
        return {
            "as_of_date": as_of_date,
            "scope": "symbol",
            "symbol": symbol,
            "one_liner": f"{symbol} 环境半句",
            "row_thesis": f"{symbol} 环境半句",
            "synthesis": f"{symbol} 环境半句",
            "struct": {"fundamentals": {"year_move": {"return_1y_pct": 10}}},
            "missingFlags": [],
            "publishState": "published",
            "prediction_ready": False,
        }

    def append_environment_snapshot(self, snapshot):
        symbol = snapshot.get("symbol") or snapshot.get("scope")
        if symbol in self.fail_append or snapshot.get("scope") in self.fail_append:
            raise RuntimeError("write failed")
        self.snapshots.append(snapshot)

    def append_job_run(self, job):
        self.jobs.append(job)

    def latest_environment_snapshots(self, as_of_date):
        latest: dict[tuple, dict] = {}
        want = str(as_of_date or "")[:10]
        for row in self.snapshots:
            if str(row.get("as_of_date") or "")[:10] != want:
                continue
            latest[(row.get("scope"), row.get("symbol"))] = row
        return list(latest.values())

    def environment_history(self, symbol, limit=30):
        needle = symbol.upper()
        rows = [row for row in reversed(self.snapshots) if row.get("symbol") == needle]
        return rows[:limit]

    def job_runs(self, limit=20):
        return list(reversed(self.jobs))[:limit]


def test_publish_appends_market_and_each_symbol() -> None:
    store = MemoryStore()
    result = publish_environment_snapshots(store, as_of_date="2026-09-04")
    assert result["status"] == "success"
    scopes = [(row.get("scope"), row.get("symbol")) for row in store.snapshots]
    assert ("market", None) in scopes
    assert ("symbol", "NVDA") in scopes
    assert ("symbol", "INTC") in scopes
    assert store.jobs[-1]["job_name"] == "environment"
    assert store.jobs[-1]["status"] == "success"
    assert all(row.get("publishState") != "missing" for row in store.snapshots)


def test_publish_failure_writes_visible_missing_not_silence() -> None:
    store = MemoryStore(fail_symbols={"INTC"})
    result = publish_environment_snapshots(store, as_of_date="2026-09-04")
    assert result["status"] == "partial"
    intc = next(row for row in store.snapshots if row.get("symbol") == "INTC")
    assert intc["publishState"] == "missing"
    assert "未编造数字" in intc["one_liner"]
    assert intc["struct"]["fundamentals"] is None
    assert store.jobs[-1]["status"] == "partial"
    assert store.jobs[-1]["error"]
    assert "INTC" in store.jobs[-1]["error"]


def test_failed_snapshot_helper_matches_job_contract() -> None:
    snap = failed_snapshot("MU", "2026-09-04", "disk full")
    assert snap["missingFlags"]
    assert snap["struct"]["news"] == {"macro": None, "sector": None, "company": None}


def test_history_is_non_empty_after_publish() -> None:
    store = MemoryStore(symbols=["AAPL"])
    publish_environment_snapshots(store, as_of_date="2026-09-04", symbols=["AAPL"])
    history = store.environment_history("AAPL")
    assert history
    assert history[0]["symbol"] == "AAPL"
    assert history[0]["publishState"] in {"published", "draft", "stale", "missing"}
    assert any(job["job_name"] == "environment" for job in store.job_runs())


def test_failed_publish_history_is_honest_missing_not_empty() -> None:
    store = MemoryStore(fail_symbols={"AAPL"}, symbols=["AAPL"])
    result = publish_environment_snapshots(
        store, as_of_date="2026-09-04", symbols=["AAPL"]
    )
    assert result["status"] == "partial"
    history = store.environment_history("AAPL")
    assert history
    assert history[0]["publishState"] == "missing"
    assert history[0]["missingFlags"]
    assert any(job["job_name"] == "environment" for job in store.job_runs())


def test_publish_if_missing_skips_when_symbol_snapshots_exist() -> None:
    store = MemoryStore(symbols=["AAPL"])
    first = publish_if_missing(store, as_of_date="2026-09-04", symbols=["AAPL"])
    assert first["status"] == "success"
    count = len(store.snapshots)
    second = publish_if_missing(store, as_of_date="2026-09-04", symbols=["AAPL"])
    assert second["status"] == "skipped"
    assert len(store.snapshots) == count


def test_get_environment_history_and_jobs_after_publish(monkeypatch) -> None:
    store = MemoryStore(symbols=["AAPL"])
    publish_environment_snapshots(store, as_of_date="2026-09-04", symbols=["AAPL"])
    monkeypatch.setattr(api, "database", store)
    client = TestClient(api.app)
    history = client.get("/api/environment/history?symbol=AAPL")
    assert history.status_code == 200
    body = history.json()
    assert body
    assert body[0]["symbol"] == "AAPL"
    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200
    names = [row.get("job_name") for row in jobs.json()]
    assert "environment" in names


def test_job_runs_merges_environment_with_alpaca_sync() -> None:
    class Harness(QueryMixin):
        def fetch_all(self, query, params=()):
            if "FROM job_runs" in query:
                return [
                    {
                        "job_name": "environment",
                        "started_at": "2026-09-08T12:00:00+00:00",
                        "completed_at": "2026-09-08T12:01:00+00:00",
                        "status": "success",
                        "item_counts": {"written": 2},
                        "error": None,
                    }
                ]
            if "FROM sync_runs" in query:
                return [
                    {
                        "source": "alpaca",
                        "started_at": "2026-09-08T11:00:00+00:00",
                        "completed_at": "2026-09-08T11:05:00+00:00",
                        "status": "success",
                        "item_counts": {"bars": 10},
                        "error": None,
                    }
                ]
            raise DatabaseError(query)

    rows = Harness().job_runs()
    names = [row["job_name"] for row in rows]
    assert names[0] == "environment"
    assert "alpaca" in names


def test_environment_job_is_wired_in_compose_and_daily_timer() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "environment-job:" in compose
    assert "python -m stock_pm.environment_job" in compose
    service = Path("deploy/stock-pm-daily.service").read_text(encoding="utf-8")
    assert "environment-job" in service
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "stock-pm-environment" in pyproject


def test_review_main_still_publishes_environment_if_generate_fails() -> None:
    import inspect

    from stock_pm.review import main

    source = inspect.getsource(main)
    assert "publish_environment_snapshots" in source
    assert "review_generate_error" in source
    gen_at = source.index("generate_review")
    pub_at = source.index("publish_environment_snapshots")
    assert gen_at < pub_at
    # Per-symbol try so one review failure cannot skip environment publish.
    assert source.index("try:") < gen_at < source.index("continue")
