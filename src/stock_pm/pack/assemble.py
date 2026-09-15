"""I/O adapter: load live watchlist/events/quotes into frozen page payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from stock_pm.calendar import NY_TZ
from stock_pm.errors import DatabaseError

from .overview import build_overview_payload
from .review_page import build_review_payload
from .stock_page import build_stock_payload


def _watch(database) -> list[dict[str, Any]]:
    try:
        return list(database.watchlist_rows() or [])
    except (DatabaseError, Exception):
        return []


def _briefing(database) -> dict[str, Any]:
    try:
        return database.briefing() or {"rows": []}
    except (DatabaseError, Exception):
        return {"rows": [], "status": "error"}


def _degraded_cover(reason: str = "timeout") -> dict[str, Any]:
    from stock_pm.events.service import _degraded_cover as service_cover

    return service_cover(reason)


def _events_book():
    try:
        from stock_pm.events import budget as events_budget
        from stock_pm.events.service import build_event_book, coverage

        def load():
            with events_budget.discovery_budget(
                overall=events_budget.OVERALL_TIMEOUT_SECONDS,
                provider=events_budget.PROVIDER_TIMEOUT_SECONDS,
            ):
                events = build_event_book()
                cover = coverage(events=events)
                if events_budget.budget_exhausted() or (
                    not events and (cover.get("reason_code") == "timeout" or cover.get("data_mode") == "degraded")
                ):
                    cover = {**cover, "data_mode": "degraded", "live": False}
                    if not cover.get("reason_code"):
                        cover["reason_code"] = "timeout"
                return events, cover

        return events_budget.call_with_timeout(load, events_budget.DESK_ASSEMBLE_TIMEOUT_SECONDS)
    except Exception:
        return [], _degraded_cover("timeout")


def _env(database, symbol: str) -> dict[str, Any]:
    try:
        return database.environment_payload(None, symbol) or {}
    except (DatabaseError, Exception):
        return {"publishState": "missing"}


def _env_history(database, symbol: str) -> list[dict[str, Any]]:
    try:
        return list(database.environment_history(symbol, 4) or [])
    except (DatabaseError, Exception):
        return []


def _tape(database, symbol: str) -> dict[str, Any]:
    try:
        return database.tape_payload(None, symbol) or {}
    except (DatabaseError, Exception):
        try:
            rows = database.tape_history(symbol, 1)
            return rows[0] if rows else {}
        except Exception:
            return {}


def _prediction(database, symbol: str) -> dict[str, Any]:
    try:
        return database.prediction_payload(None, symbol) or {}
    except (DatabaseError, Exception):
        return {"state": "missing", "prediction_ready": False}


def _decision(database, symbol: str) -> dict[str, Any] | None:
    try:
        from stock_pm.decision.assemble import assemble_from_bundle

        return assemble_from_bundle(database.decision_bundle(symbol))
    except Exception:
        return None


def _stock_events(symbol: str) -> list[Any]:
    try:
        from stock_pm.events import budget as events_budget
        from stock_pm.events.service import stock_events

        def load():
            with events_budget.discovery_budget(
                overall=events_budget.OVERALL_TIMEOUT_SECONDS,
                provider=events_budget.PROVIDER_TIMEOUT_SECONDS,
            ):
                payload = stock_events(symbol)
                return list(payload.get("events") or [])

        return events_budget.call_with_timeout(load, events_budget.DESK_ASSEMBLE_TIMEOUT_SECONDS)
    except Exception:
        return []


def _news(database) -> list[dict[str, Any]]:
    try:
        return list(database.news(limit=40) or [])
    except (DatabaseError, Exception):
        return []


def build_overview(database, *, now: datetime | None = None) -> dict[str, Any]:
    watch = _watch(database)
    briefing = _briefing(database)
    events, cover = _events_book()
    payload = build_overview_payload(
        watch=watch,
        events=events,
        briefing=briefing,
        now=now or datetime.now(tz=NY_TZ),
        coverage=cover,
        news=_news(database),
    )
    try:
        snaps = database.latest_snapshots()
        payload["gaps"]["quotes"] = not bool(snaps)
    except Exception:
        payload["gaps"]["quotes"] = True
    return payload


def build_stock(database, symbol: str) -> dict[str, Any]:
    watch = _watch(database)
    briefing = _briefing(database)
    row = next(
        (item for item in (briefing.get("rows") or []) if str(item.get("symbol") or "").upper() == symbol.upper()),
        None,
    )
    live = next((item for item in watch if str(item.get("symbol") or "").upper() == symbol.upper()), None)
    return build_stock_payload(
        symbol=symbol,
        watch=watch,
        briefing_row=row,
        events=_stock_events(symbol),
        environment=_env(database, symbol),
        env_history=_env_history(database, symbol),
        tape=_tape(database, symbol),
        prediction=_prediction(database, symbol),
        decision=_decision(database, symbol),
        name=(live or {}).get("name"),
    )


def build_review(database, *, today=None) -> dict[str, Any]:
    watch = _watch(database)
    briefing = _briefing(database)
    predictions: dict[str, list[dict[str, Any]]] = {}
    checks: dict[str, list[dict[str, Any]]] = {}
    events_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in watch:
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        try:
            history = database.prediction_history(symbol, 8)
        except Exception:
            history = []
        if not history:
            live = _prediction(database, symbol)
            history = [live] if live else []
        predictions[symbol] = history
        for pred in history[:2]:
            pid = pred.get("id")
            if not pid:
                continue
            try:
                checks[str(pid)] = database.prediction_checks(int(pid), 8)
            except Exception:
                checks[str(pid)] = []
        try:
            from .cards import event_card

            raw = _stock_events(symbol)
            events_by_symbol[symbol] = [event_card(event, watch) for event in raw[:4]]
        except Exception:
            events_by_symbol[symbol] = []
    return build_review_payload(
        watch=watch,
        predictions=predictions,
        checks=checks,
        briefing_rows=list(briefing.get("rows") or []),
        events_by_symbol=events_by_symbol,
        today=today,
    )
