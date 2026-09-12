from __future__ import annotations

"""Macro event calendar (手工维护) + FRED actual-value sync.

The calendar file `data/macro_calendar.json` is the manually maintained
schedule (event time, consensus, prior). `--sync` upserts it into the
`macro_events` table and fills official FRED actuals (API key optional;
keyless fredgraph.csv is first-party). FOMC decisions (cut/hold/hike) have
no numeric actual and are maintained manually or via POST /api/macro/events.
"""

import argparse
import json
from datetime import datetime, timezone
from importlib.resources import files

from .config import Settings
from .database import Database
from .series import fetch_fred_series, parse_fred_observations

# event_type -> (FRED series, transform)
FRED_SERIES = {
    "nfp": ("PAYEMS", "diff"),        # 非农新增就业 = 月度总就业环比差值（千人）
    "cpi": ("CPIAUCSL", "yoy_pct"),   # CPI 同比 %
    "pce": ("PCEPILFE", "yoy_pct"),   # 核心 PCE 同比 %
}


def _fred_observations(series: str, api_key: str = "", limit: int = 14) -> list[tuple[str, float]]:
    result = fetch_fred_series(series, api_key, limit=limit)
    observations = []
    for row in parse_fred_observations(result.payload):
        try:
            observations.append((row["period"], float(row["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return observations


def fred_actual(event_type: str, api_key: str = "") -> float | None:
    """Fill calendar actuals from official FRED. API key optional (keyless CSV)."""
    entry = FRED_SERIES.get(event_type)
    if not entry:
        return None
    series, transform = entry
    observations = _fred_observations(series, api_key)
    if transform == "diff":
        if len(observations) < 2:
            return None
        return round(observations[0][1] - observations[1][1], 1)
    if transform == "yoy_pct":
        if len(observations) < 13:
            return None
        latest, year_ago = observations[0][1], observations[12][1]
        return round(100 * (latest / year_ago - 1), 2) if year_ago else None
    return None


def _surprise(actual: float | None, consensus: float | None) -> str:
    if actual is None or consensus is None:
        return "unknown"
    if actual > consensus:
        return "above"
    if actual < consensus:
        return "below"
    return "inline"


def sync(fill_actuals: bool = True) -> dict:
    calendar_path = files("stock_pm").joinpath("data/macro_calendar.json")
    events = json.loads(calendar_path.read_text(encoding="utf-8"))
    settings = Settings()
    database = Database(settings)
    counts = {"upserted": 0, "actuals_filled": 0}
    try:
        database.initialize()
        for event in events:
            actual = event.get("actual")
            event_time = datetime.fromisoformat(event["event_time"].replace("Z", "+00:00"))
            if (
                fill_actuals
                and actual is None
                and event["event_type"] in FRED_SERIES
                and event_time <= datetime.now(timezone.utc)
            ):
                try:
                    actual = fred_actual(event["event_type"], settings.fred_api_key or "")
                    if actual is not None:
                        counts["actuals_filled"] += 1
                except Exception:
                    actual = None
            surprise = event.get("surprise") or _surprise(actual, event.get("consensus"))
            database.store_macro_event(
                {
                    "event_type": event["event_type"],
                    "event_time": event["event_time"],
                    "name": event["name"],
                    "actual": actual,
                    "consensus": event.get("consensus"),
                    "prior": event.get("prior"),
                    "unit": event.get("unit"),
                    "surprise": surprise,
                    "confirmed": event.get("confirmed", True),
                    "source": "calendar+FRED" if actual is not None else "calendar",
                    "notes": event.get("notes"),
                }
            )
            counts["upserted"] += 1
        from .series import sync_fred_market_series

        series_report = sync_fred_market_series(
            settings,
            store=database.store_macro_event,
        )
        counts["series"] = series_report.get("series")
    finally:
        database.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the macro event calendar")
    parser.add_argument("--no-actuals", action="store_true", help="Skip FRED actual-value lookup")
    args = parser.parse_args()
    print(json.dumps(sync(fill_actuals=not args.no_actuals), ensure_ascii=False))


if __name__ == "__main__":
    main()
