from __future__ import annotations

from typing import Any, Protocol

from ..extract import (
    extract_industry_mentions,
    official_documents,
    source_type_for_document,
    transcript_materials,
)
from ..templates import load_prompt, load_template
from ..types import AGENT_INDUSTRY, AGENT_SEARCH, AgentInput, AgentOutput, FollowUpSpec
from .base import BaseAgent, JsonCompleter


PROMPT_VERSION = "sprint3-industry-v1"

DEMAND_CATEGORIES = {"demand", "guidance_delivery"}
SUPPLY_CATEGORIES = {"execution", "supply"}
COMPETITION_CATEGORIES = {"competition"}


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

        def add_hit(hit: dict[str, Any], *, source: str, source_url: Any, source_time: Any, source_type: str) -> None:
            quote = str(hit.get("quote") or "").strip()
            key = quote.lower()
            if not quote or not source_time or key in seen:
                return
            seen.add(key)
            kind = _kind_for(quote)
            evidence.append(
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
            for query in queries[:2]:
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
                            "source_type": "official_document",
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
                    source_type=source_type_for_document(material),
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
        challenged = []
        for assumption in payload.assumptions:
            category = str(assumption.get("category") or "")
            assumption_id = str(assumption.get("id") or "")
            statement = str(assumption.get("statement") or "")
            if not assumption_id:
                continue
            related = []
            if category in DEMAND_CATEGORIES:
                related = [
                    item
                    for item in evidence
                    if any(token in str(item.get("fact") or "").lower() for token in ("customer", "demand", "capex", "deploy"))
                ]
                direction = "support" if related else "contextual"
            elif category in SUPPLY_CATEGORIES:
                related = [
                    item
                    for item in evidence
                    if any(
                        token in str(item.get("fact") or "").lower()
                        for token in ("supply", "capacity", "foundry", "contract", "agreement", "production")
                    )
                ]
                direction = "support" if related else "contextual"
            elif category in COMPETITION_CATEGORIES:
                related = [
                    item
                    for item in evidence
                    if any(token in str(item.get("fact") or "").lower() for token in ("competitor", "competition", "share"))
                ]
                direction = "support" if related else "contextual"
            else:
                related = evidence[:1]
                direction = "contextual"
            for item in related[:2]:
                assumption_links.append(
                    {
                        "assumption_id": assumption_id,
                        "evidence_key": item.get("_key"),
                        "direction": direction,
                        "strength": "moderate" if direction == "support" else "weak",
                        "reason": "industry material relates to this assumption",
                    }
                )
            if related and direction == "support":
                supported.append(assumption_id)
                proposals.append(
                    {
                        "assumption_id": assumption_id,
                        "statement": statement,
                        "proposed_status": "strengthen",
                        "reason": "industry or customer-side source language supports the claim; PM still owns status",
                        "confidence": 0.55,
                        "unresolved_gaps": missing[:4],
                    }
                )
            elif category in DEMAND_CATEGORIES and "end_demand" in missing:
                challenged.append(assumption_id)
                proposals.append(
                    {
                        "assumption_id": assumption_id,
                        "statement": statement,
                        "proposed_status": "weaken",
                        "reason": "demand assumption still lacks customer-side or capex confirmation in scanned materials",
                        "confidence": 0.45,
                        "unresolved_gaps": missing[:4],
                    }
                )
            elif assumption_id:
                proposals.append(
                    {
                        "assumption_id": assumption_id,
                        "statement": statement,
                        "proposed_status": "unchanged",
                        "reason": "industry pass did not change the balance of this assumption",
                        "confidence": 0.4,
                        "unresolved_gaps": missing[:4],
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
            findings=findings,
            new_evidence=evidence,
            supported_assumption_ids=supported,
            challenged_assumption_ids=challenged,
            assumption_links=assumption_links,
            proposed_assumption_changes=proposals,
            follow_up_tasks=follow_ups,
            missing_data=missing,
            confidence=confidence,
            agent_name=self.name,
            prompt_version=self.prompt_version,
        )
