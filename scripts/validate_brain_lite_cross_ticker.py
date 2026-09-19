#!/usr/bin/env python3
"""LITE Cold-Start Bootstrap then the same frozen 18-event tape.

Empty Brain. Bootstrap from research-pack Evidence (not the first event).
Then incremental replay. No LITE-specific rules, no seeded drivers/claims/graph.
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from stock_pm.brain.bootstrap import bootstrap_brain, brain_has_baseline
from stock_pm.brain.context_miss import find_context_misses, score_snapshot_context
from stock_pm.brain.runtime import run_brain_update
from stock_pm.brain.store import BrainStore
from stock_pm.brain.routing import brain_completers
from stock_pm.config import Settings
from stock_pm.research.llm_reason import compact_text
from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService
from stock_pm.research.sources import DictPackSource

from validate_brain_phase03_e2e import (
    SLOW_TYPES,
    _tokens,
    compact_now,
    diff_brain,
)
from validate_brain_runtime import ping_layers

OUT = Path("artifacts/brain_lite_cross_ticker")
TICKER = "LITE"
AVGO_BRAIN = ROOT / "artifacts/brain_token_stabilization/after_run/final_brain.json"
AVGO_METRICS = ROOT / "artifacts/brain_token_stabilization/after_metrics.json"

AVGO_OVERFIT_TERMS = (
    "custom asic",
    "custom silicon",
    "google tpu",
    "google order",
    "xpu customer",
    "broadcom",
    " avgo",
    "marvell custom",
    "ai semiconductor duration",
    "ai semiconductor demand durability",
    "ai revenue mix concentration",
)

REVIEW_REFERENCE = (
    "ai datacenter",
    "cloud datacenter",
    "optical",
    "datacom",
    "transceiver",
    "pump laser",
    "cpo",
    "ocs",
    "capacity",
    "indium phosphide",
    "inp",
    "pricing",
    "gross margin",
    "product mix",
    "cloud light",
    "1.6t",
    "800g",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _public_history_pack() -> dict[str, Any]:
    """Historical Evidence for bootstrap. Not a seeded Driver / Claim / Graph."""
    return {
        "ticker": TICKER,
        "template_id": "optical",
        "is_fixture": False,
        "source": "public_filings",
        "company_profile": {
            "legal_name": "Lumentum Holdings Inc.",
            "cik": "0001633978",
            "fiscal_year_end_month": 6,
            "sector": "光通信",
            "revenue_ttm": 1_645_000_000,
            "gross_margin_pct": 35.0,
            "operating_margin_pct": 10.0,
        },
        "earnings_history": [
            {
                "report_date": "2025-05-07",
                "period_end": "2025-03-29",
                "fiscal_year": 2025,
                "fiscal_period": "Q3",
                "revenue": 425_200_000,
                "source": "derived from Q3 FY2026 Exhibit 99.1 YoY +90.1% on $808.4M",
            }
        ],
        "official_documents": [
            {
                "title": "Lumentum Form 10-K business description",
                "published_at": "2025-08-22",
                "source": "sec.gov",
                "form": "10-K",
                "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001633978",
                "excerpt": (
                    "Lumentum Holdings Inc. is a provider of optical and photonic products "
                    "that enable optical networking and laser applications. The company sells "
                    "components, modules, and subsystems used in telecommunications and "
                    "datacom networks, including lasers and transceivers that carry traffic "
                    "inside and between data centers, as well as commercial lasers for "
                    "industrial and manufacturing uses."
                ),
            }
        ],
        "guidance_history": [
            {
                "text": "Management has described datacom and cloud optical demand as a growing share of the optical product mix, while manufacturing capacity and component supply remain operating constraints.",
                "source": "prior transcripts / 10-K",
                "published_at": "2025-08-22",
            }
        ],
        "missing_fields": ["fcf", "segment_growth"],
    }


def _make_research() -> tuple[Any, BrainStore, dict[str, Any]]:
    """Fresh in-memory Brain. Research pack is public Evidence, not a seeded Brain."""
    meta: dict[str, Any] = {"live_db": False, "fetch_live": False, "seeded_brain_objects": False}
    pack = _public_history_pack()
    source = DictPackSource.from_mapping(TICKER, pack)
    research = ResearchService(InMemoryResearchStore(), pack_source=source)
    research.ensure_issuer(
        TICKER,
        legal_name="Lumentum Holdings Inc.",
        cik="0001633978",
        sector="光通信",
        fiscal_year_end_month=6,
    )
    research.store.upsert_pack(pack)
    for doc in pack.get("official_documents") or []:
        try:
            research.create_evidence(
                TICKER,
                {
                    "evidence_type": "filing",
                    "fact": doc.get("excerpt"),
                    "excerpt": doc.get("excerpt"),
                    "source": doc.get("source") or "sec.gov",
                    "source_url": doc.get("url"),
                    "source_time": doc.get("published_at"),
                    "retrieved_at": _now(),
                    "source_type": "sec_filing",
                    "importance": "high",
                },
                actor="bootstrap",
            )
        except Exception:
            continue
    return research, BrainStore(), meta


def _object_signature(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("status") or ""),
        compact_text(row.get("statement") or row.get("current_state") or row.get("mechanism") or "", 80),
        str(row.get("confidence") or row.get("support_strength") or ""),
    )


def continuity_delta(prior: dict[str, Any], after: dict[str, Any], bootstrap: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kind, key in (
        ("states", "states"),
        ("drivers", "drivers"),
        ("claims", "claims"),
        ("edges", "edges"),
    ):
        before = prior.get(kind) or {}
        now = after.get(kind) or {}
        boot = bootstrap.get(kind) or {}
        created = [token for token in now if token not in before]
        reused = [token for token in now if token in boot]
        updated = [
            token
            for token in now
            if token in before and _object_signature(now[token]) != _object_signature(before[token])
        ]
        out[kind] = {
            "created": len(created),
            "updated": len(updated),
            "reused_bootstrap": len(reused),
            "bootstrap_pool": len(boot),
            "created_ids": created[:6],
            "updated_ids": updated[:6],
        }
    return out


def _write(name: str, payload: object) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    if name.endswith(".md"):
        path.write_text(str(payload), encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print("wrote", path, flush=True)
    return path


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
        "exposures": _map(store.list_exposures(TICKER), "exposure_id"),
        "expectations": _map(store.list_expectations(TICKER), "expectation_id", "name"),
        "attentions": _map(store.list_market_attentions(TICKER), "attention_id", "name"),
        "hypotheses": _map(store.list_hypotheses(TICKER), "hypothesis_id"),
        "shadows": _map(store.list_shadows(TICKER), "shadow_id"),
        "questions": _map(store.list_questions(TICKER), "question_id"),
        "divergences": _map(store.list_divergences(TICKER), "divergence_id") if hasattr(store, "list_divergences") else {},
    }


def _hyp_by_key(store: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in store.list_hypotheses(TICKER):
        out[str(row.get("canonical_key") or row.get("hypothesis_id"))] = row
    return out


def _tokens_of(text: str) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9]{4,}", (text or "").lower())}


def expected_from_formed(event: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    """Retrieval target = already-formed objects that overlap this event. Not a pre-written LITE graph."""
    blob = f"{event.get('title') or ''} {event.get('fact') or ''} {event.get('statement') or ''}"
    event_tokens = _tokens_of(blob)
    spec: dict[str, list[str]] = {"drivers": [], "claims": [], "states": [], "support_evidence": []}
    if len(event_tokens) < 2:
        return spec
    for kind, key, fields in (
        ("states", "state_id", ("name", "statement")),
        ("drivers", "driver_id", ("name", "canonical_key", "current_state")),
        ("claims", "claim_id", ("title", "statement")),
    ):
        for row in (prior.get(kind) or {}).values():
            hay = " ".join(str(row.get(field) or "") for field in fields)
            if len(event_tokens & _tokens_of(hay)) >= 2 and row.get(key):
                spec[kind if kind != "states" else "states"].append(str(row.get(key)))
    spec["states"] = list(dict.fromkeys(spec["states"]))
    spec["drivers"] = list(dict.fromkeys(spec["drivers"]))
    spec["claims"] = list(dict.fromkeys(spec["claims"]))
    return spec


def leftover_from_index(prior: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        "claims": list((prior.get("claims") or {}).values()),
        "drivers": list((prior.get("drivers") or {}).values()),
        "states": list((prior.get("states") or {}).values()),
        "causal_edges": list((prior.get("edges") or {}).values()),
        "evidence": [],
    }


def _uses_history(snapshot: dict[str, Any] | None, leftover: dict[str, Any]) -> dict[str, Any]:
    shot = snapshot or {}
    leftover_ids = set()
    for group, keys in (
        (leftover.get("claims") or [], ("claim_id",)),
        (leftover.get("drivers") or [], ("driver_id", "canonical_key")),
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
        shot.get("causal_edges") or [],
        shot.get("exposures") or [],
        shot.get("hypotheses") or [],
        shot.get("expectations") or [],
    ):
        for row in group:
            if not isinstance(row, dict):
                continue
            for key in ("claim_id", "driver_id", "canonical_key", "state_id", "id", "evidence_id", "edge_id", "from_node"):
                if row.get(key):
                    retrieved.add(str(row.get(key)))
    hit = leftover_ids & retrieved
    return {
        "used_historical_objects": len(hit),
        "historical_pool": len(leftover_ids),
        "used": bool(hit),
        "sample_ids": sorted(hit)[:8],
    }


def timeline() -> list[dict[str, Any]]:
    """Documented LITE window 2026-05-05 → 2026-09-16. Public facts only."""
    return [
        {
            "event_id": "e01_q3_filing",
            "published_at": "2026-05-05T21:05:00+00:00",
            "role": "earnings",
            "source": "Lumentum Q3 FY2026 Exhibit 99.1, 2026-05-05",
            "item": {
                "kind": "filing",
                "event_key": "lite_q3_fy2026_release",
                "title": "Lumentum reports fiscal Q3 FY2026 results",
                "fact": (
                    "Q3 FY2026 net revenue was $808.4 million, up 21.5% sequentially and 90.1% year over year. "
                    "GAAP gross margin was 44.2% and non-GAAP gross margin was 47.9%. "
                    "GAAP operating margin was 21.6% and non-GAAP operating margin was 32.2%. "
                    "GAAP diluted EPS was $1.50; non-GAAP diluted EPS was $2.37. "
                    "Components revenue was $533.3 million; systems revenue was $275.1 million. "
                    "Management guided Q4 FY2026 revenue to $960 million to $1.01 billion."
                ),
                "url": "https://www.sec.gov/Archives/edgar/data/1633978/000162828026030530/lite_ex991xq3fy26.htm",
                "source": "Lumentum IR / SEC Exhibit 99.1",
                "event_type": "earnings",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Lumentum"],
            },
        },
        {
            "event_id": "e02_q3_print_vs_expect",
            "published_at": "2026-05-05T22:10:00+00:00",
            "role": "expectation_print",
            "source": "Company print vs street EPS cited in prior LITE pack: $1.50 vs $1.81",
            "item": {
                "kind": "news",
                "event_key": "lite_q3_gaap_eps_vs_street",
                "title": "LITE GAAP EPS printed 1.50 versus street 1.81",
                "fact": (
                    "GAAP diluted EPS printed $1.50 versus street $1.81. "
                    "Revenue printed $808.4 million. Non-GAAP EPS was $2.37."
                ),
                "source": "Company print / consensus comparison already in the public pack",
                "event_type": "other",
                "actual": 1.50,
                "expected": 1.81,
                "expectation_name": "Q3 GAAP EPS",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Lumentum"],
            },
        },
        {
            "event_id": "e03_q3_tape",
            "published_at": "2026-05-06T20:00:00+00:00",
            "role": "peer_sector",
            "source": "Prior LITE pack: Q3 miss next-day -5.06% after a +25.68% five-day run",
            "item": {
                "kind": "price",
                "event_key": "lite_q3_post_print_tape",
                "title": "LITE shares move -5.06% after the Q3 print",
                "fact": "LITE -5.06% the next session after the Q3 print, following a +25.68% five-day run into the report.",
                "event_type": "other",
                "price_change_pct": -5.06,
                "peers": {"COHR": -2.1, "FN": -1.4, "SOXX": -1.8},
                "fact_reliability": "signal",
            },
        },
        {
            "event_id": "e04_q3_call_cloud",
            "published_at": "2026-05-06T22:00:00+00:00",
            "role": "customer_demand",
            "source": "Q3 FY2026 call transcript, 2026-05-05/06",
            "item": {
                "kind": "news",
                "event_key": "lite_q3_cloud_transceivers",
                "title": "Lumentum said cloud transceiver shipments rose more than 40% sequentially and remain below customer demand",
                "fact": (
                    "Systems revenue reached $275 million, up 24% sequentially and 121% year over year. "
                    "Cloud transceivers accounted for most of that growth, increasing over 40% sequentially "
                    "as the company used expanded manufacturing in Thailand. Management said it is poised to "
                    "ramp 1.6T-speed transceiver shipments in fiscal Q4. Supply constraints on critical "
                    "components keep shipments well below customer demand."
                ),
                "url": "https://www.theglobeandmail.com/investing/markets/stocks/LITE-Q/pressreleases/1746649/lumentum-lite-q3-2026-earnings-transcript/",
                "source": "Q3 FY2026 call transcript",
                "event_type": "customer",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Lumentum", "Thailand"],
            },
        },
        {
            "event_id": "e05_q3_call_capacity",
            "published_at": "2026-05-06T22:30:00+00:00",
            "role": "capacity_supply",
            "source": "Q3 FY2026 call: InP/EML shortage and mix commentary",
            "item": {
                "kind": "news",
                "event_key": "lite_q3_inp_capacity",
                "title": "Lumentum said indium phosphide and EML demand exceeds supply by more than 30%",
                "fact": (
                    "Management said EML and indium phosphide demand exceeds supply by more than 30%, "
                    "and Japan wafer fabrication capacity is fully allocated. Margin mix was aided by "
                    "laser chips, pump lasers, and narrow linewidth laser assemblies. Co-packaged optics "
                    "and optical circuit switches were described as beginning to contribute."
                ),
                "source": "Q3 FY2026 call",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Lumentum"],
            },
        },
        {
            "event_id": "e06_noise_etf",
            "published_at": "2026-06-16T14:00:00+00:00",
            "role": "ordinary_news",
            "source": "Existing LITE news corpus: IYZ ETF outflow alert",
            "item": {
                "kind": "news",
                "event_key": "lite_iyz_etf_outflow",
                "title": "IYZ, CHTR, MSI, LITE: ETF Outflow Alert",
                "fact": "An ETF outflow alert lists LITE among IYZ holdings. No new operating disclosure.",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e07_cpo_rumor",
            "published_at": "2026-07-14T16:00:00+00:00",
            "role": "rumor",
            "source": "Unconfirmed CPO-displacement rumor pattern used in prior LITE counter-search, not issuer-confirmed",
            "item": {
                "kind": "rumor",
                "event_key": "lite_cpo_displaces_transceivers_rumor",
                "subject": "CPO versus pluggable transceivers",
                "title": "Unconfirmed rumor that co-packaged optics will displace Lumentum pluggable transceiver demand",
                "fact": (
                    "An unconfirmed rumor says co-packaged optics will displace pluggable transceiver demand "
                    "and reduce Lumentum cloud-module volume."
                ),
                "event_type": "other",
                "entities": ["Lumentum"],
                "confirmed": False,
                "confidence": "low",
                "fact_reliability": "rumor",
            },
        },
        {
            "event_id": "e08_noise_token",
            "published_at": "2026-07-22T13:00:00+00:00",
            "role": "ordinary_news",
            "source": "Existing LITE news corpus",
            "item": {
                "kind": "news",
                "event_key": "lite_liteon_token_feature",
                "title": "What Is Lumentum Holdings (LITE) Stock Tied Token LITEON Really About?",
                "fact": "A feature discusses a stock-tied token. No issuer operating disclosure.",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e09_q4_filing",
            "published_at": "2026-08-11T21:05:00+00:00",
            "role": "earnings",
            "source": "Lumentum Q4 FY2026 Exhibit 99.1, 2026-08-11",
            "item": {
                "kind": "filing",
                "event_key": "lite_q4_fy2026_release",
                "title": "Lumentum reports fiscal Q4 and full-year FY2026 results",
                "fact": (
                    "Q4 FY2026 net revenue was $1.0063 billion, up 24.5% sequentially and 109.3% year over year. "
                    "GAAP gross margin was 47.4% and non-GAAP gross margin was 50.4%. "
                    "GAAP operating margin was 27.8% and non-GAAP operating margin was 36.6%. "
                    "Non-GAAP diluted EPS was $3.23. GAAP net loss was driven by a one-time non-cash "
                    "$7.8 billion loss on convertible-note equitization. "
                    "Components revenue was $649.4 million; systems revenue was $356.9 million. "
                    "Full-year FY2026 revenue was $3.014 billion, up 83.2%."
                ),
                "url": "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm",
                "source": "Lumentum IR / SEC Exhibit 99.1",
                "event_type": "earnings",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Lumentum"],
            },
        },
        {
            "event_id": "e10_q4_print_vs_guide",
            "published_at": "2026-08-11T22:10:00+00:00",
            "role": "expectation_print",
            "source": "Q4 print versus the May Q4 guide of $2.85–$3.05 non-GAAP EPS",
            "item": {
                "kind": "news",
                "event_key": "lite_q4_eps_vs_guide",
                "title": "LITE Q4 non-GAAP EPS printed 3.23 versus the prior 2.85 to 3.05 guide",
                "fact": (
                    "Q4 revenue printed $1.0063 billion versus the May guide of $960 million to $1.01 billion. "
                    "Non-GAAP diluted EPS printed $3.23 versus the prior $2.85 to $3.05 guide."
                ),
                "source": "Q4 Exhibit 99.1 vs Q3 outlook",
                "event_type": "other",
                "actual": 3.23,
                "expected": 2.95,
                "expectation_name": "Q4 non-GAAP EPS",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Lumentum"],
            },
        },
        {
            "event_id": "e11_q1_guide",
            "published_at": "2026-08-11T22:25:00+00:00",
            "role": "guidance",
            "source": "Q4 FY2026 Exhibit 99.1 Business Outlook",
            "item": {
                "kind": "filing",
                "event_key": "lite_q1_fy2027_guide",
                "title": "Lumentum guided Q1 FY2027 revenue to 1.225 to 1.275 billion",
                "fact": (
                    "Management expects Q1 FY2027 net revenue of $1.225 billion to $1.275 billion, "
                    "non-GAAP operating margin of 39.5% to 40.5%, and non-GAAP diluted EPS of $4.05 to $4.35. "
                    "The CEO said the Q1 midpoint of $1.25 billion reaches the target model more than a quarter ahead of schedule."
                ),
                "url": "https://investor.lumentum.com/financial-news-releases/news-details/2026/Lumentum-Announces-Fourth-Quarter-and-Full-Fiscal-Year-2026-Results/default.aspx",
                "source": "Lumentum IR",
                "event_type": "guidance",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Lumentum"],
            },
        },
        {
            "event_id": "e12_q4_tape",
            "published_at": "2026-08-12T20:00:00+00:00",
            "role": "peer_sector",
            "source": "Prior LITE pack: Q4 next-day +13.63% on 2.45x volume, +11.31 vs SOXX",
            "item": {
                "kind": "price",
                "event_key": "lite_q4_post_print_tape",
                "title": "LITE shares move +13.63% after the Q4 print",
                "fact": "LITE +13.63% the next session on about 2.45x average volume, outperforming SOXX by 11.31 points.",
                "event_type": "other",
                "price_change_pct": 13.63,
                "peers": {"COHR": 3.2, "FN": 2.4, "SOXX": 2.32},
                "fact_reliability": "signal",
            },
        },
        {
            "event_id": "e13_q4_call_confirm",
            "published_at": "2026-08-12T22:00:00+00:00",
            "role": "customer_demand",
            "source": "Q4 FY2026 CEO commentary in Exhibit 99.1",
            "item": {
                "kind": "news",
                "event_key": "lite_q4_ocs_cpo_els",
                "title": "Lumentum said OCS and 1.6T cloud modules are layering in, with an initial ELS order and rising CPO laser demand",
                "fact": (
                    "The CEO said Q4 showed broad-based traction and that OCS solutions and the cloud module "
                    "business, including 1.6T adoption, are beginning to layer in. He cited increasing demand "
                    "for ultra-high-power CPO lasers, an initial order for ELS modules, and NPO engagements "
                    "as early signs that optics are entering in-rack connectivity."
                ),
                "url": "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm",
                "source": "Q4 FY2026 Exhibit 99.1",
                "event_type": "customer",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Lumentum"],
            },
        },
        {
            "event_id": "e14_duplicate_q4",
            "published_at": "2026-08-13T15:00:00+00:00",
            "role": "duplicate",
            "source": "Secondary reprint of the Q4 $1.01 billion sentence",
            "item": {
                "kind": "news",
                "event_key": "lite_q4_revenue_1_01b_reprint",
                "title": "Lumentum reports fiscal fourth quarter net revenue of 1.01 billion",
                "fact": "Q4 FY2026 net revenue was $1.01 billion.",
                "source": "Reprint of Exhibit 99.1",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e15_aug26_tape",
            "published_at": "2026-08-26T20:00:00+00:00",
            "role": "peer_sector",
            "source": "Prior LITE pack: +6.44% on 2026-08-26",
            "item": {
                "kind": "price",
                "event_key": "lite_aug26_tape",
                "title": "LITE shares move +6.44% with no new filing",
                "fact": "Shares moved +6.44% on 2026-08-26 without a new operating filing.",
                "event_type": "other",
                "price_change_pct": 6.44,
                "peers": {"COHR": 1.8, "SOXX": 0.9},
                "fact_reliability": "signal",
            },
        },
        {
            "event_id": "e16_coherent_capacity",
            "published_at": "2026-09-03T15:00:00+00:00",
            "role": "competition",
            "source": "Coherent fiscal Q3 commentary reported in 2026 optical-capacity coverage",
            "item": {
                "kind": "news",
                "event_key": "cohr_6inch_inp_capacity",
                "title": "Coherent said 6-inch indium phosphide EMLs and CW lasers are in production and capacity is doubling",
                "fact": (
                    "Peer Coherent said EMLs, CW lasers, and photodiodes are in production on a 6-inch "
                    "indium phosphide line, that internal capacity would double by the end of the June quarter, "
                    "and that data center and communications were 75% of revenue."
                ),
                "source": "Coherent commentary via 2026 industry coverage",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
                "entities": ["Coherent", "Lumentum"],
            },
        },
        {
            "event_id": "e17_ecoc_noise",
            "published_at": "2026-09-08T14:00:00+00:00",
            "role": "ordinary_news",
            "source": "Existing LITE news corpus",
            "item": {
                "kind": "news",
                "event_key": "lite_ecoc_2026_schedule",
                "title": "Lumentum Sets ECOC 2026 Speaker Schedule",
                "fact": "Lumentum published an ECOC 2026 speaker schedule. No new operating results or guidance.",
                "event_type": "other",
                "confirmed": True,
                "fact_reliability": "direct_fact",
            },
        },
        {
            "event_id": "e18_optics_group_tape",
            "published_at": "2026-09-16T19:30:00+00:00",
            "role": "unresolved_tape",
            "source": "Existing LITE news corpus: AI-optics group weakens after peer financing; header price 2026-09-16 $919.40",
            "item": {
                "kind": "news",
                "event_key": "lite_ai_optics_group_weakens",
                "title": "Lumentum shares fall as AI-optics group weakens after peer financing move",
                "fact": (
                    "Lumentum shares moved with the AI-optics group after a peer financing headline. "
                    "No new Lumentum operating filing. Last available print in the pack is $919.40 on 2026-09-16."
                ),
                "source": "Quiver Quantitative / pack header",
                "event_type": "other",
                "price_change_pct": None,
                "fact_reliability": "signal",
                "entities": ["Lumentum"],
            },
        },
    ]


def final_snapshot(store: Any) -> dict[str, Any]:
    def _short(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
        out = []
        for row in rows or []:
            item = {key: row.get(key) for key in keys if key in row}
            if row.get("statement"):
                item["statement"] = compact_text(row.get("statement"), 220)
            if row.get("hypothesis"):
                item["hypothesis"] = compact_text(row.get("hypothesis"), 180)
            if row.get("question"):
                item["question"] = compact_text(row.get("question"), 200)
            if row.get("current_state"):
                item["current_state"] = compact_text(row.get("current_state"), 180)
            if row.get("reason"):
                item["reason"] = compact_text(row.get("reason"), 140)
            out.append(item)
        return out

    divergences = store.list_divergences(TICKER) if hasattr(store, "list_divergences") else []
    return {
        "states": _short(store.list_states(TICKER), "state_id", "name", "state_type", "direction", "confidence", "status"),
        "drivers": _short(store.list_drivers(TICKER), "driver_id", "canonical_key", "name", "category", "status"),
        "claims": _short(store.list_active_claims(TICKER), "claim_id", "title", "status", "is_core", "confidence"),
        "exposures": _short(store.list_exposures(TICKER), "exposure_id", "exposure_type", "subject", "object_name", "reason"),
        "causal_edges": _short(store.list_causal_edges(TICKER), "edge_id", "from_node", "to_node", "status", "mechanism"),
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
        ),
        "shadows": _short(store.list_shadows(TICKER), "shadow_id", "name", "status", "statement"),
        "questions": _short(store.list_questions(TICKER), "question_id", "question", "why_it_matters", "status"),
        "divergences": _short(divergences, "divergence_id", "status", "explanation_grade", "statement"),
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
            "divergences": len(divergences),
        },
    }


def scan_overfit(store: Any, timeline_rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_blob = " ".join(
        f"{row.get('title') or ''} {row.get('source') or ''}"
        for row in timeline_rows
    ).lower()
    evidence_blob += " " + " ".join(
        f"{spec['item'].get('title')} {spec['item'].get('fact')}" for spec in timeline()
    ).lower()
    findings: list[dict[str, Any]] = []
    buckets = [
        ("state", store.list_states(TICKER), ("name", "statement")),
        ("driver", store.list_drivers(TICKER), ("name", "canonical_key", "current_state")),
        ("claim", store.list_active_claims(TICKER), ("title", "statement")),
        ("hypothesis", store.list_hypotheses(TICKER), ("canonical_key", "hypothesis")),
        ("edge", store.list_causal_edges(TICKER), ("mechanism", "statement")),
    ]
    for kind, rows, fields in buckets:
        for row in rows or []:
            text = " ".join(str(row.get(field) or "") for field in fields).lower()
            hits = [term for term in AVGO_OVERFIT_TERMS if term in text]
            supported = [term for term in hits if term.strip() in evidence_blob]
            unsupported = [term for term in hits if term not in supported]
            if unsupported:
                findings.append(
                    {
                        "flag": "AVGO_OVERFIT",
                        "kind": kind,
                        "object_id": row.get("state_id") or row.get("driver_id") or row.get("claim_id") or row.get("hypothesis_id") or row.get("edge_id"),
                        "terms": unsupported,
                        "text": compact_text(text, 180),
                    }
                )
    return {"avgo_overfit": findings, "count": len(findings)}


def architecture_overfit(lite: dict[str, Any], avgo: dict[str, Any]) -> dict[str, Any]:
    def keys(rows: list[dict[str, Any]], *fields: str) -> set[str]:
        out = set()
        for row in rows or []:
            for field in fields:
                token = str(row.get(field) or "").strip().lower()
                if token:
                    out.add(token)
        return out

    lite_d = keys(lite.get("drivers") or [], "canonical_key", "name")
    avgo_d = keys(avgo.get("drivers") or [], "canonical_key", "name")
    lite_c = keys(lite.get("claims") or [], "title")
    avgo_c = keys(avgo.get("claims") or [], "title")
    lite_h = keys(lite.get("hypotheses") or [], "canonical_key")
    avgo_h = keys(avgo.get("hypotheses") or [], "canonical_key")

    def jaccard(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return round(len(a & b) / len(a | b), 4)

    shared_drivers = sorted(lite_d & avgo_d)
    shared_claims = sorted(lite_c & avgo_c)
    shared_hyps = sorted(lite_h & avgo_h)
    flagged = []
    if jaccard(lite_d, avgo_d) >= 0.35 or len(shared_drivers) >= 3:
        flagged.append({"flag": "ARCHITECTURE_OR_LLM_OVERFIT", "layer": "driver", "shared": shared_drivers, "jaccard": jaccard(lite_d, avgo_d)})
    if jaccard(lite_c, avgo_c) >= 0.35 or len(shared_claims) >= 2:
        flagged.append({"flag": "ARCHITECTURE_OR_LLM_OVERFIT", "layer": "claim", "shared": shared_claims, "jaccard": jaccard(lite_c, avgo_c)})
    if jaccard(lite_h, avgo_h) >= 0.35 or len(shared_hyps) >= 3:
        flagged.append({"flag": "ARCHITECTURE_OR_LLM_OVERFIT", "layer": "hypothesis", "shared": shared_hyps, "jaccard": jaccard(lite_h, avgo_h)})
    return {
        "driver_jaccard": jaccard(lite_d, avgo_d),
        "claim_jaccard": jaccard(lite_c, avgo_c),
        "hypothesis_jaccard": jaccard(lite_h, avgo_h),
        "shared_drivers": shared_drivers,
        "shared_claims": shared_claims,
        "shared_hypotheses": shared_hyps,
        "flags": flagged,
    }


def lite_structure_hits(lite: dict[str, Any]) -> dict[str, Any]:
    blob = json.dumps(lite, ensure_ascii=False).lower()
    hits = [term for term in REVIEW_REFERENCE if term in blob]
    return {"reference_terms_found": hits, "count": len(hits)}


def _layer_mix(timeline_rows: list[dict[str, Any]]) -> dict[str, Any]:
    fast = slow = graph = 0
    for row in timeline_rows:
        diffs = row.get("diff_counts") or {}
        fast += int(diffs.get("expectations") or 0) + int(diffs.get("attentions") or 0) + int(diffs.get("hypotheses") or 0)
        slow += int(diffs.get("states") or 0) + int(diffs.get("drivers") or 0) + int(diffs.get("claims") or 0)
        graph += int(diffs.get("edges") or 0)
    return {"fast_market_writes": fast, "medium_slow_state_driver_claim": slow, "slowest_graph": graph}


def write_report(payload: dict[str, Any]) -> str:
    m = payload["metrics"]
    lite = payload["final_brain"]
    avgo = payload.get("avgo_brain") or {}
    cmp = payload["comparison"]
    q = payload["review_answers"]
    lines = [
        "# Stock-PM Brain v2 — LITE Cold-Start Bootstrap",
        "",
        f"Generated: {payload['generated_at']}",
        f"Ticker: `{payload['ticker']}`",
        f"Window: {payload['window']['start']} → {payload['window']['end']}",
        "Seed: empty BrainStore. Cold-Start Bootstrap from research-pack Evidence. No pre-written LITE drivers / claims / graph. No AVGO copy.",
        "Architecture: frozen Phase 0–4 runtime + Cold-Start Bootstrap. No special LITE path. Constitution unchanged.",
        "",
        "## LLM ping",
        "",
        json.dumps(payload["llm_ping"], ensure_ascii=False, indent=2),
        "",
        "## Cold-Start Bootstrap",
        "",
        json.dumps(payload.get("bootstrap") or {}, ensure_ascii=False, indent=2),
        "",
        "## Runtime path mix",
        "",
        f"- events: {m['events_total']}",
        f"- duplicate_stop: {m['duplicate_stop']}",
        f"- non_material_stop: {m['non_material_stop']}",
        f"- material_incremental: {m['material_incremental']}",
        f"- full_review: {m['full_review']}",
        f"- glm53_called: {m['glm53_called']}",
        f"- Now Chain coverage: {m['now_chain_coverage']}",
        "",
        "## Token metrics (bootstrap vs incremental)",
        "",
        f"- Bootstrap tokens (one-time): {m.get('bootstrap_tokens')}",
        f"- Incremental tokens (18-event tape): {m.get('incremental_tape_tokens')}",
        f"- Incremental tokens / event: {m.get('tokens_per_incremental')}",
        f"- Incremental tokens / material event: {m.get('tokens_per_material')}",
        f"- Full Review tokens (avg, if any): {m.get('tokens_per_full_review')}",
        f"- Tape total tokens (no bootstrap): {m['total_tokens']}",
        f"- Combined bootstrap + tape: {m.get('combined_tokens')}",
        f"- GLM-5.3 input / output (tape): {m['token_input']} / {m['token_output']}",
        f"- Critic input / output (tape): {m['critic_input']} / {m['critic_output']}",
        f"- AVGO after-stabilization total tokens (reference): {payload.get('avgo_tokens')}",
        f"- Note: {payload.get('cold_start_note')}",
        "",
        "## Context retrieval",
        "",
        f"- Context Recall: {m['context_recall']}",
        f"- Context Precision: {m['context_precision']}",
        f"- Context miss events: {m['context_miss_events']}",
        f"- Memory continuity: {m['memory_continuity']}",
        "Recall/precision are scored against already-formed LITE objects that overlap the event, not a pre-written golden graph.",
        "",
        "## Cross-ticker invariants",
        "",
        f"- runtime crash / unexpected write: {m['unexpected_brain_write']}",
        f"- Price → Fundamental: {m['price_fundamental_violations']}",
        f"- Price → Core Claim: {m['price_claim_violations']}",
        f"- Price → established causal edge: {m['price_established_edge_violations']}",
        f"- Unsupported Event → Claim: {m['unsupported_event_claim_jump']}",
        "",
        "## Brain growth",
        "",
        f"- Bootstrap inventory: {(payload.get('bootstrap') or {}).get('inventory')}",
        f"- Early (first 4 events) counts: {payload['growth']['early']}",
        f"- Mid counts: {payload['growth']['mid']}",
        f"- Final counts: {payload['growth']['final']}",
        f"- Continuity: {payload.get('continuity')}",
        f"- High-confidence claims in first 2 material events: {payload['growth']['early_high_conf_claims']}",
        f"- Candidate / shadow / RQ early: {payload['growth']['early_uncertain']}",
        f"- Layer mix (fast / slow / graph writes): {payload['growth']['layer_mix']}",
        "",
        "## Overfit findings",
        "",
        f"- AVGO_OVERFIT count: {payload['overfit']['count']}",
    ]
    for row in payload["overfit"]["avgo_overfit"][:12]:
        lines.append(f"  - {row.get('flag')} {row.get('kind')} {row.get('object_id')}: {row.get('terms')} — {row.get('text')}")
    lines.extend(
        [
            f"- ARCHITECTURE_OR_LLM_OVERFIT flags: {payload['arch_overfit']['flags']}",
            f"- driver/claim/hypothesis jaccard vs AVGO: {payload['arch_overfit']['driver_jaccard']} / {payload['arch_overfit']['claim_jaccard']} / {payload['arch_overfit']['hypothesis_jaccard']}",
            f"- LITE review-reference terms found (not hardcoded drivers): {payload['lite_hits']['reference_terms_found']}",
            "",
            "## AVGO vs LITE",
            "",
        ]
    )
    for section, key in (
        ("Top Company States", "states"),
        ("Top Exposures", "exposures"),
        ("Top Value Drivers", "drivers"),
        ("Core Claims", "claims"),
        ("Major Causal Paths", "edges"),
        ("Expectation States", "expectations"),
        ("Market Driver Hypotheses", "hypotheses"),
        ("Research Questions", "questions"),
        ("Price Divergences", "divergences"),
    ):
        lines.append(f"### {section}")
        lines.append("")
        lines.append("**AVGO**")
        for row in (avgo.get(key) or [])[:8]:
            lines.append(f"- {compact_text(json.dumps(row, ensure_ascii=False), 220)}")
        if not avgo.get(key):
            lines.append("- (none)")
        lines.append("")
        lines.append("**LITE**")
        for row in (lite.get(key) or [])[:8]:
            lines.append(f"- {compact_text(json.dumps(row, ensure_ascii=False), 220)}")
        if not lite.get(key):
            lines.append("- (none)")
        lines.append("")
    lines.extend(
        [
            "## Distinct brains?",
            "",
            cmp.get("distinct_note") or "",
            "",
            "## Eight bootstrap review questions",
            "",
        ]
    )
    for idx, (question, answer) in enumerate(q.items(), start=1):
        lines.append(f"{idx}. **{question}**")
        lines.append(f"   {answer}")
        lines.append("")
    lines.extend(
        [
            "## Material Now Chains",
            "",
        ]
    )
    for row in payload["timeline"]:
        if not row.get("material") or row.get("stopped"):
            continue
        chain = row.get("now_chain") or {}
        lines.append(f"### {row['event_id']} — {row.get('title')}")
        lines.append(f"- 发生了什么: {chain.get('what_happened')}")
        lines.append(f"- 为什么影响 LITE: {chain.get('why_company')}")
        lines.append(f"- 路径: {chain.get('path')}")
        lines.append(f"- 市场怎么理解: {chain.get('market_understands')}")
        lines.append("")
    lines.extend(
        [
            "## Runtime anomalies",
            "",
        ]
    )
    for item in payload.get("anomalies") or ["(none)"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Cognitive drift", ""])
    for item in payload.get("drift") or ["(none)"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _answer_questions(payload: dict[str, Any]) -> dict[str, str]:
    m = payload["metrics"]
    boot = payload.get("bootstrap") or {}
    cont = payload.get("continuity") or {}
    growth = payload["growth"]
    lite_hits = payload["lite_hits"]["reference_terms_found"]
    overfit_n = payload["overfit"]["count"]
    initialized = bool(boot.get("brain_initialized"))
    slow = (
        (growth["final"].get("states") or 0) > 0
        and (growth["final"].get("drivers") or 0) > 0
        and (growth["final"].get("claims") or 0) > 0
    )
    reused = any(int((cont.get(key) or {}).get("reused_bootstrap") or 0) > 0 for key in ("states", "drivers", "claims"))
    evolved = any(int((cont.get(key) or {}).get("updated") or 0) > 0 for key in ("states", "drivers", "claims"))
    edges = growth["final"].get("edges") or 0
    candidate_only = bool((payload.get("final_brain") or {}).get("causal_edges")) and all(
        str(row.get("status") or "") == "candidate" for row in (payload.get("final_brain") or {}).get("causal_edges") or []
    )
    early = bool(slow and lite_hits)
    return {
        "Empty Brain 是否能够完成 bootstrap？": (
            f"{'是' if initialized and slow else '否'}。"
            f" brain_initialized={initialized} bootstrap_states={boot.get('inventory', {}).get('states')} "
            f"drivers={boot.get('inventory', {}).get('drivers')} core_claims={boot.get('inventory', {}).get('core_claims')}."
        ),
        "Bootstrap 是否形成 LITE-specific Slow Brain？": (
            f"{'倾向是' if lite_hits and slow else '不明显'}。"
            f" Review-reference terms found: {lite_hits}. Not hardcoded."
        ),
        "是否没有人工 seed Driver / Claim / Graph？": (
            f"是。 seed.prewritten_lite_objects={payload.get('seed', {}).get('prewritten_lite_objects')} "
            f"research_meta={payload.get('research_meta')}."
        ),
        "后续 Incremental 是否真正利用 bootstrap 结果？": (
            f"{'是' if reused else '弱'}。"
            f" Continuity reused/updated: { {k: {kk: (cont.get(k) or {}).get(kk) for kk in ('reused_bootstrap', 'updated', 'created')} for k in ('states', 'drivers', 'claims', 'edges')} }."
        ),
        "State / Driver / Claim 是否会随 Evidence 演化？": (
            f"{'有更新' if evolved else '主要停留在 bootstrap 快照'}。 layer_mix={growth.get('layer_mix')}."
        ),
        "Causal Graph 是否从 candidate 逐步积累？": (
            f"Final edges={edges}. candidate_only={candidate_only}. "
            f"edge continuity={cont.get('edges')}."
        ),
        "是否仍然没有 AVGO overfit？": (
            f"{'未发现明显 AVGO_OVERFIT' if not overfit_n else '是'}。 count={overfit_n}."
        ),
        "Bootstrap 后，LITE 是否可以被称为一个完整的 early Investment Brain？": (
            f"{'可以作为 early / minimum viable Investment Brain' if early else '仍不完整'}。"
            f" states={growth['final'].get('states')} drivers={growth['final'].get('drivers')} "
            f"claims={growth['final'].get('claims')} edges={edges} exposures={growth['final'].get('exposures')}."
        ),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    ping = ping_layers(settings)
    _write("ping.json", ping)
    research, store, research_meta = _make_research()
    assert brain_has_baseline(store, TICKER) is False
    events = timeline()
    _write("timeline.json", [{"event_id": row["event_id"], "published_at": row["published_at"], "role": row["role"], "title": row["item"].get("title"), "source": row.get("source")} for row in events])
    mechanical, reasoning = brain_completers(settings)

    # Pack Evidence is the bootstrap corpus. Do not block Cold-Start on live web search.
    import stock_pm.brain.pipeline as brain_pipeline

    brain_pipeline.search_recent_news = lambda *args, **kwargs: []
    research_meta["news_search"] = "disabled_ddg_hang_guard"

    print("[bootstrap] starting research-pack init (not the first event)", flush=True)
    bootstrap_result = bootstrap_brain(
        research,
        TICKER,
        store=store,
        mechanical_completer=mechanical,
        reasoning_completer=reasoning,
        fetch_live=bool(research_meta.get("fetch_live")),
    )
    bootstrap_tokens = int((bootstrap_result.get("token_usage") or {}).get("total_tokens") or 0)
    bootstrap_index = brain_index(store)
    _write(
        "bootstrap.json",
        {
            "path": bootstrap_result.get("path"),
            "brain_initialized": bootstrap_result.get("brain_initialized"),
            "lifecycle": bootstrap_result.get("lifecycle"),
            "inventory": bootstrap_result.get("inventory"),
            "recovered_graph": bootstrap_result.get("recovered_graph"),
            "token_usage": bootstrap_result.get("token_usage"),
            "phase0": bootstrap_result.get("phase0"),
            "direct_llm_write": bootstrap_result.get("direct_llm_write"),
            "research_meta": research_meta,
            "evidence_set_id": bootstrap_result.get("evidence_set_id"),
            "seeded_drivers_claims_graph": False,
            "objects": {
                "states": final_snapshot(store).get("states"),
                "drivers": final_snapshot(store).get("drivers"),
                "claims": final_snapshot(store).get("claims"),
                "exposures": final_snapshot(store).get("exposures"),
                "causal_edges": final_snapshot(store).get("causal_edges"),
            },
        },
    )
    print(
        f"[bootstrap] initialized={bootstrap_result.get('brain_initialized')} "
        f"inventory={bootstrap_result.get('inventory')} tokens={bootstrap_tokens}",
        flush=True,
    )

    timeline_rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    diffs: list[dict[str, Any]] = []
    anomalies: list[str] = []
    drift: list[str] = []
    evolution: list[dict[str, Any]] = []
    recall_vals: list[float] = []
    precision_vals: list[float] = []
    memory_hits = 0
    memory_denom = 0
    glm53_token_vals: list[int] = []
    incremental_tokens: list[int] = []
    full_tokens: list[int] = []
    hyp_new_keys = 0
    hyp_update_events = 0
    now_n = 0
    early_high_conf_claims = 0
    early_uncertain = 0
    growth_early: dict[str, int] = {}
    growth_mid: dict[str, int] = {}

    metrics = {
        "events_total": 0,
        "duplicate_stop": 0,
        "non_material_stop": 0,
        "material_incremental": 0,
        "full_review": 0,
        "glm53_called": 0,
        "avg_glm53_tokens": 0,
        "avg_tokens_per_event": 0,
        "token_input": 0,
        "token_output": 0,
        "critic_input": 0,
        "critic_output": 0,
        "total_tokens": 0,
        "tokens_per_incremental": 0,
        "tokens_per_full_review": 0,
        "context_miss_events": 0,
        "unexpected_brain_write": 0,
        "price_fundamental_violations": 0,
        "price_claim_violations": 0,
        "price_established_edge_violations": 0,
        "unsupported_event_claim_jump": 0,
        "successful_transmission": 0,
        "blocked_transmission": 0,
        "research_questions": 0,
        "context_recall": None,
        "context_precision": None,
        "memory_continuity": None,
        "hypothesis_continuity": None,
        "now_chain_coverage": "0/18",
        "bootstrap_tokens": bootstrap_tokens,
        "incremental_tape_tokens": 0,
        "combined_tokens": bootstrap_tokens,
        "tokens_per_material": 0,
    }

    prior = brain_index(store)
    prior_hyps = _hyp_by_key(store)
    continuity_acc = {
        "states": {"created": 0, "updated": 0, "reused_bootstrap": 0},
        "drivers": {"created": 0, "updated": 0, "reused_bootstrap": 0},
        "claims": {"created": 0, "updated": 0, "reused_bootstrap": 0},
        "edges": {"created": 0, "updated": 0, "reused_bootstrap": 0},
    }

    for idx, spec in enumerate(events):
        metrics["events_total"] += 1
        item = dict(spec["item"])
        item["published_at"] = spec["published_at"]
        item["event_id"] = spec["event_id"]
        result: dict[str, Any] = {}
        try:
            result = run_brain_update(ticker=TICKER, item=item, store=store)
        except Exception as exc:  # noqa: BLE001 — record, do not patch
            anomalies.append(f"{spec['event_id']}: exception {exc}")
            result = {"path": "error", "error": str(exc), "stopped": True, "llm_calls": []}
            traceback.print_exc()

        after = brain_index(store)
        after_hyps = _hyp_by_key(store)
        delta = diff_brain(prior, after)
        cont = continuity_delta(prior, after, bootstrap_index)
        for kind, row in cont.items():
            for field in ("created", "updated", "reused_bootstrap"):
                continuity_acc[kind][field] += int(row.get(field) or 0)
        diffs.append({"event_id": spec["event_id"], "diff": delta, "continuity": cont})
        path = str(result.get("path") or "")
        if path == "l0_stop" or result.get("duplicate"):
            metrics["duplicate_stop"] += 1
        elif path == "observation_memory" or result.get("stop_reason") == "non_material":
            metrics["non_material_stop"] += 1
        elif result.get("full_review") or path == "full_review":
            metrics["full_review"] += 1
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
        if path == "incremental":
            incremental_tokens.append(tokens.get("total_tokens") or 0)
        if result.get("full_review") or path == "full_review":
            full_tokens.append(tokens.get("total_tokens") or 0)

        market_stats = result.get("market_layer") or {}
        metrics["price_fundamental_violations"] += int(market_stats.get("price_fundamental_violations") or 0)
        metrics["price_claim_violations"] += int(market_stats.get("price_claim_violations") or 0)
        metrics["price_established_edge_violations"] += int(market_stats.get("price_established_edge_violations") or 0)
        metrics["unsupported_event_claim_jump"] += int(result.get("unsupported_jump_count") or 0)
        metrics["successful_transmission"] += int((result.get("transmission") or {}).get("successful_count") or 0)
        metrics["blocked_transmission"] += int((result.get("transmission") or {}).get("blocked_count") or 0)

        created_keys = set(after_hyps) - set(prior_hyps)
        updated_keys = []
        for key, row in after_hyps.items():
            prev_row = prior_hyps.get(key)
            if prev_row and (
                prev_row.get("status") != row.get("status")
                or prev_row.get("confidence") != row.get("confidence")
            ):
                updated_keys.append(key)
        if created_keys:
            hyp_new_keys += len(created_keys)
        if updated_keys:
            hyp_update_events += 1

        for row in (result.get("gate") or {}).get("approved") or []:
            kind = str(row.get("object_type") or "")
            source = str(row.get("source_kind") or "")
            if source in {"price", "rumor"} and kind in {"state", "company_state", "claim", "core_claim", "driver", "value_driver"}:
                metrics["unexpected_brain_write"] += 1
                anomalies.append(f"{spec['event_id']}: unexpected {source} write to {kind}")
            if spec["role"] in {"ordinary_news", "duplicate"} and kind in SLOW_TYPES:
                drift.append(f"{spec['event_id']}: ordinary/noise event wrote slow object {kind}")

        now_chain = result.get("now_chain")
        if now_chain:
            now_n += 1

        shot = result.get("snapshot") or {}
        leftover = leftover_from_index(prior)
        if (path == "incremental" and result.get("material")) or result.get("full_review"):
            memory_denom += 1
            hist = _uses_history(shot, leftover)
            if hist["used"]:
                memory_hits += 1
            expected = expected_from_formed(item, prior)
            if any(expected.get(key) for key in ("drivers", "claims", "states")):
                score = score_snapshot_context(snapshot=shot, expected=expected, irrelevant=[])
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
            hist = {"used": False, "used_historical_objects": 0, "historical_pool": 0}
            score = {}
            misses = []

        snap = {
            "event_id": spec["event_id"],
            "counts": {key: len(val) for key, val in after.items()},
        }
        evolution.append(snap)
        if idx == 3:
            growth_early = snap["counts"]
            early_high_conf_claims = sum(
                1
                for row in store.list_active_claims(TICKER)
                if str(row.get("confidence") or "") == "high"
            )
            early_uncertain = (
                sum(1 for row in store.list_shadows(TICKER) if str(row.get("status") or "") in {"candidate", "open", "unresolved", ""})
                + sum(1 for row in store.list_questions(TICKER) if str(row.get("status") or "open") == "open")
                + sum(1 for row in store.list_causal_edges(TICKER) if str(row.get("status") or "") in {"candidate", "unsupported"})
            )
        if idx == 10:
            growth_mid = snap["counts"]

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
            "continuity": cont,
            "tokens": tokens,
            "brain_counts": snap["counts"],
            "brain_initialized": result.get("brain_initialized"),
            "lifecycle": result.get("lifecycle"),
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
                "critic_skipped": result.get("critic_skipped"),
            }
        )
        print(
            f"[{spec['event_id']}] path={path} material={result.get('material')} glm53={result.get('glm53_called')} "
            f"states={len(after['states'])} drivers={len(after['drivers'])} claims={len(after['claims'])}",
            flush=True,
        )
        prior = after
        prior_hyps = after_hyps

    lite_brain = final_snapshot(store)
    avgo_brain = json.loads(AVGO_BRAIN.read_text(encoding="utf-8")) if AVGO_BRAIN.is_file() else {}
    avgo_metrics = json.loads(AVGO_METRICS.read_text(encoding="utf-8")) if AVGO_METRICS.is_file() else {}
    growth_final = lite_brain["counts"]
    metrics["avg_glm53_tokens"] = round(sum(glm53_token_vals) / max(len(glm53_token_vals), 1), 2) if glm53_token_vals else 0
    metrics["avg_tokens_per_event"] = round(metrics["total_tokens"] / max(metrics["events_total"], 1), 1)
    metrics["tokens_per_incremental"] = round(sum(incremental_tokens) / max(len(incremental_tokens), 1), 1) if incremental_tokens else 0
    metrics["tokens_per_full_review"] = round(sum(full_tokens) / max(len(full_tokens), 1), 1) if full_tokens else 0
    metrics["context_recall"] = round(sum(recall_vals) / len(recall_vals), 4) if recall_vals else None
    metrics["context_precision"] = round(sum(precision_vals) / len(precision_vals), 4) if precision_vals else None
    metrics["memory_continuity"] = round(memory_hits / max(memory_denom, 1), 4) if memory_denom else None
    denom = hyp_update_events + hyp_new_keys
    metrics["hypothesis_continuity"] = round(hyp_update_events / denom, 4) if denom else None
    metrics["research_questions"] = len(store.list_questions(TICKER))
    metrics["now_chain_coverage"] = f"{now_n}/{metrics['events_total']}"
    metrics["incremental_tape_tokens"] = metrics["total_tokens"]
    metrics["combined_tokens"] = bootstrap_tokens + metrics["total_tokens"]
    metrics["tokens_per_material"] = (
        round(sum(incremental_tokens) / max(len(incremental_tokens), 1), 1) if incremental_tokens else 0
    )

    overfit = scan_overfit(store, timeline_rows)
    arch = architecture_overfit(lite_brain, avgo_brain)
    lite_hits = lite_structure_hits(lite_brain)
    avgo_total = avgo_metrics.get("total_tokens")
    colder = None
    if avgo_total:
        colder = round((metrics["total_tokens"] / avgo_total - 1) * 100, 1)
    payload = {
        "generated_at": _now(),
        "ticker": TICKER,
        "window": {"start": "2026-05-05", "end": "2026-09-16"},
        "seed": {"mode": "empty_then_bootstrap", "prewritten_lite_objects": False, "avgo_copy": False, "manual_driver_claim_graph": False},
        "research_meta": research_meta,
        "bootstrap": {
            "path": bootstrap_result.get("path"),
            "brain_initialized": bootstrap_result.get("brain_initialized"),
            "lifecycle": bootstrap_result.get("lifecycle"),
            "inventory": bootstrap_result.get("inventory"),
            "recovered_graph": bootstrap_result.get("recovered_graph"),
            "token_usage": bootstrap_result.get("token_usage"),
            "phase0": bootstrap_result.get("phase0"),
            "direct_llm_write": bootstrap_result.get("direct_llm_write"),
        },
        "continuity": continuity_acc,
        "llm_ping": ping,
        "metrics": metrics,
        "timeline": timeline_rows,
        "anomalies": anomalies,
        "drift": drift,
        "evolution": evolution,
        "final_brain": lite_brain,
        "avgo_brain": avgo_brain,
        "avgo_tokens": avgo_total,
        "cold_start_note": (
            f"Bootstrap {bootstrap_tokens} tokens once. Incremental tape {metrics['total_tokens']} "
            f"(avg {metrics['tokens_per_incremental']}/event). Combined {metrics['combined_tokens']} "
            f"vs AVGO {avgo_total} ({colder}% {'more' if (colder or 0) > 0 else 'less'}). "
            "Bootstrap is supposed to be more expensive than a daily update."
        ),
        "overfit": overfit,
        "arch_overfit": arch,
        "lite_hits": lite_hits,
        "growth": {
            "early": growth_early,
            "mid": growth_mid,
            "final": growth_final,
            "early_high_conf_claims": early_high_conf_claims,
            "early_uncertain": early_uncertain,
            "layer_mix": _layer_mix(timeline_rows),
        },
        "comparison": {
            "distinct_note": (
                "Compare object names and mechanisms, not quality. "
                f"Shared driver keys={arch.get('shared_drivers')}. "
                f"LITE review terms={lite_hits.get('reference_terms_found')}."
            )
        },
    }
    payload["review_answers"] = _answer_questions(payload)
    _write("metrics.json", metrics)
    _write("runtime_timeline.json", timeline_rows)
    _write("traces.json", traces)
    _write("diffs.json", diffs)
    _write("brain_evolution.json", evolution)
    _write("final_brain.json", lite_brain)
    _write("context_miss.json", [row for row in timeline_rows if row.get("context_misses")])
    _write("runtime_anomalies.json", anomalies)
    _write("cognitive_drift.json", drift)
    _write("overfit_findings.json", {"avgo": overfit, "architecture": arch})
    _write("comparison.json", {"lite": lite_brain, "avgo": avgo_brain, "arch_overfit": arch, "lite_hits": lite_hits})
    report = write_report(payload)
    _write("REPORT.md", report)
    _write("report.json", payload)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
