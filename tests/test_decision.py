from datetime import datetime, timezone

import pytest

from stock_pm.decision import (
    build_expectation_gap,
    build_thesis,
    build_what_changed,
    freeze_prediction,
    review_prediction,
    verify_frozen_prediction,
)


def _frozen():
    return freeze_prediction(
        {"symbol": "COHR", "direction": "bullish", "horizon": "5D"},
        generated_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        model_version="decision-v1",
        data_snapshot_id=42,
    )


def test_what_changed_is_ranked_and_keeps_missing_honest():
    result = build_what_changed(
        {"price": 100, "eps": 4, "iv30": None},
        {"price": 120, "eps": 4.1, "iv30": 60},
        materiality={"price": 5, "eps": 5},
    )
    assert result["changes"][0]["field"] == "price"
    assert result["changes"][0]["delta_pct"] == 20
    assert result["material_count"] == 1
    assert all(row["field"] != "iv30" for row in result["changes"])


def test_expectation_gap_uses_latest_consensus_and_shows_revision():
    result = build_expectation_gap(
        actual={"eps": 1.21}, latest_consensus={"eps": 1.2}, prior_consensus={"eps": 1.1}
    )
    row = result["rows"][0]
    assert row["gap_pct"] == 0.83
    assert row["revision_pct"] == 9.09
    assert row["result"] == "above"


def test_thesis_requires_both_sides_and_invalidation():
    thesis = build_thesis(
        direction="bullish",
        bull_drivers=["EPS revisions rise"],
        bear_drivers=["valuation is elevated"],
        key_disagreement="how much growth is priced in",
        invalidation={"fundamental": "FY27 EPS revisions below -8%"},
        evidence_quality="medium",
    )
    assert thesis["direction"] == "bullish"
    with pytest.raises(ValueError):
        build_thesis(direction="bullish", bull_drivers=["x"], bear_drivers=[], key_disagreement="x", invalidation={"x": 1}, evidence_quality="medium")


def test_frozen_record_detects_rewrite():
    record = _frozen()
    assert verify_frozen_prediction(record)
    record["prediction"]["direction"] = "bearish"
    assert not verify_frozen_prediction(record)


def test_review_scores_benchmark_and_invalidation():
    review = review_prediction(
        _frozen(), actual_return_pct=4, benchmark_return_pct=6, max_drawdown_pct=-2,
        invalidated=False, attribution="known_but_underweighted",
        attribution_evidence=[{"fact": "valuation high", "observed_at": "2026-09-09T00:00:00+00:00"}],
    )
    assert review["outcome"] == "hit"
    assert review["direction_hit"] is True
    assert review["excess_return_pct"] == -2

    invalidated = review_prediction(
        _frozen(), actual_return_pct=8, invalidated=True,
        attribution="timing_error", attribution_evidence=[],
    )
    assert invalidated["outcome"] == "miss"
    assert invalidated["invalidated_first"] is True


def test_attribution_rejects_hindsight_relabeling():
    with pytest.raises(ValueError):
        review_prediction(
            _frozen(), actual_return_pct=-3, attribution="known_but_underweighted",
            attribution_evidence=[{"fact": "late news", "observed_at": "2026-09-11T00:00:00+00:00"}],
        )
