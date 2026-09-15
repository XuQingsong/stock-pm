"""Live research fetchers. Reuse FMP, Alpha Vantage, SEC, Nasdaq, and Alpaca.

Ticker is a query parameter. No issuer-specific branches or fixture imports.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from stock_pm.config import Settings
from stock_pm.fetch import FetchError, json_get, utc_now
from stock_pm.providers import FMPProvider, NasdaqProvider, _number


FMP_V3 = "https://financialmodelingprep.com/api/v3"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
BODY_LIMIT = 220_000
EXCERPT_LIMIT = 8


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_quarter_parts(quarter: str) -> tuple[int, int] | None:
    match = re.match(r"(20\d{2})\s*Q\s*([1-4])", str(quarter or ""), re.I)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def calendar_quarters(count: int = 6, *, today: date | None = None) -> list[str]:
    current = today or date.today()
    year, qn = current.year, (current.month - 1) // 3 + 1
    out: list[str] = []
    for _ in range(max(1, count)):
        out.append(f"{year}Q{qn}")
        qn -= 1
        if qn < 1:
            qn = 4
            year -= 1
    return out


def _join_turns(rows: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for row in rows:
        speaker = str(row.get("speaker") or row.get("title") or "").strip()
        content = str(row.get("content") or row.get("text") or "").strip()
        if not content:
            continue
        chunks.append(f"{speaker}: {content}" if speaker else content)
    return "\n".join(chunks)


def _trim(text: str, limit: int = BODY_LIMIT) -> str:
    return str(text or "")[:limit]


class LiveResearchFetchers:
    """HTTP adapters around existing providers. Safe to replace in tests."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def _fmp(self) -> FMPProvider | None:
        key = (self.settings.fmp_api_key or "").strip()
        if not key:
            return None
        return FMPProvider(key)

    def _fmp_try(self, path: str, params: dict[str, Any]) -> Any:
        provider = self._fmp()
        if provider is None:
            return None
        try:
            return provider._try_get(path, params)
        except Exception:
            return None

    def _fmp_v3(self, path: str, params: dict[str, Any]) -> Any:
        key = (self.settings.fmp_api_key or "").strip()
        if not key:
            return None
        query = urlencode({**params, "apikey": key})
        url = f"{FMP_V3}/{path}?{query}"
        try:
            with urlopen(url, timeout=30) as response:
                return json.load(response)
        except Exception:
            return None

    def sec_user_agent(self) -> str:
        from stock_pm.events.av_earnings import configured_sec_user_agent

        return configured_sec_user_agent(self.settings)

    def issuer_profile(self, symbol: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"source": None, "profile": {}}
        provider = self._fmp()
        if provider is None:
            return payload
        row = provider._try_get("profile", {"symbol": symbol})
        if isinstance(row, list):
            row = row[0] if row and isinstance(row[0], dict) else {}
        if not isinstance(row, dict):
            row = {}
        payload["source"] = "fmp.profile" if row else None
        payload["profile"] = row
        return payload

    def sec_identity(self, symbol: str) -> dict[str, Any]:
        ua = self.sec_user_agent()
        if not ua:
            return {"source": None, "error": "sec_user_agent_not_configured"}
        ticker = symbol.upper()
        try:
            result = json_get(
                SEC_TICKERS,
                headers={"User-Agent": ua, "Accept": "application/json"},
                timeout=40,
                retries=2,
                cache_key="sec-company-tickers",
            )
        except FetchError as exc:
            return {"source": None, "error": str(exc.reason_code)}
        cik = ""
        title = ""
        rows = result.payload if isinstance(result.payload, dict) else {}
        for item in rows.values():
            if not isinstance(item, dict):
                continue
            if str(item.get("ticker") or "").upper() != ticker:
                continue
            cik = str(item.get("cik_str") or "").strip()
            title = str(item.get("title") or "").strip()
            break
        if cik and not cik.startswith("0"):
            cik = cik.zfill(10)
        out: dict[str, Any] = {
            "source": "sec.company_tickers",
            "cik": cik or None,
            "legal_name": title or None,
        }
        if not cik:
            return out
        try:
            sub = json_get(
                SEC_SUBMISSIONS.format(cik=cik),
                headers={"User-Agent": ua, "Accept": "application/json"},
                timeout=40,
                retries=2,
                cache_key=f"sec-submissions-{cik}",
            )
        except FetchError:
            return out
        payload = sub.payload if isinstance(sub.payload, dict) else {}
        fye = str(payload.get("fiscalYearEnd") or "").strip()
        if len(fye) == 4 and fye.isdigit():
            month = int(fye[:2])
            if 1 <= month <= 12:
                out["fiscal_year_end_month"] = month
        if payload.get("name") and not out.get("legal_name"):
            out["legal_name"] = payload.get("name")
        sic = str(payload.get("sicDescription") or "").strip()
        if sic:
            out["sic_description"] = sic
        out["submissions"] = payload
        return out

    def sec_company_facts(self, cik: str | None) -> dict[str, Any]:
        ua = self.sec_user_agent()
        if not ua or not cik:
            return {"quarters": [], "error": "sec_user_agent_not_configured" if not ua else "missing_cik"}
        padded = str(cik).zfill(10)
        try:
            result = json_get(
                SEC_FACTS.format(cik=padded),
                headers={"User-Agent": ua, "Accept": "application/json"},
                timeout=60,
                retries=2,
                cache_key=f"sec-facts-{padded}",
            )
        except FetchError as exc:
            return {"quarters": [], "error": exc.reason_code}
        payload = result.payload if isinstance(result.payload, dict) else {}
        return {"quarters": _quarters_from_companyfacts(payload), "error": None, "source": "sec.companyfacts"}

    def earnings_bundle(self, symbol: str) -> dict[str, Any]:
        captured = _now()
        provider = self._fmp()
        if provider is not None:
            try:
                fetched = provider.fetch(symbol, None, captured, "stocks")
            except Exception as exc:
                fetched = {"error": str(exc)}
            else:
                cash = self._fmp_try("cash-flow-statement", {"symbol": symbol, "period": "quarter"}) or []
                segments = self._fmp_try("revenue-product-segmentation", {"symbol": symbol}) 
                income = self._fmp_try("income-statement", {"symbol": symbol, "period": "quarter"}) or []
                return {
                    "source": "fmp",
                    "earnings": list(fetched.get("earnings") or []),
                    "fundamentals": fetched.get("fundamental"),
                    "news": list(fetched.get("news") or []),
                    "income": income if isinstance(income, list) else [],
                    "cashflow": cash if isinstance(cash, list) else [],
                    "segments": segments,
                    "error": None,
                }
        try:
            nasdaq = NasdaqProvider().fetch(symbol, None, captured, "stocks")
            earnings = list(nasdaq.get("earnings") or [])
            fundamentals = nasdaq.get("fundamental")
            news = list(nasdaq.get("news") or [])
            source = "nasdaq"
            error = None
        except Exception as exc:
            earnings, fundamentals, news, source, error = [], None, [], None, str(exc)[:300]
        from stock_pm.research.issuer import cik_for

        facts = self.sec_company_facts(cik_for(symbol) or None)
        if facts.get("quarters"):
            earnings = merge_facts_into_earnings(symbol, earnings, facts["quarters"])
            fundamentals = enrich_fundamentals_from_facts(fundamentals, facts)
            source = f"{source}+sec.companyfacts" if source else "sec.companyfacts"
            error = None if earnings else error
        return {
            "source": source,
            "earnings": earnings,
            "fundamentals": fundamentals,
            "news": news,
            "income": [],
            "cashflow": [],
            "segments": None,
            "error": error,
        }

    def press_releases(self, symbol: str) -> list[dict[str, Any]]:
        rows = self._fmp_try("press-releases", {"symbol": symbol}) 
        if rows is None:
            rows = self._fmp_v3(f"press-releases/{symbol}", {})
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("historical") or []
        if not isinstance(rows, list):
            return []
        out: list[dict[str, Any]] = []
        for row in rows[:20]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("headline") or "").strip()
            url = str(row.get("url") or row.get("link") or "").strip()
            if not title and not url:
                continue
            out.append(
                {
                    "title": title or "Press release",
                    "url": url or None,
                    "published_at": row.get("date") or row.get("publishedDate") or row.get("datetime"),
                    "text": str(row.get("text") or row.get("content") or "")[:8000],
                    "source_provider": "fmp",
                    "raw": {"keys": sorted(row.keys())},
                }
            )
        return out

    def filings(self, symbol: str, *, cik: str | None = None) -> dict[str, Any]:
        ua = self.sec_user_agent()
        docs: list[dict[str, Any]] = []
        source = None
        error = None
        if ua and cik:
            try:
                result = json_get(
                    SEC_SUBMISSIONS.format(cik=str(cik).zfill(10)),
                    headers={"User-Agent": ua, "Accept": "application/json"},
                    timeout=40,
                    retries=2,
                    cache_key=f"sec-submissions-{str(cik).zfill(10)}",
                )
                payload = result.payload if isinstance(result.payload, dict) else {}
                docs = _filings_from_submissions(payload, str(cik).zfill(10))
                source = "sec.submissions"
            except FetchError as exc:
                error = exc.reason_code
        if not docs:
            rows = self._fmp_try("sec-filings", {"symbol": symbol}) or self._fmp_v3(f"sec_filings/{symbol}", {"type": "10-K"})
            if isinstance(rows, list) and rows:
                for row in rows[:16]:
                    if not isinstance(row, dict):
                        continue
                    form = str(row.get("type") or row.get("form") or row.get("filingType") or "").upper()
                    if form not in {"10-K", "10-Q", "8-K", "20-F", "6-K"}:
                        continue
                    url = str(row.get("finalLink") or row.get("link") or row.get("url") or "").strip()
                    docs.append(
                        {
                            "form": form,
                            "filing_date": row.get("fillingDate") or row.get("filingDate") or row.get("acceptedDate"),
                            "url": url or None,
                            "title": form,
                            "source_provider": "fmp",
                        }
                    )
                if docs:
                    source = "fmp.sec-filings"
                    error = None
        if not docs and not source:
            error = error or ("sec_user_agent_not_configured" if not ua else "upstream_empty")
        return {"source": source, "filings": docs, "error": error}

    def transcripts(self, symbol: str, quarters: list[str]) -> dict[str, Any]:
        found: list[dict[str, Any]] = []
        errors: list[str] = []
        sources: list[str] = []
        fmp = self._fmp()
        av_key = (self.settings.alpha_vantage_api_key or "").strip()
        for quarter in quarters[:6]:
            item = self._fmp_transcript(symbol, quarter)
            if item:
                found.append(item)
                sources.append("fmp")
                continue
            item = self._av_transcript(symbol, quarter)
            if item:
                found.append(item)
                sources.append("alpha_vantage")
                continue
            errors.append(f"{quarter}:empty")
        source = None
        if "fmp" in sources and "alpha_vantage" in sources:
            source = "fmp+alpha_vantage"
        elif "fmp" in sources:
            source = "fmp"
        elif "alpha_vantage" in sources:
            source = "alpha_vantage"
        error = None
        if not found:
            web = self.search_transcripts(symbol, quarters)
            found.extend(list(web.get("transcripts") or []))
            if found:
                source = "web_search"
                errors = []
            else:
                error = web.get("error") or (
                    "upstream_empty" if (fmp or av_key) else "transcript_provider_not_configured"
                )
        return {
            "transcripts": found,
            "source": source,
            "error": error,
            "records_attempted": len(quarters[:6]),
            "quarter_errors": errors[:6],
        }

    def _fmp_transcript(self, symbol: str, quarter: str) -> dict[str, Any] | None:
        parts = parse_quarter_parts(quarter)
        if parts is None or self._fmp() is None:
            return None
        year, qn = parts
        payload = self._fmp_try(
            "earning-call-transcript",
            {"symbol": symbol, "year": year, "quarter": qn},
        )
        if not payload:
            payload = self._fmp_v3(
                f"earning_call_transcript/{symbol}",
                {"year": year, "quarter": qn},
            )
        return normalize_transcript_payload(payload, symbol=symbol, quarter=quarter, provider="fmp")

    def _av_transcript(self, symbol: str, quarter: str) -> dict[str, Any] | None:
        if not (self.settings.alpha_vantage_api_key or "").strip():
            return None
        try:
            from stock_pm.events.av_earnings import fetch_av_function, parse_av_transcript

            result = fetch_av_function(
                "EARNINGS_CALL_TRANSCRIPT",
                symbol,
                settings=self.settings,
                extra={"quarter": quarter},
            )
            payload = result.payload if isinstance(result.payload, dict) else {}
            turns = parse_av_transcript(payload, symbol=symbol, quarter=quarter, fetched_at=result.fetched_at)
        except (FetchError, Exception):
            return None
        if not turns and not payload.get("transcript"):
            return None
        text = _join_turns(turns) or _join_turns(list(payload.get("transcript") or []))
        if not str(text).strip():
            if isinstance(payload.get("transcript"), str):
                text = payload["transcript"]
        if not str(text).strip():
            return None
        published = payload.get("date") or payload.get("published") or utc_now()
        return {
            "quarter": payload.get("quarter") or quarter,
            "fiscal_period": payload.get("quarter") or quarter,
            "published_at": published,
            "source": "alpha_vantage",
            "source_url": f"https://www.alphavantage.co/query?function=EARNINGS_CALL_TRANSCRIPT&symbol={symbol}&quarter={quarter}",
            "text": _trim(text),
            "excerpts": _excerpts_from_turns(turns or list(payload.get("transcript") or [])),
            "title": f"Earnings call {quarter}",
        }

    def daily_bars(self, symbol: str, *, days: int = 430) -> dict[str, Any]:
        from stock_pm.alpaca import collect_live_daily_bars
        from stock_pm.research.official import stooq_daily_bars, yahoo_daily_bars

        try:
            bars, _errors, rec = collect_live_daily_bars(symbol, self.settings, days=days)
        except Exception as exc:
            bars, rec = [], {"daily_price_bars": {"error": str(exc)[:240]}}
        if bars:
            return {
                "bars": bars,
                "source": (rec.get("daily_price_bars") or {}).get("source") or "alpaca",
                "error": None,
                "record": rec.get("daily_price_bars") or {},
            }
        yahoo = yahoo_daily_bars(symbol)
        if yahoo.get("bars"):
            return {**yahoo, "record": {"status": "ok", "source": "yahoo"}}
        stooq = stooq_daily_bars(symbol)
        if stooq.get("bars"):
            return {**stooq, "record": {"status": "ok", "source": "stooq"}}
        error = (
            (rec.get("daily_price_bars") or {}).get("reason_code")
            or yahoo.get("error")
            or stooq.get("error")
            or "upstream_empty"
        )
        return {"bars": [], "source": None, "error": error, "record": rec.get("daily_price_bars") or {}}

    def official_documents(self, symbol: str, filings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        from stock_pm.research.official import ingest_official_filings, search_official_materials, fetch_search_candidates

        ua = self.sec_user_agent() or None
        docs = ingest_official_filings(list(filings or []), user_agent=ua, max_filings=4)
        if any(len(str(item.get("text") or "")) > 400 for item in docs):
            return docs
        issuer: dict[str, Any] = {}
        try:
            issuer = self.sec_identity(symbol) if symbol else {}
        except Exception:
            issuer = {}
        hits = search_official_materials(symbol, legal_name=issuer.get("legal_name"), user_agent=ua)
        docs.extend(fetch_search_candidates(hits, user_agent=ua, limit=3))
        return docs

    def web_search(self, query: str) -> list[dict[str, str]]:
        from stock_pm.research.official import web_search

        return web_search(query, user_agent=self.sec_user_agent() or None)

    def fetch_url(self, url: str) -> dict[str, Any]:
        from stock_pm.research.official import fetch_html

        return fetch_html(url, user_agent=self.sec_user_agent() or None)

    def search_transcripts(self, symbol: str, quarters: list[str] | None = None) -> dict[str, Any]:
        from stock_pm.research.official import fetch_search_candidates, looks_like_transcript, search_official_materials

        del quarters
        issuer = {}
        try:
            issuer = self.sec_identity(symbol)
        except Exception:
            issuer = {}
        hits = search_official_materials(symbol, legal_name=issuer.get("legal_name"), user_agent=self.sec_user_agent() or None)
        docs = [item for item in fetch_search_candidates(hits, user_agent=self.sec_user_agent() or None, limit=4) if looks_like_transcript(str(item.get("text") or ""))]
        out = []
        for item in docs:
            out.append(
                {
                    "quarter": None,
                    "fiscal_period": None,
                    "published_at": item.get("published_at") or _now(),
                    "source": "web_search",
                    "source_url": item.get("url"),
                    "text": item.get("text"),
                    "excerpts": [],
                    "title": item.get("title") or "Earnings call transcript",
                }
            )
        return {
            "transcripts": out,
            "source": "web_search" if out else None,
            "error": None if out else "upstream_empty",
            "records_attempted": len(hits),
        }


def _excerpts_from_turns(turns: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in turns[:EXCERPT_LIMIT]:
        if isinstance(item, dict):
            text = str(item.get("content") or item.get("text") or "").strip()
            speaker = str(item.get("speaker") or "").strip()
        else:
            text = str(item).strip()
            speaker = ""
        if len(text) < 20:
            continue
        out.append({"speaker": speaker, "text": text[:1200]})
    return out


def normalize_transcript_payload(
    payload: Any,
    *,
    symbol: str,
    quarter: str,
    provider: str,
) -> dict[str, Any] | None:
    row: Any = payload
    if isinstance(payload, list):
        row = payload[0] if payload else None
    if not isinstance(row, dict):
        return None
    content = row.get("content") or row.get("transcript") or row.get("text")
    turns: list[dict[str, Any]] = []
    text = ""
    if isinstance(content, list):
        turns = [item for item in content if isinstance(item, dict)]
        text = _join_turns(turns)
    elif isinstance(content, str):
        text = content
    elif isinstance(row.get("transcript"), list):
        turns = [item for item in row["transcript"] if isinstance(item, dict)]
        text = _join_turns(turns)
    if not str(text).strip():
        return None
    published = row.get("date") or row.get("datetime") or row.get("publishedDate") or _now()
    url = str(row.get("url") or row.get("link") or "").strip() or None
    return {
        "quarter": quarter,
        "fiscal_period": quarter,
        "published_at": published,
        "source": provider,
        "source_url": url,
        "text": _trim(text),
        "excerpts": _excerpts_from_turns(turns),
        "title": str(row.get("title") or f"Earnings call {quarter}"),
        "symbol": symbol,
    }


def _filings_from_submissions(payload: dict[str, Any], cik: str) -> list[dict[str, Any]]:
    recent = (payload.get("filings") or {}).get("recent") or {}
    forms = list(recent.get("form") or [])
    dates = list(recent.get("filingDate") or [])
    accessions = list(recent.get("accessionNumber") or [])
    documents = list(recent.get("primaryDocument") or [])
    cik_num = str(int(cik)) if cik.isdigit() else cik.lstrip("0")
    out: list[dict[str, Any]] = []
    for idx, form in enumerate(forms):
        form_u = str(form or "").upper()
        if form_u not in {"10-K", "10-Q", "8-K", "20-F", "6-K"}:
            continue
        accession = str(accessions[idx] if idx < len(accessions) else "").replace("-", "")
        primary = documents[idx] if idx < len(documents) else ""
        filed = dates[idx] if idx < len(dates) else None
        url = None
        if accession and primary:
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession}/{primary}"
        out.append(
            {
                "form": form_u,
                "filing_date": filed,
                "url": url,
                "title": form_u,
                "accession": accessions[idx] if idx < len(accessions) else None,
                "source_provider": "sec",
            }
        )
        if len(out) >= 16:
            break
    return out


def quarters_from_earnings(symbol: str, earnings: list[dict[str, Any]], *, fallback: int = 6) -> list[str]:
    from stock_pm.events.earnings import fiscal_quarter_id

    found: list[str] = []
    for row in earnings:
        period = str(row.get("fiscal_period") or "")
        if re.match(r"20\d{2}Q[1-4]$", period, re.I):
            qid = period.upper()
        else:
            qid = fiscal_quarter_id(symbol, str(row.get("period_end") or row.get("report_date") or ""))
        if qid and qid not in found:
            found.append(qid)
        if len(found) >= fallback:
            break
    if len(found) < fallback:
        for item in calendar_quarters(fallback):
            if item not in found:
                found.append(item)
            if len(found) >= fallback:
                break
    return found[:fallback]


def enrich_earnings_rows(
    rows: list[dict[str, Any]],
    *,
    income: list[dict[str, Any]] | None = None,
    cashflow: list[dict[str, Any]] | None = None,
    segments: Any = None,
) -> list[dict[str, Any]]:
    """Attach margins, FCF, and segment payloads into provider_fields. Never invent numbers."""
    income_rows = [row for row in (income or []) if isinstance(row, dict)]
    cash_rows = [row for row in (cashflow or []) if isinstance(row, dict)]

    def _match(target: str | None, pool: list[dict[str, Any]]) -> dict[str, Any]:
        if not target:
            return {}
        try:
            end = date.fromisoformat(str(target)[:10])
        except ValueError:
            return {}
        for item in pool:
            raw = str(item.get("date") or item.get("fillingDate") or item.get("calendarYear") or "")[:10]
            try:
                other = date.fromisoformat(raw)
            except ValueError:
                continue
            if abs((other - end).days) <= 10:
                return item
        return {}

    segment_rows = _normalize_segments(segments)
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        fields = dict(item.get("provider_fields") or {})
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        matched_income = raw.get("income") if isinstance(raw.get("income"), dict) else _match(item.get("period_end") or item.get("report_date"), income_rows)
        matched_cash = _match(item.get("period_end") or item.get("report_date"), cash_rows)
        revenue = _number(item.get("revenue_actual") or matched_income.get("revenue"))
        gross = _number(matched_income.get("grossProfit"))
        operating = _number(matched_income.get("operatingIncome"))
        net_income = _number(matched_income.get("netIncome") or item.get("net_income_actual"))
        diluted = _number(
            matched_income.get("weightedAverageShsOutDil")
            or matched_income.get("weightedAverageShsOut")
        )
        if revenue and gross is not None:
            fields["gross_margin_pct"] = round(100.0 * gross / revenue, 2)
        if revenue and operating is not None:
            fields["operating_margin_pct"] = round(100.0 * operating / revenue, 2)
        if revenue and net_income is not None:
            fields["net_margin_pct"] = round(100.0 * net_income / revenue, 2)
        if diluted:
            fields["diluted_shares"] = diluted
        fcf = _number(matched_cash.get("freeCashFlow") or matched_cash.get("freeCashFlowReported"))
        if fcf is not None:
            fields["fcf"] = fcf
            fields["free_cash_flow"] = fcf
        period_key = str(item.get("period_end") or item.get("report_date") or "")[:10]
        segs = segment_rows.get(period_key) or []
        if segs:
            fields["segments"] = segs
        item["provider_fields"] = fields
        out.append(item)
    return out


def _normalize_segments(payload: Any) -> dict[str, list[dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    if payload is None:
        return by_date
    rows: list[Any]
    if isinstance(payload, dict):
        if all(isinstance(key, str) and isinstance(value, dict) for key, value in payload.items()):
            rows = [{"date": key, **value} if "date" not in value else value for key, value in payload.items()]
        else:
            rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        return by_date
    for row in rows:
        if not isinstance(row, dict):
            continue
        when = str(row.get("date") or row.get("period") or "")[:10]
        items: list[dict[str, Any]] = []
        data = row.get("data") if isinstance(row.get("data"), dict) else row
        for key, value in data.items():
            if key in {"date", "period", "symbol", "reportedCurrency", "data"}:
                continue
            amount = _number(value)
            if amount is None:
                continue
            items.append({"name": str(key), "revenue": amount})
        if when and items:
            by_date[when] = items
    return by_date


SHARE_CONCEPTS = (
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfShareOutstandingDiluted",
    "WeightedAverageNumberOfSharesOutstandingDiluted",
    "WeightedAverageNumberOfDilutedSharesOutstandingProForma",
    "WeightedAverageNumberOfDilutedSharesOutstandingBasicAndDiluted",
    "WeightedAverageNumberOfDilutedSharesOutstandingCommonStock",
)


def _duration_days(row: dict[str, Any]) -> int | None:
    start = str(row.get("start") or "")[:10]
    end = str(row.get("end") or "")[:10]
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _collapse_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in points:
        key = (str(row.get("end") or ""), str(row.get("fp") or ""))
        prev = best.get(key)
        if prev is None:
            best[key] = row
            continue
        d_new = _duration_days(row)
        d_old = _duration_days(prev)
        new_q = d_new is not None and 60 <= d_new <= 120
        old_q = d_old is not None and 60 <= d_old <= 120
        if new_q != old_q:
            if new_q:
                best[key] = row
            continue
        if str(row.get("filed") or "") >= str(prev.get("filed") or ""):
            best[key] = row
    return list(best.values())


def _share_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract diluted weighted-average share counts (units=SHARES) from companyfacts."""
    taxonomies = payload.get("facts") or {}
    trees = [taxonomies.get("us-gaap") or {}, taxonomies.get("ifrs-full") or {}]
    points: list[dict[str, Any]] = []
    for gaap in trees:
        for name in SHARE_CONCEPTS:
            concept = gaap.get(name) or {}
            units = concept.get("units") or {}
            for unit, rows in units.items():
                if not isinstance(rows, list):
                    continue
                if "SHARE" not in str(unit).upper():
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    form = str(row.get("form") or "").upper()
                    fp = str(row.get("fp") or "").upper()
                    if form not in {"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "6-K"}:
                        continue
                    if fp not in {"Q1", "Q2", "Q3", "Q4", "FY"}:
                        continue
                    end = str(row.get("end") or "")[:10]
                    val = _number(row.get("val"))
                    if not end or val in (None, 0):
                        continue
                    points.append(
                        {
                            "end": end,
                            "start": str(row.get("start") or "")[:10],
                            "val": val,
                            "form": form,
                            "fp": fp,
                            "fy": row.get("fy"),
                            "filed": row.get("filed"),
                        }
                    )
    return _collapse_points(points)


def _fact_points(payload: dict[str, Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
    taxonomies = (payload.get("facts") or {})
    trees = [taxonomies.get("us-gaap") or {}, taxonomies.get("ifrs-full") or {}]
    points: list[dict[str, Any]] = []
    for gaap in trees:
        for name in names:
            concept = gaap.get(name) or {}
            units = concept.get("units") or {}
            for unit, rows in units.items():
                if not isinstance(rows, list):
                    continue
                unit_u = str(unit).upper()
                if unit_u not in {"USD", "USD/SHARES", "PURE"} and not unit_u.startswith("USD"):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    form = str(row.get("form") or "").upper()
                    fp = str(row.get("fp") or "").upper()
                    if form not in {"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "6-K"}:
                        continue
                    if fp not in {"Q1", "Q2", "Q3", "Q4"}:
                        continue
                    end = str(row.get("end") or "")[:10]
                    val = _number(row.get("val"))
                    if not end or val is None:
                        continue
                    points.append(
                        {
                            "end": end,
                            "start": str(row.get("start") or "")[:10],
                            "val": val,
                            "form": form,
                            "fp": fp,
                            "fy": row.get("fy"),
                            "filed": row.get("filed"),
                        }
                    )
    return _collapse_points(points)


def _quarters_from_companyfacts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    revenue = _fact_points(
        payload,
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueGoodsNet",
            "RevenueFromContractsWithCustomers",
        ),
    )
    net_income = _fact_points(
        payload,
        (
            "ProfitLoss",
            "NetIncomeLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
            "NetIncomeLossAvailableToCommonStockholdersDiluted",
        ),
    )
    eps = _fact_points(payload, ("EarningsPerShareDiluted", "EarningsPerShareBasic"))
    gross = _fact_points(payload, ("GrossProfit",))
    operating = _fact_points(payload, ("OperatingIncomeLoss",))
    shares = _share_points(payload)
    by_end: dict[str, dict[str, Any]] = {}
    for row in revenue:
        by_end.setdefault(row["end"], {"period_end": row["end"], "fiscal_period": row["fp"], "fiscal_year": row.get("fy"), "form": row.get("form"), "filed": row.get("filed")})
        by_end[row["end"]]["revenue_actual"] = row["val"]
    for row in net_income:
        by_end.setdefault(row["end"], {"period_end": row["end"], "fiscal_period": row["fp"], "fiscal_year": row.get("fy")})
        by_end[row["end"]]["net_income_actual"] = row["val"]
    for row in eps:
        by_end.setdefault(row["end"], {"period_end": row["end"], "fiscal_period": row["fp"], "fiscal_year": row.get("fy")})
        by_end[row["end"]]["eps_actual"] = row["val"]
    for row in gross:
        item = by_end.get(row["end"])
        if item and item.get("revenue_actual"):
            item.setdefault("provider_fields", {})["gross_margin_pct"] = round(100.0 * row["val"] / item["revenue_actual"], 2)
    for row in operating:
        item = by_end.get(row["end"])
        if item and item.get("revenue_actual"):
            item.setdefault("provider_fields", {})["operating_margin_pct"] = round(100.0 * row["val"] / item["revenue_actual"], 2)
    for row in shares:
        item = by_end.get(row["end"])
        if item:
            item.setdefault("provider_fields", {})["diluted_shares"] = row["val"]
    for item in by_end.values():
        if item.get("net_income_actual") is None:
            eps = item.get("eps_actual")
            sh = (item.get("provider_fields") or {}).get("diluted_shares")
            if eps is not None and sh not in (None, 0):
                item["net_income_actual"] = float(eps) * float(sh)
        rev = item.get("revenue_actual")
        ni = item.get("net_income_actual")
        if rev and ni is not None:
            item.setdefault("provider_fields", {})["net_margin_pct"] = round(100.0 * ni / rev, 1)
    rows = sorted(by_end.values(), key=lambda item: str(item.get("period_end")), reverse=True)
    return rows[:12]


def merge_facts_into_earnings(symbol: str, earnings: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not facts:
        return earnings
    used = set()
    out: list[dict[str, Any]] = []
    for row in earnings:
        item = dict(row)
        matched = None
        report = str(item.get("period_end") or item.get("report_date") or "")[:10]
        try:
            report_day = date.fromisoformat(report) if report else None
        except ValueError:
            report_day = None
        for fact in facts:
            key = str(fact.get("period_end"))
            if key in used:
                continue
            try:
                end = date.fromisoformat(key)
            except ValueError:
                continue
            if report_day and abs((end - report_day).days) <= 45:
                matched = fact
                used.add(key)
                break
        if matched:
            if item.get("revenue_actual") is None:
                item["revenue_actual"] = matched.get("revenue_actual")
            if item.get("net_income_actual") is None:
                item["net_income_actual"] = matched.get("net_income_actual")
            if item.get("eps_actual") is None:
                item["eps_actual"] = matched.get("eps_actual")
            if not item.get("period_end"):
                item["period_end"] = matched.get("period_end")
            fields = dict(item.get("provider_fields") or {})
            fields.update(matched.get("provider_fields") or {})
            item["provider_fields"] = fields
            item["source"] = ((item.get("source") or "nasdaq") + "+sec.companyfacts")
        out.append(item)
    for fact in facts:
        if str(fact.get("period_end")) in used:
            continue
        end = str(fact.get("period_end"))
        out.append(
            {
                "symbol": symbol,
                "report_date": str(fact.get("filed") or end)[:10],
                "report_timing": "unknown",
                "fiscal_period": fact.get("fiscal_period") or "Quarter",
                "fiscal_year": fact.get("fiscal_year"),
                "period_end": end,
                "currency": "USD",
                "eps_actual": fact.get("eps_actual"),
                "revenue_actual": fact.get("revenue_actual"),
                "net_income_actual": fact.get("net_income_actual"),
                "provider_fields": fact.get("provider_fields") or {},
                "source": "sec.companyfacts",
            }
        )
        if len(out) >= 12:
            break
    out.sort(key=lambda row: str(row.get("report_date") or row.get("period_end") or ""), reverse=True)
    return out[:12]


def enrich_fundamentals_from_facts(snapshot: dict[str, Any] | None, facts: dict[str, Any]) -> dict[str, Any] | None:
    quarters = list(facts.get("quarters") or [])
    trailing = [row.get("revenue_actual") for row in quarters[:4]]
    revenue_ttm = sum(item for item in trailing if item is not None) if trailing and all(item is not None for item in trailing) else None
    eps_trail = [row.get("eps_actual") for row in quarters[:4]]
    eps_ttm = sum(item for item in eps_trail if item is not None) if eps_trail and all(item is not None for item in eps_trail) else None
    yoy = None
    if len(quarters) >= 5 and quarters[0].get("revenue_actual") and quarters[4].get("revenue_actual"):
        yoy = round(100.0 * (quarters[0]["revenue_actual"] / quarters[4]["revenue_actual"] - 1.0), 2)
    if snapshot is None and not quarters:
        return None
    out = dict(snapshot or {"source": "sec.companyfacts", "captured_at": _now(), "currency": "USD"})
    if out.get("revenue_ttm") is None and revenue_ttm is not None:
        out["revenue_ttm"] = revenue_ttm
    if out.get("eps_ttm") is None and eps_ttm is not None:
        out["eps_ttm"] = eps_ttm
    if out.get("revenue_growth_yoy_pct") is None and yoy is not None:
        out["revenue_growth_yoy_pct"] = yoy
    margins = (quarters[0].get("provider_fields") or {}) if quarters else {}
    nis = [row.get("net_income_actual") for row in quarters[:4]]
    net_income_ttm = sum(item for item in nis if item is not None) if nis and all(item is not None for item in nis) and len(nis) == 4 else None
    if out.get("net_income_ttm") is None and net_income_ttm is not None:
        out["net_income_ttm"] = net_income_ttm
    if out.get("gross_margin_pct") is None:
        out["gross_margin_pct"] = margins.get("gross_margin_pct")
    if out.get("operating_margin_pct") is None:
        out["operating_margin_pct"] = margins.get("operating_margin_pct")
    if out.get("net_margin_pct") is None:
        out["net_margin_pct"] = margins.get("net_margin_pct")
    if out.get("net_margin_pct") is None and revenue_ttm not in (None, 0) and net_income_ttm is not None:
        out["net_margin_pct"] = round(100.0 * float(net_income_ttm) / float(revenue_ttm), 1)
    for row in quarters:
        shares = (row.get("provider_fields") or {}).get("diluted_shares")
        if shares in (None, 0):
            continue
        form = str(row.get("form") or "")
        origin = "sec_10k" if "10-K" in form else "sec_10q" if "10-Q" in form else "companyfacts"
        out["diluted_shares"] = shares
        out["diluted_shares_origin"] = origin
        fy = row.get("fiscal_year")
        fp = row.get("fiscal_period")
        out["diluted_shares_period"] = f"{fp} FY{fy}" if fy else str(fp or "")
        out["diluted_shares_source"] = "sec.companyfacts"
        out["diluted_shares_source_url"] = None
        break
    if snapshot is None:
        out["source"] = "sec.companyfacts"
    elif "sec.companyfacts" not in str(out.get("source") or ""):
        out["source"] = str(out.get("source") or "nasdaq") + "+sec.companyfacts"
    return out
