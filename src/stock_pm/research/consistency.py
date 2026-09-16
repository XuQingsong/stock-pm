"""Deterministic reasoning consistency audit. Does not invent Evidence or valuation numbers."""

from __future__ import annotations

import json
import re
from typing import Any

from .deep_case import customer_hit_relation, evidence_side
from .extract import to_number
from .llm_reason import compact_text
from .relevance import CONTRACT_RE
from .valuation import attribute_target_change, display_target


CAPACITY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:giga\s*watts?|gw)\b", re.I)
PULL_FORWARD_RE = re.compile(r"pull[- ]forward|inventory build|channel inventory", re.I)
BELOW_BASE_RE = re.compile(
    r"(implied (?:growth|expect)|market (?:implied|appears to price|is pricing)).{0,80}(below|lower than).{0,40}(base|pm base)",
    re.I,
)
INVENT_TARGET_RE = re.compile(r"\$\s*(\d{2,4})\b")
GRADES = ("FACT", "SUPPORTED_INFERENCE", "SPECULATION")


def _index(rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        key = str(row.get("id") or row.get("evidence_id") or "").strip()
        if key:
            out[key] = row
    return out


def _blob(row: dict[str, Any] | None) -> str:
    item = row or {}
    return " ".join(str(item.get(key) or "") for key in ("fact", "excerpt", "source", "source_type"))


def _source_date(row: dict[str, Any] | None) -> str | None:
    item = row or {}
    return item.get("source_time") or item.get("published_at") or item.get("as_of") or (_raw(item).get("published_at"))


def _raw(row: dict[str, Any] | None) -> dict[str, Any]:
    raw = (row or {}).get("raw_reference")
    return raw if isinstance(raw, dict) else {}


def hydrate_evidence(eid: str, index: dict[str, dict[str, Any]], *, ticker: str | None = None) -> dict[str, Any] | None:
    row = index.get(str(eid or "").strip())
    if not row:
        return None
    side = evidence_side(row, ticker)
    return {
        "evidence_id": str(row.get("id") or eid),
        "fact": compact_text(row.get("fact") or "", 280),
        "excerpt": compact_text(row.get("excerpt") or row.get("fact") or "", 280),
        "source": row.get("source"),
        "source_url": row.get("source_url") or _raw(row).get("url"),
        "source_date": _source_date(row),
        "evidence_family": side,
        "evidence_type": row.get("evidence_type") or row.get("source_type"),
        "customer_proof_class": customer_proof_class(row, ticker=ticker),
    }


def customer_proof_class(row: dict[str, Any] | None, *, ticker: str | None = None, legal_name: str | None = None) -> str:
    """A = industry capex/demand; B = customer demand for this issuer; C = a specific contract."""
    item = row or {}
    side = evidence_side(item, ticker)
    relation = customer_hit_relation(item, ticker=ticker, legal_name=legal_name)
    fact = str(item.get("fact") or item.get("excerpt") or "")
    fact_l = fact.lower()
    has_customer = "customer" in fact_l or "hyperscal" in fact_l
    if side == "independent_customer" and (relation == "direct_issuer_cross_check" or CONTRACT_RE.search(fact)):
        return "C"
    if side == "independent_customer" and has_customer:
        return "B"
    if has_customer and side == "issuer_management" and ("capex" in fact_l or "capital expend" in fact_l):
        return "A"
    if has_customer and side == "issuer_management":
        return "B_issuer_claim"
    if relation == "industry_demand_only" or side == "industry_third_party":
        return "A"
    return "not_customer_evidence"


def _ids(value: Any, index: dict[str, dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in value or []:
        if isinstance(item, dict):
            eid = str(item.get("evidence_id") or item.get("id") or "").strip()
        else:
            eid = str(item).strip()
        if eid and eid in index and eid not in out:
            out.append(eid)
    return out


def _capacity_numbers(text: str) -> set[str]:
    return {m.group(1) for m in CAPACITY_RE.finditer(text or "")}


def _grounded_capacity(index: dict[str, dict[str, Any]]) -> tuple[set[str], list[dict[str, Any]]]:
    numbers: set[str] = set()
    rows: list[dict[str, Any]] = []
    for row in index.values():
        found = _capacity_numbers(_blob(row))
        if found:
            numbers |= found
            rows.append(row)
    return numbers, rows


def _scrub_capacity(text: str, allowed: set[str]) -> str:
    if not text:
        return text

    def repl(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1) in allowed else ""

    cleaned = CAPACITY_RE.sub(repl, text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _case_inputs(valuation: dict[str, Any] | None, name: str) -> dict[str, Any]:
    row = (valuation or {}).get(f"{name}_case") or {}
    growth = row.get("growth_assumptions") if isinstance(row.get("growth_assumptions"), dict) else {}
    margin = row.get("margin_assumptions") if isinstance(row.get("margin_assumptions"), dict) else {}
    lineage = (valuation or {}).get("financial_lineage") or ((valuation or {}).get("calibration_json") or {}).get("financial_lineage") or {}
    shares = lineage.get("diluted_shares") if isinstance(lineage.get("diluted_shares"), dict) else {}
    return {
        "forward_revenue": row.get("revenue"),
        "forward_growth": growth.get("annual_rate"),
        "growth_origin": growth.get("origin"),
        "margin": margin.get("net_margin_pct"),
        "eps": row.get("eps"),
        "diluted_shares": shares.get("value"),
        "diluted_shares_origin": shares.get("origin"),
        "pe_multiple": row.get("multiple"),
        "horizon": row.get("horizon") or (valuation or {}).get("horizon"),
        "target": row.get("target_value"),
        "method": row.get("valuation_method") or (valuation or {}).get("method"),
        "eps_derivation": row.get("eps_derivation"),
    }


def valuation_snapshot(valuation: dict[str, Any] | None, pack: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = (pack or {}).get("company_profile") or {}
    lineage = (valuation or {}).get("financial_lineage") or ((valuation or {}).get("calibration_json") or {}).get("financial_lineage") or {}
    shares = lineage.get("diluted_shares") if isinstance(lineage.get("diluted_shares"), dict) else {}
    net = lineage.get("net_margin") if isinstance(lineage.get("net_margin"), dict) else {}
    spot = to_number((valuation or {}).get("spot_price") or profile.get("last_close"))
    cases = {name: _case_inputs(valuation, name) for name in ("bear", "base", "bull")}
    return {
        "spot": spot,
        "revenue_ttm": to_number(profile.get("revenue_ttm")),
        "eps_ttm": to_number(profile.get("eps_ttm")),
        "pe_ttm": to_number(profile.get("pe_ttm")),
        "diluted_shares": shares.get("value"),
        "diluted_shares_origin": shares.get("origin"),
        "net_margin": net.get("value"),
        "method": (valuation or {}).get("method") or ((valuation or {}).get("calibration_json") or {}).get("method"),
        "eps_method": (valuation or {}).get("eps_method") or ((valuation or {}).get("calibration_json") or {}).get("eps_method"),
        "horizon": (valuation or {}).get("horizon"),
        "targets": {name: cases[name]["target"] for name in cases},
        "cases": cases,
        "llm_must_not_replace_targets": True,
    }


def valuation_stance(spot: float | None, targets: dict[str, Any]) -> dict[str, Any]:
    bear = to_number(targets.get("bear"))
    base = to_number(targets.get("base"))
    bull = to_number(targets.get("bull"))
    if spot in (None, 0) or bull is None:
        return {
            "code": "incomparable",
            "summary": "Spot is missing or bull has no target, so the tape cannot be ranked against Bear/Base/Bull.",
            "spot_above_bull": False,
            "spot_above_base": False,
            "spot_below_base": False,
        }
    above_bull = float(spot) > float(bull)
    above_base = base is not None and float(spot) > float(base)
    below_base = base is not None and float(spot) < float(base)
    if above_bull:
        code = "market_above_bull"
        summary = (
            f"Spot {display_target(spot)} is above Bull {display_target(bull)}. "
            "Even the most optimistic researched case is below the market price."
        )
    elif above_base:
        code = "market_above_base"
        summary = f"Spot {display_target(spot)} sits above Base {display_target(base)} and at or below Bull {display_target(bull)}."
    elif below_base:
        code = "market_below_base"
        summary = f"Spot {display_target(spot)} is below Base {display_target(base)}. Only then may PM say the tape prices less than Base."
    else:
        code = "market_at_base"
        summary = f"Spot {display_target(spot)} is close to Base {display_target(base)}."
    return {
        "code": code,
        "summary": summary,
        "spot": spot,
        "bear": bear,
        "base": base,
        "bull": bull,
        "spot_above_bull": above_bull,
        "spot_above_base": above_base,
        "spot_below_base": below_base,
    }


def _grade(text: str, *, evidence_ids: list[str], index: dict[str, dict[str, Any]]) -> str:
    blob = " ".join(_blob(index[eid]) for eid in evidence_ids if eid in index)
    if PULL_FORWARD_RE.search(text or "") and not PULL_FORWARD_RE.search(blob):
        return "SPECULATION"
    if not evidence_ids:
        return "SPECULATION"
    if text and blob and compact_text(text, 80).lower()[:40] in blob.lower():
        return "FACT"
    return "SUPPORTED_INFERENCE"


def audit_pm_reasoning(
    reasoning: dict[str, Any] | None,
    *,
    evidence: list[dict[str, Any]] | None = None,
    valuation: dict[str, Any] | None = None,
    pack: dict[str, Any] | None = None,
    previous_valuation: dict[str, Any] | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Ground, classify, and warn. Mutates reasoning in place. Never changes Bear/Base/Bull numbers."""
    reasoning = reasoning if isinstance(reasoning, dict) else {}
    index = _index(evidence)
    symbol = str(ticker or (pack or {}).get("ticker") or "").upper() or None
    snap = valuation_snapshot(valuation, pack)
    stance = valuation_stance(snap["spot"], snap["targets"])
    warnings: list[str] = []
    unsupported: list[str] = []
    stale: list[str] = []
    claim_grades: list[dict[str, Any]] = []

    python_targets = snap["targets"]
    for match in INVENT_TARGET_RE.finditer(" ".join(str(reasoning.get(key) or "") for key in ("valuation_driver_judgment", "core_thesis"))):
        value = int(match.group(1))
        if value not in {python_targets.get("bear"), python_targets.get("base"), python_targets.get("bull")} and value >= 50:
            if abs(value - float(python_targets.get("base") or 0)) > 20:
                stale.append(f"prose cites ${value} which is not the Python Bear/Base/Bull")

    allowed_capacity, capacity_rows = _grounded_capacity(index)
    for key in (
        "core_thesis",
        "core_contradiction",
        "long_term_view",
        "mid_term_view",
        "short_term_view",
        "weakest_link",
        "next_information_to_seek",
        "valuation_driver_judgment",
        "most_likely_wrong",
        "what_would_change_my_mind",
        "thesis_invalidation",
    ):
        text = reasoning.get(key)
        if isinstance(text, str) and CAPACITY_RE.search(text):
            if not allowed_capacity:
                reasoning[key] = _scrub_capacity(text, allowed_capacity)
                unsupported.append(f"{key} cited a capacity target with no Evidence; removed")
            else:
                claim_grades.append(
                    {
                        "claim": compact_text(CAPACITY_RE.search(text).group(0), 80),
                        "grade": "FACT",
                        "evidence_ids": [str(row.get("id")) for row in capacity_rows[:3]],
                    }
                )

    grounded_top: list[dict[str, Any]] = []
    dropped_top: list[str] = []
    for item in reasoning.get("top_thesis_changing_evidence") or []:
        eid = str((item or {}).get("evidence_id") or "").strip() if isinstance(item, dict) else str(item).strip()
        hydrated = hydrate_evidence(eid, index, ticker=symbol)
        if not hydrated:
            dropped_top.append(eid or "missing_id")
            continue
        why = compact_text((item.get("why_it_changes_thesis") or item.get("why") or "") if isinstance(item, dict) else "", 200)
        hydrated["why_it_changes_thesis"] = why
        grounded_top.append(hydrated)
        claim_grades.append({"claim": hydrated["fact"], "grade": "FACT", "evidence_ids": [eid]})
        proof = hydrated["customer_proof_class"]
        if proof == "A" and "customer" in (hydrated["fact"] or "").lower():
            warnings.append(
                f"{eid} is industry/issuer language about customers; it does not prove a named-customer contract"
            )
    if dropped_top:
        unsupported.append("dropped top_thesis_changing_evidence without a real evidence_id: " + ", ".join(dropped_top))
    reasoning["top_thesis_changing_evidence"] = grounded_top[:5]

    mapped_vars = []
    for item in reasoning.get("decisive_variables") or []:
        if not isinstance(item, dict):
            continue
        support = _ids(item.get("supporting_evidence_ids") or item.get("evidence_ids") or item.get("evidence"), index)
        oppose = _ids(item.get("opposing_evidence_ids"), index)
        missing = [compact_text(gap, 160) for gap in (item.get("missing_evidence") or []) if str(gap).strip() and len(str(gap).strip()) > 1][:4]
        if not missing and not support:
            missing = ["no grounded evidence_id on this variable"]
        row = dict(item)
        row["supporting_evidence_ids"] = support[:6]
        row["opposing_evidence_ids"] = oppose[:6]
        row["missing_evidence"] = missing
        row["evidence_ids"] = support[:6]
        mapped_vars.append(row)
        claim_grades.append(
            {
                "claim": row.get("current_view") or row.get("name"),
                "grade": _grade(str(row.get("current_view") or ""), evidence_ids=support, index=index),
                "evidence_ids": support,
            }
        )
    reasoning["decisive_variables"] = mapped_vars[:3]

    mapped_h = []
    for item in reasoning.get("competing_hypotheses") or []:
        if not isinstance(item, dict):
            continue
        support = _ids(item.get("supporting_evidence_ids") or item.get("evidence_ids"), index)
        oppose = _ids(item.get("opposing_evidence_ids"), index)
        statement = compact_text(item.get("statement") or "", 280)
        speculative = (not support) or bool(PULL_FORWARD_RE.search(statement) and not any(PULL_FORWARD_RE.search(_blob(index[eid])) for eid in support))
        row = dict(item)
        row["supporting_evidence_ids"] = support[:6]
        row["opposing_evidence_ids"] = oppose[:6]
        row["missing_evidence"] = [compact_text(gap, 160) for gap in (item.get("missing_evidence") or []) if str(gap).strip() and len(str(gap).strip()) > 1][:4]
        row["confidence_band"] = compact_text(item.get("confidence_band") or item.get("probability_band") or "", 40)
        row["speculative_hypothesis"] = speculative
        if speculative:
            row["grade"] = "SPECULATION"
            unsupported.append(f"hypothesis is speculative: {statement[:160]}")
        else:
            row["grade"] = "SUPPORTED_INFERENCE"
        mapped_h.append(row)
        claim_grades.append({"claim": statement, "grade": row["grade"], "evidence_ids": support})
    reasoning["competing_hypotheses"] = mapped_h[:4]

    disagreement = list(reasoning.get("market_disagreement") or [])
    if stance["code"] == "market_above_bull":
        warnings.append(stance["summary"])
        blob = json_blob(disagreement)
        if BELOW_BASE_RE.search(blob):
            warnings.append("market_disagreement claimed the tape is below Base while spot is above Bull; that pairing is invalid")
            unsupported.append("thesis vs valuation contradiction: market-below-base language with spot > bull")
        if "above" not in blob.lower() and "more optimistic" not in blob.lower() and "bull" not in blob.lower():
            disagreement = (
                [
                    {
                        "pm_believes": stance["summary"],
                        "market_appears_to_price": "a price above the researched bull case",
                        "why_pm_differs": "Python Bear/Base/Bull sit entirely below spot",
                        "evidence_that_would_prove_market_right": "a researched bull path whose target reaches spot without inventing multiples",
                    }
                ]
                + disagreement
            )[:2]
            reasoning["market_disagreement"] = disagreement
    elif stance["code"] == "market_below_base":
        pass
    elif stance["code"] == "incomparable":
        warnings.append(stance["summary"])
        blob = json_blob(disagreement)
        if BELOW_BASE_RE.search(blob) or "market appears to price" in blob.lower():
            unsupported.append("market_disagreement talks about the tape but last_close/spot is missing on this valuation object")
            stale.append("tape language may be leaking from another pack or from model memory")

    customer_rows = []
    for item in grounded_top:
        if "customer" in (item.get("fact") or "").lower() or "capex" in (item.get("fact") or "").lower() or "capital expend" in (item.get("fact") or "").lower():
            customer_rows.append(
                {
                    **{k: item.get(k) for k in ("evidence_id", "fact", "excerpt", "source", "source_url", "source_date", "evidence_family")},
                    "proof_class": item.get("customer_proof_class"),
                    "named_customer": item.get("customer_proof_class") == "C",
                    "may_not_promote_to": ["C"] if item.get("customer_proof_class") in {"A", "B_issuer_claim"} else [],
                }
            )

    delta = attribute_target_change(previous_valuation, valuation) if previous_valuation else None
    verdict = "FAIL" if (unsupported or dropped_top or (stance["code"] == "market_above_bull" and BELOW_BASE_RE.search(json_blob(disagreement)))) else "PASS"
    if warnings and verdict == "PASS" and (stance["code"] in {"market_above_bull", "incomparable"}):
        verdict = "FAIL"

    audit = {
        "verdict": verdict,
        "valuation_consistency": {
            "python_engine_targets": python_targets,
            "snapshot": snap,
            "previous_delta": delta,
            "llm_replaced_numbers": False,
        },
        "thesis_vs_valuation": stance,
        "evidence_grounding": {
            "top_thesis_changing_evidence": grounded_top,
            "dropped": dropped_top,
            "capacity_target": {
                "grounded": bool(allowed_capacity),
                "numbers_in_evidence": sorted(allowed_capacity),
                "evidence_ids": [str(row.get("id")) for row in capacity_rows[:5]],
                "rows": [row for row in (hydrate_evidence(str(item.get("id")), index, ticker=symbol) for item in capacity_rows[:3]) if row],
            },
        },
        "customer_evidence_boundary": customer_rows,
        "unsupported_llm_claims": unsupported,
        "hallucination_or_stale_context": stale,
        "warnings": warnings,
        "claim_grades": claim_grades[:20],
        "decisive_variable_mapping": [
            {
                "name": row.get("name"),
                "supporting_evidence_ids": row.get("supporting_evidence_ids"),
                "opposing_evidence_ids": row.get("opposing_evidence_ids"),
                "missing_evidence": row.get("missing_evidence"),
            }
            for row in mapped_vars
        ],
        "competing_hypotheses": [
            {
                "statement": row.get("statement"),
                "supporting_evidence_ids": row.get("supporting_evidence_ids"),
                "opposing_evidence_ids": row.get("opposing_evidence_ids"),
                "missing_evidence": row.get("missing_evidence"),
                "confidence_band": row.get("confidence_band"),
                "speculative_hypothesis": row.get("speculative_hypothesis"),
                "grade": row.get("grade"),
            }
            for row in mapped_h
        ],
    }
    reasoning["consistency_audit"] = audit
    reasoning["claim_grades"] = claim_grades[:20]
    reasoning["consistency_warnings"] = warnings
    reasoning["valuation_stance"] = stance
    return audit


def json_blob(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)
