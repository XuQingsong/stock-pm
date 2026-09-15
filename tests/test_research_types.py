from pathlib import Path

from stock_pm.research.classify import classify_template
from stock_pm.research.issuer import cik_for, fiscal_year_end_month_for, merge_identity, ticker_for_cik
from stock_pm.research.types import empty_valuation_case, follow_up_from_payload, normalize_valuation_case, LINK_DIRECTIONS, LINK_STRENGTHS


def test_classify_uses_sector_and_themes_not_ticker() -> None:
    assert classify_template(themes=["semis"]) == "semiconductor"
    assert classify_template(sector="能源", themes=["oil_producer"]) == "energy"
    assert classify_template(asset_class="etf", themes=["semis"]) == "generic_company"
    assert classify_template(sector="银行") == "generic_company"


def test_issuer_directory_is_data_lookup() -> None:
    assert cik_for("aapl") == "0000320193"
    assert fiscal_year_end_month_for("AVGO") == 10
    assert ticker_for_cik("0001045810") == "NVDA"
    unknown = merge_identity("ZZZY", legal_name="Unknown Co", source="test")
    assert unknown["ticker"] == "ZZZY"
    assert unknown["cik"] is None
    assert "cik" in unknown["missing_fields"]
    listed = merge_identity("COHR")
    assert listed["cik"] == "0000856298"
    assert Path("src/stock_pm/research/data/issuer_directory.json").is_file()


def test_valuation_case_keeps_nulls() -> None:
    blank = empty_valuation_case()
    assert blank["target_value"] is None
    filled = normalize_valuation_case({"target_value": 200, "notes": "base"})
    assert filled["target_value"] == 200
    assert filled["revenue"] is None


def test_link_polarity_includes_contextual() -> None:
    assert LINK_DIRECTIONS == ("support", "oppose", "contextual")
    assert LINK_STRENGTHS == ("strong", "moderate", "weak")


def test_follow_up_spec_from_dict() -> None:
    spec = follow_up_from_payload({"title": "verify demand", "assigned_agents": ["risk"]})
    assert spec.task_type == "verify_assumption"
    assert spec.assigned_agents == ("risk",)
