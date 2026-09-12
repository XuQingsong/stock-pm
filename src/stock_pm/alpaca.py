from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .bars import DAILY_ADJUSTMENT, decorate_bar, last_completed_session_end
from .config import Settings
from .database import Database
from .fetch import utc_now


DATA_API = "https://data.alpaca.markets"
TRADING_API = "https://paper-api.alpaca.markets"
OPTION_SYMBOL = re.compile(r"^([A-Z.]+)(\d{6})([CP])(\d{8})$")


class AlpacaError(RuntimeError):
    pass


class AlpacaClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        if not self.settings.alpaca_api_key_id or not self.settings.alpaca_api_secret_key:
            raise AlpacaError("ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are required")
        self.headers = {
            "Accept": "application/json",
            "APCA-API-KEY-ID": self.settings.alpaca_api_key_id,
            "APCA-API-SECRET-KEY": self.settings.alpaca_api_secret_key,
            "User-Agent": "stock-pm/0.5",
        }

    def get(self, base: str, path: str, params: dict | None = None) -> dict:
        url = f"{base}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers=self.headers)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=45) as response:
                    return json.load(response)
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1 + attempt)
        raise AlpacaError(f"Alpaca request failed for {path}: {last_error}")


def _num(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_option_symbol(symbol: str) -> tuple[str, date, str, float]:
    normalized = symbol.removeprefix("O:")
    match = OPTION_SYMBOL.fullmatch(normalized)
    if not match:
        raise ValueError(f"Unsupported OCC option symbol: {symbol}")
    underlying, expiry, side, strike = match.groups()
    return underlying, datetime.strptime(expiry, "%y%m%d").date(), side, int(strike) / 1000


def _bars(client: AlpacaClient, symbols: list[str], timeframe: str, start: datetime, end: datetime) -> dict[str, list[dict]]:
    collected = {symbol: [] for symbol in symbols}
    token = None
    while True:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "feed": client.settings.alpaca_bars_feed,
            "adjustment": DAILY_ADJUSTMENT if timeframe == "1Day" else "raw",
            "limit": 10000,
            "sort": "asc",
        }
        if token:
            params["page_token"] = token
        response = client.get(DATA_API, "/v2/stocks/bars", params)
        for symbol, rows in (response.get("bars") or {}).items():
            collected.setdefault(symbol, []).extend(
                {
                    "bar_time": row.get("t"),
                    "open_price": _num(row.get("o")),
                    "high_price": _num(row.get("h")),
                    "low_price": _num(row.get("l")),
                    "close_price": _num(row.get("c")),
                    "volume": _num(row.get("v")),
                    "trade_count": row.get("n"),
                    "vwap": _num(row.get("vw")),
                }
                for row in rows
            )
        token = response.get("next_page_token")
        if not token:
            return collected


def _trades(client: AlpacaClient, symbol: str, start: datetime, end: datetime) -> list[dict]:
    """Tick-level trades in a window (free tier: only data older than ~15 min)."""
    collected: list[dict] = []
    token = None
    while True:
        params = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 10000,
            "feed": "sip",
            "sort": "asc",
        }
        if token:
            params["page_token"] = token
        response = client.get(DATA_API, f"/v2/stocks/{symbol}/trades", params)
        for row in response.get("trades") or []:
            price, size = _num(row.get("p")), _num(row.get("s"))
            if price is None or size is None:
                continue
            collected.append(
                {
                    "trade_time": datetime.fromisoformat(row["t"].replace("Z", "+00:00")),
                    "price": price,
                    "size": size,
                    "notional": price * size,
                    "exchange": row.get("x"),
                    "trade_id": str(row.get("i", "")),
                }
            )
        token = response.get("next_page_token")
        if not token:
            return collected


def _snapshots(client: AlpacaClient, symbols: list[str]) -> list[dict]:
    response = client.get(
        DATA_API,
        "/v2/stocks/snapshots",
        {"symbols": ",".join(symbols), "feed": client.settings.alpaca_data_feed},
    )
    result = []
    for symbol in symbols:
        item = response.get(symbol) or {}
        trade, quote = item.get("latestTrade") or {}, item.get("latestQuote") or {}
        day, prior = item.get("dailyBar") or {}, item.get("prevDailyBar") or {}
        minute = item.get("minuteBar") or {}
        result.append(
            {
                "symbol": symbol,
                "contract_id": 0,
                "last_price": _num(trade.get("p")) or _num(minute.get("c")) or _num(day.get("c")),
                "bid": _num(quote.get("bp")),
                "ask": _num(quote.get("ap")),
                "open_price": _num(day.get("o")),
                "high_price": _num(day.get("h")),
                "low_price": _num(day.get("l")),
                "prior_close": _num(prior.get("c")),
                "volume": _num(day.get("v")),
                "halted": None,
                "source": f"alpaca_{client.settings.alpaca_data_feed}",
                "delayed": "1",
                "provider_payload": item,
            }
        )
    return [row for row in result if row["last_price"] is not None]


def _contract_open_interest(client: AlpacaClient, symbol: str, start: date, end: date) -> dict[str, float]:
    result: dict[str, float] = {}
    token = None
    while True:
        params = {
            "underlying_symbols": symbol,
            "expiration_date_gte": start.isoformat(),
            "expiration_date_lte": end.isoformat(),
            "status": "active",
            "limit": 1000,
        }
        if token:
            params["page_token"] = token
        response = client.get(TRADING_API, "/v2/options/contracts", params)
        for item in response.get("option_contracts") or []:
            value = _num(item.get("open_interest"))
            if value is not None:
                result[item["symbol"]] = value
        token = response.get("next_page_token")
        if not token:
            return result


def _option_wall(client: AlpacaClient, symbol: str, spot: float | None) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=45)
    params = {
        "feed": client.settings.alpaca_options_feed,
        "expiration_date_gte": today.isoformat(),
        "expiration_date_lte": end.isoformat(),
        "limit": 1000,
    }
    response = client.get(DATA_API, f"/v1beta1/options/snapshots/{symbol}", params)
    snapshots = response.get("snapshots") or {}
    parsed = []
    for contract_symbol, snap in snapshots.items():
        try:
            underlying, expiry, side, strike = parse_option_symbol(contract_symbol)
        except ValueError:
            continue
        if underlying == symbol:
            parsed.append((expiry, strike, side, contract_symbol, snap))
    if not parsed:
        return []
    nearest = min(item[0] for item in parsed)
    expiry_rows = [item for item in parsed if item[0] == nearest]
    strikes = sorted({item[1] for item in expiry_rows}, key=lambda value: abs(value - (spot or value)))[:18]
    selected = set(strikes)
    try:
        open_interest = _contract_open_interest(client, symbol, nearest, nearest)
    except Exception:
        # Market snapshots are still useful when the paper account has not been
        # approved for option trading and therefore cannot list contracts.
        open_interest = {}
    rows: dict[float, dict] = {}
    for expiry, strike, side, contract_symbol, snap in expiry_rows:
        if strike not in selected:
            continue
        row = rows.setdefault(
            strike,
            {
                "symbol": symbol,
                "expiration_date": expiry.isoformat(),
                "strike": strike,
                "spot_price": spot,
                "call_last": None, "call_bid": None, "call_ask": None,
                "call_volume": None, "call_open_interest": None, "call_implied_volatility": None,
                "put_last": None, "put_bid": None, "put_ask": None,
                "put_volume": None, "put_open_interest": None, "put_implied_volatility": None,
                "source": f"alpaca_{client.settings.alpaca_options_feed}",
            },
        )
        prefix = "call" if side == "C" else "put"
        trade, quote, daily = snap.get("latestTrade") or {}, snap.get("latestQuote") or {}, snap.get("dailyBar") or {}
        row[f"{prefix}_last"] = _num(trade.get("p")) or _num(daily.get("c"))
        row[f"{prefix}_bid"] = _num(quote.get("bp"))
        row[f"{prefix}_ask"] = _num(quote.get("ap"))
        row[f"{prefix}_volume"] = _num(daily.get("v"))
        row[f"{prefix}_open_interest"] = open_interest.get(contract_symbol)
        row[f"{prefix}_implied_volatility"] = _num(snap.get("impliedVolatility") or snap.get("implied_volatility"))
    return [rows[strike] for strike in sorted(rows)]


def market_is_collectible(now: datetime | None = None) -> bool:
    eastern = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    return eastern.weekday() < 5 and clock_time(9, 45) <= eastern.time().replace(tzinfo=None) <= clock_time(16, 30)


def collect(mode: str = "intraday", symbols: list[str] | None = None) -> tuple[dict, dict[str, str]]:
    if symbols:
        requested = [symbol.upper() for symbol in symbols]
    else:
        database = Database()
        try:
            database.initialize()
            requested = database.active_symbols()
        finally:
            database.close()
    client = AlpacaClient()
    now = datetime.now(timezone.utc)
    delayed_end = now - timedelta(minutes=16)
    snapshots = _snapshots(client, requested)
    prices = {row["symbol"]: row["last_price"] for row in snapshots}
    daily_end = last_completed_session_end(now)
    end = delayed_end if mode == "intraday" else daily_end
    start = end - (timedelta(days=3) if mode == "intraday" else timedelta(days=430))
    timeframe, bar_size = ("1Min", "1m") if mode == "intraday" else ("1Day", "1d")
    fetched_at = utc_now()
    bars = _bars(client, requested, timeframe, start, end)
    errors: dict[str, str] = {}
    options = []
    for symbol in requested:
        try:
            options.extend(_option_wall(client, symbol, prices.get(symbol)))
        except Exception as exc:
            errors[f"options:{symbol}"] = str(exc)
    payload = {
        "source": "alpaca",
        "captured_at": now.isoformat(),
        "snapshots": snapshots,
        "history": [
            {
                "symbol": symbol,
                "bar_size": bar_size,
                "source": f"alpaca_{client.settings.alpaca_bars_feed}",
                "adjustment": DAILY_ADJUSTMENT if bar_size == "1d" else "raw",
                "bars": [
                    decorate_bar(
                        row,
                        fetched_at=fetched_at,
                        adjustment=DAILY_ADJUSTMENT if bar_size == "1d" else "raw",
                        source=f"alpaca_{client.settings.alpaca_bars_feed}",
                    )
                    for row in rows
                ],
            }
            for symbol, rows in bars.items() if rows
        ],
        "options": options,
    }
    return payload, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect delayed stock and option data from Alpaca")
    parser.add_argument("--mode", choices=("intraday", "daily"), default="intraday")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Run intraday mode outside US market hours")
    args = parser.parse_args()
    if args.mode == "intraday" and not args.force and not market_is_collectible():
        print(json.dumps({"status": "skipped", "reason": "US market is closed"}))
        return
    payload, errors = collect(args.mode, args.symbols)
    if args.dry_run:
        print(json.dumps({"counts": {"snapshots": len(payload["snapshots"]), "bars": sum(len(x["bars"]) for x in payload["history"]), "options": len(payload["options"])}, "errors": errors}, ensure_ascii=False))
        return
    database = Database()
    try:
        database.initialize()
        counts = database.ingest(payload)
    finally:
        database.close()
    print(json.dumps({"status": "ok", "counts": counts, "errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
