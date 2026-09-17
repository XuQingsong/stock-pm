"""Phase 1 Brain run. Parallel to run_new_ticker_research; does not replace it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from stock_pm.config import Settings
from stock_pm.research.agents.base import SettingsCompleter
from stock_pm.research.backfill import ResearchDataBackfill, can_live_backfill, pack_needs_research_data
from stock_pm.research.llm_reason import compact_pack, compact_text

from .header import company_header
from .integrity import assess_financial_integrity
from .llm_steps import (
    claim_reasoning,
    company_understanding,
    compact_evidence_rows,
    core_claims,
    news_interpretation,
    normalize_claim,
    normalize_news_item,
    pm_synthesis,
)
from .news import classify_news_hits, is_high_quality, search_recent_news
from .quality import assess_brain_quality
from .store import BrainStore
from .types import (
    EXA_SEARCH_BUDGET,
    FINANCIAL_EVIDENCE_DAYS,
    LLM_EVIDENCE_LIMIT,
    NEWS_WINDOW_DAYS,
    PROMPT_VERSION,
    TAVILY_SEARCH_BUDGET,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or _now().isoformat())


def _allowed(evidence: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("id")) for row in evidence if row.get("id")}


def _parse_stamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _is_official_row(row: dict[str, Any]) -> bool:
    source = str(row.get("source") or "").lower()
    source_type = str(row.get("source_type") or "").lower()
    evidence_type = str(row.get("evidence_type") or "").lower()
    if source_type in {"sec_filing", "earnings_release", "official_document", "transcript", "exhibit", "filing"}:
        return True
    if evidence_type in {"filing", "earnings", "transcript", "official"}:
        return True
    return any(token in source for token in ("sec.gov", "sec.companyfacts", "sec.exhibit", "sec.submissions", "earnings"))


def _recent_evidence(
    rows: list[dict[str, Any]],
    *,
    news_days: int = NEWS_WINDOW_DAYS,
    financial_days: int = FINANCIAL_EVIDENCE_DAYS,
    limit: int = LLM_EVIDENCE_LIMIT,
) -> list[dict[str, Any]]:
    news_cut = _now() - timedelta(days=news_days)
    financial_cut = _now() - timedelta(days=financial_days)
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        stamp = _parse_stamp(row.get("source_time") or row.get("published_at"))
        official = _is_official_row(row)
        keep = False
        rank = 0
        if official and (stamp is None or stamp >= financial_cut):
            keep = True
            rank = 4 if stamp and stamp >= financial_cut else 3
        elif stamp is not None and stamp >= news_cut:
            keep = True
            rank = 2
        if not keep:
            continue
        rank += 1 if row.get("importance") == "high" else 0
        scored.append((rank, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _rank, row in scored:
        key = str(row.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def _pack_evidence_bodies(ticker: str, pack: dict[str, Any], *, retrieved_at: str) -> list[dict[str, Any]]:
    symbol = ticker.upper()
    bodies: list[dict[str, Any]] = []
    cutoff = _now() - timedelta(days=FINANCIAL_EVIDENCE_DAYS)
    for row in (pack.get("earnings_history") or [])[:8]:
        if not isinstance(row, dict):
            continue
        stamp = str(row.get("period_end") or row.get("report_date") or "")[:10]
        parsed = _parse_stamp(stamp)
        if parsed is not None and parsed < cutoff:
            continue
        if not stamp:
            continue
        fy = row.get("fiscal_year") or ""
        fp = row.get("fiscal_period") or ""
        rev = row.get("revenue")
        eps = row.get("eps")
        gm = row.get("gross_margin_pct")
        om = row.get("operating_margin_pct")
        fact = (
            f"{symbol} {fy} {fp} ended {stamp}: revenue={rev}, diluted EPS={eps}, "
            f"gross margin={gm}, operating margin={om}."
        )
        bodies.append(
            {
                "ticker": symbol,
                "evidence_type": "filing",
                "fact": fact[:800],
                "excerpt": fact[:600],
                "source": row.get("source") or "earnings_history",
                "source_url": None,
                "source_time": stamp,
                "retrieved_at": retrieved_at,
                "source_type": "earnings_release",
                "importance": "high",
                "raw_reference": {
                    "period_end": row.get("period_end"),
                    "fiscal_period": fp,
                    "fiscal_year": fy,
                },
            }
        )
    for row in pack.get("official_documents") or []:
        if not isinstance(row, dict):
            continue
        stamp = str(row.get("published_at") or row.get("source_time") or "")[:10]
        parsed = _parse_stamp(stamp)
        if parsed is not None and parsed < cutoff:
            continue
        text = str(row.get("excerpt") or row.get("text") or row.get("title") or "").strip()
        if len(text) < 40:
            continue
        bodies.append(
            {
                "ticker": symbol,
                "evidence_type": "filing",
                "fact": text[:800],
                "excerpt": text[:600],
                "source": row.get("source") or row.get("source_provider") or "sec.gov",
                "source_url": row.get("url") or row.get("source_url"),
                "source_time": stamp or retrieved_at,
                "retrieved_at": retrieved_at,
                "source_type": "official_document",
                "importance": "high",
                "raw_reference": {"form": row.get("form") or row.get("title")},
            }
        )
    for row in (pack.get("guidance_history") or [])[:6]:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or row.get("excerpt") or row.get("quote") or "").strip()
        if len(text) < 40:
            continue
        stamp = str(row.get("source_time") or row.get("published_at") or retrieved_at)[:10] or retrieved_at
        bodies.append(
            {
                "ticker": symbol,
                "evidence_type": "filing",
                "fact": text[:800],
                "excerpt": text[:600],
                "source": row.get("source") or "guidance",
                "source_url": row.get("url") or row.get("source_url"),
                "source_time": stamp,
                "retrieved_at": retrieved_at,
                "source_type": "earnings_release",
                "importance": "high",
                "raw_reference": {"kind": "management_guidance"},
            }
        )
    return bodies


def _persist_pack_evidence(research: Any, ticker: str, pack: dict[str, Any], *, actor: str) -> list[dict[str, Any]]:
    existing = research.store.list_evidence(ticker)
    seen_facts = {str(row.get("fact") or "").strip().lower() for row in existing}
    created: list[dict[str, Any]] = []
    retrieved = _now().isoformat()
    for body in _pack_evidence_bodies(ticker, pack, retrieved_at=retrieved):
        key = str(body.get("fact") or "").strip().lower()
        if not key or key in seen_facts:
            continue
        try:
            row = research.create_evidence(ticker, body, actor=actor)
        except Exception:
            continue
        seen_facts.add(key)
        created.append(row)
    return created


def _persist_extracted_evidence(
    research: Any, ticker: str, bodies: list[dict[str, Any]], *, actor: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    existing = research.store.list_evidence(ticker)
    by_url = {str(row.get("source_url") or ""): row for row in existing if row.get("source_url")}
    seen_facts = {str(row.get("fact") or "").strip().lower() for row in existing}
    created: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    for body in bodies:
        url = str(body.get("source_url") or "")
        fact = str(body.get("fact") or "").strip().lower()
        if not fact:
            continue
        if url and url in by_url:
            matched.append(by_url[url])
            continue
        if fact in seen_facts:
            continue
        try:
            row = research.create_evidence(ticker, body, actor=actor)
        except Exception:
            continue
        seen_facts.add(fact)
        if url:
            by_url[url] = row
        created.append(row)
        matched.append(row)
    return created, matched


def _merge_news_hits(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for row in group or []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("url") or row.get("title") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(row)
    return out


def _evidence_id_for_hit(hit: dict[str, Any], rows: list[dict[str, Any]]) -> str | None:
    url = str(hit.get("url") or "")
    if not url:
        return None
    for row in rows:
        if str(row.get("source_url") or "") == url and row.get("id"):
            return str(row["id"])
    return None


def _select_core(candidates: list[dict[str, Any]], core_raw: list[dict[str, Any]], *, allowed: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    fallback_ids = [eid for eid in allowed if str(eid).startswith("rev_")] or list(allowed)
    candidate_by_statement: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        if isinstance(raw, dict) and raw.get("statement"):
            candidate_by_statement[str(raw.get("statement") or "").strip().lower()] = raw

    def _prepare(raw: dict[str, Any]) -> dict[str, Any]:
        item = dict(raw)
        if not compact_text(item.get("uncertainty") or (item.get("scores") or {}).get("uncertainty") or "", 40):
            item["uncertainty"] = "medium"
        if not compact_text(item.get("valuation_relevance") or (item.get("scores") or {}).get("valuation_relevance") or "", 40):
            item["valuation_relevance"] = "medium"
        ids = list(item.get("supporting_evidence_ids") or item.get("evidence_ids") or [])
        if not ids:
            sibling = candidate_by_statement.get(str(item.get("statement") or "").strip().lower())
            if sibling:
                ids = list(sibling.get("supporting_evidence_ids") or sibling.get("evidence_ids") or [])
            if ids:
                item["supporting_evidence_ids"] = ids
            elif fallback_ids:
                item["supporting_evidence_ids"] = fallback_ids[:2]
        return item

    normalized_core: list[dict[str, Any]] = []
    seen_statements: set[str] = set()
    for raw in core_raw:
        if not isinstance(raw, dict):
            continue
        item = normalize_claim(_prepare(raw), allowed_ids=allowed, core=True)
        if not item:
            continue
        key = item["statement"].lower()
        if key in seen_statements:
            continue
        seen_statements.add(key)
        normalized_core.append(item)
        if len(normalized_core) >= 5:
            break
    normalized_candidates = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        item = normalize_claim(_prepare(raw), allowed_ids=allowed, core=False)
        if item:
            normalized_candidates.append(item)
        if len(normalized_candidates) >= 8:
            break
    reason = None
    if not normalized_core:
        reason = "No Core Claim had grounded supporting evidence_id values."
    return normalized_candidates, normalized_core, reason


def _pack_print_stale(pack: dict[str, Any] | None) -> bool:
    from stock_pm.research.live_fetch import dedupe_earnings_prints

    rows = [row for row in ((pack or {}).get("earnings_history") or []) if isinstance(row, dict)]
    if not rows:
        return True
    dated = [row for row in dedupe_earnings_prints(rows) if row.get("period_end")]
    latest = dated[0] if dated else rows[0]
    if not latest.get("revenue") and not latest.get("revenue_actual"):
        return True
    return False


def run_brain(
    research: Any,
    ticker: str,
    *,
    store: BrainStore | None = None,
    completer: Any | None = None,
    fetch_live: bool = True,
    days: int = NEWS_WINDOW_DAYS,
) -> dict[str, Any]:
    from stock_pm.external.clients import SearchBudget, exa_configured, tavily_configured
    from stock_pm.external.layer import gather_external_intelligence, merge_intelligence

    symbol = str(ticker or "").upper()
    brain = store or BrainStore(getattr(getattr(research, "store", None), "database", None))
    model_completer = completer if completer is not None else getattr(research, "completer", None) or SettingsCompleter()
    warnings: list[dict[str, str]] = []
    errors: list[str] = []
    fallbacks: list[str] = []
    llm_calls: list[dict[str, Any]] = []
    run = brain.insert_run({"ticker": symbol, "status": "running", "prompt_version": PROMPT_VERSION})
    run_id = run["run_id"]
    actor = "brain_phase1"

    research.ensure_issuer(symbol)
    pack = research.get_pack(symbol) or {}
    backfill_row = None
    profile = pack.get("company_profile") or {}
    needs_data = (
        pack_needs_research_data(pack)
        or not (profile.get("revenue_ttm") or profile.get("last_close"))
        or _pack_print_stale(pack)
    )
    if fetch_live and can_live_backfill(research) and needs_data:
        try:
            backfill_row = ResearchDataBackfill(research).run(symbol, workflow_run_id=None)
            pack = research.build_pack(symbol) or pack
        except Exception as exc:
            errors.append(f"live backfill failed: {exc}")
            warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "Data Coverage", "reason": str(exc)})
    profile = pack.get("company_profile") or {}
    if not pack or (profile.get("revenue_ttm") is None and profile.get("last_close") is None):
        try:
            pack = research.build_pack(symbol) or pack
        except Exception as exc:
            errors.append(f"pack rebuild failed: {exc}")
    header = company_header(pack, issuer=research.get_issuer(symbol))
    integrity = assess_financial_integrity(pack, header)
    if integrity.get("inconsistent"):
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "Data Coverage", "reason": "financial_input_inconsistent"})
    if integrity.get("data_poor"):
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "Data Coverage", "reason": integrity.get("reason") or "financial_input_incomplete"})
    snapshot = None
    try:
        snapshot = research.freeze_research_snapshot(symbol)
    except Exception as exc:
        errors.append(f"snapshot freeze failed: {exc}")
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "Freshness", "reason": "Could not freeze a Research Snapshot; Brain will still read the live pack."})
        snapshot = research.research_snapshot(symbol) if hasattr(research, "research_snapshot") else {"pack": pack}
    snapshot_id = (snapshot or {}).get("snapshot_id")

    extra_queries: list[str] = []
    settings = Settings()
    budget = SearchBudget(
        tavily=TAVILY_SEARCH_BUDGET if tavily_configured(settings) else 0,
        exa=EXA_SEARCH_BUDGET if exa_configured(settings) else 0,
    )
    intel_base: dict[str, Any] = {}
    if fetch_live:
        intel_base = gather_external_intelligence(
            symbol,
            pack=pack,
            header=header,
            claims=[],
            understanding=None,
            completer=model_completer,
            settings=settings,
            days=days,
            fetch_live=True,
            phase="base",
            budget=budget,
        )
        llm_calls.extend(intel_base.get("llm_calls") or [])
        warnings.extend(intel_base.get("warnings") or [])
    providers = (intel_base.get("providers") or {}) if intel_base else {}
    need_ddg = (not fetch_live) or (
        str((providers.get("tavily") or {}).get("status") or "not_configured") in {"not_configured", "failed", "not_run", ""}
        and str((providers.get("exa") or {}).get("status") or "not_configured") in {"not_configured", "failed", "not_run", ""}
    )
    ddg_hits = search_recent_news(symbol, pack=pack, extra_queries=extra_queries, days=days) if need_ddg else []
    hits = _merge_news_hits(intel_base.get("news_hits") or [], ddg_hits)
    created_news, news_evidence = _persist_extracted_evidence(
        research, symbol, list(intel_base.get("evidence_bodies") or []), actor=actor
    )
    created_pack = _persist_pack_evidence(research, symbol, pack, actor=actor)
    evidence = list(research.store.list_evidence(symbol) or [])
    llm_evidence = _recent_evidence(evidence, news_days=days, financial_days=FINANCIAL_EVIDENCE_DAYS, limit=LLM_EVIDENCE_LIMIT)
    allowed = _allowed(llm_evidence) | _allowed(created_news) | _allowed(news_evidence) | _allowed(created_pack)
    if not allowed:
        allowed = _allowed(evidence[:LLM_EVIDENCE_LIMIT])
        llm_evidence = evidence[:LLM_EVIDENCE_LIMIT]

    understanding = None
    payload_a, audit_a = company_understanding(
        model_completer,
        {
            "ticker": symbol,
            "reported_financials": header,
            "research_pack": compact_pack(pack),
            "evidence": compact_evidence_rows(llm_evidence, limit=LLM_EVIDENCE_LIMIT),
            "snapshot_id": snapshot_id,
            "rules": ["Do not invent numbers.", "Cite evidence_id only.", "Mark unavailable when missing."],
        },
        allowed_ids=allowed,
    )
    llm_calls.append(audit_a)
    if payload_a:
        understanding = payload_a
        extra_queries = [
            str(item)
            for item in (
                payload_a.get("search_questions_last_30d")
                or payload_a.get("search_questions_last_7d")
                or []
            )
            if str(item).strip()
        ]
        if extra_queries and fetch_live:
            more = search_recent_news(symbol, pack=pack, extra_queries=extra_queries, days=days)
            hits = _merge_news_hits(hits, more)
            evidence = list(research.store.list_evidence(symbol) or [])
            llm_evidence = _recent_evidence(evidence, news_days=days, financial_days=FINANCIAL_EVIDENCE_DAYS, limit=LLM_EVIDENCE_LIMIT)
            allowed = _allowed(llm_evidence) | _allowed(news_evidence) | _allowed(created_pack)
        for state in payload_a.get("states") or []:
            if not isinstance(state, dict) or not state.get("name"):
                continue
            eids = [eid for eid in (state.get("evidence_ids") or []) if str(eid) in allowed]
            brain.insert_state(
                {
                    "ticker": symbol,
                    "state_type": state.get("state_type") or "company",
                    "name": compact_text(state.get("name"), 80),
                    "statement": compact_text(state.get("statement"), 400),
                    "direction": state.get("direction"),
                    "confidence": state.get("confidence") if state.get("confidence") in {"high", "medium", "low"} else "low",
                    "evidence_ids": eids,
                    "source": "llm_company_understanding",
                    "run_id": run_id,
                }
            )
        for question in payload_a.get("candidate_questions") or []:
            text = compact_text(question, 240)
            if not text:
                continue
            brain.insert_question(
                {
                    "ticker": symbol,
                    "question": text,
                    "why_it_matters": "company understanding coverage gap",
                    "priority": "high" if integrity.get("data_poor") else "medium",
                    "run_id": run_id,
                }
            )
    else:
        fallbacks.append("company_understanding")
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "LLM Reasoning", "reason": audit_a.get("error") or "Company understanding LLM call did not return JSON."})

    candidates: list[dict[str, Any]] = []
    core: list[dict[str, Any]] = []
    insufficient = None
    payload_b = None
    audit_b = {"step": "core_claims", "llm_called": False, "llm_status": "skipped"}
    if integrity.get("block_core_claims"):
        fallbacks.append("core_claims")
        insufficient = "financial_input_inconsistent"
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "Data Coverage", "reason": "Core Claim Generation blocked: financial_input_inconsistent"})
        audit_b["error"] = "financial_input_inconsistent"
        audit_b["fallback_used"] = True
        llm_calls.append(audit_b)
    else:
        payload_b, audit_b = core_claims(
            model_completer,
            {
                "ticker": symbol,
                "reported_financials": header,
                "states": [row for row in brain.list_states(symbol, run_id=run_id)],
                "evidence": compact_evidence_rows(llm_evidence, limit=LLM_EVIDENCE_LIMIT),
                "company_understanding": understanding or {"missing": True},
                "snapshot_id": snapshot_id,
            },
            allowed_ids=allowed,
        )
        llm_calls.append(audit_b)
        if payload_b:
            candidates, core, insufficient = _select_core(
                list(payload_b.get("candidates") or []),
                list(payload_b.get("core") or []),
                allowed=allowed,
            )
            insufficient = insufficient or payload_b.get("insufficient_reason")
        else:
            fallbacks.append("core_claims")
            insufficient = audit_b.get("error") or "Core claim LLM call failed; no template claims were generated."
            warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "LLM Reasoning", "reason": str(insufficient)})
    if integrity.get("data_poor"):
        capped: list[dict[str, Any]] = []
        for item in core:
            item["confidence"] = "low"
            if item.get("status") in {"strongly_supported"}:
                item["status"] = "unverified"
            capped.append(item)
        core = capped
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "Data Coverage", "reason": "Data coverage is insufficient for high-confidence Core Claims."})

    persisted_claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    for item in core:
        claim = brain.insert_claim(
            {
                "ticker": symbol,
                "title": item["title"],
                "statement": item["statement"],
                "claim_type": item["claim_type"],
                "status": item["status"],
                "importance": item["importance"],
                "confidence": item["confidence"],
                "time_horizon": item["time_horizon"],
                "why_it_matters": item["why_it_matters"],
                "financial_driver": item["financial_driver"],
                "is_core": True,
                "run_id": run_id,
                "snapshot_id": snapshot_id,
            }
        )
        version = brain.insert_version(
            {
                "claim_id": claim["claim_id"],
                "version": 1,
                "statement": item["statement"],
                "status": item["status"],
                "confidence": item["confidence"],
                "reason_for_change": "initial core claim",
                "added_evidence_ids": item["supporting_evidence_ids"],
                "counter_evidence_ids": item["opposing_evidence_ids"],
                "snapshot_id": snapshot_id,
                "run_id": run_id,
            }
        )
        brain.update_claim_pointer(claim["claim_id"], {"current_version_id": version["claim_version_id"], "statement": item["statement"], "status": item["status"], "confidence": item["confidence"]})
        claim["current_version_id"] = version["claim_version_id"]
        for eid in item["supporting_evidence_ids"]:
            brain.insert_link({"claim_id": claim["claim_id"], "evidence_id": eid, "direction": "support", "strength": "strong", "run_id": run_id})
        for eid in item["opposing_evidence_ids"]:
            brain.insert_link({"claim_id": claim["claim_id"], "evidence_id": eid, "direction": "oppose", "strength": "medium", "run_id": run_id})
        persisted_claims.append(claim)
        claim_ids.add(claim["claim_id"])

    intel_claims: dict[str, Any] | None = None
    if fetch_live and persisted_claims:
        prior_urls = {str(row.get("canonical_url") or row.get("url") or "") for row in (intel_base.get("documents") or []) if row.get("url")}
        intel_claims = gather_external_intelligence(
            symbol,
            pack=pack,
            header=header,
            claims=persisted_claims,
            understanding=understanding,
            completer=model_completer,
            settings=settings,
            days=days,
            fetch_live=True,
            phase="claims",
            budget=budget,
            prior_urls=prior_urls,
            include_macro=False,
            include_alphavantage=False,
        )
        llm_calls.extend(intel_claims.get("llm_calls") or [])
        warnings.extend(intel_claims.get("warnings") or [])
        more_created, more_matched = _persist_extracted_evidence(
            research, symbol, list(intel_claims.get("evidence_bodies") or []), actor=actor
        )
        created_news.extend(more_created)
        news_evidence.extend(more_matched)
        hits = _merge_news_hits(hits, intel_claims.get("news_hits") or [])
        evidence = list(research.store.list_evidence(symbol) or [])
        llm_evidence = _recent_evidence(evidence, news_days=days, financial_days=FINANCIAL_EVIDENCE_DAYS, limit=LLM_EVIDENCE_LIMIT)
        allowed = _allowed(llm_evidence) | _allowed(news_evidence) | _allowed(created_pack)

    news_payload = []
    for idx, hit in enumerate(hits[:24]):
        news_payload.append(
            {
                "news_index": idx,
                "title": hit.get("title"),
                "url": hit.get("url"),
                "snippet": hit.get("snippet"),
                "source": hit.get("source"),
                "published_at": hit.get("published_at"),
                "evidence_id": _evidence_id_for_hit(hit, news_evidence or evidence),
            }
        )
    news_allowed = {str(item.get("evidence_id")) for item in news_payload if item.get("evidence_id")} | allowed
    payload_c, audit_c = news_interpretation(
        model_completer,
        {
            "ticker": symbol,
            "news": news_payload,
            "claims": [{"claim_id": row["claim_id"], "title": row["title"], "statement": row["statement"]} for row in persisted_claims],
        },
        allowed_ids=news_allowed | claim_ids,
    )
    llm_calls.append(audit_c)
    interpreted: list[dict[str, Any]] = []
    versions_changed = 0
    if payload_c:
        by_index: dict[int, dict[str, Any]] = {}
        for raw_item in payload_c.get("items") or []:
            if not isinstance(raw_item, dict):
                continue
            try:
                idx = int(raw_item.get("news_index"))
            except (TypeError, ValueError):
                continue
            by_index[idx] = raw_item
        for idx, hit in enumerate(hits[:24]):
            raw = by_index.get(idx) or {}
            item = normalize_news_item(raw, allowed_ids=news_allowed, claim_ids=claim_ids)
            evidence_id = item.get("evidence_id") or news_payload[idx].get("evidence_id")
            changed = False
            if item.get("changes_claim_status") and item.get("affected_claim_id") and item.get("layer") == "material":
                claim = brain.get_claim(item["affected_claim_id"])
                if claim:
                    versions = brain.list_versions(claim["claim_id"])
                    nxt = (max((int(row.get("version") or 1) for row in versions), default=1) + 1)
                    new_status = "challenged" if item.get("impact") == "oppose" else claim.get("status")
                    if item.get("impact") == "support" and claim.get("status") in {"emerging", "unverified", "partially_supported"}:
                        new_status = "strongly_supported" if claim.get("status") == "partially_supported" else "partially_supported"
                    version = brain.insert_version(
                        {
                            "claim_id": claim["claim_id"],
                            "version": nxt,
                            "statement": claim.get("statement"),
                            "status": new_status,
                            "confidence": claim.get("confidence"),
                            "reason_for_change": item.get("reason") or "material news",
                            "added_evidence_ids": [evidence_id] if evidence_id else [],
                            "snapshot_id": snapshot_id,
                            "run_id": run_id,
                        }
                    )
                    brain.update_claim_pointer(
                        claim["claim_id"],
                        {"current_version_id": version["claim_version_id"], "status": new_status, "statement": claim.get("statement")},
                    )
                    if evidence_id:
                        brain.insert_link(
                            {
                                "claim_id": claim["claim_id"],
                                "evidence_id": evidence_id,
                                "direction": "support" if item.get("impact") == "support" else "oppose" if item.get("impact") == "oppose" else "contextual",
                                "reason": item.get("reason") or "",
                                "run_id": run_id,
                            }
                        )
                    changed = True
                    versions_changed += 1
            if item.get("new_research_question"):
                brain.insert_question(
                    {
                        "ticker": symbol,
                        "related_claim_id": item.get("affected_claim_id"),
                        "question": item["new_research_question"],
                        "why_it_matters": "material or unresolved news item",
                        "priority": "high" if item.get("layer") == "material" else "medium",
                        "run_id": run_id,
                    }
                )
            stored_news = brain.insert_news(
                {
                    "run_id": run_id,
                    "ticker": symbol,
                    "evidence_id": evidence_id,
                    "layer": item.get("layer") or "uninterpreted",
                    "title": hit.get("title"),
                    "source": hit.get("source"),
                    "url": hit.get("url"),
                    "published_at": hit.get("published_at"),
                    "new_fact": item.get("new_fact"),
                    "affected_claim_id": item.get("affected_claim_id"),
                    "impact": item.get("impact"),
                    "reason": item.get("reason"),
                    "financial_impact": item.get("financial_impact"),
                    "quantifiable": item.get("quantifiable"),
                    "claim_version_changed": changed,
                    "interpretation": item,
                }
            )
            interpreted.append(stored_news)
    else:
        fallbacks.append("news_interpretation")
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "LLM Reasoning", "reason": "News interpretation LLM call failed; items stored as uninterpreted."})
        for hit in hits[:24]:
            interpreted.append(
                brain.insert_news(
                    {
                        "run_id": run_id,
                        "ticker": symbol,
                        "evidence_id": _evidence_id_for_hit(hit, news_evidence or evidence),
                        "layer": "uninterpreted",
                        "title": hit.get("title"),
                        "source": hit.get("source"),
                        "url": hit.get("url"),
                        "published_at": hit.get("published_at"),
                        "financial_impact": "unavailable",
                        "quantifiable": False,
                    }
                )
            )

    for claim in list(persisted_claims):
        links = brain.list_links(claim_id=claim["claim_id"])
        related = [row for row in evidence if str(row.get("id")) in {str(link.get("evidence_id")) for link in links} or str(row.get("id")) in allowed]
        payload_d, audit_d = claim_reasoning(
            model_completer,
            {
                "claim": claim,
                "evidence": compact_evidence_rows(related or llm_evidence, limit=24),
                "snapshot_id": snapshot_id,
            },
            allowed_ids=allowed,
        )
        llm_calls.append(audit_d)
        if payload_d:
            brain.update_claim_pointer(claim["claim_id"], {"reasoning": payload_d})
            claim["reasoning"] = payload_d
            if payload_d.get("next_research_question"):
                brain.insert_question(
                    {
                        "ticker": symbol,
                        "related_claim_id": claim["claim_id"],
                        "question": payload_d["next_research_question"],
                        "why_it_matters": "claim reasoning gap",
                        "priority": "high",
                        "run_id": run_id,
                    }
                )
        else:
            fallbacks.append(f"claim_reasoning:{claim['claim_id']}")

    persisted_claims = [brain.get_claim(row["claim_id"]) or row for row in persisted_claims]
    payload_e, audit_e = pm_synthesis(
        model_completer,
        {
            "ticker": symbol,
            "header": header,
            "states": brain.list_states(symbol, run_id=run_id),
            "core_claims": persisted_claims,
            "material_news": [row for row in interpreted if row.get("layer") == "material"],
            "valuation_snapshot": {
                "pe_ttm": ((header.get("valuation") or {}).get("pe_ttm") or {}),
                "revenue_ttm": ((header.get("growth") or {}).get("revenue_ttm") or {}),
                "eps_ttm": ((header.get("growth") or {}).get("eps_ttm") or {}),
                "price": header.get("price"),
            },
            "snapshot_id": snapshot_id,
        },
        allowed_ids=allowed | claim_ids,
    )
    llm_calls.append(audit_e)
    synthesis = payload_e or {}
    if not payload_e:
        fallbacks.append("pm_synthesis")
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "LLM Reasoning", "reason": "PM synthesis LLM call failed; no template PM view was written."})
        synthesis = {
            "current_view": "LLM PM synthesis unavailable. Do not treat the page as a completed Brain view.",
            "cannot_conclude": ["pm_synthesis_failed"],
        }

    intel = merge_intelligence(intel_base, intel_claims) if intel_claims else intel_base
    news_stats = classify_news_hits(hits, days=days)
    quality = assess_brain_quality(
        header=header,
        evidence=evidence,
        news=hits,
        claims=persisted_claims,
        llm_calls=llm_calls,
        pack=pack,
        integrity=integrity,
    )
    quality["warnings"] = list(quality.get("warnings") or []) + [row for row in warnings if row not in (quality.get("warnings") or [])]
    if insufficient:
        quality["warnings"].append({"code": "BRAIN QUALITY WARNING", "axis": "LLM Reasoning", "reason": str(insufficient)})
    if header.get("ticker") == "LITE" and (not evidence or quality["axes"]["data_coverage"] == "Poor"):
        quality["warnings"].append({"code": "BRAIN QUALITY WARNING", "axis": "Data Coverage", "reason": "当前 LITE 数据覆盖不足。"})

    tokens_in = sum(int(row.get("input_tokens") or 0) for row in llm_calls if row.get("input_tokens") is not None)
    tokens_out = sum(int(row.get("output_tokens") or 0) for row in llm_calls if row.get("output_tokens") is not None)
    latency = sum(int(row.get("latency_ms") or 0) for row in llm_calls if row.get("latency_ms") is not None)
    models = [str(row.get("model")) for row in llm_calls if row.get("model")]
    llm_ok = any(row.get("llm_status") == "ok" and row.get("llm_called") for row in llm_calls)
    status = "success" if llm_ok and persisted_claims else ("partial" if header.get("price") or evidence else "failed")
    if quality["axes"]["llm_reasoning"] == "Poor" and not persisted_claims:
        status = "partial" if (hits or evidence or (header.get("growth") or {}).get("revenue_ttm", {}).get("value") is not None) else "failed"

    audit = {
        "ticker": symbol,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "model": models[-1] if models else None,
        "prompt_version": PROMPT_VERSION,
        "llm_calls": llm_calls,
        "input_tokens": tokens_in or None,
        "output_tokens": tokens_out or None,
        "latency_ms": latency or None,
        "news_searched": len(hits),
        "sources_fetched": len({str(row.get("url")) for row in hits if row.get("url")}),
        "evidence_created": len(created_news),
        "candidate_claim_count": len(candidates),
        "core_claim_count": len(persisted_claims),
        "claim_versions_changed": versions_changed,
        "errors": errors,
        "fallbacks": fallbacks,
        "backfill_id": (backfill_row or {}).get("id") if isinstance(backfill_row, dict) else None,
        "high_quality_news": sum(1 for row in hits if is_high_quality(row.get("url"), row.get("source"))),
        "news_coverage_stats": news_stats,
        "integrity": integrity,
        "llm_invoked": llm_ok,
        "external_intelligence_report": (intel or {}).get("report") or {},
        "external_providers": (intel or {}).get("providers") or {},
        "tavily_vs_exa": ((intel or {}).get("report") or {}).get("tavily_vs_exa") or {},
        "related_entities": (intel or {}).get("related_entities") or [],
        "claim_queries": (intel or {}).get("claim_queries") or [],
        "duplicates_removed": (intel or {}).get("duplicates_removed") or 0,
    }
    completed = brain.complete_run(
        run_id,
        {
            "status": status,
            "model": audit["model"],
            "snapshot_id": snapshot_id,
            "llm_calls": llm_calls,
            "input_tokens": audit["input_tokens"],
            "output_tokens": audit["output_tokens"],
            "latency_ms": audit["latency_ms"],
            "news_searched": audit["news_searched"],
            "sources_fetched": audit["sources_fetched"],
            "evidence_created": audit["evidence_created"],
            "candidate_claim_count": audit["candidate_claim_count"],
            "core_claim_count": audit["core_claim_count"],
            "claim_versions_changed": versions_changed,
            "errors": errors,
            "warnings": quality.get("warnings") or [],
            "fallbacks": fallbacks,
            "quality": quality,
            "company_understanding": understanding or {},
            "pm_synthesis": synthesis,
            "header": header,
            "audit": audit,
        },
    )
    return {
        "run": completed or run,
        "header": header,
        "snapshot_id": snapshot_id,
        "claims": persisted_claims,
        "candidates": candidates,
        "news": interpreted,
        "states": brain.list_states(symbol, run_id=run_id),
        "questions": brain.list_questions(symbol, run_id=run_id),
        "quality": quality,
        "pm_synthesis": synthesis,
        "company_understanding": understanding or {},
        "audit": audit,
        "pack": pack,
        "integrity": integrity,
        "external_intelligence": intel or {},
    }
