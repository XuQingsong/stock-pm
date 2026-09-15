"""Brain research HTTP API. Independent of desk routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException

from .errors import CrossTickerError, DepthLimitError, ProvenanceError, ResearchPermissionError
from .service import ResearchService
from .store import ResearchStore
from .types import ACTOR_API, ACTOR_PM


router = APIRouter(prefix="/api/research", tags=["research"])
_service_override: ResearchService | None = None


def get_service() -> ResearchService:
    if _service_override is not None:
        return _service_override
    from stock_pm.api import database

    return ResearchService(ResearchStore(database))


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, ResearchPermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (ProvenanceError, CrossTickerError, DepthLimitError, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))


def _actor(body: dict[str, Any] | None, default: str = ACTOR_API) -> str:
    return str((body or {}).get("actor") or default)


@router.get("/{symbol}/issuer")
def get_issuer(symbol: str) -> dict[str, Any]:
    try:
        row = get_service().get_issuer(symbol)
    except Exception as exc:
        raise _http(exc) from exc
    if row:
        return row
    return {"ticker": symbol.upper(), "status": "missing", "missing_fields": ["cik", "fiscal_year_end_month", "legal_name"]}


@router.put("/{symbol}/issuer")
def put_issuer(symbol: str, body: Annotated[dict, Body()]) -> dict[str, Any]:
    try:
        return get_service().ensure_issuer(symbol, **body)
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/pack")
def get_pack(symbol: str) -> dict[str, Any]:
    try:
        return get_service().get_pack(symbol)
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/backfill")
def get_backfill(symbol: str) -> dict[str, Any]:
    try:
        store = get_service().store
        row = store.latest_backfill(symbol.upper()) if hasattr(store, "latest_backfill") else None
    except Exception as exc:
        raise _http(exc) from exc
    if row:
        return row
    return {"ticker": symbol.upper(), "status": "missing", "steps": {}}


@router.post("/{symbol}/backfill", status_code=201)
def run_backfill(symbol: str, body: Annotated[dict, Body()] | None = None) -> dict[str, Any]:
    payload = body or {}
    try:
        from .backfill import ResearchDataBackfill

        service = get_service()
        result = ResearchDataBackfill(service).run(
            symbol,
            workflow_run_id=payload.get("workflow_run_id"),
            force=bool(payload.get("force")),
        )
        return result
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/pack/rebuild")
def rebuild_pack(symbol: str, body: Annotated[dict, Body()] | None = None) -> dict[str, Any]:
    payload = body or {}
    try:
        return get_service().build_pack(symbol, workflow_run_id=payload.get("workflow_run_id"))
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/review")
def research_review(symbol: str) -> dict[str, Any]:
    try:
        from .review_view import build_research_review

        return build_research_review(get_service(), symbol)
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/chain")
def research_chain(symbol: str, workflow_run_id: str | None = None) -> dict[str, Any]:
    try:
        return get_service().research_snapshot(symbol, workflow_run_id)
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/tasks")
def list_tasks(symbol: str, workflow_run_id: str | None = None) -> list[dict[str, Any]]:
    try:
        return get_service().store.list_tasks(symbol.upper(), workflow_run_id)
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/tasks", status_code=201)
def create_task(symbol: str, body: Annotated[dict, Body()]) -> dict[str, Any]:
    try:
        return get_service().create_task(symbol, body, actor=_actor(body))
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/tasks/{task_id}")
def get_task(symbol: str, task_id: str) -> dict[str, Any]:
    try:
        row = get_service().store.get_task(task_id)
    except Exception as exc:
        raise _http(exc) from exc
    if row is None or row.get("ticker") != symbol.upper():
        raise HTTPException(status_code=404, detail="task not found")
    return row


@router.post("/{symbol}/tasks/{task_id}/follow-ups", status_code=201)
def create_follow_ups(symbol: str, task_id: str, body: Annotated[dict, Body()]) -> dict[str, Any]:
    service = get_service()
    try:
        parent = service.store.get_task(task_id)
        if parent is None or parent.get("ticker") != symbol.upper():
            raise HTTPException(status_code=404, detail="task not found")
        run = service.store.get_workflow_run(parent.get("workflow_run_id") or "")
        max_depth = int(((run or {}).get("config_json") or {}).get("max_depth") or body.get("max_depth") or 4)
        created, dropped = service.enqueue_follow_ups(
            parent,
            list(body.get("tasks") or []),
            max_depth=max_depth,
            actor=_actor(body),
        )
        return {"created": created, "dropped": dropped, "max_depth": max_depth}
    except HTTPException:
        raise
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/evidence")
def list_evidence(symbol: str) -> list[dict[str, Any]]:
    try:
        return get_service().store.list_evidence(symbol.upper())
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/evidence", status_code=201)
def create_evidence(symbol: str, body: Annotated[dict, Body()]) -> dict[str, Any]:
    try:
        return get_service().create_evidence(symbol, body, actor=_actor(body))
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/assumptions")
def list_assumptions(symbol: str) -> list[dict[str, Any]]:
    service = get_service()
    try:
        rows = service.store.list_assumptions(symbol.upper())
        out = []
        for row in rows:
            links = service.store.list_links(assumption_id=row["id"])
            item = dict(row)
            item["supporting_evidence_ids"] = [link["evidence_id"] for link in links if link["direction"] == "support"]
            item["counter_evidence_ids"] = [link["evidence_id"] for link in links if link["direction"] == "oppose"]
            item["contextual_evidence_ids"] = [link["evidence_id"] for link in links if link["direction"] == "contextual"]
            out.append(item)
        return out
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/assumptions", status_code=201)
def create_assumption(symbol: str, body: Annotated[dict, Body()]) -> dict[str, Any]:
    try:
        return get_service().create_assumption(symbol, body, actor=_actor(body))
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/assumptions/{assumption_id}/links", status_code=201)
def link_evidence(symbol: str, assumption_id: str, body: Annotated[dict, Body()]) -> dict[str, Any]:
    try:
        return get_service().link_assumption_evidence(
            symbol,
            assumption_id=assumption_id,
            evidence_id=str(body.get("evidence_id") or ""),
            direction=str(body.get("direction") or ""),
            strength=body.get("strength"),
            reason=body.get("reason"),
            actor=_actor(body),
            workflow_run_id=body.get("workflow_run_id"),
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/assumptions/{assumption_id}/status")
def update_assumption_status(symbol: str, assumption_id: str, body: Annotated[dict, Body()]) -> dict[str, Any]:
    try:
        return get_service().update_assumption_status(
            symbol,
            assumption_id,
            actor=_actor(body, default=""),
            status=str(body.get("status") or ""),
            importance=body.get("importance"),
            thesis_role=body.get("thesis_role"),
            confidence=body.get("confidence"),
            next_verification=body.get("next_verification"),
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/thesis")
def get_thesis(symbol: str) -> dict[str, Any]:
    service = get_service()
    try:
        row = service.store.get_latest_thesis(symbol.upper())
        return row or service.empty_thesis(symbol)
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/thesis/history")
def thesis_history(symbol: str) -> list[dict[str, Any]]:
    try:
        return get_service().store.list_theses(symbol.upper())
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/thesis", status_code=201)
def create_thesis(symbol: str, body: Annotated[dict, Body()]) -> dict[str, Any]:
    try:
        return get_service().create_thesis(symbol, body, actor=_actor(body, default=""))
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/valuation")
def get_valuation(symbol: str) -> dict[str, Any]:
    service = get_service()
    try:
        thesis = service.store.get_latest_thesis(symbol.upper())
        if not thesis:
            return service.empty_valuation(symbol)
        row = service.store.get_valuation_for_thesis(thesis["id"])
        return row or service.empty_valuation(symbol)
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/valuation", status_code=201)
def create_valuation(symbol: str, body: Annotated[dict, Body()]) -> dict[str, Any]:
    try:
        return get_service().create_valuation(symbol, body, actor=_actor(body, default=ACTOR_PM))
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/workflow/runs", status_code=201)
def create_workflow_run(symbol: str, body: Annotated[dict, Body()] | None = None) -> dict[str, Any]:
    payload = body or {}
    try:
        if payload.get("execute") or payload.get("start"):
            from .workflow import run_new_ticker_research

            result = run_new_ticker_research(
                get_service(),
                symbol,
                trigger=str(payload.get("trigger") or "api"),
                max_depth=int(payload.get("max_depth") or 4),
                max_tasks=int(payload.get("max_tasks") or 32),
                execute=True,
            )
            run = dict(result["workflow_run"])
            if result.get("backfill"):
                counts = dict(run.get("item_counts") or {})
                counts["backfill_id"] = result["backfill"].get("id")
                counts["backfill_status"] = result["backfill"].get("status")
                run["item_counts"] = counts
                run["backfill"] = result["backfill"]
            return run
        run = get_service().start_workflow_run(
            symbol,
            workflow_name=str(payload.get("workflow_name") or "new_ticker_research"),
            trigger=str(payload.get("trigger") or "api"),
            template_id=payload.get("template_id"),
            max_depth=int(payload.get("max_depth") or 4),
            max_tasks=int(payload.get("max_tasks") or 32),
        )
        return run
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/workflow/runs")
def list_workflow_runs(symbol: str) -> list[dict[str, Any]]:
    try:
        return get_service().store.list_workflow_runs(symbol.upper())
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/workflow/runs/{run_id}")
def get_workflow_run(symbol: str, run_id: str) -> dict[str, Any]:
    try:
        row = get_service().store.get_workflow_run(run_id)
    except Exception as exc:
        raise _http(exc) from exc
    if row is None or row.get("ticker") != symbol.upper():
        raise HTTPException(status_code=404, detail="workflow run not found")
    return row


@router.post("/{symbol}/workflow/runs/{run_id}/execute")
def execute_workflow_run(symbol: str, run_id: str, body: Annotated[dict, Body()] | None = None) -> dict[str, Any]:
    payload = body or {}
    try:
        from .workflow import run_new_ticker_research

        return run_new_ticker_research(
            get_service(),
            symbol,
            workflow_run_id=run_id,
            trigger=str(payload.get("trigger") or "api"),
            max_depth=int(payload.get("max_depth") or 4),
            max_tasks=int(payload.get("max_tasks") or 32),
            execute=True,
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/workflow/runs/{run_id}/agent-runs")
def list_agent_runs(symbol: str, run_id: str) -> list[dict[str, Any]]:
    try:
        return get_service().store.list_agent_runs(symbol.upper(), run_id)
    except Exception as exc:
        raise _http(exc) from exc
