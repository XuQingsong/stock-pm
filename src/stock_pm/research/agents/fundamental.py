from __future__ import annotations

from typing import Any

from ..deep_case import build_delivery_history
from ..extract import (
    beat_label,
    extract_commitments,
    extract_guidance_mentions,
    followups_from_claim,
    guidance_move_from_history,
    has_official_source,
    has_transcript_source,
    official_documents,
    source_type_for_document,
    to_number,
    transcript_materials,
    yoy_from_quarters,
)
from ..templates import load_prompt, load_template
from ..types import AGENT_FUNDAMENTAL, AGENT_INDUSTRY, AGENT_QUANT, AGENT_RISK, AGENT_SEARCH, AgentInput, AgentOutput, FollowUpSpec
from .base import BaseAgent, JsonCompleter


PROMPT_VERSION = "sprint5-fundamental-v1"


def _stamp(row: dict[str, Any], fallback: str | None = None) -> str | None:
    return (
        row.get("report_date")
        or row.get("source_time")
        or row.get("period_end")
        or row.get("published_at")
        or fallback
    )


def _source_for(row: dict[str, Any]) -> str:
    return str(row.get("source") or "earnings_reports")


class FundamentalAgent(BaseAgent):
    name = AGENT_FUNDAMENTAL
    prompt_version = PROMPT_VERSION

    def __init__(self, completer: JsonCompleter | None = None) -> None:
        super().__init__(completer=completer, system_prompt=load_prompt("fundamental.txt"))

    def observe(self, payload: AgentInput) -> AgentOutput:
        pack = payload.research_pack or {}
        profile = pack.get("company_profile") or {}
        earnings = list(pack.get("earnings_history") or [])
        guidance = list(pack.get("guidance_history") or [])
        missing = list(pack.get("missing_fields") or [])
        template = load_template(pack.get("template_id"))
        findings: list[str] = []
        evidence: list[dict[str, Any]] = []
        assumptions: list[dict[str, Any]] = []
        follow_ups: list[FollowUpSpec] = []

        def add_evidence(**item: Any) -> str:
            key = item.get("_key") or f"fund-{len(evidence)+1}"
            item["_key"] = key
            item.setdefault("evidence_type", "fundamental")
            item.setdefault("direction", "neutral")
            item.setdefault("excerpt", item.get("fact"))
            item.setdefault("source_type", "structured_provider")
            item.setdefault("confidence", 0.55 if item["source_type"] == "structured_provider" else 0.75)
            evidence.append(item)
            return str(key)

        latest = earnings[0] if earnings else {}
        if latest:
            fact_bits = []
            if latest.get("revenue") is not None:
                fact_bits.append(f"revenue={latest['revenue']}")
            if latest.get("eps") is not None:
                fact_bits.append(f"EPS={latest['eps']}")
            if latest.get("margin_pct") is not None:
                fact_bits.append(f"net margin={latest['margin_pct']}%")
            if latest.get("fcf") is not None:
                fact_bits.append(f"FCF={latest['fcf']}")
            if fact_bits and _stamp(latest):
                add_evidence(
                    fact=f"Latest print {latest.get('fiscal_period') or ''}: " + ", ".join(fact_bits),
                    source=_source_for(latest),
                    source_time=_stamp(latest),
                    source_url=(latest.get("ref") or {}).get("url") if isinstance(latest.get("ref"), dict) else None,
                    raw_reference=latest.get("ref") or {},
                    importance="high",
                    excerpt=", ".join(fact_bits),
                )
            rev_beat = beat_label(to_number(latest.get("revenue")), to_number(latest.get("revenue_estimate")))
            eps_beat = beat_label(to_number(latest.get("eps")), to_number(latest.get("eps_estimate")))
            if rev_beat and latest.get("revenue_estimate") is not None:
                add_evidence(
                    fact=(
                        f"Revenue {rev_beat} vs consensus "
                        f"(actual={latest.get('revenue')}, estimate={latest.get('revenue_estimate')})"
                    ),
                    source=_source_for(latest),
                    source_time=_stamp(latest),
                    raw_reference=latest.get("ref") or {},
                    direction="support" if rev_beat == "beat" else "oppose" if rev_beat == "miss" else "neutral",
                )
                findings.append(f"latest revenue {rev_beat} versus consensus")
            if eps_beat and latest.get("eps_estimate") is not None:
                add_evidence(
                    fact=(
                        f"EPS {eps_beat} vs consensus "
                        f"(actual={latest.get('eps')}, estimate={latest.get('eps_estimate')})"
                    ),
                    source=_source_for(latest),
                    source_time=_stamp(latest),
                    raw_reference=latest.get("ref") or {},
                    direction="support" if eps_beat == "beat" else "oppose" if eps_beat == "miss" else "neutral",
                )
        revenue_yoy = to_number(profile.get("revenue_growth_yoy_pct")) or yoy_from_quarters(earnings, "revenue")
        eps_yoy = to_number(profile.get("eps_growth_yoy_pct")) or yoy_from_quarters(earnings, "eps")
        if revenue_yoy is not None and latest:
            add_evidence(
                fact=f"Quarterly revenue year-over-year change is {revenue_yoy}%",
                source=_source_for(latest),
                source_time=_stamp(latest),
                raw_reference={"field": "revenue", "yoy_pct": revenue_yoy},
                importance="high",
            )
            findings.append(f"revenue YoY {revenue_yoy}%")
        if eps_yoy is not None and latest:
            add_evidence(
                fact=f"Quarterly EPS year-over-year change is {eps_yoy}%",
                source=_source_for(latest),
                source_time=_stamp(latest),
                raw_reference={"field": "eps", "yoy_pct": eps_yoy},
            )
        for row in earnings[:2]:
            for segment in row.get("segments") or []:
                if not segment.get("name"):
                    continue
                growth = segment.get("growth_yoy_pct")
                add_evidence(
                    fact=(
                        f"Segment {segment['name']}: revenue={segment.get('revenue')}"
                        + (f", YoY={growth}%" if growth is not None else "")
                    ),
                    source=_source_for(row),
                    source_time=_stamp(row),
                    raw_reference={"segment": segment["name"], "ref": row.get("ref")},
                    evidence_type="fundamental",
                )
                findings.append(f"segment {segment['name']} present in the print")

        prints_with_estimate = [
            row for row in earnings if row.get("eps") is not None and row.get("eps_estimate") is not None
        ]
        beats = [row for row in prints_with_estimate if beat_label(to_number(row.get("eps")), to_number(row.get("eps_estimate"))) == "beat"]
        if prints_with_estimate:
            findings.append(f"EPS beat {len(beats)} of last {len(prints_with_estimate)} estimated prints")
            add_evidence(
                fact=f"EPS beat consensus in {len(beats)} of the last {len(prints_with_estimate)} prints with estimates",
                source=_source_for(prints_with_estimate[0]),
                source_time=_stamp(prints_with_estimate[0]),
                raw_reference={"sample": len(prints_with_estimate)},
            )
        delivery = build_delivery_history(pack)
        if delivery.get("prints_scored") and latest:
            findings.append("management delivery history: " + str(delivery.get("summary") or ""))
            add_evidence(
                fact="Management delivery versus consensus: " + str(delivery.get("summary") or ""),
                source=_source_for(latest),
                source_time=_stamp(latest),
                evidence_type="fundamental",
                raw_reference={"kind": "management_delivery", "history": delivery.get("history") or []},
                importance="high",
            )

        material_rows: list[dict[str, Any]] = []
        for doc in official_documents(pack):
            text = str(doc.get("text") or doc.get("body") or "")
            if not text.strip():
                continue
            source_type = source_type_for_document(doc)
            material_rows.append(
                {
                    "text": text,
                    "source": str(doc.get("source") or doc.get("source_provider") or "official"),
                    "source_url": doc.get("url") or doc.get("source_url"),
                    "source_time": doc.get("published_at") or doc.get("source_time") or _stamp(latest),
                    "source_type": source_type,
                    "evidence_type": "filing" if source_type == "sec_filing" else "guidance",
                    "allow_commitments": True,
                }
            )
        transcript_text = transcript_materials(pack) if has_transcript_source(pack) else ""
        if transcript_text:
            transcript_meta = (profile.get("transcripts") or [{}])[0]
            material_rows.append(
                {
                    "text": transcript_text,
                    "source": str(transcript_meta.get("source") or "earnings call"),
                    "source_url": transcript_meta.get("source_url"),
                    "source_time": transcript_meta.get("source_time") or transcript_meta.get("published_at") or _stamp(latest),
                    "source_type": "transcript",
                    "evidence_type": "transcript",
                }
            )
        if not has_transcript_source(pack) and "transcripts" not in missing:
            missing.append("transcripts")
        if not has_official_source(pack) and not has_transcript_source(pack):
            findings.append("no official document or transcript text; management claims not invented")

        commitments: list[dict[str, Any]] = []
        guidance_hits: list[dict[str, Any]] = []
        seen_quotes: set[str] = set()
        for material in material_rows:
            stamp = material.get("source_time")
            if not stamp:
                continue
            if material.get("allow_commitments", True):
                for hit in extract_commitments(material["text"])[:8]:
                    key = hit["quote"].lower()
                    if key in seen_quotes:
                        continue
                    seen_quotes.add(key)
                    commitments.append({**hit, **material})
                    add_evidence(
                        fact=hit["quote"],
                        excerpt=hit["quote"],
                        source=material["source"],
                        source_url=material.get("source_url"),
                        source_time=stamp,
                        source_type=material["source_type"],
                        evidence_type=material["evidence_type"],
                        importance="high",
                        confidence=0.8,
                        raw_reference={"kind": "management_commitment", "source_type": material["source_type"]},
                    )
                    findings.append("management commitment located in source text")
            for hit in extract_guidance_mentions(material["text"])[:8]:
                key = "g:" + hit["quote"].lower()
                if key in seen_quotes:
                    continue
                seen_quotes.add(key)
                guidance_hits.append({**hit, **material})
                add_evidence(
                    fact=hit["quote"],
                    excerpt=hit["quote"],
                    source=material["source"],
                    source_url=material.get("source_url"),
                    source_time=stamp,
                    source_type=material["source_type"],
                    evidence_type="guidance",
                    confidence=0.8,
                    raw_reference={"kind": "guidance", "move": hit.get("move"), "source_type": material["source_type"]},
                )
        for row in guidance:
            stamp = _stamp(row, _stamp(latest))
            text_row = str(row.get("text") or row.get("quote") or row.get("summary") or "").strip()
            if not text_row or not stamp:
                continue
            if text_row.lower() in seen_quotes:
                continue
            add_evidence(
                fact=text_row,
                excerpt=str(row.get("excerpt") or text_row),
                source=str(row.get("source") or "guidance"),
                source_url=row.get("url") or row.get("source_url"),
                source_time=stamp,
                source_type=str(row.get("source_type") or "earnings_release"),
                evidence_type="guidance",
                confidence=0.75,
                raw_reference={"move": row.get("move")},
            )
        move = guidance_move_from_history(guidance) or (guidance_hits[0].get("move") if guidance_hits else None)
        if move:
            findings.append(f"guidance language indicates {move}")

        def propose(statement: str, *, category: str, importance: str, keys: list[str], reason: str, source_type: str) -> None:
            links = [
                {"evidence_key": key, "direction": "support", "strength": "moderate", "reason": reason}
                for key in keys[:3]
            ]
            assumptions.append(
                {
                    "statement": statement,
                    "category": category,
                    "importance": importance,
                    "thesis_role": "supporting",
                    "links": links,
                    "next_verification": reason,
                    "source_type": source_type,
                }
            )

        growth_keys = [item["_key"] for item in evidence if "year-over-year" in str(item.get("fact") or "").lower() or "latest print" in str(item.get("fact") or "").lower()]
        if revenue_yoy is not None:
            propose(
                "Recent revenue growth can persist over the next two years",
                category="demand",
                importance="high",
                keys=growth_keys,
                reason="growth print needs demand and supply confirmation",
                source_type="template_seed",
            )
        elif latest.get("revenue") is not None:
            propose(
                "The latest revenue print is a sustainable run-rate rather than a one-off",
                category="demand",
                importance="medium",
                keys=growth_keys or [item["_key"] for item in evidence[:1]],
                reason="need more prints and demand checks",
                source_type="template_seed",
            )
        if move:
            propose(
                f"Management can deliver the latest {move} guidance",
                category="guidance_delivery",
                importance="high",
                keys=[item["_key"] for item in evidence if item.get("evidence_type") in {"guidance", "transcript"}],
                reason="guidance delivery must be checked against later prints",
                source_type="evidence_discovered" if guidance_hits or guidance else "template_seed",
            )
        elif prints_with_estimate:
            propose(
                "Management can continue to meet consensus on upcoming prints",
                category="guidance_delivery",
                importance="medium",
                keys=[item["_key"] for item in evidence if "beat consensus" in str(item.get("fact") or "")],
                reason="historical beat rate is not proof of the next print",
                source_type="template_seed",
            )
        for hit in commitments[:4]:
            quote = str(hit.get("quote") or "")
            propose(
                f"Management can deliver the stated commitment: {quote[:180]}",
                category="execution",
                importance="critical",
                keys=[item["_key"] for item in evidence if item.get("fact") == quote],
                reason="stated commitment is a claim until demand, supply, and timing are checked",
                source_type="evidence_discovered",
            )

        seen = set()
        unique_assumptions = []
        for item in assumptions:
            key = item["statement"]
            if key in seen:
                continue
            seen.add(key)
            unique_assumptions.append(item)
        assumptions = unique_assumptions[:8]

        def _assigned_for(required: tuple[str, ...]) -> tuple[str, ...]:
            hay = " ".join(required).lower()
            if any(
                token in hay
                for token in (
                    "customer",
                    "capex",
                    "supply",
                    "capacity",
                    "competition",
                    "end_demand",
                    "end_market",
                    "power",
                    "foundry",
                    "design_win",
                    "contract",
                )
            ):
                return (AGENT_INDUSTRY,)
            if any(token in hay for token in ("price", "valuation", "reaction")):
                return (AGENT_QUANT,)
            if any(token in hay for token in ("risk", "miss", "margin", "concentration")):
                return (AGENT_RISK,)
            return (AGENT_SEARCH,)

        def follow(
            title: str,
            *,
            required: tuple[str, ...],
            assumption: dict[str, Any] | None = None,
            reason: str,
            source_type: str,
            description: str | None = None,
            priority: int = 40,
        ) -> None:
            required_data = list(required)
            text = description or title
            if assumption:
                required_data.append("assumption:" + str(assumption.get("statement") or title)[:80])
                text = f"{text}. Related assumption: {assumption['statement']}"
            follow_ups.append(
                FollowUpSpec(
                    title=title,
                    description=text,
                    task_type="verify_assumption",
                    assigned_agents=_assigned_for(tuple(required_data)),
                    required_data=tuple(required_data),
                    source_reason=reason,
                    source_type=source_type,
                    priority=priority,
                )
            )

        seen_follow: set[str] = set()
        for hit in commitments + guidance_hits:
            quote = str(hit.get("quote") or "")
            for spec in followups_from_claim(quote):
                title = spec["title"]
                if title.lower() in seen_follow:
                    continue
                seen_follow.add(title.lower())
                related = next((row for row in assumptions if row.get("source_type") == "evidence_discovered"), None)
                follow(
                    title,
                    required=(spec["required_data"],),
                    assumption=related,
                    reason="evidence_discovered",
                    source_type="evidence_discovered",
                    description=f"Generated from management claim: {quote[:240]}",
                    priority=25,
                )
                if sum(1 for item in follow_ups if item.source_type == "evidence_discovered") >= 8:
                    break
            if sum(1 for item in follow_ups if item.source_type == "evidence_discovered") >= 8:
                break

        follow(
            "Check historical management delivery against prior guidance",
            required=("guidance_history",),
            reason="delivery_follow_up",
            source_type="assumption_gap",
        )
        for axis in template.get("question_axes") or []:
            axis_id = str(axis.get("id") or "")
            question = str(axis.get("question") or "").strip()
            if not axis_id or not question:
                continue
            if any(axis_id in " ".join(spec.required_data) for spec in follow_ups):
                continue
            follow(question, required=(axis_id,), reason="template_axis", source_type="template_seed")
            if sum(1 for spec in follow_ups if spec.source_type == "template_seed") >= 6:
                break

        if not earnings:
            findings.append("no earnings history in the research pack; facts not invented")
        if missing:
            findings.append("pack missing: " + ", ".join(missing[:8]))

        confidence = 0.2
        if earnings:
            confidence = 0.45
        if commitments:
            confidence = min(0.8, confidence + 0.25)
        if move:
            confidence = min(0.85, confidence + 0.1)
        if has_official_source(pack):
            confidence = min(0.85, confidence + 0.1)

        return AgentOutput(
            findings=findings,
            new_evidence=evidence,
            new_assumptions=assumptions,
            follow_up_tasks=follow_ups,
            missing_data=missing,
            confidence=confidence,
            agent_name=self.name,
            prompt_version=self.prompt_version,
        )
