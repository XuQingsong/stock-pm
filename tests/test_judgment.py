from stock_pm.evidence import (
    INCOMPLETE_LABEL,
    analysis_ref,
    evidence_item,
    fact_ref,
    public_evidence,
)
from stock_pm.judgment import NO_STORED_LABEL, assemble_judgment
from stock_pm.prediction import (
    GATE_ANALYSIS_ABSTAIN,
    GATE_BOUNDS_TOO_TIGHT,
    GATE_PREMISE_MISSING,
    diagnose_quality_gate,
    failed_prediction,
    synthesize_prediction,
)
from stock_pm.tape import synthesize_review_note, synthesize_tape_analysis


def _env(atmosphere: str = "补涨") -> dict:
    return {
        "id": 11,
        "as_of_date": "2026-09-04",
        "one_liner": "盘面：缩量跌；消息：行业利多；因此：先按盘面读。",
        "synthesis": "盘面：缩量跌；消息：行业利多；因此：先按盘面读。",
        "publishState": "published",
        "missingFlags": [],
        "struct": {"sentiment": {"atmosphere": atmosphere, "clause": f"氛围{atmosphere}"}},
    }


def _tape(*, support=19.0, resistance=22.0, close=20.0, environment=None, **metrics):
    payload = {
        "day_change_pct": metrics.get("day_change_pct", -1.2),
        "relative_volume": metrics.get("relative_volume", 0.6),
        "poc_60d": 19.5,
        "support": support,
        "resistance": resistance,
        "close": close,
        "position": "筹码在现价附近",
    }
    tape = synthesize_tape_analysis(
        as_of_date="2026-09-04",
        symbol=metrics.get("symbol", "INTC"),
        metrics=payload,
        environment=environment or _env(),
        source="test",
    )
    tape["id"] = 12
    return tape


def _note(tape):
    note = synthesize_review_note(
        as_of_date="2026-09-04",
        symbol="INTC",
        tape=tape,
        environment=_env(),
        source="test",
    )
    note["id"] = 13
    return note


def test_evidence_schema_separates_fact_and_analysis() -> None:
    fact = fact_ref(
        ref_table="price_bars",
        ref_id="AAPL|1d|2026-09-04",
        as_of="2026-09-04",
        text="AAPL 日线收盘 230",
        source_name="Alpaca",
    )
    analysis = analysis_ref(
        ref_table="tape_analyses",
        ref_id=12,
        as_of="2026-09-04",
        text="缩量跌",
        based_on=[fact],
    )
    assert fact["layer"] == "fact"
    assert analysis["layer"] == "analysis"
    assert analysis["based_on"][0]["layer"] == "fact"
    assert analysis["completeness"] == "complete"
    orphan = analysis_ref(
        ref_table="environment_snapshots",
        ref_id=11,
        as_of="2026-09-04",
        text="隔夜环境",
    )
    assert orphan["completeness"] == "partial"
    assert INCOMPLETE_LABEL in orphan["text"]
    published = public_evidence(
        evidence_item(
            layer="fact",
            ref_table="news_articles",
            ref_id=9,
            text="标题",
            source_url="javascript:alert(1)",
            completeness="complete",
        )
    )
    assert published["source_url"] is None


def test_aapl_like_tight_support_is_not_missing_flag() -> None:
    tape = _tape(support=229.4, resistance=238.0, close=230.0, judgment="吸筹", symbol="AAPL")
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="AAPL",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=230.0,
        support=229.4,
        resistance=238.0,
    )
    assert pred["gate_reason"] == GATE_BOUNDS_TOO_TIGHT
    assert pred["missingFlags"] == []
    assert "缺下沿" not in (pred["missing_label"] or "")
    assert "缺上沿" not in (pred["missing_label"] or "")
    assert "支撑距现价过近" in pred["missing_label"]
    assert pred["upside_bound_pct"] is None
    assert pred["window_start"] is None
    diagnosed = diagnose_quality_gate(
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=230.0,
        support=229.4,
        resistance=238.0,
        as_of_date="2026-09-04",
    )
    assert diagnosed["gate_reason"] == GATE_BOUNDS_TOO_TIGHT
    assert diagnosed["missingFlags"] == []


def test_avgo_like_abstain_is_not_six_missing_flags() -> None:
    hot = _env(atmosphere="过热")
    tape = _tape(
        support=160.0,
        resistance=180.0,
        close=170.0,
        environment=hot,
        day_change_pct=1.8,
        relative_volume=1.6,
        symbol="AVGO",
    )
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="AVGO",
        environment=hot,
        tape=tape,
        review_note=_note(tape),
        entry_price=170.0,
        support=160.0,
        resistance=180.0,
    )
    assert pred["gate_reason"] == GATE_ANALYSIS_ABSTAIN
    assert pred["missingFlags"] == []
    assert "缺入场价" not in (pred["missing_label"] or "")
    assert "缺昨盘" not in (pred["missing_label"] or "")
    assert "区间假设" in (pred["missing_label"] or pred["kind_label"] or "")
    assert pred["upside_bound_pct"] is None
    assert pred["window_label"] is None


def test_true_missing_inputs_keep_named_flags() -> None:
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment={"publishState": "missing", "one_liner": None},
        tape={"publishState": "missing", "volume_price": None, "chips": {}},
        review_note={"unexplained": True},
        entry_price=None,
    )
    assert pred["gate_reason"] == GATE_PREMISE_MISSING
    assert "tape" in pred["missingFlags"]
    assert "environment" in pred["missingFlags"]
    assert "entry_price" in pred["missingFlags"]
    assert set(pred["missingFlags"]) <= {
        "tape",
        "environment",
        "entry_price",
        "support",
        "resistance",
        "window",
    }


def test_failed_prediction_does_not_dump_all_flags() -> None:
    pred = failed_prediction("MU", "2026-09-04", "quality_gate")
    assert pred["missingFlags"] == []
    assert "缺入场价" not in (pred.get("missing_label") or "")


def test_assemble_judgment_layers_and_missing_row() -> None:
    tape = _tape()
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=19.0,
        resistance=22.0,
    )
    pred["id"] = 7
    pred["created_at"] = "2026-09-04T20:10:00+00:00"
    price = fact_ref(
        ref_table="price_bars",
        ref_id="INTC|1d|2026-09-04",
        as_of="2026-09-04",
        text="INTC 日线收盘 20",
        role="price",
    )
    payload = assemble_judgment(
        symbol="INTC",
        as_of_date="2026-09-04",
        prediction=pred,
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        resolved_facts=[price],
        generated_at=pred["created_at"],
    )
    assert payload["judgment"]["prediction_ready"] is True
    assert payload["judgment"]["kind_label"] == "区间假设"
    assert payload["gate"]["reason"] is None
    assert all(item["layer"] == "analysis" for item in payload["reasons"])
    assert all(item["layer"] == "fact" for item in payload["facts"])
    assert payload["facts"][0]["ref_table"] == "price_bars"
    assert "environment_snapshots" not in {item["ref_table"] for item in payload["facts"]}
    assert payload["invalidation"]
    assert payload["data_snapshot_id"]

    empty = assemble_judgment(symbol="AAPL", as_of_date="2026-09-04")
    assert empty["judgment"]["prediction_ready"] is False
    assert empty["gate"]["reason"] == "missing"
    assert empty["judgment"]["upside_bound_pct"] is None
    assert empty["judgment"]["window_start"] is None
    assert NO_STORED_LABEL in empty["judgment"]["one_liner"]


def test_legacy_six_flag_row_is_rediagnosed() -> None:
    hot = _env(atmosphere="过热")
    tape = _tape(
        support=160.0,
        resistance=180.0,
        close=170.0,
        environment=hot,
        day_change_pct=1.8,
        relative_volume=1.6,
        symbol="AVGO",
    )
    stale = failed_prediction(
        "AVGO",
        "2026-09-04",
        "quality_gate",
        flags=["entry_price", "support", "resistance", "tape", "environment", "window"],
    )
    stale["id"] = 8
    payload = assemble_judgment(
        symbol="AVGO",
        as_of_date="2026-09-04",
        prediction=stale,
        environment=hot,
        tape=tape,
        review_note=_note(tape),
        resolved_facts=[],
    )
    assert payload["gate"]["reason"] == GATE_ANALYSIS_ABSTAIN
    assert payload["gate"]["missingFlags"] == []
    assert payload["judgment"]["upside_bound_pct"] is None
    assert all(item["layer"] != "fact" for item in payload["reasons"])


def test_unresolved_fact_is_dropped() -> None:
    tape = _tape()
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        entry_price=20.0,
        support=19.0,
        resistance=22.0,
    )
    pred["id"] = 9
    payload = assemble_judgment(
        symbol="INTC",
        as_of_date="2026-09-04",
        prediction=pred,
        environment=_env(),
        tape=tape,
        review_note=_note(tape),
        resolved_facts=[
            {
                "layer": "fact",
                "ref_table": "price_bars",
                "ref_id": None,
                "text": "should drop",
            },
            {
                "layer": "analysis",
                "ref_table": "tape_analyses",
                "ref_id": 12,
                "text": "should not become a fact",
            },
        ],
    )
    assert payload["facts"] == []
    assert payload["reasons"]
    assert any(INCOMPLETE_LABEL in (item.get("text") or "") for item in payload["reasons"])


def test_judgment_view_has_no_side_effects() -> None:
    writes: list[str] = []

    class Probe:
        def market_session(self, date=None):
            return {"date": "2026-09-04", "default_review_date": "2026-09-04"}

        def latest_prediction(self, *_args, **_kwargs):
            return None

        def latest_environment_snapshot(self, *_args, **_kwargs):
            return None

        def latest_tape_analysis(self, *_args, **_kwargs):
            return None

        def latest_review_note(self, *_args, **_kwargs):
            return None

        def reviews_by_date(self, *_args, **_kwargs):
            return []

        def fetch_all(self, *_args, **_kwargs):
            return []

        def append_prediction(self, *_args, **_kwargs):
            writes.append("append_prediction")

        def build_live_prediction(self, *_args, **_kwargs):
            writes.append("build_live_prediction")
            raise AssertionError("must not synthesize on read")

    from stock_pm.queries import QueryMixin

    probe = Probe()
    probe._stored_daily_review = QueryMixin._stored_daily_review.__get__(probe)
    probe._collect_judgment_facts = QueryMixin._collect_judgment_facts.__get__(probe)
    probe._safe_fetch = QueryMixin._safe_fetch.__get__(probe)
    probe._fact_price_bar = QueryMixin._fact_price_bar.__get__(probe)
    probe._fact_snapshot = QueryMixin._fact_snapshot.__get__(probe)
    probe._fact_news = QueryMixin._fact_news.__get__(probe)
    probe._fact_earnings = QueryMixin._fact_earnings.__get__(probe)
    probe._fact_macro = QueryMixin._fact_macro.__get__(probe)
    view = QueryMixin.judgment_view(probe, "AAPL", "2026-09-04")
    assert view["gate"]["reason"] == "missing"
    assert view["judgment"]["window_label"] is None
    assert writes == []
