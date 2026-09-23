from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from stock_pm.calendar import NY_TZ, is_early_close
from stock_pm.events.types import EventDocument
from stock_pm.news.adapters import (
    from_alpha_vantage_item,
    from_discovery_document,
    from_nasdaq_row,
    from_official_document,
    from_sec_document,
)
from stock_pm.news.dedupe import dedupe_articles
from stock_pm.news.health import DEFAULT_POLICIES, cursor_row, evaluate_health, health_from_cursor
from stock_pm.news.timeutil import market_session, normalize_published, reaction_date, session_fields

UTC = timezone.utc
FETCHED = datetime(2026, 9, 22, 21, 0, tzinfo=UTC)


def et(*args: int) -> datetime:
    return datetime(*args, tzinfo=NY_TZ)


# --- time normalization -----------------------------------------------------


def test_rfc2822_gmt_is_explicit_second_precision():
    parsed = normalize_published("Thu, 10 Sep 2026 20:00:00 GMT")
    assert parsed.iso == "2026-09-10T20:00:00+00:00"
    assert (parsed.precision, parsed.tz_basis) == ("second", "explicit")
    assert parsed.local_date == date(2026, 9, 10)


def test_rfc2822_named_zone_is_honoured():
    parsed = normalize_published("Tue, 7 Jul 2026 12:00:00 EST")
    assert parsed.iso == "2026-07-07T17:00:00+00:00"
    assert parsed.tz_explicit


def test_rfc2822_minus_zero_means_unknown_zone():
    parsed = normalize_published("Tue, 7 Jul 2026 12:00:00 -0000")
    assert parsed.tz_basis == "assumed:America/New_York"


def test_iso_with_offset_keeps_instant_and_et_date():
    parsed = normalize_published("2026-09-11T23:29:31-04:00")
    assert parsed.iso == "2026-09-12T03:29:31+00:00"
    assert parsed.local_date == date(2026, 9, 11)
    assert parsed.precision == "second"


def test_iso_without_seconds_is_minute_precision():
    assert normalize_published("2026-09-11T17:29-04:00").precision == "minute"


def test_alpha_vantage_compact_is_flagged_as_assumed_zone():
    parsed = normalize_published("20260916T183000", naive_tz="UTC")
    assert parsed.iso == "2026-09-16T18:30:00+00:00"
    assert (parsed.precision, parsed.tz_basis) == ("second", "assumed:UTC")
    assert normalize_published("20260916T1830", naive_tz="UTC").precision == "minute"


@pytest.mark.parametrize("raw", ["Sep 22, 2026", "2026-09-22", "09/22/2026"])
def test_date_only_keeps_et_calendar_date(raw):
    parsed = normalize_published(raw)
    assert parsed.precision == "day"
    assert parsed.tz_basis == "date_only"
    assert parsed.local_date == date(2026, 9, 22)
    assert parsed.utc.astimezone(NY_TZ).date() == date(2026, 9, 22)
    assert session_fields(parsed) == {"session": "unknown", "reaction_date": None}


@pytest.mark.parametrize("raw", ["3 hours ago", "yesterday", "", None, "not a date"])
def test_relative_or_garbage_is_refused(raw):
    parsed = normalize_published(raw)
    assert parsed.utc is None
    assert parsed.tz_basis == "unparsed"


# --- sessions ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("stamp", "session"),
    [
        (et(2026, 9, 22, 3, 59), "overnight"),
        (et(2026, 9, 22, 4, 0), "premarket"),
        (et(2026, 9, 22, 9, 29), "premarket"),
        (et(2026, 9, 22, 9, 30), "regular"),
        (et(2026, 9, 22, 15, 59), "regular"),
        (et(2026, 9, 22, 16, 0), "after_hours"),
        (et(2026, 9, 22, 20, 0), "overnight"),
        (et(2026, 9, 19, 12, 0), "closed"),
        (et(2026, 9, 7, 12, 0), "closed"),
    ],
)
def test_market_session(stamp, session):
    assert market_session(stamp) == session


def test_early_close_day_shifts_session_bounds():
    assert market_session(et(2026, 11, 27, 12, 59)) == "regular"
    assert market_session(et(2026, 11, 27, 13, 0)) == "after_hours"
    assert market_session(et(2026, 11, 27, 17, 0)) == "overnight"


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2025, 7, 3), True),
        (date(2026, 7, 2), False),
        (date(2026, 7, 3), False),
        (date(2026, 11, 27), True),
        (date(2026, 12, 24), True),
        (date(2027, 12, 24), False),
        (date(2026, 9, 22), False),
    ],
)
def test_is_early_close(day, expected):
    assert is_early_close(day) is expected


def test_reaction_date_rolls_after_close_and_over_weekends():
    assert reaction_date(et(2026, 9, 22, 8, 0)) == date(2026, 9, 22)
    assert reaction_date(et(2026, 9, 22, 15, 0)) == date(2026, 9, 22)
    assert reaction_date(et(2026, 9, 25, 16, 5)) == date(2026, 9, 28)
    assert reaction_date(et(2026, 9, 26, 10, 0)) == date(2026, 9, 28)
    assert reaction_date(et(2026, 11, 25, 18, 0)) == date(2026, 11, 27)


# --- adapters ---------------------------------------------------------------


NASDAQ_ROW = {
    "title": "Nvidia Supplier Raises Guidance Ahead of Blackwell Ramp",
    "description": "Shares moved after the update.",
    "publisher": "Zacks",
    "created": "Sep 22, 2026",
    "ago": "5 hours ago",
    "url": "/articles/nvidia-supplier-raises-guidance",
    "related_symbols": ["nvda|stocks", "tsm|stocks"],
}

AV_ITEM = {
    "title": "Nvidia Supplier Raises Guidance Ahead of Blackwell Ramp",
    "url": "https://www.benzinga.com/news/26/09/nvidia-supplier?utm_source=av",
    "time_published": "20260922T123000",
    "authors": ["Jane Doe"],
    "summary": "Guidance raised.",
    "source": "Benzinga",
    "source_domain": "www.benzinga.com",
    "topics": [{"topic": "Earnings", "relevance_score": "0.9"}],
    "ticker_sentiment": [
        {"ticker": "NVDA", "relevance_score": "0.8", "ticker_sentiment_score": "0.3", "ticker_sentiment_label": "Bullish"},
        {"ticker": "tsm", "relevance_score": "0.4", "ticker_sentiment_score": "0.1", "ticker_sentiment_label": "Neutral"},
    ],
}


def _sec_doc(**overrides) -> EventDocument:
    base = dict(
        title="8-K - APPLE INC (0000320193) (Filer)",
        url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/0000320193-26-000123-index.htm",
        publisher="SEC EDGAR",
        published_at="2026-09-11T21:29:31+00:00",
        event_type="company_filing",
        entities=["AAPL", "0000320193", "0000320193-26-000123", "APPLE INC"],
        body="Filed: 2026-09-11 AccNo: 0000320193-26-000123",
        filing_items=["Item 2.02: Results of Operations and Financial Condition", "Item 9.01: Financial Statements and Exhibits"],
        last_fetched_at="2026-09-11T21:35:00+00:00",
    )
    base.update(overrides)
    return EventDocument(**base)


def test_nasdaq_adapter_reports_date_only_and_missing_id():
    article = from_nasdaq_row(NASDAQ_ROW, symbol="nvda", fetched_at=FETCHED)
    assert article.url == "https://www.nasdaq.com/articles/nvidia-supplier-raises-guidance"
    assert article.vendor_tickers == ["NVDA", "TSM"]
    assert article.published.local_date == date(2026, 9, 22)
    assert article.session == "unknown"
    gaps = article.missing_fields()
    assert "external_id" in gaps
    assert "published_at:time_of_day" in gaps
    assert "vendor_tickers" not in gaps


def test_nasdaq_ingest_keeps_et_date_and_vendor_row(monkeypatch):
    from stock_pm import fundamentals

    monkeypatch.setattr(fundamentals, "_get_json", lambda path: {"data": {"rows": [NASDAQ_ROW]}})
    [row] = fundamentals._news("NVDA")
    stamp = datetime.fromisoformat(row["published_at"])
    assert stamp.astimezone(NY_TZ).date() == date(2026, 9, 22)
    assert row["vendor_row"]["related_symbols"] == ["nvda|stocks", "tsm|stocks"]


def test_nasdaq_adapter_uses_vendor_id_when_present():
    article = from_nasdaq_row({**NASDAQ_ROW, "id": 991}, symbol="NVDA", fetched_at=FETCHED)
    assert (article.external_id, article.external_id_kind) == ("991", "vendor_id")


def test_alpha_vantage_adapter_keeps_ticker_metadata_and_flags_zone():
    article = from_alpha_vantage_item(AV_ITEM, fetched_at=FETCHED)
    assert article.vendor_tickers == ["NVDA", "TSM"]
    assert article.vendor_ticker_meta[0]["relevance_score"] == "0.8"
    assert article.vendor_topics == ["Earnings"]
    assert article.canonical_url == "https://benzinga.com/news/26/09/nvidia-supplier"
    assert article.session == "premarket"
    assert article.reaction_date == date(2026, 9, 22)
    gaps = article.missing_fields()
    assert "published_at:tz_assumed" in gaps
    assert "external_id" in gaps


def test_sec_adapter_extracts_form_items_accession_cik():
    article = from_sec_document(_sec_doc())
    assert article.sec_form == "8-K"
    assert article.sec_items == ["2.02", "9.01"]
    assert article.sec_accession == "0000320193-26-000123"
    assert article.sec_cik == "0000320193"
    assert article.vendor_tickers == ["AAPL"]
    assert (article.external_id, article.external_id_kind) == ("0000320193-26-000123", "sec_accession")
    assert article.session == "after_hours"
    assert article.reaction_date == date(2026, 9, 14)
    assert article.fetched_at == datetime(2026, 9, 11, 21, 35, tzinfo=UTC)
    assert article.missing_fields() == []


def test_sec_adapter_amendment_and_unmapped_filer():
    doc = _sec_doc(
        title="8-K/A - Fly-E Group, Inc. (0001975940) (Filer)",
        entities=["0001975940", "0001213900-26-099368", "Fly-E Group, Inc.", "UNMAPPED_FILER"],
        filing_items=[],
    )
    article = from_sec_document(doc)
    assert article.sec_form == "8-K/A"
    assert article.vendor_tickers == []
    assert article.native["unmapped_filer"] is True
    assert {"vendor_tickers", "sec_items"} <= set(article.missing_fields())


def test_official_rss_adapter_is_not_company_scoped():
    doc = EventDocument(
        title="Federal Reserve issues FOMC statement",
        url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm",
        publisher="Federal Reserve",
        published_at="2026-09-16T18:00:00+00:00",
        event_type="central_bank_rates",
    )
    article = from_official_document(doc, source="federal_reserve", fetched_at=FETCHED)
    assert article.session == "regular"
    gaps = article.missing_fields()
    assert "vendor_tickers" not in gaps
    assert "external_id:url_fallback" in gaps


def test_discovery_adapter_marks_day_precision():
    doc = {
        "provider": "tavily",
        "url": "https://www.reuters.com/technology/nvidia-2026-09-22/",
        "title": "Nvidia supplier update",
        "ticker": "NVDA",
        "published_at": "2026-09-22",
        "fetched_at": "2026-09-22T21:00:00+00:00",
        "source_domain": "reuters.com",
        "clean_text": "Body",
    }
    article = from_discovery_document(doc)
    assert article.source_kind == "discovery"
    assert article.published.precision == "day"
    assert article.fetched_at == FETCHED


# --- dedupe -----------------------------------------------------------------


def test_same_accession_from_current_and_company_feeds_merges():
    current = from_sec_document(_sec_doc(entities=["0000320193", "0000320193-26-000123"], filing_items=[]))
    company = from_sec_document(_sec_doc(url=_sec_doc().url.replace("-index.htm", "-index.html")))
    result = dedupe_articles([current, company])
    assert len(result.unique) == 1
    kept = result.unique[0]
    assert kept.vendor_tickers == ["AAPL"]
    assert kept.sec_items == ["2.02", "9.01"]
    assert result.dropped[0]["reason"] == "sec_accession"


def test_tracking_params_collapse_to_one_url():
    left = from_alpha_vantage_item(AV_ITEM, fetched_at=FETCHED)
    right = from_alpha_vantage_item({**AV_ITEM, "url": "https://benzinga.com/news/26/09/nvidia-supplier/"}, fetched_at=FETCHED)
    result = dedupe_articles([left, right])
    assert len(result.unique) == 1
    assert result.dropped[0]["reason"] == "canonical_url"


def test_syndicated_title_prefers_timed_vendor_feed_and_records_sources():
    nasdaq = from_nasdaq_row(NASDAQ_ROW, symbol="NVDA", fetched_at=FETCHED)
    av = from_alpha_vantage_item(AV_ITEM, fetched_at=FETCHED)
    result = dedupe_articles([nasdaq, av])
    assert len(result.unique) == 1
    kept = result.unique[0]
    assert kept.source == "alpha_vantage_news"
    assert kept.also_seen_in == ["nasdaq_news"]
    assert result.dropped[0]["reason"] == "title"


def test_short_or_official_titles_are_not_title_merged():
    short = {**NASDAQ_ROW, "title": "Stocks to watch"}
    a = from_nasdaq_row(short, symbol="NVDA", fetched_at=FETCHED)
    b = from_nasdaq_row({**short, "url": "/articles/other"}, symbol="NVDA", fetched_at=FETCHED)
    assert len(dedupe_articles([a, b]).unique) == 2

    first = from_sec_document(_sec_doc())
    second = from_sec_document(
        _sec_doc(
            url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000124/0000320193-26-000124-index.htm",
            entities=["AAPL", "0000320193", "0000320193-26-000124"],
        )
    )
    assert len(dedupe_articles([first, second]).unique) == 2


def test_title_match_respects_time_window():
    first = from_alpha_vantage_item(AV_ITEM, fetched_at=FETCHED)
    later = from_alpha_vantage_item(
        {**AV_ITEM, "url": "https://example.com/reprint", "time_published": "20260925T123000"}, fetched_at=FETCHED
    )
    assert len(dedupe_articles([first, later]).unique) == 2


# --- health -----------------------------------------------------------------

SEC = DEFAULT_POLICIES["sec_edgar"]
MARKET_NOW = et(2026, 9, 22, 11, 0).astimezone(UTC)


def _health(**kwargs):
    base = dict(
        configured=True,
        last_attempt=MARKET_NOW - timedelta(minutes=5),
        last_success=MARKET_NOW - timedelta(minutes=5),
        last_attempt_ok=True,
        newest_published=MARKET_NOW - timedelta(minutes=10),
        now=MARKET_NOW,
    )
    base.update(kwargs)
    return evaluate_health(SEC, **base)


def test_health_ok_during_filing_window():
    report = _health()
    assert (report["status"], report["reason_code"]) == ("ok", None)
    assert report["fetch_age_min"] == 5.0


def test_health_silent_when_fetch_ok_but_items_stop():
    report = _health(newest_published=MARKET_NOW - timedelta(hours=3))
    assert (report["status"], report["reason_code"]) == ("silent", "upstream_silent")


def test_health_stale_when_job_stops_running():
    report = _health(last_attempt=MARKET_NOW - timedelta(hours=2), last_success=MARKET_NOW - timedelta(hours=2))
    assert report["status"] == "stale"


def test_health_down_vs_degraded():
    assert _health(last_attempt_ok=False, last_success=MARKET_NOW - timedelta(hours=2))["status"] == "down"
    assert _health(last_attempt_ok=False)["status"] == "degraded"


def test_health_not_configured_and_weekend_idle():
    assert _health(configured=False)["reason_code"] == "source_not_configured"
    weekend = et(2026, 9, 19, 11, 0).astimezone(UTC)
    report = _health(now=weekend, newest_published=weekend - timedelta(days=1))
    assert report["status"] == "idle"


def test_cursor_row_round_trip():
    newest = MARKET_NOW - timedelta(minutes=10)
    row = cursor_row("sec_edgar", ok=True, reason_code=None, item_count=12, newest_published=newest, now=MARKET_NOW)
    assert row["provider"] == "news:sec_edgar"
    stored = {
        "last_attempt": row["stamp"],
        "last_success": row["stamp"],
        "status": row["status"],
        "cursor_json": row["cursor_json"],
    }
    report = health_from_cursor(stored, SEC, configured=True, now=MARKET_NOW + timedelta(minutes=1))
    assert report["status"] == "ok"
    assert report["newest_item_age_min"] == 11.0
