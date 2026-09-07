from datetime import datetime, timedelta, timezone

from stock_pm.review import analyze_bars, generate_review, retry_reviews_for_llm


def _bars(latest_close: float = 125, latest_volume: float = 3_000_000) -> list[dict]:
    start = datetime(2026, 9, 4, tzinfo=timezone.utc)
    rows = []
    for index in range(80):
        close = latest_close if index == 0 else 100 + (79 - index) * 0.25
        rows.append(
            {
                "bar_time": start - timedelta(days=index),
                "open_price": close - 0.5,
                "high_price": close + 1,
                "low_price": close - 1,
                "close_price": close,
                "volume": latest_volume if index == 0 else 1_000_000,
            }
        )
    return rows


def test_breakout_requires_close_and_volume_confirmation() -> None:
    result = analyze_bars(_bars())
    assert result["breakout"] == "放量有效突破"
    assert result["relative_volume"] == 3
    assert result["support"] < result["close"]


def test_volume_profile_and_flow_are_exposed() -> None:
    result = analyze_bars(_bars(latest_close=118, latest_volume=800_000))
    assert result["poc_60d"] is not None
    assert result["value_area_low"] <= result["value_area_high"]
    assert 0 <= result["volume_below_price_pct"] <= 100
    assert result["flow"]


class _StubDatabase:
    def __init__(self) -> None:
        self.saved = None
        self.articles = [{"headline": "Fed signals rate cut", "summary": "", "themes": ["rates"]}]

    def fetch_all(self, query, params=()):
        if "daily_price_bars" in query:
            return _bars()
        return []

    def option_wall(self, symbol):
        return []

    def theme_symbols(self):
        return {}

    def news_on_date(self, symbol, date):
        return list(self.articles)

    def macro_events_between(self, start, end):
        return []

    def segments(self, symbol, date=None):
        return []

    def review_row(self, symbol, review_date):
        if self.saved and self.saved.get("symbol") == symbol:
            return self.saved
        return None

    def reviews_by_date(self, date):
        return [self.saved] if self.saved else []

    def latest_review_date(self):
        if not self.saved:
            return None
        return str(self.saved["review_date"])

    def store_event(self, event):
        return None

    def store_review(self, review):
        self.saved = review

    def fill_review_outcome(self, symbol, review_date, actual):
        self.outcome = (symbol, review_date, actual)


def test_generate_review_attaches_llm_and_rule_draft() -> None:
    database = _StubDatabase()
    review = generate_review(
        database,
        "AAPL",
        llm_fn=lambda context: {
            "llm_why": "放量突破叠加降息预期",
            "llm_outlook": "关注压力位",
            "llm_bias": "偏多",
            "llm_model": "test-model",
            "llm_status": "ok",
        },
    )
    assert review["llm_why"] == "放量突破叠加降息预期"
    assert review["rule_bias"] in {"偏多", "中性", "偏空"}
    assert review["llm_cached"] is False
    assert review["llm_context_hash"]
    assert database.saved["context"]["news"]
    assert database.outcome[0] == "AAPL"


def test_generate_review_reuses_llm_until_inputs_change() -> None:
    database = _StubDatabase()
    calls: list[dict] = []

    def llm_fn(context):
        calls.append(context)
        return {
            "llm_why": f"解释{len(calls)}",
            "llm_outlook": "关注压力位",
            "llm_bias": "偏多",
            "llm_model": "test-model",
            "llm_status": "ok",
        }

    first = generate_review(database, "AAPL", llm_fn=llm_fn)
    second = generate_review(database, "AAPL", llm_fn=llm_fn)
    assert len(calls) == 1
    assert second["llm_cached"] is True
    assert second["llm_why"] == first["llm_why"] == "解释1"

    database.articles = [{"headline": "Company raises guidance", "summary": "", "themes": []}]
    third = generate_review(database, "AAPL", llm_fn=llm_fn)
    assert len(calls) == 2
    assert third["llm_cached"] is False
    assert third["llm_why"] == "解释2"

    forced = generate_review(database, "AAPL", llm_fn=llm_fn, force_llm=True)
    assert len(calls) == 3
    assert forced["llm_cached"] is False


def test_retry_reviews_after_quota_exhausted() -> None:
    database = _StubDatabase()
    generate_review(
        database,
        "AAPL",
        llm_fn=lambda context: {
            "llm_why": None,
            "llm_outlook": None,
            "llm_bias": None,
            "llm_model": "test-model",
            "llm_status": "quota_exhausted",
            "llm_error": "模型额度已用尽，请充值后刷新本页，将自动重新生成解释与明日看法。",
        },
    )
    assert database.saved["llm_status"] == "quota_exhausted"

    def recovered(context):
        return {
            "llm_why": "充值后重试成功",
            "llm_outlook": "观察压力位",
            "llm_bias": "偏多",
            "llm_model": "test-model",
            "llm_status": "ok",
        }

    result = retry_reviews_for_llm(database, "2026-09-04", llm_fn=recovered)
    assert result["ok"] == 1
    assert result["quota_exhausted"] is False
    assert database.saved["llm_why"] == "充值后重试成功"
    assert database.saved["llm_error"] is None


def test_retry_reviews_skips_closed_market() -> None:
    database = _StubDatabase()
    database.saved = {
        "symbol": "AAPL",
        "review_date": "2026-09-07",
        "llm_status": "quota_exhausted",
    }
    calls = []
    result = retry_reviews_for_llm(
        database,
        "2026-09-07",
        llm_fn=lambda context: calls.append(context) or {"llm_status": "ok"},
    )
    assert result["skipped"] == "market_closed"
    assert result["retried"] == []
    assert calls == []
