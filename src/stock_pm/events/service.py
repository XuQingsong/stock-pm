"""Build coverage + selective event views for market and stock pages."""

from __future__ import annotations

from typing import Any

from stock_pm.config import Settings

from .analyze import DISPLAY_SYMBOLS, analyze_event, causal_chain_is_complete, symbol_event_view
from .evidence import excerpt_supports_claim
from .dedupe import build_events
from .live import discover_live_documents, reset_live_state
from .policy import events_data_mode
from .providers import GoogleDiscoveryProvider, OfficialFeedProvider, provider_coverage
from .replay import RecordedReplayProvider
from .types import TrustedEvent


_CACHE: dict[str, Any] = {"events": None, "coverage": None}
REQUIRED_LIVE = ("sec_edgar", "federal_reserve", "eia_press")


def build_event_book(settings: Settings | None = None, *, refresh: bool = False) -> list[TrustedEvent]:
    if _CACHE["events"] is not None and not refresh:
        return list(_CACHE["events"])
    mode = events_data_mode(settings)
    discovered: list = []
    if mode == "recorded_replay":
        discovered.extend(RecordedReplayProvider().discover())
    else:
        official = OfficialFeedProvider(settings).discover()
        live = discover_live_documents(settings)
        discovered.extend(official)
        discovered.extend(live)
        google = GoogleDiscoveryProvider(settings)
        if google.configured():
            try:
                discovered.extend(google.discover())
            except Exception:
                pass
    events = build_events(discovered)
    for event in events:
        analyze_event(event)
    _CACHE["events"] = events
    _CACHE["coverage"] = None
    return list(events)


def coverage(settings: Settings | None = None, events: list[TrustedEvent] | None = None) -> dict[str, Any]:
    rows = events if events is not None else build_event_book(settings)
    providers = provider_coverage(settings)
    google = providers["google_cse"]
    mode = events_data_mode(settings)
    fixture_count = len(rows) if mode in {"demo", "fixture"} else 0
    replay_count = len(rows) if mode == "recorded_replay" else 0
    live_rows = [providers[name] for name in REQUIRED_LIVE if name in providers]
    live_ok = [
        row for row in live_rows if row.get("status") == "ok" and int(row.get("event_count") or 0) > 0
    ]
    live_event_count = 0 if mode in {"demo", "fixture", "recorded_replay"} else len(rows)
    ratio = (len(live_ok) / len(REQUIRED_LIVE)) if mode not in {"demo", "fixture", "recorded_replay"} else 0.0
    is_live = mode not in {"demo", "fixture", "recorded_replay"} and bool(live_ok)
    if mode == "recorded_replay":
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
    provider_health_gate = mode not in {"demo", "fixture", "recorded_replay"} and len(live_ok) == len(REQUIRED_LIVE)
    product_status = _product_status(rows, provider_health_gate=provider_health_gate, note=note)
    return {
        "status": verdict,
        "verdict": verdict,
        "provider_health_gate": provider_health_gate,
        "live_e1_e10_gate": None,
        "capability_e1_e10_gate": None,
        "data_mode": mode if mode != "test" else "fixture",
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
        "reason_code": None if not failed else ",".join(failed),
        "providers": providers,
        "implemented_live_providers": list(REQUIRED_LIVE),
        "live_ok_providers": [row.get("provider") for row in live_ok],
        "real_source_count": len(REQUIRED_LIVE),
        "affects_chain": "events",
        "does_not_affect": ["price", "earnings", "macro_rates"],
        "note": note,
        "google_cse": google.get("status"),
        "product_status": product_status,
    }


def _product_status(events: list[TrustedEvent], *, provider_health_gate: bool, note: str) -> dict[str, Any]:
    supporting = 0
    official = 0
    observable = 0
    for event in events:
        analysis = event.analysis or {}
        if analysis.get("evidence_refs"):
            official += 1
        if (analysis.get("withheld") or {}).get("status") == "observable" and causal_chain_is_complete(
            analysis.get("causal_chain")
        ):
            observable += 1
        for claim in event.claims:
            if claim.status in {"superseded", "revoked"}:
                continue
            if excerpt_supports_claim(claim.text, claim.excerpt or ""):
                supporting += 1
    reasons: list[str] = []
    if events and supporting == 0:
        reasons.append("当前没有绑定正文摘录的有效主张")
    if events and official == 0:
        reasons.append("缺少可点击官方原文")
    if observable == 0:
        reasons.append(note or "证据不足，不形成方向结论")
    evidence_ok = supporting > 0 and official > 0
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
            "label": "证据充分" if evidence_ok else "证据不足",
            "detail": f"{supporting} 条正文摘录支持当前主张" if supporting else "没有正文摘录支持当前主张",
        },
        "can_conclude": {
            "ok": observable > 0,
            "label": "可以形成观察结论" if observable > 0 else "尚不能形成结论",
            "reason": "；".join(reasons) if reasons else "已确认事实并完成行业/个股暴露映射",
        },
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
        "vix_risk": 6,
        "war_sanctions": 1,
    }.get(event_type, 7)
    return (type_rank, published or "", title)


def market_center(settings: Settings | None = None) -> dict[str, Any]:
    events = build_event_book(settings)
    cover = coverage(settings, events)
    ordered = sorted(events, key=_center_sort_key)
    return {
        "title": "市场事件中心",
        "data_mode": cover["data_mode"],
        "live": cover["live"],
        "recorded_replay": cover.get("recorded_replay") is True,
        "coverage": cover,
        "events": [event.as_dict() for event in ordered],
    }


def stock_events(symbol: str, settings: Settings | None = None) -> dict[str, Any]:
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
    return {
        "symbol": symbol.upper(),
        "data_mode": cover["data_mode"],
        "live": cover["live"],
        "recorded_replay": cover.get("recorded_replay") is True,
        "coverage": cover,
        "events": selected,
        "risk_state": risk_state,
        "note": "个股页只显示经行业映射和公司暴露判定相关的事件，并说明为什么相关。VIX 只确认风险，不复制成个股涨跌。",
    }


def event_detail(event_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    for event in build_event_book(settings):
        if event.event_id == event_id:
            return event.as_dict()
    return None


def reset_cache() -> None:
    _CACHE["events"] = None
    _CACHE["coverage"] = None
    reset_live_state()


def display_symbols() -> tuple[str, ...]:
    return DISPLAY_SYMBOLS
