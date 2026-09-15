from __future__ import annotations

from typing import Any, Protocol

from ..deep_case import search_queries_for, stamp_evidence_side
from ..extract import (
    extract_industry_mentions,
    official_documents,
    source_type_for_document,
    transcript_materials,
)
from ..relevance import annotate_evidence, assumption_kind, judged_links
from ..templates import load_prompt, load_template
from ..types import AGENT_INDUSTRY, AGENT_SEARCH, AgentInput, AgentOutput, FollowUpSpec
from .base import BaseAgent, JsonCompleter


PROMPT_VERSION = "sprint5-industry-v1"


class SearchTools(Protocol):
    def fetch_url(self, url: str) -> dict[str, Any]: ...
    def web_search(self, query: str) -> list[dict[str, str]]: ...
    def official_documents(self, symbol: str, filings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]: ...


def _stamp(row: dict[str, Any], fallback: str | None = None) -> str | None:
    return (
        row.get("published_at")
        or row.get("source_time")
        or row.get("report_date")
        or fallback
    )


def _kind_for(quote: str) -> str:
    hay = quote.lower()
    if any(token in hay for token in ("competitor", "competition", "market share")):
        return "competitive"
    if any(token in hay for token in ("supply", "foundry", "capacity", "wafer", "packag")):
        return "industry"
    return "industry"


def _axis_gaps(template: dict[str, Any], quotes: list[str]) -> list[str]:
    hay = " ".join(quotes).lower()
    missing: list[str] = []
    mapping = {
        "customer_capex": ("capex", "capital expend", "capital spend"),
        "end_demand": ("customer", "demand", "hyperscal"),
        "supply_capacity": ("supply", "capacity", "foundry", "production"),
        "competition": ("competitor", "competition", "market share"),
        "power_capacity": ("power", "electric", "data center", "grid"),
        "customer_confirmation": ("customer", "hyperscal", "deploy"),
    }
    for axis in template.get("question_axes") or []:
        axis_id = str(axis.get("id") or "")
        tokens = mapping.get(axis_id)
        if not tokens:
            continue
        if not any(token in hay for token in tokens):
            missing.append(axis_id)
    return missing


class IndustryAgent(BaseAgent):
    name = AGENT_INDUSTRY
    prompt_version = PROMPT_VERSION

    def __init__(self, completer: JsonCompleter | None = None, tools: SearchTools | None = None) -> None:
        super().__init__(completer=completer, system_prompt=load_prompt("industry.txt"))
        self.tools = tools

    def observe(self, payload: AgentInput) -> AgentOutput:
        pack = payload.research_pack or {}
        template = load_template(pack.get("template_id"))
        findings: list[str] = []
        evidence: list[dict[str, Any]] = []
        follow_ups: list[FollowUpSpec] = []
        missing: list[str] = []
        seen: set[str] = set()
        fallback_stamp = None
        earnings = list(pack.get("earnings_history") or [])
        if earnings:
            fallback_stamp = earnings[0].get("report_date")

        def add_hit(hit: dict[str, Any], *, source: str, source_url: Any, source_time: Any, source_type: str, query: str | None = None) -> None:
            quote = str(hit.get("quote") or "").strip()
            key = quote.lower()
            if not quote or not source_time or key in seen:
                return
            seen.add(key)
            kind = _kind_for(quote)
            evidence.append(
                stamp_evidence_side(
                    annotate_evidence(
                        {
                            "_key": f"ind-{len(evidence)+1}",
                            "evidence_type": kind,
                            "fact": quote,
                            "excerpt": quote,
                            "source": source,
                            "source_url": source_url,
                            "source_time": source_time,
                            "source_type": source_type,
                            "confidence": 0.75,
                            "importance": "high",
                            "raw_reference": {"kind": hit.get("kind") or "industry", "source_type": source_type},
                        }
                    ),
                    query=query,
                )
            )

        materials: list[dict[str, Any]] = []
        for doc in official_documents(pack):
            materials.append(doc)
        profile = pack.get("company_profile") or {}
        for item in profile.get("transcripts") or []:
            materials.append(
                {
                    "text": str(item.get("text") or "") + "\n" + "\n".join(
                        str(excerpt.get("text") if isinstance(excerpt, dict) else excerpt)
                        for excerpt in (item.get("excerpts") or [])
                    ),
                    "source": item.get("source") or "earnings call",
                    "url": item.get("source_url"),
                    "published_at": item.get("source_time") or item.get("published_at"),
                    "source_type": "transcript",
                }
            )
        extra_text = transcript_materials(pack)
        if extra_text and not any(item.get("source_type") == "transcript" for item in materials):
            materials.append(
                {
                    "text": extra_text,
                    "source": "earnings call",
                    "published_at": fallback_stamp,
                    "source_type": "transcript",
                }
            )

        if self.tools is not None:
            needed = [str(item) for item in (payload.task.get("required_data") or [])]
            queries = search_queries_for(payload.ticker, pack, needed)
            if not queries:
                queries = [
                    f"{payload.ticker} customer capital expenditure data center",
                    f"{payload.ticker} supply capacity production",
                    f"{payload.ticker} market share competition",
                ]
            try:
                fetched = self.tools.official_documents(payload.ticker, None) or []
                materials.extend(fetched)
                findings.append("industry tools fetched additional official documents")
            except Exception as exc:
                findings.append(f"industry official fetch incomplete: {exc}")
            for query in queries[:3]:
                try:
                    hits = self.tools.web_search(query) or []
                except Exception:
                    hits = []
                findings.append(f"industry web search for {query!r} returned {len(hits)} candidates")
                for hit in hits[:2]:
                    url = str(hit.get("url") or "")
                    if not url.startswith("https://"):
                        continue
                    try:
                        fetched_page = self.tools.fetch_url(url)
                    except Exception:
                        continue
                    text = str(fetched_page.get("text") or "")
                    if len(text) < 400:
                        continue
                    materials.append(
                        {
                            "text": text,
                            "url": url,
                            "source": "web_search",
                            "published_at": fallback_stamp,
                            "source_type": "web_search",
                            "query": query,
                        }
                    )

        for material in materials:
            text = str(material.get("text") or material.get("body") or "")
            stamp = _stamp(material, fallback_stamp)
            if not text.strip() or not stamp:
                continue
            for hit in extract_industry_mentions(text)[:10]:
                add_hit(
                    hit,
                    source=str(material.get("source") or material.get("source_provider") or "official"),
                    source_url=material.get("url") or material.get("source_url"),
                    source_time=stamp,
                    source_type=source_type_for_document(material) if str(material.get("source_type") or "") != "web_search" else "web_search",
                    query=str(material.get("query") or "") or None,
                )

        quotes = [str(item.get("fact") or "") for item in evidence]
        missing.extend(_axis_gaps(template, quotes))
        if evidence:
            findings.append(f"located {len(evidence)} industry or competitive facts from source text")
        else:
            findings.append("no customer, capex, supply, or competitive facts were located in official materials")
            missing.append("industry_context")

        hay = " ".join(quotes).lower()
        if any(token in hay for token in ("customer", "hyperscal", "client")):
            findings.append("customer-side language is present in source text")
        else:
            findings.append("customer-side confirmation was not found in the scanned materials")
        if any(token in hay for token in ("capex", "capital expend", "capital spend")):
            findings.append("customer or industry capex language is present")
        if any(token in hay for token in ("contract", "agreement", "multi-year", "long-term")):
            findings.append("contract or multi-year agreement language is present; delivery probability still needs checking")
        if any(token in hay for token in ("power", "electric", "data center", "data-center")):
            findings.append("infrastructure or power language is present in source text")
        if any(token in hay for token in ("supply", "capacity", "foundry", "production")):
            findings.append("supply or capacity language is present")

        assumption_links = []
        proposals = []
        supported = []
        for assumption in payload.assumptions:
            assumption_id = str(assumption.get("id") or "")
            statement = str(assumption.get("statement") or "")
            if not assumption_id:
                continue
            links = judged_links(evidence, assumption, allow_support=True, allow_oppose=True, limit=3)
            assumption_links.extend(links)
            kind = assumption_kind(assumption)
            direct_support = [
                item
                for item in links
                if item.get("direction") == "support"
                and item.get("relevance") == "direct"
                and item.get("strength") in {"strong", "moderate"}
            ]
            support_any = [item for item in links if item.get("direction") == "support"]
            current = assumption.get("confidence")
            try:
                current_conf = float(current) if current is not None else 0.5
            except (TypeError, ValueError):
                current_conf = 0.5
            gaps = list(missing[:4])
            if kind in {"demand_visibility", "growth_persist"} and ("end_demand" in missing or "customer_confirmation" in missing):
                gaps.append("customer-side demand still lacks independent confirmation")
            if kind == "execution" and ("customer_capex" in missing or "power_capacity" in missing):
                gaps.append("deployment still lacks independent customer capex confirmation")
            proposed = "unchanged"
            delta = 0.0
            if direct_support and len([item for item in gaps if "confirmation" in item or "capex" in item]) <= 1:
                if kind in {"demand_visibility", "execution", "supply", "competition"}:
                    proposed = "strengthen"
                    delta = 0.08 if kind == "demand_visibility" else 0.05
                    supported.append(assumption_id)
                    reason = (
                        f"direct industry evidence bears on this {kind} claim; "
                        + "; ".join(item.get("reason") or "" for item in direct_support[:2])
                    )
                else:
                    reason = (
                        f"industry facts are only {links[0].get('relevance') if links else 'indirect'} "
                        "for this assumption, so the suggestion stays unchanged"
                    )
            elif support_any:
                reason = (
                    "industry evidence is related but too indirect or incomplete to strengthen this specific assumption"
                )
                delta = 0.03
            else:
                reason = "no causally relevant industry evidence was found for this specific assumption"
            proposals.append(
                {
                    "assumption_id": assumption_id,
                    "statement": statement,
                    "proposed_status": proposed,
                    "reason": reason,
                    "confidence": round(min(0.85, current_conf + delta), 3),
                    "current_confidence": current_conf,
                    "confidence_delta": delta,
                    "reasoning": {
                        "positives": [str(item.get("reason") or "") for item in support_any[:3]],
                        "limits": gaps,
                        "why": reason,
                    },
                    "unresolved_gaps": gaps,
                }
            )

        if missing:
            follow_ups.append(
                FollowUpSpec(
                    title="Seek customer, capex, supply, or competitive confirmation still missing from the industry pass",
                    description="Missing industry axes: " + ", ".join(missing),
                    task_type="verify_assumption",
                    assigned_agents=(AGENT_SEARCH,),
                    required_data=tuple(missing[:4]),
                    source_reason="industry_gap",
                    source_type="assumption_gap",
                    priority=45,
                )
            )

        confidence = 0.25
        if evidence:
            confidence = 0.55
        if any("customer" in str(item.get("fact") or "").lower() for item in evidence):
            confidence = min(0.75, confidence + 0.1)
        return AgentOutput(
            findings=list(dict.fromkeys(findings)),
            new_evidence=evidence,
            supported_assumption_ids=supported,
            assumption_links=assumption_links,
            proposed_assumption_changes=proposals,
            follow_up_tasks=follow_ups,
            missing_data=missing,
            confidence=confidence,
            agent_name=self.name,
            prompt_version=self.prompt_version,
        )
