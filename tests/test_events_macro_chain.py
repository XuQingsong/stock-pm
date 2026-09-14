"""Phase 6A: market-level macro causal chain and selective transmission."""

from __future__ import annotations

from stock_pm.config import Settings
from stock_pm.events.analyze import analyze_event
from stock_pm.events.macro_chain import (
    LAYER_KINDS,
    apply_macro_chain_inject,
    apply_macro_inject,
    build_event_macro_chain,
    build_market_macro_chains,
    build_numeric_macro_chain,
    compare_same_basis,
    event_chain_id,
    load_frozen_6a_facts,
    load_macro_facts,
    reset_macro_cache,
    stable_chain_id,
    stock_macro_chains,
    summarize_macro_chains,
)
from stock_pm.events.service import market_center, reset_cache, stock_events
from stock_pm.events.types import EventClaim, EventSource, TrustedEvent


def setup_function() -> None:
    reset_cache()
    reset_macro_cache()


def _fact(**extra) -> dict:
    row = {
        "metric": "cpi",
        "name": "CPI-U",
        "actual": 0.40,
        "prior": 0.22,
        "consensus": 0.30,
        "unit": "percent",
        "series": "CPIAUCSL",
        "period": "2026-08-01",
        "prior_as_of": "2026-07-01",
        "consensus_as_of": "2026-08-01",
        "as_of": "2026-08-01T00:00:00+00:00",
        "source": "FRED",
        "http_source": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
        "status": "ok",
        "data_class": "frozen_provider_audit",
        "formula": "CPIAUCSL MoM%[t] = CPIAUCSL[t] / CPIAUCSL[t−1] − 1；与同口径 MoM% 共识比较",
        "comparison": "same_definition_mom_pct",
        "basis": "mom_pct",
        "prior_basis": "mom_pct",
        "consensus_basis": "mom_pct",
        "consensus_unit": "percent",
        "consensus_series": "CPIAUCSL",
        "consensus_rate_kind": "mom_pct",
        "rate_kind": "mom_pct",
        "index_level": 334.131,
        "index_prior": 332.8,
    }
    row.update(extra)
    return row


def _nfp(**extra) -> dict:
    return _fact(
        metric="nfp",
        name="NFP",
        actual=162.0,
        prior=21.0,
        consensus=140.0,
        unit="thousands",
        series="PAYEMS",
        formula="ΔPAYEMS[t] = PAYEMS[t] − PAYEMS[t−1]（千人）",
        comparison="same_definition_monthly_diff",
        basis="monthly_diff",
        prior_basis="monthly_diff",
        consensus_basis="monthly_diff",
        consensus_unit="thousands",
        consensus_series="PAYEMS",
        consensus_rate_kind=None,
        rate_kind=None,
        index_level=None,
        index_prior=None,
        http_source="https://fred.stlouisfed.org/graph/fredgraph.csv?id=PAYEMS",
        **extra,
    )


def _layer(chain: dict, name: str) -> dict:
    return next(row for row in chain["layers"] if row["id"] == name)


def _event(
    event_type: str,
    title: str,
    *,
    entities: list[str] | None = None,
    event_id: str | None = None,
    dedupe_group: str | None = None,
    event_time: str = "2026-09-01T15:00:00+00:00",
) -> TrustedEvent:
    source = EventSource(
        source_id="src_macro_6a",
        source_url="https://home.treasury.gov/news/press-releases/jy2609-refunding",
        canonical_url="https://home.treasury.gov/news/press-releases/jy2609-refunding",
        publisher="U.S. Treasury",
        source_tier=1,
        content_type="official_fact",
        fact_or_opinion="fact",
        primary_or_secondary="primary",
        title=title,
        published_at="2026-09-01T15:00:00+00:00",
    )
    claim = EventClaim(
        claim_id="cl_macro_6a",
        text=title,
        polarity="supports",
        source_id=source.source_id,
        source_url=source.source_url,
        publisher=source.publisher,
        excerpt=title,
        observed_at="2026-09-01T15:00:00+00:00",
    )
    event = TrustedEvent(
        event_id=event_id or f"evt-{event_type}",
        canonical_title=title,
        event_type=event_type,
        entities=list(entities or ["Treasury", "debt", "credit"]),
        countries=["US"],
        event_time=event_time,
        published_at=event_time,
        first_seen_at=event_time,
        updated_at=event_time,
        sources=[source],
        claims=[claim],
        dedupe_group=dedupe_group or event_id or f"evt-{event_type}",
        status="active",
        freshness="fresh",
        severity="high",
        scope="market",
        duration="weeks_to_months",
        invalidation="若财政部撤回或拍卖缩量，则融资/流动性观察失效",
    )
    analyze_event(event)
    return event


def test_a_cpi_above_consensus_to_duration():
    chain = build_numeric_macro_chain(_fact())
    assert chain["chain_id"] == stable_chain_id("inflation", "cpi", "2026-08-01")
    assert chain["status"] == "ok"
    assert chain["can_form_direction"] is False
    assert chain["percent_forecast"] is None
    assert _layer(chain, "fact")["layer_kind"] == "observable_fact"
    assert _layer(chain, "change")["layer_kind"] == "derived_analysis"
    assert _layer(chain, "expectation")["layer_kind"] == "conditional_expectation"
    assert "高于一致预期" in _layer(chain, "expectation")["text"]
    assert "不是已发生事实" in _layer(chain, "expectation")["text"]
    assert "通胀环比上升" not in _layer(chain, "expectation")["text"]
    assert "MoM" in _layer(chain, "fact")["text"]
    assert "CPIAUCSL[t] / CPIAUCSL[t−1]" in (_layer(chain, "fact")["text"] + _layer(chain, "change")["text"])
    assert "rates" in _layer(chain, "transmission")["channels"]
    assert "discount_rate" in _layer(chain, "transmission")["channels"]
    assert "高估值成长" in _layer(chain, "impact")["text"]
    what = _layer(chain, "what_changes")
    assert "通胀回落" in (what.get("text") or "") or any("通胀" in item for item in (what.get("follow_ups") or []))
    assert "反向" in (what.get("text") or "") or any("反转" in item for item in (what.get("follow_ups") or []))
    symbols = {row["symbol"] for row in chain["exposures"]}
    assert "NVDA" in symbols
    assert "AAPL" not in symbols
    assert "NOK" not in symbols
    assert all(row.get("evidence_refs") for row in chain["layers"])


def test_b_nfp_same_basis_not_level():
    ok = build_numeric_macro_chain(_nfp())
    assert ok["status"] == "ok"
    assert "就业韧性" in _layer(ok, "expectation")["text"]
    mismatched = _nfp()
    mismatched["prior"] = 159533.0
    mismatched["prior_basis"] = "employment_stock"
    bad = compare_same_basis(mismatched)
    assert bad["status"] == "degraded"
    assert bad["reason"] == "period_or_basis_mismatch"
    mixed_row = _nfp()
    mixed_row["consensus"] = 3.2
    mixed_row["consensus_unit"] = "percent"
    mixed = compare_same_basis(mixed_row)
    assert mixed["status"] == "degraded"


def test_c_vix_is_amplifier_only():
    vix = _fact(metric="vix", name="VIX", actual=18.4, prior=16.46, consensus=None, unit="index", series="VIXCLS", period="2026-09-10", http_source="https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS")
    us2y = _fact(metric="us2y", name="US2Y", actual=4.43, prior=4.56, consensus=None, unit="percent", series="DGS2", period="2026-09-10", http_source="https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2")
    chain = build_numeric_macro_chain(vix, companion_facts=[vix, us2y])
    assert chain["vix_role"] == "risk_confirmation_only"
    assert chain["can_form_direction"] is False
    assert chain["exposures"] == []
    assert "不单独推导个股" in _layer(chain, "expectation")["text"]
    assert any("US2Y" in str(row.get("text") or "") for row in chain["counter_evidence"])
    mapped = stock_macro_chains([chain], "NVDA")
    assert mapped == []


def test_d_oil_selective_xom_not_aapl_nok():
    wti = _fact(metric="wti", name="WTI", actual=78.4, prior=72.1, consensus=None, unit="usd_per_barrel", series="DCOILWTICO", period="2026-09-10")
    chain = build_numeric_macro_chain(wti)
    symbols = {row["symbol"]: row for row in chain["exposures"]}
    assert "XOM" in symbols
    assert symbols["XOM"]["channel"] == "commodity_revenue"
    assert "AAPL" not in symbols
    assert "NOK" not in symbols
    assert "通胀" in _layer(chain, "impact")["text"] or "成本" in _layer(chain, "impact")["text"]


def test_e_war_not_copied_to_every_stock():
    event = _event("war_sanctions", "Treasury OFAC designates additional energy sanctions", entities=["Iran", "oil", "energy"])
    chain = event.analysis["macro_chain"]
    symbols = {row["symbol"] for row in chain["exposures"]}
    assert "XOM" in symbols
    assert "NVDA" in symbols or "JPM" in symbols
    assert "NOK" not in symbols
    assert chain["chain_id"].startswith("macro:geopolitics:")
    nvda = stock_macro_chains([chain], "NVDA")
    xom = stock_macro_chains([chain], "XOM")
    nok = stock_macro_chains([chain], "NOK")
    if nvda and xom:
        assert nvda[0]["why_relevant"] != xom[0]["why_relevant"]
    assert nok == []


def test_f_debt_only_with_exposure():
    event = _event("sovereign_or_corporate_debt", "Treasury increased coupon auction sizes citing funding and liquidity conditions")
    chain = event.analysis["macro_chain"]
    symbols = {row["symbol"] for row in chain["exposures"]}
    assert symbols == {"JPM"}
    assert "liquidity" in _layer(chain, "transmission")["channels"]
    assert stock_macro_chains([chain], "AAPL") == []
    assert stock_macro_chains([chain], "XOM") == []
    assert stock_macro_chains([chain], "JPM")[0]["cited_chain_id"] == chain["chain_id"]


def test_g_local_degrade_does_not_kill_other_chains():
    facts = [_fact(prior=None, consensus=None), _nfp()]
    chains = build_market_macro_chains(facts=facts)
    by_metric = {row["metric"]: row for row in chains}
    assert by_metric["cpi"]["status"] == "degraded"
    assert by_metric["cpi"]["degrade_reason"] == "missing_baseline"
    assert "笼统" not in (by_metric["cpi"]["degrade_detail"] or "")
    assert "缺少同口径" in by_metric["cpi"]["degrade_detail"]
    assert by_metric["nfp"]["status"] == "ok"


def test_h_reverse_update_keeps_stable_id():
    first = build_numeric_macro_chain(_fact())
    reversed_facts = apply_macro_inject([_fact()], "reverse_cpi")
    second = build_numeric_macro_chain(reversed_facts[0])
    assert first["chain_id"] == second["chain_id"]
    assert _layer(first, "change")["direction"] == "up"
    assert _layer(second, "change")["direction"] == "down"
    assert "前移" in _layer(second, "expectation")["text"]


def test_inject_source_fail_and_period_mismatch():
    rows = apply_macro_inject([_fact(metric="us2y", consensus=None), _nfp()], "source_fail_us2y,period_mismatch_nfp")
    us2y = build_numeric_macro_chain(next(row for row in rows if row["metric"] == "us2y"))
    nfp = build_numeric_macro_chain(next(row for row in rows if row["metric"] == "nfp"))
    assert us2y["degrade_reason"] == "source_failed"
    assert nfp["degrade_reason"] == "period_or_basis_mismatch"


def test_production_empty_does_not_load_frozen(monkeypatch):
    monkeypatch.setattr(
        "stock_pm.series.collect_live_macro_overlay",
        lambda settings=None: ([], set(), {}),
    )
    reset_macro_cache()
    rows = load_macro_facts(Settings(events_mode="empty"))
    assert rows == []
    frozen = load_frozen_6a_facts()
    assert frozen
    assert all(row.get("live") is False for row in frozen)


def test_fixture_market_center_exposes_summary_and_layers():
    center = market_center(Settings(events_mode="fixture"))
    assert center["macro_driver_summary"]["count"] >= 1
    assert center["macro_chains"]
    cpi = next(row for row in center["macro_chains"] if row["metric"] == "cpi")
    assert cpi["data_class"] == "frozen_provider_audit"
    assert cpi["live"] is False
    assert set(LAYER_KINDS) <= {layer["id"] for layer in cpi["layers"]}
    nvda = stock_events("NVDA", Settings(events_mode="fixture"))
    aapl = stock_events("AAPL", Settings(events_mode="fixture"))
    xom = stock_events("XOM", Settings(events_mode="fixture"))
    nok = stock_events("NOK", Settings(events_mode="fixture"))
    nvda_metrics = {row["metric"] for row in nvda["macro_chains"]}
    aapl_metrics = {row["metric"] for row in aapl["macro_chains"]}
    xom_metrics = {row["metric"] for row in xom["macro_chains"]}
    nok_metrics = {row["metric"] for row in nok["macro_chains"]}
    assert "cpi" in nvda_metrics
    assert "cpi" not in aapl_metrics
    assert "wti" in xom_metrics
    assert "wti" not in aapl_metrics
    assert "wti" not in nok_metrics
    assert nvda["risk_state"]["role"] == "risk_confirmation_only"
    assert all(row.get("can_form_direction") is not True for row in nvda["macro_chains"])


def test_fixture_then_live_does_not_reuse_frozen_cache(monkeypatch):
    live_row = {
        "event_type": "cpi",
        "name": "CPI-U",
        "actual": 301.2,
        "prior": 300.1,
        "prior_as_of": "2026-07-01",
        "as_of": "2026-08-01",
        "event_time": "2026-08-01T00:00:00+00:00",
        "unit": "index",
        "series": "CPIAUCSL",
        "http_source": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
        "source": "FRED",
        "status": "ok",
        "comparison": "same_series_same_unit",
    }
    monkeypatch.setattr(
        "stock_pm.series.collect_live_macro_overlay",
        lambda settings=None: ([live_row], set(), {}),
    )
    reset_macro_cache()
    fixture = load_macro_facts(Settings(events_mode="fixture"))
    assert fixture
    assert any(row.get("data_class") == "frozen_provider_audit" for row in fixture)
    live = load_macro_facts(Settings(events_mode="empty"))
    assert live
    assert all(row.get("data_class") == "live_current" for row in live)
    assert all(row.get("data_class") != "frozen_provider_audit" for row in live)
    assert any(abs(float(row.get("actual")) - 301.2) < 0.001 for row in live)
    live_chains = build_market_macro_chains(facts=live)
    assert all(row.get("data_class") != "frozen_provider_audit" for row in live_chains)


def test_ok_chain_requires_clickable_source_url():
    for url in ("", "not-a-url", "http://localhost/cpi", "https://example.com/cpi", "https://127.0.0.1/cpi"):
        chain = build_numeric_macro_chain(_fact(http_source=url, source_url=url))
        assert chain["status"] == "degraded"
        assert chain["degrade_reason"] == "missing_source_url"
        assert chain["live"] is False
        assert chain["coverage_label"] == "degraded"
    healthy = build_numeric_macro_chain(_fact())
    assert healthy["status"] == "ok"
    assert _layer(healthy, "fact")["evidence_refs"][0]["source_url"].startswith("https://fred.stlouisfed.org")


def test_same_basis_rejects_ambiguous_prior_and_series():
    same_period = _fact(consensus=None, prior_as_of="2026-08-01")
    assert compare_same_basis(same_period)["reason"] == "period_or_basis_mismatch"
    missing_prior_stamp = _fact(consensus=None)
    missing_prior_stamp["prior_as_of"] = None
    assert compare_same_basis(missing_prior_stamp)["reason"] == "period_or_basis_mismatch"
    mixed_basis = _nfp()
    mixed_basis["consensus_basis"] = "level"
    assert compare_same_basis(mixed_basis)["reason"] == "period_or_basis_mismatch"
    wrong_series = _fact(consensus_series="UNRATE")
    assert compare_same_basis(wrong_series)["reason"] == "period_or_basis_mismatch"
    assert compare_same_basis(_fact())["status"] == "ok"
    assert compare_same_basis(_nfp())["status"] == "ok"


def test_live_current_count_excludes_degraded():
    healthy = build_numeric_macro_chain(_fact(data_class="live_current"))
    broken = build_numeric_macro_chain(_fact(data_class="live_current", http_source="", source_url=""))
    assert healthy["live"] is True
    assert healthy["coverage_label"] == "live-current"
    assert broken["live"] is False
    assert broken["coverage_label"] == "degraded"
    summary = summarize_macro_chains([healthy, broken])
    assert summary["live_current_count"] == 1
    assert summary["degraded_count"] == 1
    assert all(row["coverage_label"] == "live-current" for row in summary["headlines"])


def test_cpi_index_up_rate_down_does_not_delay_cuts():
    chain = build_numeric_macro_chain(
        {
            "metric": "cpi",
            "name": "CPI-U",
            "actual": 333.2,
            "prior": 332.0,
            "prior_prior": 330.0,
            "unit": "index",
            "series": "CPIAUCSL",
            "period": "2026-08-01",
            "prior_as_of": "2026-07-01",
            "prior_prior_as_of": "2026-06-01",
            "as_of": "2026-08-01T00:00:00+00:00",
            "source": "FRED",
            "http_source": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
            "status": "ok",
            "basis": "index_level",
            "data_class": "frozen_provider_audit",
        }
    )
    exp = _layer(chain, "expectation")["text"]
    change = _layer(chain, "change")["text"]
    assert chain["status"] == "ok"
    assert "后移" not in exp
    assert "通胀环比上升" not in exp
    assert "减速" in exp
    assert "未加速" in change
    assert "价格指数上升" in change
    assert "CPIAUCSL[t] / CPIAUCSL[t−1]" in (_layer(chain, "fact")["text"] + change)
    assert _layer(chain, "expectation")["stance"] == "cut_odds_earlier"


def test_cpi_two_index_levels_withhold_acceleration():
    chain = build_numeric_macro_chain(
        {
            "metric": "cpi",
            "name": "CPI-U",
            "actual": 334.131,
            "prior": 332.81,
            "unit": "index",
            "series": "CPIAUCSL",
            "period": "2026-08-01",
            "prior_as_of": "2026-07-01",
            "as_of": "2026-08-01T00:00:00+00:00",
            "source": "FRED",
            "http_source": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
            "status": "ok",
            "basis": "index_level",
            "data_class": "live_current",
        }
    )
    exp = _layer(chain, "expectation")["text"]
    assert "通胀环比上升" not in exp
    assert "不能把指数上升写成通胀加速" in exp
    assert _layer(chain, "expectation")["stance"] == "withheld"
    assert "MoM" in _layer(chain, "fact")["text"] or "MoM" in _layer(chain, "change")["text"]
    assert "CPIAUCSL[t] / CPIAUCSL[t−1]" in (_layer(chain, "fact")["text"] + _layer(chain, "change")["text"])
    assert "高估值成长" not in _layer(chain, "impact")["text"]


def test_cpi_index_consensus_is_rejected():
    chain = build_numeric_macro_chain(_fact(actual=334.131, prior=332.81, consensus=333.0, unit="index", basis="index_level", rate_kind=None))
    assert chain["status"] == "degraded"
    assert chain["degrade_reason"] == "period_or_basis_mismatch"
    assert "333" in (chain.get("degrade_detail") or "") or "价格指数" in (chain.get("degrade_detail") or "")


def test_cpi_ambiguous_consensus_falls_back_to_prior_rate():
    chain = build_numeric_macro_chain(
        _fact(
            consensus=0.30,
            consensus_basis=None,
            consensus_unit=None,
            consensus_series=None,
            consensus_as_of=None,
            consensus_period=None,
            consensus_rate_kind=None,
        )
    )
    exp = _layer(chain, "expectation")["text"]
    change = _layer(chain, "change")
    assert chain["status"] == "ok"
    assert "高于一致预期" not in exp
    assert "低于一致预期" not in exp
    assert change.get("baseline_kind") == "prior"
    assert change.get("baseline") == 0.22


def test_cpi_mom_vs_yoy_consensus_mismatches():
    chain = build_numeric_macro_chain(
        _fact(
            consensus=3.2,
            consensus_basis="yoy_pct",
            consensus_rate_kind="yoy_pct",
            consensus_unit="percent",
            consensus_series="CPIAUCSL",
            consensus_as_of="2026-08-01",
        )
    )
    assert chain["status"] == "degraded"
    assert chain["degrade_reason"] == "period_or_basis_mismatch"
    assert "yoy_pct" in (chain.get("degrade_detail") or "")
    assert "高于一致预期" not in (_layer(chain, "expectation")["text"] or "")


def test_cpi_fully_specified_mom_consensus_forms_expectation():
    chain = build_numeric_macro_chain(_fact())
    change = _layer(chain, "change")
    exp = _layer(chain, "expectation")["text"]
    assert chain["status"] == "ok"
    assert change.get("baseline_kind") == "consensus"
    assert change.get("baseline") == 0.30
    assert "高于一致预期" in exp
    assert "CPIAUCSL[t] / CPIAUCSL[t−1]" in (_layer(chain, "fact")["text"] + change["text"])


def test_same_day_events_keep_distinct_ids_and_updates_reuse_id():
    first = _event(
        "war_sanctions",
        "Treasury OFAC designates additional energy sanctions",
        entities=["Iran", "oil", "energy"],
        event_id="evt-war-a",
        dedupe_group="grp-war-a",
    )
    second = _event(
        "war_sanctions",
        "Treasury OFAC designates a separate energy sanctions package",
        entities=["Iran", "oil", "energy"],
        event_id="evt-war-b",
        dedupe_group="grp-war-b",
    )
    id_a = event_chain_id(first)
    id_b = event_chain_id(second)
    assert id_a != id_b
    assert first.analysis["macro_chain"]["chain_id"] == id_a
    assert second.analysis["macro_chain"]["chain_id"] == id_b
    merged = build_market_macro_chains(events=[first, second], facts=[])
    war_ids = {row["chain_id"] for row in merged if row.get("event_type") == "war_sanctions"}
    assert war_ids == {id_a, id_b}
    first.canonical_title = "Treasury OFAC updates the first energy sanctions package"
    first.analysis["change_vs_baseline"] = {"text": "官方后续文档刷新同一制裁事件", "evidence_refs": []}
    updated = build_event_macro_chain(first, first.analysis)
    assert updated["chain_id"] == id_a
    assert "刷新同一制裁事件" in _layer(updated, "change")["text"]


def test_production_chain_inject_is_gated(monkeypatch):
    monkeypatch.delenv("ENABLE_DECISION_INJECT", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    chains = build_market_macro_chains(facts=[_fact(), _nfp()], events=[], inject="vix_only")
    ok = {row["metric"] for row in chains if row.get("status") == "ok"}
    assert "cpi" in ok
    assert "nfp" in ok
    bypassed = apply_macro_chain_inject(chains, "vix_only")
    assert {row["metric"] for row in bypassed if row.get("status") == "ok"} >= {"cpi", "nfp"}
