from __future__ import annotations

from typing import Any

from ..extract import (
    beat_label,
    extract_commitments,
    extract_guidance_mentions,
    guidance_move_from_history,
    has_transcript_source,
    to_number,
    transcript_materials,
    yoy_from_quarters,
)
from ..templates import load_prompt, load_template
from ..types import AGENT_FUNDAMENTAL, AGENT_SEARCH, AgentInput, AgentOutput, FollowUpSpec
from .base import BaseAgent, JsonCompleter


PROMPT_VERSION = "sprint2-fundamental-v1"


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

    def run(self, payload: AgentInput) -> AgentOutput:
        output = super().run(payload)
        if has_transcript_source(payload.research_pack or {}):
            return output
        cleaned = []
        for item in output.new_evidence:
            ref = item.get("raw_reference") or {}
            kind = ref.get("kind") if isinstance(ref, dict) else None
            if str(item.get("evidence_type") or "") == "transcript" or kind == "management_commitment":
                continue
            cleaned.append(item)
        output.new_evidence = cleaned
        return output

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
                    raw_reference=latest.get("ref") or {},
                    importance="high",
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

        text = transcript_materials(pack) if has_transcript_source(pack) else ""
        commitments = extract_commitments(text) if text else []
        guidance_hits = extract_guidance_mentions(text) if text else []
        transcript_meta = (profile.get("transcripts") or [{}])[0]
        transcript_source = str(transcript_meta.get("source") or "earnings call")
        transcript_time = transcript_meta.get("source_time") or transcript_meta.get("published_at") or _stamp(latest)
        if not has_transcript_source(pack):
            if "transcripts" not in missing:
                missing.append("transcripts")
            findings.append("transcripts missing; management commitment evidence not minted")
        for hit in commitments:
            if not transcript_time:
                continue
            add_evidence(
                fact=hit["quote"],
                source=transcript_source,
                source_time=transcript_time,
                evidence_type="transcript",
                importance="high",
                raw_reference={"kind": "management_commitment"},
            )
            findings.append("management commitment located in source text")
        for hit in guidance_hits:
            if not transcript_time:
                continue
            add_evidence(
                fact=hit["quote"],
                source=transcript_source,
                source_time=transcript_time,
                evidence_type="transcript",
                raw_reference={"kind": "guidance", "move": hit.get("move")},
            )
        for row in guidance:
            stamp = _stamp(row, _stamp(latest))
            text_row = str(row.get("text") or row.get("quote") or row.get("summary") or "").strip()
            if not text_row or not stamp:
                continue
            add_evidence(
                fact=text_row,
                source=str(row.get("source") or "guidance"),
                source_time=stamp,
                evidence_type="guidance",
                raw_reference={"move": row.get("move")},
            )
        move = guidance_move_from_history(guidance) or (guidance_hits[0].get("move") if guidance_hits else None)
        if move:
            findings.append(f"guidance language indicates {move}")

        def propose(statement: str, *, category: str, importance: str, keys: list[str], reason: str) -> None:
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
            )
        elif latest.get("revenue") is not None:
            propose(
                "The latest revenue print is a sustainable run-rate rather than a one-off",
                category="demand",
                importance="medium",
                keys=growth_keys or [item["_key"] for item in evidence[:1]],
                reason="need more prints and demand checks",
            )
        if move:
            propose(
                f"Management can deliver the latest {move} guidance",
                category="guidance_delivery",
                importance="high",
                keys=[item["_key"] for item in evidence if item.get("evidence_type") in {"guidance", "transcript"}],
                reason="guidance delivery must be checked against later prints",
            )
        elif prints_with_estimate:
            propose(
                "Management can continue to meet consensus on upcoming prints",
                category="guidance_delivery",
                importance="medium",
                keys=[item["_key"] for item in evidence if "beat consensus" in str(item.get("fact") or "")],
                reason="historical beat rate is not proof of the next print",
            )
        if commitments:
            propose(
                "Management's stated long-term operating target can be delivered",
                category="execution",
                importance="critical",
                keys=[item["_key"] for item in evidence if item.get("evidence_type") == "transcript"],
                reason="long-term target is a claim until demand, supply, and capex are checked",
            )
        if latest:
            propose(
                "End-customer demand is real enough to support the current growth plan",
                category="demand",
                importance="high",
                keys=growth_keys,
                reason="customer capex and orders are not yet independently confirmed",
            )

        seen = set()
        unique_assumptions = []
        for item in assumptions:
            key = item["statement"]
            if key in seen:
                continue
            seen.add(key)
            unique_assumptions.append(item)
        assumptions = unique_assumptions[:6]

        def follow(title: str, *, required: tuple[str, ...], assumption: dict[str, Any] | None = None, reason: str) -> None:
            required_data = list(required)
            description = title
            if assumption:
                required_data.append("assumption:" + str(assumption.get("statement") or title)[:80])
                description = f"{title}. Related assumption: {assumption['statement']}"
            follow_ups.append(
                FollowUpSpec(
                    title=title,
                    description=description,
                    task_type="verify_assumption",
                    assigned_agents=(AGENT_SEARCH,),
                    required_data=tuple(required_data),
                    source_reason=reason,
                    priority=40,
                )
            )

        if commitments:
            follow("Verify whether stated demand is confirmed by customers", required=("customer_capex", "orders"), assumption=assumptions[0] if assumptions else None, reason="commitment_follow_up")
            follow("Verify whether supply and capacity can support the stated plan", required=("supply_capacity", "foundry"), reason="commitment_follow_up")
            follow("Verify whether capex can support the stated plan", required=("capex",), reason="commitment_follow_up")
        follow("Check historical management delivery against prior guidance", required=("guidance_history",), reason="delivery_follow_up")
        for axis in template.get("question_axes") or []:
            axis_id = str(axis.get("id") or "")
            question = str(axis.get("question") or "").strip()
            if not axis_id or not question:
                continue
            if any(axis_id in " ".join(spec.required_data) for spec in follow_ups):
                continue
            follow(question, required=(axis_id,), reason="template_axis")
            if sum(1 for spec in follow_ups if spec.source_reason == "template_axis") >= 6:
                break

        if not earnings:
            findings.append("no earnings history in the research pack; facts not invented")
        if missing:
            findings.append("pack missing: " + ", ".join(missing[:8]))

        confidence = 0.2
        if earnings:
            confidence = 0.45
        if commitments:
            confidence = min(0.75, confidence + 0.2)
        if move:
            confidence = min(0.8, confidence + 0.1)

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
