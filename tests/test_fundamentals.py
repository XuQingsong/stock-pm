from stock_pm.fundamentals import _fiscal_year, _last_trade, _number


def test_number_parses_financial_display_values() -> None:
    assert _number({"value": "$1,234.50"}) == 1234.5
    assert _number("18.6%") == 18.6
    assert _number("N/A") is None


def test_fiscal_year_extracts_year_when_present() -> None:
    assert _fiscal_year("May 2026") == 2026
    assert _fiscal_year("Quarter") is None


def test_last_trade_ignores_as_of_date() -> None:
    assert _last_trade("LAST TRADE: $230.36 (AS OF SEP 3, 2026)") == 230.36
