"""Post-close publisher for TapeAnalysis + ReviewNote.

Writes one append-only tape row and one review note per active symbol.
Failures become visible missing rows and a job_runs record — never a
silent empty page or fabricated volume-price.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .tape import failed_review_note, failed_tape


def publish_tape_and_reviews(
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

    for symbol in symbols:
        try:
            tape = store.build_live_tape(symbol, date)
            if not tape or tape.get("publishState") is None:
                tape = failed_tape(symbol, date, "empty tape")
            tape = dict(tape)
            tape["source"] = "job"
            store.append_tape_analysis(tape)
            try:
                note = store.build_live_review_note(symbol, date, tape=tape)
                if not note or note.get("publishState") is None:
                    note = failed_review_note(symbol, date, "empty review note")
                note = dict(note)
                note["source"] = "job"
                store.append_review_note(note)
            except Exception as exc:
                errors.append({"scope": "review_note", "symbol": symbol, "error": str(exc)})
                try:
                    store.append_review_note(failed_review_note(symbol, date, str(exc)))
                except Exception as inner:
                    errors.append(
                        {
                            "scope": "review_note",
                            "symbol": symbol,
                            "error": f"append failed: {inner}",
                        }
                    )
            written.append(symbol)
        except Exception as exc:
            errors.append({"scope": "tape", "symbol": symbol, "error": str(exc)})
            try:
                store.append_tape_analysis(failed_tape(symbol, date, str(exc)))
                store.append_review_note(failed_review_note(symbol, date, str(exc)))
                written.append(f"{symbol}:missing")
            except Exception as inner:
                errors.append(
                    {
                        "scope": "tape",
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
            "job_name": "tape",
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

    parser = argparse.ArgumentParser(description="Append TapeAnalysis and ReviewNote after the close")
    parser.add_argument("--date", help="As-of date YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*", help="Optional watchlist symbols")
    args = parser.parse_args()
    database = Database()
    try:
        database.initialize()
        result = publish_tape_and_reviews(
            database, as_of_date=args.date, symbols=args.symbols
        )
    finally:
        database.close()
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
