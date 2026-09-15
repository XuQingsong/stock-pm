from __future__ import annotations

from ..extract import extract_commitments, extract_guidance_mentions
from ..templates import load_prompt
from ..types import AGENT_SEARCH, AgentInput, AgentOutput, FollowUpSpec
from .base import BaseAgent, JsonCompleter


PROMPT_VERSION = "sprint2-search-v1"


def _assumption_ids_from_task(task: dict) -> list[str]:
    found: list[str] = []
    for item in task.get("required_data") or []:
        text = str(item)
        if text.startswith("assumption:"):
            found.append(text.split(":", 1)[1])
    description = str(task.get("description") or "")
    marker = "assumption_id="
    if marker in description:
        found.append(description.split(marker, 1)[1].split()[0].strip())
    return [item for item in found if item]


class SearchDataAgent(BaseAgent):
    name = AGENT_SEARCH
    prompt_version = PROMPT_VERSION

    def __init__(self, completer: JsonCompleter | None = None) -> None:
        super().__init__(completer=completer, system_prompt=load_prompt("search_data.txt"))

    def observe(self, payload: AgentInput) -> AgentOutput:
        pack = payload.research_pack or {}
        missing = list(pack.get("missing_fields") or [])
        needed = [str(item) for item in (payload.task.get("required_data") or []) if not str(item).startswith("assumption:")]
        evidence = []
        findings = []
        source_time = None
        profile = pack.get("company_profile") or {}
        for item in profile.get("transcripts") or []:
            source = str(item.get("source") or "earnings call")
            source_time = item.get("source_time") or item.get("published_at")
            text = str(item.get("text") or "")
            for excerpt in item.get("excerpts") or []:
                quote = excerpt.get("text") if isinstance(excerpt, dict) else str(excerpt)
                if quote:
                    text = f"{text}\n{quote}"
            if not text.strip() or not source_time:
                continue
            for hit in extract_commitments(text) + extract_guidance_mentions(text):
                evidence.append(
                    {
                        "_key": f"search-{len(evidence)+1}",
                        "evidence_type": "transcript",
                        "fact": hit["quote"],
                        "source": source,
                        "source_url": item.get("source_url"),
                        "source_time": source_time,
                        "raw_reference": {"kind": hit.get("kind"), "ref_table": "research_packs", "field": "company_profile.transcripts"},
                        "importance": "high" if hit.get("kind") == "management_commitment" else "medium",
                    }
                )
        for row in pack.get("major_events") or []:
            title = str(row.get("title") or "").strip()
            when = row.get("event_time")
            if not title or not when:
                continue
            evidence.append(
                {
                    "_key": f"search-event-{len(evidence)+1}",
                    "evidence_type": "news",
                    "fact": title,
                    "source": str(row.get("source") or "company_event"),
                    "source_url": row.get("url"),
                    "source_time": when,
                    "raw_reference": row.get("ref") or {},
                }
            )
        unresolved = []
        for field in needed or missing:
            label = str(field)
            if label in {"transcripts", "guidance_history", "fcf", "segment_growth"} and label in missing:
                unresolved.append(label)
            elif label and label not in {"assumption"} and not any(label in str(item.get("fact") or "") for item in evidence):
                if label in missing or label in needed:
                    unresolved.append(label)
        unresolved = list(dict.fromkeys(unresolved or [item for item in missing if item in {"transcripts", "guidance_history", "fcf"}]))
        if evidence:
            findings.append(f"located {len(evidence)} source-backed facts for {payload.ticker}")
        else:
            findings.append("no additional source documents were available beyond the research pack snapshot")
        if unresolved:
            findings.append("unresolved data: " + ", ".join(unresolved))

        assumption_ids = _assumption_ids_from_task(payload.task)
        links = []
        supported = []
        challenged = []
        for assumption_id in assumption_ids:
            if evidence:
                supported.append(assumption_id)
                links.append(
                    {
                        "assumption_id": assumption_id,
                        "evidence_key": evidence[0].get("_key"),
                        "direction": "contextual",
                        "strength": "weak",
                        "reason": "search located related source material; confirmation still open",
                    }
                )
            else:
                challenged = []
        follow_ups = []
        if unresolved and int((payload.task.get("depth") or 0)) == 0:
            follow_ups.append(
                FollowUpSpec(
                    title="Obtain missing filings or transcripts for unresolved fields",
                    description="; ".join(unresolved),
                    task_type="fetch_missing",
                    assigned_agents=(AGENT_SEARCH,),
                    required_data=tuple(unresolved),
                    source_reason="search_gap",
                    priority=70,
                )
            )
        confidence = 0.55 if evidence else 0.2
        return AgentOutput(
            findings=findings,
            new_evidence=evidence,
            follow_up_tasks=follow_ups,
            missing_data=unresolved,
            supported_assumption_ids=supported,
            challenged_assumption_ids=challenged,
            assumption_links=links,
            confidence=confidence,
            agent_name=self.name,
            prompt_version=self.prompt_version,
            model=None,
        )
