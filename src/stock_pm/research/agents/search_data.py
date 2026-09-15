from __future__ import annotations

from typing import Any, Protocol

from ..deep_case import search_queries_for, stamp_evidence_side
from ..extract import extract_commitments, extract_guidance_mentions, extract_industry_mentions, official_documents, source_type_for_document
from ..templates import load_prompt
from ..types import AGENT_SEARCH, AgentInput, AgentOutput, FollowUpSpec
from .base import BaseAgent, JsonCompleter


PROMPT_VERSION = "sprint5-search-v1"


class SearchTools(Protocol):
    def fetch_url(self, url: str) -> dict[str, Any]: ...
    def web_search(self, query: str) -> list[dict[str, str]]: ...
    def official_documents(self, symbol: str, filings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]: ...


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


def _pack_filing_urls(pack: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in pack.get("official_documents") or []:
        if item.get("url"):
            rows.append({"url": item.get("url"), "form": item.get("form") or item.get("title"), "title": item.get("title")})
    for item in pack.get("major_events") or []:
        url = str(item.get("url") or "")
        if url.startswith("https://www.sec.gov/"):
            rows.append({"url": url, "form": item.get("title") or "8-K", "title": item.get("title")})
    seen: set[str] = set()
    unique = []
    for row in rows:
        url = str(row.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(row)
    return unique


class SearchDataAgent(BaseAgent):
    name = AGENT_SEARCH
    prompt_version = PROMPT_VERSION

    def __init__(self, completer: JsonCompleter | None = None, tools: SearchTools | None = None) -> None:
        super().__init__(completer=completer, system_prompt=load_prompt("search_data.txt"))
        self.tools = tools

    def observe(self, payload: AgentInput) -> AgentOutput:
        pack = payload.research_pack or {}
        missing = list(pack.get("missing_fields") or [])
        needed = [str(item) for item in (payload.task.get("required_data") or []) if not str(item).startswith("assumption:")]
        evidence: list[dict[str, Any]] = []
        findings: list[str] = []
        fetched_docs: list[dict[str, Any]] = []

        def add_from_text(text: str, *, source: str, source_url: Any, source_time: Any, source_type: str, evidence_type: str) -> None:
            if not str(text).strip() or not source_time:
                return
            seen = {str(item.get("fact") or "").lower() for item in evidence}
            for hit in extract_commitments(text) + extract_guidance_mentions(text):
                quote = hit["quote"]
                if quote.lower() in seen:
                    continue
                seen.add(quote.lower())
                evidence.append(
                    stamp_evidence_side(
                        {
                            "_key": f"search-{len(evidence)+1}",
                            "evidence_type": evidence_type,
                            "fact": quote,
                            "excerpt": quote,
                            "source": source,
                            "source_url": source_url,
                            "source_time": source_time,
                            "source_type": source_type,
                            "confidence": 0.75,
                            "raw_reference": {"kind": hit.get("kind"), "source_type": source_type},
                            "importance": "high" if hit.get("kind") == "management_commitment" else "medium",
                        }
                    )
                )

        profile = pack.get("company_profile") or {}
        for item in profile.get("transcripts") or []:
            text = str(item.get("text") or "")
            for excerpt in item.get("excerpts") or []:
                quote = excerpt.get("text") if isinstance(excerpt, dict) else str(excerpt)
                if quote:
                    text = f"{text}\n{quote}"
            add_from_text(
                text,
                source=str(item.get("source") or "earnings call"),
                source_url=item.get("source_url"),
                source_time=item.get("source_time") or item.get("published_at"),
                source_type="transcript",
                evidence_type="transcript",
            )
        for item in official_documents(pack):
            add_from_text(
                str(item.get("text") or item.get("body") or ""),
                source=str(item.get("source") or item.get("source_provider") or "official"),
                source_url=item.get("url"),
                source_time=item.get("published_at") or item.get("source_time"),
                source_type=source_type_for_document(item),
                evidence_type="filing" if source_type_for_document(item) == "sec_filing" else "guidance",
            )
        for row in pack.get("guidance_history") or []:
            add_from_text(
                str(row.get("text") or row.get("quote") or ""),
                source=str(row.get("source") or "guidance"),
                source_url=row.get("url") or row.get("source_url"),
                source_time=row.get("source_time") or row.get("published_at"),
                source_type=str(row.get("source_type") or "earnings_release"),
                evidence_type="guidance",
            )

        still_missing = [item for item in (needed or missing) if item in {"transcripts", "guidance_history"}]
        customer_needed = [
            item
            for item in (needed or missing)
            if item
            in {
                "customer_confirmation",
                "customer_capex",
                "power_capacity",
                "end_demand",
                "supply_lock_in",
                "supply_capacity",
            }
        ]
        if self.tools is not None:
            if still_missing:
                filings = _pack_filing_urls(pack)
                try:
                    fetched_docs.extend(self.tools.official_documents(payload.ticker, filings) or [])
                    findings.append("search tools fetched official documents after structured providers were incomplete")
                except Exception as exc:
                    findings.append(f"official document fetch incomplete: {exc}")
            queries = []
            if "transcripts" in still_missing:
                queries.append(f"{payload.ticker} earnings call transcript")
            if "guidance_history" in still_missing:
                queries.append(f"{payload.ticker} earnings release guidance")
            extra = search_queries_for(payload.ticker, pack, needed or customer_needed)
            for query in extra:
                if query not in queries:
                    queries.append(query)
            for query in queries[:4]:
                try:
                    hits = self.tools.web_search(query) or []
                except Exception:
                    hits = []
                findings.append(f"web search for {query!r} returned {len(hits)} candidates")
                customer_query = any(
                    token in query.lower()
                    for token in ("customer", "capex", "data center", "power", "foundry", "deploy", "offtake")
                )
                for hit in hits[:3]:
                    url = str(hit.get("url") or "")
                    if not url:
                        continue
                    try:
                        fetched = self.tools.fetch_url(url)
                    except Exception:
                        continue
                    text = str(fetched.get("text") or "")
                    if len(text) < 400:
                        continue
                    fetched_docs.append(
                        {
                            "text": text,
                            "url": url,
                            "title": hit.get("title"),
                            "source": "web_search",
                            "source_provider": "web_search",
                            "published_at": None,
                            "doc_type": "web_search" if customer_query else ("transcript" if "transcript" in query else "earnings_release"),
                            "source_type": "web_search" if customer_query else None,
                            "query": query,
                        }
                    )
            for item in fetched_docs:
                stamp = item.get("published_at") or item.get("source_time")
                if not stamp:
                    stamp = (pack.get("earnings_history") or [{}])[0].get("report_date")
                source_type = str(item.get("source_type") or "") or source_type_for_document(item)
                add_from_text(
                    str(item.get("text") or ""),
                    source=str(item.get("source") or item.get("source_provider") or "web_search"),
                    source_url=item.get("url"),
                    source_time=stamp,
                    source_type=source_type,
                    evidence_type="transcript" if str(item.get("doc_type")) == "transcript" else "guidance",
                )
                if str(item.get("source") or "") == "web_search":
                    seen = {str(row.get("fact") or "").lower() for row in evidence}
                    for hit in extract_industry_mentions(str(item.get("text") or ""))[:8]:
                        quote = str(hit.get("quote") or "").strip()
                        if not quote or quote.lower() in seen:
                            continue
                        seen.add(quote.lower())
                        evidence.append(
                            stamp_evidence_side(
                                {
                                    "_key": f"search-{len(evidence)+1}",
                                    "evidence_type": "industry",
                                    "fact": quote,
                                    "excerpt": quote,
                                    "source": "web_search",
                                    "source_url": item.get("url"),
                                    "source_time": stamp,
                                    "source_type": "web_search",
                                    "confidence": 0.65,
                                    "raw_reference": {"kind": hit.get("kind"), "query": item.get("query")},
                                    "importance": "high",
                                },
                                query=str(item.get("query") or ""),
                            )
                        )

        unresolved = []
        for field in needed or missing:
            label = str(field)
            if label in {"transcripts", "guidance_history", "fcf", "segment_growth"} and label in missing and not evidence:
                unresolved.append(label)
            elif label in missing and label in {"transcripts"} and not any(item.get("source_type") == "transcript" for item in evidence):
                unresolved.append(label)
            elif label in missing and label in {"guidance_history"} and not any(item.get("evidence_type") == "guidance" for item in evidence):
                unresolved.append(label)
        if "guidance_history" in missing and any(item.get("evidence_type") == "guidance" for item in evidence):
            missing = [item for item in missing if item != "guidance_history"]
        unresolved = list(dict.fromkeys(unresolved))
        if evidence:
            findings.append(f"located {len(evidence)} source-backed facts for {payload.ticker}")
        else:
            findings.append("no additional official documents were available beyond the research pack snapshot")
        if unresolved:
            findings.append("unresolved data: " + ", ".join(unresolved))

        assumption_ids = _assumption_ids_from_task(payload.task)
        links = []
        for assumption_id in assumption_ids:
            if evidence:
                links.append(
                    {
                        "assumption_id": assumption_id,
                        "evidence_key": evidence[0].get("_key"),
                        "direction": "contextual",
                        "strength": "weak",
                        "relevance": "background",
                        "reason": "search located related source material; confirmation still open",
                    }
                )
        follow_ups = []
        if unresolved and int((payload.task.get("depth") or 0)) == 0:
            follow_ups.append(
                FollowUpSpec(
                    title="Continue searching official filings, IR, and transcripts for unresolved fields",
                    description="; ".join(unresolved),
                    task_type="fetch_missing",
                    assigned_agents=(AGENT_SEARCH,),
                    required_data=tuple(unresolved),
                    source_reason="search_gap",
                    source_type="agent_followup",
                    priority=70,
                )
            )
        confidence = 0.6 if evidence else 0.2
        return AgentOutput(
            findings=findings,
            new_evidence=evidence,
            follow_up_tasks=follow_ups,
            missing_data=unresolved,
            assumption_links=links,
            confidence=confidence,
            agent_name=self.name,
            prompt_version=self.prompt_version,
            model=None,
        )
