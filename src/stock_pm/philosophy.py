"""Slice A / P0: auto-loop philosophy, quote honesty, environment half-sentence.

This module is pure (no database). Callers assemble EnvironmentSnapshot,
severity alerts, and explicit_state without inventing Prediction boundaries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .analytics import _number, pick_outlook_bias
from .environment import (
    causal_one_liner,
    flag_labels,
    news_stance,
    tape_stance,
)
from .prediction import (
    has_real_bounds,
    prediction_badge,
)
from .ux_copy import named_missing_labels

EXPLICIT_STATES = ("face_slap", "overdue", "missing", "clear")
EXPLICIT_STATE_PRIORITY = {
    "face_slap": 0,
    "overdue": 1,
    "missing": 2,
    "clear": 3,
}
EXPLICIT_STATE_LABELS = {
    "face_slap": "打脸待核验",
    "overdue": "产出逾期",
    "missing": "数据暂缺",
    "clear": "状态明确",
}
QUOTE_STATUSES = ("ok", "delayed", "stale", "missing", "bad")
PUBLISH_STATES = ("published", "draft", "stale", "missing")


def _truthy_delayed(value: Any) -> bool:
    if value in (True, 1, "1", "true", "True", "yes"):
        return True
    if value in (False, 0, "0", "false", "False", None, ""):
        return False
    return bool(value)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        stamp = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def quote_quality(snapshot: dict | None, review: dict | None = None, now: datetime | None = None) -> dict:
    """Classify a quote and pick the price that may appear in a conclusion."""
    snap = snapshot or {}
    review = review or {}
    now = now or datetime.now(timezone.utc)
    last_price = _number(snap.get("last_price") or snap.get("price") or snap.get("close_price"))
    prior_close = _number(snap.get("prior_close") or snap.get("previous_close"))
    review_close = _number(review.get("close_price"))
    source = str(snap.get("source") or snap.get("data_source") or "")
    delayed = _truthy_delayed(snap.get("delayed")) or "delayed" in source.lower() or "_iex" in source.lower()
    captured = _parse_ts(snap.get("captured_at") or snap.get("as_of") or snap.get("updated_at"))
    age_hours = None
    if captured is not None:
        age_hours = (now - captured).total_seconds() / 3600

    status = "ok"
    reason = "可用"
    if last_price is None and prior_close is None and review_close is None:
        status = "missing"
        reason = "没有可用报价或收盘价"
    elif last_price is not None and last_price <= 0:
        status = "bad"
        reason = "报价无效"
    elif (
        last_price is not None
        and prior_close is not None
        and prior_close > 0
        and abs(last_price / prior_close - 1) > 0.45
    ):
        status = "bad"
        reason = "现价相对昨收偏离过大，不作为结论价"
    elif age_hours is not None and age_hours > 36:
        status = "stale"
        reason = "报价过期"
    elif delayed:
        status = "delayed"
        reason = "延迟行情，结论价优先用收盘"

    conclusion_price = None
    conclusion_source = "missing"
    if review_close is not None:
        conclusion_price = review_close
        conclusion_source = "review_close"
    elif prior_close is not None:
        conclusion_price = prior_close
        conclusion_source = "prior_close"
    elif status in {"ok", "delayed"} and last_price is not None:
        conclusion_price = last_price
        conclusion_source = "last_price"

    usable = conclusion_price is not None
    labels = {
        "ok": "报价可用",
        "delayed": "延迟行情",
        "stale": "报价过期",
        "missing": "数据暂缺",
        "bad": "报价不可用",
    }
    return {
        "status": status,
        "label": labels[status],
        "reason": reason,
        "delayed": delayed or status == "delayed",
        "usable_for_conclusion": usable,
        "hide_last_price": status in {"bad", "missing"},
        "last_price": None if status in {"bad", "missing"} else last_price,
        "prior_close": prior_close,
        "review_close": review_close,
        "conclusion_price": conclusion_price if usable else None,
        "conclusion_source": conclusion_source if usable else "missing",
        "source": source or None,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
    }


def impact_row_thesis(mapped: dict | None) -> str | None:
    """One causal sentence instead of direction chips in two columns."""
    if not mapped:
        return None
    narrative = (mapped.get("narrative") or mapped.get("name") or "").strip()
    if not narrative:
        return None
    bits: list[str] = []
    for impact in mapped.get("impacts") or []:
        direction = impact.get("direction") or ""
        theme = impact.get("theme_name") or impact.get("theme") or ""
        symbols = [str(item) for item in (impact.get("symbols") or [])[:4]]
        if not direction or not theme:
            continue
        held = f"（{'、'.join(symbols)}）" if symbols else ""
        bits.append(f"{direction}{theme}{held}")
    if bits:
        return f"{narrative}，因此{'；'.join(bits)}。"
    return f"{narrative}。"


def stock_row_thesis(row: dict | None) -> str:
    """Morning-scan sentence: 盘面 → 消息 → 因此. Not two pretty columns."""
    row = row or {}
    health = (row.get("health") or "").strip()
    breakout = (row.get("breakout_status") or "").strip()
    tape = (row.get("tape") or row.get("short_trend") or "").strip()
    context = row.get("context") or {}
    news = context.get("news") or []
    macro = context.get("macro") or []
    news_dirs = [
        str(impact.get("direction") or "")
        for item in news
        for impact in (item.get("impacts") or [])
    ]
    for event in macro:
        news_dirs.extend(
            str(impact.get("direction") or "") for impact in (event.get("impacts") or [])
        )
    headline = (news[0].get("headline") if news else None) or (
        (macro[0].get("row_thesis") or macro[0].get("narrative") or macro[0].get("name"))
        if macro
        else None
    )
    parts: list[str] = []
    if health:
        parts.append(health)
    if breakout and breakout not in parts:
        parts.append(breakout)
    elif tape and tape not in parts:
        parts.append(tape)
    tape_text = "，".join(parts) if parts else None
    stance_n = news_stance(news_dirs)
    news_text = None
    if headline:
        if stance_n == "bull":
            news_text = "偏多 · 可点新闻"
        elif stance_n == "bear":
            news_text = "偏空 · 可点新闻"
        elif stance_n == "mixed":
            news_text = "分歧 · 可点新闻"
        else:
            news_text = "暂未形成对该股的明确影响"
            stance_n = None
    return causal_one_liner(tape_text, news_text, tape_stance(health, breakout), stance_n)


def _options_clause(options: dict | None) -> tuple[str | None, bool]:
    if not options or options.get("status") == "missing":
        return None, True
    pc = _number(options.get("total_put_call"))
    if pc is None:
        return None, True
    if pc >= 1.0:
        tone = "认沽偏多，市场偏谨慎"
    elif pc <= 0.7:
        tone = "认购偏多，市场偏乐观"
    else:
        tone = "认沽认购大致均衡"
    return f"期权{tone}（Cboe 一家交易所 P/C {pc:.2f}）", False


def _macro_clause(impact: dict | None) -> tuple[str | None, bool]:
    macros = (impact or {}).get("macro") or []
    if not macros:
        return None, True
    first = macros[0]
    thesis = first.get("row_thesis") or impact_row_thesis(first)
    return thesis, False


def _tape_clause(rows: list[dict]) -> tuple[str | None, bool]:
    if not rows:
        return None, True
    broken = sum(1 for row in rows if (row.get("health") or "") == "走坏")
    hot = sum(1 for row in rows if (row.get("health") or "") == "过热")
    healthy = sum(1 for row in rows if (row.get("health") or "") == "趋势健康")
    return (
        f"自选{len(rows)}只里{healthy}只趋势健康、{broken}只走坏、{hot}只过热",
        False,
    )


def synthesize_environment(
    *,
    as_of_date: str | None,
    briefing_rows: list[dict] | None = None,
    options: dict | None = None,
    impact: dict | None = None,
    symbol: str | None = None,
    session: dict | None = None,
) -> dict:
    """First-cut EnvironmentSnapshot: one-liner + struct + missingFlags + publishState."""
    rows = list(briefing_rows or [])
    if symbol:
        rows = [row for row in rows if str(row.get("symbol") or "").upper() == symbol.upper()]
    missing: list[str] = []
    option_text, option_missing = _options_clause(options)
    if option_missing:
        missing.append("options")
    macro_text, macro_missing = _macro_clause(impact)
    if macro_missing:
        missing.append("macro")
    tape_text, tape_missing = _tape_clause(rows)
    if tape_missing:
        missing.append("reviews")

    if session and session.get("is_trading_day") is False:
        label = session.get("label") or "美股休市"
        one_liner = f"{as_of_date or ''} {label}，今日休市，沿用最近交易日环境作为背景。".strip()
        publish_state = "stale"
    elif tape_missing and macro_missing:
        one_liner = causal_one_liner(None, None, None, None)
        publish_state = "missing"
    else:
        healthy = sum(1 for row in rows if (row.get("health") or "") == "趋势健康")
        broken = sum(1 for row in rows if (row.get("health") or "") == "走坏")
        market_tape = "bear" if broken > healthy else "bull" if healthy > broken else tape_stance(
            (rows[0].get("health") if rows else None)
        )
        macro_dirs = [
            str(impact.get("direction") or "")
            for event in (impact or {}).get("macro") or []
            for impact in (event.get("impacts") or [])
        ]
        one_liner = causal_one_liner(
            tape_text,
            macro_text,
            None if tape_missing else market_tape,
            None if macro_missing else news_stance(macro_dirs),
            missing_note=flag_labels(missing) if len(missing) >= 2 else None,
        )
        publish_state = "draft" if len(missing) >= 2 else "published"

    row_thesis = one_liner
    if symbol and rows:
        row_thesis = stock_row_thesis(rows[0])

    struct = {
        "options": None if option_missing else {
            "trade_date": (options or {}).get("trade_date"),
            "total_put_call": (options or {}).get("total_put_call"),
            "clause": option_text,
        },
        "macro": None if macro_missing else {
            "name": ((impact or {}).get("macro") or [{}])[0].get("name"),
            "clause": macro_text,
        },
        "tape": None if tape_missing else {
            "symbols": len(rows),
            "clause": tape_text,
        },
        "session": session or None,
    }
    return {
        "as_of_date": as_of_date,
        "scope": "symbol" if symbol else "market",
        "symbol": symbol.upper() if symbol else None,
        "one_liner": one_liner,
        "row_thesis": row_thesis,
        "struct": struct,
        "missingFlags": missing,
        "publishState": publish_state,
        "prediction_ready": False,
    }


def pick_explicit_state(candidates: list[str]) -> str:
    ranked = [code for code in candidates if code in EXPLICIT_STATE_PRIORITY]
    if not ranked:
        return "clear"
    return min(ranked, key=lambda code: EXPLICIT_STATE_PRIORITY[code])


def derive_explicit_state(
    *,
    briefing: dict | None = None,
    environment: dict | None = None,
    sync: dict | None = None,
    now: datetime | None = None,
    predictions: list[dict] | None = None,
) -> dict:
    """Priority: face-slap > overdue > missing. Real Prediction bounds only."""
    briefing = briefing or {}
    environment = environment or {}
    rows = briefing.get("rows") or []
    session = briefing.get("session") or {}
    now = now or datetime.now(timezone.utc)
    candidates: list[str] = []
    details: list[str] = []
    pred_rows = list(predictions or [])
    if not pred_rows:
        pred_rows = [
            row.get("prediction")
            for row in rows
            if row.get("prediction")
        ]

    slap_preds = [
        pred
        for pred in pred_rows
        if pred and pred.get("state") == "invalidated" and has_real_bounds(pred)
    ]
    overdue_preds = [
        pred
        for pred in pred_rows
        if pred and (pred.get("state") == "missing" or not has_real_bounds(pred))
    ]
    ready = any(has_real_bounds(pred) for pred in pred_rows)

    if slap_preds:
        symbols = "、".join(str(pred.get("symbol") or "") for pred in slap_preds[:4])
        candidates.append("face_slap")
        details.append(
            f"预测被打脸：{symbols}。{prediction_badge(slap_preds[0])}。"
            "请判断是否改口（留痕），小噪声不自动改口。"
        )

    completed = _parse_ts((sync or {}).get("completed_at"))
    stale_sync = completed is not None and (now - completed).total_seconds() > 36 * 3600
    trading = session.get("is_trading_day") is not False
    reviews_missing = trading and not briefing.get("has_reviews")
    due_missing = trading and overdue_preds and not slap_preds
    if stale_sync or reviews_missing or due_missing:
        candidates.append("overdue")
        if due_missing:
            details.append("到期未产出或依据不足，暂不形成可验证预测。")
        if reviews_missing:
            details.append("交易日复盘尚未生成。")
        if stale_sync:
            details.append("行情同步超过 36 小时。")

    missing_flags = list(environment.get("missingFlags") or [])
    publish = environment.get("publishState")
    if publish in {"missing", "draft"} or missing_flags:
        candidates.append("missing")
        if missing_flags:
            shown = "、".join(named_missing_labels(missing_flags))
            details.append(f"数据暂缺：{shown}。")

    code = pick_explicit_state(candidates)
    if code == "clear":
        details = ["没有更高优先级的打脸、逾期或缺失。"]
    return {
        "code": code,
        "label": EXPLICIT_STATE_LABELS[code],
        "priority": EXPLICIT_STATE_PRIORITY[code],
        "detail": " ".join(details),
        "prediction_ready": ready,
        "face_slap_symbols": [pred.get("symbol") for pred in slap_preds],
    }


def derive_severity_alerts(
    *,
    briefing: dict | None = None,
    snapshots: list[dict] | None = None,
    explicit_state: dict | None = None,
) -> list[dict]:
    """Severe alerts only. Empty list means the strip stays hidden."""
    alerts: list[dict] = []
    rows = (briefing or {}).get("rows") or []
    if any((row.get("llm_status") or "") == "quota_exhausted" for row in rows):
        alerts.append(
            {
                "alert_key": "llm_quota",
                "severity": "severe",
                "title": "模型额度已用尽",
                "message": "解释与明日看法暂停生成。充值后刷新即可自动补写，不需要每日确认。",
                "symbol": None,
            }
        )
    for snap in snapshots or []:
        if snap.get("halted"):
            alerts.append(
                {
                    "alert_key": f"halted:{snap.get('symbol')}",
                    "severity": "severe",
                    "title": f"{snap.get('symbol')} 停牌",
                    "message": "该标的报价已停，结论区不展示现价。",
                    "symbol": snap.get("symbol"),
                }
            )
        quality = snap.get("quote_quality") or {}
        if quality.get("status") == "bad":
            alerts.append(
                {
                    "alert_key": f"bad_quote:{snap.get('symbol')}",
                    "severity": "severe",
                    "title": f"{snap.get('symbol')} 报价不可用",
                    "message": quality.get("reason") or "现价已隐藏。",
                    "symbol": snap.get("symbol"),
                }
            )
    state = explicit_state or {}
    if state.get("code") == "face_slap":
        ready = bool(state.get("prediction_ready"))
        alerts.append(
            {
                "alert_key": "face_slap",
                "severity": "severe",
                "title": "打脸待核验",
                "message": state.get("detail") or "预测边界被打破。",
                "symbol": None,
                "cta": "judgment_change" if ready else None,
                "legacy": not ready,
            }
        )
    return alerts


def enrich_briefing_row(row: dict, snapshot: dict | None = None) -> dict:
    """Attach quote_quality, conclusion price, row_thesis, and active auto bias."""
    enriched = dict(row)
    quality = quote_quality(snapshot, row)
    bias, bias_source = pick_outlook_bias(row)
    enriched["quote_quality"] = quality
    enriched["conclusion_price"] = quality.get("conclusion_price")
    enriched["conclusion_price_source"] = quality.get("conclusion_source")
    enriched["row_thesis"] = stock_row_thesis(row)
    enriched["active_bias"] = bias
    enriched["active_bias_source"] = bias_source
    enriched["confirm_required"] = False
    return enriched


def build_shell(
    *,
    briefing: dict,
    options: dict | None = None,
    snapshots: list[dict] | None = None,
    impact: dict | None = None,
    sync: dict | None = None,
    symbol: str | None = None,
    symbol_environment: dict | None = None,
    predictions: list[dict] | None = None,
) -> dict:
    env = symbol_environment or synthesize_environment(
        as_of_date=briefing.get("date"),
        briefing_rows=briefing.get("rows") or [],
        options=options,
        impact=impact,
        symbol=symbol,
        session=briefing.get("session"),
    )
    state = derive_explicit_state(
        briefing=briefing, environment=env, sync=sync, predictions=predictions
    )
    alerts = derive_severity_alerts(
        briefing=briefing, snapshots=snapshots, explicit_state=state
    )
    return {
        "as_of": briefing.get("date"),
        "explicit_state": state,
        "alerts": alerts,
        "environment": env,
        "quote_quality": {
            row.get("symbol"): row.get("quote_quality")
            for row in briefing.get("rows") or []
            if row.get("symbol")
        },
    }
