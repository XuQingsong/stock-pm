"""Phase 6A: market-level macro causal chain and selective transmission."""

from __future__ import annotations

from stock_pm.config import Settings
from stock_pm.events.analyze import analyze_event
from stock_pm.events.macro_chain import (
    LAYER_KINDS,
    apply_macro_inject,
    build_market_macro_chains,
    build_numeric_macro_chain,
    compare_same_basis,
    load_frozen_6a_facts,
    load_macro_facts,
    reset_macro_cache,
    stable_chain_id,
    stock_macro_chains,
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
        "actual": 334.131,
        "prior": 332.81,
        "consensus": 333.0,
        "unit": "index",
        "series": "CPIAUCSL",
        "period": "2026-08-01",
        "prior_as_of": "2026-07-01",
        "consensus_as_of": "2026-08-01",
        "as_of": "2026-08-01T00:00:00+00:00",
        "source": "FRED",
        "http_source": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
        "status": "ok",
        "data_class": "frozen_provider_audit",
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
        http_source="https://fred.stlouisfed.org/graph/fredgraph.csv?id=PAYEMS",
        **extra,
    )


def _layer(chain: dict, name: str) -> dict:
    return next(row for row in chain["layers"] if row["id"] == name)


def _event(event_type: str, title: str, *, entities: list[str] | None = None) -> TrustedEvent:
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
        event_id=f"evt-{event_type}",
        canonical_title=title,
        event_type=event_type,
        entities=list(entities or ["Treasury", "debt", "credit"]),
        countries=["US"],
        event_time="2026-09-01T15:00:00+00:00",
        published_at="2026-09-01T15:00:00+00:00",
        first_seen_at="2026-09-01T15:00:00+00:00",
        updated_at="2026-09-01T15:00:00+00:00",
        sources=[source],
        claims=[claim],
        dedupe_group=f"evt-{event_type}",
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
