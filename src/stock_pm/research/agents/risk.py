from __future__ import annotations

from typing import Any, Protocol

from ..extract import (
    extract_risk_mentions,
    official_documents,
    source_type_for_document,
    transcript_materials,
)
from ..templates import load_prompt
from ..types import AGENT_RISK, AGENT_SEARCH, AgentInput, AgentOutput, FollowUpSpec
from .base import BaseAgent


PROMPT_VERSION = "sprint3-risk-v1"

RISK_LABELS = (
    "demand risk",
    "execution risk",
    "customer concentration",
    "margin risk",
    "valuation risk",
)


class SearchTools(Protocol):
    def fetch_url(self, url: str) -> dict[str, Any]: ...
    def web_search(self, query: str) -> list[dict[str, str]]: ...
    def official_documents(self, symbol: str, filings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]: ...


def _stamp(row: dict[str, Any], fallback: str | None = None) -> str | None:
    return row.get("published_at") or row.get("source_time") or row.get("report_date") or fallback


def _risk_kind(quote: str) -> str:
    hay = quote.lower()
    if "customer" in hay or "concentration" in hay:
        return "concentration"
    if "margin" in hay:
        return "margin"
    if any(token in hay for token in ("delay", "execution", "ramp", "slip")):
        return "execution"
    if any(token in hay for token in ("pull-in", "inventory", "temporary", "commodity")):
        return "demand"
    return "other"


class RiskAgent(BaseAgent):
    name = AGENT_RISK
    prompt_version = PROMPT_VERSION

    def __init__(self, completer=None, tools: SearchTools | None = None) -> None:
        super().__init__(completer=completer, system_prompt=load_prompt("risk.txt"))
        self.tools = tools

    def observe(self, payload: AgentInput) -> AgentOutput:
        pack = payload.research_pack or {}
        findings: list[str] = []
        evidence: list[dict[str, Any]] = []
        missing: list[str] = []
        seen: set[str] = set()
        fallback = None
        earnings = list(pack.get("earnings_history") or [])
        if earnings:
            fallback = earnings[0].get("report_date")

        def add_hit(hit: dict[str, Any], *, source: str, source_url: Any, source_time: Any, source_type: str, direction: str = "oppose") -> None:
            quote = str(hit.get("quote") or "").strip()
            key = quote.lower()
            if not quote or not source_time or key in seen:
                return
            seen.add(key)
            evidence.append(
                {
                    "_key": f"risk-{len(evidence)+1}",
                    "evidence_type": "industry" if _risk_kind(quote) == "demand" else "fundamental",
                    "fact": quote,
                    "excerpt": quote,
                    "source": source,
                    "source_url": source_url,
                    "source_time": source_time,
                    "source_type": source_type,
                    "direction": direction,
                    "confidence": 0.7,
                    "importance": "high",
                    "raw_reference": {"kind": _risk_kind(quote), "source_type": source_type},
                }
            )

        materials = list(official_documents(pack))
        profile = pack.get("company_profile") or {}
        for item in profile.get("transcripts") or []:
            materials.append(
                {
                    "text": str(item.get("text") or ""),
                    "source": item.get("source") or "earnings call",
                    "url": item.get("source_url"),
                    "published_at": item.get("source_time") or item.get("published_at"),
                    "source_type": "transcript",
                }
            )
        extra = transcript_materials(pack)
        if extra:
            materials.append({"text": extra, "source": "earnings call", "published_at": fallback, "source_type": "transcript"})

        if self.tools is not None:
            try:
                materials.extend(self.tools.official_documents(payload.ticker, None) or [])
            except Exception as exc:
                findings.append(f"risk official fetch incomplete: {exc}")

        for material in materials:
            text = str(material.get("text") or material.get("body") or "")
            stamp = _stamp(material, fallback)
            if not text.strip() or not stamp:
                continue
            for hit in extract_risk_mentions(text)[:8]:
                add_hit(
                    hit,
                    source=str(material.get("source") or material.get("source_provider") or "official"),
                    source_url=material.get("url") or material.get("source_url"),
                    source_time=stamp,
                    source_type=source_type_for_document(material),
                )

        alt_explanations = []
        hay = " ".join(str(item.get("fact") or "") for item in evidence).lower()
        if any(token in hay for token in ("pull-in", "inventory", "temporary", "channel")):
            alt_explanations.append("recent growth may reflect pull-in or inventory rather than end demand")
        if any(token in hay for token in ("delay", "slip", "push-out", "shortfall")):
            alt_explanations.append("stated ramps may slip, which is an execution alternative to the bullish delivery claim")
        if any(token in hay for token in ("concentration", "largest customer", "single customer")):
            alt_explanations.append("revenue may depend on a small customer set")
        if any(token in hay for token in ("margin", "compress", "pressure")):
            alt_explanations.append("mix or cost pressure may offset volume growth")

        for assumption in payload.assumptions:
            statement = str(assumption.get("statement") or "").lower()
            if "persist" in statement or "sustain" in statement:
                alt_explanations.append("growth persistence may be a cycle or mix effect rather than a durable demand shift")
                break

        pe = (pack.get("company_profile") or {}).get("pe_ttm")
        reaction = (pack.get("price_reaction_history") or [{}])[0]
        post_5d = reaction.get("post_5d_return_pct")
        if pe is not None or post_5d is not None:
            findings.append("valuation risk is qualitative only; no target price is formed")
            if post_5d is not None and fallback:
                fact = f"Post-print 5d return is {post_5d}%; this is a valuation-risk context fact, not an investment conclusion"
                if fact.lower() not in seen:
                    evidence.append(
                        {
                            "_key": f"risk-{len(evidence)+1}",
                            "evidence_type": "quant",
                            "fact": fact,
                            "excerpt": fact,
                            "source": "daily_price_bars",
                            "source_time": fallback,
                            "source_type": "structured_provider",
                            "direction": "oppose",
                            "confidence": 0.5,
                            "raw_reference": {"post_5d_return_pct": post_5d, "pe_ttm": pe},
                        }
                    )

        if evidence:
            findings.append(f"located {len(evidence)} counter-facts or risk snippets")
        else:
            findings.append("no explicit counter-facts were located; absence of opposition is itself a gap")
            missing.append("opposing_evidence")
        for label in RISK_LABELS:
            token = label.split()[0]
            if token == "customer":
                present = "concentration" in hay or "largest customer" in hay
            elif token == "valuation":
                present = post_5d is not None or pe is not None
            else:
                present = token in hay
            if present:
                findings.append(f"{label} has source language or market context")
            else:
                findings.append(f"{label} was scanned and not evidenced in source text")
                missing.append(label.replace(" ", "_"))
        for item in dict.fromkeys(alt_explanations):
            findings.append("alternative explanation: " + item)

        assumption_links = []
        proposals = []
        challenged = []
        for assumption in payload.assumptions:
            assumption_id = str(assumption.get("id") or "")
            if not assumption_id:
                continue
            category = str(assumption.get("category") or "")
            related = evidence[:2]
            if related:
                challenged.append(assumption_id)
                for item in related:
                    assumption_links.append(
                        {
                            "assumption_id": assumption_id,
                            "evidence_key": item.get("_key"),
                            "direction": "oppose" if item.get("direction") == "oppose" else "contextual",
                            "strength": "moderate" if category in {"demand", "execution", "guidance_delivery"} else "weak",
                            "reason": "skeptic pass attaches counter-evidence or an alternative reading",
                        }
                    )
            proposed = "unchanged"
            reason = "skeptic pass did not find enough source-backed opposition to change the suggestion"
            gaps = list(missing[:5])
            if related and any(item.get("direction") == "oppose" for item in related):
                proposed = "weaken"
                reason = "counter-evidence or concentration/execution language challenges this assumption"
            if not related:
                gaps.append("no opposing evidence linked by the skeptic pass")
            if category == "demand" and "demand_risk" in {item.replace(" ", "_") for item in missing}:
                gaps.append("demand risk still lacks a customer-side negative fact")
            proposals.append(
                {
                    "assumption_id": assumption_id,
                    "statement": assumption.get("statement"),
                    "proposed_status": proposed,
                    "reason": reason,
                    "confidence": 0.5 if related else 0.35,
                    "unresolved_gaps": gaps,
                }
            )

        follow_ups = []
        if missing:
            follow_ups.append(
                FollowUpSpec(
                    title="Collect missing counter-evidence for demand, execution, concentration, margin, or valuation",
                    description=", ".join(missing[:6]),
                    task_type="verify_assumption",
                    assigned_agents=(AGENT_SEARCH,),
                    required_data=tuple(missing[:5]),
                    source_reason="skeptic_gap",
                    source_type="assumption_gap",
                    priority=48,
                )
            )

        confidence = 0.35 if evidence else 0.2
        if any("concentration" in str(item.get("fact") or "").lower() for item in evidence):
            confidence = min(0.7, confidence + 0.15)
        return AgentOutput(
            findings=findings,
            new_evidence=evidence,
            challenged_assumption_ids=challenged,
            assumption_links=assumption_links,
            proposed_assumption_changes=proposals,
            follow_up_tasks=follow_ups,
            missing_data=list(dict.fromkeys(missing)),
            confidence=confidence,
            agent_name=self.name,
            prompt_version=self.prompt_version,
        )
