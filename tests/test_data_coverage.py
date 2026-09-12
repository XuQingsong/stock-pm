"""Phase 4A: recorded fixtures form a complete input; one failure isolates."""

from __future__ import annotations

from stock_pm.config import Settings
from stock_pm.decision.assemble import assemble_from_bundle
from stock_pm.decision.health import build_data_health
from stock_pm.series import decorate_macro_row


def _valid_bar(as_of: str, close: float) -> dict:
    return {
        "symbol": "NVDA",
        "open_price": close - 1,
        "high_price": close + 2,
        "low_price": close - 2,
        "close_price": close,
        "volume": 10,
        "bar_time": as_of,
        "source": "alpaca_sip",
        "observed_at": as_of,
        "adjustment": "split",
    }


def _macro(metric: str, actual: float, observed: str, event_time: str, *, series: str | None = None, unit: str = "index", frequency: str = "daily") -> dict:
    series_id = series or metric
    return decorate_macro_row(
        {
            "event_type": metric,
            "event_time": event_time,
            "actual": actual,
            "prior": actual - 0.1,
            "source": "FRED",
            "name": "广义美元代理" if metric == "usd_broad" else metric.upper(),
            "unit": unit,
            "notes": (
                '{"series":"%s","symbol":"%s","observed_at":"%s","fetched_at":"%s",'
                '"as_of":"%s","unit":"%s","frequency":"%s","status":"ok"}'
                % (series_id, series_id, observed, observed, event_time[:10], unit, frequency)
            ),
        }
    )


def _bundle(*, include_vix: bool = True) -> dict:
    macros = [
        _macro("nfp", 220, "2026-09-05T14:00:00+00:00", "2026-09-05T12:30:00+00:00", series="PAYEMS", unit="thousands"),
        _macro("cpi", 323.1, "2026-09-11T12:00:00+00:00", "2026-08-01T00:00:00+00:00", series="CPIAUCSL", frequency="monthly"),
        _macro("us2y", 3.71, "2026-09-11T12:00:00+00:00", "2026-09-10T00:00:00+00:00", series="DGS2", unit="percent"),
        _macro("gold", 2300, "2026-09-11T12:00:00+00:00", "2026-09-10T00:00:00+00:00", series="GOLDPMGBD228NLBM", unit="USD/oz"),
        _macro("wti", 78.2, "2026-09-11T12:00:00+00:00", "2026-09-10T00:00:00+00:00", series="DCOILWTICO", unit="USD/bbl"),
        _macro("usd_broad", 121.4, "2026-09-11T12:00:00+00:00", "2026-09-10T00:00:00+00:00", series="DTWEXBGS"),
    ]
    if include_vix:
        macros.append(_macro("vix", 16.2, "2026-09-11T12:00:00+00:00", "2026-09-10T00:00:00+00:00", series="VIXCLS"))
    return {
        "symbol": "NVDA",
        "bars": [
            _valid_bar("2026-09-10T20:00:00+00:00", 117.2),
            _valid_bar("2026-09-09T20:00:00+00:00", 116.3),
        ],
        "earnings": [
            {
                "symbol": "NVDA",
                "eps_actual": 0.81,
                "eps_estimate": 0.74,
                "fiscal_period": "FY2026Q2",
                "report_date": "2026-08-28",
                "source": "fmp",
                "synced_at": "2026-09-10T20:05:00+00:00",
                "observed_at": "2026-09-10T20:05:00+00:00",
            }
        ],
        "macro_events": macros,
        "synthetic": False,
        "_skip_previous": True,
    }


def _settings() -> Settings:
    return Settings(
        alpaca_api_key_id="set",
        alpaca_api_secret_key="set",
        fred_api_key="set",
        fmp_api_key="set",
    )


def _ds(health, name):
    return next(row for row in health["datasets"] if row["dataset"] == name)


def test_recorded_nvda_bundle_forms_complete_inputs():
    bundle = _bundle()
    view = assemble_from_bundle(bundle)
    health = build_data_health(bundle, settings=_settings())
    assert view["symbol"] == "NVDA"
    assert view["synthetic"] is False
    assert [step["id"] for step in view["chain"]] == [
        "what_changed", "expectation", "tension", "causal_impact", "thesis_impact"
    ]
    assert _ds(health, "daily_price_bars")["status"] == "ok"
    assert _ds(health, "macro_cpi")["status"] == "ok"
    assert _ds(health, "macro_rates_confirm")["status"] == "ok"
    assert _ds(health, "macro_vix")["status"] == "ok"
    assert _ds(health, "macro_gold")["status"] == "ok"
    assert _ds(health, "macro_usd_broad")["status"] == "ok"
    assert _ds(health, "macro_usd_broad")["title_zh"] == "广义美元代理"
    assert _ds(health, "macro_usd_broad")["series"] == "DTWEXBGS"
    assert health["overall"]["kind"] == "operational_health"


def test_dxy_never_healthy_when_usd_broad_ok():
    health = build_data_health(_bundle(), settings=_settings())
    dxy = _ds(health, "macro_dxy")
    proxy = _ds(health, "macro_usd_broad")
    assert dxy["status"] == "not_configured"
    assert dxy["reason_code"] == "source_not_configured"
    assert dxy["title_zh"] == "ICE 美元指数"
    assert dxy["series"] is None
    assert proxy["status"] == "ok"
    assert proxy["metric"] == "usd_broad"
    assert proxy["title_zh"] == "广义美元代理"
    assert "DXY" not in proxy["title"]
    assert "DXY" not in proxy["title_zh"]


def test_vix_failure_does_not_drop_other_facts_or_mint_direction():
    healthy = build_data_health(_bundle(include_vix=True), settings=_settings())
    failed = build_data_health(_bundle(include_vix=False), settings=_settings())
    view = assemble_from_bundle(_bundle(include_vix=False))
    assert _ds(failed, "macro_vix")["status"] == "missing"
    assert _ds(failed, "macro_vix")["reason_code"] == "upstream_empty"
    for dataset in ("daily_price_bars", "macro_cpi", "macro_rates_confirm", "macro_nfp", "macro_wti"):
        assert _ds(failed, dataset)["status"] == _ds(healthy, dataset)["status"], dataset
    assert view["can_form_direction"] is False or view["overall"]["level"] != "L3"
    assert failed["judgment"]["level"] is None or failed["judgment"]["level"] == view["overall"]["level"]


def test_optional_gold_gap_does_not_unavail_macro_chain():
    bundle = _bundle()
    bundle["macro_events"] = [row for row in bundle["macro_events"] if row["event_type"] != "gold"]
    health = build_data_health(bundle, settings=_settings())
    assert _ds(health, "macro_gold")["status"] == "missing"
    assert next(row for row in health["chains"] if row["id"] == "macro_rates")["health"] != "unavailable"
