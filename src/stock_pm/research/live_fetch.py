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


def calendar_quarters(count: int = 8, *, today: date | None = None) -> list[str]:
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

    def sec_company_facts(self, cik: str | None, *, fiscal_year_end_month: int | None = None) -> dict[str, Any]:
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
        return {
            "quarters": _quarters_from_companyfacts(payload, fiscal_year_end_month=fiscal_year_end_month),
            "error": None,
            "source": "sec.companyfacts",
        }

    def earnings_bundle(self, symbol: str) -> dict[str, Any]:
        captured = _now()
        earnings: list[dict[str, Any]] = []
        fundamentals: dict[str, Any] | None = None
        news: list[dict[str, Any]] = []
        income: list[Any] = []
        cashflow: list[Any] = []
        segments: Any = None
        source: str | None = None
        error: str | None = None
        provider = self._fmp()
        if provider is not None:
            try:
                fetched = provider.fetch(symbol, None, captured, "stocks")
            except Exception as exc:
                error = str(exc)[:300]
            else:
                cashflow = self._fmp_try("cash-flow-statement", {"symbol": symbol, "period": "quarter"}) or []
                segments = self._fmp_try("revenue-product-segmentation", {"symbol": symbol})
                income = self._fmp_try("income-statement", {"symbol": symbol, "period": "quarter"}) or []
                earnings = list(fetched.get("earnings") or [])
                fundamentals = fetched.get("fundamental")
                news = list(fetched.get("news") or [])
                source = "fmp"
                error = None
        if not earnings:
            try:
                nasdaq = NasdaqProvider().fetch(symbol, None, captured, "stocks")
                earnings = list(nasdaq.get("earnings") or [])
                fundamentals = nasdaq.get("fundamental") if fundamentals is None else fundamentals
                news = list(nasdaq.get("news") or []) or news
                source = "nasdaq" if source is None else f"{source}+nasdaq"
                error = None if earnings else error
            except Exception as exc:
                error = error or str(exc)[:300]
        from stock_pm.research.issuer import cik_for, fiscal_year_end_month_for

        ident = self.sec_identity(symbol) if not cik_for(symbol) else {}
        cik = cik_for(symbol) or (ident.get("cik") if isinstance(ident, dict) else None)
        fye = fiscal_year_end_month_for(symbol) or (ident.get("fiscal_year_end_month") if isinstance(ident, dict) else None)
        facts = self.sec_company_facts(cik or None, fiscal_year_end_month=fye)
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
            "income": income if isinstance(income, list) else [],
            "cashflow": cashflow if isinstance(cashflow, list) else [],
            "segments": segments,
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
        for quarter in quarters[:8]:
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
            "records_attempted": len(quarters[:8]),
            "quarter_errors": errors[:8],
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
        docs = ingest_official_filings(list(filings or []), user_agent=ua, max_filings=8)
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


def quarters_from_earnings(symbol: str, earnings: list[dict[str, Any]], *, fallback: int = 8) -> list[str]:
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


def _is_quarterly_duration(row: dict[str, Any]) -> bool:
    days = _duration_days(row)
    return days is not None and 60 <= days <= 120


def _is_annual_duration(row: dict[str, Any]) -> bool:
    days = _duration_days(row)
    return days is not None and 330 <= days <= 400


def _collapse_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One fact per period-end. Prefer 60–120 day quarterly duration over YTD/FY."""
    best: dict[str, dict[str, Any]] = {}
    for row in points:
        key = str(row.get("end") or "")[:10]
        if not key:
            continue
        prev = best.get(key)
        if prev is None:
            best[key] = row
            continue
        new_q = _is_quarterly_duration(row)
        old_q = _is_quarterly_duration(prev)
        if new_q != old_q:
            if new_q:
                best[key] = row
            continue
        if str(row.get("filed") or "") > str(prev.get("filed") or ""):
            best[key] = row
    return list(best.values())


def _collapse_annual_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in points:
        if not _is_annual_duration(row):
            continue
        key = str(row.get("end") or "")[:10]
        if not key:
            continue
        prev = best.get(key)
        if prev is None or str(row.get("filed") or "") > str(prev.get("filed") or ""):
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
    return [row for row in _collapse_points(points) if _is_quarterly_duration(row)]


def _raw_fact_points(payload: dict[str, Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
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
                    if fp not in {"Q1", "Q2", "Q3", "Q4", "FY"}:
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
    return points


def _fact_points(payload: dict[str, Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [row for row in _collapse_points(_raw_fact_points(payload, names)) if _is_quarterly_duration(row)]


def _annual_fact_points(payload: dict[str, Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
    return _collapse_annual_points(_raw_fact_points(payload, names))


def _derive_q4_from_annual(
    quarterly: list[dict[str, Any]],
    annuals: list[dict[str, Any]],
    *,
    fiscal_year_end_month: int | None,
) -> list[dict[str, Any]]:
    """10-K often files FY duration only. Q4 = FY − Q1 − Q2 − Q3 for that fiscal year."""
    from stock_pm.research.issuer import fiscal_label_from_period_end

    by_end = {str(row.get("end") or "")[:10]: row for row in quarterly if row.get("end")}
    by_fy_fp: dict[tuple[int, str], dict[str, Any]] = {}
    for row in quarterly:
        fy, fp = fiscal_label_from_period_end(row.get("end"), fiscal_year_end_month)
        if fy and fp:
            by_fy_fp[(int(fy), str(fp))] = row
    for row in annuals:
        end = str(row.get("end") or "")[:10]
        if not end or end in by_end:
            continue
        fy, fp = fiscal_label_from_period_end(end, fiscal_year_end_month)
        if not fy or fp != "Q4":
            continue
        q1 = by_fy_fp.get((int(fy), "Q1"))
        q2 = by_fy_fp.get((int(fy), "Q2"))
        q3 = by_fy_fp.get((int(fy), "Q3"))
        if not (q1 and q2 and q3):
            continue
        parts = [q1.get("val"), q2.get("val"), q3.get("val"), row.get("val")]
        if any(item is None for item in parts):
            continue
        derived = float(row["val"]) - float(q1["val"]) - float(q2["val"]) - float(q3["val"])
        annual_val = float(row["val"])
        # 0.75 cap is for revenue/income scale, not EPS (a seasonal Q4 can be most of annual EPS).
        if abs(annual_val) >= 1000 and annual_val > 0 and (derived <= 0 or derived > annual_val * 0.75):
            continue
        scale = max(abs(float(q1["val"])), abs(float(q2["val"])), abs(float(q3["val"])), 1e-9)
        if abs(derived) > 8.0 * scale:
            continue
        if abs(annual_val) < 1000:
            derived = round(derived, 4)
        by_end[end] = {
            "end": end,
            "start": str(q3.get("end") or "")[:10],
            "val": derived,
            "form": row.get("form") or "10-K",
            "fp": "Q4",
            "fy": fy,
            "filed": row.get("filed"),
            "derived_q4": True,
        }
    return list(by_end.values())


def _parse_day(value: Any) -> date | None:
    text = str(value or "")[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


REVENUE_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueGoodsNet",
    "RevenueFromContractsWithCustomers",
)
NET_INCOME_CONCEPTS = (
    "ProfitLoss",
    "NetIncomeLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "NetIncomeLossAvailableToCommonStockholdersDiluted",
)
EPS_CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")


def _quarters_from_companyfacts(payload: dict[str, Any], *, fiscal_year_end_month: int | None = None) -> list[dict[str, Any]]:
    from stock_pm.research.issuer import fiscal_label_from_period_end

    revenue = _derive_q4_from_annual(
        _fact_points(payload, REVENUE_CONCEPTS),
        _annual_fact_points(payload, REVENUE_CONCEPTS),
        fiscal_year_end_month=fiscal_year_end_month,
    )
    net_income = _derive_q4_from_annual(
        _fact_points(payload, NET_INCOME_CONCEPTS),
        _annual_fact_points(payload, NET_INCOME_CONCEPTS),
        fiscal_year_end_month=fiscal_year_end_month,
    )
    eps = _derive_q4_from_annual(
        _fact_points(payload, EPS_CONCEPTS),
        _annual_fact_points(payload, EPS_CONCEPTS),
        fiscal_year_end_month=fiscal_year_end_month,
    )
    gross = _derive_q4_from_annual(
        _fact_points(payload, ("GrossProfit",)),
        _annual_fact_points(payload, ("GrossProfit",)),
        fiscal_year_end_month=fiscal_year_end_month,
    )
    operating = _derive_q4_from_annual(
        _fact_points(payload, ("OperatingIncomeLoss",)),
        _annual_fact_points(payload, ("OperatingIncomeLoss",)),
        fiscal_year_end_month=fiscal_year_end_month,
    )
    shares = _share_points(payload)
    by_end: dict[str, dict[str, Any]] = {}
    for row in revenue:
        fy, fp = fiscal_label_from_period_end(row["end"], fiscal_year_end_month)
        by_end.setdefault(
            row["end"],
            {
                "period_end": row["end"],
                "fiscal_period": fp or row["fp"],
                "fiscal_year": fy or row.get("fy"),
                "form": row.get("form"),
                "filed": row.get("filed"),
            },
        )
        by_end[row["end"]]["revenue_actual"] = row["val"]
    for row in net_income:
        item = by_end.setdefault(row["end"], {"period_end": row["end"], "fiscal_period": row["fp"], "fiscal_year": row.get("fy")})
        item["net_income_actual"] = row["val"]
    for row in eps:
        item = by_end.setdefault(row["end"], {"period_end": row["end"], "fiscal_period": row["fp"], "fiscal_year": row.get("fy")})
        item["eps_actual"] = row["val"]
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
        fy, fp = fiscal_label_from_period_end(item.get("period_end"), fiscal_year_end_month)
        if fy:
            item["fiscal_year"] = fy
        if fp:
            item["fiscal_period"] = fp
        item.setdefault("provider_fields", {})["companyfacts_revenue"] = item.get("revenue_actual")
        if any(row.get("derived_q4") and row.get("end") == item.get("period_end") for row in revenue):
            item["provider_fields"]["q4_derived_from_10k"] = True
        if item.get("net_income_actual") is None:
            eps_val = item.get("eps_actual")
            sh = (item.get("provider_fields") or {}).get("diluted_shares")
            if eps_val is not None and sh not in (None, 0):
                item["net_income_actual"] = float(eps_val) * float(sh)
        if item.get("eps_actual") is None:
            ni = item.get("net_income_actual")
            sh = (item.get("provider_fields") or {}).get("diluted_shares")
            if ni is not None and sh not in (None, 0):
                item["eps_actual"] = round(float(ni) / float(sh), 4)
                item.setdefault("provider_fields", {})["eps_from_ni_shares"] = True
        item["provider_fields"]["companyfacts_eps"] = item.get("eps_actual")
        rev = item.get("revenue_actual")
        ni = item.get("net_income_actual")
        if rev and ni is not None:
            item.setdefault("provider_fields", {})["net_margin_pct"] = round(100.0 * ni / rev, 1)
    rows = sorted(by_end.values(), key=lambda item: str(item.get("period_end") or ""), reverse=True)
    return rows[:16]


def merge_facts_into_earnings(symbol: str, earnings: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not facts:
        return earnings
    facts_by_end = {str(fact.get("period_end") or "")[:10]: fact for fact in facts if fact.get("period_end")}
    used: set[str] = set()
    out: list[dict[str, Any]] = []

    def _near(end: date, target: date, days: int) -> bool:
        return abs((end - target).days) <= days

    for row in earnings:
        item = dict(row)
        matched = None
        period = _parse_day(item.get("period_end"))
        report = _parse_day(item.get("report_date"))
        if period:
            for key, fact in facts_by_end.items():
                end = _parse_day(key)
                if end and _near(end, period, 10):
                    matched = fact
                    break
        if matched is None and report:
            candidates: list[tuple[date, dict[str, Any]]] = []
            for key, fact in facts_by_end.items():
                end = _parse_day(key)
                if end and end <= report and (report - end).days <= 95:
                    candidates.append((end, fact))
            if candidates:
                matched = max(candidates, key=lambda pair: pair[0])[1]
        if matched:
            key = str(matched.get("period_end") or "")[:10]
            used.add(key)
            fields = dict(item.get("provider_fields") or {})
            if item.get("revenue_actual") is not None:
                fields["nasdaq_revenue"] = item.get("revenue_actual")
            if item.get("eps_actual") is not None:
                fields["nasdaq_eps"] = item.get("eps_actual")
            fields.update(matched.get("provider_fields") or {})
            if matched.get("revenue_actual") is not None:
                item["revenue_actual"] = matched.get("revenue_actual")
            if matched.get("net_income_actual") is not None:
                item["net_income_actual"] = matched.get("net_income_actual")
            if matched.get("eps_actual") is not None:
                item["eps_actual"] = matched.get("eps_actual")
            if matched.get("period_end"):
                item["period_end"] = matched.get("period_end")
            if matched.get("fiscal_year"):
                item["fiscal_year"] = matched.get("fiscal_year")
            if matched.get("fiscal_period"):
                item["fiscal_period"] = matched.get("fiscal_period")
            item["provider_fields"] = fields
            item["source"] = ((item.get("source") or "nasdaq") + "+sec.companyfacts")
        out.append(item)
    for fact in facts:
        key = str(fact.get("period_end") or "")[:10]
        if not key or key in used:
            continue
        end = _parse_day(key)
        already = False
        for row in out:
            other = _parse_day(row.get("period_end"))
            if end and other and abs((end - other).days) <= 10:
                already = True
                break
        if already:
            continue
        out.append(
            {
                "symbol": symbol,
                "report_date": str(fact.get("filed") or key)[:10],
                "report_timing": "unknown",
                "fiscal_period": fact.get("fiscal_period") or "Quarter",
                "fiscal_year": fact.get("fiscal_year"),
                "period_end": key,
                "currency": "USD",
                "eps_actual": fact.get("eps_actual"),
                "revenue_actual": fact.get("revenue_actual"),
                "net_income_actual": fact.get("net_income_actual"),
                "provider_fields": fact.get("provider_fields") or {},
                "source": "sec.companyfacts",
            }
        )
        used.add(key)
        if len([row for row in out if row.get("period_end")]) >= 16:
            break
    dated = [row for row in out if row.get("period_end")]
    dated.sort(key=lambda row: str(row.get("period_end") or ""), reverse=True)
    return dedupe_earnings_prints(dated)[:16]


def _print_score(row: dict[str, Any]) -> int:
    fields = row.get("provider_fields") if isinstance(row.get("provider_fields"), dict) else {}
    score = 0
    if row.get("period_end"):
        score += 8
    if fields.get("companyfacts_revenue") is not None or "companyfacts" in str(row.get("source") or ""):
        score += 4
    if fields.get("companyfacts_eps") is not None:
        score += 2
    if row.get("revenue_actual") is not None or row.get("revenue") is not None:
        score += 2
    if str(row.get("fiscal_period") or "") in {"Q1", "Q2", "Q3", "Q4"}:
        score += 3
    return score


def _absorb_print_fields(winner: dict[str, Any], loser: dict[str, Any]) -> dict[str, Any]:
    out = dict(winner)
    winner_fp = str(out.get("fiscal_period") or "")
    loser_fp = str(loser.get("fiscal_period") or "")
    if loser_fp in {"Q1", "Q2", "Q3", "Q4"} and winner_fp not in {"Q1", "Q2", "Q3", "Q4"}:
        out["fiscal_period"] = loser_fp
        if loser.get("fiscal_year"):
            out["fiscal_year"] = loser.get("fiscal_year")
    if not out.get("period_end") and loser.get("period_end"):
        out["period_end"] = loser.get("period_end")
    fields = dict(out.get("provider_fields") or {})
    other = loser.get("provider_fields") if isinstance(loser.get("provider_fields"), dict) else {}
    loser_is_nasdaq = "nasdaq" in str(loser.get("source") or "").lower()
    if fields.get("nasdaq_revenue") is None:
        fields["nasdaq_revenue"] = other.get("nasdaq_revenue") or ((loser.get("revenue_actual") or loser.get("revenue")) if loser_is_nasdaq else None)
    if fields.get("nasdaq_eps") is None:
        fields["nasdaq_eps"] = other.get("nasdaq_eps") or ((loser.get("eps_actual") or loser.get("eps")) if loser_is_nasdaq else None)
    if fields.get("companyfacts_revenue") is None:
        fields["companyfacts_revenue"] = other.get("companyfacts_revenue")
    if fields.get("companyfacts_eps") is None:
        fields["companyfacts_eps"] = other.get("companyfacts_eps") or (
            loser.get("eps_actual") if "companyfacts" in str(loser.get("source") or "") else None
        )
    for key in ("gross_margin_pct", "operating_margin_pct", "net_margin_pct", "diluted_shares", "q4_derived_from_10k"):
        if fields.get(key) is None and other.get(key) is not None:
            fields[key] = other.get(key)
    for key in ("eps_estimate", "revenue_estimate", "eps_surprise_pct", "revenue_surprise_pct"):
        if out.get(key) is None and loser.get(key) is not None:
            out[key] = loser.get(key)
    if fields.get("companyfacts_eps") is not None:
        out["eps_actual"] = fields["companyfacts_eps"]
        if "eps" in out or loser.get("eps") is not None:
            out["eps"] = fields["companyfacts_eps"]
    if fields.get("companyfacts_revenue") is not None:
        out["revenue_actual"] = fields["companyfacts_revenue"]
        if "revenue" in out or loser.get("revenue") is not None:
            out["revenue"] = fields["companyfacts_revenue"]
    if "companyfacts" in str(loser.get("source") or "") and "companyfacts" not in str(out.get("source") or ""):
        out["source"] = ((out.get("source") or "nasdaq") + "+sec.companyfacts")
    out["provider_fields"] = fields
    return out


def dedupe_earnings_prints(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One print per period_end. Prefer companyfacts + Q1–Q4 labels over Nasdaq month labels."""
    by_end: dict[str, dict[str, Any]] = {}
    leftover: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        end = str(row.get("period_end") or "")[:10]
        if not end:
            leftover.append(row)
            continue
        prev = by_end.get(end)
        if prev is None:
            by_end[end] = row
        elif _print_score(row) > _print_score(prev):
            by_end[end] = _absorb_print_fields(row, prev)
        else:
            by_end[end] = _absorb_print_fields(prev, row)
    kept = list(by_end.values())
    unused: list[dict[str, Any]] = []
    for row in leftover:
        report = _parse_day(row.get("report_date"))
        absorbed = False
        if report:
            for idx, item in enumerate(kept):
                end = _parse_day(item.get("period_end"))
                if end and end <= report and (report - end).days <= 95:
                    kept[idx] = _absorb_print_fields(item, row)
                    absorbed = True
                    break
        if not absorbed:
            unused.append(row)
    dated = sorted(kept, key=lambda row: str(row.get("period_end") or ""), reverse=True)
    return dated + unused


def _contiguous_quarters(rows: list[dict[str, Any]], *, count: int = 4) -> list[dict[str, Any]]:
    """Trailing prints must be adjacent fiscal quarters. Do not fill a missing Q4 with the prior-year Q3."""
    picked: list[dict[str, Any]] = []
    for row in rows:
        if row.get("revenue_actual") is None:
            continue
        end = _parse_day(row.get("period_end"))
        if end is None:
            continue
        if picked:
            prev = _parse_day(picked[-1].get("period_end"))
            if prev is None:
                break
            gap = (prev - end).days
            if gap < 50:
                continue
            if gap > 140:
                break
        picked.append(row)
        if len(picked) >= count:
            break
    return picked if len(picked) == count else []


def enrich_fundamentals_from_facts(snapshot: dict[str, Any] | None, facts: dict[str, Any]) -> dict[str, Any] | None:
    seen: set[str] = set()
    quarters: list[dict[str, Any]] = []
    for row in list(facts.get("quarters") or []):
        key = str(row.get("period_end") or "")[:10]
        if not key or key in seen:
            continue
        seen.add(key)
        quarters.append(row)
    quarters.sort(key=lambda item: str(item.get("period_end") or ""), reverse=True)
    trailing_rows = _contiguous_quarters(quarters, count=4)
    leftover = [row for row in quarters if str(row.get("period_end") or "")[:10] not in {str(item.get("period_end") or "")[:10] for item in trailing_rows}]
    prior_rows = _contiguous_quarters(leftover, count=4) if trailing_rows else []
    trailing = [row.get("revenue_actual") for row in trailing_rows]
    revenue_ttm = sum(item for item in trailing if item is not None) if trailing and len(trailing) == 4 and all(item is not None for item in trailing) else None
    prior = [row.get("revenue_actual") for row in prior_rows]
    prior_ttm = sum(item for item in prior if item is not None) if prior and all(item is not None for item in prior) and len(prior) == 4 else None
    eps_trail = [row.get("eps_actual") for row in trailing_rows]
    eps_ttm = sum(item for item in eps_trail if item is not None) if eps_trail and all(item is not None for item in eps_trail) and len(eps_trail) == 4 else None
    yoy = None
    if revenue_ttm and prior_ttm:
        yoy = round(100.0 * (revenue_ttm / prior_ttm - 1.0), 2)
    if snapshot is None and not quarters:
        return None
    out = dict(snapshot or {"source": "sec.companyfacts", "captured_at": _now(), "currency": "USD"})
    if revenue_ttm is not None:
        out["revenue_ttm"] = revenue_ttm
    if eps_ttm is not None:
        out["eps_ttm"] = eps_ttm
    if yoy is not None:
        out["revenue_growth_yoy_pct"] = yoy
    margins = (quarters[0].get("provider_fields") or {}) if quarters else {}
    nis = [row.get("net_income_actual") for row in trailing_rows]
    net_income_ttm = sum(item for item in nis if item is not None) if nis and all(item is not None for item in nis) and len(nis) == 4 else None
    if trailing_rows:
        out["revenue_ttm"] = revenue_ttm
        out["eps_ttm"] = eps_ttm
        out["net_income_ttm"] = net_income_ttm if net_income_ttm is not None else out.get("net_income_ttm")
        if out.get("eps_ttm") is None:
            shares = out.get("diluted_shares")
            ni_ttm = out.get("net_income_ttm")
            if ni_ttm is not None and shares not in (None, 0):
                out["eps_ttm"] = round(float(ni_ttm) / float(shares), 4)
    elif quarters:
        out["revenue_ttm"] = None
        out["eps_ttm"] = None
        out.setdefault("provider_fields_notes", "ttm_requires_four_contiguous_quarters")
    if out.get("net_income_ttm") is None and net_income_ttm is not None:
        out["net_income_ttm"] = net_income_ttm
    if margins.get("gross_margin_pct") is not None:
        out["gross_margin_pct"] = margins.get("gross_margin_pct")
    if margins.get("operating_margin_pct") is not None:
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
