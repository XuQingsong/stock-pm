from __future__ import annotations

from pathlib import Path

from stock_pm.events.accept_report import load_accept_reports
from stock_pm.events.accept_score import (
    e10_event_passes,
    e8_live_excerpt_ok,
    e8_metadata_only_passes,
)
from stock_pm.events.analyze import analyze_event, causal_chain_is_complete
from stock_pm.events.dedupe import build_events
from stock_pm.events.providers import load_fixture_documents
from stock_pm.events.service import coverage, market_center, reset_cache
from stock_pm.events.types import EventDocument


OFFICIAL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm"
CLAIM = "The Committee decided to maintain the target range for the federal funds rate."


def setup_function() -> None:
    reset_cache()


def _answers() -> dict:
    return {
        "what_happened": "placeholder",
        "credibility": "medium",
        "why_relevant": "placeholder",
        "how_long": "weeks",
        "invalidates_when": "later",
    }


def _complete_layers(*, cites_ok: bool = True, excerpt: str = CLAIM, exposures=None, fact_refs=None, texts=None):
    texts = texts or {
        "fact": CLAIM,
        "change": "市场首次纳入该利率事实",
        "expectation": "方向 watch · 期限 weeks_to_months · 置信度 medium",
        "impact": "先市场/行业：duration；NVDA 经 duration（inflation_to_rates_to_discount）",
        "what_changes": "纳入观察清单",
    }
    exposures = exposures if exposures is not None else [
        {"symbol": "NVDA", "channel": "duration", "mechanism": "inflation_to_rates_to_discount"}
    ]
    fact_refs = fact_refs if fact_refs is not None else [{"source_url": OFFICIAL, "publisher": "Federal Reserve"}]
    fact = {"id": "fact", "layer_id": "fact:1", "text": texts["fact"], "cites": [], "excerpt": excerpt, "evidence_refs": fact_refs}
    change = {
        "id": "change",
        "layer_id": "change:1",
        "text": texts["change"],
        "cites": ["fact:1"] if cites_ok else [],
        "evidence_refs": fact_refs,
    }
    expectation = {
        "id": "expectation",
        "layer_id": "expectation:1",
        "text": texts["expectation"],
        "cites": ["change:1"] if cites_ok else ["fact:1"],
        "direction": "watch",
        "horizon": "weeks_to_months",
        "confidence": "medium",
        "evidence_refs": fact_refs,
    }
    impact = {
        "id": "impact",
        "layer_id": "impact:1",
        "text": texts["impact"],
        "cites": ["expectation:1"] if cites_ok else [],
        "exposures": exposures,
        "evidence_refs": [],
    }
    what = {
        "id": "what_changes",
        "layer_id": "what_changes:1",
        "text": texts["what_changes"],
        "cites": ["impact:1"] if cites_ok else [],
        "invalidation": "若 FOMC 撤回该会议事实则失效",
        "follow_up": "观察后续声明",
        "evidence_refs": fact_refs,
    }
    return [fact, change, expectation, impact, what]


def test_e8_official_url_without_excerpt_cannot_pass():
    assert e8_metadata_only_passes(source_url=OFFICIAL, publisher="Federal Reserve", title=CLAIM, excerpt="") is False
    assert e8_live_excerpt_ok(claims=[{"text": CLAIM, "excerpt": "", "status": "current", "source_url": OFFICIAL}]) is False


def test_e8_unrelated_excerpt_cannot_pass():
    assert (
        e8_metadata_only_passes(
            source_url=OFFICIAL,
            publisher="Federal Reserve",
            title=CLAIM,
            claim=CLAIM,
            excerpt="Skip to main content. An official website of the United States Government.",
        )
        is False
    )


def test_e8_title_only_hit_cannot_pass():
    assert (
        e8_metadata_only_passes(
            source_url=OFFICIAL,
            publisher="Federal Reserve",
            http_status=200,
            title=CLAIM,
            claim=CLAIM,
            excerpt="",
        )
        is False
    )
    assert e8_live_excerpt_ok(
        claims=[{"text": CLAIM, "excerpt": "", "title": CLAIM, "status": "current", "source_url": OFFICIAL}]
    ) is False


def test_e8_supporting_excerpt_can_pass():
    assert e8_live_excerpt_ok(
        claims=[
            {
                "text": CLAIM,
                "excerpt": "The Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent.",
                "status": "current",
                "source_url": OFFICIAL,
                "publisher": "Federal Reserve",
            }
        ]
    )


def test_e10_fails_when_dom_markers_exist_but_chain_is_broken():
    analysis = {"answers": _answers(), "causal_chain": {"layers": _complete_layers(cites_ok=False)}}
    assert causal_chain_is_complete(analysis["causal_chain"]) is False
    assert e10_event_passes(analysis, dom_answers=list(_answers())) is False


def test_e10_fails_when_layers_empty_or_missing_evidence_or_exposure():
    empty = {
        "answers": _answers(),
        "causal_chain": {
            "layers": _complete_layers(texts={key: "" for key in ("fact", "change", "expectation", "impact", "what_changes")})
        },
    }
    no_evidence = {"answers": _answers(), "causal_chain": {"layers": _complete_layers(excerpt="", fact_refs=[])}}
    no_exposure = {"answers": _answers(), "causal_chain": {"layers": _complete_layers(exposures=[])}}
    assert e10_event_passes(empty, dom_answers=list(_answers())) is False
    assert e10_event_passes(no_evidence, dom_answers=list(_answers())) is False
    assert e10_event_passes(no_exposure, dom_answers=list(_answers())) is False


def test_e10_complete_chain_passes_without_relying_on_dom_markers():
    analysis = {"answers": {}, "causal_chain": {"layers": _complete_layers()}}
    assert causal_chain_is_complete(analysis["causal_chain"])
    assert e10_event_passes(analysis, dom_answers=[])


def test_withhold_without_sources_fails_e10_chain():
    event = build_events(
        [
            EventDocument(
                title="Rumor without url",
                url="",
                publisher="Unknown",
                published_at=None,
                event_type="other",
            )
        ]
    )[0]
    analysis = analyze_event(event)
    assert analysis["causal_chain"]["complete"] is False
    assert e10_event_passes(analysis, dom_answers=list(analysis["answers"])) is False


def test_product_pages_do_not_show_accept_gates_or_debug_none():
    root = Path(__file__).resolve().parents[1] / "src" / "stock_pm" / "static"
    product = (root / "events_ui.js").read_text(encoding="utf-8") + (root / "stock.js").read_text(encoding="utf-8")
    accept = (root / "accept.js").read_text(encoding="utf-8") + (root / "accept.html").read_text(encoding="utf-8")
    assert "accept-only" not in product
    assert "live_e1_e10_gate" not in product
    assert "capability_e1_e10_gate" not in product
    assert "percent_forecast=" not in product
    assert "price_target=" not in product
    assert "live_e1_e10_gate" in accept
    assert "capability_e1_e10_gate" in accept
    cover = coverage()
    assert cover["live_e1_e10_gate"] is None
    assert cover["capability_e1_e10_gate"] is None
    assert cover["product_status"]["source_health"]["label"]
    assert cover["product_status"]["evidence_sufficiency"]["label"]
    assert cover["product_status"]["can_conclude"]["label"]
    assert cover["product_status"]["can_conclude"]["reason"]


def test_accept_report_api_matches_files(tmp_path: Path):
    missing = load_accept_reports(tmp_path)
    assert missing["source"] == "missing_accept_report"
    assert missing["live_e1_e10_gate"] is None
    assert missing["capability_e1_e10_gate"] is None
    (tmp_path / "live-current.json").write_text(
        '{"provider_health_gate": true, "live_e1_e10_gate": false, "pass_count": 6, "verdict": {"E8": "PASS"}}',
        encoding="utf-8",
    )
    (tmp_path / "capability-black-box.json").write_text(
        '{"capability_e1_e10_gate": true, "pass_count": 9, "verdict": {"E3": "UNVERIFIED"}}',
        encoding="utf-8",
    )
    loaded = load_accept_reports(tmp_path)
    assert loaded["source"] == "accept_report_files"
    assert loaded["provider_health_gate"] is True
    assert loaded["live_e1_e10_gate"] is False
    assert loaded["capability_e1_e10_gate"] is True
    assert loaded["live"]["pass_count"] == 6
    assert loaded["capability"]["pass_count"] == 9


def test_fixture_iran_chain_is_not_mechanical_copy():
    iran = next(row for row in build_events(load_fixture_documents()) if row.event_type == "war_sanctions")
    analyze_event(iran)
    symbols = {row["symbol"] for row in iran.analysis["causal_chain"]["layers"][3]["exposures"]}
    assert "XOM" in symbols
    assert "AAPL" not in symbols
    center = market_center()
    assert any(row["analysis"]["causal_chain"]["layers"] for row in center["events"])
