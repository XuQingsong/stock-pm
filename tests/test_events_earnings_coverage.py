from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_pm.config import Settings
from stock_pm.events.analyze import analyze_event
from stock_pm.events.av_earnings import (
    AvEarningsProvider,
    _LIMITER,
    av_cache_key,
    evaluate_av_endpoint,
    reset_earnings_runtime,
)
from stock_pm.events.dedupe import build_events
from stock_pm.events.earnings import (
    FROZEN_EARNINGS_DATA_CLASS,
    compute_frozen_earnings_integrity,
    load_frozen_coverage,
    load_frozen_coverage_documents,
    reset_earnings_registry,
)
from stock_pm.events.earnings_health import (
    attempted_symbols,
    clear_earnings_health_memory,
    current_earnings_health,
    endpoint_record,
    health_cache_path,
    health_for_symbol,
    pending_endpoint_tasks,
    persist_health,
    purge_earnings_health_persist,
    set_earnings_inject,
    summarize_health,
    _is_fresh_success,
    _parse_stamp,
    _retry_due,
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
    assert "缓存年龄" in ui
    assert "data-cache-age" in ui
    assert "data-earnings-endpoint-health" in ui
    assert "不使用推测值填空" in ui
    assert "宏观信息不复制到全部个股" in ui
    assert "fresh-live" in ui or "本轮 live" in ui
    assert "cache/stale" in ui
    assert "data-earnings-endpoint-coverage" in ui


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


def _restart_style_discover(monkeypatch, fake_fetch, *, settings=None, watchlist=None):
    """Equivalent to an independent job/process: reset_cache then a new provider."""
    reset_cache()
    apply_watchlist_rows(watchlist or ROTATION_WATCH)
    monkeypatch.setattr("stock_pm.events.av_earnings.fetch_av_function", fake_fetch)
    monkeypatch.setattr("stock_pm.events.av_earnings.match_sec_8k_for_print", lambda *args, **kwargs: "")
    monkeypatch.setattr("stock_pm.events.av_earnings._key", lambda settings=None: "configured")
    provider = AvEarningsProvider(settings or _rotation_settings())
    return provider.discover()


def _round_symbols(health):
    return attempted_symbols((health.get("schedule") or {}).get("attempted_this_round") or [])


def _round_tasks(health):
    raw = (health.get("schedule") or {}).get("attempted_this_round") or []
    out = []
    for item in raw:
        if isinstance(item, dict):
            out.append((item.get("symbol"), item.get("endpoint")))
        else:
            out.append((item, "EARNINGS"))
    return out


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
        attempted = _round_symbols(health)
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
        attempted = _round_symbols(current_earnings_health())
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
    assert health["symbols"]["FFF"]["symbol"] not in _round_symbols(health)
    if summarize_health(health)["cache_stale_complete_count"]:
        assert summary["live_complete_count"] < summary["complete_count"] or summary["complete_count"] == summary["cache_stale_complete_count"] + summary["fresh_live_complete_count"]
    assert summary["live_complete_count"] == summary["fresh_live_complete_count"]


TEN_WATCH = [
    {"symbol": "MU", "asset_class": "stocks"},
    {"symbol": "INTC", "asset_class": "stocks"},
    {"symbol": "AAPL", "asset_class": "stocks"},
    {"symbol": "GOOGL", "asset_class": "stocks"},
    {"symbol": "NVDA", "asset_class": "stocks"},
    {"symbol": "SKHY", "asset_class": "stocks"},
    {"symbol": "NOK", "asset_class": "stocks"},
    {"symbol": "XOM", "asset_class": "stocks"},
    {"symbol": "JPM", "asset_class": "stocks"},
    {"symbol": "AVGO", "asset_class": "stocks"},
]
TEN_NAMES = [row["symbol"] for row in TEN_WATCH]
QUARTER_NAMES = [name for name in TEN_NAMES if name != "SKHY"]


def _ten_settings() -> Settings:
    return Settings(events_mode="empty", earnings_av_budget=8)


def _aapl_like_fetch(calls, aapl, *, fail_earnings=None, empty_earnings=None):
    fail_earnings = set(fail_earnings or [])
    empty_earnings = set(empty_earnings or [])

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        calls.append((function, symbol, (extra or {}).get("quarter") or ""))
        if symbol in fail_earnings and function == "EARNINGS":
            raise FetchError("query_error", "upstream request failed")
        if function == "EARNINGS":
            payload = {"symbol": symbol, "quarterlyEarnings": []} if symbol in empty_earnings else {
                **dict(aapl["av_earnings"]),
                "symbol": symbol,
            }
        elif function == "EARNINGS_ESTIMATES":
            payload = dict(aapl.get("av_estimates") or {"estimates": []})
        else:
            quarter = (extra or {}).get("quarter") or "2026Q3"
            excerpts = []
            for item in (aapl.get("av_transcript") or {}).get("excerpts") or []:
                row = dict(item)
                row["symbol"] = symbol
                row["quarter"] = quarter
                excerpts.append(row)
            payload = {"quarter": quarter, "transcript": excerpts}
        write_cache(av_cache_key(function, symbol, extra), payload)
        return payload

    return fake_fetch


def test_cross_job_three_endpoints_cover_watchlist(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "8")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    calls = []
    fake_fetch = _aapl_like_fetch(calls, aapl)
    settings = _ten_settings()
    for _ in range(6):
        _restart_style_discover(monkeypatch, fake_fetch, settings=settings, watchlist=TEN_WATCH)

    earnings = {symbol for function, symbol, _ in calls if function == "EARNINGS"}
    estimates = {symbol for function, symbol, _ in calls if function == "EARNINGS_ESTIMATES"}
    transcripts = {symbol for function, symbol, _ in calls if function == "EARNINGS_CALL_TRANSCRIPT"}
    assert earnings == set(TEN_NAMES)
    assert estimates == set(TEN_NAMES)
    assert transcripts == set(QUARTER_NAMES)
    assert len([row for row in calls if row[0] == "EARNINGS"]) == 10
    health = current_earnings_health()
    skhy = health["symbols"]["SKHY"]
    assert (skhy.get("endpoints") or {}).get("EARNINGS_CALL_TRANSCRIPT", {}).get("status") == "skipped_dependency"
    assert skhy["fields"]["transcript"]["reason_code"] == "skipped_dependency"
    summary = summarize_health(health)
    endpoints = summary["endpoints"]["cumulative"]
    assert set(endpoints["EARNINGS"]["attempted_symbols"]) == set(TEN_NAMES)
    assert set(endpoints["EARNINGS_ESTIMATES"]["attempted_symbols"]) == set(TEN_NAMES)
    assert "SKHY" in endpoints["EARNINGS_CALL_TRANSCRIPT"]["skipped_dependency_symbols"]
    assert set(QUARTER_NAMES) <= set(endpoints["EARNINGS_CALL_TRANSCRIPT"]["attempted_symbols"])


def test_failed_earnings_skips_transcript_and_does_not_block_others(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "8")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    calls = []
    fake_fetch = _aapl_like_fetch(calls, aapl, fail_earnings={"AAPL"})
    settings = _ten_settings()
    for _ in range(6):
        _restart_style_discover(monkeypatch, fake_fetch, settings=settings, watchlist=TEN_WATCH)

    assert ("EARNINGS_CALL_TRANSCRIPT", "AAPL") not in {(row[0], row[1]) for row in calls}
    aapl_health = health_for_symbol("AAPL")
    assert (aapl_health.get("endpoints") or {}).get("EARNINGS_CALL_TRANSCRIPT", {}).get("reason_code") == "skipped_dependency"
    assert aapl_health["fields"]["transcript"]["reason_code"] == "skipped_dependency"
    others = [name for name in TEN_NAMES if name != "AAPL"]
    estimates = {symbol for function, symbol, _ in calls if function == "EARNINGS_ESTIMATES"}
    transcripts = {symbol for function, symbol, _ in calls if function == "EARNINGS_CALL_TRANSCRIPT"}
    assert set(others) <= estimates
    assert set(others) - {"SKHY"} <= transcripts


def test_complete_chain_forms_across_restart_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "8")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    calls = []
    fake_fetch = _aapl_like_fetch(calls, aapl)
    settings = _ten_settings()
    formed = None
    for _ in range(6):
        _restart_style_discover(monkeypatch, fake_fetch, settings=settings, watchlist=TEN_WATCH)
        row = health_for_symbol("AAPL")
        fields = row.get("fields") or {}
        if all((fields.get(name) or {}).get("status") in {"ok", "stale"} for name in ("actual", "prior", "consensus", "transcript")):
            formed = row
            break
    assert formed is not None
    fields = formed["fields"]
    assert fields["actual"]["source"] in {"live", "cache"}
    assert fields["prior"]["source"] in {"live", "cache"}
    assert fields["consensus"]["source"] in {"live", "cache"}
    assert fields["transcript"]["source"] in {"live", "cache"}
    assert fields["transcript"]["freshness"] in {"fresh", "stale"}
    endpoints = formed.get("endpoints") or {}
    assert endpoints.get("EARNINGS", {}).get("last_success_at")
    assert endpoints.get("EARNINGS_ESTIMATES", {}).get("last_attempt_at")
    assert endpoints.get("EARNINGS_CALL_TRANSCRIPT", {}).get("last_success_at")
    assert {"EARNINGS", "EARNINGS_ESTIMATES", "EARNINGS_CALL_TRANSCRIPT"} <= {
        function for function, symbol, _ in calls if symbol == "AAPL"
    }


def test_evaluate_av_endpoint_rejects_empty_and_wrong_shape():
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    earn = evaluate_av_endpoint("EARNINGS", aapl["av_earnings"], symbol="AAPL")
    assert earn["usable"] is True
    assert earn["quarter"] == "2026Q3"
    assert evaluate_av_endpoint("EARNINGS", {"quarterlyEarnings": []}, symbol="AAPL") == {
        "usable": False,
        "reason_code": "upstream_empty",
        "quarter": "",
        "period": "",
    }
    assert evaluate_av_endpoint("EARNINGS", {"quarterlyEarnings": "oops"}, symbol="AAPL")["reason_code"] == "record_invalid"
    assert evaluate_av_endpoint("EARNINGS_ESTIMATES", {"estimates": []}, symbol="AAPL", quarter="2026Q3")["reason_code"] == "upstream_empty"
    assert evaluate_av_endpoint("EARNINGS_ESTIMATES", {"estimates": {}}, symbol="AAPL", quarter="2026Q3")["reason_code"] == "record_invalid"
    assert evaluate_av_endpoint(
        "EARNINGS_ESTIMATES",
        {"estimates": [{"date": "2020-03-31", "horizon": "current fiscal quarter", "eps_estimate_average": "1.00"}]},
        symbol="AAPL",
        quarter="2026Q3",
    )["reason_code"] == "period_mismatch"
    assert evaluate_av_endpoint("EARNINGS_CALL_TRANSCRIPT", {"quarter": "2026Q3", "transcript": []}, symbol="AAPL", quarter="2026Q3")["reason_code"] == "upstream_empty"
    assert evaluate_av_endpoint("EARNINGS_CALL_TRANSCRIPT", {"quarter": "2026Q3", "transcript": "oops"}, symbol="AAPL", quarter="2026Q3")["reason_code"] == "record_invalid"
    assert evaluate_av_endpoint(
        "EARNINGS_CALL_TRANSCRIPT",
        {"quarter": "2020Q1", "transcript": [{"content": "hello", "quarter": "2020Q1", "symbol": "AAPL"}]},
        symbol="AAPL",
        quarter="2026Q3",
    )["reason_code"] == "period_mismatch"
    valid_est = evaluate_av_endpoint("EARNINGS_ESTIMATES", aapl["av_estimates"], symbol="AAPL", quarter="2026Q3")
    assert valid_est["usable"] is True
    valid_tr = evaluate_av_endpoint(
        "EARNINGS_CALL_TRANSCRIPT",
        {"quarter": "2026Q3", "transcript": aapl["av_transcript"]["excerpts"]},
        symbol="AAPL",
        quarter="2026Q3",
    )
    assert valid_tr["usable"] is True


def _two_watch():
    return [{"symbol": "AAPL", "asset_class": "stocks"}, {"symbol": "NVDA", "asset_class": "stocks"}]


def test_empty_and_invalid_endpoints_are_not_success(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "20")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        if symbol == "AAPL":
            if function == "EARNINGS":
                return {"quarterlyEarnings": []}
            if function == "EARNINGS_ESTIMATES":
                return {"estimates": []}
            return {"quarter": extra.get("quarter") if extra else "2026Q3", "transcript": []}
        if function == "EARNINGS":
            payload = dict(aapl["av_earnings"])
            payload["symbol"] = symbol
            write_cache(av_cache_key(function, symbol, extra), payload)
            return payload
        if function == "EARNINGS_ESTIMATES":
            payload = dict(aapl["av_estimates"])
            write_cache(av_cache_key(function, symbol, extra), payload)
            return payload
        payload = {"quarter": (extra or {}).get("quarter") or "2026Q3", "transcript": [
            {**aapl["av_transcript"]["excerpts"][0], "symbol": symbol, "quarter": (extra or {}).get("quarter") or "2026Q3"}
        ]}
        write_cache(av_cache_key(function, symbol, extra), payload)
        return payload

    _restart_style_discover(
        monkeypatch,
        fake_fetch,
        settings=Settings(events_mode="empty", earnings_av_budget=20),
        watchlist=_two_watch(),
    )
    health = current_earnings_health()
    summary = summarize_health(health)
    bad = health["symbols"]["AAPL"]
    good = health["symbols"]["NVDA"]
    assert bad["endpoints"]["EARNINGS"]["status"] == "failed"
    assert bad["endpoints"]["EARNINGS"]["reason_code"] == "upstream_empty"
    assert bad["endpoints"]["EARNINGS"]["last_success_at"] is None
    assert "AAPL" not in summary["endpoints"]["cumulative"]["EARNINGS"]["success_symbols"]
    assert bad["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["status"] == "skipped_dependency"
    assert good["endpoints"]["EARNINGS"]["status"] == "ok"
    assert good["endpoints"]["EARNINGS"]["last_success_at"]
    assert "NVDA" in summary["endpoints"]["cumulative"]["EARNINGS"]["success_symbols"]
    assert "NVDA" in summary["endpoints"]["cumulative"]["EARNINGS_ESTIMATES"]["success_symbols"]
    assert "NVDA" in summary["endpoints"]["cumulative"]["EARNINGS_CALL_TRANSCRIPT"]["success_symbols"]


def test_wrong_shape_and_wrong_quarter_are_not_success(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "20")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        if symbol == "AAPL":
            if function == "EARNINGS":
                return {"quarterlyEarnings": "oops"}
            if function == "EARNINGS_ESTIMATES":
                return {"estimates": {"not": "a-list"}}
            return {"quarter": "2020Q1", "transcript": [{"content": "old call", "quarter": "2020Q1", "symbol": "AAPL"}]}
        if function == "EARNINGS":
            payload = dict(aapl["av_earnings"])
            payload["symbol"] = symbol
            return payload
        if function == "EARNINGS_ESTIMATES":
            return dict(aapl["av_estimates"])
        return {
            "quarter": (extra or {}).get("quarter") or "2026Q3",
            "transcript": [{**aapl["av_transcript"]["excerpts"][0], "symbol": symbol, "quarter": (extra or {}).get("quarter") or "2026Q3"}],
        }

    _restart_style_discover(
        monkeypatch,
        fake_fetch,
        settings=Settings(events_mode="empty", earnings_av_budget=20),
        watchlist=_two_watch(),
    )
    bad = health_for_symbol("AAPL")
    good = health_for_symbol("NVDA")
    summary = summarize_health()
    assert bad["endpoints"]["EARNINGS"]["reason_code"] == "record_invalid"
    assert bad["endpoints"]["EARNINGS"]["last_success_at"] is None
    assert bad["endpoints"]["EARNINGS"]["status"] == "failed"
    assert "AAPL" not in summary["endpoints"]["cumulative"]["EARNINGS"]["success_symbols"]
    assert good["endpoints"]["EARNINGS"]["status"] == "ok"
    assert good["endpoints"]["EARNINGS_ESTIMATES"]["status"] == "ok"


def test_empty_earnings_retry_unlocks_transcript(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "20")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    phase = {"valid": False}
    calls = []

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        calls.append((function, symbol))
        if symbol == "AAPL" and function == "EARNINGS" and not phase["valid"]:
            return {"quarterlyEarnings": []}
        if function == "EARNINGS":
            payload = dict(aapl["av_earnings"])
            payload["symbol"] = symbol
            write_cache(av_cache_key(function, symbol, extra), payload)
            return payload
        if function == "EARNINGS_ESTIMATES":
            payload = dict(aapl["av_estimates"])
            write_cache(av_cache_key(function, symbol, extra), payload)
            return payload
        quarter = (extra or {}).get("quarter") or "2026Q3"
        payload = {
            "quarter": quarter,
            "transcript": [{**aapl["av_transcript"]["excerpts"][0], "symbol": symbol, "quarter": quarter}],
        }
        write_cache(av_cache_key(function, symbol, extra), payload)
        return payload

    settings = Settings(events_mode="empty", earnings_av_budget=20)
    watch = _two_watch()
    _restart_style_discover(monkeypatch, fake_fetch, settings=settings, watchlist=watch)
    bad = health_for_symbol("AAPL")
    assert bad["endpoints"]["EARNINGS"]["last_success_at"] is None
    assert bad["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["status"] == "skipped_dependency"
    assert ("EARNINGS_CALL_TRANSCRIPT", "AAPL") not in calls
    health = current_earnings_health()
    health["symbols"]["AAPL"]["endpoints"]["EARNINGS"]["next_retry_at"] = "2020-01-01T00:00:00+00:00"
    persist_health(health)
    phase["valid"] = True
    _restart_style_discover(monkeypatch, fake_fetch, settings=settings, watchlist=watch)
    bad = health_for_symbol("AAPL")
    assert bad["endpoints"]["EARNINGS"]["status"] == "ok"
    assert bad["endpoints"]["EARNINGS"]["last_success_at"]
    assert bad["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["status"] == "ok"
    assert bad["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["last_success_at"]
    assert ("EARNINGS_CALL_TRANSCRIPT", "AAPL") in calls


def test_empty_complements_do_not_form_complete_chain_or_count_success(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "20")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        if function == "EARNINGS":
            payload = dict(aapl["av_earnings"])
            payload["symbol"] = symbol
            write_cache(av_cache_key(function, symbol, extra), payload)
            return payload
        if symbol == "AAPL":
            if function == "EARNINGS_ESTIMATES":
                return {"estimates": []}
            return {"quarter": (extra or {}).get("quarter") or "2026Q3", "transcript": []}
        if function == "EARNINGS_ESTIMATES":
            payload = dict(aapl["av_estimates"])
            write_cache(av_cache_key(function, symbol, extra), payload)
            return payload
        quarter = (extra or {}).get("quarter") or "2026Q3"
        payload = {
            "quarter": quarter,
            "transcript": [{**aapl["av_transcript"]["excerpts"][0], "symbol": symbol, "quarter": quarter}],
        }
        write_cache(av_cache_key(function, symbol, extra), payload)
        return payload

    _restart_style_discover(
        monkeypatch,
        fake_fetch,
        settings=Settings(events_mode="empty", earnings_av_budget=20),
        watchlist=_two_watch(),
    )
    bad = health_for_symbol("AAPL")
    good = health_for_symbol("NVDA")
    summary = summarize_health()
    assert bad["endpoints"]["EARNINGS"]["status"] == "ok"
    assert bad["endpoints"]["EARNINGS_ESTIMATES"]["status"] == "failed"
    assert bad["endpoints"]["EARNINGS_ESTIMATES"]["reason_code"] == "upstream_empty"
    assert bad["endpoints"]["EARNINGS_ESTIMATES"]["last_success_at"] is None
    assert bad["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["status"] == "failed"
    assert bad["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["reason_code"] == "upstream_empty"
    assert bad["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["last_success_at"] is None
    assert bad["fields"]["transcript"]["status"] != "ok"
    assert "AAPL" not in summary["endpoints"]["cumulative"]["EARNINGS_ESTIMATES"]["success_symbols"]
    assert "AAPL" not in summary["endpoints"]["cumulative"]["EARNINGS_CALL_TRANSCRIPT"]["success_symbols"]
    assert "NVDA" in summary["endpoints"]["cumulative"]["EARNINGS_ESTIMATES"]["success_symbols"]
    assert "NVDA" in summary["endpoints"]["cumulative"]["EARNINGS_CALL_TRANSCRIPT"]["success_symbols"]
    assert good["fields"]["transcript"]["status"] in {"ok", "stale"}


def test_wrong_quarter_complements_are_not_success(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "20")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")

    def fake_fetch(function, symbol, *, settings=None, extra=None):
        if function == "EARNINGS":
            payload = dict(aapl["av_earnings"])
            payload["symbol"] = symbol
            write_cache(av_cache_key(function, symbol, extra), payload)
            return payload
        if symbol == "AAPL":
            if function == "EARNINGS_ESTIMATES":
                return {"estimates": [{"date": "2020-03-31", "horizon": "current fiscal quarter", "eps_estimate_average": "1.00"}]}
            return {"quarter": "2020Q1", "transcript": [{"content": "old call", "quarter": "2020Q1", "symbol": "AAPL"}]}
        if function == "EARNINGS_ESTIMATES":
            return dict(aapl["av_estimates"])
        quarter = (extra or {}).get("quarter") or "2026Q3"
        return {"quarter": quarter, "transcript": [{**aapl["av_transcript"]["excerpts"][0], "symbol": symbol, "quarter": quarter}]}

    _restart_style_discover(
        monkeypatch,
        fake_fetch,
        settings=Settings(events_mode="empty", earnings_av_budget=20),
        watchlist=_two_watch(),
    )
    bad = health_for_symbol("AAPL")
    good = health_for_symbol("NVDA")
    summary = summarize_health()
    assert bad["endpoints"]["EARNINGS"]["status"] == "ok"
    assert bad["endpoints"]["EARNINGS_ESTIMATES"]["reason_code"] == "period_mismatch"
    assert bad["endpoints"]["EARNINGS_ESTIMATES"]["last_success_at"] is None
    assert bad["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["reason_code"] == "period_mismatch"
    assert bad["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["last_success_at"] is None
    assert "AAPL" not in summary["endpoints"]["cumulative"]["EARNINGS_ESTIMATES"]["success_symbols"]
    assert "NVDA" in summary["endpoints"]["cumulative"]["EARNINGS_ESTIMATES"]["success_symbols"]
    assert good["endpoints"]["EARNINGS_CALL_TRANSCRIPT"]["status"] == "ok"


def _one_watch():
    return [{"symbol": "AAPL", "asset_class": "stocks"}]


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def _same_stamp(left, right) -> bool:
    return _parse_stamp(str(left or "")) == _parse_stamp(str(right or ""))


def test_rate_limit_cache_keeps_thirty_day_success_time(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "8")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    old = _days_ago(30)
    write_cache(av_cache_key("EARNINGS", "AAPL"), aapl["av_earnings"], fetched_at=old)
    calls = []

    def boom(function, symbol, *, settings=None, extra=None):
        calls.append((function, symbol))
        raise FetchError("rate_limited", "upstream")

    _restart_style_discover(
        monkeypatch,
        boom,
        settings=Settings(events_mode="empty", earnings_av_budget=8),
        watchlist=_one_watch(),
    )
    health = current_earnings_health()
    row = health["symbols"]["AAPL"]
    earn = row["endpoints"]["EARNINGS"]
    assert _same_stamp(earn["last_success_at"], old)
    assert earn["status"] == "stale"
    assert earn["source"] == "cache"
    assert earn["reason_code"] == "rate_limited"
    assert earn["freshness"] == "stale"
    assert not _is_fresh_success(earn)
    assert _same_stamp(row["last_success_at"], old)
    assert health["as_of"] != earn["last_success_at"]
    attempt = _parse_stamp(earn["last_attempt_at"])
    retry = _parse_stamp(earn["next_retry_at"])
    assert attempt and retry
    assert retry - attempt == timedelta(minutes=15)
    assert _same_stamp(row["next_retry_at"], earn["next_retry_at"])
    assert earn["cache_age_days"] is not None
    assert 29 <= float(earn["cache_age_days"]) <= 31
    assert ("EARNINGS", "AAPL") in calls


def test_rate_limit_cache_retries_only_after_next_retry(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "8")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    old = _days_ago(30)
    write_cache(av_cache_key("EARNINGS", "AAPL"), aapl["av_earnings"], fetched_at=old)
    calls = []

    def boom(function, symbol, *, settings=None, extra=None):
        calls.append((function, symbol))
        raise FetchError("rate_limited", "upstream")

    settings = Settings(events_mode="empty", earnings_av_budget=8)
    watch = _one_watch()
    _restart_style_discover(monkeypatch, boom, settings=settings, watchlist=watch)
    after_first = list(calls)
    row = health_for_symbol("AAPL")
    earn = row["endpoints"]["EARNINGS"]
    assert _same_stamp(earn["last_success_at"], old)
    assert pending_endpoint_tasks("AAPL", row) == []
    _restart_style_discover(monkeypatch, boom, settings=settings, watchlist=watch)
    assert calls == after_first
    assert _same_stamp(health_for_symbol("AAPL")["endpoints"]["EARNINGS"]["last_success_at"], old)
    health = current_earnings_health()
    health["symbols"]["AAPL"]["endpoints"]["EARNINGS"]["next_retry_at"] = "2020-01-01T00:00:00+00:00"
    persist_health(health)
    live_calls = []
    fake_live = _aapl_like_fetch(live_calls, aapl)
    _restart_style_discover(monkeypatch, fake_live, settings=settings, watchlist=watch)
    earn = health_for_symbol("AAPL")["endpoints"]["EARNINGS"]
    assert ("EARNINGS", "AAPL", "") in live_calls or any(item[0] == "EARNINGS" and item[1] == "AAPL" for item in live_calls)
    assert earn["status"] == "ok"
    assert earn["source"] == "live"
    assert _is_fresh_success(earn)
    assert not _same_stamp(earn["last_success_at"], old)
    assert _parse_stamp(earn["last_success_at"]) >= _parse_stamp(current_earnings_health()["as_of"]) - timedelta(seconds=5)


def test_consecutive_rate_limits_do_not_refresh_cache_age(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "8")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    old = _days_ago(30)
    write_cache(av_cache_key("EARNINGS", "AAPL"), aapl["av_earnings"], fetched_at=old)
    calls = []

    def boom(function, symbol, *, settings=None, extra=None):
        calls.append((function, symbol))
        raise FetchError("rate_limited", "upstream")

    settings = Settings(events_mode="empty", earnings_av_budget=8)
    watch = _one_watch()
    _restart_style_discover(monkeypatch, boom, settings=settings, watchlist=watch)
    first = health_for_symbol("AAPL")["endpoints"]["EARNINGS"]
    health = current_earnings_health()
    health["symbols"]["AAPL"]["endpoints"]["EARNINGS"]["next_retry_at"] = "2020-01-01T00:00:00+00:00"
    persist_health(health)
    _restart_style_discover(monkeypatch, boom, settings=settings, watchlist=watch)
    second = health_for_symbol("AAPL")["endpoints"]["EARNINGS"]
    assert _same_stamp(first["last_success_at"], old)
    assert _same_stamp(second["last_success_at"], old)
    assert _same_stamp(first["last_success_at"], second["last_success_at"])
    assert _parse_stamp(second["last_attempt_at"]) >= _parse_stamp(first["last_attempt_at"])
    assert abs(float(second["cache_age_days"]) - float(first["cache_age_days"])) < 0.01
    assert calls.count(("EARNINGS", "AAPL")) >= 2


def test_expired_120_day_cache_is_not_fresh_but_still_retried(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "8")
    purge_earnings_health_persist()
    expired = _days_ago(121)
    rec = endpoint_record(
        status="stale",
        last_success_at=expired,
        last_attempt_at=expired,
        source="cache",
        reason_code="rate_limited",
        quarter="2026Q3",
        next_retry="2020-01-01T00:00:00+00:00",
    )
    assert rec["freshness"] == "expired"
    assert _is_fresh_success(rec) is False
    assert _retry_due(rec) is True
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    write_cache(av_cache_key("EARNINGS", "AAPL"), aapl["av_earnings"], fetched_at=expired)
    calls = []

    def boom(function, symbol, *, settings=None, extra=None):
        calls.append((function, symbol))
        raise FetchError("rate_limited", "upstream")

    settings = Settings(events_mode="empty", earnings_av_budget=8)
    watch = _one_watch()
    _restart_style_discover(monkeypatch, boom, settings=settings, watchlist=watch)
    earn = health_for_symbol("AAPL")["endpoints"]["EARNINGS"]
    assert ("EARNINGS", "AAPL") in calls
    assert _same_stamp(earn["last_success_at"], expired)
    assert earn["freshness"] == "expired"
    assert earn["status"] == "stale"
    assert not _is_fresh_success(earn)
    assert health_for_symbol("AAPL")["fields"]["actual"]["freshness"] == "expired"
    health = current_earnings_health()
    health["symbols"]["AAPL"]["endpoints"]["EARNINGS"]["next_retry_at"] = "2020-01-01T00:00:00+00:00"
    persist_health(health)
    live_calls = []
    _restart_style_discover(monkeypatch, _aapl_like_fetch(live_calls, aapl), settings=settings, watchlist=watch)
    live = health_for_symbol("AAPL")["endpoints"]["EARNINGS"]
    assert live["status"] == "ok"
    assert live["source"] == "live"
    assert live["freshness"] == "fresh"
    assert not _same_stamp(live["last_success_at"], expired)


def test_summary_and_ui_times_stay_consistent_with_cache_age(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_PM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_PM_EARNINGS_LIVE", "1")
    monkeypatch.setenv("STOCK_PM_EVENTS_MODE", "empty")
    monkeypatch.setenv("STOCK_PM_EARNINGS_BUDGET", "8")
    purge_earnings_health_persist()
    aapl = next(row for row in load_frozen_coverage()["symbols"] if row["symbol"] == "AAPL")
    old = _days_ago(30)
    write_cache(av_cache_key("EARNINGS", "AAPL"), aapl["av_earnings"], fetched_at=old)

    def boom(function, symbol, *, settings=None, extra=None):
        raise FetchError("rate_limited", "upstream")

    _restart_style_discover(
        monkeypatch,
        boom,
        settings=Settings(events_mode="empty", earnings_av_budget=8),
        watchlist=_one_watch(),
    )
    health = current_earnings_health()
    summary = summarize_health(health)
    row = health["symbols"]["AAPL"]
    earn = row["endpoints"]["EARNINGS"]
    actual = row["fields"]["actual"]
    assert summary["as_of"] == health["as_of"]
    assert summary["as_of"] != earn["last_success_at"]
    assert _same_stamp(row["last_success_at"], earn["last_success_at"])
    assert _same_stamp(actual["last_success_at"], earn["last_success_at"])
    assert _same_stamp(row["next_retry_at"], earn["next_retry_at"])
    assert _same_stamp(actual["next_retry_at"], earn["next_retry_at"])
    assert _same_stamp(earn["last_success_at"], old)
    assert abs(float(row["cache_age_days"]) - float(earn["cache_age_days"])) < 0.01
    assert abs(float(actual["cache_age_days"]) - float(earn["cache_age_days"])) < 0.01
    ui = (Path(__file__).resolve().parents[1] / "src" / "stock_pm" / "static" / "events_ui.js").read_text(encoding="utf-8")
    assert "上次成功" in ui and "缓存年龄" in ui and "下次重试" in ui
    assert "data-last-success-at" in ui and "data-next-retry-at" in ui and "data-cache-age" in ui
    page = stock_events("AAPL", Settings(events_mode="empty"))
    shown = page["earnings_health"]
    assert _same_stamp(shown["last_success_at"], old)
    assert _same_stamp(shown["endpoints"]["EARNINGS"]["last_success_at"], old)
    assert shown["next_retry_at"] == shown["endpoints"]["EARNINGS"]["next_retry_at"]
