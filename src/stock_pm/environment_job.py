"""Post-close (or stub) publisher for EnvironmentSnapshot rows.

Writes one market snapshot plus one snapshot per active watchlist symbol.
Failures become visible missing rows and a job_runs record — never a silent
empty page or fabricated numbers. History is append-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .environment import failed_snapshot, synthesize_symbol_environment
from .philosophy import synthesize_environment


def publish_environment_snapshots(
    store: Any,
    as_of_date: str | None = None,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    session = store.market_session(as_of_date)
    date = as_of_date or session.get("default_review_date") or session.get("date")
    symbols = list(symbols or store.active_symbols())
    written: list[str] = []
    errors: list[dict[str, str]] = []

    try:
        briefing = store.briefing(date)
        market_env = briefing.get("environment")
        if not market_env:
            options = None
            try:
                stats = store.cboe_option_stats(date)
                options = {"status": "ok", **stats} if stats else {"status": "missing"}
            except Exception:
                options = {"status": "missing"}
            try:
                impact = store.market_impact()
            except Exception:
                impact = {"macro": []}
            market_env = synthesize_environment(
                as_of_date=date,
                briefing_rows=briefing.get("rows") or [],
                options=options,
                impact=impact,
                session=briefing.get("session") or session,
            )
        store.append_environment_snapshot(market_env)
        written.append("market")
    except Exception as exc:
        errors.append({"scope": "market", "error": str(exc)})
        try:
            store.append_environment_snapshot(
                failed_snapshot(None, date, str(exc), scope="market")
            )
        except Exception as inner:
            errors.append({"scope": "market", "error": f"append failed: {inner}"})

    for symbol in symbols:
        try:
            snapshot = store.build_live_environment(symbol, date)
            if not snapshot or snapshot.get("publishState") is None:
                snapshot = synthesize_symbol_environment(
                    as_of_date=date, symbol=symbol, session=session, source="job"
                )
            snapshot = dict(snapshot)
            snapshot["source"] = "job"
            store.append_environment_snapshot(snapshot)
            written.append(symbol)
        except Exception as exc:
            errors.append({"scope": "symbol", "symbol": symbol, "error": str(exc)})
            try:
                store.append_environment_snapshot(failed_snapshot(symbol, date, str(exc)))
                written.append(f"{symbol}:missing")
            except Exception as inner:
                errors.append(
                    {
                        "scope": "symbol",
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
            "job_name": "environment",
            "started_at": started,
            "completed_at": datetime.now(timezone.utc),
            "status": status,
            "item_counts": {
                "written": len(written),
                "failed": len(errors),
                "symbols": len(symbols),
            },
            "error": error_text,
        }
    )
    return {
        "date": date,
        "status": status,
        "written": written,
        "errors": errors,
        "publishState": "missing" if status == "failed" else status,
    }


def main() -> None:
    import argparse
    import json

    from .database import Database

    parser = argparse.ArgumentParser(description="Append EnvironmentSnapshot rows after the close")
    parser.add_argument("--date", help="As-of date YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*", help="Optional watchlist symbols")
    args = parser.parse_args()
    database = Database()
    try:
        database.initialize()
        result = publish_environment_snapshots(
            database, as_of_date=args.date, symbols=args.symbols
        )
    finally:
        database.close()
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
