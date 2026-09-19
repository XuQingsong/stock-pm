from pathlib import Path

from stock_pm.prediction import synthesize_prediction
from stock_pm.ux_copy import (
    BANNED_ON_SCREEN,
    attention_rank,
    decorate_news_item,
    env_half_display,
    featured_and_rest,
    named_missing_line,
    news_stance_line,
    sort_attention_rows,
    ui_copy_violations,
)


UI_FILES = [
    Path("src/stock_pm/static/overview.html"),
    Path("src/stock_pm/static/review.html"),
    Path("src/stock_pm/static/stock.js"),
    Path("src/stock_pm/static/shell.js"),
    Path("src/stock_pm/static/desk.js"),
    Path("src/stock_pm/static/market.html"),
    Path("src/stock_pm/static/market.js"),
]


def test_named_missing_never_bare_queshu() -> None:
    line = named_missing_line(["window", "support", "price"])
    assert "缺时间窗" in line
    assert "缺下沿" in line
    assert "缺对照行情" in line
    assert "缺数，" not in line
    assert line != "缺数"
    assert "未编造" not in line
    assert "不计入预测准确率" in line


def test_news_clickable_or_marks_missing_url() -> None:
    linked = decorate_news_item(
        {
            "headline": "芯片缺货",
            "url": "https://example.com/story",
            "impacts": [{"direction": "利多", "theme_name": "半导体", "rationale": "供给偏紧"}],
        }
    )
    assert linked["has_url"] is True
    assert linked["url"] == "https://example.com/story"
    assert linked["stance_line"] == "利好 · 因为供给偏紧"

    bare = decorate_news_item(
        {
            "headline": "无链标题",
            "url": "javascript:alert(1)",
            "impacts": [
                {"direction": "利空", "theme_name": "估值", "rationale": "利率预期上行"}
            ],
        }
    )
    assert bare["has_url"] is False
    assert bare["url"] is None
    assert bare["url_label"] == "无原文链接"
    assert news_stance_line(bare).startswith("利空 · 因为")


def test_env_half_drops_english_headlines() -> None:
    env = {
        "one_liner": (
            "盘面：走坏；消息：行业利多（Profits surge to record high）；"
            "因此：盘面与消息反向，先以收盘盘面为准，不当成两套并列结论。"
        ),
        "struct": {
            "news": {
                "sector": {
                    "bias": "利多",
                    "headline": "Profits surge to record high",
                    "url": "https://example.com/a",
                    "clause": "行业偏利多：Profits surge to record high",
                }
            }
        },
    }
    half = env_half_display(env)
    assert "Profits surge" not in half
    assert "行业利多" in half
    assert "可点新闻" in half
    assert "盘面" in half and "因此" in half


def test_attention_orders_alerts_conflict_then_rest() -> None:
    rows = [
        {"symbol": "QQQ", "prediction": {"state": "active", "prediction_ready": True}},
        {
            "symbol": "NVDA",
            "prediction": {
                "state": "invalidated",
                "prediction_ready": True,
                "judgment_alert": {"id": 11, "severity": "severe"},
            },
        },
        {
            "symbol": "INTC",
            "env_tape_conflict": True,
            "prediction": {"state": "active", "prediction_ready": True},
        },
        {
            "symbol": "MU",
            "tape_analysis": {"weak_vs_env": {"status": "weak"}},
            "prediction": {"state": "active", "prediction_ready": True},
        },
        {
            "symbol": "AAPL",
            "prediction": {
                "state": "missing",
                "prediction_ready": False,
                "missingFlags": ["window", "support"],
            },
        },
    ]
    ordered = sort_attention_rows(rows)
    assert [row["symbol"] for row in ordered] == ["NVDA", "AAPL", "INTC", "MU", "QQQ"]
    featured, rest = featured_and_rest(rows)
    assert [row["symbol"] for row in featured] == ["NVDA", "AAPL", "INTC", "MU"]
    assert [row["symbol"] for row in rest] == ["QQQ"]
    legacy_miss = attention_rank(
        {
            "symbol": "AMD",
            "prior_outcome": {"outcome_vs_bias": "相反", "bias": "偏多"},
            "prediction": {"state": "active", "prediction_ready": True},
        }
    )
    assert legacy_miss["key"] != "face_slap"


def test_main_ui_path_bans_engineering_jargon() -> None:
    for path in UI_FILES:
        text = path.read_text(encoding="utf-8")
        hits = ui_copy_violations(text)
        assert hits == [], f"{path}: {hits}"
        assert "缺数" not in text or "缺数点名" in text
    overview = Path("src/stock_pm/static/overview.html").read_text(encoding="utf-8")
    review = Path("src/stock_pm/static/review.html").read_text(encoding="utf-8")
    stock = Path("src/stock_pm/static/stock.js").read_text(encoding="utf-8")
    shell = Path("src/stock_pm/static/shell.js").read_text(encoding="utf-8")
    assert "无原文链接" in overview and "无原文链接" in review and "无原文链接" in stock
    assert "须严重提醒后改口并写原因" in shell
    assert "因此：" in shell
    assert "依据↑环境/昨盘" in shell
    assert "其余" in overview and "其余" in review
    for phrase in BANNED_ON_SCREEN:
        assert phrase not in overview
        assert phrase not in review


def test_quality_gate_names_missing_inputs() -> None:
    pred = synthesize_prediction(
        as_of_date="2026-09-04",
        symbol="INTC",
        environment={"publishState": "missing", "one_liner": None},
        tape={"publishState": "missing", "volume_price": None, "chips": {}},
        review_note={"unexplained": True},
        entry_price=None,
    )
    assert pred["state"] == "missing"
    assert "缺数" not in (pred["missing_label"] or "")
    assert "缺" in pred["missing_label"]
    assert "昨盘" in pred["missing_label"] or "环境" in pred["missing_label"]
