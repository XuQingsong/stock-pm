from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from .database import Database
from .impact import news_sentiment, tag_news


NASDAQ_API = "https://api.nasdaq.com/api"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140 Safari/537.36"
    ),
}


def _get_json(path: str) -> dict:
    request = Request(f"{NASDAQ_API}/{path}", headers=HEADERS)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    assert last_error is not None
    raise last_error


def _number(value) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if value in (None, "", "N/A", "--"):
        return None
    cleaned = re.sub(r"[^0-9.+-]", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _fiscal_year(period: str | None) -> int | None:
    match = re.search(r"(20\d{2})", period or "")
    return int(match.group(1)) if match else None


def _last_trade(value: str | None) -> float | None:
    match = re.search(r"\$([0-9,.]+)", value or "")
    return float(match.group(1).replace(",", "")) if match else None


def _news(symbol: str) -> list[dict]:
    try:
        response = _get_json(
            f"news/topic/articlebysymbol?q={symbol}&offset=0&limit=20"
        )
    except Exception:
        return []
    articles = []
    for row in (response.get("data") or {}).get("rows") or []:
        try:
            published = datetime.strptime(row["created"], "%b %d, %Y").replace(
                tzinfo=timezone.utc
            )
        except (KeyError, ValueError):
            published = None
        text = f"{row.get('title', '')} {row.get('description', '')}"
        path = row.get("url") or ""
        articles.append(
            {
                "symbol": symbol,
                "headline": row.get("title") or "Untitled",
                "summary": row.get("description") or "",
                "source": row.get("publisher") or "Nasdaq news feed",
                "published_at": published.isoformat() if published else None,
                "url": path if path.startswith("http") else f"https://www.nasdaq.com{path}",
                "sentiment": news_sentiment(text),
                "themes": tag_news(text),
            }
        )
    return articles


def fetch_symbol(
    symbol: str,
    last_price: float | None,
    captured_at: str,
    asset_class: str = "stocks",
) -> dict:
    summary_response = _get_json(f"quote/{symbol}/summary?assetclass={asset_class}")
    eps_response = _get_json(f"quote/{symbol}/eps?assetclass={asset_class}")
    earnings_response = _get_json(
        f"company/{symbol}/earnings-surprise?assetclass={asset_class}"
    )
    summary = ((summary_response.get("data") or {}).get("summaryData") or {})
    eps_rows = ((eps_response.get("data") or {}).get("earningsPerShare") or [])
    previous = [row for row in eps_rows if row.get("type") == "PreviousQuarter"][-4:]
    upcoming = [row for row in eps_rows if row.get("type") == "UpcomingQuarter"][:4]
    eps_ttm = sum(float(row.get("earnings") or 0) for row in previous) or None
    eps_forward = sum(float(row.get("consensus") or 0) for row in upcoming) or None

    fundamental = {
        "symbol": symbol,
        "captured_at": captured_at,
        "currency": "USD",
        "market_cap": _number(summary.get("MarketCap")),
        "pe_ttm": last_price / eps_ttm if last_price and eps_ttm else None,
        "pe_forward": last_price / eps_forward if last_price and eps_forward else None,
        "eps_ttm": eps_ttm,
        "dividend_yield_pct": _number(summary.get("Yield")),
        "analyst_target_price": _number(summary.get("OneYrTarget")),
        "source": "Nasdaq summary + EPS consensus",
        "raw": {"summary": summary_response, "eps": eps_response},
    }

    table = ((earnings_response.get("data") or {}).get("earningsSurpriseTable") or {})
    earnings = []
    for row in table.get("rows") or []:
        report_date = datetime.strptime(row["dateReported"], "%m/%d/%Y").date()
        earnings.append(
            {
                "symbol": symbol,
                "report_date": report_date.isoformat(),
                "report_timing": "unknown",
                "fiscal_period": row.get("fiscalQtrEnd") or "Quarter",
                "fiscal_year": _fiscal_year(row.get("fiscalQtrEnd")),
                "currency": "USD",
                "eps_actual": _number(row.get("eps")),
                "eps_estimate": _number(row.get("consensusForecast")),
                "eps_surprise_pct": _number(row.get("percentageSurprise")),
                "source": "Nasdaq earnings surprise",
                "raw": row,
            }
        )
    return {
        "fundamental": fundamental,
        "earnings": earnings,
        "news": _news(symbol),
    }


def collect(symbols: list[str] | None = None) -> tuple[dict, dict[str, str]]:
    captured_at = datetime.now(timezone.utc).isoformat()
    database = Database()
    try:
        database.initialize()
        requested = database._watchlist_symbols(symbols)
        asset_classes = {
            row["symbol"]: row["asset_class"] for row in database.watchlist_rows()
        }
        prices = {
            row["symbol"]: float(row["last_price"])
            for row in database.latest_snapshots(requested)
            if row.get("last_price") is not None
        }
    finally:
        database.close()

    payload = {
        "source": "nasdaq_fundamentals",
        "captured_at": captured_at,
        "fundamentals": [],
        "earnings": [],
        "news": [],
    }
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                fetch_symbol,
                symbol,
                prices.get(symbol),
                captured_at,
                asset_classes.get(symbol, "stocks"),
            ): symbol
            for symbol in requested
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                result = future.result()
                payload["fundamentals"].append(result["fundamental"])
                payload["earnings"].extend(result["earnings"])
                payload["news"].extend(result["news"])
            except Exception as exc:
                errors[symbol] = str(exc)
    return payload, errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync valuation and earnings history from Nasdaq"
    )
    parser.add_argument("--symbols", nargs="*", help="Optional watchlist symbols")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    payload, errors = collect(args.symbols)
    if args.dry_run:
        print(json.dumps({"payload": payload, "errors": errors}, ensure_ascii=False))
        return

    database = Database()
    try:
        database.initialize()
        counts = database.ingest(payload)
    finally:
        database.close()
    print(json.dumps({"counts": counts, "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
