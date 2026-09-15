from __future__ import annotations

import json
import re
import threading
from contextlib import asynccontextmanager
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .database import Database
from .errors import DatabaseError
from .review import retry_reviews_for_llm

SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")

database = Database()
_database_reachable = False


def _warm_event_book() -> None:
    try:
        from .events.service import build_event_book

        build_event_book(refresh=True)
    except Exception as exc:
        print(json.dumps({"events_warm_error": type(exc).__name__, "affects_chain": "events"}, ensure_ascii=False))


def _backfill_environment_snapshots() -> None:
    try:
        if not hasattr(database, "append_environment_snapshot"):
            return
        from .environment_job import publish_if_missing

        result = publish_if_missing(database)
        if result.get("status") != "skipped":
            print(
                json.dumps(
                    {"environment_backfill": result},
                    ensure_ascii=False,
                    default=str,
                )
            )
    except Exception as exc:
        print(json.dumps({"environment_backfill_error": str(exc)}, ensure_ascii=False))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _database_reachable
    try:
        _database_reachable = bool(database.ping())
        if _database_reachable:
            database.initialize()
            threading.Thread(
                target=_backfill_environment_snapshots,
                name="environment-backfill",
                daemon=True,
            ).start()
            threading.Thread(
                target=_warm_event_book,
                name="events-warm",
                daemon=True,
            ).start()
        else:
            print(json.dumps({"database_init_error": "postgres unreachable; real health still serves official FRED"}, ensure_ascii=False))
    except Exception as exc:
        _database_reachable = False
        print(json.dumps({"database_init_error": str(exc)}, ensure_ascii=False))
    yield
    try:
        database.close()
    except Exception:
        pass


app = FastAPI(
    title="Stock PM",
    version="0.9.0",
    description=(
        "Watchlist analysis API. Knife 4: Prediction "
        "(/api/stock/{symbol}/prediction, /predictions, /prediction/checks) "
        "and judgment-change supersede. Knife 3 TapeAnalysis and Knife 2 "
        "EnvironmentSnapshot remain as premises."
    ),
    lifespan=lifespan,
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))


def refresh_database_reachable() -> bool:
    global _database_reachable
    ping = getattr(database, "ping", None)
    try:
        _database_reachable = bool(ping()) if callable(ping) else False
    except Exception:
        _database_reachable = False
    return _database_reachable


def database_monitor_status() -> dict:
    monitor = getattr(database, "monitor_status", None)
    if callable(monitor):
        try:
            status = monitor()
            global _database_reachable
            _database_reachable = bool(status.get("reachable"))
            return status
        except Exception:
            pass
    reachable = refresh_database_reachable()
    return {
        "status": "ok" if reachable else "error",
        "reachable": reachable,
        "database": "connected" if reachable else "unavailable",
        "reason_code": None if reachable else "query_error",
        "note": None if reachable else "PostgreSQL unreachable; live overlay does not hide this",
    }


def _degraded_payload(dataset: str, **extra) -> dict:
    payload = {
        "status": "error",
        "reason_code": "query_error",
        "dataset": dataset,
        "database": database_monitor_status(),
    }
    payload.update(extra)
    return payload


def _read_list(loader):
    try:
        return loader()
    except DatabaseError:
        return []


def _read_dict(dataset: str, loader, fallback: dict | None = None):
    try:
        return loader()
    except DatabaseError:
        return _degraded_payload(dataset, **(fallback or {}))


def _page(name: str) -> str:
    return files("stock_pm").joinpath(f"static/{name}").read_text(encoding="utf-8")


# ---------------------------------------------------------------- pages

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def overview_page() -> str:
    return _page("overview.html")


@app.get("/stock/{symbol}", response_class=HTMLResponse, include_in_schema=False)
def stock_page(symbol: str) -> str:
    return _page("stock.html")


@app.get("/stock", include_in_schema=False)
def stock_index() -> RedirectResponse:
    try:
        rows = database.watchlist_rows()
    except DatabaseError:
        rows = []
    symbol = (rows[0].get("symbol") if rows else None) or "NVDA"
    return RedirectResponse(f"/stock/{symbol}", status_code=307)


@app.get("/replay", response_class=HTMLResponse, include_in_schema=False)
def replay_page() -> str:
    return _page("replay.html")


@app.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_page() -> str:
    return _page("settings.html")


@app.get("/live", include_in_schema=False)
def legacy_live() -> RedirectResponse:
    return RedirectResponse("/", status_code=307)


@app.get("/review", response_class=HTMLResponse, include_in_schema=False)
def review_page() -> str:
    return _page("review.html")


@app.get("/events", response_class=HTMLResponse, include_in_schema=False)
def events_page() -> str:
    return _page("events.html")


@app.get("/accept/e1-e10", response_class=HTMLResponse, include_in_schema=False)
def accept_e1_e10_page() -> str:
    return _page("accept.html")


@app.get("/api/accept/e1-e10")
def api_accept_e1_e10() -> dict:
    from .events.accept_report import load_accept_reports

    return load_accept_reports()


# ---------------------------------------------------------------- health & watchlist

@app.get("/health")
def health() -> dict:
    status = database_monitor_status()
    return {
        "status": "ok" if status.get("reachable") else "error",
        "database": status.get("database"),
        "database_status": status.get("status"),
        "reason_code": status.get("reason_code"),
        "note": status.get("note"),
        "data_source": "alpaca",
    }


@app.get("/api/watchlist")
def watchlist(include_inactive: bool = False) -> list[dict]:
    return _read_list(lambda: database.watchlist_rows(include_inactive=include_inactive))


def _backfill_symbol(symbol: str) -> None:
    """Best-effort history backfill for a newly added symbol."""
    try:
        from .alpaca import collect as alpaca_collect

        payload, _ = alpaca_collect("daily", [symbol])
        database.ingest(payload)
    except Exception:
        pass
    try:
        from .fundamentals import collect as fundamentals_collect

        payload, _ = fundamentals_collect([symbol])
        database.ingest(payload)
    except Exception:
        pass


@app.post("/api/watchlist", status_code=201)
def add_watchlist(
    body: Annotated[dict, Body()],
    background: BackgroundTasks,
) -> dict:
    symbol = str(body.get("symbol", "")).upper().strip()
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="symbol must match [A-Z][A-Z0-9.]{0,9}")
    row = {
        "symbol": symbol,
        "name": body.get("name") or symbol,
        "primary_exchange": body.get("primary_exchange", ""),
        "asset_class": body.get("asset_class", "stocks"),
        "sector": body.get("sector"),
        "themes": body.get("themes") or [],
        "rate_sensitivity": body.get("rate_sensitivity", "medium"),
    }
    try:
        from .alpaca import AlpacaClient, TRADING_API

        client = AlpacaClient()
        asset = client.get(TRADING_API, f"/v2/assets/{symbol}")
        if not asset.get("tradable", True):
            raise HTTPException(status_code=400, detail=f"{symbol} is not tradable on Alpaca")
        row["name"] = body.get("name") or asset.get("name") or symbol
        row["primary_exchange"] = asset.get("exchange", row["primary_exchange"])
    except HTTPException:
        raise
    except Exception:
        # Missing Alpaca keys or a lookup failure: accept the row as provided;
        # data starts flowing on the next scheduled sync.
        pass
    try:
        database.upsert_watchlist(row)
    except DatabaseError as exc:
        raise _http_error(exc) from exc
    background.add_task(_backfill_symbol, symbol)
    return {"status": "added", "symbol": symbol, "backfill": "scheduled"}


@app.delete("/api/watchlist/{symbol}")
def remove_watchlist(symbol: str) -> dict:
    try:
        database.deactivate_watchlist(symbol)
    except DatabaseError as exc:
        raise _http_error(exc) from exc
    return {"status": "deactivated", "symbol": symbol.upper()}


# ---------------------------------------------------------------- market (all symbols)

@app.get("/api/sync/status")
def sync_status() -> dict:
    return _read_dict("sync_runs", lambda: database.sync_status() or {"status": "never_synced"})


@app.get("/api/market/snapshot")
def market_snapshot(
    symbols: Annotated[list[str] | None, Query()] = None,
) -> list[dict]:
    try:
        return database.latest_snapshots(symbols)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/market/signals")
def market_signals(
    symbols: Annotated[list[str] | None, Query()] = None,
) -> list[dict]:
    try:
        return database.live_signals(symbols)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/market/technicals")
def market_technicals() -> list[dict]:
    return _read_list(database.technical_summary)


@app.get("/api/market/events")
def market_events(
    symbol: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict]:
    try:
        return database.market_events(symbol, limit)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/events")
async def api_market_events(request: Request, macro_inject: str | None = Query(None)) -> dict:
    from .decision.inject import inject_allowed
    from .events.service import market_center

    tokens = None
    if inject_allowed():
        tokens = macro_inject or request.headers.get("x-stock-pm-macro-inject")
        return await run_in_threadpool(market_center, inject=tokens)
    return await run_in_threadpool(market_center)


@app.get("/api/events/coverage")
async def api_events_coverage() -> dict:
    from .events.service import coverage

    return await run_in_threadpool(coverage)


@app.get("/api/events/{event_id}")
async def api_event_detail(event_id: str) -> dict:
    from .events.service import event_detail

    payload = await run_in_threadpool(event_detail, event_id)
    if not payload:
        raise HTTPException(status_code=404, detail="event_not_found")
    return payload


@app.get("/api/stock/{symbol}/events")
async def api_stock_events(symbol: str, request: Request, macro_inject: str | None = Query(None)) -> dict:
    from .decision.inject import inject_allowed
    from .events.service import stock_events

    if inject_allowed():
        tokens = macro_inject or request.headers.get("x-stock-pm-macro-inject")
        return await run_in_threadpool(stock_events, symbol, inject=tokens)
    return await run_in_threadpool(stock_events, symbol)


@app.get("/api/market/news")
def market_news(
    symbols: Annotated[list[str] | None, Query()] = None,
    limit: int = Query(60, ge=1, le=200),
) -> list[dict]:
    try:
        return database.news(symbols, limit)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/market/earnings/recent")
def market_recent_earnings(limit: int = Query(8, ge=1, le=50)) -> list[dict]:
    return _read_list(lambda: database.recent_earnings(limit))


@app.get("/api/market/impact")
def market_impact(days: int = Query(14, ge=1, le=90)) -> dict:
    return _read_dict(
        "market_impact",
        lambda: database.market_impact(days),
        {"macro": [], "macro_unanalyzed": [], "upcoming": [], "news_themes": []},
    )


@app.get("/api/market/session")
def market_session(
    date_: Annotated[str | None, Query(alias="date")] = None,
) -> dict:
    try:
        if date_:
            date.fromisoformat(date_)
        return database.market_session(date_)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc
    except DatabaseError:
        return _degraded_payload("market_session", trade_date=date_)


@app.get("/api/market/options-overview")
def options_overview(
    date_: Annotated[str | None, Query(alias="date")] = None,
) -> dict:
    try:
        if date_:
            date.fromisoformat(date_)
        row = database.cboe_option_stats(date_)
        if not row:
            return {"status": "missing", "trade_date": date_}
        return {"status": "ok", **row}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc
    except DatabaseError:
        return _degraded_payload("cboe_option_stats", trade_date=date_)


# ---------------------------------------------------------------- single stock

@app.get("/api/stock/{symbol}/history")
def stock_history(
    symbol: str,
    limit: int = Query(400, ge=1, le=5000),
    bar_size: str = Query("1d"),
) -> list[dict]:
    try:
        return database.history(symbol, limit, bar_size)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/stock/{symbol}/chart")
def stock_chart(
    symbol: str,
    limit: int = Query(260, ge=50, le=1000),
    interval: str = Query("1d"),
) -> dict:
    try:
        return database.chart_history(symbol, limit, interval)
    except ValueError as exc:
        raise _http_error(exc) from exc
    except DatabaseError:
        return _degraded_payload(
            "daily_price_bars",
            symbol=symbol.upper(),
            interval=interval,
            bars=[],
            source=None,
            as_of=None,
        )


@app.get("/api/stock/{symbol}/intraday")
def stock_intraday(symbol: str, limit: int = Query(600, ge=1, le=3000)) -> list[dict]:
    try:
        return database.intraday_history(symbol, limit)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/stock/{symbol}/segments")
def stock_segments(symbol: str, date: str | None = None) -> dict:
    try:
        return {
            "segments": database.segments(symbol, date),
            "dates": [str(row["trade_date"]) for row in database.segment_dates(symbol)],
        }
    except (DatabaseError, ValueError):
        return _degraded_payload("intraday_segments", segments=[], dates=[])


@app.get("/api/stock/{symbol}/large-trades")
def stock_large_trades(
    symbol: str,
    date: str | None = None,
    min_notional: float | None = Query(None, ge=0),
) -> list[dict]:
    try:
        return database.large_trades(symbol, date, min_notional)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/stock/{symbol}/overview")
def stock_overview(symbol: str) -> dict:
    try:
        return database.investment_overview(symbol)
    except (DatabaseError, ValueError):
        return _degraded_payload(
            "overview",
            symbol=symbol.upper(),
            technical=None,
            sentiment=None,
            valuation=None,
            earnings=[],
        )


def _request_inject(request: Request, inject: str | None) -> frozenset[str]:
    from .decision.inject import inject_allowed, parse_inject_tokens

    if not inject_allowed():
        return frozenset()
    return parse_inject_tokens([inject or "", request.headers.get("x-stock-pm-inject") or ""])


@app.get("/api/stock/{symbol}/decision")
def stock_decision(
    request: Request,
    symbol: str,
    preview: str | None = Query(None),
    inject: str | None = Query(None),
) -> dict:
    from .decision.assemble import assemble_from_bundle
    from .decision.preview import PREVIEW_LABELS, build_preview, preview_allowed
    from .live_bundle import overlay_live_bundle

    key = (preview or "").strip().upper()
    try:
        if key in PREVIEW_LABELS and preview_allowed():
            return build_preview(symbol, key)
        packed = overlay_live_bundle(
            database, symbol, persist=True, inject=_request_inject(request, inject)
        )
        return assemble_from_bundle(packed["bundle"])
    except ValueError as exc:
        raise _http_error(exc) from exc
    except DatabaseError:
        return _degraded_payload("decision", symbol=symbol.upper())


@app.get("/api/stock/{symbol}/data-health")
def stock_data_health(
    request: Request,
    symbol: str,
    preview: str | None = Query(None),
    inject: str | None = Query(None),
) -> dict:
    from .decision.assemble import assemble_from_bundle
    from .decision.health import HEALTH_PREVIEW_LABELS, build_data_health, build_health_preview
    from .decision.preview import preview_allowed
    from .live_bundle import overlay_live_bundle

    key = (preview or "").strip().upper()
    try:
        if key in HEALTH_PREVIEW_LABELS and preview_allowed():
            return build_health_preview(symbol, key)
        packed = overlay_live_bundle(
            database, symbol, persist=True, inject=_request_inject(request, inject)
        )
        bundle = packed["bundle"]
        db_status = packed["db_status"]
        persistence = packed["persistence"]
        query_errors = packed["query_errors"]
        settings = packed["settings"]
        live_report = packed["live_report"]
        bar_report = packed["bar_report"]
        earn_report = packed["earn_report"]
        try:
            view = assemble_from_bundle(bundle)
            judgment = view.get("overall")
        except Exception:
            judgment = None
        payload = build_data_health(
            bundle,
            settings=settings,
            judgment=judgment,
            query_errors=query_errors,
            synthetic=False,
        )
        series_report = {}
        eps_rec = (earn_report or {}).get("earnings_reports")
        if eps_rec:
            series_report["eps"] = {
                "source": eps_rec.get("source"),
                "series_or_symbol": eps_rec.get("series_or_symbol"),
                "as_of": eps_rec.get("as_of"),
                "value": eps_rec.get("value"),
                "unit": eps_rec.get("unit"),
                "status": eps_rec.get("status"),
                "reason_code": eps_rec.get("reason_code"),
                "http_source": eps_rec.get("http_source"),
                "transport": eps_rec.get("transport"),
            }
        close_rec = (bar_report or {}).get("daily_price_bars")
        if close_rec:
            series_report["close"] = {
                "source": close_rec.get("source"),
                "series_or_symbol": close_rec.get("series_or_symbol"),
                "as_of": close_rec.get("as_of"),
                "value": close_rec.get("value"),
                "unit": close_rec.get("unit"),
                "status": close_rec.get("status"),
                "reason_code": close_rec.get("reason_code"),
                "http_source": close_rec.get("http_source"),
                "transport": close_rec.get("transport"),
            }
        for metric, rec in (live_report.get("series") or {}).items():
            series_report[metric] = {
                "source": rec.get("source"),
                "series_or_symbol": rec.get("series_or_symbol"),
                "as_of": rec.get("as_of"),
                "value": rec.get("value"),
                "unit": rec.get("unit"),
                "status": rec.get("status"),
                "reason_code": rec.get("reason_code"),
                "http_source": rec.get("http_source"),
                "transport": rec.get("transport"),
            }
        payload["runtime"] = "real"
        payload["runtime_fetched_at"] = live_report.get("fetched_at")
        payload["http_sources"] = {
            metric: row.get("http_source") for metric, row in series_report.items()
        }
        payload["series_report"] = series_report
        payload["database"] = db_status
        payload["persistence"] = persistence
        try:
            from .events.service import coverage as event_coverage

            payload["events_coverage"] = event_coverage(settings)
        except Exception:
            payload["events_coverage"] = {
                "status": "degraded",
                "affects_chain": "events",
                "does_not_affect": ["price", "earnings", "macro_rates"],
            }
        for row in payload.get("datasets") or []:
            rec = series_report.get(row.get("metric") or "") or {}
            if not row.get("http_source") and rec.get("http_source"):
                row["http_source"] = rec.get("http_source")
                row["transport"] = rec.get("transport") or row.get("transport")
        return payload
    except ValueError as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/fundamentals")
def stock_fundamentals(symbol: str) -> dict:
    try:
        return database.latest_fundamentals(symbol) or {
            "symbol": symbol.upper(),
            "status": "awaiting_sync",
        }
    except (DatabaseError, ValueError):
        return _degraded_payload("fundamentals", symbol=symbol.upper())


@app.get("/api/stock/{symbol}/earnings/summary")
def stock_earnings_summary(symbol: str) -> dict:
    try:
        return database.earnings_summary_view(symbol)
    except (DatabaseError, ValueError):
        return _degraded_payload("earnings_reports", latest=None, history=[], highlights=[])


@app.get("/api/stock/{symbol}/earnings")
def stock_earnings(symbol: str) -> list[dict]:
    try:
        return database.earnings_history(symbol)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/stock/{symbol}/valuation/history")
def stock_valuation_history(
    symbol: str,
    limit: int = Query(260, ge=8, le=1000),
) -> dict:
    try:
        return database.valuation_history(symbol, limit)
    except (DatabaseError, ValueError):
        return _degraded_payload("fundamentals", current=None, series=[], metrics={}, coverage={})


@app.get("/api/stock/{symbol}/volume-profile")
def stock_volume_profile(
    symbol: str,
    lookback: int = Query(60, ge=10, le=250),
) -> dict:
    try:
        return database.volume_profile_view(symbol, lookback)
    except (DatabaseError, ValueError):
        return _degraded_payload("volume_profile", buckets=[], lookback=lookback)


@app.get("/api/stock/{symbol}/capital-flow")
def stock_capital_flow(
    symbol: str,
    days: int = Query(5, ge=1, le=30),
) -> dict:
    try:
        return database.capital_flow_view(symbol, days)
    except (DatabaseError, ValueError):
        return _degraded_payload("capital_flow", tiers=[], timeline=[], days=days)


@app.get("/api/stock/{symbol}/sentiment")
def stock_sentiment(symbol: str) -> dict:
    try:
        return database.sentiment_summary(symbol)
    except (DatabaseError, ValueError):
        return _degraded_payload("news_articles", symbol=symbol.upper())


@app.get("/api/stock/{symbol}/options")
def stock_options(
    request: Request,
    symbol: str,
    inject: str | None = Query(None),
) -> list[dict]:
    if "missing_options" in _request_inject(request, inject):
        return []
    try:
        return database.option_wall(symbol)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/stock/{symbol}/news")
def stock_news(
    request: Request,
    symbol: str,
    limit: int = Query(30, ge=1, le=100),
    inject: str | None = Query(None),
) -> list[dict]:
    if "missing_news" in _request_inject(request, inject):
        return []
    try:
        return database.news([symbol], limit)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/stock/{symbol}/reviews")
def stock_reviews(symbol: str) -> list[dict]:
    try:
        return database.latest_reviews(symbol)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/stock/{symbol}/tape")
def stock_tape(
    symbol: str,
    date_: Annotated[str | None, Query(alias="date")] = None,
) -> dict:
    try:
        if date_:
            date.fromisoformat(date_)
        if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        return database.tape_payload(date_, symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseError:
        return _degraded_payload("tape_analyses", symbol=symbol.upper())


@app.get("/api/stock/{symbol}/tape/history")
def stock_tape_history(
    symbol: str,
    limit: int = Query(30, ge=1, le=120),
) -> list[dict]:
    try:
        if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        return database.tape_history(symbol.upper(), limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseError:
        return []


@app.get("/api/stock/{symbol}/prediction")
def stock_prediction(
    symbol: str,
    date_: Annotated[str | None, Query(alias="date")] = None,
) -> dict:
    try:
        if date_:
            date.fromisoformat(date_)
        if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        return database.prediction_payload(date_, symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseError:
        return _degraded_payload("predictions", symbol=symbol.upper())


@app.get("/api/stock/{symbol}/predictions")
def stock_prediction_history(
    symbol: str,
    limit: int = Query(30, ge=1, le=120),
) -> list[dict]:
    try:
        if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        return database.prediction_history(symbol.upper(), limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseError:
        return []


@app.get("/api/stock/{symbol}/prediction/checks")
def stock_prediction_checks(
    symbol: str,
    date_: Annotated[str | None, Query(alias="date")] = None,
    limit: int = Query(60, ge=1, le=180),
) -> list[dict]:
    try:
        if date_:
            date.fromisoformat(date_)
        if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        pred = database.prediction_payload(date_, symbol.upper())
        pred_id = pred.get("id")
        if not pred_id:
            return []
        return database.prediction_checks(pred_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseError:
        return []


@app.post("/api/stock/{symbol}/predictions/{prediction_id}/supersede")
def stock_prediction_supersede(
    symbol: str,
    prediction_id: int,
    body: Annotated[dict, Body()],
) -> dict:
    try:
        if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        existing = database.prediction_by_id(prediction_id)
        if not existing:
            raise ValueError(f"No prediction {prediction_id}")
        if existing.get("symbol") != symbol.upper():
            raise ValueError("prediction does not belong to symbol")
        return database.supersede_prediction(prediction_id, body or {})
    except ValueError as exc:
        raise _http_error(exc) from exc
    except DatabaseError as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/review-notes")
def stock_review_notes(
    symbol: str,
    date_: Annotated[str | None, Query(alias="date")] = None,
    limit: int = Query(30, ge=1, le=120),
) -> list[dict]:
    try:
        if date_:
            date.fromisoformat(date_)
        if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        if date_:
            note = database.review_note_payload(date_, symbol.upper())
            return [note] if note else []
        return database.review_note_history(symbol.upper(), limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseError:
        return []


@app.get("/api/reviews")
def reviews(symbol: str | None = None) -> list[dict]:
    try:
        return database.latest_reviews(symbol)
    except (DatabaseError, ValueError):
        return []


@app.get("/api/briefing")
def briefing(date_: Annotated[str | None, Query(alias="date")] = None) -> dict:
    try:
        if date_:
            date.fromisoformat(date_)
        return database.briefing(date_)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc
    except DatabaseError:
        return _degraded_payload("daily_reviews", rows=[], hit_rate=None)


@app.get("/api/desk/overview")
async def desk_overview() -> dict:
    from .pack.assemble import build_overview

    try:
        return await run_in_threadpool(build_overview, database)
    except DatabaseError:
        return _degraded_payload("desk_overview", featured=None, carousel=[], focus={"priority": [], "watch": [], "skip": []})


@app.get("/api/desk/stock/{symbol}")
async def desk_stock(symbol: str) -> dict:
    from .pack.assemble import build_stock

    if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
        raise HTTPException(status_code=400, detail="invalid symbol")
    try:
        return await run_in_threadpool(build_stock, database, symbol.upper())
    except DatabaseError:
        return _degraded_payload("desk_stock", symbol=symbol.upper())


@app.get("/api/desk/review")
async def desk_review() -> dict:
    from .pack.assemble import build_review

    try:
        return await run_in_threadpool(build_review, database)
    except DatabaseError:
        return _degraded_payload("desk_review", formal=[], observations=[], learning=[])


@app.get("/api/shell")
def shell_state(
    date_: Annotated[str | None, Query(alias="date")] = None,
    symbol: str | None = None,
) -> dict:
    try:
        if date_:
            date.fromisoformat(date_)
        if symbol and not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        return database.shell_state(date_, symbol.upper() if symbol else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseError:
        return _degraded_payload("shell")


@app.get("/api/environment")
def environment_snapshot(
    date_: Annotated[str | None, Query(alias="date")] = None,
    symbol: str | None = None,
) -> dict:
    try:
        if date_:
            date.fromisoformat(date_)
        if symbol and not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        return database.environment_payload(date_, symbol.upper() if symbol else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseError:
        return _degraded_payload(
            "environment_snapshots",
            symbol=symbol.upper() if symbol else None,
            scope="symbol" if symbol else "market",
            publishState="missing",
        )


@app.get("/api/environment/history")
def environment_history(
    symbol: str,
    limit: int = Query(30, ge=1, le=120),
) -> list[dict]:
    try:
        if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        return database.environment_history(symbol.upper(), limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DatabaseError:
        return []


@app.get("/api/jobs")
def job_runs(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    return _read_list(lambda: database.job_runs(limit))


@app.post("/api/reviews/retry-llm")
def retry_llm(
    date_: Annotated[str | None, Query(alias="date")] = None,
    symbol: Annotated[str | None, Query()] = None,
) -> dict:
    try:
        if date_:
            date.fromisoformat(date_)
        if symbol and not SYMBOL_PATTERN.fullmatch(symbol.upper()):
            raise ValueError("invalid symbol")
        result = retry_reviews_for_llm(database, date_, symbol.upper() if symbol else None)
        result["briefing"] = database.briefing(result.get("date"))
        return result
    except ValueError as exc:
        raise _http_error(exc) from exc
    except DatabaseError as exc:
        raise _http_error(exc) from exc


@app.patch("/api/reviews/{symbol}/{review_date}")
def patch_review(symbol: str, review_date: str, body: Annotated[dict, Body()]) -> dict:
    try:
        date.fromisoformat(review_date)
        normalized = database._watchlist_symbol(symbol)
        return database.update_review_user(normalized, review_date, body)
    except ValueError as exc:
        raise _http_error(exc) from exc
    except DatabaseError as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------- replay

@app.get("/api/replay/day")
def replay_day(date_: Annotated[str, Query(alias="date")]) -> dict:
    try:
        date.fromisoformat(date_)
        return database.replay_day(date_)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc
    except DatabaseError:
        return _degraded_payload(
            "replay_day",
            date=date_,
            reviews=[],
            segments=[],
            events=[],
            macro=[],
        )


@app.get("/api/replay/range")
def replay_range(
    symbol: str,
    start: Annotated[str, Query(alias="from")],
    end: Annotated[str, Query(alias="to")],
) -> dict:
    try:
        start_day = date.fromisoformat(start)
        end_day = date.fromisoformat(end)
        if (end_day - start_day).days > 10:
            raise ValueError("分钟回放区间不能超过 10 个自然日")
        result = database.daily_range(symbol, start, end)
        result["events"] = database.events_between(start, end, symbol)
        result["macro"] = database.macro_events_between(start, end)
        result["reviews"] = database.reviews_between(symbol, start, end)
        result["segments"] = database.segments_between(symbol, start, end)
        return result
    except ValueError as exc:
        raise _http_error(exc) from exc
    except DatabaseError:
        return _degraded_payload(
            "replay_range",
            symbol=symbol.upper(),
            bars=[],
            events=[],
            macro=[],
            reviews=[],
            segments=[],
        )


# ---------------------------------------------------------------- macro maintenance

@app.get("/api/macro/events")
def macro_events(
    start: Annotated[str | None, Query(alias="from")] = None,
    end: Annotated[str | None, Query(alias="to")] = None,
) -> list[dict]:
    return _read_list(
        lambda: database.macro_events_between(start or "1970-01-01", end or "2999-01-01")
    )


@app.post("/api/macro/events")
def upsert_macro_event(body: Annotated[dict, Body()]) -> dict:
    required = {"event_type", "event_time", "name"}
    missing = required - body.keys()
    if missing:
        raise HTTPException(status_code=400, detail=f"missing fields: {', '.join(sorted(missing))}")
    try:
        database.store_macro_event(body)
    except DatabaseError as exc:
        raise _http_error(exc) from exc
    return {"status": "ok"}


app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).resolve().parent / "static"),
    name="static",
)


def run() -> None:
    # workers>=2 keeps /health and static pages up if one worker is in discovery.
    uvicorn.run("stock_pm.api:app", host="127.0.0.1", port=8000, reload=False, workers=2)


if __name__ == "__main__":
    run()
