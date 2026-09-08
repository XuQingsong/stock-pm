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
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import Database
from .errors import DatabaseError
from .review import retry_reviews_for_llm

SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")

database = Database()


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
    database.initialize()
    threading.Thread(
        target=_backfill_environment_snapshots,
        name="environment-backfill",
        daemon=True,
    ).start()
    yield
    database.close()


app = FastAPI(
    title="Stock PM",
    version="0.8.0",
    description=(
        "Watchlist analysis API. Knife 3: TapeAnalysis "
        "(/api/stock/{symbol}/tape, /tape/history) and ReviewNote "
        "(/api/stock/{symbol}/review-notes) with append-only publishState. "
        "Knife 2 EnvironmentSnapshot remains at /api/environment."
    ),
    lifespan=lifespan,
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))


def _page(name: str) -> str:
    return files("stock_pm").joinpath(f"static/{name}").read_text(encoding="utf-8")


# ---------------------------------------------------------------- pages

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def overview_page() -> str:
    return _page("overview.html")


@app.get("/stock/{symbol}", response_class=HTMLResponse, include_in_schema=False)
def stock_page(symbol: str) -> str:
    return _page("stock.html")


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


# ---------------------------------------------------------------- health & watchlist

@app.get("/health")
def health() -> dict[str, str]:
    available = database.ping()
    return {
        "status": "ok" if available else "degraded",
        "database": "connected" if available else "unavailable",
        "data_source": "alpaca",
    }


@app.get("/api/watchlist")
def watchlist(include_inactive: bool = False) -> list[dict]:
    try:
        return database.watchlist_rows(include_inactive=include_inactive)
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    try:
        return database.sync_status() or {"status": "never_synced"}
    except DatabaseError as exc:
        raise _http_error(exc) from exc


@app.get("/api/market/snapshot")
def market_snapshot(
    symbols: Annotated[list[str] | None, Query()] = None,
) -> list[dict]:
    try:
        return database.latest_snapshots(symbols)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/market/signals")
def market_signals(
    symbols: Annotated[list[str] | None, Query()] = None,
) -> list[dict]:
    try:
        return database.live_signals(symbols)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/market/technicals")
def market_technicals() -> list[dict]:
    try:
        return database.technical_summary()
    except DatabaseError as exc:
        raise _http_error(exc) from exc


@app.get("/api/market/events")
def market_events(
    symbol: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict]:
    try:
        return database.market_events(symbol, limit)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/market/news")
def market_news(
    symbols: Annotated[list[str] | None, Query()] = None,
    limit: int = Query(60, ge=1, le=200),
) -> list[dict]:
    try:
        return database.news(symbols, limit)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/market/earnings/recent")
def market_recent_earnings(limit: int = Query(8, ge=1, le=50)) -> list[dict]:
    try:
        return database.recent_earnings(limit)
    except DatabaseError as exc:
        raise _http_error(exc) from exc


@app.get("/api/market/impact")
def market_impact(days: int = Query(14, ge=1, le=90)) -> dict:
    try:
        return database.market_impact(days)
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    except DatabaseError as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------- single stock

@app.get("/api/stock/{symbol}/history")
def stock_history(
    symbol: str,
    limit: int = Query(400, ge=1, le=5000),
    bar_size: str = Query("1d"),
) -> list[dict]:
    try:
        return database.history(symbol, limit, bar_size)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/chart")
def stock_chart(
    symbol: str,
    limit: int = Query(260, ge=50, le=1000),
    interval: str = Query("1d"),
) -> dict:
    try:
        return database.chart_history(symbol, limit, interval)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/intraday")
def stock_intraday(symbol: str, limit: int = Query(600, ge=1, le=3000)) -> list[dict]:
    try:
        return database.intraday_history(symbol, limit)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/segments")
def stock_segments(symbol: str, date: str | None = None) -> dict:
    try:
        return {
            "segments": database.segments(symbol, date),
            "dates": [str(row["trade_date"]) for row in database.segment_dates(symbol)],
        }
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/large-trades")
def stock_large_trades(
    symbol: str,
    date: str | None = None,
    min_notional: float | None = Query(None, ge=0),
) -> list[dict]:
    try:
        return database.large_trades(symbol, date, min_notional)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/overview")
def stock_overview(symbol: str) -> dict:
    try:
        return database.investment_overview(symbol)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/fundamentals")
def stock_fundamentals(symbol: str) -> dict:
    try:
        return database.latest_fundamentals(symbol) or {
            "symbol": symbol.upper(),
            "status": "awaiting_sync",
        }
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/earnings/summary")
def stock_earnings_summary(symbol: str) -> dict:
    try:
        return database.earnings_summary_view(symbol)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/earnings")
def stock_earnings(symbol: str) -> list[dict]:
    try:
        return database.earnings_history(symbol)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/valuation/history")
def stock_valuation_history(
    symbol: str,
    limit: int = Query(260, ge=8, le=1000),
) -> dict:
    try:
        return database.valuation_history(symbol, limit)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/volume-profile")
def stock_volume_profile(
    symbol: str,
    lookback: int = Query(60, ge=10, le=250),
) -> dict:
    try:
        return database.volume_profile_view(symbol, lookback)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/capital-flow")
def stock_capital_flow(
    symbol: str,
    days: int = Query(5, ge=1, le=30),
) -> dict:
    try:
        return database.capital_flow_view(symbol, days)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/sentiment")
def stock_sentiment(symbol: str) -> dict:
    try:
        return database.sentiment_summary(symbol)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/options")
def stock_options(symbol: str) -> list[dict]:
    try:
        return database.option_wall(symbol)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/news")
def stock_news(symbol: str, limit: int = Query(30, ge=1, le=100)) -> list[dict]:
    try:
        return database.news([symbol], limit)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/stock/{symbol}/reviews")
def stock_reviews(symbol: str) -> list[dict]:
    try:
        return database.latest_reviews(symbol)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


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
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    except DatabaseError as exc:
        raise _http_error(exc) from exc


@app.get("/api/reviews")
def reviews(symbol: str | None = None) -> list[dict]:
    try:
        return database.latest_reviews(symbol)
    except (DatabaseError, ValueError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/briefing")
def briefing(date_: Annotated[str | None, Query(alias="date")] = None) -> dict:
    try:
        if date_:
            date.fromisoformat(date_)
        return database.briefing(date_)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    except DatabaseError as exc:
        raise _http_error(exc) from exc


@app.get("/api/jobs")
def job_runs(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    try:
        return database.job_runs(limit)
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    except DatabaseError as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------- macro maintenance

@app.get("/api/macro/events")
def macro_events(
    start: Annotated[str | None, Query(alias="from")] = None,
    end: Annotated[str | None, Query(alias="to")] = None,
) -> list[dict]:
    try:
        return database.macro_events_between(start or "1970-01-01", end or "2999-01-01")
    except DatabaseError as exc:
        raise _http_error(exc) from exc


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
    uvicorn.run("stock_pm.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
