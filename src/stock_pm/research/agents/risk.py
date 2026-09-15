from __future__ import annotations

from typing import Any, Protocol

from ..extract import (
    extract_risk_mentions,
    official_documents,
    source_type_for_document,
    transcript_materials,
)
from ..llm_reason import (
    attach_audit,
    clean_hypotheses,
    clean_link,
    clean_proposal,
    compact_assumptions,
    compact_evidence,
    compact_pack,
    complete_structured,
    dump_user,
    known_ids,
)
from ..relevance import annotate_evidence, hard_opposing_links, judged_links
from ..templates import load_prompt
from ..types import AGENT_RISK, AGENT_SEARCH, AgentInput, AgentOutput, FollowUpSpec
from .base import BaseAgent


PROMPT_VERSION = "sprint55-risk-v1"

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

    def run(self, payload: AgentInput) -> AgentOutput:
        grounded = self.observe(payload)
        allowed = known_ids(grounded.new_evidence, payload.evidence, payload.assumptions)
        user = dump_user(
            {
                "ticker": payload.ticker,
                "research_pack": compact_pack(payload.research_pack),
                "assumptions": compact_assumptions(payload.assumptions, limit=8),
                "candidate_evidence": compact_evidence(list(payload.evidence) + list(grounded.new_evidence), limit=20),
                "deterministic_findings": grounded.findings,
                "rules": [
                    "Generate competing hypotheses. Cite only existing evidence ids.",
                    "Do not mint evidence. Probability bands only, never 37%.",
                ],
            }
        )
        raw, audit = complete_structured(
            self.completer,
            system=self.system_prompt,
            user=user,
            allowed_ids=allowed or None,
        )
        extra = {"llm_role": "competing_hypotheses", "linking": "deterministic_fallback"}
        if raw:
            assumption_ids = {str(row.get("id") or "") for row in payload.assumptions if row.get("id")}
            evidence_ids = known_ids(grounded.new_evidence, payload.evidence)
            hypotheses = clean_hypotheses(raw.get("competing_hypotheses"), evidence_ids=evidence_ids)
            extra["competing_hypotheses"] = hypotheses
            links = [
                item
                for item in (clean_link(row, assumption_ids=assumption_ids, evidence_ids=evidence_ids) for row in (raw.get("assumption_links") or []))
                if item
            ]
            proposals = [
                item
                for item in (clean_proposal(row, assumption_ids=assumption_ids) for row in (raw.get("proposed_assumption_changes") or []))
                if item
            ]
            if links:
                grounded.assumption_links = links
                extra["linking"] = "llm"
            if proposals:
                grounded.proposed_assumption_changes = proposals
            if hypotheses:
                extra["hypothesis_engine"] = "llm"
        grounded = attach_audit(grounded, audit, extra)
        grounded.agent_name = self.name
        grounded.prompt_version = self.prompt_version
        from ..schema import validate_agent_output

        return validate_agent_output(grounded, agent_name=self.name)

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

        def add_hit(hit: dict[str, Any], *, source: str, source_url: Any, source_time: Any, source_type: str) -> None:
            quote = str(hit.get("quote") or "").strip()
            key = quote.lower()
            if not quote or not source_time or key in seen:
                return
            seen.add(key)
            evidence.append(
                annotate_evidence(
                    {
                        "_key": f"risk-{len(evidence)+1}",
                        "evidence_type": "industry" if _risk_kind(quote) == "demand" else "fundamental",
                        "fact": quote,
                        "excerpt": quote,
                        "source": source,
                        "source_url": source_url,
                        "source_time": source_time,
                        "source_type": source_type,
                        "direction": "neutral",
                        "confidence": 0.7,
                        "importance": "high",
                        "raw_reference": {"kind": _risk_kind(quote), "source_type": source_type},
                    }
                )
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
                        annotate_evidence(
                            {
                                "_key": f"risk-{len(evidence)+1}",
                                "evidence_type": "quant",
                                "fact": fact,
                                "excerpt": fact,
                                "source": "daily_price_bars",
                                "source_time": fallback,
                                "source_type": "structured_provider",
                                "direction": "neutral",
                                "confidence": 0.5,
                                "raw_reference": {"post_5d_return_pct": post_5d, "pe_ttm": pe},
                            }
                        )
                    )

        if evidence:
            findings.append(f"located {len(evidence)} risk snippets or market-context facts")
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
            links = judged_links(evidence, assumption, allow_support=False, allow_oppose=True, limit=4)
            assumption_links.extend(links)
            hard = hard_opposing_links(links)
            current = assumption.get("confidence")
            try:
                current_conf = float(current) if current is not None else 0.5
            except (TypeError, ValueError):
                current_conf = 0.5
            gaps = list(missing[:5])
            if hard:
                challenged.append(assumption_id)
                proposed = "broken" if any(item.get("strength") == "strong" for item in hard) and len(hard) >= 2 else "weaken"
                delta = -0.12 if proposed == "broken" else -0.07
                reason = "hard opposing evidence: " + "; ".join(str(item.get("reason") or "") for item in hard[:2])
            else:
                proposed = "unchanged"
                delta = 0.0
                reason = "未发现足够反证"
                gaps.append("未发现足够反证")
            proposals.append(
                {
                    "assumption_id": assumption_id,
                    "statement": assumption.get("statement"),
                    "proposed_status": proposed,
                    "reason": reason,
                    "confidence": round(min(0.85, max(0.15, current_conf + delta)), 3),
                    "current_confidence": current_conf,
                    "confidence_delta": delta,
                    "reasoning": {
                        "positives": [],
                        "limits": gaps,
                        "why": reason,
                    },
                    "unresolved_gaps": list(dict.fromkeys(gaps)),
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
