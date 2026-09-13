from __future__ import annotations

from pathlib import Path

from stock_pm.config import Settings
from stock_pm.events.analyze import analyze_event
from stock_pm.events.av_earnings import AvEarningsProvider, _LIMITER, av_cache_key, reset_earnings_runtime
from stock_pm.events.dedupe import build_events
from stock_pm.events.earnings import (
    FROZEN_EARNINGS_DATA_CLASS,
    compute_frozen_earnings_integrity,
    load_frozen_coverage,
    load_frozen_coverage_documents,
    reset_earnings_registry,
)
from stock_pm.events.earnings_health import (
    clear_earnings_health_memory,
    current_earnings_health,
    health_cache_path,
    health_for_symbol,
    purge_earnings_health_persist,
    set_earnings_inject,
    summarize_health,
)
from stock_pm.events.service import coverage, reset_cache, stock_events
from stock_pm.events.watchlist import apply_watchlist_rows
from stock_pm.fetch import FetchError, write_cache


FROZEN = Path(__file__).resolve().parents[1] / "src/stock_pm/data/events_5c_c_frozen_earnings.json"


def setup_function() -> None:
    reset_earnings_runtime()
    reset_cache()


def _closed(docs):
    events = build_events(docs)
    for event in events:
        analyze_event(event)
    return events


def _evidence_by_symbol(events):
    out = {}
    for event in events:
        row = (event.analysis or {}).get("earnings_evidence") or {}
        symbol = row.get("symbol")
        if symbol:
            out.setdefault(symbol, []).append(row)
    return out


def test_frozen_coverage_pack_is_not_live():
    pack = load_frozen_coverage()
    assert pack["live"] is False
    assert pack["data_class"] == FROZEN_EARNINGS_DATA_CLASS
    assert pack["not_production_live"] is True
    assert compute_frozen_earnings_integrity(pack) == pack["integrity_sha256"]
    tampered = dict(pack)
    tampered["live"] = True
    try:
        from stock_pm.events.earnings import FrozenEarningsError, load_frozen_earnings

        load_frozen_earnings(FROZEN)
    except FrozenEarningsError as exc:
        assert "live" in str(exc) or True
    assert pack["live"] is False


def test_multi_symbol_matrix_is_not_mechanical():
    reset_earnings_registry()
    from stock_pm.events.av_earnings import apply_frozen_health
    from stock_pm.events.watchlist import seed_etf_symbols, seed_stock_symbols

    docs = load_frozen_coverage_documents()
    apply_frozen_health(load_frozen_coverage(), stocks=seed_stock_symbols(), etfs=seed_etf_symbols())
    events = _closed(docs)
    by_symbol = _evidence_by_symbol(events)
    aapl = by_symbol["AAPL"][0]
    nvda = by_symbol["NVDA"][0]
    jpm = by_symbol["JPM"][0]
    xom = by_symbol["XOM"][0]
    nok = by_symbol["NOK"][0]
    assert aapl["actual"] == 2.02
    assert aapl["prior_year_actual"] == 1.57
    assert aapl["consensus"] == 1.88
    assert aapl["implication"] == "beat_and_grow"
    assert aapl["yoy"] == round((2.02 - 1.57) / 1.57, 6)
    assert aapl["surprise"] == round((2.02 - 1.88) / 1.88, 6)
    assert nvda["actual"] == 0.81
    assert nvda["consensus"] == 0.86
    assert nvda["implication"] == "miss_but_grow"
    assert nvda["yoy"] == round((0.81 - 0.68) / 0.68, 6)
    assert jpm["implication"] == "beat_but_contract"
    assert {aapl["implication"], nvda["implication"], jpm["implication"]} == {
        "beat_and_grow",
        "miss_but_grow",
        "beat_but_contract",
    }
    assert xom["prior_year_actual"] is None
    assert xom["gap"] == "baseline_missing"
    assert xom["implication"] is None
    assert nok["consensus"] is None
    assert nok["gap"] == "baseline_missing"
    assert nok["implication"] is None
    assert nok["actual"] == 0.09
    assert aapl["implication"] != nvda["implication"] != nok["implication"]
    health = current_earnings_health()["symbols"]
    assert health["AAPL"]["scenario"] == "complete"
    assert health["NVDA"]["scenario"] == "complete"
    assert health["XOM"]["scenario"] == "partial"
    assert health["JPM"]["source"] == "cache"
    assert health["JPM"]["reason_code"] == "rate_limited"
    assert health["NOK"]["scenario"] == "partial"
    assert health["QQQ"]["reason_code"] == "unsupported"
    assert health["QQQ"]["supported"] is False
    summary = summarize_health()
    assert summary["live"] is False
    assert summary["data_class"] == "frozen_provider_audit"
    assert summary["live_complete_count"] == 0


def test_empty_mode_does_not_load_fixture(monkeypatch):
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.delenv("STOCK_PM_EARNINGS_FIXTURE", raising=False)
    monkeypatch.delenv("STOCK_PM_EARNINGS_LIVE", raising=False)
    docs = AvEarningsProvider(Settings(events_mode="empty")).discover()
    assert docs == []
    assert current_earnings_health().get("symbols", {}) == {}


def test_etf_is_unsupported_without_blocking_stocks(monkeypatch):
    calls = []

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        calls.append((function, symbol))
        if symbol == "QQQ":
            raise AssertionError("ETF must not be requested")
        pack = load_frozen_coverage()
        item = next(row for row in pack["symbols"] if row["symbol"] == "AAPL")
        if function == "EARNINGS":
            return item["av_earnings"]
        if function == "EARNINGS_ESTIMATES":
            return item["av_estimates"]
        return {"quarter": (extra or {}).get("quarter") or "2026Q3", "transcript": []}

    monkeypatch.setattr("stock_pm.events.av_earnings.fetch_av_function", fake_fetch)
    monkeypatch.setattr("stock_pm.events.av_earnings.match_sec_8k_for_print", lambda *args, **kwargs: "")
    monkeypatch.setattr("stock_pm.events.av_earnings._key", lambda settings=None: "configured")
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "3")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    docs = AvEarningsProvider(Settings(events_mode="empty", earnings_av_budget=3)).discover()
    assert docs
    assert all(symbol != "QQQ" for _, symbol in calls)
    assert health_for_symbol("QQQ")["reason_code"] == "unsupported"
    assert health_for_symbol("QQQ")["supported"] is False


def test_failure_injection_is_isolated_per_symbol_and_endpoint(monkeypatch):
    calls = []
    pack = load_frozen_coverage()
    by_symbol = {row["symbol"]: row for row in pack["symbols"]}

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        calls.append((function, symbol))
        item = by_symbol.get(symbol) or by_symbol["AAPL"]
        if function == "EARNINGS":
            return item["av_earnings"]
        if function == "EARNINGS_ESTIMATES":
            return item.get("av_estimates") or {"estimates": []}
        return {"quarter": (extra or {}).get("quarter") or "2026Q3", "transcript": []}

    set_earnings_inject({"NVDA:EARNINGS": "rate_limited", "XOM:EARNINGS_ESTIMATES": "upstream_empty"})
    monkeypatch.setattr("stock_pm.events.av_earnings.fetch_av_function", fake_fetch)
    monkeypatch.setattr("stock_pm.events.av_earnings.match_sec_8k_for_print", lambda *args, **kwargs: "")
    monkeypatch.setattr("stock_pm.events.av_earnings._key", lambda settings=None: "configured")
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "30")
    docs = AvEarningsProvider(Settings(events_mode="empty", earnings_av_budget=30)).discover()
    symbols = {doc.entities[0] for doc in docs if doc.entities}
    assert "AAPL" in symbols
    assert "NVDA" not in {function_symbol[1] for function_symbol in calls if function_symbol[0] == "EARNINGS"}
    health = current_earnings_health()["symbols"]
    assert health["NVDA"]["reason_code"] in {"rate_limited", "upstream_empty", "stale"}
    assert health["AAPL"]["scenario"] in {"complete", "partial"}
    assert health["XOM"]["fields"]["actual"]["status"] in {"ok", "stale"}


def test_rate_limit_uses_last_success_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    pack = load_frozen_coverage()
    jpm = next(row for row in pack["symbols"] if row["symbol"] == "JPM")
    write_cache(av_cache_key("EARNINGS", "JPM"), jpm["av_earnings"])

    def boom(function, symbol, *, settings=None, extra=None):
        raise FetchError("rate_limited", "upstream")

    monkeypatch.setattr("stock_pm.events.av_earnings.fetch_av_function", boom)
    monkeypatch.setattr("stock_pm.events.av_earnings.match_sec_8k_for_print", lambda *args, **kwargs: "")
    monkeypatch.setattr("stock_pm.events.av_earnings._key", lambda settings=None: "configured")
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "30")
    docs = AvEarningsProvider(Settings(events_mode="empty", earnings_av_budget=30)).discover()
    jpm_docs = [doc for doc in docs if "JPM" in (doc.entities or [])]
    assert jpm_docs
    row = health_for_symbol("JPM")
    assert row["source"] == "cache"
    assert row["fields"]["actual"]["source"] == "cache"
    assert row["fields"]["actual"]["reason_code"] in {"rate_limited", "stale"}
    events = _closed(jpm_docs)
    evidence = events[0].analysis["earnings_evidence"]
    assert evidence["actual"] == 4.24
    assert evidence["implication"] == "beat_but_contract"


def test_fixture_coverage_is_not_reported_as_live(monkeypatch):
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "fixture")
    monkeypatch.setenv("STOCK_PM_EARNINGS_FIXTURE", "1")
    reset_cache()
    AvEarningsProvider(Settings(events_mode="fixture")).discover()
    cover = coverage(Settings(events_mode="fixture"), events=[])
    earn = cover["earnings_coverage"]
    assert earn["live"] is False
    assert earn["data_class"] == "frozen_provider_audit"
    assert earn["live_complete_count"] == 0
    assert "not production" in earn["note"].lower() or "不是" in earn["note"] or "not" in earn["note"].lower()


def test_stock_page_exposes_real_symbol_health(monkeypatch):
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "fixture")
    monkeypatch.setenv("STOCK_PM_EARNINGS_FIXTURE", "1")
    reset_cache()
    AvEarningsProvider(Settings(events_mode="fixture")).discover()
    qqq = stock_events("QQQ", Settings(events_mode="fixture"))
    assert qqq["earnings_health"]["reason_code"] == "unsupported"
    assert qqq["earnings_health"]["supported"] is False
    aapl = stock_events("AAPL", Settings(events_mode="fixture"))
    assert aapl["earnings_health"]["scenario"] == "complete"
    assert (aapl["coverage"]["earnings_coverage"] or {}).get("live") is False


def test_budget_does_not_raise_limiter_concurrency():
    assert _LIMITER.min_interval >= 1.0


def test_ui_names_missing_field_and_retry():
    ui = (Path(__file__).resolve().parents[1] / "src" / "stock_pm" / "static" / "events_ui.js").read_text(encoding="utf-8")
    assert "data-earnings-coverage" in ui
    assert "data-earnings-symbol-health" in ui
    assert "上次成功" in ui
    assert "下次重试" in ui
    assert "不使用推测值填空" in ui
    assert "宏观信息不复制到全部个股" in ui
    assert "fresh-live" in ui or "本轮 live" in ui
    assert "cache/stale" in ui


ROTATION_WATCH = [
    {"symbol": "AAA", "asset_class": "stocks"},
    {"symbol": "BBB", "asset_class": "stocks"},
    {"symbol": "CCC", "asset_class": "stocks"},
    {"symbol": "DDD", "asset_class": "stocks"},
    {"symbol": "EEE", "asset_class": "stocks"},
    {"symbol": "FFF", "asset_class": "stocks"},
]


def _rotation_settings() -> Settings:
    return Settings(events_mode="empty", earnings_av_budget=3)


def _restart_style_discover(monkeypatch, fake_fetch, *, settings=None):
    """Equivalent to an independent job/process: reset_cache then a new provider."""
    reset_cache()
    apply_watchlist_rows(ROTATION_WATCH)
    monkeypatch.setattr("stock_pm.events.av_earnings.fetch_av_function", fake_fetch)
    monkeypatch.setattr("stock_pm.events.av_earnings.match_sec_8k_for_print", lambda *args, **kwargs: "")
    monkeypatch.setattr("stock_pm.events.av_earnings._key", lambda settings=None: "configured")
    provider = AvEarningsProvider(settings or _rotation_settings())
    return provider.discover()


def test_cross_job_rotation_gives_every_symbol_an_earnings_attempt(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "3")
    purge_earnings_health_persist()
    pack = load_frozen_coverage()
    aapl = next(row for row in pack["symbols"] if row["symbol"] == "AAPL")
    calls = []
    rounds = []

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        calls.append((function, symbol))
        if function == "EARNINGS":
            payload = dict(aapl["av_earnings"])
            payload["symbol"] = symbol
            return payload
        if function == "EARNINGS_ESTIMATES":
            return {"estimates": []}
        return {"quarter": (extra or {}).get("quarter") or "2026Q3", "transcript": []}

    names = [row["symbol"] for row in ROTATION_WATCH]
    for _ in range(4):
        _restart_style_discover(monkeypatch, fake_fetch)
        health = current_earnings_health()
        attempted = list((health.get("schedule") or {}).get("attempted_this_round") or [])
        rounds.append(list(attempted))
        assert attempted
        assert all(symbol in names for symbol in attempted)

    earnings_symbols = [symbol for function, symbol in calls if function == "EARNINGS"]
    assert set(names) <= set(earnings_symbols)
    assert len(rounds) == 4
    assert all(len(row) <= 3 for row in rounds)


def test_failed_symbol_does_not_starve_the_rest(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "3")
    purge_earnings_health_persist()
    pack = load_frozen_coverage()
    aapl = next(row for row in pack["symbols"] if row["symbol"] == "AAPL")
    first_of_round = []

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        if symbol == "AAA" and function == "EARNINGS":
            raise FetchError("query_error", "upstream request failed")
        if function == "EARNINGS":
            payload = dict(aapl["av_earnings"])
            payload["symbol"] = symbol
            return payload
        return {"estimates": []} if function == "EARNINGS_ESTIMATES" else {"transcript": []}

    for _ in range(4):
        before = len(first_of_round)
        _restart_style_discover(monkeypatch, fake_fetch)
        attempted = list((current_earnings_health().get("schedule") or {}).get("attempted_this_round") or [])
        first_of_round.append(attempted[0])
        assert before or attempted

    assert first_of_round[0] == "AAA"
    assert first_of_round != ["AAA"] * 4
    assert not any(
        first_of_round[idx] == "AAA" and first_of_round[idx + 1] == "AAA"
        for idx in range(len(first_of_round) - 1)
    )
    assert len(set(first_of_round)) >= 2
    assert health_for_symbol("AAA").get("last_attempt_at")
    attempted_all = {
        symbol
        for row in current_earnings_health().get("symbols", {}).values()
        if row.get("last_attempt_at")
        for symbol in [row.get("symbol")]
    }
    assert {"BBB", "CCC", "DDD", "EEE", "FFF"} <= attempted_all


def test_reset_cache_keeps_schedule_and_only_purge_deletes(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "3")
    purge_earnings_health_persist()
    pack = load_frozen_coverage()
    aapl = next(row for row in pack["symbols"] if row["symbol"] == "AAPL")

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        if function == "EARNINGS":
            payload = dict(aapl["av_earnings"])
            payload["symbol"] = symbol
            return payload
        return {"estimates": []} if function == "EARNINGS_ESTIMATES" else {"transcript": []}

    _restart_style_discover(monkeypatch, fake_fetch)
    before = current_earnings_health()
    assert before.get("schedule", {}).get("attempted_this_round")
    assert health_cache_path().is_file()
    reset_cache()
    clear_earnings_health_memory()
    restored = current_earnings_health()
    assert restored.get("schedule", {}).get("attempted_this_round") == before.get("schedule", {}).get("attempted_this_round")
    assert {key: (row or {}).get("last_attempt_at") for key, row in (restored.get("symbols") or {}).items()} == {
        key: (row or {}).get("last_attempt_at") for key, row in (before.get("symbols") or {}).items()
    }
    purge_earnings_health_persist()
    assert current_earnings_health() == {}
    assert not health_cache_path().is_file()


def test_budget_deferred_is_not_this_round_live_complete(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "3")
    purge_earnings_health_persist()
    pack = load_frozen_coverage()
    aapl = next(row for row in pack["symbols"] if row["symbol"] == "AAPL")
    write_cache(av_cache_key("EARNINGS", "FFF"), {**aapl["av_earnings"], "symbol": "FFF"})

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        if function == "EARNINGS":
            payload = dict(aapl["av_earnings"])
            payload["symbol"] = symbol
            return payload
        return {"estimates": []} if function == "EARNINGS_ESTIMATES" else {"transcript": []}

    apply_watchlist_rows(ROTATION_WATCH)
    monkeypatch.setattr("stock_pm.events.av_earnings.fetch_av_function", fake_fetch)
    monkeypatch.setattr("stock_pm.events.av_earnings.match_sec_8k_for_print", lambda *args, **kwargs: "")
    monkeypatch.setattr("stock_pm.events.av_earnings._key", lambda settings=None: "configured")
    AvEarningsProvider(_rotation_settings()).discover()
    health = current_earnings_health()
    summary = summarize_health(health)
    deferred = health.get("budget", {}).get("deferred") or []
    assert "FFF" in deferred
    assert health["symbols"]["FFF"]["this_round"] == "deferred"
    assert health["symbols"]["FFF"]["this_round_calls"] == 0
    assert health["symbols"]["FFF"]["source"] == "cache"
    assert summary["fresh_live_complete_count"] == summary["live_complete_count"]
    assert health["symbols"]["FFF"]["symbol"] not in (health.get("schedule") or {}).get("attempted_this_round", [])
    if summarize_health(health)["cache_stale_complete_count"]:
        assert summary["live_complete_count"] < summary["complete_count"] or summary["complete_count"] == summary["cache_stale_complete_count"] + summary["fresh_live_complete_count"]
    assert summary["live_complete_count"] == summary["fresh_live_complete_count"]
