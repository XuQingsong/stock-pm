"""Post-close publisher: generate Predictions and run PredictionChecks.

Open predictions are checked first. A new Prediction is appended only when
there is no open one. Quality-gate failures become visible missing rows —
never a silent empty badge or fabricated 10%/-5%. Human supersede is not
called here (稀少改口).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .prediction import (
    OPEN_STATES,
    failed_prediction,
    run_prediction_check,
)


def _bar_ohlc(store: Any, symbol: str, as_of_date: str | None) -> dict:
    close = high = low = None
    try:
        reviews = store.reviews_by_date(as_of_date) if as_of_date else []
        match = next(
            (row for row in reviews if str(row.get("symbol") or "").upper() == symbol),
            None,
        )
        if match:
            close = match.get("close_price")
    except Exception:
        match = None
    try:
        bars = store.history(symbol, 5, "1d")
    except Exception:
        bars = []
    day = None
    if as_of_date:
        day = next(
            (
                row
                for row in reversed(bars)
                if str(row.get("bar_time") or "")[:10] == str(as_of_date)[:10]
            ),
            None,
        )
    if day is None and bars:
        day = bars[-1]
    if day:
        close = close if close is not None else day.get("close_price")
        high = day.get("high_price")
        low = day.get("low_price")
    return {"close": close, "high": high, "low": low}


def _prior_extrema(store: Any, prediction_id: int | None) -> tuple[float | None, float | None]:
    if not prediction_id or not hasattr(store, "prediction_checks"):
        return None, None
    try:
        rows = store.prediction_checks(prediction_id)
    except Exception:
        return None, None
    gains = [row.get("max_gain_pct") for row in rows if row.get("max_gain_pct") is not None]
    dds = [row.get("max_drawdown_pct") for row in rows if row.get("max_drawdown_pct") is not None]
    return (max(gains) if gains else None, min(dds) if dds else None)


def publish_predictions_and_checks(
    store: Any,
    as_of_date: str | None = None,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    session = store.market_session(as_of_date)
    date = as_of_date or session.get("default_review_date") or session.get("date")
    symbols = list(symbols or store.active_symbols())
    written: list[str] = []
    checked: list[str] = []
    errors: list[dict[str, str]] = []
    alerts: list[dict] = []

    for symbol in symbols:
        try:
            latest = None
            if hasattr(store, "latest_prediction"):
                latest = store.latest_prediction(date, symbol, open_only=False)
            open_pred = latest if latest and latest.get("state") in OPEN_STATES else None
            if open_pred:
                ohlc = _bar_ohlc(store, symbol, date)
                prior_gain, prior_dd = _prior_extrema(store, open_pred.get("id"))
                check = run_prediction_check(
                    open_pred,
                    as_of_date=date,
                    close=ohlc["close"],
                    high=ohlc["high"],
                    low=ohlc["low"],
                    prior_max_gain_pct=prior_gain,
                    prior_max_drawdown_pct=prior_dd,
                )
                store.append_prediction_check(check)
                updated = check.get("prediction") or open_pred
                if updated.get("state") != open_pred.get("state") or updated.get("id"):
                    store.update_prediction_state(updated)
                if check.get("alert"):
                    alerts.append(check["alert"])
                    store.append_severity_alerts([check["alert"]])
                checked.append(symbol)
                written.append(f"{symbol}:{check.get('next_state') or updated.get('state')}")
                continue

            pred = store.build_live_prediction(symbol, date)
            if not pred or pred.get("state") is None:
                pred = failed_prediction(symbol, date, "empty prediction")
            pred = dict(pred)
            pred["source"] = "job"
            store.append_prediction(pred)
            written.append(f"{symbol}:{pred.get('state')}")
        except Exception as exc:
            errors.append({"scope": "prediction", "symbol": symbol, "error": str(exc)})
            try:
                store.append_prediction(failed_prediction(symbol, date, str(exc)))
                written.append(f"{symbol}:missing")
            except Exception as inner:
                errors.append(
                    {
                        "scope": "prediction",
                        "symbol": symbol,
                        "error": f"append failed: {inner}",
                    }
                )

    if not errors:
        status = "success"
    elif written:
        status = "partial"
    else:
        status = "failed"
    error_text = None
    if errors:
        error_text = "; ".join(
            f"{item.get('symbol') or item.get('scope')}: {item.get('error')}"
            for item in errors
        )
    store.append_job_run(
        {
            "job_name": "prediction",
            "started_at": started,
            "completed_at": datetime.now(timezone.utc),
            "status": status,
            "item_counts": {
                "written": len(written),
                "checked": len(checked),
                "failed": len(errors),
                "symbols": len(symbols),
                "alerts": len(alerts),
            },
            "error": error_text,
        }
    )
    return {
        "date": date,
        "status": status,
        "written": written,
        "checked": checked,
        "errors": errors,
        "alerts": alerts,
        "publishState": "missing" if status == "failed" else status,
    }


def main() -> None:
    import argparse
    import json

    from .database import Database

    parser = argparse.ArgumentParser(description="Append Predictions and PredictionChecks after the close")
    parser.add_argument("--date", help="As-of date YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*", help="Optional watchlist symbols")
    args = parser.parse_args()
    database = Database()
    try:
        database.initialize()
        result = publish_predictions_and_checks(
            database, as_of_date=args.date, symbols=args.symbols
        )
    finally:
        database.close()
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
