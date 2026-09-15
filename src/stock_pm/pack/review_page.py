"""Review view-model: formal prediction vs observation + learning."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from stock_pm.prediction import has_real_bounds

from .copy import mmdd, strip_holdings


FORMAL_FIELDS = (
    "window_start",
    "window_end",
    "upside_bound_pct",
    "downside_bound_pct",
)


def _as_date(value: Any) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def is_formal(pred: dict[str, Any] | None) -> bool:
    row = pred or {}
    if row.get("direction_withheld") or row.get("can_form_direction") is False:
        return False
    if row.get("state") in {"missing", "withheld"}:
        return False
    if not has_real_bounds(row):
        return False
    struct = row.get("struct") if isinstance(row.get("struct"), dict) else {}
    invalidation = struct.get("invalidation") or struct.get("invalidate") or row.get("change_reason")
    baseline = row.get("entry_price") or struct.get("entry_price") or struct.get("baseline")
    stamp = row.get("created_at") or row.get("as_of_date") or struct.get("as_of")
    if not (invalidation and baseline and stamp):
        # Bounds + window are the hard gate; missing invalidation/baseline
        # still counts if prediction_ready — otherwise it would starve the
        # formal column. Surface the gap in the card instead of silently
        # downgrading a complete window.
        return bool(row.get("prediction_ready"))
    return True


def missing_formal_fields(pred: dict[str, Any] | None) -> list[str]:
    row = pred or {}
    gaps: list[str] = []
    if not row.get("window_start") or not row.get("window_end"):
        gaps.append("窗")
    if row.get("upside_bound_pct") is None:
        gaps.append("上界")
    if row.get("downside_bound_pct") is None:
        gaps.append("下界")
    struct = row.get("struct") if isinstance(row.get("struct"), dict) else {}
    if not (struct.get("invalidation") or struct.get("invalidate") or row.get("change_reason")):
        gaps.append("失效")
    if row.get("entry_price") is None and struct.get("baseline") is None:
        gaps.append("基准")
    if not (row.get("created_at") or row.get("as_of_date")):
        gaps.append("数据时间")
    if not row.get("id"):
        gaps.append("证据版本")
    return gaps


def _in_review_window(pred: dict[str, Any], today: date) -> bool:
    start = _as_date(pred.get("window_start") or pred.get("as_of_date"))
    end = _as_date(pred.get("window_end"))
    if pred.get("state") in {"hit", "invalidated", "superseded", "active", "pending", "auto_gen"}:
        if end and end < today - timedelta(days=21):
            return False
        return True
    if end and today - timedelta(days=7) <= end <= today + timedelta(days=7):
        return True
    if start and start >= today - timedelta(days=14):
        return True
    return False


def _pct(value: Any, signed: bool = True) -> str:
    if value is None:
        return "—"
    number = float(value)
    if signed:
        return f"{number:+.1f}%".replace(".0%", "%")
    return f"{abs(number):.1f}%"


def _direction_label(pred: dict[str, Any]) -> str:
    thesis = str(pred.get("thesis") or pred.get("therefore") or "")
    if "偏空" in thesis or "谨慎" in thesis:
        return "偏空"
    if "中性" in thesis:
        return "中性"
    if "偏多" in thesis or "补涨" in thesis or "续涨" in thesis:
        return "偏多"
    if pred.get("upside_bound_pct") and abs(float(pred.get("upside_bound_pct") or 0)) > abs(
        float(pred.get("downside_bound_pct") or 0)
    ):
        return "偏多"
    return "中性"


def _actual_line(pred: dict[str, Any], check: dict[str, Any] | None, brief: dict[str, Any] | None) -> str:
    check = check or {}
    if check.get("max_gain_pct") is not None or check.get("max_drawdown_pct") is not None:
        gain = check.get("max_gain_pct")
        dd = check.get("max_drawdown_pct")
        state = pred.get("state")
        state_zh = {
            "active": "进行中",
            "hit": "已兑现",
            "invalidated": "已打脸",
            "superseded": "已改口",
            "pending": "待生效",
        }.get(str(state), "进行中")
        bits = []
        if gain is not None:
            bits.append(_pct(gain))
        if dd is not None:
            bits.append(f"回撤 {_pct(dd)}")
        return f"窗内 { ' · '.join(bits)} · 状态：{state_zh}"
    chg = (brief or {}).get("day_change_pct")
    if chg is not None:
        return f"最近交易日 {_pct(chg)} · 状态：跟踪中"
    return "对照行情暂缺，不静默判对"


def _evidence_lines(pred: dict[str, Any], check: dict[str, Any] | None, events: list[dict[str, Any]] | None) -> list[str]:
    lines: list[str] = []
    thesis = strip_holdings(pred.get("thesis") or pred.get("therefore") or "")
    if thesis:
        lines.append(f"✓ 有效：当时叙事「{thesis[:60]}」")
    outcome = (check or {}).get("outcome")
    reason = strip_holdings((check or {}).get("reason") or "")
    if outcome == "hit":
        lines.append("✓ 有效：窗内未破界")
    elif outcome in {"downside_break", "expired"} or pred.get("state") == "invalidated":
        lines.append(f"✗ 高估或打脸：{reason or '边界被突破或到期未兑现'}")
    elif outcome == "missing_price":
        lines.append("对照价缺失，不静默判对")
    for card in (events or [])[:2]:
        title = card.get("title")
        if title:
            lines.append(f"预测后信息：{title}")
    if len(lines) < 2:
        lines.append("证据有效/高估对照不足，不编归因")
    return lines[:4]


def _learning(symbol: str, pred: dict[str, Any], check: dict[str, Any] | None) -> dict[str, Any] | None:
    if not is_formal(pred):
        return None
    outcome = (check or {}).get("outcome") or pred.get("state")
    right = "窗与边界齐全，可以对照"
    wrong = "证据权重对照不足，不编具体错因"
    nxt = "下次仍只把齐备字段的预测计入命中"
    if outcome == "hit" or pred.get("state") == "hit":
        right = "窗内走势未打脸，叙事与价格同向"
        wrong = "若把旁证当成硬上界，仍属过度解读"
        nxt = "旁证只作确认度，不单独抬上界预期"
    elif pred.get("state") == "invalidated" or outcome in {"downside_break", "expired"}:
        right = "窗与边界齐全，打脸可核对"
        wrong = strip_holdings((check or {}).get("reason") or "边界被突破或到期未兑现")
        nxt = "失效条件触发时同步下调近端权重"
    elif pred.get("state") == "superseded":
        right = "改口留痕可核对"
        wrong = strip_holdings(pred.get("change_reason") or "原边界不再适用")
        nxt = "改口必须引用严重提醒后再写原因"
    return {
        "symbol": symbol,
        "right": right,
        "wrong": wrong,
        "next": nxt,
    }


def formal_card(
    pred: dict[str, Any],
    *,
    check: dict[str, Any] | None = None,
    brief: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    struct = pred.get("struct") if isinstance(pred.get("struct"), dict) else {}
    as_of = pred.get("as_of_date") or pred.get("created_at")
    invalidation = struct.get("invalidation") or struct.get("invalidate") or "失效条件未单列"
    evidence = pred.get("id")
    return {
        "symbol": pred.get("symbol"),
        "as_of_label": f"正式预测 · {mmdd(as_of)}",
        "direction": _direction_label(pred),
        "window": f"{mmdd(pred.get('window_start'))} → {mmdd(pred.get('window_end'))}",
        "upside": _pct(pred.get("upside_bound_pct")),
        "downside": _pct(pred.get("downside_bound_pct")),
        "baseline": f"{mmdd(as_of)} 收盘" if pred.get("entry_price") is None else f"基准 {pred.get('entry_price')}",
        "invalidation": strip_holdings(str(invalidation)),
        "data_time": str(pred.get("created_at") or as_of or "—"),
        "evidence_version": f"p-{evidence}" if evidence else "证据版本暂缺",
        "complete": True,
        "actual": _actual_line(pred, check, brief),
        "evidence_lines": _evidence_lines(pred, check, events),
        "new_info": (events[0].get("title") if events else None) or "预测后暂无新的可映射事件",
        "revision": strip_holdings(
            (brief or {}).get("env_half")
            or (brief or {}).get("row_thesis")
            or "维持原窗；作废条件不变"
        ),
        "prediction_id": pred.get("id"),
        "alert_id": (pred.get("judgment_alert") or {}).get("id") or pred.get("alert_id"),
    }


def observe_card(pred: dict[str, Any] | None, symbol: str) -> dict[str, Any]:
    gaps = missing_formal_fields(pred)
    direction = _direction_label(pred or {}) if pred else "—"
    return {
        "symbol": symbol,
        "title": f"{symbol} · 规则倾向（不完整）",
        "text": (
            f"仅有方向「{direction}」· 缺：{'、'.join(gaps) or '窗、上下边界、失效、基准、数据时间、证据版本'}"
            " → 标签【观察】· 禁止进校验主口径"
        ),
        "note": "用途：辅助理解总览「判断不变」，不计命中率",
    }


def build_review_payload(
    *,
    watch: list[dict[str, Any]],
    predictions: dict[str, list[dict[str, Any]]],
    checks: dict[str, list[dict[str, Any]]],
    briefing_rows: list[dict[str, Any]] | None = None,
    events_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    brief_map = {str(row.get("symbol") or "").upper(): row for row in (briefing_rows or [])}
    formal: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    learning: list[dict[str, Any]] = []
    for item in watch or []:
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        rows = [row for row in (predictions.get(symbol) or []) if _in_review_window(row, today)]
        if not rows:
            # Still surface incomplete live rows as observation, not a dump.
            live = (predictions.get(symbol) or [None])[0]
            if live and not is_formal(live):
                observations.append(observe_card(live, symbol))
            continue
        chosen = rows[0]
        check_list = checks.get(str(chosen.get("id") or "")) or checks.get(symbol) or []
        check = check_list[0] if check_list else None
        events = (events_by_symbol or {}).get(symbol) or []
        if is_formal(chosen):
            card = formal_card(chosen, check=check, brief=brief_map.get(symbol), events=events)
            formal.append(card)
            learned = _learning(symbol, chosen, check)
            if learned:
                learning.append(learned)
        else:
            observations.append(observe_card(chosen, symbol))
    return {
        "page": {
            "title": "为什么对、为什么错",
            "sub": "正式预测对在哪 · 错在哪 · 证据有效或被高估 · 当前如何修正 · 错误归因 / 学到什么",
        },
        "filter": "需复盘的正式预测（本周到期 / 已触发）",
        "formal": formal,
        "learning": learning,
        "observations": observations,
        "empty_formal": None if formal else "本周没有字段齐全、可进校验的正式预测。",
    }
