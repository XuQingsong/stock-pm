"""Phase 1 Brain run. Parallel to run_new_ticker_research; does not replace it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from stock_pm.config import Settings
from stock_pm.research.backfill import ResearchDataBackfill, can_live_backfill, pack_needs_research_data
from stock_pm.research.llm_reason import compact_pack, compact_text

from .claim_integrity import (
    COUNTER_MARKERS,
    check_pm_consistency,
    classify_source_relationship,
    default_counter_queries,
    derive_claim_identity,
    freeze_evidence_set,
    is_fact_restatement,
    is_material_change,
    links_from_reasoning,
    match_existing_claim,
    news_is_duplicate,
    reconcile_status,
    score_candidate,
    strip_unbound_facts,
)
from .critic import critic_context, reconcile_critic
from .drivers import claims_require_drivers, select_driver_universe
from .events import build_event
from .exposure import infer_exposure, may_affect_company_claim
from .financial_bridge import impacts_from_objects
from .header import company_header
from .history import history_row
from .incremental import affected_scope, should_full_review
from .integrity import assess_financial_integrity
from .llm_steps import (
    claim_reasoning,
    company_understanding,
    compact_evidence_rows,
    core_claims,
    event_transmission,
    independent_critic,
    news_interpretation,
    normalize_claim,
    normalize_news_item,
    pm_synthesis,
    value_driver_universe,
)
from .news import classify_news_hits, is_high_quality, search_recent_news
from .pm_gate import pm_context
from .quality import assess_brain_quality
from .routing import resolve_brain_completers
from .scenario import apply_scenario_policy, qualifies_for_base
from .state_layer import match_existing_state, normalize_state
from .store import BrainStore
from .transmission import validate_transmission
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


def _brain_evidence_rows(frozen: dict[str, Any] | None, *, limit: int) -> list[dict[str, Any]]:
    rows = list((frozen or {}).get("reasoning_rows") or [])
    return rows[:limit]


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


def _select_core(
    candidates: list[dict[str, Any]],
    core_raw: list[dict[str, Any]],
    rejected_raw: list[dict[str, Any]] | None,
    *,
    allowed: set[str],
    ticker: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str | None]:
    why_not = {}
    for raw in rejected_raw or []:
        if isinstance(raw, dict) and raw.get("title"):
            why_not[str(raw.get("title") or "").strip().lower()] = compact_text(raw.get("why_not_core") or "", 240)

    def _prepare(raw: dict[str, Any]) -> dict[str, Any]:
        item = dict(raw)
        if not compact_text(item.get("uncertainty") or (item.get("scores") or {}).get("uncertainty") or "", 40):
            item["uncertainty"] = "medium"
        if not compact_text(item.get("valuation_relevance") or (item.get("scores") or {}).get("valuation_relevance") or "", 40):
            item["valuation_relevance"] = "medium"
        identity = derive_claim_identity(item, ticker=ticker)
        item.update(identity)
        return item

    normalized_core: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []
    seen_statements: set[str] = set()
    seen_keys: set[str] = set()
    rejected_ids: list[str] = []
    for raw in core_raw:
        if not isinstance(raw, dict):
            continue
        item = normalize_claim(_prepare(raw), allowed_ids=allowed, core=True)
        if not item:
            if raw.get("supporting_evidence_ids"):
                rejected_ids.extend([str(eid) for eid in raw.get("supporting_evidence_ids") or [] if str(eid) not in allowed])
            continue
        item.update(derive_claim_identity(item, ticker=ticker))
        rejected_ids.extend(item.get("rejected_evidence_ids") or [])
        if is_fact_restatement(item["statement"]):
            item["selected_as_core"] = False
            item["why_not_core"] = item.get("why_not_core") or "reclassify_as_fact_or_state: reported fact, not a decision variable"
            item["is_core"] = False
            demoted.append(item)
            continue
        key = item["statement"].lower()
        if key in seen_statements or item.get("claim_key") in seen_keys:
            continue
        seen_statements.add(key)
        seen_keys.add(str(item.get("claim_key") or ""))
        item["selected_as_core"] = True
        normalized_core.append(item)
    normalized_core.sort(key=score_candidate, reverse=True)
    normalized_core = normalized_core[:5]
    normalized_candidates = []
    core_keys = {str(row.get("claim_key")) for row in normalized_core}
    core_statements = {row["statement"].lower() for row in normalized_core}
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        item = normalize_claim(_prepare(raw), allowed_ids=allowed, core=False)
        if not item:
            continue
        item.update(derive_claim_identity(item, ticker=ticker))
        selected = item["statement"].lower() in core_statements or item.get("claim_key") in core_keys
        item["selected_as_core"] = selected
        if selected and not item.get("why_core"):
            match = next((row for row in normalized_core if row["statement"].lower() == item["statement"].lower()), None)
            item["why_core"] = (match or {}).get("why_core") or "Highest value impact × uncertainty × decision relevance among grounded candidates."
        if not selected:
            item["why_not_core"] = (
                item.get("why_not_core")
                or why_not.get(item["title"].lower())
                or ("reclassify_as_fact_or_state" if is_fact_restatement(item["statement"]) else "Not selected into the Top Core Claims for this run.")
            )
        normalized_candidates.append(item)
        if len(normalized_candidates) >= 8:
            break
    for row in demoted:
        if row["statement"].lower() not in {item["statement"].lower() for item in normalized_candidates}:
            normalized_candidates.append(row)
    reason = None
    if not normalized_core:
        reason = "No Core Claim had grounded supporting evidence_id values inside the current Evidence Set."
    return normalized_candidates, normalized_core, [{"evidence_id": eid, "reason": "not in current evidence_set"} for eid in dict.fromkeys(rejected_ids)], reason


def _counter_hits_to_bodies(ticker: str, hits: list[dict[str, Any]], *, retrieved_at: str) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []
    for row in hits or []:
        url = str(row.get("url") or "")
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("snippet") or row.get("excerpt") or "").strip()
        fact = snippet or title
        if not url or len(fact) < 24:
            continue
        bodies.append(
            {
                "ticker": ticker.upper(),
                "evidence_type": "news",
                "fact": fact[:800],
                "excerpt": fact[:600],
                "source": row.get("source") or "web_search",
                "source_url": url,
                "source_time": row.get("published_at") or retrieved_at,
                "retrieved_at": retrieved_at,
                "source_type": "web_search",
                "importance": "medium",
                "raw_reference": {
                    "query": row.get("query"),
                    "query_type": "counter",
                    "title": title,
                    "counter_search": True,
                },
            }
        )
    return bodies


def _pm_claim_view(claim: dict[str, Any], links: list[dict[str, Any]], versions: list[dict[str, Any]]) -> dict[str, Any]:
    reasoning = claim.get("reasoning") if isinstance(claim.get("reasoning"), dict) else {}
    return {
        "claim_id": claim.get("claim_id"),
        "title": claim.get("title"),
        "statement": claim.get("statement"),
        "final_status": claim.get("final_status") or claim.get("status"),
        "confidence": claim.get("confidence"),
        "lifecycle": claim.get("lifecycle"),
        "why_core": claim.get("why_core"),
        "unverified_detail": claim.get("unverified_detail"),
        "counter_search": claim.get("counter_search") or {},
        "evidence_links": [
            {
                "evidence_id": row.get("evidence_id"),
                "direction": row.get("direction"),
                "strength": row.get("strength"),
                "relevance": row.get("relevance"),
                "source_relationship": row.get("source_relationship"),
                "reason": row.get("reason"),
                "proves": row.get("proves"),
                "does_not_prove": row.get("does_not_prove"),
            }
            for row in links
        ],
        "history": [
            {
                "version": row.get("version"),
                "status": row.get("new_status") or row.get("status"),
                "reason_for_change": row.get("reason_for_change"),
            }
            for row in versions
        ],
        "evidence_coverage": reasoning.get("evidence_boundary"),
        "unsupported_assertions": reasoning.get("unsupported_assertions") or [],
    }


def _apply_claim_version(
    brain: BrainStore,
    claim: dict[str, Any],
    new_fields: dict[str, Any],
    *,
    snapshot_id: str | None,
    run_id: str,
) -> bool:
    prior = claim.get("prior_version") or {
        "statement": claim.get("statement"),
        "status": claim.get("status"),
        "confidence": claim.get("confidence"),
        "supporting_evidence_ids": claim.get("supporting_evidence_ids") or [],
        "opposing_evidence_ids": claim.get("opposing_evidence_ids") or [],
        "current_version_id": claim.get("current_version_id"),
    }
    check = is_material_change(prior, new_fields)
    pointer = {
        **{key: value for key, value in new_fields.items() if key not in {"supporting_evidence_ids", "opposing_evidence_ids"}},
        "last_reviewed_at": _now(),
    }
    if not check["material"]:
        pointer["current_version_id"] = claim.get("current_version_id") or prior.get("current_version_id")
        brain.update_claim_pointer(claim["claim_id"], pointer)
        claim["version_change"] = "no_version_change"
        claim["version_reason"] = check["reason"]
        return False
    versions = brain.list_versions(claim["claim_id"])
    next_n = max([int(row.get("version") or 0) for row in versions] or [0]) + 1
    old_e = set(prior.get("supporting_evidence_ids") or [])
    new_e = set(new_fields.get("supporting_evidence_ids") or [])
    old_c = set(prior.get("opposing_evidence_ids") or [])
    new_c = set(new_fields.get("opposing_evidence_ids") or [])
    version = brain.insert_version(
        {
            "claim_id": claim["claim_id"],
            "version": next_n,
            "statement": new_fields.get("statement"),
            "status": new_fields.get("status"),
            "confidence": new_fields.get("confidence"),
            "old_statement": prior.get("statement"),
            "new_statement": new_fields.get("statement"),
            "old_status": prior.get("status"),
            "new_status": new_fields.get("status"),
            "old_confidence": prior.get("confidence"),
            "new_confidence": new_fields.get("confidence"),
            "reason_for_change": check["reason"],
            "added_evidence_ids": sorted(new_e - old_e),
            "removed_evidence_ids": sorted(old_e - new_e),
            "counter_evidence_ids": sorted(new_c),
            "added_counter_evidence_ids": sorted(new_c - old_c),
            "snapshot_id": snapshot_id,
            "run_id": run_id,
        }
    )
    pointer["current_version_id"] = version["claim_version_id"]
    brain.update_claim_pointer(claim["claim_id"], pointer)
    claim["current_version_id"] = version["claim_version_id"]
    claim["version_change"] = "new_version"
    claim["version_reason"] = check["reason"]
    return True


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
    mechanical_completer: Any | None = None,
    reasoning_completer: Any | None = None,
    fetch_live: bool = True,
    days: int = NEWS_WINDOW_DAYS,
    mode: str = "full",
) -> dict[str, Any]:
    from stock_pm.external.clients import SearchBudget, exa_configured, tavily_configured
    from stock_pm.external.layer import gather_external_intelligence, merge_intelligence

    symbol = str(ticker or "").upper()
    brain = store or BrainStore(getattr(getattr(research, "store", None), "database", None))
    run_mode = str(mode or "full").strip().lower()
    if run_mode not in {"full", "incremental"}:
        run_mode = "full"
    settings = Settings()
    mech_llm, reason_llm = resolve_brain_completers(
        completer if completer is not None else getattr(research, "completer", None),
        mechanical=mechanical_completer,
        reasoning=reasoning_completer,
        settings=settings,
    )
    warnings: list[dict[str, str]] = []
    errors: list[str] = []
    fallbacks: list[str] = []
    llm_calls: list[dict[str, Any]] = []
    run = brain.insert_run({"ticker": symbol, "status": "running", "prompt_version": PROMPT_VERSION, "run_mode": run_mode})
    run_id = run["run_id"]
    actor = "brain_v1"

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
            completer=mech_llm,
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
    related_entities = list((intel_base or {}).get("related_entities") or [])
    frozen = freeze_evidence_set(
        ticker=symbol,
        intel=intel_base,
        store_evidence=evidence,
        related_entities=related_entities,
        extra_rows=created_news + news_evidence + created_pack,
    )
    brain.insert_evidence_set({"evidence_set_id": frozen["evidence_set_id"], "run_id": run_id, "ticker": symbol, "payload": frozen})
    llm_evidence = _brain_evidence_rows(frozen, limit=24)
    allowed = set(frozen.get("reasoning_allowed_ids") or [])
    integrity_violations: list[dict[str, Any]] = []
    if not allowed:
        integrity_violations.append({"code": "empty_evidence_set", "reason": "No Evidence Set rows were eligible for reasoning."})

    understanding = None
    payload_a, audit_a = company_understanding(
        reason_llm,
        {
            "ticker": symbol,
            "reported_financials": header,
            "research_pack": compact_pack(pack),
            "evidence": compact_evidence_rows(llm_evidence, limit=24),
            "evidence_set_id": frozen.get("evidence_set_id"),
            "snapshot_id": snapshot_id,
            "rules": ["Do not invent numbers.", "Cite evidence_id only from the current Evidence Set.", "Mark unavailable when missing."],
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
            frozen = freeze_evidence_set(
                ticker=symbol,
                intel=intel_base,
                store_evidence=evidence,
                related_entities=related_entities,
                extra_rows=created_news + news_evidence + created_pack,
            )
            llm_evidence = _brain_evidence_rows(frozen, limit=24)
            allowed = set(frozen.get("reasoning_allowed_ids") or [])
        for state in payload_a.get("states") or []:
            if not isinstance(state, dict) or not state.get("name"):
                continue
            eids = [eid for eid in (state.get("evidence_ids") or []) if str(eid) in allowed]
            item = normalize_state(
                {**state, "evidence_ids": eids, "source": "llm_company_understanding"},
                ticker=symbol,
                allowed_ids=allowed,
                existing=match_existing_state(
                    {"state_key": None, "subject": state.get("name"), "state_type": state.get("state_type") or "company", "name": state.get("name")},
                    brain.list_states(symbol),
                ),
            )
            if not item:
                continue
            brain.upsert_state({**item, "run_id": run_id, "ticker": symbol, "source": "llm_company_understanding"})
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

    persisted_drivers: list[dict[str, Any]] = []
    rejected_drivers: list[dict[str, Any]] = []
    existing_drivers = brain.list_drivers(symbol)
    prior_claims_all = brain.list_active_claims(symbol)
    rebuild = should_full_review(prior_drivers=existing_drivers, prior_claims=prior_claims_all, mode=run_mode)
    payload_drivers = None
    audit_drivers = {"step": "value_drivers", "llm_called": False, "llm_status": "skipped"}
    if not rebuild:
        persisted_drivers = list(existing_drivers)
        llm_calls.append(audit_drivers)
    elif not integrity.get("block_core_claims"):
        payload_drivers, audit_drivers = value_driver_universe(
            reason_llm,
            {
                "ticker": symbol,
                "reported_financials": header,
                "states": [row for row in brain.list_states(symbol, run_id=run_id)],
                "existing_drivers": [
                    {
                        "driver_id": row.get("driver_id"),
                        "canonical_key": row.get("canonical_key"),
                        "name": row.get("name"),
                        "category": row.get("category"),
                        "status": row.get("status"),
                    }
                    for row in existing_drivers
                ],
                "evidence": compact_evidence_rows(llm_evidence, limit=24),
                "evidence_set_id": frozen.get("evidence_set_id"),
                "company_understanding": understanding or {"missing": True},
                "snapshot_id": snapshot_id,
            },
            allowed_ids=allowed,
        )
        llm_calls.append(audit_drivers)
        if payload_drivers:
            selected, rejected_drivers = select_driver_universe(
                list(payload_drivers.get("drivers") or []),
                ticker=symbol,
                allowed_ids=allowed,
                existing=existing_drivers,
            )
            rejected_drivers.extend(payload_drivers.get("rejected") or [])
            for item in selected:
                prior_row = next(
                    (
                        row
                        for row in existing_drivers
                        if row.get("canonical_key") == item.get("canonical_key") or row.get("driver_id") == item.get("driver_id")
                    ),
                    None,
                )
                stored_driver = brain.upsert_driver({**item, "run_id": run_id, "ticker": symbol})
                persisted_drivers.append(stored_driver)
                if prior_row:
                    brain.insert_history(
                        history_row(
                            ticker=symbol,
                            object_type="driver",
                            object_id=str(stored_driver.get("driver_id")),
                            from_payload={"current_state": prior_row.get("current_state"), "direction": prior_row.get("direction")},
                            to_payload={"current_state": stored_driver.get("current_state"), "direction": stored_driver.get("direction")},
                            reason="driver_universe_update",
                            run_id=run_id,
                        )
                    )
        else:
            fallbacks.append("value_drivers")
            warnings.append(
                {
                    "code": "BRAIN QUALITY WARNING",
                    "axis": "LLM Reasoning",
                    "reason": audit_drivers.get("error") or "Value Driver Universe LLM call failed.",
                }
            )
    else:
        llm_calls.append(audit_drivers)

    candidates: list[dict[str, Any]] = []
    core: list[dict[str, Any]] = []
    insufficient = None
    payload_b = None
    rejected_ids: list[dict[str, Any]] = []
    audit_b = {"step": "core_claims", "llm_called": False, "llm_status": "skipped"}
    if integrity.get("block_core_claims"):
        fallbacks.append("core_claims")
        insufficient = "financial_input_inconsistent"
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "Data Coverage", "reason": "Core Claim Generation blocked: financial_input_inconsistent"})
        audit_b["error"] = "financial_input_inconsistent"
        audit_b["fallback_used"] = True
        llm_calls.append(audit_b)
    elif not rebuild:
        llm_calls.append(audit_b)
    elif not persisted_drivers:
        fallbacks.append("core_claims")
        insufficient = "No grounded Value Driver Universe; Core Claims were not generated from documents."
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "LLM Reasoning", "reason": str(insufficient)})
        audit_b["error"] = insufficient
        audit_b["fallback_used"] = True
        llm_calls.append(audit_b)
    else:
        payload_b, audit_b = core_claims(
            reason_llm,
            {
                "ticker": symbol,
                "reported_financials": header,
                "states": [row for row in brain.list_states(symbol, run_id=run_id)],
                "drivers": [
                    {
                        "driver_id": row.get("driver_id"),
                        "canonical_key": row.get("canonical_key"),
                        "name": row.get("name"),
                        "category": row.get("category"),
                        "financial_link": row.get("financial_link"),
                        "current_state": row.get("current_state"),
                        "importance": row.get("importance"),
                        "uncertainty": row.get("uncertainty"),
                        "persistence": row.get("persistence"),
                        "why_it_matters": row.get("why_it_matters"),
                        "evidence_ids": row.get("evidence_ids") or [],
                    }
                    for row in persisted_drivers
                ],
                "evidence": compact_evidence_rows(llm_evidence, limit=24),
                "evidence_set_id": frozen.get("evidence_set_id"),
                "company_understanding": understanding or {"missing": True},
                "snapshot_id": snapshot_id,
            },
            allowed_ids=allowed
            | {str(row.get("driver_id")) for row in persisted_drivers if row.get("driver_id")}
            | {str(row.get("canonical_key")) for row in persisted_drivers if row.get("canonical_key")},
        )
        llm_calls.append(audit_b)
        if payload_b:
            candidates, core, rejected_ids, insufficient = _select_core(
                list(payload_b.get("candidates") or []),
                list(payload_b.get("core") or []),
                list(payload_b.get("rejected") or []),
                allowed=allowed,
                ticker=symbol,
            )
            core = claims_require_drivers(core, persisted_drivers)
            if not core:
                insufficient = insufficient or "No Core Claim bound to a grounded Value Driver."
            insufficient = insufficient or payload_b.get("insufficient_reason")
            integrity_violations.extend(rejected_ids)
        else:
            fallbacks.append("core_claims")
            insufficient = audit_b.get("error") or "Core claim LLM call failed; no template claims were generated."
            warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "LLM Reasoning", "reason": str(insufficient)})
    if integrity.get("data_poor"):
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "Data Coverage", "reason": "Company pack coverage is incomplete; per-claim evidence strength is assessed separately."})

    evidence_by_id = {str(row.get("id")): row for row in (frozen.get("rows") or []) if row.get("id")}
    persisted_claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    selected_ids: set[str] = set()
    existing_active = brain.list_active_claims(symbol)
    if not rebuild:
        for prior in existing_active:
            if not prior.get("is_core"):
                continue
            persisted_claims.append(prior)
            selected_ids.add(str(prior["claim_id"]))
            claim_ids.add(str(prior["claim_id"]))
    for item in core:
        match = match_existing_claim(item, existing_active)
        action = match.get("action") or "create_new"
        prior = match.get("claim")
        by_key = brain.get_claim_by_key(symbol, str(item.get("claim_key") or ""))
        if by_key:
            action = "update_existing"
            prior = by_key
        bound = [evidence_by_id.get(eid) for eid in item.get("supporting_evidence_ids") or [] if evidence_by_id.get(eid)]
        stripped = strip_unbound_facts(item["statement"], [row for row in bound if row])
        if stripped.get("unsupported_tokens"):
            integrity_violations.append(
                {
                    "code": "unsupported_factual_assertion",
                    "claim_title": item.get("title"),
                    "tokens": stripped.get("unsupported_tokens"),
                }
            )
        item["statement"] = stripped["statement"]
        item["unverified_detail"] = stripped.get("unverified_detail") or ""
        item["unsupported_tokens"] = stripped.get("unsupported_tokens") or []
        payload = {
            "ticker": symbol,
            "title": item["title"],
            "statement": item["statement"],
            "claim_type": item["claim_type"],
            "status": item.get("proposed_status") or item["status"],
            "proposed_status": item.get("proposed_status") or item["status"],
            "importance": item["importance"],
            "confidence": item["confidence"],
            "time_horizon": item["time_horizon"],
            "why_it_matters": item["why_it_matters"],
            "financial_driver": item.get("financial_driver"),
            "claim_key": item.get("claim_key"),
            "claim_subject": item.get("claim_subject"),
            "claim_dimension": item.get("claim_dimension"),
            "related_driver_ids": item.get("related_driver_ids") or [],
            "why_core": item.get("why_core") or "",
            "is_core": True,
            "lifecycle": "core",
            "evidence_set_id": frozen.get("evidence_set_id"),
            "unverified_detail": item.get("unverified_detail") or "",
            "match_action": action,
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "last_reviewed_at": _now(),
        }
        if action in {"update_existing", "merge_into_existing"} and prior:
            payload["claim_key"] = prior.get("claim_key") or payload.get("claim_key")
            payload["claim_subject"] = prior.get("claim_subject") or payload.get("claim_subject")
            payload["claim_dimension"] = prior.get("claim_dimension") or payload.get("claim_dimension")
            item["claim_key"] = payload["claim_key"]
            claim = brain.update_claim_pointer(prior["claim_id"], payload) or prior
            claim.update({k: payload[k] for k in payload if k not in {"ticker"}})
            claim["claim_id"] = prior["claim_id"]
            claim["prior_version"] = {
                "statement": prior.get("statement"),
                "status": prior.get("status") or prior.get("final_status"),
                "confidence": prior.get("confidence"),
                "supporting_evidence_ids": [
                    str(link.get("evidence_id"))
                    for link in brain.list_links(claim_id=prior["claim_id"])
                    if link.get("direction") == "support"
                ],
                "opposing_evidence_ids": [
                    str(link.get("evidence_id"))
                    for link in brain.list_links(claim_id=prior["claim_id"])
                    if link.get("direction") == "oppose"
                ],
                "current_version_id": prior.get("current_version_id"),
            }
        else:
            claim = brain.insert_claim(payload)
            version = brain.insert_version(
                {
                    "claim_id": claim["claim_id"],
                    "version": 1,
                    "statement": item["statement"],
                    "status": item.get("proposed_status") or item["status"],
                    "confidence": item["confidence"],
                    "new_statement": item["statement"],
                    "new_status": item.get("proposed_status") or item["status"],
                    "new_confidence": item["confidence"],
                    "reason_for_change": "initial core claim",
                    "added_evidence_ids": item["supporting_evidence_ids"],
                    "counter_evidence_ids": item["opposing_evidence_ids"],
                    "snapshot_id": snapshot_id,
                    "run_id": run_id,
                }
            )
            brain.update_claim_pointer(claim["claim_id"], {"current_version_id": version["claim_version_id"]})
            claim["current_version_id"] = version["claim_version_id"]
            claim["prior_version"] = {
                "statement": item["statement"],
                "status": item.get("proposed_status") or item["status"],
                "confidence": item["confidence"],
                "supporting_evidence_ids": list(item.get("supporting_evidence_ids") or []),
                "opposing_evidence_ids": list(item.get("opposing_evidence_ids") or []),
                "current_version_id": version["claim_version_id"],
            }
        claim.update(item)
        claim["match_action"] = action
        persisted_claims.append(claim)
        selected_ids.add(claim["claim_id"])
        claim_ids.add(claim["claim_id"])
        existing_active = [row for row in existing_active if row.get("claim_id") != claim.get("claim_id")] + [claim]
    for item in candidates:
        matched = next((row for row in persisted_claims if row.get("statement") == item.get("statement")), None)
        brain.insert_candidate(
            {
                "run_id": run_id,
                "ticker": symbol,
                "title": item.get("title"),
                "statement": item.get("statement"),
                "selected_as_core": bool(item.get("selected_as_core")),
                "why_core": item.get("why_core") or "",
                "why_not_core": item.get("why_not_core") or "",
                "scores": item.get("scores") or {},
                "supporting_evidence_ids": item.get("supporting_evidence_ids") or [],
                "opposing_evidence_ids": item.get("opposing_evidence_ids") or [],
                "missing_evidence": item.get("missing_evidence") or [],
                "claim_id": (matched or {}).get("claim_id"),
            }
        )
    for prior in brain.list_active_claims(symbol):
        if prior.get("is_core") and prior.get("claim_id") not in selected_ids and prior.get("run_id") != run_id:
            brain.update_claim_pointer(prior["claim_id"], {"is_core": False, "lifecycle": "background", "last_reviewed_at": _now()})
    for driver in persisted_drivers:
        bound_claims = [
            str(row.get("claim_id"))
            for row in persisted_claims
            if str(driver.get("driver_id")) in [str(item) for item in (row.get("related_driver_ids") or [])]
        ]
        if bound_claims:
            brain.update_driver(driver["driver_id"], {"related_claim_ids": bound_claims})
            driver["related_claim_ids"] = bound_claims

    intel_claims: dict[str, Any] | None = None
    if fetch_live and persisted_claims:
        prior_urls = {str(row.get("canonical_url") or row.get("url") or "") for row in (intel_base.get("documents") or []) if row.get("url")}
        intel_claims = gather_external_intelligence(
            symbol,
            pack=pack,
            header=header,
            claims=persisted_claims,
            understanding=understanding,
            completer=mech_llm,
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
        related_entities = list((intel_claims or {}).get("related_entities") or related_entities)
        frozen = freeze_evidence_set(
            ticker=symbol,
            intel=intel_claims,
            store_evidence=evidence,
            related_entities=related_entities,
            extra_rows=created_news + news_evidence + created_pack,
            research_leads=(intel_claims.get("evidence_set") or {}).get("research_leads"),
        )
        llm_evidence = _brain_evidence_rows(frozen, limit=24)
        allowed = set(frozen.get("reasoning_allowed_ids") or [])
        evidence_by_id = {str(row.get("id")): row for row in (frozen.get("rows") or []) if row.get("id")}

    persisted_events: list[dict[str, Any]] = []
    persisted_exposures: list[dict[str, Any]] = []
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
        reason_llm,
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
            facts = [str(row.get("fact") or "") for row in (frozen.get("rows") or [])]
            duplicate = news_is_duplicate(hit, facts + [str(item.get("new_fact") or "")])
            event_row = build_event(
                {
                    **hit,
                    **item,
                    "evidence_id": evidence_id,
                    "subject": item.get("affected_state") or hit.get("title"),
                    "ticker": symbol,
                },
                ticker=symbol,
                related_entities=related_entities,
                drivers=persisted_drivers,
                claims=persisted_claims,
                existing=persisted_events + brain.list_events(symbol),
            )
            exposure_row = None
            if event_row and not event_row.get("duplicate"):
                stored_event = brain.insert_event({**event_row, "run_id": run_id, "ticker": symbol})
                persisted_events.append(stored_event)
                evidence_rows = [evidence_by_id[evidence_id]] if evidence_id and evidence_by_id.get(evidence_id) else []
                origin = "issuer_news"
                if evidence_rows and classify_source_relationship(evidence_rows[0], ticker=symbol, related_entities=related_entities) == "related_entity_primary":
                    origin = "related_entity"
                exposure_row = infer_exposure(
                    ticker=symbol,
                    state_or_event={**stored_event, "direction": item.get("impact")},
                    related_entities=related_entities,
                    evidence_rows=evidence_rows,
                    origin=origin,
                )
                if exposure_row:
                    stored_exp = brain.insert_exposure({**exposure_row, "run_id": run_id, "event_id": stored_event["event_id"], "ticker": symbol})
                    persisted_exposures.append(stored_exp)
                    exposure_row = stored_exp
            elif event_row and event_row.get("duplicate"):
                persisted_events.append(event_row)
            if (
                item.get("layer") == "material"
                and item.get("affected_claim_id")
                and evidence_id
                and evidence_id in allowed
                and not duplicate
                and may_affect_company_claim(exposure_row)
            ):
                target = next((row for row in persisted_claims if row.get("claim_id") == item.get("affected_claim_id")), None)
                if target is not None:
                    direction = "support" if item.get("impact") == "support" else "oppose" if item.get("impact") == "oppose" else "contextual"
                    ids_key = "opposing_evidence_ids" if direction == "oppose" else "supporting_evidence_ids"
                    current_ids = list(target.get(ids_key) or [])
                    if evidence_id not in current_ids:
                        current_ids.append(evidence_id)
                        target[ids_key] = current_ids
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

    transmissions: list[dict[str, Any]] = []
    material_events = [row for row in persisted_events if str(row.get("materiality") or "") == "material" and not row.get("duplicate")]
    if material_events:
        by_event_exp = {str(row.get("event_id")): row for row in persisted_exposures if row.get("event_id")}
        payload_t, audit_t = event_transmission(
            reason_llm,
            {
                "ticker": symbol,
                "events": [
                    {
                        "event_id": row.get("event_id"),
                        "event_type": row.get("event_type"),
                        "subject": row.get("subject"),
                        "title": row.get("title"),
                        "materiality": row.get("materiality"),
                        "evidence_ids": row.get("evidence_ids") or [],
                    }
                    for row in material_events
                ],
                "exposures": persisted_exposures,
                "states": brain.list_states(symbol, run_id=run_id),
                "drivers": [
                    {"driver_id": row.get("driver_id"), "canonical_key": row.get("canonical_key"), "name": row.get("name")}
                    for row in persisted_drivers
                ],
                "claims": [{"claim_id": row.get("claim_id"), "title": row.get("title"), "statement": row.get("statement")} for row in persisted_claims],
                "evidence": compact_evidence_rows(llm_evidence, limit=24),
            },
            allowed_ids=allowed
            | {str(row.get("event_id")) for row in material_events}
            | {str(row.get("driver_id")) for row in persisted_drivers if row.get("driver_id")}
            | claim_ids,
        )
        llm_calls.append(audit_t)
        items = list((payload_t or {}).get("items") or [])
        for event in material_events:
            raw_item = next((row for row in items if str(row.get("event_id")) == str(event.get("event_id"))), items[0] if len(items) == 1 else {})
            checked = validate_transmission(raw_item, allowed_ids=allowed, exposure=by_event_exp.get(str(event.get("event_id"))))
            event["transmission"] = checked
            transmissions.append({"event_id": event.get("event_id"), **checked})
            if not checked.get("truncated"):
                event["affected_states"] = checked.get("affected_states") or []
                event["affected_drivers"] = checked.get("affected_drivers") or []
                event["affected_claims"] = checked.get("affected_claims") or []
        for idx, row in enumerate(transmissions):
            event = next((item for item in material_events if str(item.get("event_id")) == str(row.get("event_id"))), {})
            ev_ids = [eid for eid in (event.get("evidence_ids") or []) if evidence_by_id.get(eid)]
            decision = qualifies_for_base(
                ticker=symbol,
                event=event,
                transmission=row,
                evidence_rows=[evidence_by_id[eid] for eid in ev_ids],
                related_entities=related_entities,
            )
            transmissions[idx] = apply_scenario_policy(row, decision)
            transmissions[idx]["scenario_policy"] = decision
            event["transmission"] = transmissions[idx]
            brain.insert_history(
                history_row(
                    ticker=symbol,
                    object_type="event_impact",
                    object_id=str(event.get("event_id") or ""),
                    from_payload={},
                    to_payload={"scenario_only": transmissions[idx].get("scenario_only"), "base_case_change": transmissions[idx].get("base_case_change"), "affected_claims": transmissions[idx].get("affected_claims") or []},
                    reason="event_transmission",
                    event_id=str(event.get("event_id") or "") or None,
                    run_id=run_id,
                )
            )
    elif persisted_events:
        llm_calls.append({"step": "event_transmission", "llm_called": False, "llm_status": "skipped"})

    counter_created: list[dict[str, Any]] = []
    for claim in list(persisted_claims):
        queries = default_counter_queries(claim, symbol)
        if len(queries) < 2:
            queries.extend(
                [
                    f"{symbol} demand slowdown OR capex cut OR order delay",
                    f"{symbol} customer concentration OR margin pressure OR lawsuit",
                ]
            )
        queries = queries[:4]
        hits_c = search_recent_news(symbol, pack=pack, extra_queries=queries, days=days)
        bodies = _counter_hits_to_bodies(symbol, hits_c, retrieved_at=_now().isoformat())
        created_c, matched_c = _persist_extracted_evidence(research, symbol, bodies, actor=actor)
        counter_created.extend(created_c)
        found_ids: list[str] = []
        for row in created_c + matched_c:
            blob = f"{row.get('fact') or ''} {row.get('excerpt') or ''}"
            if row.get("id") and COUNTER_MARKERS.search(blob):
                found_ids.append(str(row["id"]))
        claim["counter_search"] = {
            "counter_search_performed": True,
            "counter_queries": queries,
            "counter_evidence_found": bool(found_ids),
            "counter_evidence_ids": found_ids,
            "results": [
                {
                    "title": hit.get("title"),
                    "url": hit.get("url"),
                    "query": hit.get("query"),
                    "snippet": compact_text(hit.get("snippet") or "", 200),
                }
                for hit in hits_c[:8]
            ],
        }
        if found_ids:
            oppose = list(claim.get("opposing_evidence_ids") or [])
            for eid in found_ids:
                if eid not in oppose:
                    oppose.append(eid)
            claim["opposing_evidence_ids"] = oppose

    if counter_created:
        created_news.extend(counter_created)
        evidence = list(research.store.list_evidence(symbol) or [])
        frozen = freeze_evidence_set(
            ticker=symbol,
            intel=intel_claims or intel_base,
            store_evidence=evidence,
            related_entities=related_entities,
            extra_rows=created_news + news_evidence + created_pack + counter_created,
            research_leads=((intel_claims or intel_base or {}).get("evidence_set") or {}).get("research_leads"),
        )
        brain.insert_evidence_set({"evidence_set_id": frozen["evidence_set_id"], "run_id": run_id, "ticker": symbol, "payload": frozen})
        llm_evidence = _brain_evidence_rows(frozen, limit=24)
        allowed = set(frozen.get("reasoning_allowed_ids") or [])
        evidence_by_id = {str(row.get("id")): row for row in (frozen.get("rows") or []) if row.get("id")}

    claims_for_reasoning = list(persisted_claims)
    if not rebuild:
        scope = affected_scope(
            events=persisted_events,
            transmissions=transmissions,
            drivers=persisted_drivers,
            claims=persisted_claims,
        )
        if scope.get("touched"):
            wanted = set(scope.get("claims") or [])
            filtered = [row for row in persisted_claims if str(row.get("claim_id")) in wanted]
            if filtered:
                claims_for_reasoning = filtered
    for claim in claims_for_reasoning:
        bound_ids = set(claim.get("supporting_evidence_ids") or []) | set(claim.get("opposing_evidence_ids") or [])
        related = [row for row in (frozen.get("reasoning_rows") or llm_evidence) if str(row.get("id")) in bound_ids or str(row.get("id")) in allowed]
        related = related or llm_evidence
        coverage = None
        for row in ((intel_claims or intel_base or {}).get("evidence_set") or {}).get("coverage_matrix") or ((intel_claims or intel_base or {}).get("reasoning_context") or {}).get("coverage_matrix") or []:
            if str(row.get("claim_title") or "") == str(claim.get("title") or ""):
                coverage = row
                break
        payload_d, audit_d = claim_reasoning(
            reason_llm,
            {
                "claim": {
                    "claim_id": claim.get("claim_id"),
                    "title": claim.get("title"),
                    "statement": claim.get("statement"),
                    "proposed_status": claim.get("proposed_status"),
                    "claim_subject": claim.get("claim_subject"),
                    "claim_dimension": claim.get("claim_dimension"),
                    "financial_driver": claim.get("financial_driver"),
                    "time_horizon": claim.get("time_horizon"),
                    "supporting_evidence_ids": claim.get("supporting_evidence_ids") or [],
                    "opposing_evidence_ids": claim.get("opposing_evidence_ids") or [],
                    "unverified_detail": claim.get("unverified_detail"),
                    "counter_search": claim.get("counter_search") or {},
                },
                "evidence": compact_evidence_rows(related, limit=24),
                "evidence_coverage": coverage,
                "independence_gap": claim.get("independence_gap"),
                "brain_context": ((intel_claims or intel_base or {}).get("evidence_set") or {}).get("brain_context"),
                "snapshot_id": snapshot_id,
                "evidence_set_id": frozen.get("evidence_set_id"),
            },
            allowed_ids=allowed,
        )
        llm_calls.append(audit_d)
        reasoning = payload_d or {}
        if payload_d:
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
            integrity_violations.append({"code": "claim_reasoning_failed", "claim_id": claim.get("claim_id")})

        version_id = claim.get("current_version_id") or (claim.get("prior_version") or {}).get("current_version_id")
        links, rejected_link_ids = links_from_reasoning(
            reasoning,
            claim=claim,
            evidence_by_id=evidence_by_id,
            allowed=allowed,
            ticker=symbol,
            related_entities=related_entities,
            run_id=run_id,
            claim_version_id=version_id,
        )
        for eid in rejected_link_ids:
            integrity_violations.append({"code": "invalid_evidence_id_rejected", "claim_id": claim.get("claim_id"), "evidence_id": eid})
        statement = compact_text(reasoning.get("statement_revision") or claim.get("statement") or "", 600) or claim.get("statement")
        bound_rows = [evidence_by_id.get(str(row.get("evidence_id"))) for row in links if evidence_by_id.get(str(row.get("evidence_id")))]
        stripped = strip_unbound_facts(statement, [row for row in bound_rows if row])
        if stripped.get("unsupported_tokens"):
            integrity_violations.append(
                {
                    "code": "unsupported_factual_assertion",
                    "claim_id": claim.get("claim_id"),
                    "tokens": stripped.get("unsupported_tokens"),
                    "action": "stripped_from_statement",
                }
            )
        claim["statement"] = stripped["statement"]
        claim["unverified_detail"] = stripped.get("unverified_detail") or claim.get("unverified_detail") or ""
        claim["unsupported_tokens"] = stripped.get("unsupported_tokens") or []
        recon = reconcile_status(
            claim=claim,
            links=links,
            evidence_by_id=evidence_by_id,
            unsupported_tokens=claim.get("unsupported_tokens"),
            counter_search=claim.get("counter_search"),
            reasoning=reasoning,
        )
        if recon.get("proposed_status") and recon.get("final_status") and recon["proposed_status"] != recon["final_status"]:
            integrity_violations.append(
                {
                    "code": "status_downgrade" if recon["final_status"] != "strongly_supported" else "status_reconciled",
                    "claim_id": claim.get("claim_id"),
                    "from": recon["proposed_status"],
                    "to": recon["final_status"],
                    "reason": recon.get("reconciliation_reason"),
                }
            )
        lifecycle = "core"
        if recon["final_status"] in {"challenged", "contradicted"}:
            lifecycle = "challenged"
        elif recon["final_status"] == "closed":
            lifecycle = "closed"
        counter = dict(claim.get("counter_search") or {})
        oppose_ids = [str(row.get("evidence_id")) for row in links if row.get("direction") == "oppose"]
        support_ids = [str(row.get("evidence_id")) for row in links if row.get("direction") == "support"]
        if oppose_ids:
            counter["counter_evidence_found"] = True
            counter["counter_evidence_ids"] = sorted(set((counter.get("counter_evidence_ids") or []) + oppose_ids))
        counter["counter_search_performed"] = True
        claim["counter_search"] = counter
        claim["supporting_evidence_ids"] = support_ids
        claim["opposing_evidence_ids"] = oppose_ids
        claim["proposed_status"] = recon.get("proposed_status") or claim.get("proposed_status")
        claim["final_status"] = recon["final_status"]
        claim["status"] = recon["final_status"]
        claim["confidence"] = recon["confidence"]
        claim["reconciliation_reason"] = recon.get("reconciliation_reason")
        claim["lifecycle"] = lifecycle
        new_fields = {
            "statement": claim["statement"],
            "status": recon["final_status"],
            "proposed_status": claim.get("proposed_status"),
            "confidence": recon["confidence"],
            "lifecycle": lifecycle,
            "unverified_detail": claim.get("unverified_detail") or "",
            "counter_search": counter,
            "reasoning": reasoning,
            "evidence_set_id": frozen.get("evidence_set_id"),
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "supporting_evidence_ids": support_ids,
            "opposing_evidence_ids": oppose_ids,
        }
        if _apply_claim_version(brain, claim, new_fields, snapshot_id=snapshot_id, run_id=run_id):
            versions_changed += 1
            version_id = claim.get("current_version_id") or version_id
            brain.insert_history(
                history_row(
                    ticker=symbol,
                    object_type="claim",
                    object_id=str(claim.get("claim_id")),
                    from_payload={"status": (claim.get("prior_version") or {}).get("status"), "statement": (claim.get("prior_version") or {}).get("statement")},
                    to_payload={"status": new_fields.get("status"), "statement": new_fields.get("statement")},
                    reason=str(claim.get("version_reason") or "material claim update"),
                    run_id=run_id,
                )
            )
            for row in links:
                row["claim_version_id"] = version_id
        persisted_links = []
        for row in links:
            row["claim_version_id"] = claim.get("current_version_id") or version_id
            stored_link = brain.insert_link(row)
            persisted_links.append(stored_link)
        claim["evidence_links"] = persisted_links

    financial_impacts = []
    for item in impacts_from_objects(
        drivers=persisted_drivers,
        claims=persisted_claims,
        transmissions=transmissions,
        allowed_ids=allowed,
    ):
        financial_impacts.append(brain.insert_financial_impact({**item, "ticker": symbol, "run_id": run_id}))

    critic_result = {"issues": [], "unresolved": [], "inconsistent": False, "status": "ok", "transmissions": transmissions}
    payload_critic, audit_critic = independent_critic(
        reason_llm,
        critic_context(
            states=brain.list_states(symbol, run_id=run_id),
            drivers=persisted_drivers,
            claims=persisted_claims,
            events=persisted_events,
            transmissions=transmissions,
            financial_impacts=financial_impacts,
            evidence=compact_evidence_rows(llm_evidence, limit=24),
        ),
        allowed_ids=allowed | claim_ids | {str(row.get("driver_id")) for row in persisted_drivers if row.get("driver_id")},
    )
    llm_calls.append(audit_critic)
    if payload_critic:
        critic_result = reconcile_critic(list(payload_critic.get("issues") or []), transmissions=transmissions)
        transmissions = critic_result.get("transmissions") or transmissions
        if critic_result.get("inconsistent"):
            integrity_violations.append({"code": "critic_high_severity_unresolved", "issues": critic_result.get("unresolved")})
    else:
        fallbacks.append("independent_critic")
        warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "LLM Reasoning", "reason": audit_critic.get("error") or "Independent critic did not return JSON."})

    pm_claims = []
    for row in persisted_claims:
        stored = brain.get_claim(row["claim_id"]) or {}
        merged = dict(stored)
        merged.update(
            {
                "final_status": row.get("final_status") or stored.get("status"),
                "proposed_status": row.get("proposed_status") or stored.get("proposed_status"),
                "counter_search": row.get("counter_search") or stored.get("counter_search") or {},
                "reasoning": row.get("reasoning") or stored.get("reasoning") or {},
                "supporting_evidence_ids": row.get("supporting_evidence_ids") or [],
                "opposing_evidence_ids": row.get("opposing_evidence_ids") or [],
                "evidence_links": row.get("evidence_links") or [],
                "unverified_detail": row.get("unverified_detail") or stored.get("unverified_detail"),
                "reconciliation_reason": row.get("reconciliation_reason"),
                "version_change": row.get("version_change"),
                "claim_key": row.get("claim_key") or stored.get("claim_key"),
                "why_core": row.get("why_core") or stored.get("why_core"),
            }
        )
        pm_claims.append(merged)
    persisted_claims = pm_claims
    pm_payload_claims = [
        _pm_claim_view(row, row.get("evidence_links") or brain.list_links(claim_id=row["claim_id"]), brain.list_versions(row["claim_id"]))
        for row in persisted_claims
    ]
    pm_payload = pm_context(
        ticker=symbol,
        states=brain.list_states(symbol, run_id=run_id),
        drivers=persisted_drivers,
        claims=persisted_claims,
        evidence_by_id=evidence_by_id,
        financial_impacts=financial_impacts,
        transmissions=transmissions,
        history=brain.list_history(symbol),
        rejected_ids={
            str(row.get("evidence_id"))
            for row in integrity_violations
            if row.get("evidence_id")
        },
    )
    payload_e, audit_e = pm_synthesis(
        reason_llm,
        {
            **pm_payload,
            "header": header,
            "core_claims": pm_payload_claims,
            "snapshot_id": snapshot_id,
            "evidence_set_id": frozen.get("evidence_set_id"),
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
            "status": "inconsistent",
        }
        pm_check = {"passed": False, "status": "inconsistent", "reasons": ["pm_synthesis_failed"]}
    else:
        pm_check = check_pm_consistency(synthesis, persisted_claims, evidence_by_id=evidence_by_id)
        if not pm_check.get("passed"):
            synthesis["status"] = "inconsistent"
            integrity_violations.append({"code": "pm_inconsistency_blocked", "reasons": pm_check.get("reasons") or []})
            warnings.append({"code": "BRAIN QUALITY WARNING", "axis": "LLM Reasoning", "reason": "PM consistency check failed: " + "; ".join(pm_check.get("reasons") or [])})
            synthesis["current_view"] = "PM consistency check failed. Do not treat this as a completed PM view. " + "; ".join(pm_check.get("reasons") or [])
        else:
            synthesis["status"] = "completed"
    synthesis["pm_consistency"] = pm_check

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
    if synthesis.get("status") == "inconsistent" or critic_result.get("inconsistent"):
        status = "partial"
        if critic_result.get("inconsistent"):
            synthesis["status"] = "inconsistent"
            synthesis["critic_blocked"] = True

    audit = {
        "ticker": symbol,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "evidence_set_id": frozen.get("evidence_set_id"),
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
        "integrity_violations": integrity_violations,
        "pm_consistency": pm_check,
        "llm_invoked": llm_ok,
        "driver_count": len(persisted_drivers),
        "rejected_drivers": rejected_drivers,
        "run_mode": run_mode,
        "external_intelligence_report": (intel or {}).get("report") or {},
        "evidence_coverage_matrix": ((intel or {}).get("evidence_set") or {}).get("coverage_matrix") or ((intel or {}).get("report") or {}).get("coverage_matrix") or [],
        "independent_validation": ((intel or {}).get("evidence_set") or {}).get("independent_validation"),
        "brain_context": ((intel or {}).get("evidence_set") or {}).get("brain_context"),
        "research_leads": ((intel or {}).get("evidence_set") or {}).get("research_leads") or [],
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
        "integrity_violations": integrity_violations,
        "pm_consistency": pm_check,
        "evidence_set_id": frozen.get("evidence_set_id"),
        "external_intelligence": intel or {},
        "drivers": persisted_drivers,
        "rejected_drivers": rejected_drivers,
        "events": persisted_events,
        "exposures": persisted_exposures,
        "transmissions": transmissions,
        "financial_impacts": financial_impacts,
        "critic": critic_result,
        "history": brain.list_history(symbol),
        "run_mode": run_mode,
        "full_review": rebuild,
    }
