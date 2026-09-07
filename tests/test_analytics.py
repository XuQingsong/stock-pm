from datetime import datetime, timezone

from stock_pm.analytics import (
    earnings_summary,
    enrich_chart_bars,
    money_flow,
    percentile,
    resample_bars,
    volume_profile,
)


def _bar(day: int, hour: int = 14, minute: int = 0, **fields) -> dict:
    stamp = datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc)
    row = {
        "symbol": "AAPL",
        "bar_time": stamp,
        "open_price": 100,
        "high_price": 102,
        "low_price": 99,
        "close_price": 101,
        "volume": 1000,
        "source": "test",
    }
    row.update(fields)
    return row


def test_resample_intraday_and_daily_passthrough() -> None:
    rows = [
        _bar(3, 14, 0, open_price=10, high_price=10.5, low_price=9.8, close_price=10, volume=10),
        _bar(3, 14, 1, open_price=10, high_price=12, low_price=10, close_price=12, volume=20),
        _bar(3, 14, 2, open_price=12, high_price=12, low_price=9, close_price=11, volume=30),
    ]
    sampled = resample_bars(rows, "5m")
    assert len(sampled) == 1
    assert sampled[0]["open_price"] == 10
    assert sampled[0]["high_price"] == 12
    assert sampled[0]["low_price"] == 9
    assert sampled[0]["close_price"] == 11
    assert sampled[0]["volume"] == 60
    assert resample_bars(rows, "1d")[0]["close_price"] == 10


def test_enrich_adds_amount_ma_and_kdj() -> None:
    rows = [_bar(day, close_price=100 + day, high_price=101 + day, low_price=99 + day) for day in range(1, 12)]
    enriched = enrich_chart_bars(rows)
    assert enriched[0]["ma5"] is None
    assert enriched[4]["ma5"] is not None
    assert "ma10" not in enriched[-1]
    assert enriched[-1]["ma20"] is None
    long_rows = [_bar(min(28, day), close_price=100 + day, high_price=101 + day, low_price=99 + day) for day in range(1, 55)]
    long_enriched = enrich_chart_bars(long_rows)
    assert long_enriched[-1]["ma20"] is not None
    assert long_enriched[-1]["ma50"] is not None
    assert long_enriched[-1]["ma200"] is None
    assert long_enriched[-1]["amount"] > 0
    assert {"k", "d", "j"} <= long_enriched[-1].keys()


def test_volume_profile_marks_poc_and_value_area() -> None:
    bars = [
        _bar(1, close_price=10, high_price=10.5, low_price=9.5, volume=100),
        _bar(2, close_price=20, high_price=21, low_price=19, volume=800),
        _bar(3, close_price=11, high_price=11.5, low_price=10.5, volume=120),
    ]
    profile = volume_profile(bars)
    assert profile["poc"] is not None
    assert 18 <= profile["poc"] <= 22
    assert profile["support_levels"] or profile["resistance_levels"]
    assert profile["current_price"] == 11


def test_money_flow_and_percentile() -> None:
    bars = [
        _bar(5, close_price=12, high_price=13, low_price=10, volume=200),
        _bar(4, close_price=11, high_price=12, low_price=10, volume=150),
        _bar(3, close_price=10, high_price=11, low_price=9, volume=100),
    ]
    flow = money_flow(bars)
    assert "cmf20" in flow
    assert "flow_label" in flow
    assert percentile([10, 20, 30], 20) == 66.7


def test_earnings_summary_does_not_invent_missing_fields() -> None:
    summary = earnings_summary(
        [
            {
                "eps_actual": 1.5,
                "eps_estimate": 1.4,
                "eps_surprise_pct": 7.1,
                "revenue_actual": None,
                "net_income_actual": None,
                "post_1d_return_pct": 2.0,
            }
        ]
    )
    assert any("EPS" in item for item in summary["highlights"])
    assert all("营收实际值" not in item and "净利润实际值" not in item for item in summary["highlights"])
    assert summary["avg_abs_move_pct"] == 2.0


def test_prefer_fmp_over_nasdaq_same_date() -> None:
    from stock_pm.queries import QueryMixin

    rows = QueryMixin()._prefer_earnings_rows(
        [
            {
                "report_date": "2026-07-30",
                "source": "Nasdaq earnings surprise",
                "eps_actual": 1.91,
                "revenue_actual": None,
            },
            {
                "report_date": "2026-07-30",
                "source": "FMP earnings + income-statement",
                "eps_actual": 2.02,
                "revenue_actual": 109e9,
            },
            {
                "report_date": "2026-04-30",
                "source": "FMP earnings + income-statement",
                "eps_actual": 2.01,
                "revenue_actual": 111e9,
            },
        ]
    )
    assert [row["report_date"] for row in rows] == ["2026-07-30", "2026-04-30"]
    assert rows[0]["eps_actual"] == 2.02
    assert rows[0]["revenue_actual"] == 109e9
