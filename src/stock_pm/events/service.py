"""Build coverage + selective event views for market and stock pages."""

from __future__ import annotations

import threading
import time
from typing import Any

from stock_pm.config import Settings

from .analyze import DISPLAY_SYMBOLS, analyze_event, closed_loop_summary, symbol_event_view
from .budget import (
    DEGRADED_COOLDOWN_SECONDS,
    BudgetTimeout,
    budget_exhausted,
    call_with_timeout,
    discovery_budget,
    provider_timeout_seconds,
    request_budget_active,
)
from .dedupe import build_events
from .earnings_health import current_earnings_health, health_for_symbol, summarize_health
from .live import discover_live_documents, reset_live_state
from .horizon import build_horizon_forecast
from .macro_chain import (
    build_market_macro_chains,
    env_macro_inject,
    reset_macro_cache,
    stock_macro_chains,
    summarize_macro_chains,
)
from .synthesis import evaluation_date, stock_synthesis, summarize_synthesis, synthesize_drivers
from .policy import events_data_mode
from .providers import GoogleDiscoveryProvider, OfficialFeedProvider, provider_coverage
from .replay import RecordedReplayProvider
from .resolve import resolve_discovery_candidates
from .types import TrustedEvent
from stock_pm.decision.inject import inject_allowed


_CACHE: dict[str, Any] = {
    "events": None,
    "coverage": None,
    "discovery_resolution": None,
    "degraded_until": 0.0,
    "degraded_reason": None,
}
_DISCOVER_LOCK = threading.Lock()
REQUIRED_LIVE = ("sec_edgar", "federal_reserve", "eia_press")


def _degraded_cover(reason: str = "timeout") -> dict[str, Any]:
    return {
        "status": "degraded",
        "verdict": "degraded",
        "data_mode": "degraded",
        "live": False,
        "event_count": 0,
        "live_event_count": 0,
        "reason_code": reason,
        "note": "Live event discovery timed out or failed. Desk shows empty events.",
        "affects_chain": "events",
        "does_not_affect": ["price", "earnings", "macro_rates"],
    }


def _bounded_discover(fn):
    timeout = provider_timeout_seconds()
    if timeout is None:
        return fn()
    try:
        return call_with_timeout(fn, timeout)
    except BudgetTimeout:
        _mark_timeout()
        return []


def _mark_timeout() -> None:
    _CACHE["degraded_reason"] = "timeout"
    _CACHE["degraded_until"] = time.monotonic() + DEGRADED_COOLDOWN_SECONDS


def _in_cooldown() -> bool:
    return float(_CACHE.get("degraded_until") or 0) > time.monotonic()


def _inject_tokens(explicit: Any, settings: Settings | None = None) -> Any:
    """Production never reads STOCK_PM_MACRO_INJECT or forwards caller inject."""
    if not inject_allowed(settings):
        return None
    if explicit is not None:
        return explicit
    return env_macro_inject()


def build_event_book(settings: Settings | None = None, *, refresh: bool = False) -> list[TrustedEvent]:
    if _CACHE["events"] is not None and not refresh:
        return list(_CACHE["events"])
    if not refresh and _in_cooldown():
        return list(_CACHE["events"] or [])
    acquired = _DISCOVER_LOCK.acquire(blocking=refresh)
    if not acquired:
        _CACHE["degraded_reason"] = _CACHE.get("degraded_reason") or "in_flight"
        return list(_CACHE["events"] or [])
    timed_out = False
    try:
        if _CACHE["events"] is not None and not refresh:
            return list(_CACHE["events"])
        if not refresh and _in_cooldown():
            return list(_CACHE["events"] or [])
        mode = events_data_mode(settings)
        discovered: list = []
        if mode == "recorded_replay":
            discovered.extend(RecordedReplayProvider().discover())
        else:
            official = _bounded_discover(OfficialFeedProvider(settings).discover)
            timed_out = timed_out or _CACHE.get("degraded_reason") == "timeout" or budget_exhausted()
            live = [] if timed_out else _bounded_discover(lambda: discover_live_documents(settings))
            timed_out = timed_out or _CACHE.get("degraded_reason") == "timeout" or budget_exhausted()
            discovered.extend(official or [])
            discovered.extend(live or [])
            if mode in {"demo", "fixture"} and not timed_out:
                from .macro_chain import load_frozen_6a_documents

                discovered.extend(load_frozen_6a_documents())
            google = GoogleDiscoveryProvider(settings)
            if google.configured() and not timed_out and not budget_exhausted():
                try:
                    discovered.extend(_bounded_discover(google.discover) or [])
                except Exception:
                    pass
            timed_out = timed_out or _CACHE.get("degraded_reason") == "timeout" or budget_exhausted()
        discovered, resolution = resolve_discovery_candidates(discovered)
        _CACHE["discovery_resolution"] = resolution
        events = build_events(discovered)
        for event in events:
            analyze_event(event)
        if timed_out and not events:
            _mark_timeout()
            _CACHE["coverage"] = None
            return []
        _CACHE["events"] = events
        _CACHE["coverage"] = None
        if not timed_out:
            _CACHE["degraded_reason"] = None
            _CACHE["degraded_until"] = 0.0
        else:
            _CACHE["degraded_reason"] = "timeout"
        return list(events)
    except BudgetTimeout:
        _mark_timeout()
        return list(_CACHE["events"] or [])
    except Exception:
        if request_budget_active() or timed_out:
            _mark_timeout()
            return list(_CACHE["events"] or [])
        raise
    finally:
        _DISCOVER_LOCK.release()


def coverage(settings: Settings | None = None, events: list[TrustedEvent] | None = None) -> dict[str, Any]:
    if events is not None:
        rows = events
    elif _CACHE["events"] is not None:
        rows = list(_CACHE["events"])
    elif _in_cooldown():
        rows = []
    else:
        if not request_budget_active():
            with discovery_budget():
                rows = build_event_book(settings)
        else:
            rows = build_event_book(settings)
    providers = provider_coverage(settings)
    google = providers["google_cse"]
    mode = events_data_mode(settings)
    if _CACHE.get("degraded_reason") and not rows:
        mode = "degraded"
    fixture_count = len(rows) if mode in {"demo", "fixture"} else 0
    replay_count = len(rows) if mode == "recorded_replay" else 0
    live_rows = [providers[name] for name in REQUIRED_LIVE if name in providers]
    live_ok = [
        row for row in live_rows if row.get("status") == "ok" and int(row.get("event_count") or 0) > 0
    ]
    live_event_count = 0 if mode in {"demo", "fixture", "recorded_replay"} else len(rows)
    ratio = (len(live_ok) / len(REQUIRED_LIVE)) if mode not in {"demo", "fixture", "recorded_replay"} else 0.0
    is_live = mode not in {"demo", "fixture", "recorded_replay", "degraded"} and bool(live_ok)
    if mode == "degraded":
        verdict = "degraded"
        note = "Live event discovery timed out or failed. Desk shows empty events."
    elif mode == "recorded_replay":
        verdict = "recorded_replay"
        note = "RECORDED REPLAY of reachable official originals. Not production live latest events."
    elif mode in {"demo", "fixture"}:
        verdict = "framework_complete_live_coverage_incomplete"
        note = "Labeled fixture/demo only. Not production live coverage."
    elif len(live_ok) == len(REQUIRED_LIVE):
        verdict = "live_official_ingest"
        note = "Production showing verified SEC / Federal Reserve / EIA events only."
    elif live_ok:
        verdict = "partial_live_official_ingest"
        note = "At least one official feed succeeded. Failed sources stay isolated on the events chain."
    else:
        verdict = "framework_complete_live_coverage_incomplete"
        note = "Live official ingest ran but no provider returned events."
    last_success = None
    for row in live_rows:
        stamp = row.get("last_success_at")
        if stamp and (last_success is None or str(stamp) > str(last_success)):
            last_success = stamp
    failed = [f"{row.get('provider')}:{row.get('reason_code')}" for row in live_rows if row.get("status") != "ok"]
    reason = None if not failed else ",".join(failed)
    if mode == "degraded" and not reason:
        reason = str(_CACHE.get("degraded_reason") or "timeout")
    provider_health_gate = mode not in {"demo", "fixture", "recorded_replay", "degraded"} and len(live_ok) == len(REQUIRED_LIVE)
    product_status = _product_status(rows, provider_health_gate=provider_health_gate, note=note)
    earnings_report = current_earnings_health()
    earnings_cover = summarize_health(earnings_report)
    if mode in {"demo", "fixture"}:
        earnings_cover["live"] = False
        earnings_cover["data_class"] = "frozen_provider_audit"
        earnings_cover["live_complete_count"] = 0
        earnings_cover["fresh_live_complete_count"] = 0
        earnings_cover["cache_stale_complete_count"] = 0
        earnings_cover["fixture_complete_count"] = int(earnings_cover.get("complete_count") or 0)
        earnings_cover["note"] = "Frozen/fixture coverage is not production live coverage."
    elif not earnings_report:
        earnings_cover["live"] = False
        earnings_cover["data_class"] = "live_current"
        earnings_cover["note"] = "No live earnings discover has run. Fixture was not loaded."
    return {
        "status": verdict,
        "verdict": verdict,
        "provider_health_gate": provider_health_gate,
        "live_e1_e10_gate": None,
        "capability_e1_e10_gate": None,
        "data_mode": "degraded" if mode == "degraded" else (mode if mode != "test" else "fixture"),
        "live": is_live,
        "live_event_count": live_event_count,
        "live_coverage_ratio": ratio,
        "fixture_event_count": fixture_count,
        "recorded_replay_event_count": replay_count,
        "recorded_replay": mode == "recorded_replay",
        "coverage": "live_official" if is_live else "incomplete_live",
        "last_success": last_success,
        "source_count": sum(len(event.sources) for event in rows),
        "event_count": len(rows),
        "conflict_count": sum(int((event.analysis or {}).get("conflict_count") or 0) for event in rows),
        "reason_code": reason,
        "providers": providers,
        "implemented_live_providers": list(REQUIRED_LIVE),
        "live_ok_providers": [row.get("provider") for row in live_ok],
        "real_source_count": len(REQUIRED_LIVE),
        "affects_chain": "events",
        "does_not_affect": ["price", "earnings", "macro_rates"],
        "note": note,
        "google_cse": google.get("status"),
        "product_status": product_status,
        "earnings_coverage": earnings_cover,
        "schedule_entry": "stock-pm-events / run_event_job",
        "discovery_resolution": dict(_CACHE.get("discovery_resolution") or {}),
    }


def _evidence_sufficiency_copy(*, valid: int, withheld: int, unsupported: int) -> tuple[str, str]:
    """User-facing evidence label. Does not change accept scoring."""
    detail = (
        f"有效结论 {valid} · 不形成方向 {withheld} · 摘录不支持 {unsupported}。"
        "摘录不支持是不形成方向的原因子集，三项不是互斥总数。"
    )
    if valid <= 0:
        return "证据不足", detail
    if withheld > 0 or unsupported > 0:
        return "部分事件证据充分", detail
    return "证据充分", detail


def _product_status(events: list[TrustedEvent], *, provider_health_gate: bool, note: str) -> dict[str, Any]:
    summary = closed_loop_summary(events)
    valid = int(summary["valid_conclusion_count"])
    withheld = int(summary["withheld_count"])
    unsupported = int(summary["unsupported_count"])
    evidence_ok = int(summary["evidence_event_count"]) > 0 and int(summary["leaked_observable_count"]) == 0
    can_conclude = summary["ok"]
    reasons: list[str] = []
    if events and int(summary["evidence_event_count"]) == 0:
        reasons.append("没有同一事件同时具备官方原文和支持性正文摘录")
    if int(summary["leaked_observable_count"]) > 0:
        reasons.append("存在仍标为可观察但证据或链条不合格的事件")
    if valid == 0:
        reasons.append(note or "证据不足，不形成方向结论")
    evidence_label, evidence_detail = _evidence_sufficiency_copy(
        valid=valid, withheld=withheld, unsupported=unsupported
    )
    return {
        "source_health": {
            "ok": provider_health_gate,
            "label": "数据源健康" if provider_health_gate else "数据源不完整",
            "detail": "SEC / Fed / EIA 官方源已接通并有实时数据"
            if provider_health_gate
            else "SEC / Fed / EIA 官方源未全部接通或没有实时数据",
        },
        "evidence_sufficiency": {
            "ok": evidence_ok,
            "label": evidence_label,
            "detail": evidence_detail,
        },
        "can_conclude": {
            "ok": can_conclude,
            "label": "可以形成观察结论" if can_conclude else "尚不能形成结论",
            "reason": "；".join(reasons) if reasons else "已确认事实并完成行业/个股暴露映射",
        },
        "valid_conclusion_count": valid,
        "withheld_count": withheld,
        "unsupported_count": unsupported,
    }


def _center_sort_key(event: TrustedEvent | dict[str, Any]) -> tuple:
    event_type = event.event_type if isinstance(event, TrustedEvent) else str(event.get("event_type") or "")
    entities = event.entities if isinstance(event, TrustedEvent) else list(event.get("entities") or [])
    published = event.published_at if isinstance(event, TrustedEvent) else event.get("published_at")
    title = event.canonical_title if isinstance(event, TrustedEvent) else str(event.get("canonical_title") or "")
    mapped = any(str(item).upper() in DISPLAY_SYMBOLS for item in entities)
    type_rank = {
        "central_bank_rates": 0,
        "energy_supply": 1,
        "inflation_employment": 2,
        "sovereign_or_corporate_debt": 3,
        "other": 4,
        "company_filing": 5 if mapped else 8,
        "company_earnings": 5 if mapped else 8,
        "vix_risk": 6,
        "war_sanctions": 1,
    }.get(event_type, 7)
    return (type_rank, published or "", title)


def market_center(settings: Settings | None = None, *, inject: Any = None, now: Any = None) -> dict[str, Any]:
    if not request_budget_active():
        with discovery_budget():
            return _market_center(settings, inject=inject, now=now)
    return _market_center(settings, inject=inject, now=now)


def _market_center(settings: Settings | None = None, *, inject: Any = None, now: Any = None) -> dict[str, Any]:
    events = build_event_book(settings)
    cover = coverage(settings, events)
    ordered = sorted(events, key=_center_sort_key)
    tokens = _inject_tokens(inject, settings)
    chains = build_market_macro_chains(events=events, settings=settings, inject=tokens)
    clock = evaluation_date(now)
    synthesis = synthesize_drivers(chains, now=clock)
    industry_forecasts = [
        build_horizon_forecast(chains, synthesis=row, scope="industry", target=row.get("target"), now=clock)
        for row in synthesis["industries"]
    ]
    return {
        "title": "市场事件中心",
        "data_mode": cover["data_mode"],
        "live": cover["live"],
        "recorded_replay": cover.get("recorded_replay") is True,
        "coverage": cover,
        "events": [event.as_dict() for event in ordered],
        "macro_chains": chains,
        "macro_driver_summary": summarize_macro_chains(chains),
        "driver_synthesis": synthesis["market"],
        "driver_syntheses": synthesis["syntheses"],
        "industry_syntheses": synthesis["industries"],
        "synthesis_summary": summarize_synthesis(synthesis),
        "horizon_forecast": build_horizon_forecast(
            chains, synthesis=synthesis["market"], scope="market", now=clock
        ),
        "industry_forecasts": industry_forecasts,
    }


def stock_events(symbol: str, settings: Settings | None = None, *, inject: Any = None, now: Any = None) -> dict[str, Any]:
    if not request_budget_active():
        with discovery_budget():
            return _stock_events_payload(symbol, settings, inject=inject, now=now)
    return _stock_events_payload(symbol, settings, inject=inject, now=now)


def _stock_events_payload(symbol: str, settings: Settings | None = None, *, inject: Any = None, now: Any = None) -> dict[str, Any]:
    events = build_event_book(settings)
    selected = []
    risk_state = None
    cover = coverage(settings, events)
    for event in events:
        if event.event_type == "vix_risk" and risk_state is None:
            analysis = event.analysis or {}
            risk_state = {
                "role": "risk_confirmation_only",
                "does_not_imply": "个股涨跌方向",
                "event_id": event.event_id,
                "canonical_title": event.canonical_title,
                "confidence": (analysis.get("confidence") or {}).get("text"),
                "evidence_refs": analysis.get("evidence_refs") or [],
            }
        view = symbol_event_view(event, symbol)
        if view:
            selected.append(view)
    selected.sort(key=_center_sort_key)
    tokens = _inject_tokens(inject, settings)
    chains = build_market_macro_chains(events=events, settings=settings, inject=tokens)
    mapped = stock_macro_chains(chains, symbol)
    clock = evaluation_date(now)
    scoped = stock_synthesis(chains, symbol, now=clock)
    vix_chain = next((row for row in chains if row.get("metric") == "vix"), None)
    if vix_chain and risk_state is None:
        risk_state = {
            "role": "risk_confirmation_only",
            "does_not_imply": "个股涨跌方向",
            "event_id": vix_chain.get("event_id") or vix_chain.get("chain_id"),
            "chain_id": vix_chain.get("chain_id"),
            "canonical_title": "VIX 风险确认",
            "confidence": vix_chain.get("confidence"),
            "counter_evidence": vix_chain.get("counter_evidence") or [],
            "what_changes": vix_chain.get("what_changes"),
            "evidence_refs": ((vix_chain.get("layers") or [{}])[0].get("evidence_refs") if vix_chain.get("layers") else []),
        }
    elif vix_chain and risk_state is not None:
        risk_state = {
            **risk_state,
            "chain_id": vix_chain.get("chain_id"),
            "counter_evidence": vix_chain.get("counter_evidence") or risk_state.get("counter_evidence") or [],
            "what_changes": vix_chain.get("what_changes"),
        }
    return {
        "symbol": symbol.upper(),
        "data_mode": cover["data_mode"],
        "live": cover["live"],
        "recorded_replay": cover.get("recorded_replay") is True,
        "coverage": cover,
        "events": selected,
        "macro_chains": mapped,
        "macro_driver_summary": summarize_macro_chains(mapped),
        "driver_synthesis": scoped,
        "driver_syntheses": [scoped] if scoped else [],
        "synthesis_summary": {
            "synthesis_id": (scoped or {}).get("synthesis_id"),
            "scope": "stock",
            "stance": ((scoped or {}).get("net_expectation") or {}).get("stance"),
            "text": ((scoped or {}).get("net_expectation") or {}).get("text"),
            "confidence": ((scoped or {}).get("confidence") or {}).get("label"),
            "why_relevant": (scoped or {}).get("why_relevant"),
            "can_form_direction": False,
        } if scoped else None,
        "risk_state": risk_state,
        "earnings_health": health_for_symbol(symbol),
        "horizon_forecast": build_horizon_forecast(
            chains, synthesis=scoped, scope="stock", target=symbol.upper(), now=clock
        ),
        "note": "个股页只显示经行业映射和公司暴露判定相关的事件，并说明为什么相关。VIX 只确认风险，不复制成个股涨跌。宏观事件不会复制到全部股票。",
    }


def event_detail(event_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    if not request_budget_active():
        with discovery_budget():
            return _event_detail(event_id, settings)
    return _event_detail(event_id, settings)


def _event_detail(event_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    for event in build_event_book(settings):
        if event.event_id == event_id:
            return event.as_dict()
    return None


def reset_cache() -> None:
    _CACHE["events"] = None
    _CACHE["coverage"] = None
    _CACHE["discovery_resolution"] = None
    _CACHE["degraded_until"] = 0.0
    _CACHE["degraded_reason"] = None
    reset_live_state()
    from .earnings_health import clear_earnings_health_memory
    from .watchlist import reset_watchlist_override

    clear_earnings_health_memory()
    reset_watchlist_override()
    reset_macro_cache()


def display_symbols() -> tuple[str, ...]:
    return DISPLAY_SYMBOLS
