"""Phase 1 Brain HTTP API. Parallel to /api/research. Does not replace it."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException

from .pipeline import run_brain
from .pm_view import build_pm_view
from .store import BrainStore
from .types import GOLDEN_TICKERS
from .view import build_brain_view, build_claim_detail, build_evidence_detail


router = APIRouter(prefix="/api/brain", tags=["brain"])
_override: dict[str, Any] | None = None


def get_brain_deps() -> tuple[Any, BrainStore]:
    if _override is not None:
        return _override["research"], _override["store"]
    from stock_pm.research.api import get_service
    from stock_pm.api import database

    research = get_service()
    return research, BrainStore(database)


def _http(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/{symbol}/pm-view")
def get_pm_view(symbol: str) -> dict[str, Any]:
    try:
        research, store = get_brain_deps()
        return build_pm_view(store, symbol, research=research)
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}")
def get_brain(symbol: str) -> dict[str, Any]:
    try:
        research, store = get_brain_deps()
        return build_brain_view(store, research, symbol)
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/{symbol}/runs", status_code=201)
def create_brain_run(symbol: str, body: Annotated[dict, Body()] | None = None) -> dict[str, Any]:
    payload = body or {}
    try:
        research, store = get_brain_deps()
        result = run_brain(
            research,
            symbol,
            store=store,
            fetch_live=bool(payload.get("fetch_live", True)),
        )
        return build_brain_view(store, research, symbol, run=result.get("run"))
    except Exception as exc:
        raise _http(exc) from exc


@router.get("/{symbol}/claims/{claim_id}")
def get_claim(symbol: str, claim_id: str) -> dict[str, Any]:
    try:
        research, store = get_brain_deps()
        payload = build_claim_detail(store, research, symbol, claim_id)
    except Exception as exc:
        raise _http(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return payload


@router.get("/{symbol}/evidence/{evidence_id}")
def get_evidence(symbol: str, evidence_id: str) -> dict[str, Any]:
    try:
        research, store = get_brain_deps()
        payload = build_evidence_detail(store, research, symbol, evidence_id)
    except Exception as exc:
        raise _http(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    return payload


@router.get("/tickers")
def list_golden() -> dict[str, Any]:
    return {"tickers": list(GOLDEN_TICKERS)}
