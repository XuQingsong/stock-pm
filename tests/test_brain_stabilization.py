from __future__ import annotations

from stock_pm.brain.causal import coerce_causal_edges, detect_causal_gaps, research_question_ok, structured_gap_question
from stock_pm.brain.constitution import constitution_violations
from stock_pm.brain.expectation import expectation_from_event, normalize_expectation
from stock_pm.brain.hypothesis import event_polarity, hypotheses_from_event
from stock_pm.brain.materiality import materiality_gate
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore

from test_brain_runtime import RuntimeFakeCompleter


def test_malformed_causal_edges_are_rejected_not_crashed() -> None:
    edges = coerce_causal_edges(
        [
            {"from_node": "a", "to_node": "b", "status": "supported"},
            '{"from_node": "c", "to_node": "d", "status": "observed"}',
            "bced_bare_id",
            None,
            "not-json",
        ],
        ticker="AVGO",
    )
    assert len(edges) == 2
    assert all(isinstance(row, dict) and row.get("from_node") for row in edges)
    hits = constitution_violations(
        {
            "object_type": "core_claim",
            "source_kind": "news",
            "causal_edges": ["bced_bare_id", "also-bad"],
            "to_payload": {"status": "strongly_supported"},
        }
    )
    assert any(row["rule"] == "unsupported_causal_cannot_transmit" for row in hits)


def test_abnormal_price_is_material_even_if_l1_says_no() -> None:
    gate = materiality_gate(
        {"title": "AVGO shares move -6.2% with no new filing", "kind": "price", "price_change_pct": -6.2, "event_type": "other"},
        ticker="AVGO",
        extract={"material": False, "novelty": "none", "fact": "Shares moved -6.2%."},
    )
    assert gate["material"] is True
    assert gate["abnormal_price"] is True
    assert gate["price_only"] is True


def test_expectation_without_pair_is_unknown() -> None:
    row = normalize_expectation({"name": "print", "comparison": "in_line", "actual": None, "expected": None}, ticker="AVGO")
    assert row["comparison"] == "unknown"
    rumor = expectation_from_event(
        {
            "kind": "rumor",
            "title": "Unconfirmed rumor that Google may delay volume",
            "fact": "Google may delay custom silicon volume.",
            "fact_reliability": "rumor",
        },
        ticker="AVGO",
    )
    assert rumor is not None
    assert rumor["comparison"] == "unknown"
    assert rumor["expected"] is None


def test_later_confirmation_weakens_or_closes_same_hypothesis() -> None:
    first = hypotheses_from_event(
        {
            "kind": "rumor",
            "title": "Unconfirmed rumor that Google may delay custom silicon volume",
            "fact": "Google may delay TPU volume.",
            "fact_reliability": "rumor",
            "entities": ["Google"],
        },
        ticker="AVGO",
    )
    created = first["created"]
    assert created
    assert event_polarity({"title": "Google may delay", "kind": "rumor", "fact_reliability": "rumor"}) == "risk"
    later = hypotheses_from_event(
        {
            "kind": "news",
            "title": "Google confirmed a Broadcom custom-silicon order expansion",
            "fact": "Google confirmed it will expand custom ASIC / TPU orders.",
            "fact_reliability": "direct_fact",
            "confirmed": True,
            "entities": ["Google"],
        },
        ticker="AVGO",
        existing=created,
    )
    assert later["updated"]
    assert later["created"] == []
    assert later["hypothesis_closed"] + later["hypothesis_weakened"] >= 1
    assert str(later["updated"][0]["status"]) in {"weakened", "closed", "retired"}


def test_causal_gap_question_is_not_a_headline_template() -> None:
    gaps = detect_causal_gaps(
        event={"title": "A very long unused headline about something unrelated to a template", "fact": "x", "entities": ["Google"]},
        edges=[{"from_node": "a", "to_node": "b", "status": "supported"}],
        related_claims=[{"claim_id": "bclm_x", "title": "AI durability"}],
    )
    for row in gaps:
        assert "How exposed is the issuer to" not in str(row.get("question") or "")
        assert research_question_ok(row.get("question"))
    assert "How exposed is the issuer to" not in structured_gap_question(entity="Google", exposure="customer exposure", target="AI durability")


def test_price_only_cannot_write_fundamental_or_claim() -> None:
    fake = RuntimeFakeCompleter()
    store = BrainStore()
    result = run_brain_update(
        ticker="AVGO",
        item={
            "kind": "price",
            "title": "AVGO shares move -6.2% with no new filing",
            "fact": "Shares moved -6.2% without a new operating disclosure.",
            "price_change_pct": -6.2,
            "event_type": "other",
            "fact_reliability": "signal",
        },
        store=store,
        completer=fake,
    )
    assert result["stopped"] is False
    assert result["material"] is True
    assert result["now_chain"]
    approved = result.get("gate", {}).get("approved") or []
    assert not any(str(row.get("object_type") or "") in {"company_state", "state", "core_claim", "claim"} for row in approved)
    assert result["market_layer"]["price_fundamental_violations"] == 0
    assert result["market_layer"]["price_claim_violations"] == 0
