from __future__ import annotations

from stock_pm.brain.header import company_header
from stock_pm.brain.integrity import assess_financial_integrity
from stock_pm.brain.llm_steps import normalize_claim
from stock_pm.brain.news import search_recent_news
from stock_pm.brain.quality import assess_brain_quality
from stock_pm.research.extract import extract_guidance_mentions, is_operating_guidance
from stock_pm.research.issuer import fiscal_label_from_period_end
from stock_pm.research.live_fetch import _quarters_from_companyfacts, dedupe_earnings_prints, merge_facts_into_earnings


def _point(end: str, start: str, val: float, fy: int, fp: str, filed: str) -> dict:
    return {"end": end, "start": start, "val": val, "form": "10-Q", "fp": fp, "fy": fy, "filed": filed}


def _aapl_facts() -> dict:
    # Current Q3 FY2026 + YTD + prior-year comparative tagged with the current filing fy.
    current = _point("2026-06-27", "2026-03-29", 109_417_000_000, 2026, "Q3", "2026-07-31")
    ytd = _point("2026-06-27", "2025-09-28", 316_000_000_000, 2026, "Q3", "2026-07-31")
    comparative = _point("2025-06-28", "2025-03-30", 94_036_000_000, 2026, "Q3", "2026-07-31")
    original_prior = _point("2025-06-28", "2025-03-30", 94_036_000_000, 2025, "Q3", "2025-08-01")
    q2 = _point("2026-03-28", "2025-12-28", 111_184_000_000, 2026, "Q2", "2026-05-01")
    q1 = _point("2025-12-27", "2025-09-28", 143_756_000_000, 2026, "Q1", "2026-01-30")
    q4 = _point("2025-09-27", "2025-06-29", 102_466_000_000, 2025, "Q4", "2025-10-31")
    units = [current, ytd, comparative, original_prior, q2, q1, q4]
    eps = [
        {**current, "val": 2.02},
        {**comparative, "val": 1.57},
        {**q2, "val": 2.01},
        {**q1, "val": 2.84},
        {**q4, "val": 1.85},
    ]
    gross = [
        {**current, "val": 54_800_000_000},
        {**comparative, "val": 43_718_000_000},
    ]
    return {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": units}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
                "GrossProfit": {"units": {"USD": gross}},
            }
        }
    }


def test_fiscal_label_apple_q3() -> None:
    fy, fp = fiscal_label_from_period_end("2026-06-27", 9)
    assert fy == 2026
    assert fp == "Q3"
    fy, fp = fiscal_label_from_period_end("2025-12-27", 9)
    assert fy == 2026
    assert fp == "Q1"


def test_companyfacts_does_not_use_comparative_column() -> None:
    quarters = _quarters_from_companyfacts(_aapl_facts(), fiscal_year_end_month=9)
    latest = quarters[0]
    assert latest["period_end"] == "2026-06-27"
    assert latest["revenue_actual"] == 109_417_000_000
    assert latest["eps_actual"] == 2.02
    assert latest["fiscal_year"] == 2026
    assert latest["fiscal_period"] == "Q3"
    assert abs(float(latest["provider_fields"]["gross_margin_pct"]) - 50.08) < 0.2
    prior = next(row for row in quarters if row["period_end"] == "2025-06-28")
    assert prior["revenue_actual"] == 94_036_000_000
    assert prior["fiscal_year"] == 2025


def test_merge_prefers_period_end_not_filed_date() -> None:
    facts = _quarters_from_companyfacts(_aapl_facts(), fiscal_year_end_month=9)
    nasdaq = [
        {
            "symbol": "AAPL",
            "report_date": "2026-07-30",
            "fiscal_period": "Jun 2026",
            "fiscal_year": 2026,
            "period_end": "2026-06-27",
            "revenue_actual": 109_417_000_000,
            "eps_actual": 1.91,
            "source": "Nasdaq earnings surprise",
        }
    ]
    merged = merge_facts_into_earnings("AAPL", nasdaq, facts)
    assert merged[0]["period_end"] == "2026-06-27"
    assert merged[0]["revenue_actual"] == 109_417_000_000
    assert merged[0]["eps_actual"] == 2.02
    pack = {
        "ticker": "AAPL",
        "earnings_history": [
            {
                "period_end": row.get("period_end"),
                "report_date": row.get("report_date"),
                "fiscal_period": row.get("fiscal_period"),
                "fiscal_year": row.get("fiscal_year"),
                "revenue": row.get("revenue_actual"),
                "eps": row.get("eps_actual"),
                "gross_margin_pct": (row.get("provider_fields") or {}).get("gross_margin_pct"),
                "source": row.get("source"),
                "provider_fields": row.get("provider_fields") or {},
            }
            for row in merged
        ],
        "company_profile": {"revenue_ttm": 466_823_000_000, "eps_ttm": 8.72, "last_close": 332.41, "legal_name": "Apple Inc"},
        "guidance_history": [],
    }
    header = company_header(pack)
    assert header["latest_quarter"]["revenue"]["value"] == 109_417_000_000
    assert header["latest_quarter"]["eps"]["value"] == 2.02
    assert header["latest_quarter"]["revenue_yoy"]["value"] is not None
    assert header["latest_quarter"]["revenue_yoy"]["value"] > 10


def test_risk_factor_is_not_guidance() -> None:
    text = "The Company expects these trends to intensify, which may materially negatively impact the Company’s revenue, costs, gross margin, results of operations and financial condition"
    assert is_operating_guidance(text) is False
    assert extract_guidance_mentions(text) == []
    deferred = "the Company expects 64 % of total deferred revenue to be realized in less than a year"
    assert is_operating_guidance(deferred) is False
    real = "The Company expects net revenue in the range of $1.225 billion to $1.275 billion."
    assert is_operating_guidance(real) is True
    assert extract_guidance_mentions(real)
    historical = "Our revenue of $94 billion was up 10% year-over-year and is a new June quarter record. Company gross margin was 46.5% at the high end of our guidance range"
    assert is_operating_guidance(historical) is False


def test_undated_search_hits_are_not_last_30_day_news() -> None:
    hits = search_recent_news(
        "AAPL",
        pack={"major_events": [{"title": "10-Q", "url": "https://www.sec.gov/x", "source": "sec"}]},
        extra_queries=[],
        fetchers=type("F", (), {"web_search": staticmethod(lambda query, limit=5: [{"title": "10-Q", "url": "https://www.sec.gov/old", "snippet": ""}])})(),
        days=30,
    )
    assert hits == []


def test_inconsistent_financials_block_reason() -> None:
    pack = {
        "ticker": "AAPL",
        "earnings_history": [
            {
                "period_end": "2026-06-27",
                "revenue": 109_417_000_000,
                "eps": 2.02,
                "source": "sec.companyfacts",
                "provider_fields": {"companyfacts_revenue": 109_417_000_000, "nasdaq_revenue": 80_000_000_000, "companyfacts_eps": 2.02, "nasdaq_eps": 2.02},
            }
        ],
        "company_profile": {"revenue_ttm": 400_000_000_000},
    }
    header = company_header(pack)
    integrity = assess_financial_integrity(pack, header)
    assert integrity["inconsistent"] is True
    assert integrity["block_core_claims"] is True
    quality = assess_brain_quality(header=header, evidence=[], news=[], claims=[], llm_calls=[], pack=pack, integrity=integrity)
    assert quality["axes"]["data_coverage"] == "Poor"
    assert any("financial_input_inconsistent" in str(item.get("reason")) for item in quality["warnings"])


def test_q4_derived_from_10k_annual_not_prior_q3() -> None:
    q1 = _point("2024-12-28", "2024-09-29", 124_300_000_000, 2025, "Q1", "2025-01-31")
    q2 = _point("2025-03-29", "2024-12-29", 95_359_000_000, 2025, "Q2", "2025-05-02")
    q3 = _point("2025-06-28", "2025-03-30", 94_036_000_000, 2025, "Q3", "2025-08-01")
    fy = {
        "end": "2025-09-27",
        "start": "2024-09-29",
        "val": 416_161_000_000,
        "form": "10-K",
        "fp": "FY",
        "fy": 2025,
        "filed": "2025-10-31",
    }
    current = _point("2026-06-27", "2026-03-29", 109_417_000_000, 2026, "Q3", "2026-07-31")
    q2_26 = _point("2026-03-28", "2025-12-28", 111_184_000_000, 2026, "Q2", "2026-05-01")
    q1_26 = _point("2025-12-27", "2025-09-28", 143_756_000_000, 2026, "Q1", "2026-01-30")
    payload = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [current, q2_26, q1_26, q1, q2, q3, fy]}
                }
            }
        }
    }
    quarters = _quarters_from_companyfacts(payload, fiscal_year_end_month=9)
    q4 = next(row for row in quarters if row["period_end"] == "2025-09-27")
    assert q4["revenue_actual"] == 102_466_000_000
    assert q4["fiscal_period"] == "Q4"
    assert q4["fiscal_year"] == 2025
    assert q4["provider_fields"].get("q4_derived_from_10k") is True
    latest_four = sorted(quarters, key=lambda row: row["period_end"], reverse=True)[:4]
    ttm = sum(row["revenue_actual"] for row in latest_four)
    assert ttm == 109_417_000_000 + 111_184_000_000 + 143_756_000_000 + 102_466_000_000
    assert all(row["period_end"] != "2025-06-28" for row in latest_four)


def test_duplicate_nasdaq_month_label_is_not_latest() -> None:
    pack = {
        "ticker": "AVGO",
        "earnings_history": [
            {
                "report_date": "2026-09-02",
                "fiscal_period": "Jul 2026",
                "fiscal_year": 2026,
                "period_end": None,
                "revenue": 29_591_000_000,
                "eps": 3.03,
                "source": "Nasdaq earnings surprise+sec.companyfacts",
            },
            {
                "report_date": "2026-09-02",
                "fiscal_period": "Q3",
                "fiscal_year": 2026,
                "period_end": "2026-08-02",
                "revenue": 29_591_000_000,
                "eps": 2.68,
                "gross_margin_pct": 69.13,
                "operating_margin_pct": 53.92,
                "source": "Nasdaq earnings surprise+sec.companyfacts",
                "provider_fields": {
                    "companyfacts_revenue": 29_591_000_000,
                    "companyfacts_eps": 2.68,
                    "nasdaq_eps": 3.03,
                },
            },
        ],
        "company_profile": {"revenue_ttm": 89_104_000_000, "eps_ttm": 7.84, "last_close": 339.51},
    }
    header = company_header(pack)
    assert header["latest_quarter"]["period_end"] == "2026-08-02"
    assert header["latest_quarter"]["eps"]["value"] == 2.68
    integrity = assess_financial_integrity(pack, header)
    assert integrity["fields"]["latest_quarter_eps"]["value"] == 2.68
    assert integrity["block_core_claims"] is False


def test_same_period_nasdaq_month_label_does_not_keep_nongaap_eps() -> None:
    pack = {
        "ticker": "AAPL",
        "earnings_history": [
            {
                "report_date": "2026-07-30",
                "fiscal_period": "Jun 2026",
                "fiscal_year": 2026,
                "period_end": "2026-06-27",
                "revenue": 109_417_000_000,
                "eps": 1.91,
                "source": "Nasdaq earnings surprise",
            },
            {
                "report_date": "2026-07-31",
                "fiscal_period": "Q3",
                "fiscal_year": 2026,
                "period_end": "2026-06-27",
                "revenue": 109_417_000_000,
                "eps": 2.02,
                "gross_margin_pct": 50.08,
                "source": "sec.companyfacts",
                "provider_fields": {"companyfacts_revenue": 109_417_000_000, "companyfacts_eps": 2.02},
            },
        ],
        "company_profile": {"revenue_ttm": 466_823_000_000, "eps_ttm": 8.72, "last_close": 332.41},
    }
    rows = dedupe_earnings_prints(pack["earnings_history"])
    assert rows[0]["fiscal_period"] == "Q3"
    assert rows[0]["eps"] == 2.02
    header = company_header(pack)
    assert header["latest_quarter"]["fiscal_period"] == "Q3"
    assert header["latest_quarter"]["eps"]["value"] == 2.02


def test_eps_gaap_vs_nongaap_does_not_block_claims() -> None:
    pack = {
        "ticker": "AVGO",
        "earnings_history": [
            {
                "period_end": "2026-08-02",
                "revenue": 29_591_000_000,
                "eps": 2.75,
                "source": "nasdaq+sec.companyfacts",
                "provider_fields": {
                    "companyfacts_revenue": 29_591_000_000,
                    "nasdaq_revenue": 29_591_000_000,
                    "companyfacts_eps": 2.75,
                    "nasdaq_eps": 3.03,
                },
            }
        ],
        "company_profile": {"revenue_ttm": 63_000_000_000, "eps_ttm": 8.0, "last_close": 344.82},
    }
    header = company_header(pack)
    integrity = assess_financial_integrity(pack, header)
    assert integrity["inconsistent"] is False
    assert integrity["block_core_claims"] is False
    assert integrity["fields"]["latest_quarter_eps"]["status"] == "warning"
    assert integrity["fields"]["latest_quarter_eps"]["value"] == 2.75


def test_core_claim_rejects_financial_restatement() -> None:
    allowed = {"rev_1"}
    assert (
        normalize_claim(
            {
                "title": "Revenue",
                "statement": "Revenue is growing strongly",
                "why_it_matters": "because growth",
                "supporting_evidence_ids": ["rev_1"],
            },
            allowed_ids=allowed,
            core=True,
        )
        is None
    )
    kept = normalize_claim(
        {
            "title": "iPhone cycle",
            "statement": "iPhone product cycle is strengthening, but duration still needs unit/mix confirmation.",
            "why_it_matters": "It binds the 1-3y EPS path versus the current multiple.",
            "supporting_evidence_ids": ["rev_1"],
            "value_impact": "high",
            "uncertainty": "high",
            "valuation_relevance": "high",
        },
        allowed_ids=allowed,
        core=True,
    )
    assert kept is not None
    assert kept["why_it_matters"]
