"""Phase 6B: multi-chain driver synthesis. Deterministic rules only."""

from __future__ import annotations

from datetime import date

from stock_pm.config import Settings
from stock_pm.events.macro_chain import apply_macro_inject, build_market_macro_chains, reset_macro_cache
from stock_pm.events.service import market_center, reset_cache, stock_events
from stock_pm.events.synthesis import fact_key, synthesize_drivers

from test_events_macro_chain import _event, _fact, _nfp


def setup_function() -> None:
    reset_cache()
    reset_macro_cache()


def _us2y(*, up: bool = True, **extra) -> dict:
    actual, prior = (4.69, 4.56) if up else (4.43, 4.56)
    row = _fact(
        metric="us2y",
        name="US 2Y Treasury",
        actual=actual,
        prior=prior,
        consensus=None,
        unit="percent",
        series="DGS2",
        period="2026-09-10",
        prior_as_of="2026-09-09",
        consensus_as_of=None,
        consensus_basis=None,
        consensus_unit=None,
        consensus_series=None,
        consensus_rate_kind=None,
        rate_kind=None,
        basis=None,
        index_level=None,
        index_prior=None,
        http_source="https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2",
        formula="DGS2[t] vs DGS2[t−1] (percent)",
        comparison="same_series_same_unit",
    )
    row.update(extra)
    return row


def _vix(**extra) -> dict:
    return _fact(
        metric="vix",
        name="VIX",
        actual=18.4,
        prior=16.46,
        consensus=None,
        unit="index",
        series="VIXCLS",
        period="2026-09-10",
        prior_as_of="2026-09-09",
        consensus_as_of=None,
        consensus_basis=None,
        consensus_unit=None,
        consensus_series=None,
        rate_kind=None,
        basis=None,
        index_level=None,
        index_prior=None,
        http_source="https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS",
        formula="VIXCLS[t] vs VIXCLS[t−1] (index)",
        **extra,
    )


def _wti(**extra) -> dict:
    return _fact(
        metric="wti",
        name="WTI",
        actual=78.4,
        prior=72.1,
        consensus=None,
        unit="usd_per_barrel",
        series="DCOILWTICO",
        period="2026-09-10",
        prior_as_of="2026-09-09",
        consensus_as_of=None,
        consensus_basis=None,
        consensus_unit=None,
        consensus_series=None,
        rate_kind=None,
        basis=None,
        index_level=None,
        index_prior=None,
        http_source="https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO",
        formula="DCOILWTICO[t] vs DCOILWTICO[t−1] (usd_per_barrel)",
        **extra,
    )


def _chains(facts, events=None):
    return build_market_macro_chains(facts=facts, events=events or [])


def test_s1_rates_confirmation_is_conditional():
    chains = _chains([_fact(), _nfp(), _us2y(up=True), _vix()])
    payload = synthesize_drivers(chains)
    market = payload["market"]
    assert market["synthesis_id"] == "synth:market:macro"
    assert market["scope"] == "market"
    assert market["can_form_direction"] is False
    assert market["percent_forecast"] is None
    assert market["price_target"] is None
    assert market["net_expectation"]["kind"] == "conditional_expectation"
    assert market["net_expectation"]["is_fact"] is False
    assert "利率" in market["net_expectation"]["text"] or "折现" in market["net_expectation"]["text"]
    assert "同向确认" in (market["confirmations"][0]["text"] if market["confirmations"] else "")
    assert not market["contradictions"]
    assert market["confidence"]["label"] == "medium"
    assert market["confidence"]["independent_fact_count"] == 3
    assert market["confidence"]["majority_vote"] is False
    assert market["vix"]["sets_direction"] is False
    assert all(row.get("evidence_refs") for row in market["drivers"])
    nvda = payload["stocks"]["NVDA"]
    assert nvda["scope"] == "stock"
    assert "久期" in (nvda.get("why_relevant") or "") or "利率" in (nvda.get("why_relevant") or "")


def test_s2_conflict_keeps_both_sides_and_lower_confidence():
    cpi_down = apply_macro_inject([_fact()], "reverse_cpi")[0]
    confirm = synthesize_drivers(_chains([_fact(), _nfp(), _us2y(up=True)]))
    conflict = synthesize_drivers(_chains([cpi_down, _us2y(up=True)]))
    market = conflict["market"]
    assert market["contradictions"]
    assert "冲突" in market["contradictions"][0]["text"]
    assert "冲突" in market["net_expectation"]["text"] or market["net_expectation"]["stance"] == "signal_conflict"
    sides = {item["polarity"] for item in market["contradictions"][0]["sides"]}
    assert sides == {"pressure", "relief"}
    assert "cpi" in {row["metric"] for row in market["drivers"]}
    assert "us2y" in {row["metric"] for row in market["drivers"]}
    assert market["confidence"]["rank"] < confirm["market"]["confidence"]["rank"]
    assert market["confidence"]["label"] == "limited"
    assert market["can_form_direction"] is False


def test_s3_vix_alone_does_not_form_direction():
    chains = _chains([_vix()])
    market = synthesize_drivers(chains)["market"]
    assert market["net_expectation"]["stance"] == "risk_confirmation_only"
    assert market["can_form_direction"] is False
    assert market["vix"]["sets_direction"] is False
    assert market["vix"]["copied_to_all_stocks"] is False
    assert not market["driver_themes"]
    assert "不形成方向" in market["net_expectation"]["text"]
    assert synthesize_drivers(chains)["stocks"] == {}


def test_s4_wti_maps_xom_not_aapl_nok():
    chains = _chains([_wti(), _vix()])
    payload = synthesize_drivers(chains)
    assert "XOM" in payload["stocks"]
    assert "AAPL" not in payload["stocks"]
    assert "NOK" not in payload["stocks"]
    xom = payload["stocks"]["XOM"]
    assert any(row["metric"] == "wti" for row in xom["drivers"])
    assert "生产" in xom["net_expectation"]["text"] or "收入" in (xom.get("why_relevant") or "") or "commodity" in (xom.get("why_relevant") or "")
    industries = {row["target"] for row in payload["industries"]}
    assert "energy" in industries
    assert not any(row["target"] == "semis" and any(d["metric"] == "wti" for d in row["drivers"]) for row in payload["industries"])


def test_s5_credit_only_with_jpm_exposure():
    event = _event("sovereign_or_corporate_debt", "Treasury increased coupon auction sizes citing funding and liquidity conditions")
    chains = _chains([], events=[event])
    payload = synthesize_drivers(chains)
    assert "JPM" in payload["stocks"]
    assert "AAPL" not in payload["stocks"]
    assert "XOM" not in payload["stocks"]
    assert payload["stocks"]["JPM"]["why_relevant"]


def test_s6_one_failed_source_does_not_kill_synthesis():
    facts = apply_macro_inject([_fact(), _nfp(), _us2y(up=True)], "source_fail_us2y")
    chains = _chains(facts)
    by_metric = {row["metric"]: row for row in chains}
    assert by_metric["us2y"]["status"] != "ok"
    assert by_metric["cpi"]["status"] == "ok"
    assert by_metric["nfp"]["status"] == "ok"
    market = synthesize_drivers(chains)["market"]
    assert market["net_expectation"]["stance"] != "withheld"
    assert "us2y" in {row["metric"] for row in market["missing"]}
    assert "cpi" in {row["metric"] for row in market["drivers"]}
    assert "nfp" in {row["metric"] for row in market["drivers"]}
    assert "us2y" not in {row["metric"] for row in market["drivers"]}


def test_s7_same_fact_does_not_double_count():
    base = synthesize_drivers(_chains([_fact(), _nfp(), _us2y(up=True)]))
    dup_facts = apply_macro_inject([_fact(), _nfp(), _us2y(up=True)], "duplicate_cpi")
    dup = synthesize_drivers(_chains(dup_facts))
    assert fact_key(next(row for row in _chains(dup_facts) if row["metric"] == "cpi")) == fact_key(
        next(row for row in _chains(dup_facts) if row["metric"] == "core_cpi")
    )
    assert dup["market"]["confidence"]["independent_fact_count"] == base["market"]["confidence"]["independent_fact_count"]
    assert dup["market"]["confidence"]["rank"] == base["market"]["confidence"]["rank"]
    assert dup["market"]["confidence"]["duplicate_facts_collapsed"] >= 1


def test_s8_reverse_update_replaces_same_synthesis_id():
    first = synthesize_drivers(_chains([_fact(), _us2y(up=True)]))
    reversed_cpi = apply_macro_inject([_fact()], "reverse_cpi")[0]
    second = synthesize_drivers(_chains([reversed_cpi, _us2y(up=True)]))
    assert first["market"]["synthesis_id"] == second["market"]["synthesis_id"]
    assert first["market"]["synthesis_id"] == "synth:market:macro"
    first_cpi = next(row for row in first["market"]["drivers"] if row["metric"] == "cpi")
    second_cpi = next(row for row in second["market"]["drivers"] if row["metric"] == "cpi")
    assert first_cpi["polarity"] != second_cpi["polarity"]
    assert second["market"]["contradictions"]
    assert first["market"]["net_expectation"]["text"] != second["market"]["net_expectation"]["text"] or first_cpi["polarity"] != second_cpi["polarity"]


def test_s9_never_emits_direction_or_targets():
    payload = synthesize_drivers(_chains([_fact(), _nfp(), _us2y(up=True), _wti(), _vix()]))
    blob = str(payload)
    assert payload["market"]["can_form_direction"] is False
    assert "目标价" not in blob
    assert "买入" not in blob
    assert "卖出" not in blob
    for row in payload["syntheses"]:
        assert row["can_form_direction"] is False
        assert row["percent_forecast"] is None
        assert row["price_target"] is None


def test_s10_lists_specific_missing_not_vague_gap():
    facts = apply_macro_inject([_fact(), _nfp(), _us2y(up=True), _wti()], "vix_only")
    facts.append(_vix())
    chains = _chains(facts)
    market = synthesize_drivers(chains)["market"]
    assert market["net_expectation"]["stance"] in {"risk_confirmation_only", "withheld"}
    missing_metrics = {row["metric"] for row in market["missing"]}
    assert {"cpi", "nfp", "us2y"} <= missing_metrics or {"cpi", "nfp"} <= missing_metrics
    text = market["net_expectation"]["text"] + market["what_changes"]["text"] + str(market["missing"])
    assert "数据不足" not in market["net_expectation"]["text"] or "缺少" in market["net_expectation"]["text"]
    assert "cpi" in text.lower() or "CPI" in text
    assert any(row.get("what_changes") for row in market["missing"])


def test_fixture_center_exposes_synthesis_without_copying_to_aapl():
    center = market_center(Settings(events_mode="fixture"))
    assert center["driver_synthesis"]["synthesis_id"] == "synth:market:macro"
    assert center["synthesis_summary"]["can_form_direction"] is False
    assert center["macro_driver_summary"]["count"] >= 1
    nvda = stock_events("NVDA", Settings(events_mode="fixture"))
    aapl = stock_events("AAPL", Settings(events_mode="fixture"))
    xom = stock_events("XOM", Settings(events_mode="fixture"))
    nok = stock_events("NOK", Settings(events_mode="fixture"))
    jpm = stock_events("JPM", Settings(events_mode="fixture"))
    assert nvda["driver_synthesis"]
    assert nvda["driver_synthesis"]["why_relevant"]
    assert xom["driver_synthesis"]
    assert any(row["metric"] == "wti" for row in xom["driver_synthesis"]["drivers"])
    assert jpm["driver_synthesis"]
    assert aapl["driver_synthesis"] is None
    assert nok["driver_synthesis"] is None
    assert aapl["macro_chains"] == [] or "wti" not in {row["metric"] for row in aapl["macro_chains"]}
    jpm_stocks = (jpm["driver_synthesis"] or {}).get("impact", {}).get("stocks") or []
    nvda_stocks = (nvda["driver_synthesis"] or {}).get("impact", {}).get("stocks") or []
    xom_stocks = (xom["driver_synthesis"] or {}).get("impact", {}).get("stocks") or []
    assert jpm_stocks == ["JPM"]
    assert "NVDA" not in jpm_stocks
    assert nvda_stocks == ["NVDA"]
    assert xom_stocks == ["XOM"]
    assert "NVDA" not in (center["driver_synthesis"].get("impact", {}).get("stocks") or []) or "JPM" in (
        center["driver_synthesis"].get("impact", {}).get("stocks") or []
    )


def test_jpm_impact_does_not_name_nvda():
    payload = synthesize_drivers(_chains([_fact(), _nfp(), _us2y(up=True), _wti()]))
    jpm = payload["stocks"]["JPM"]
    nvda = payload["stocks"]["NVDA"]
    xom = payload["stocks"]["XOM"]
    assert jpm["impact"]["stocks"] == ["JPM"]
    assert "NVDA" not in jpm["impact"]["stocks"]
    assert "NVDA" not in str(jpm["impact"])
    assert nvda["impact"]["stocks"] == ["NVDA"]
    assert "JPM" not in nvda["impact"]["stocks"]
    assert xom["impact"]["stocks"] == ["XOM"]
    assert "AAPL" not in payload["stocks"]
    assert "NOK" not in payload["stocks"]
    market_stocks = payload["market"]["impact"]["stocks"]
    assert "NVDA" in market_stocks
    assert "JPM" in market_stocks
    assert "XOM" in market_stocks
    assert "AAPL" not in market_stocks
    assert "NOK" not in market_stocks
    banks = next(row for row in payload["industries"] if row["target"] == "banks")
    energy = next(row for row in payload["industries"] if row["target"] == "energy")
    semis = next(row for row in payload["industries"] if row["target"] == "semis")
    assert banks["impact"]["stocks"] == ["JPM"]
    assert energy["impact"]["stocks"] == ["XOM"]
    assert semis["impact"]["stocks"] == ["NVDA"]
    assert jpm["impact"]["industries"] == ["banks"]
    assert "semis" not in jpm["impact"]["industries"]
    assert "energy" not in jpm["impact"]["industries"]


def test_stock_missing_is_scope_relevant():
    facts = apply_macro_inject([_fact(), _nfp(), _us2y(up=True), _wti()], "source_fail_us2y")
    payload = synthesize_drivers(_chains(facts))
    market_missing = {row["metric"] for row in payload["market"]["missing"]}
    assert "us2y" in market_missing
    nvda_missing = {row["metric"] for row in payload["stocks"]["NVDA"]["missing"]}
    jpm_missing = {row["metric"] for row in payload["stocks"]["JPM"]["missing"]}
    xom_missing = {row["metric"] for row in payload["stocks"]["XOM"]["missing"]}
    assert "us2y" in nvda_missing
    assert "wti" not in nvda_missing
    assert "us2y" in jpm_missing
    assert "wti" not in jpm_missing
    assert "us2y" not in xom_missing
    assert "cpi" not in xom_missing
    energy = next(row for row in payload["industries"] if row["target"] == "energy")
    assert "us2y" not in {row["metric"] for row in energy["missing"]}
    assert "cpi" not in {row["metric"] for row in energy["missing"]}
    wti_fail = apply_macro_inject([_wti()], "vix_only")[0]
    war = _event("war_sanctions", "Treasury OFAC designates additional energy sanctions", entities=["Iran", "oil", "energy"])
    payload2 = synthesize_drivers(_chains([_fact(), wti_fail], events=[war]))
    assert "wti" in {row["metric"] for row in payload2["stocks"]["XOM"]["missing"]}
    assert "wti" not in {row["metric"] for row in payload2["stocks"]["NVDA"]["missing"]}


def test_s7_same_fact_two_channel_kinds_does_not_confirm():
    shared = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SHAREDFACT"
    cpi = _fact(http_source=shared)
    nfp = _nfp()
    nfp["http_source"] = shared
    chains = _chains([cpi, nfp])
    payload = synthesize_drivers(chains)
    market = payload["market"]
    assert fact_key(next(row for row in chains if row["metric"] == "cpi")) == fact_key(
        next(row for row in chains if row["metric"] == "nfp")
    )
    rates = next(row for row in market["driver_themes"] if row["theme"] == "rates")
    assert rates["independent_fact_count"] == 1
    assert rates["confirmed"] is False
    assert market["confidence"]["independent_fact_count"] == 1
    assert market["confidence"]["confirmed"] is False
    assert market["confidence"]["label"] == "limited"
    assert market["confidence"]["duplicate_facts_collapsed"] >= 1


def test_fresh_vs_stale_confidence_differs():
    now = date(2026, 9, 10)
    fresh = synthesize_drivers(_chains([_fact(), _nfp(), _us2y(up=True)]), now=now)
    stale_cpi = _fact(period="2026-06-01", prior_as_of="2026-05-01", consensus_as_of="2026-06-01", as_of="2026-06-01T00:00:00+00:00")
    stale_nfp = _nfp(period="2026-06-01", prior_as_of="2026-05-01", consensus_as_of="2026-06-01", as_of="2026-06-01T00:00:00+00:00")
    stale_us2y = _us2y(up=True, period="2026-07-01", prior_as_of="2026-06-30", as_of="2026-07-01T00:00:00+00:00")
    stale = synthesize_drivers(_chains([stale_cpi, stale_nfp, stale_us2y]), now=now)
    assert fresh["market"]["confidence"]["fresh"] is True
    assert fresh["market"]["confidence"]["label"] == "medium"
    assert stale["market"]["confidence"]["fresh"] is False
    assert stale["market"]["confidence"]["label"] == "limited"
    assert stale["market"]["confidence"]["rank"] < fresh["market"]["confidence"]["rank"]
    assert "过期" in stale["market"]["confidence"]["why"] or "窗口" in stale["market"]["confidence"]["why"]
    assert stale["market"]["confidence"]["why"] != fresh["market"]["confidence"]["why"]
    assert "cpi" in stale["market"]["confidence"]["stale_metrics"]


def test_top_driver_rank_uses_freshness_not_theme_priority():
    now = date(2026, 9, 10)
    stale_us2y = _us2y(
        up=True,
        period="2026-07-01",
        prior_as_of="2026-06-30",
        as_of="2026-07-01T00:00:00+00:00",
    )
    payload = synthesize_drivers(_chains([stale_us2y, _wti()]), now=now)
    themes = [row["theme"] for row in payload["market"]["driver_themes"]]
    assert themes[0] == "energy"
    assert "rates" in themes
    assert payload["market"]["driver_themes"][0]["fresh"] is True
    stale_rates = next(row for row in payload["market"]["driver_themes"] if row["theme"] == "rates")
    assert stale_rates["fresh"] is False
