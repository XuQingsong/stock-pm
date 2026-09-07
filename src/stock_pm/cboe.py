from __future__ import annotations

"""Cboe daily options market statistics (one exchange, not OCC industry-wide)."""

import argparse
import json
import re
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .database import Database

CBOE_DAILY_URL = "https://www.cboe.com/us/options/market_statistics/daily/?mkt=cone"
SOURCE = "cboe"
DISCLAIMER = (
    "来源 Cboe 每日统计，仅该交易所，不是 OCC 全市场总量。"
    "P/C 为认沽÷认购（Cboe 口径）；C/P 为认购÷认沽（与 OptionsDaily 图相同）。"
)

RATIO_KEYS = {
    "TOTAL PUT/CALL RATIO": "total",
    "INDEX PUT/CALL RATIO": "index",
    "EXCHANGE TRADED PRODUCTS PUT/CALL RATIO": "etp",
    "EQUITY PUT/CALL RATIO": "equity",
    "CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO": "vix",
    "SPX + SPXW PUT/CALL RATIO": "spx",
}
VOLUME_KEYS = {
    "SUM OF ALL PRODUCTS": "total",
    "INDEX OPTIONS": "index",
    "EXCHANGE TRADED PRODUCTS": "etp",
    "EQUITY OPTIONS": "equity",
}
BUCKET_LABELS = {
    "index": "指数期权",
    "equity": "个股期权",
    "etp": "ETF期权",
}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _call_put(put_call: float | None) -> float | None:
    if put_call is None or put_call == 0:
        return None
    return round(1.0 / put_call, 3)


def _pct(part: float | None, whole: float | None) -> float | None:
    if part is None or not whole:
        return None
    return round(100.0 * part / whole, 1)


def _volume_row(section: Any) -> dict[str, int]:
    for row in section or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "").upper() == "VOLUME":
            return {
                "call": int(_num(row.get("call")) or 0),
                "put": int(_num(row.get("put")) or 0),
                "total": int(_num(row.get("total")) or 0),
            }
    return {"call": 0, "put": 0, "total": 0}


def _extract_json_object(html: str, marker: str) -> dict:
    start = html.find(marker)
    if start < 0:
        raise ValueError(f"Cboe page missing {marker}")
    brace = html.find("{", start)
    if brace < 0:
        raise ValueError(f"Cboe page missing JSON object for {marker}")
    depth = 0
    for index, char in enumerate(html[brace:], brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                raw = html[brace : index + 1]
                cleaned = raw.replace('\\"', '"')
                payload = json.loads(cleaned)
                if isinstance(payload, dict):
                    return payload
                raise ValueError(f"Cboe {marker} is not an object")
    raise ValueError(f"Cboe {marker} JSON was truncated")


def extract_selected_date(html: str) -> str:
    match = re.search(
        r'selectedDate\\?"?\s*:\s*\\?"(\d{4}-\d{2}-\d{2})\\?"',
        html,
    )
    if match:
        return match.group(1)
    raise ValueError("Cboe page missing selectedDate")


def extract_options_data(html: str) -> dict:
    return _extract_json_object(html, "optionsData")


def snapshot_from_options_data(data: dict, trade_date: str) -> dict[str, Any]:
    ratios: dict[str, float | None] = {}
    for row in data.get("ratios") or []:
        if not isinstance(row, dict):
            continue
        key = RATIO_KEYS.get(str(row.get("name") or "").upper())
        if key:
            ratios[key] = _num(row.get("value"))

    volumes: dict[str, dict[str, int]] = {}
    for section, key in VOLUME_KEYS.items():
        volumes[key] = _volume_row(data.get(section))

    total_volume = volumes.get("total", {}).get("total") or 0
    buckets = []
    for key in ("index", "equity", "etp"):
        vol = volumes.get(key) or {"call": 0, "put": 0, "total": 0}
        put_call = ratios.get(key)
        if put_call is None and vol["call"]:
            put_call = round(vol["put"] / vol["call"], 3)
        buckets.append(
            {
                "key": key,
                "label": BUCKET_LABELS[key],
                "call_volume": vol["call"],
                "put_volume": vol["put"],
                "volume": vol["total"],
                "volume_pct": _pct(vol["total"], total_volume),
                "put_call": put_call,
                "call_put": _call_put(put_call),
            }
        )

    total_put_call = ratios.get("total")
    if total_put_call is None and volumes["total"]["call"]:
        total_put_call = round(volumes["total"]["put"] / volumes["total"]["call"], 3)

    return {
        "trade_date": trade_date,
        "source": SOURCE,
        "disclaimer": DISCLAIMER,
        "total_volume": total_volume,
        "total_call_volume": volumes["total"]["call"],
        "total_put_volume": volumes["total"]["put"],
        "total_put_call": total_put_call,
        "total_call_put": _call_put(total_put_call),
        "buckets": buckets,
        "vix_put_call": ratios.get("vix"),
        "spx_put_call": ratios.get("spx"),
        "raw": data,
    }


def parse_cboe_html(html: str) -> dict[str, Any]:
    return snapshot_from_options_data(extract_options_data(html), extract_selected_date(html))


def fetch_cboe_html(trade_date: str | None = None) -> str:
    url = CBOE_DAILY_URL
    if trade_date:
        date.fromisoformat(trade_date)
        url = f"{CBOE_DAILY_URL}&dt={trade_date}"
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; stock-pm/0.6; +https://www.cboe.com/)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(request, timeout=45) as response:
            return response.read().decode("utf-8", "replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Failed to fetch Cboe daily statistics: {exc}") from exc


def collect(trade_date: str | None = None) -> dict[str, Any]:
    return parse_cboe_html(fetch_cboe_html(trade_date))


def sync(trade_date: str | None = None) -> dict[str, Any]:
    snapshot = collect(trade_date)
    database = Database()
    try:
        database.initialize()
        database.store_cboe_option_stats(snapshot)
    finally:
        database.close()
    return {
        "trade_date": snapshot["trade_date"],
        "total_volume": snapshot["total_volume"],
        "total_put_call": snapshot["total_put_call"],
        "total_call_put": snapshot["total_call_put"],
        "source": SOURCE,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Cboe daily options market statistics")
    parser.add_argument("--date", help="Optional YYYY-MM-DD (Cboe selectedDate)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        snapshot = collect(args.date)
        snapshot.pop("raw", None)
        print(json.dumps(snapshot, ensure_ascii=False))
        return
    print(json.dumps(sync(args.date), ensure_ascii=False))


if __name__ == "__main__":
    main()
