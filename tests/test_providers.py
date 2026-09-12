from stock_pm.config import Settings
from stock_pm.providers import (
    FMPProvider,
    _merge_fmp_earnings,
    collect_live_earnings,
    earnings_http_source,
    get_fundamentals_provider,
)


def test_merge_skips_unreported_rows_and_joins_net_income() -> None:
    reported = [
        {"date": "2027-01-28", "epsActual": None, "revenueActual": None, "epsEstimated": 2.1},
        {
            "date": "2026-08-01",
            "epsActual": 1.5,
            "epsEstimated": 1.4,
            "revenueActual": 100,
            "revenueEstimated": 90,
        },
    ]
    income = [
        {
            "date": "2026-06-28",
            "fiscalYear": 2026,
            "period": "Q3",
            "netIncome": 42_000_000,
            "reportedCurrency": "USD",
        }
    ]
    rows = _merge_fmp_earnings("AAPL", reported, income)
    assert len(rows) == 1
    assert rows[0]["eps_actual"] == 1.5
    assert rows[0]["revenue_actual"] == 100
    assert rows[0]["net_income_actual"] == 42_000_000
    assert rows[0]["net_income_estimate"] is None
    assert rows[0]["fiscal_year"] == 2026
    assert rows[0]["provider_fields"]["net_income_estimate"] is None


def test_provider_selection(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_pm.providers.Settings",
        lambda: type("Settings", (), {"fmp_api_key": ""})(),
    )
    assert get_fundamentals_provider().name == "nasdaq"
    monkeypatch.setattr(
        "stock_pm.providers.Settings",
        lambda: type("Settings", (), {"fmp_api_key": "test-key"})(),
    )
    assert get_fundamentals_provider().name == "fmp"


def test_fmp_fetch_maps_profile_and_earnings(monkeypatch) -> None:
    payloads = {
        "profile": [{"currency": "USD", "marketCap": 3e12, "beta": 1.2}],
        "ratios-ttm": [
            {
                "priceToEarningsRatioTTM": 28.5,
                "priceToBookRatioTTM": 45,
                "priceToSalesRatioTTM": 8.1,
                "priceToEarningsGrowthRatioTTM": 2.2,
                "grossProfitMarginTTM": 0.46,
                "operatingProfitMarginTTM": 0.31,
                "netProfitMarginTTM": 0.25,
                "dividendYieldTTM": 0.005,
            }
        ],
        "key-metrics-ttm": [
            {"enterpriseValueTTM": 3.1e12, "evToEBITDATTM": 22, "netIncomePerShareTTM": 7.1}
        ],
        "income-statement": [
            {"date": "2026-06-28", "fiscalYear": "2026", "period": "Q3", "netIncome": 50}
        ],
        "earnings": [
            {
                "date": "2026-08-01",
                "epsActual": 1.4,
                "epsEstimated": 1.3,
                "revenueActual": 90,
                "revenueEstimated": 88,
            }
        ],
    }

    def fake_get(self, path, params):
        assert "limit" not in params
        return payloads[path]

    monkeypatch.setattr(FMPProvider, "_get", fake_get)
    monkeypatch.setattr("stock_pm.fundamentals._news", lambda symbol: [{"headline": "x"}])
    result = FMPProvider("unused").fetch("AAPL", 200.0, "2026-09-07T00:00:00+00:00", "stocks")
    assert result["fundamental"]["pe_ttm"] == 28.5
    assert result["fundamental"]["revenue_ttm"] is None
    assert result["fundamental"]["analyst_target_price"] is None
    assert result["earnings"][0]["net_income_actual"] == 50
    assert result["news"][0]["headline"] == "x"


def test_live_earnings_unconfigured() -> None:
    rows, errors, report = collect_live_earnings("NVDA", Settings(fmp_api_key=""))
    rec = report["earnings_reports"]
    assert rows == []
    assert errors == set()
    assert rec["status"] == "not_configured"
    assert rec["required_env"] == "FMP_API_KEY"
    assert rec["http_source"] == earnings_http_source("NVDA")
    assert "apikey=" not in rec["http_source"].lower()


def test_live_earnings_ok(monkeypatch) -> None:
    def fake_try(self, path, params):
        if path == "earnings":
            return [
                {
                    "date": "2026-08-26",
                    "epsActual": 2.22,
                    "epsEstimated": 2.09,
                    "revenueActual": 100,
                    "revenueEstimated": 90,
                }
            ]
        if path == "income-statement":
            return [{"date": "2026-07-27", "fiscalYear": 2027, "period": "Q2", "netIncome": 1}]
        return []

    monkeypatch.setattr(FMPProvider, "_try_get", fake_try)
    rows, errors, report = collect_live_earnings("nvda", Settings(fmp_api_key="set"))
    rec = report["earnings_reports"]
    assert errors == set()
    assert rows[0]["eps_actual"] == 2.22
    assert rows[0]["as_of"] == "2026-08-26"
    assert rec["status"] == "ok"
    assert rec["as_of"] == "2026-08-26"
    assert rec["value"] == 2.22
    assert rec["unit"] == "USD/share"
    assert rec["series_or_symbol"] == "NVDA"
    assert "apikey=" not in rec["http_source"].lower()
    assert rec["http_source"] == earnings_http_source("NVDA")
    assert rows[0].get("prior_consensus") is None


def test_live_earnings_query_error(monkeypatch) -> None:
    def boom(self, path, params):
        raise RuntimeError("FMP earnings failed with HTTP 401")

    monkeypatch.setattr(FMPProvider, "_try_get", boom)
    rows, errors, report = collect_live_earnings("NVDA", Settings(fmp_api_key="set"))
    assert rows == []
    assert "earnings_reports" in errors
    assert report["earnings_reports"]["status"] == "error"
