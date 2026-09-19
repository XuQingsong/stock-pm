#!/usr/bin/env python3
"""Phase 0–3 continuous AVGO end-to-end validation.

One Brain. Real historical window. Sequential ingest. No architecture changes.
Does not start Phase 4.
"""

from __future__ import annotations

import json
import sys
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from stock_pm.brain.context_miss import find_context_misses, score_snapshot_context
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.types import OBJECT_LAYER
from stock_pm.config import Settings
from stock_pm.research.llm_reason import compact_text

from validate_brain_runtime import (
    CLAIM_DEMAND,
    CLAIM_HYPERSCALER,
    CLAIM_MARGIN,
    CLAIM_MULTIPLE,
    DRIVER_COMPETITION,
    DRIVER_CONCENTRATION,
    DRIVER_DEMAND,
    DRIVER_GAAP,
    DRIVER_LEVERAGE,
    DRIVER_VALUATION,
    EVIDENCE_EXHIBIT,
    EVIDENCE_MARVELL,
    GOLDEN,
    IRRELEVANT_CDE,
    leftover_brain,
    ping_layers,
    seed_avgo_brain,
)

OUT = Path("artifacts/brain_phase03_e2e")
TICKER = "AVGO"

SLOW_TYPES = {
    "state",
    "company_state",
    "industry_state",
    "macro_state",
    "driver",
    "value_driver",
    "claim",
    "core_claim",
    "causal_edge",
    "causal_relationship",
}
FAST_TYPES = {
    "expectation",
    "expectation_state",
    "market_attention",
    "market_driver_hypothesis",
    "market_driver",
    "price_reaction",
    "shadow_state",
    "research_question",
    "observation",
    "news",
    "event",
}

GENERIC_RQ = (
    "what is the outlook",
    "thoughts on avgo",
    "what will happen",
    "is avgo a buy",
    "how is the company doing",
    "what is the future",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(name: str, payload: object) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    if name.endswith(".md"):
        path.write_text(str(payload), encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print("wrote", path, flush=True)
    return path


def _sig_row(row: dict[str, Any], *keys: str) -> str:
    parts = []
    for key in keys:
        if key in row:
            parts.append(f"{key}={row.get(key)}")
    return "|".join(parts)


def brain_index(store: Any) -> dict[str, Any]:
    def _map(rows: list[dict[str, Any]], *keys: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in rows or []:
            token = ""
            for key in keys:
                if row.get(key):
                    token = str(row.get(key))
                    break
            if token:
                out[token] = deepcopy(row)
        return out

    return {
        "states": _map(store.list_states(TICKER), "state_id"),
        "drivers": _map(store.list_drivers(TICKER), "driver_id"),
        "claims": _map(store.list_active_claims(TICKER), "claim_id"),
        "edges": _map(store.list_causal_edges(TICKER), "edge_id"),
        "expectations": _map(store.list_expectations(TICKER), "expectation_id", "name"),
        "attentions": _map(store.list_market_attentions(TICKER), "attention_id", "name"),
        "hypotheses": _map(store.list_hypotheses(TICKER), "hypothesis_id"),
        "shadows": _map(store.list_shadows(TICKER), "shadow_id"),
        "questions": _map(store.list_questions(TICKER), "question_id"),
    }


def _changed(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for key, nxt in after.items():
        prev = before.get(key)
        if prev is None:
            diffs.append({"id": key, "action": "created", "to": {field: nxt.get(field) for field in fields}})
            continue
        changed = {field: {"from": prev.get(field), "to": nxt.get(field)} for field in fields if prev.get(field) != nxt.get(field)}
        if changed:
            diffs.append({"id": key, "action": "updated", "fields": changed})
    for key, prev in before.items():
        if key not in after:
            diffs.append({"id": key, "action": "removed", "from": {field: prev.get(field) for field in fields}})
    return diffs


def diff_brain(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "states": _changed(before["states"], after["states"], ("statement", "direction", "confidence")),
        "drivers": _changed(before["drivers"], after["drivers"], ("current_state", "status", "uncertainty")),
        "claims": _changed(before["claims"], after["claims"], ("statement", "status", "confidence")),
        "edges": _changed(before["edges"], after["edges"], ("status", "statement")),
        "expectations": _changed(before["expectations"], after["expectations"], ("comparison", "trend", "actual", "expected", "confidence")),
        "attentions": _changed(before["attentions"], after["attentions"], ("statement", "name")),
        "hypotheses": _changed(before["hypotheses"], after["hypotheses"], ("status", "confidence", "hypothesis", "canonical_key")),
        "shadows": _changed(before["shadows"], after["shadows"], ("statement", "status", "name")),
        "questions": _changed(before["questions"], after["questions"], ("question", "status")),
    }


def _hyp_by_key(store: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in store.list_hypotheses(TICKER):
        out[str(row.get("canonical_key") or row.get("hypothesis_id"))] = row
    return out


def classify_rq(question: str) -> dict[str, Any]:
    text = (question or "").strip()
    low = text.lower()
    generic = any(token in low for token in GENERIC_RQ) or len(text.split()) < 6
    specific = any(
        token in low
        for token in (
            "google",
            "meta",
            "anthropic",
            "openai",
            "marvell",
            "hyperscaler",
            "capex",
            "xpu",
            "asic",
            "tpu",
            "exposure",
            "causal",
            "expectation",
            "eps",
            "ai semiconductor",
        )
    )
    if generic and not specific:
        grade = "weak"
        note = "Generic or underspecified; not clearly tied to a Brain gap."
    elif specific:
        grade = "useful"
        note = "Names a concrete entity, metric, or gap that can be checked."
    else:
        grade = "mixed"
        note = "Possibly useful, but not tightly bound to a named gap."
    return {"question": compact_text(text, 220), "grade": grade, "note": note}


def expected_for(event: dict[str, Any]) -> dict[str, Any]:
    tags = set(event.get("tags") or [])
    spec: dict[str, Any] = {"irrelevant": list(IRRELEVANT_CDE)}
    drivers: list[str] = []
    claims: list[str] = []
    evidence: list[str] = []
    counter: list[str] = []
    if tags & {"customer", "demand", "ai", "google", "print"}:
        drivers.extend([DRIVER_DEMAND, DRIVER_CONCENTRATION])
        claims.extend([CLAIM_DEMAND, CLAIM_HYPERSCALER])
        evidence.append(EVIDENCE_EXHIBIT)
    if tags & {"competition", "marvell"}:
        drivers.extend([DRIVER_COMPETITION, DRIVER_CONCENTRATION])
        claims.append(CLAIM_HYPERSCALER)
        counter.append(EVIDENCE_MARVELL)
        evidence.append(EVIDENCE_EXHIBIT)
    if tags & {"valuation", "tape"}:
        drivers.append(DRIVER_VALUATION)
        claims.append(CLAIM_MULTIPLE)
    spec["drivers"] = list(dict.fromkeys(drivers))
    spec["claims"] = list(dict.fromkeys(claims))
    spec["support_evidence"] = list(dict.fromkeys(evidence))
    spec["counter_evidence"] = list(dict.fromkeys(counter))
    return spec


def timeline() -> list[dict[str, Any]]:
    """Documented AVGO window: 2026-06-03 to 2026-09-16. Not independent fixtures."""
    return [
        {
            "event_id": "e01_q2_filing",
            "published_at": "2026-06-03T20:05:00+00:00",
            "role": "earnings",
            "tags": ["earnings", "ai"],
            "source": "Broadcom Q2 FY2026 release, 2026-06-03",
            "item": {
                "kind": "filing",
                "event_key": "avgo_q2_fy2026_release",
                "title": "Broadcom reports fiscal Q2 FY2026 earnings and quarterly dividend",
                "fact": "Q2 FY2026 revenue was $22.2 billion, up 48% year over year. AI semiconductor revenue was $10.8 billion, up 143%.",
                "url": "https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announces-second-quarter-fiscal-year-2026-financial",
                "source": "Broadcom IR",
                "event_type": "earnings",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e02_q2_print_vs_expect",
            "published_at": "2026-06-03T21:10:00+00:00",
            "role": "expectation_print",
            "tags": ["print", "ai", "demand"],
            "source": "CNBC / company figures, 2026-06-03: revenue 22.19 vs 22.27; Q3 AI 16 vs expected 17.2; EPS 2.44 vs 2.40",
            "item": {
                "kind": "news",
                "event_key": "avgo_q2_ai_print_vs_street",
                "title": "AVGO AI semiconductor next-quarter figure 16 billion versus street 17.2 billion",
                "fact": (
                    "Revenue printed 22.19 billion versus street 22.27 billion. Adjusted EPS printed 2.44 versus 2.40. "
                    "The next-quarter AI semiconductor figure of 16 billion was below the street 17.2 billion."
                ),
                "url": "https://www.cnbc.com/2026/06/03/broadcom-avgo-earnings-report-q2-2026.html",
                "source": "CNBC",
                "event_type": "other",
                "actual": 16.0,
                "expected": 17.2,
                "expectation_name": "Q3 AI semiconductor revenue",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Broadcom"],
            },
        },
        {
            "event_id": "e03_q2_sector_tape",
            "published_at": "2026-06-04T20:00:00+00:00",
            "role": "peer_sector",
            "tags": ["tape", "valuation"],
            "source": "Golden Brain price-reaction state; SOX -10.26% and AVGO about -12.6% on 2026-06-04",
            "item": {
                "kind": "price",
                "event_key": "avgo_q2_post_print_tape",
                "title": "AVGO shares move -12.6% with semiconductor peers",
                "fact": "AVGO -12.59%. NVDA and other semiconductor names also sold off. SOX about -10%.",
                "event_type": "other",
                "price_change_pct": -12.59,
                "peers": {"NVDA": -8.0, "AMD": -7.0, "SOX": -10.26},
                "fact_reliability": "signal",
            },
        },
        {
            "event_id": "e04_noise_druckenmiller",
            "published_at": "2026-06-15T14:00:00+00:00",
            "role": "ordinary_news",
            "tags": ["noise"],
            "source": "Golden Brain news title already in the v1 dump",
            "item": {
                "kind": "news",
                "event_key": "avgo_druckenmiller_feature",
                "title": "Billionaire Stanley Druckenmiller Dumped Broadcom and 11X'd His Fund's Stake in This Trillion-Dollar Dual-Industry Leader",
                "fact": "A feature recap says Stanley Druckenmiller sold Broadcom and raised another fund stake. No new operating disclosure.",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e05_tender_notes",
            "published_at": "2026-06-20T16:00:00+00:00",
            "role": "ordinary_news",
            "tags": ["capital"],
            "source": "Golden driver evidence: cash tender offers for notes in June 2026",
            "item": {
                "kind": "news",
                "event_key": "avgo_june_note_tender",
                "title": "Broadcom priced cash tender offers for certain outstanding notes",
                "fact": "Broadcom priced cash tender offers for certain outstanding notes, an active balance-sheet item. No customer or AI demand update.",
                "url": "https://www.sec.gov/",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e06_noise_arista",
            "published_at": "2026-07-20T13:30:00+00:00",
            "role": "ordinary_news",
            "tags": ["noise"],
            "source": "Golden Brain news title",
            "item": {
                "kind": "news",
                "event_key": "avgo_arista_zacks_roundup",
                "title": "Arista Networks highlighted as Zacks Bull and Yum! Brands Bear of the Day",
                "fact": "A Zacks roundup names Arista and Yum. Broadcom is not the operating subject.",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e07_google_rumor",
            "published_at": "2026-08-12T18:00:00+00:00",
            "role": "rumor",
            "tags": ["google", "customer", "rumor"],
            "source": "Recurring unconfirmed Google TPU/order-cut rumor pattern cited in prior runtime validation",
            "item": {
                "kind": "rumor",
                "event_key": "google_may_delay_tpu_volume",
                "subject": "Google custom silicon volume",
                "title": "Unconfirmed rumor that Google may delay custom silicon volume",
                "fact": "An unconfirmed rumor says Google may delay custom silicon volume with Broadcom as it expands in-house silicon.",
                "event_type": "other",
                "entities": ["Google"],
                "confirmed": False,
                "confidence": "low",
                "fact_reliability": "rumor",
            },
        },
        {
            "event_id": "e08_q3_filing",
            "published_at": "2026-09-02T20:05:00+00:00",
            "role": "earnings",
            "tags": ["earnings", "ai"],
            "source": "Broadcom Q3 FY2026 release, 2026-09-02",
            "item": {
                "kind": "filing",
                "event_key": "avgo_q3_fy2026_release",
                "title": "Broadcom reports fiscal Q3 FY2026 earnings and guides Q4 AI semiconductor revenue to 21.7 billion",
                "fact": (
                    "Q3 FY2026 revenue was 29.6 billion, up 86%. AI semiconductor revenue was 16.7 billion, up 221%. "
                    "Management expects Q4 AI semiconductor revenue of 21.7 billion."
                ),
                "url": "https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announces-third-quarter-fiscal-year-2026-financial",
                "source": "Broadcom IR",
                "event_type": "earnings",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e09_q3_print_vs_expect",
            "published_at": "2026-09-02T21:20:00+00:00",
            "role": "expectation_print",
            "tags": ["print", "ai", "demand"],
            "source": "Company print + golden EPS history: EPS 2.68 vs 2.83; AI 16.7 vs prior 16 figure",
            "item": {
                "kind": "news",
                "event_key": "avgo_q3_ai_print_vs_street",
                "title": "AVGO AI semiconductor printed 16.7 billion; EPS 2.68 versus 2.83 expected",
                "fact": (
                    "AI semiconductor revenue printed 16.7 billion versus the prior 16 billion figure. "
                    "EPS printed 2.68 versus 2.83 expected. Total revenue was 29.6 billion, up 86%."
                ),
                "url": "https://www.prnewswire.com/news-releases/broadcom-inc-announces-third-quarter-fiscal-year-2026-financial-results-and-quarterly-dividend-302868129.html",
                "source": "PR Newswire / golden EPS history",
                "event_type": "other",
                "actual": 2.68,
                "expected": 2.83,
                "expectation_name": "Q3 EPS",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e10_q3_company_tape",
            "published_at": "2026-09-03T20:00:00+00:00",
            "role": "peer_sector",
            "tags": ["tape", "valuation"],
            "source": "Golden Brain: shares fell 2.74% after Q3 (2026-09-02 session reaction)",
            "item": {
                "kind": "price",
                "event_key": "avgo_q3_post_print_tape",
                "title": "AVGO shares move -2.74% after the latest print",
                "fact": "AVGO -2.74%. MRVL about 0. SOX about 0.",
                "event_type": "other",
                "price_change_pct": -2.74,
                "peers": {"MRVL": 0.2, "SOX": -0.4},
                "fact_reliability": "signal",
            },
        },
        {
            "event_id": "e11_duplicate_demand",
            "published_at": "2026-09-03T21:10:00+00:00",
            "role": "duplicate",
            "tags": ["demand"],
            "source": "Secondary reprint of the Exhibit 99.1 'very strong' sentence",
            "item": {
                "kind": "news",
                "event_key": "avgo_ai_demand_very_strong_q3",
                "title": "Broadcom says demand for AI accelerators and networking continues to be very strong",
                "fact": "Management said demand for AI accelerators and networking continues to be very strong.",
                "url": "https://www.reuters.com/technology/broadcom-ai-demand-very-strong-2026-09-02/",
                "source": "Reuters reprint",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e12_conference_noise",
            "published_at": "2026-09-08T14:00:00+00:00",
            "role": "ordinary_news",
            "tags": ["noise"],
            "source": "Goldman Sachs Communacopia appearance listing",
            "item": {
                "kind": "news",
                "event_key": "avgo_gs_conference_appearance",
                "title": "Broadcom CEO Hock Tan scheduled for Goldman Sachs conference appearance",
                "fact": "Hock Tan will make a conference appearance at the Goldman Sachs Communacopia + Technology Conference. No operating update and no new information.",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e13_xpu_customers",
            "published_at": "2026-09-09T17:00:00+00:00",
            "role": "customer_demand",
            "tags": ["customer", "demand", "ai", "google"],
            "source": "Motley Fool Q3 FY2026 call transcript, 2026-09-09: six XPU customers; FY26 AI 58 vs prior 56",
            "item": {
                "kind": "news",
                "event_key": "avgo_six_xpu_customers_58b",
                "title": "Hock Tan said Broadcom has six XPU customers and fiscal 2026 AI revenue of 58 billion versus prior 56 billion",
                "fact": (
                    "On the call, management said six XPU customers are accelerating custom accelerators. "
                    "Fiscal 2026 AI revenue was described as 58 billion versus the prior 56 billion figure."
                ),
                "url": "https://www.fool.com/earnings/call-transcripts/2026/09/09/broadcom-avgo-q3-2026-earnings-call-transcript/",
                "source": "Motley Fool transcript",
                "event_type": "customer",
                "actual": 58.0,
                "expected": 56.0,
                "expectation_name": "FY2026 AI revenue",
                "entities": ["Google", "Anthropic", "OpenAI", "Meta"],
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e14_google_confirm",
            "published_at": "2026-09-10T16:20:00+00:00",
            "role": "customer_demand",
            "tags": ["google", "customer", "demand"],
            "source": "Known Google TPU/ASIC customer relationship used as a confirmed expansion update",
            "item": {
                "kind": "news",
                "event_key": "google_confirmed_custom_asic_expansion",
                "title": "Google confirmed a Broadcom custom-silicon order expansion for next-generation TPU",
                "fact": (
                    "Google, a named Broadcom customer, confirmed it will expand custom ASIC / TPU "
                    "orders with Broadcom for the next-generation accelerator deployment."
                ),
                "event_type": "customer",
                "entities": ["Google", "Broadcom"],
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e15_google_rumor_again",
            "published_at": "2026-09-11T18:05:00+00:00",
            "role": "rumor",
            "tags": ["google", "customer", "rumor"],
            "source": "Same unconfirmed Google order-cut pattern, later in the window",
            "item": {
                "kind": "rumor",
                "event_key": "google_may_reduce_avgo_orders_rumor",
                "title": "Unconfirmed: Google may reduce Broadcom custom TPU orders",
                "fact": "Rumor that Google may reduce Broadcom ASIC / TPU orders as it expands in-house silicon. The report is unconfirmed.",
                "event_type": "other",
                "entities": ["Google", "Broadcom"],
                "confirmed": False,
                "confidence": "low",
                "fact_reliability": "rumor",
            },
        },
        {
            "event_id": "e16_marvell_win",
            "published_at": "2026-09-12T15:30:00+00:00",
            "role": "competition",
            "tags": ["marvell", "competition", "customer"],
            "source": "Golden claim already cites a hyperscaler awarding custom AI chip work to Marvell",
            "item": {
                "kind": "news",
                "event_key": "marvell_hyperscaler_asic_win",
                "title": "Marvell wins a hyperscaler custom ASIC program Broadcom had been expected to supply",
                "fact": (
                    "Marvell Technology announced a hyperscaler custom ASIC design win. The program "
                    "had been expected to go to Broadcom."
                ),
                "event_type": "competition",
                "entities": ["Marvell", "Broadcom"],
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e17_230b_feature",
            "published_at": "2026-09-14T12:00:00+00:00",
            "role": "ordinary_news",
            "tags": ["ai", "demand"],
            "source": "Golden Brain news title about 2028 AI revenue",
            "item": {
                "kind": "news",
                "event_key": "avgo_230b_ai_2028_feature",
                "title": "Hock Tan Just Guided Broadcom's AI Revenue to Reach $230 Billion by 2028. Should You Believe Him?",
                "fact": "A feature discusses management commentary that AI revenue could reach 230 billion by 2028. It is secondary commentary, not a new filing.",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "opinion",
            },
        },
        {
            "event_id": "e18_unexplained_tape",
            "published_at": "2026-09-16T19:30:00+00:00",
            "role": "unresolved_tape",
            "tags": ["tape"],
            "source": "Golden header price date 2026-09-16; no new operating disclosure in the dump",
            "item": {
                "kind": "price",
                "event_key": "avgo_sept16_tape_no_filing",
                "title": "AVGO shares move -6.2% with no new filing",
                "fact": "Shares moved -6.2% without a new operating disclosure.",
                "event_type": "other",
                "price_change_pct": -6.2,
                "fact_reliability": "signal",
            },
        },
    ]


def _tokens(result: dict[str, Any]) -> dict[str, int]:
    usage = dict(result.get("token_usage") or {})
    calls = list(result.get("llm_calls") or [])
    reasoning = [row for row in calls if str(row.get("role") or "") == "reasoning"]
    critic = [row for row in calls if str(row.get("role") or "") == "critic"]
    def _sum(rows: list[dict[str, Any]], key: str) -> int:
        return sum(int(row.get(key) or 0) for row in rows)
    input_tokens = int(usage.get("input_tokens") or _sum(calls, "input_tokens"))
    output_tokens = int(usage.get("output_tokens") or _sum(calls, "output_tokens"))
    critic_input = int(usage.get("critic_input") or _sum(critic, "input_tokens"))
    critic_output = int(usage.get("critic_output") or _sum(critic, "output_tokens"))
    parts = dict(usage.get("context_parts") or (result.get("snapshot") or {}).get("context_part_tokens") or {})
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "critic_input": critic_input,
        "critic_output": critic_output,
        "total_tokens": int(usage.get("total_tokens") or (input_tokens + output_tokens)),
        "reasoning_input": int(usage.get("reasoning_input") or _sum(reasoning, "input_tokens")),
        "reasoning_output": int(usage.get("reasoning_output") or _sum(reasoning, "output_tokens")),
        "glm53_calls": len(reasoning) + len(critic),
        "glm53_input": int(usage.get("reasoning_input") or _sum(reasoning, "input_tokens")) + critic_input,
        "glm53_output": int(usage.get("reasoning_output") or _sum(reasoning, "output_tokens")) + critic_output,
        "all_input": input_tokens,
        "all_output": output_tokens,
        "context_event": int(parts.get("event") or 0),
        "context_state": int(parts.get("state") or 0),
        "context_evidence": int(parts.get("evidence") or 0),
        "context_causal": int(parts.get("causal") or 0),
        "context_market": int(parts.get("market") or 0),
        "context_history": int(parts.get("history") or 0),
        "context_price": int(parts.get("price") or 0),
    }


def _overconfident(hyps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flags = []
    for row in hyps:
        obs = list(row.get("supporting_observations") or [])
        if str(row.get("confidence") or "") == "high" and str(row.get("status") or "") in {"candidate", "open", "unresolved"} and len(obs) < 2:
            flags.append(
                {
                    "canonical_key": row.get("canonical_key"),
                    "status": row.get("status"),
                    "confidence": row.get("confidence"),
                    "hypothesis": compact_text(row.get("hypothesis") or "", 160),
                    "why": "High confidence with thin supporting observations.",
                }
            )
    return flags


def _uses_history(snapshot: dict[str, Any] | None, leftover: dict[str, Any]) -> dict[str, Any]:
    shot = snapshot or {}
    leftover_ids = set()
    for group, keys in (
        (leftover.get("claims") or [], ("claim_id",)),
        (leftover.get("drivers") or [], ("driver_id", "canonical_key")),
        (leftover.get("evidence") or [], ("id", "evidence_id")),
        (leftover.get("states") or [], ("state_id",)),
        (leftover.get("causal_edges") or [], ("edge_id", "from_node")),
    ):
        for row in group:
            for key in keys:
                if row.get(key):
                    leftover_ids.add(str(row.get(key)))
    retrieved = set()
    for group in (
        shot.get("claims") or [],
        shot.get("drivers") or [],
        shot.get("states") or [],
        shot.get("evidence") or [],
        shot.get("counter_evidence") or [],
        shot.get("causal_edges") or [],
        shot.get("exposures") or [],
        shot.get("hypotheses") or [],
        shot.get("expectations") or [],
    ):
        for row in group:
            if not isinstance(row, dict):
                continue
            for key in ("claim_id", "driver_id", "canonical_key", "state_id", "id", "evidence_id", "edge_id", "from_node", "hypothesis_id", "expectation_id"):
                if row.get(key):
                    retrieved.add(str(row.get(key)))
    hit = leftover_ids & retrieved
    return {
        "used_historical_objects": len(hit),
        "historical_pool": len(leftover_ids),
        "used": bool(hit),
        "sample_ids": sorted(hit)[:8],
    }


def _single_or_multi(now_chain: dict[str, Any] | None) -> str:
    market = (now_chain or {}).get("what_market_is_trading") or {}
    if market.get("unresolved"):
        return "unresolved"
    drivers = list(market.get("candidate_drivers") or [])
    live = [row for row in drivers if str(row.get("status") or "") not in {"retired"}]
    if len(live) >= 2:
        return "multi"
    if len(live) == 1:
        return "single"
    return "none"


def _forced_because(now_chain: dict[str, Any] | None) -> bool:
    text = str(((now_chain or {}).get("answers") or {}).get("what_market_is_trading") or "").lower()
    return "fell because" in text or "下跌因为" in text or "today because" in text


def compact_now(now_chain: dict[str, Any] | None) -> dict[str, Any] | None:
    if not now_chain:
        return None
    market = now_chain.get("what_market_is_trading") or {}
    return {
        "what_happened": compact_text((now_chain.get("answers") or {}).get("what_happened") or "", 240),
        "why_company": compact_text((now_chain.get("answers") or {}).get("why_it_affects_company") or "", 240),
        "path": compact_text((now_chain.get("answers") or {}).get("path_to_driver_claim") or "", 240),
        "market_understands": compact_text((now_chain.get("answers") or {}).get("what_market_is_trading") or "", 400),
        "can_affect_claim": (now_chain.get("path_to_driver_claim") or {}).get("can_affect_claim"),
        "alignment": market.get("alignment"),
        "expectation": market.get("expectation"),
        "attentions": market.get("attentions") or [],
        "candidate_drivers": market.get("candidate_drivers") or [],
        "unresolved": market.get("unresolved"),
        "research_questions": market.get("research_questions") or [],
        "confidence": market.get("confidence"),
        "cannot_conclude_mispricing": market.get("cannot_conclude_mispricing"),
    }


def final_snapshot(store: Any) -> dict[str, Any]:
    def _short(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
        out = []
        for row in rows or []:
            item = {key: row.get(key) for key in keys if key in row}
            if row.get("statement"):
                item["statement"] = compact_text(row.get("statement"), 200)
            if row.get("hypothesis"):
                item["hypothesis"] = compact_text(row.get("hypothesis"), 160)
            if row.get("question"):
                item["question"] = compact_text(row.get("question"), 200)
            out.append(item)
        return out

    return {
        "states": _short(store.list_states(TICKER), "state_id", "name", "direction", "confidence", "statement"),
        "drivers": _short(store.list_drivers(TICKER), "driver_id", "canonical_key", "name", "current_state"),
        "claims": _short(store.list_active_claims(TICKER), "claim_id", "title", "status", "is_core", "statement"),
        "exposures": _short(store.list_exposures(TICKER), "exposure_id", "exposure_type", "subject", "object_name", "reason"),
        "causal_edges": _short(store.list_causal_edges(TICKER), "edge_id", "from_node", "to_node", "status"),
        "expectations": _short(store.list_expectations(TICKER), "expectation_id", "name", "actual", "expected", "comparison", "trend", "confidence"),
        "attentions": _short(store.list_market_attentions(TICKER), "attention_id", "name", "statement"),
        "hypotheses": _short(
            store.list_hypotheses(TICKER),
            "hypothesis_id",
            "canonical_key",
            "kind",
            "status",
            "confidence",
            "hypothesis",
            "supporting_observations",
            "counter_observations",
        ),
        "shadows": _short(store.list_shadows(TICKER), "shadow_id", "name", "status", "statement"),
        "questions": _short(store.list_questions(TICKER), "question_id", "question", "why_it_matters"),
        "counts": {
            "states": len(store.list_states(TICKER)),
            "drivers": len(store.list_drivers(TICKER)),
            "claims": len(store.list_active_claims(TICKER)),
            "exposures": len(store.list_exposures(TICKER)),
            "edges": len(store.list_causal_edges(TICKER)),
            "expectations": len(store.list_expectations(TICKER)),
            "attentions": len(store.list_market_attentions(TICKER)),
            "hypotheses": len(store.list_hypotheses(TICKER)),
            "shadows": len(store.list_shadows(TICKER)),
            "questions": len(store.list_questions(TICKER)),
        },
    }


def _yn(ok: bool) -> str:
    return "是" if ok else "否 / 不完全是"


def write_report(payload: dict[str, Any]) -> str:
    m = payload["metrics"]
    q = payload["review_answers"]
    lines = [
        "# Stock-PM Brain v2 — Phase 0–3 连续功能验证",
        "",
        f"Generated: {payload['generated_at']}",
        f"Ticker: `{payload['ticker']}`",
        f"Window: {payload['window']['start']} → {payload['window']['end']}",
        f"Seed: golden `{payload['seed']['run_id']}` once; events replayed in time order on the same Brain.",
        "",
        "## LLM ping",
        "",
        json.dumps(payload["llm_ping"], ensure_ascii=False, indent=2),
        "",
        "## Metrics",
        "",
        f"- 总 Event 数: {m['events_total']}",
        f"- duplicate stop: {m['duplicate_stop']}",
        f"- non-material stop: {m['non_material_stop']}",
        f"- material incremental: {m['material_incremental']}",
        f"- Full Review 次数: {m['full_review']}",
        f"- GLM-5.3 调用率: {m['glm53_call_rate']}",
        f"- 平均 snapshot objects: {m['avg_snapshot_objects']}",
        f"- 平均 GLM-5.3 tokens (input+output): {m['avg_glm53_tokens']}",
        f"- token input: {m.get('token_input', 0)}",
        f"- token output: {m.get('token_output', 0)}",
        f"- critic input: {m.get('critic_input', 0)}",
        f"- critic output: {m.get('critic_output', 0)}",
        f"- total tokens: {m.get('total_tokens', 0)}",
        f"- context tokens event/state/evidence/causal/market/history: {m.get('context_event', 0)}/{m.get('context_state', 0)}/{m.get('context_evidence', 0)}/{m.get('context_causal', 0)}/{m.get('context_market', 0)}/{m.get('context_history', 0)}",
        f"- context miss (events with miss): {m['context_miss_events']}",
        f"- unexpected Brain write: {m['unexpected_brain_write']}",
        "",
        f"- State changes: {m['state_changes']}",
        f"- Value Driver changes: {m['driver_changes']}",
        f"- Core Claim changes: {m['claim_changes']}",
        f"- Causal Edge changes: {m['edge_changes']}",
        f"- Expectation changes: {m['expectation_changes']}",
        f"- Market Attention changes: {m['attention_changes']}",
        "",
        f"- Hypothesis created: {m['hypothesis_created']}",
        f"- Hypothesis updated: {m['hypothesis_updated']}",
        f"- Hypothesis strengthened: {m['hypothesis_strengthened']}",
        f"- Hypothesis weakened: {m['hypothesis_weakened']}",
        f"- Hypothesis closed: {m['hypothesis_closed']}",
        f"- Average competing hypotheses: {m['avg_competing_hypotheses']}",
        "",
        f"- Successful transmission: {m['successful_transmission']}",
        f"- Blocked transmission: {m['blocked_transmission']}",
        f"- Causal gaps: {m['causal_gaps']}",
        f"- Research Questions: {m['research_questions']}",
        "",
        f"- Price → Fundamental violation: {m['price_fundamental_violations']}",
        f"- Price → Core Claim violation: {m['price_claim_violations']}",
        f"- Unsupported Event → Claim jump: {m['unsupported_event_claim_jump']}",
        "",
        f"- single-hypothesis events: {m['single_hypothesis_events']}",
        f"- multi-hypothesis events: {m['multi_hypothesis_events']}",
        f"- unresolved events: {m['unresolved_events']}",
        "",
        "## Quality scores",
        "",
        f"- Brain Stability (slow writes / ordinary event): {m['brain_stability']}",
        f"- Memory Continuity (material events that retrieved leftover objects): {m['memory_continuity']}",
        f"- Hypothesis Continuity (updates / (updates+new keys)): {m['hypothesis_continuity']}",
        f"- Context Recall (avg): {m['context_recall']}",
        f"- Context Precision (avg): {m['context_precision']}",
        "",
        "## Cognitive Drift",
        "",
    ]
    if payload["cognitive_drift"]:
        for row in payload["cognitive_drift"]:
            lines.append(f"- {row}")
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Runtime anomalies", ""])
    if payload["runtime_anomalies"]:
        for row in payload["runtime_anomalies"]:
            lines.append(f"- {row}")
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Research Questions (graded)", ""])
    for row in payload["research_question_review"]:
        lines.append(f"- [{row['grade']}] {row['question']} — {row['note']}")
    if not payload["research_question_review"]:
        lines.append("- none persisted")
    lines.extend(["", "## Review questions", ""])
    for idx, (key, row) in enumerate(q.items(), start=1):
        lines.append(f"### {idx}. {row['question']}")
        lines.append("")
        lines.append(row["answer"])
        lines.append("")
    lines.extend(["", "## Timeline (compact)", ""])
    for row in payload["timeline"]:
        chain = row.get("now_chain") or {}
        lines.append(f"### {row['event_id']} — {row['published_at']} — `{row['path']}`")
        lines.append("")
        lines.append(f"- title: {row['title']}")
        lines.append(f"- material: {row.get('material')} | glm53: {row.get('glm53_called')} | stopped: {row.get('stopped')}")
        if chain:
            lines.append(f"- 发生了什么: {chain.get('what_happened')}")
            lines.append(f"- 为什么影响公司: {chain.get('why_company')}")
            lines.append(f"- causal path: {chain.get('path')}")
            lines.append(f"- 市场怎么理解: {chain.get('market_understands')}")
        else:
            lines.append("- Now Chain: not produced (see anomalies)")
        lines.append("")
    lines.append("Validation finished. No Phase 4 work. No architecture change. Waiting for review.")
    lines.append("")
    return "\n".join(lines)


def build_review(metrics: dict[str, Any], notes: dict[str, Any]) -> dict[str, Any]:
    slow = metrics["state_changes"] + metrics["driver_changes"] + metrics["claim_changes"] + metrics["edge_changes"]
    fast = metrics["expectation_changes"] + metrics["attention_changes"] + metrics["hypothesis_created"] + metrics["hypothesis_updated"]
    return {
        "noise_stable": {
            "question": "Brain 是否对噪声稳定？",
            "answer": (
                f"普通/噪声事件 {notes['ordinary_events']} 条中，慢变量变化 {notes['ordinary_slow_changes']} 次，"
                f"稳定分 {metrics['brain_stability']}。"
                f"{'普通新闻没有大规模改写 Claim/Driver。' if notes['ordinary_slow_changes'] <= notes['ordinary_events'] else '普通新闻仍触发了偏多的慢变量变化。'}"
            ),
        },
        "sensitive_to_material": {
            "question": "Brain 是否对真正重要的信息敏感？",
            "answer": (
                f"material incremental {metrics['material_incremental']}，Full Review {metrics['full_review']}。"
                f"Expectation 变化 {metrics['expectation_changes']}，Hypothesis 创建/更新 "
                f"{metrics['hypothesis_created']}/{metrics['hypothesis_updated']}。"
                f"{'重要 customer/demand/print 进入了 incremental 或 Full Review。' if metrics['material_incremental'] or metrics['full_review'] else '重要事件没有进入推理路径。'}"
            ),
        },
        "slow_vs_fast": {
            "question": "Slow Brain 是否真的比 Fast Brain 更稳定？",
            "answer": (
                f"慢层变化合计 {slow}（State {metrics['state_changes']} / Driver {metrics['driver_changes']} / "
                f"Claim {metrics['claim_changes']} / Edge {metrics['edge_changes']}）。"
                f"快层变化合计 {fast}（Expectation {metrics['expectation_changes']} / Attention {metrics['attention_changes']} / "
                f"Hypothesis +{metrics['hypothesis_created']}/~{metrics['hypothesis_updated']}）。"
                f"{'快层更敏感、慢层更稳。' if fast >= slow else '快慢层变化幅度接近或慢层并不更稳，这是稳定性问题。'}"
            ),
        },
        "uses_history": {
            "question": "新 Event 是否在利用历史，而不是重新研究？",
            "answer": (
                f"Memory Continuity {metrics['memory_continuity']}。"
                f"{notes['memory_note']}"
            ),
        },
        "causal_constraint": {
            "question": "Causal Graph 是否真实约束了推理？",
            "answer": (
                f"successful {metrics['successful_transmission']} / blocked {metrics['blocked_transmission']} / "
                f"gaps {metrics['causal_gaps']} / unsupported jump {metrics['unsupported_event_claim_jump']}。"
                f"{notes['causal_note']}"
            ),
        },
        "expectation_vs_fundamental": {
            "question": "Expectation 和 Fundamental 是否真的分开？",
            "answer": notes["expectation_note"],
        },
        "hypothesis_evolution": {
            "question": "Market Driver Hypothesis 是否真正会竞争和演化？",
            "answer": (
                f"created {metrics['hypothesis_created']}, updated {metrics['hypothesis_updated']}, "
                f"strengthened {metrics['hypothesis_strengthened']}, weakened {metrics['hypothesis_weakened']}, "
                f"closed {metrics['hypothesis_closed']}, avg competing {metrics['avg_competing_hypotheses']}, "
                f"continuity {metrics['hypothesis_continuity']}。"
                f"{notes['hypothesis_note']}"
            ),
        },
        "can_be_unresolved": {
            "question": "Brain 是否能够承认“目前无法解释”？",
            "answer": (
                f"unresolved events {metrics['unresolved_events']}。"
                f"{'存在 unresolved + Research Question，这是正确结果而不是失败。' if metrics['unresolved_events'] else '窗口内没有明确的 unresolved 承认。'}"
            ),
        },
        "rq_from_gap": {
            "question": "Research Question 是否真的来自认知缺口？",
            "answer": (
                f"共 {metrics['research_questions']} 条。useful {notes['rq_useful']} / mixed {notes['rq_mixed']} / weak {notes['rq_weak']}。"
                f"{notes['rq_note']}"
            ),
        },
        "now_chain_useful": {
            "question": "Now Chain 是否已经能够帮助投资者理解发生了什么、为什么重要、怎么影响投资逻辑、市场可能在交易什么？",
            "answer": notes["now_chain_note"],
        },
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    settings = Settings()
    ping = ping_layers(settings)
    _write("ping.json", ping)

    store, leftover = seed_avgo_brain(golden, include_case_a_original=False)
    seed_meta = {
        "run_id": golden.get("run_id"),
        "states": len(store.list_states(TICKER)),
        "drivers": len(store.list_drivers(TICKER)),
        "claims": len(store.list_active_claims(TICKER)),
        "exposures": len(store.list_exposures(TICKER)),
        "edges": len(store.list_causal_edges(TICKER)),
        "evidence": len(store.list_evidence(TICKER)),
        "events_preloaded": len(store.list_events(TICKER)),
        "news_preloaded": len(store.list_news(TICKER)),
    }
    _write("seed_snapshot.json", {"seed": seed_meta, "leftover_counts": {k: len(v or []) for k, v in leftover.items()}})

    events = timeline()
    timeline_rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    diffs: list[dict[str, Any]] = []
    anomalies: list[str] = []
    drift: list[str] = []
    claim_status_hist: dict[str, list[str]] = {cid: [str((store.claims.get(cid) or {}).get("status") or "")] for cid in store.claims}
    hyp_seen: set[str] = set()
    hyp_new_keys = 0
    hyp_update_events = 0
    ordinary_events = 0
    ordinary_slow = 0
    memory_hits = 0
    memory_denom = 0
    recall_vals: list[float] = []
    precision_vals: list[float] = []
    competing_vals: list[int] = []
    snapshot_sizes: list[int] = []
    glm53_token_vals: list[int] = []
    overconfident: list[dict[str, Any]] = []
    rq_review: list[dict[str, Any]] = []
    seen_rq: set[str] = set()

    metrics = {
        "events_total": 0,
        "duplicate_stop": 0,
        "non_material_stop": 0,
        "material_incremental": 0,
        "full_review": 0,
        "glm53_called": 0,
        "glm53_call_rate": 0.0,
        "avg_snapshot_objects": 0,
        "avg_glm53_tokens": 0,
        "token_input": 0,
        "token_output": 0,
        "critic_input": 0,
        "critic_output": 0,
        "total_tokens": 0,
        "context_event": 0,
        "context_state": 0,
        "context_evidence": 0,
        "context_causal": 0,
        "context_market": 0,
        "context_history": 0,
        "context_price": 0,
        "context_miss_events": 0,
        "unexpected_brain_write": 0,
        "state_changes": 0,
        "driver_changes": 0,
        "claim_changes": 0,
        "edge_changes": 0,
        "expectation_changes": 0,
        "attention_changes": 0,
        "hypothesis_created": 0,
        "hypothesis_updated": 0,
        "hypothesis_strengthened": 0,
        "hypothesis_weakened": 0,
        "hypothesis_closed": 0,
        "avg_competing_hypotheses": 0,
        "successful_transmission": 0,
        "blocked_transmission": 0,
        "causal_gaps": 0,
        "research_questions": 0,
        "price_fundamental_violations": 0,
        "price_claim_violations": 0,
        "unsupported_event_claim_jump": 0,
        "single_hypothesis_events": 0,
        "multi_hypothesis_events": 0,
        "unresolved_events": 0,
        "brain_stability": None,
        "memory_continuity": None,
        "hypothesis_continuity": None,
        "context_recall": None,
        "context_precision": None,
    }

    prev = brain_index(store)
    prev_hyps = _hyp_by_key(store)
    claim_start = {cid: deepcopy(row) for cid, row in prev["claims"].items()}
    state_start = {sid: deepcopy(row) for sid, row in prev["states"].items()}

    for spec in events:
        metrics["events_total"] += 1
        item = dict(spec["item"])
        item["published_at"] = spec["published_at"]
        item["event_id"] = spec["event_id"]
        before = brain_index(store)
        before_hyps = _hyp_by_key(store)
        result: dict[str, Any] = {}
        try:
            result = run_brain_update(ticker=TICKER, item=item, store=store)
        except Exception as exc:  # noqa: BLE001 — validation must keep going
            anomalies.append(f"{spec['event_id']}: exception {exc}")
            result = {"path": "error", "error": str(exc), "stopped": True, "llm_calls": []}
            traceback.print_exc()

        after = brain_index(store)
        after_hyps = _hyp_by_key(store)
        delta = diff_brain(before, after)
        diffs.append({"event_id": spec["event_id"], "diff": delta})
        path = str(result.get("path") or "")
        if path == "l0_stop" or result.get("duplicate"):
            metrics["duplicate_stop"] += 1
        elif path == "observation_memory" or result.get("stop_reason") == "non_material":
            metrics["non_material_stop"] += 1
        elif result.get("full_review"):
            metrics["full_review"] += 1
            if not result.get("now_chain"):
                anomalies.append(f"{spec['event_id']}: Full Review path produced no Now Chain and did not run incremental reasoning.")
        elif path == "incremental" and result.get("material"):
            metrics["material_incremental"] += 1

        if result.get("glm53_called"):
            metrics["glm53_called"] += 1
        tokens = _tokens(result)
        if tokens["glm53_input"] or tokens["glm53_output"]:
            glm53_token_vals.append(tokens["glm53_input"] + tokens["glm53_output"])
        metrics["token_input"] += tokens.get("input_tokens") or 0
        metrics["token_output"] += tokens.get("output_tokens") or 0
        metrics["critic_input"] += tokens.get("critic_input") or 0
        metrics["critic_output"] += tokens.get("critic_output") or 0
        metrics["total_tokens"] += tokens.get("total_tokens") or 0
        metrics["context_event"] += tokens.get("context_event") or 0
        metrics["context_state"] += tokens.get("context_state") or 0
        metrics["context_evidence"] += tokens.get("context_evidence") or 0
        metrics["context_causal"] += tokens.get("context_causal") or 0
        metrics["context_market"] += tokens.get("context_market") or 0
        metrics["context_history"] += tokens.get("context_history") or 0
        metrics["context_price"] += tokens.get("context_price") or 0
        for row in store.list_expectations(TICKER):
            if row.get("expected") is None and str(row.get("comparison") or "") in {"above", "in_line", "below"}:
                anomalies.append(f"{spec['event_id']}: expectation {row.get('name')} has expected=None with comparison={row.get('comparison')}")
        shot = result.get("snapshot") or {}
        snapshot_sizes.append(
            len(shot.get("states") or [])
            + len(shot.get("drivers") or [])
            + len(shot.get("claims") or [])
            + len(shot.get("exposures") or [])
            + len(shot.get("evidence") or [])
            + len(shot.get("causal_edges") or [])
            + len(shot.get("expectations") or [])
            + len(shot.get("hypotheses") or [])
        )

        market_stats = result.get("market_layer") or {}
        metrics["price_fundamental_violations"] += int(market_stats.get("price_fundamental_violations") or 0)
        metrics["price_claim_violations"] += int(market_stats.get("price_claim_violations") or 0)
        metrics["unsupported_event_claim_jump"] += int(result.get("unsupported_jump_count") or 0)
        metrics["successful_transmission"] += int((result.get("transmission") or {}).get("successful_count") or 0)
        metrics["blocked_transmission"] += int((result.get("transmission") or {}).get("blocked_count") or 0)
        metrics["causal_gaps"] += len(result.get("causal_gaps") or [])

        metrics["state_changes"] += len(delta["states"])
        metrics["driver_changes"] += len(delta["drivers"])
        metrics["claim_changes"] += len(delta["claims"])
        metrics["edge_changes"] += len(delta["edges"])
        metrics["expectation_changes"] += len(delta["expectations"])
        metrics["attention_changes"] += len(delta["attentions"])

        created_keys = set(after_hyps) - set(before_hyps)
        updated_keys = []
        for key, row in after_hyps.items():
            prev_row = before_hyps.get(key)
            if prev_row and (
                prev_row.get("status") != row.get("status")
                or prev_row.get("confidence") != row.get("confidence")
                or prev_row.get("supporting_observations") != row.get("supporting_observations")
                or prev_row.get("counter_observations") != row.get("counter_observations")
            ):
                updated_keys.append(key)
                if _STATUS_RANK.get(str(row.get("status") or ""), 0) > _STATUS_RANK.get(str(prev_row.get("status") or ""), 0):
                    metrics["hypothesis_strengthened"] += 1
                elif str(row.get("status") or "") == "weakened" and str(prev_row.get("status") or "") != "weakened":
                    metrics["hypothesis_weakened"] += 1
                if str(row.get("status") or "") in {"retired", "closed"} and str(prev_row.get("status") or "") not in {"retired", "closed"}:
                    metrics["hypothesis_closed"] += 1
        metrics["hypothesis_created"] += len(created_keys)
        metrics["hypothesis_updated"] += len(updated_keys)
        if created_keys:
            hyp_new_keys += len(created_keys)
        if updated_keys:
            hyp_update_events += 1
        hyp_seen |= set(after_hyps)
        competing_vals.append(len([row for row in after_hyps.values() if str(row.get("status") or "") not in {"retired"}]))

        gate = result.get("gate") or {}
        for row in gate.get("approved") or []:
            kind = str(row.get("object_type") or "")
            source = str(row.get("source_kind") or "")
            layer = OBJECT_LAYER.get(kind, "observation")
            if source in {"price", "rumor"} and kind in {"state", "company_state", "claim", "core_claim", "driver", "value_driver"}:
                metrics["unexpected_brain_write"] += 1
                anomalies.append(f"{spec['event_id']}: unexpected {source} write to {kind}")
            if spec["role"] in {"ordinary_news", "duplicate"} and kind in SLOW_TYPES:
                ordinary_slow += 1
                drift.append(f"{spec['event_id']}: ordinary/noise event wrote slow object {kind}")

        if spec["role"] in {"ordinary_news", "duplicate"}:
            ordinary_events += 1

        now_chain = result.get("now_chain")
        kind = _single_or_multi(now_chain)
        if kind == "single":
            metrics["single_hypothesis_events"] += 1
        elif kind == "multi":
            metrics["multi_hypothesis_events"] += 1
        elif kind == "unresolved":
            metrics["unresolved_events"] += 1
        if _forced_because(now_chain):
            anomalies.append(f"{spec['event_id']}: Now Chain collapsed into a single 'fell because' sentence.")
        overconfident.extend(_overconfident(store.list_hypotheses(TICKER)))

        if path == "incremental" and result.get("material"):
            memory_denom += 1
            hist = _uses_history(shot, leftover)
            if hist["used"]:
                memory_hits += 1
            expected = expected_for(spec)
            if any(expected.get(key) for key in ("drivers", "claims", "support_evidence", "counter_evidence")):
                score = score_snapshot_context(snapshot=shot, expected=expected, irrelevant=IRRELEVANT_CDE)
                if score.get("context_recall") is not None:
                    recall_vals.append(float(score["context_recall"]))
                if score.get("context_precision") is not None:
                    precision_vals.append(float(score["context_precision"]))
                misses = find_context_misses(event=item, snapshot=shot, expected=expected)
                if misses:
                    metrics["context_miss_events"] += 1
            else:
                score = {}
                misses = []
        else:
            hist = {"used": False, "used_historical_objects": 0}
            score = {}
            misses = []

        for row in store.list_questions(TICKER):
            q = str(row.get("question") or "")
            if q and q not in seen_rq:
                seen_rq.add(q)
                rq_review.append(classify_rq(q))
        metrics["research_questions"] = len(seen_rq)

        for cid, row in after["claims"].items():
            claim_status_hist.setdefault(cid, []).append(str(row.get("status") or ""))

        if spec["role"] == "expectation_print":
            exp_rows = store.list_expectations(TICKER)
            claim_changed = any(row["action"] == "updated" for row in delta["claims"])
            state_changed = any(row["action"] == "updated" for row in delta["states"])
            notes_flag = {
                "event_id": spec["event_id"],
                "expectations": [
                    {"name": row.get("name"), "comparison": row.get("comparison"), "trend": row.get("trend"), "actual": row.get("actual"), "expected": row.get("expected")}
                    for row in exp_rows
                ],
                "claim_changed": claim_changed,
                "state_changed": state_changed,
            }
            _write(f"expectation_case_{spec['event_id']}.json", notes_flag)

        row_out = {
            "event_id": spec["event_id"],
            "published_at": spec["published_at"],
            "role": spec["role"],
            "title": item.get("title"),
            "source": spec.get("source"),
            "path": path,
            "full_review": bool(result.get("full_review")),
            "stopped": bool(result.get("stopped")),
            "stop_reason": result.get("stop_reason"),
            "material": result.get("material"),
            "glm52_called": result.get("glm52_called"),
            "glm53_called": result.get("glm53_called"),
            "core_claims_unchanged": result.get("core_claims_unchanged"),
            "current_state_unchanged": result.get("current_state_unchanged"),
            "now_chain": compact_now(now_chain),
            "market_layer": market_stats,
            "transmission": {
                "successful": (result.get("transmission") or {}).get("successful_count"),
                "blocked": (result.get("transmission") or {}).get("blocked_count"),
            },
            "causal_gaps": result.get("causal_gaps") or [],
            "questions": result.get("questions") or [],
            "memory": hist,
            "context_score": {k: score.get(k) for k in ("context_recall", "context_precision", "missed_count", "irrelevant_count")} if score else {},
            "context_misses": misses,
            "diff_counts": {k: len(v) for k, v in delta.items()},
            "tokens": tokens,
            "hypothesis_keys_after": sorted(after_hyps),
        }
        timeline_rows.append(row_out)
        traces.append(
            {
                "event_id": spec["event_id"],
                "trace": result.get("trace"),
                "llm_calls": result.get("llm_calls") or [],
                "token_usage": result.get("token_usage") or {},
                "l0": result.get("l0"),
                "extract": result.get("extract"),
                "error": result.get("error"),
            }
        )
        print(
            f"[{spec['event_id']}] path={path} material={result.get('material')} glm53={result.get('glm53_called')} "
            f"hyps={len(after_hyps)} exp={len(store.list_expectations(TICKER))}",
            flush=True,
        )
        prev = after
        prev_hyps = after_hyps

    for cid, hist in claim_status_hist.items():
        uniq = [item for item in hist if item]
        flips = sum(1 for idx in range(1, len(uniq)) if uniq[idx] != uniq[idx - 1])
        if flips >= 2:
            drift.append(f"Core Claim {cid} flipped status {flips} times: {uniq}")

    if metrics["material_incremental"]:
        metrics["glm53_call_rate"] = round(metrics["glm53_called"] / max(metrics["material_incremental"], 1), 4)
    metrics["avg_snapshot_objects"] = round(sum(snapshot_sizes) / max(len(snapshot_sizes), 1), 2)
    metrics["avg_glm53_tokens"] = round(sum(glm53_token_vals) / max(len(glm53_token_vals), 1), 2) if glm53_token_vals else 0
    metrics["avg_competing_hypotheses"] = round(sum(competing_vals) / max(len(competing_vals), 1), 2)
    metrics["brain_stability"] = round(1 - min(ordinary_slow / max(ordinary_events, 1), 1), 4) if ordinary_events else None
    metrics["memory_continuity"] = round(memory_hits / max(memory_denom, 1), 4) if memory_denom else None
    denom = hyp_update_events + hyp_new_keys
    metrics["hypothesis_continuity"] = round(hyp_update_events / denom, 4) if denom else None
    metrics["context_recall"] = round(sum(recall_vals) / len(recall_vals), 4) if recall_vals else None
    metrics["context_precision"] = round(sum(precision_vals) / len(precision_vals), 4) if precision_vals else None

    # Dedup overconfident flags
    seen_oc = set()
    unique_oc = []
    for row in overconfident:
        key = (row.get("canonical_key"), row.get("confidence"), row.get("status"))
        if key in seen_oc:
            continue
        seen_oc.add(key)
        unique_oc.append(row)

    rq_counts = {"useful": 0, "mixed": 0, "weak": 0}
    for row in rq_review:
        rq_counts[str(row.get("grade") or "mixed")] = rq_counts.get(str(row.get("grade") or "mixed"), 0) + 1

    exp_sep = []
    for spec in events:
        if spec["role"] != "expectation_print":
            continue
        path = next((row for row in timeline_rows if row["event_id"] == spec["event_id"]), {})
        exp_sep.append(
            {
                "event_id": spec["event_id"],
                "expectation": (path.get("now_chain") or {}).get("expectation"),
                "core_claims_unchanged": path.get("core_claims_unchanged"),
                "current_state_unchanged": path.get("current_state_unchanged"),
            }
        )
    claim_end = {row.get("claim_id"): row for row in store.list_active_claims(TICKER)}
    unchanged_core = all(
        str((claim_end.get(cid) or {}).get("status") or "") == str((claim_start.get(cid) or {}).get("status") or "")
        for cid in claim_start
    )
    notes = {
        "ordinary_events": ordinary_events,
        "ordinary_slow_changes": ordinary_slow,
        "memory_note": (
            f"{memory_hits}/{memory_denom} 个 material incremental 事件的 snapshot 含有 seed 阶段已有对象。"
            if memory_denom
            else "没有 material incremental 事件可评估历史召回。"
        ),
        "causal_note": (
            "Golden graph 主要是 Driver→Claim。若 blocked/gap 多而 successful 少，说明连续环境里 Causal Brain 更多是在停写，而不是送完整路径。"
            if metrics["blocked_transmission"] or metrics["causal_gaps"]
            else "本窗口几乎没有 blocked transmission / gap，约束可能偏弱，或事件没有碰到不完整路径。"
        ),
        "expectation_note": (
            f"Print-vs-expect 事件: {exp_sep}. "
            f"期末 Core Claim status 相对 seed {'未变' if unchanged_core else '已变'}。"
            "Q2 AI 16 vs 17.2 与 Q3 EPS 2.68 vs 2.83 是 Fundamental 仍可偏正、Expectation 下降的真实样本。"
        ),
        "hypothesis_note": (
            "若 updated 远小于 created，说明 Market Memory 仍在重复建假设。"
            if metrics["hypothesis_updated"] < metrics["hypothesis_created"]
            else "已有 hypothesis 被更新，不是每次只新建。"
        ),
        "rq_useful": rq_counts["useful"],
        "rq_mixed": rq_counts["mixed"],
        "rq_weak": rq_counts["weak"],
        "rq_note": "弱问题是泛问；有用问题应点名客户、路径或 expectation gap。",
        "now_chain_note": (
            f"{sum(1 for row in timeline_rows if row.get('now_chain'))}/{len(timeline_rows)} 条事件产出了 Now Chain。"
            f" Full Review 与 Incremental 写入同一 Brain，并都应产出 Now Chain。"
            f" multi={metrics['multi_hypothesis_events']} single={metrics['single_hypothesis_events']} unresolved={metrics['unresolved_events']}。"
        ),
    }
    review = build_review(metrics, notes)
    report = {
        "generated_at": _now(),
        "ticker": TICKER,
        "phase": "phase0-3-e2e",
        "window": {"start": events[0]["published_at"], "end": events[-1]["published_at"], "event_count": len(events)},
        "seed": seed_meta,
        "llm_ping": ping,
        "metrics": metrics,
        "quality_notes": notes,
        "review_answers": review,
        "cognitive_drift": drift,
        "runtime_anomalies": anomalies,
        "overconfident_hypotheses": unique_oc,
        "research_question_review": rq_review,
        "expectation_separation_cases": exp_sep,
        "timeline": timeline_rows,
    }
    _write("timeline.json", timeline_rows)
    _write("diffs.json", diffs)
    _write("traces.json", traces)
    _write("metrics.json", metrics)
    _write("final_brain.json", final_snapshot(store))
    _write("context_miss.json", [row for row in timeline_rows if row.get("context_misses")])
    _write("cognitive_drift.json", drift)
    _write("runtime_anomalies.json", anomalies)
    _write("research_questions.json", rq_review)
    _write("report.json", report)
    md = write_report(report)
    _write("REPORT.md", md)
    print(md)
    return 0


_STATUS_RANK = {
    "closed": 0,
    "retired": 0,
    "unresolved": 1,
    "candidate": 2,
    "weakened": 3,
    "open": 4,
    "supported": 5,
}


if __name__ == "__main__":
    raise SystemExit(main())
