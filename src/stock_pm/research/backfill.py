"""ResearchDataBackfill: modular per-ticker source ingest with independent step status.

Raw rows land in existing tables (earnings_reports, fundamentals_snapshots,
price_bars, news_articles) plus research_source_documents. Research Pack stays
a rebuildable snapshot. Transcript failure must not abort other steps.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from stock_pm.config import Settings

from .extract import extract_guidance_mentions
from .ids import new_id
from .issuer import merge_identity, missing_identity_fields
from .live_fetch import (
    LiveResearchFetchers,
    calendar_quarters,
    enrich_earnings_rows,
    quarters_from_earnings,
)
from .sources import DictPackSource


STEP_NAMES = (
    "issuer",
    "earnings",
    "filings",
    "transcripts",
    "fundamentals",
    "prices",
    "major_events",
    "rebuild_pack",
)

KEY_MISSING = {
    "earnings_history",
    "earnings_history_depth",
    "transcripts",
    "guidance_history",
    "fundamentals_snapshot",
    "price_reaction_history",
    "major_events",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _timeout_seconds(settings: Settings | None = None) -> int:
    raw = os.getenv("RESEARCH_BACKFILL_TIMEOUT_SECONDS")
    if raw:
        try:
            return max(15, int(raw))
        except ValueError:
            pass
    return 180


def _retries() -> int:
    raw = os.getenv("RESEARCH_BACKFILL_RETRIES")
    try:
        return max(0, int(raw)) if raw else 1
    except ValueError:
        return 1


def pack_needs_research_data(pack: dict[str, Any] | None) -> bool:
    missing = {str(item) for item in (pack or {}).get("missing_fields") or []}
    return bool(missing & KEY_MISSING)


def can_live_backfill(service: Any, fetchers: Any | None = None) -> bool:
    if fetchers is not None:
        return True
    return getattr(getattr(service, "store", None), "database", None) is not None


def should_backfill(
    service: Any,
    pack: dict[str, Any] | None,
    *,
    execute: bool,
    backfill: Any = None,
) -> bool:
    if backfill is False:
        return False
    if isinstance(backfill, ResearchDataBackfill) or backfill is True:
        if isinstance(getattr(service, "pack_source", None), DictPackSource) and backfill is not True and not isinstance(backfill, ResearchDataBackfill):
            return False
        return True
    if not execute:
        return False
    if isinstance(getattr(service, "pack_source", None), DictPackSource):
        return False
    if not can_live_backfill(service):
        return False
    return pack_needs_research_data(pack)


class ResearchDataBackfill:
    def __init__(
        self,
        service: Any,
        settings: Settings | None = None,
        *,
        fetchers: Any | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.service = service
        self.settings = settings or Settings()
        self.fetchers = fetchers if fetchers is not None else LiveResearchFetchers(self.settings)
        self.timeout_seconds = int(timeout_seconds or _timeout_seconds(self.settings))
        self.max_retries = int(max_retries if max_retries is not None else _retries())
        self._deadline = 0.0

    def latest(self, ticker: str) -> dict[str, Any] | None:
        store = self.service.store
        if hasattr(store, "latest_backfill"):
            return store.latest_backfill(ticker)
        return None

    def run(self, ticker: str, *, workflow_run_id: str | None = None, force: bool = False) -> dict[str, Any]:
        symbol = str(ticker or "").upper()
        self._deadline = time.monotonic() + self.timeout_seconds
        steps = {name: _pending_step() for name in STEP_NAMES}
        row = self._insert(symbol, workflow_run_id, steps)
        backfill_id = row["id"]
        try:
            self._run_step("issuer", steps, backfill_id, lambda: self._issuer(symbol))
            self._run_step("earnings", steps, backfill_id, lambda: self._earnings(symbol))
            self._run_step("filings", steps, backfill_id, lambda: self._filings(symbol))
            self._run_step("transcripts", steps, backfill_id, lambda: self._transcripts(symbol))
            self._run_step("fundamentals", steps, backfill_id, lambda: self._fundamentals(symbol))
            self._run_step("prices", steps, backfill_id, lambda: self._prices(symbol))
            self._run_step("major_events", steps, backfill_id, lambda: self._major_events(symbol))
            self._run_step("rebuild_pack", steps, backfill_id, lambda: self._rebuild(symbol, workflow_run_id))
        except Exception as exc:
            status = _overall(steps, interrupted=True)
            return self._finish(backfill_id, steps, status, error=str(exc)[:400])
        status = _overall(steps)
        return self._finish(backfill_id, steps, status)

    def _remaining(self) -> float:
        return self._deadline - time.monotonic()

    def _run_step(self, name: str, steps: dict[str, Any], backfill_id: str, fn: Any) -> None:
        if self._remaining() <= 1:
            steps[name] = _step_result("failed", error="timeout", records_found=0)
            self._save(backfill_id, steps, "running")
            return
        attempts = 1 + max(0, self.max_retries)
        last_error = None
        for attempt in range(attempts):
            steps[name] = {**steps[name], "status": "running", "last_attempt_at": _now()}
            self._save(backfill_id, steps, "running")
            try:
                result = fn()
                steps[name] = _step_result(
                    str(result.get("status") or "success"),
                    records_found=int(result.get("records_found") or 0),
                    source=result.get("source"),
                    error=result.get("error"),
                )
                self._save(backfill_id, steps, "running")
                return
            except Exception as exc:
                last_error = str(exc)[:300]
                if attempt + 1 >= attempts:
                    steps[name] = _step_result("failed", error=last_error, records_found=0)
                    self._save(backfill_id, steps, "running")
                    return

    def _insert(self, ticker: str, workflow_run_id: str | None, steps: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": new_id("rbfl"),
            "ticker": ticker,
            "status": "running",
            "steps": steps,
            "started_at": _now(),
            "workflow_run_id": workflow_run_id,
        }
        return self.service.store.insert_backfill(payload)

    def _save(self, backfill_id: str, steps: dict[str, Any], status: str, error: str | None = None) -> dict[str, Any]:
        return self.service.store.update_backfill(backfill_id, status=status, steps=steps, error=error)

    def _finish(self, backfill_id: str, steps: dict[str, Any], status: str, error: str | None = None) -> dict[str, Any]:
        return self.service.store.update_backfill(
            backfill_id,
            status=status,
            steps=steps,
            error=error,
            finished_at=_now(),
        )

    def _issuer(self, symbol: str) -> dict[str, Any]:
        listed = merge_identity(symbol, source="research_backfill")
        profile = {}
        sec = {}
        sources: list[str] = []
        try:
            fetched = self.fetchers.issuer_profile(symbol)
            profile = fetched.get("profile") or {}
            if fetched.get("source"):
                sources.append(str(fetched["source"]))
        except Exception:
            profile = {}
        try:
            sec = self.fetchers.sec_identity(symbol) or {}
            if sec.get("source"):
                sources.append(str(sec["source"]))
        except Exception:
            sec = {}
        fye = listed.get("fiscal_year_end_month")
        if fye in (None, "") and sec.get("fiscal_year_end_month"):
            fye = sec.get("fiscal_year_end_month")
        cik = listed.get("cik") or sec.get("cik") or _digits(profile.get("cik"))
        name = listed.get("legal_name") if listed.get("legal_name") and listed.get("legal_name") != symbol else None
        name = name or sec.get("legal_name") or profile.get("companyName") or listed.get("legal_name") or symbol
        sector = listed.get("sector") or _sector_hint(profile, sec)
        exchange = listed.get("primary_exchange") or profile.get("exchangeShortName") or ""
        stored = self.service.ensure_issuer(
            symbol,
            legal_name=name,
            cik=cik,
            fiscal_year_end_month=fye,
            sector=sector,
            primary_exchange=exchange,
            source="research_backfill",
        )
        missing = missing_identity_fields(stored)
        status = "success" if not missing else ("partial" if stored.get("legal_name") else "failed")
        return {
            "status": status,
            "records_found": 0 if missing == ["cik", "fiscal_year_end_month", "legal_name"] else 1,
            "source": "+".join(sources) or "issuer_directory",
            "error": ",".join(missing) if missing else None,
        }

    def _earnings(self, symbol: str) -> dict[str, Any]:
        bundle = self.fetchers.earnings_bundle(symbol)
        rows = enrich_earnings_rows(
            list(bundle.get("earnings") or []),
            income=bundle.get("income") or [],
            cashflow=bundle.get("cashflow") or [],
            segments=bundle.get("segments"),
        )
        self._remember(symbol, "earnings", rows)
        self._remember(symbol, "fundamentals", bundle.get("fundamentals"))
        self._remember(symbol, "news", list(bundle.get("news") or []))
        self._persist_bundle(symbol, rows, bundle)
        count = len(rows)
        if count >= 4:
            status = "success"
        elif count:
            status = "partial"
        else:
            status = "failed"
        return {
            "status": status,
            "records_found": count,
            "source": bundle.get("source"),
            "error": bundle.get("error") if count == 0 else None,
        }

    def _filings(self, symbol: str) -> dict[str, Any]:
        issuer = self.service.get_issuer(symbol) or {}
        result = self.fetchers.filings(symbol, cik=issuer.get("cik"))
        written = 0
        for row in result.get("filings") or []:
            form = str(row.get("form") or row.get("title") or "filing")
            doc = self.service.store.upsert_source_document(
                {
                    "ticker": symbol,
                    "doc_type": "filing",
                    "source_key": str(row.get("url") or row.get("accession") or form),
                    "published_at": row.get("filing_date"),
                    "title": form,
                    "url": row.get("url"),
                    "excerpt": form,
                    "body": "",
                    "source_provider": row.get("source_provider") or result.get("source") or "sec",
                    "metadata": {"form": form, "filing_date": row.get("filing_date")},
                }
            )
            if doc:
                written += 1
        count = written
        if count:
            status = "success"
        else:
            status = "failed"
        return {
            "status": status,
            "records_found": count,
            "source": result.get("source"),
            "error": result.get("error") if count == 0 else None,
        }

    def _transcripts(self, symbol: str) -> dict[str, Any]:
        earnings = self._overlay(symbol, "earnings") or []
        if not earnings:
            earnings = _earnings_from_store(self.service, symbol)
        quarters = quarters_from_earnings(symbol, earnings) or calendar_quarters(6)
        result = self.fetchers.transcripts(symbol, quarters)
        written = 0
        for item in result.get("transcripts") or []:
            text = str(item.get("text") or "")
            period = str(item.get("fiscal_period") or item.get("quarter") or "")
            published = item.get("published_at")
            source = str(item.get("source") or result.get("source") or "transcript")
            self.service.store.upsert_source_document(
                {
                    "ticker": symbol,
                    "doc_type": "transcript",
                    "source_key": str(item.get("source_url") or period or item.get("title") or "transcript"),
                    "fiscal_period": period or None,
                    "published_at": published,
                    "title": item.get("title") or f"Earnings call {period}",
                    "url": item.get("source_url"),
                    "excerpt": (item.get("excerpts") or [{}])[0].get("text") if item.get("excerpts") else text[:1200],
                    "body": text,
                    "source_provider": source,
                    "metadata": {"quarter": period, "excerpts": item.get("excerpts") or []},
                }
            )
            written += 1
            for hit in extract_guidance_mentions(text)[:8]:
                self.service.store.upsert_source_document(
                    {
                        "ticker": symbol,
                        "doc_type": "guidance",
                        "source_key": f"{period}:{hit['quote'][:80]}",
                        "fiscal_period": period or None,
                        "published_at": published,
                        "title": "Management guidance",
                        "url": item.get("source_url"),
                        "excerpt": hit["quote"],
                        "body": hit["quote"],
                        "source_provider": source,
                        "metadata": {"kind": "guidance", "move": hit.get("move")},
                    }
                )
        count = written
        if count >= 4:
            status = "success"
        elif count:
            status = "partial"
        else:
            status = "failed"
        return {
            "status": status,
            "records_found": count,
            "source": result.get("source"),
            "error": result.get("error") if count == 0 else None,
        }

    def _fundamentals(self, symbol: str) -> dict[str, Any]:
        snapshot = self._overlay(symbol, "fundamentals")
        if snapshot is None:
            bundle = self.fetchers.earnings_bundle(symbol)
            snapshot = bundle.get("fundamentals")
            if bundle.get("earnings") and not self._overlay(symbol, "earnings"):
                self._remember(symbol, "earnings", bundle.get("earnings"))
                self._persist_bundle(symbol, list(bundle.get("earnings") or []), bundle)
            self._remember(symbol, "fundamentals", snapshot)
            self._remember(symbol, "news", list(bundle.get("news") or []))
            source = bundle.get("source")
            error = bundle.get("error")
        else:
            source = str((snapshot or {}).get("source") or "fmp")
            error = None
        if snapshot:
            self._ingest(symbol, fundamentals=[snapshot], source=str(source or "fundamentals"))
            status = "success"
            count = 1
        else:
            status = "failed"
            count = 0
            error = error or "provider_unsupported_or_empty"
        return {"status": status, "records_found": count, "source": source, "error": error if count == 0 else None}

    def _prices(self, symbol: str) -> dict[str, Any]:
        written = 0
        sources: list[str] = []
        errors: list[str] = []
        for ticker in (symbol, "SPY", "QQQ"):
            if self._remaining() <= 1:
                errors.append("timeout")
                break
            result = self.fetchers.daily_bars(ticker, days=430)
            bars = list(result.get("bars") or [])
            self._remember(ticker, "bars", bars)
            if bars:
                self._persist_bars(ticker, bars, source=str(result.get("source") or "alpaca"))
                written += len(bars)
                if result.get("source"):
                    sources.append(f"{ticker}:{result['source']}")
            elif result.get("error"):
                errors.append(f"{ticker}:{result['error']}")
        if written and symbol in (self._overlay_map("bars") or {}) and self._overlay(symbol, "bars"):
            status = "success" if not errors else "partial"
        elif written:
            status = "partial"
        else:
            status = "failed"
        return {
            "status": status,
            "records_found": written,
            "source": ",".join(sources) or None,
            "error": ";".join(errors) if errors and status != "success" else (errors[0] if errors and not written else None),
        }

    def _major_events(self, symbol: str) -> dict[str, Any]:
        written = 0
        source = None
        try:
            releases = self.fetchers.press_releases(symbol)
        except Exception as exc:
            return {"status": "failed", "records_found": 0, "source": None, "error": str(exc)[:240]}
        for row in releases:
            text = str(row.get("text") or "")
            title = str(row.get("title") or "Press release")
            self.service.store.upsert_source_document(
                {
                    "ticker": symbol,
                    "doc_type": "press_release",
                    "source_key": str(row.get("url") or title),
                    "published_at": row.get("published_at"),
                    "title": title,
                    "url": row.get("url"),
                    "excerpt": (text or title)[:1200],
                    "body": text[:20000],
                    "source_provider": row.get("source_provider") or "fmp",
                    "metadata": {"kind": "press_release"},
                }
            )
            written += 1
            source = "fmp.press-releases"
            lowered = title.lower()
            if any(token in lowered for token in ("earning", "results", "outlook", "guidance")):
                for hit in extract_guidance_mentions(f"{title}. {text}")[:4]:
                    self.service.store.upsert_source_document(
                        {
                            "ticker": symbol,
                            "doc_type": "guidance",
                            "source_key": f"pr:{hit['quote'][:80]}",
                            "published_at": row.get("published_at"),
                            "title": title,
                            "url": row.get("url"),
                            "excerpt": hit["quote"],
                            "body": hit["quote"],
                            "source_provider": row.get("source_provider") or "fmp",
                            "metadata": {"kind": "guidance", "move": hit.get("move")},
                        }
                    )
        news = self._overlay(symbol, "news") or []
        if news:
            self._ingest(symbol, news=news, source="news")
            written += len(news)
            source = (source + "+news") if source else "news"
        else:
            database = getattr(self.service.store, "database", None)
            if database is not None:
                try:
                    rows = database.fetch_all(
                        "SELECT url FROM news_articles WHERE symbol = %s LIMIT 20",
                        (symbol.upper(),),
                    ) or []
                except Exception:
                    rows = []
                if rows:
                    written += len(rows)
                    source = (source + "+news") if source else "news_articles"
        docs = 0
        if hasattr(self.service.store, "list_source_documents"):
            docs = len(self.service.store.list_source_documents(symbol) or [])
            written += docs
        if written:
            status = "success"
        else:
            status = "partial"
        return {
            "status": status,
            "records_found": written,
            "source": source,
            "error": None if written else "no_press_or_news",
        }

    def _rebuild(self, symbol: str, workflow_run_id: str | None) -> dict[str, Any]:
        pack = self.service.build_pack(symbol, workflow_run_id=workflow_run_id)
        missing = list(pack.get("missing_fields") or [])
        status = "success" if not (set(missing) & KEY_MISSING) else "partial"
        return {
            "status": status,
            "records_found": len(pack.get("earnings_history") or []),
            "source": "research_packs",
            "error": ",".join(missing[:8]) if status != "success" else None,
        }

    def _remember(self, symbol: str, kind: str, value: Any) -> None:
        store = self.service.store
        bucket = getattr(store, f"raw_{kind}", None)
        if isinstance(bucket, dict):
            bucket[symbol.upper()] = value

    def _overlay(self, symbol: str, kind: str) -> Any:
        bucket = getattr(self.service.store, f"raw_{kind}", None)
        if isinstance(bucket, dict):
            return bucket.get(symbol.upper())
        return None

    def _overlay_map(self, kind: str) -> dict[str, Any] | None:
        bucket = getattr(self.service.store, f"raw_{kind}", None)
        return bucket if isinstance(bucket, dict) else None

    def _persist_bundle(self, symbol: str, earnings: list[dict[str, Any]], bundle: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "source": str(bundle.get("source") or "research_backfill"),
            "captured_at": _now(),
        }
        if earnings:
            payload["earnings"] = earnings
        fundamentals = bundle.get("fundamentals")
        if fundamentals:
            payload["fundamentals"] = [fundamentals]
        news = list(bundle.get("news") or [])
        if news:
            payload["news"] = news
        self._ingest(symbol, **{k: v for k, v in payload.items() if k not in {"source", "captured_at"}}, source=payload["source"])

    def _persist_bars(self, symbol: str, bars: list[dict[str, Any]], *, source: str) -> None:
        database = getattr(self.service.store, "database", None)
        if database is None:
            return
        from stock_pm.persist_live import persist_daily_bars

        persist_daily_bars(database, symbol, bars, captured_at=_now(), source=source)

    def _ingest(self, symbol: str, *, source: str, earnings: list | None = None, fundamentals: list | None = None, news: list | None = None) -> None:
        del symbol
        database = getattr(self.service.store, "database", None)
        if database is None:
            return
        payload: dict[str, Any] = {"source": source, "captured_at": _now()}
        if earnings:
            payload["earnings"] = earnings
        if fundamentals:
            payload["fundamentals"] = fundamentals
        if news:
            payload["news"] = news
        if len(payload) == 2:
            return
        database.ingest(payload)


def _pending_step() -> dict[str, Any]:
    return {
        "status": "pending",
        "records_found": 0,
        "source": None,
        "last_attempt_at": None,
        "error": None,
    }


def _step_result(status: str, *, records_found: int = 0, source: str | None = None, error: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "records_found": records_found,
        "source": source,
        "last_attempt_at": _now(),
        "error": error,
    }


def _overall(steps: dict[str, Any], *, interrupted: bool = False) -> str:
    statuses = [str((steps.get(name) or {}).get("status") or "pending") for name in STEP_NAMES]
    if interrupted and any(item == "failed" for item in statuses):
        return "failed" if all(item in {"failed", "pending"} for item in statuses) else "partial"
    if all(item == "success" for item in statuses):
        return "success"
    if all(item in {"failed", "pending"} for item in statuses):
        return "failed"
    if any(item in {"failed", "partial", "pending", "running"} for item in statuses):
        return "partial"
    return "success"


def _digits(value: Any) -> str | None:
    text = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not text:
        return None
    return text.zfill(10)


def _sector_hint(profile: dict[str, Any], sec: dict[str, Any]) -> str | None:
    industry = str(profile.get("industry") or "")
    sector = str(profile.get("sector") or "")
    sic = str(sec.get("sic_description") or "")
    text = f"{industry} {sector} {sic}".lower()
    if "semiconductor" in text or "电子" in text:
        return sector or industry or None
    if "energy" in text or "oil" in text or "gas" in text:
        return sector or "Energy"
    return sector or industry or None


def _earnings_from_store(service: Any, symbol: str) -> list[dict[str, Any]]:
    store = service.store
    database = getattr(store, "database", None)
    if database is None:
        return []
    try:
        return list(
            database.fetch_all(
                """
                SELECT report_date, fiscal_period, fiscal_year, period_end
                FROM earnings_reports
                WHERE symbol = %s
                ORDER BY report_date DESC
                LIMIT 8
                """,
                (symbol.upper(),),
            )
            or []
        )
    except Exception:
        return []
