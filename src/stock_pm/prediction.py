"""Knife 4 / Slice D: Prediction + face-slap.

Pure module (no database). Callers pass EnvironmentSnapshot, TapeAnalysis,
ReviewNote, and a close. This file writes a verifiable Prediction
(time window + upside + downside) or an honest missing row. It does not
reuse llm_outlook / rule bias as if they were the new Prediction.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from .analytics import _number
from .calendar import add_trading_days, next_trading_day
from .decision import build_thesis, freeze_prediction
from .environment import _as_clause
from .ux_copy import (
    LEGACY_DISCLAIMER,
    LEGACY_LABEL,
    PREDICTION_HIT_LABEL,
    named_missing_line,
)

def withhold_unsourced_prediction(pred: dict[str, Any] | None, *, can_form_direction: bool) -> dict[str, Any]:
    """When the decision kernel cannot form a direction, never show a % path."""
    payload = dict(pred or {})
    payload["can_form_direction"] = bool(can_form_direction)
    payload["kind"] = "prediction" if can_form_direction else "historical_or_withheld"
    if can_form_direction:
        return payload
    payload["direction_withheld"] = True
    payload["prediction_ready"] = False
    payload["therefore"] = "决策未形成方向：不展示无来源涨跌或百分比预测。下面若有数字，只可能是已发生事实。"
    payload["upside_bound_pct"] = None
    payload["downside_bound_pct"] = None
    payload["upside_price"] = None
    payload["downside_price"] = None
    payload["window_label"] = None
    payload["window_start"] = None
    payload["window_end"] = None
    payload["badge"] = None
    payload["one_liner"] = None
    payload["target"] = None
    payload["thesis"] = None
    payload["state"] = "withheld"
    payload["missing_label"] = "决策未形成方向，不展示百分比预测"
    payload["prediction_half"] = payload["missing_label"]
    payload["missingFlags"] = list(payload.get("missingFlags") or []) + ["decision_direction"]
    struct = dict(payload.get("struct") or {})
    if struct:
        struct["therefore"] = payload["therefore"]
        struct["target"] = None
        struct["action"] = None
        struct["window_label"] = None
        struct["prediction_ready"] = False
        struct["missing_label"] = payload["missing_label"]
        payload["struct"] = struct
    return payload


PUBLISH_STATES = ("published", "draft", "stale", "missing")
PREDICTION_STATES = (
    "auto_gen",
    "pending",
    "active",
    "hit",
    "invalidated",
    "superseded",
    "missing",
)
OPEN_STATES = frozenset({"auto_gen", "pending", "active"})
TERMINAL_STATES = frozenset({"hit", "invalidated", "superseded", "missing"})
STATE_LABELS = {
    "auto_gen": "已自动生成",
    "pending": "待生效",
    "active": "跟踪中",
    "hit": "已兑现",
    "invalidated": "已打脸",
    "superseded": "已改口",
    "missing": "到期未产出",
}

PRED_FIELD_FLAGS = (
    "entry_price",
    "support",
    "resistance",
    "tape",
    "environment",
    "window",
)

FLAG_LABELS = {
    "entry_price": "入场价",
    "support": "下跌边界",
    "resistance": "上涨边界",
    "tape": "昨盘",
    "environment": "环境",
    "window": "时间窗口",
    "price": "对照价格",
}

MISSING_LINE = "到期未产出，未编造时间窗口或涨跌边界。"
MISSING_DATA_LINE = named_missing_line(PRED_FIELD_FLAGS)
QUALIFIED_EXAMPLE = "两周内补涨约10%，期间跌幅不超过5%"

MIN_BOUND_PCT = 0.5
MAX_BOUND_PCT = 30.0
SAME_DAY_BOUND_PCT = 4.0
DEFAULT_WINDOW_DAYS = 10
SAME_DAY_WINDOW_DAYS = 1


def flag_labels(flags: list[str]) -> str:
    from .ux_copy import named_missing_labels

    return "、".join(named_missing_labels(flags) or [FLAG_LABELS.get(flag, flag) for flag in flags])


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _round_pct(value: float) -> float:
    nearest = round(value)
    if abs(value - nearest) < 0.2:
        return float(nearest)
    return round(value, 1)


def _fmt_pct(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "—"
    number = _round_pct(value)
    if signed:
        return f"{number:+.0f}%" if number == int(number) else f"{number:+.1f}%"
    abs_n = abs(number)
    return f"{abs_n:.0f}%" if abs_n == int(abs_n) else f"{abs_n:.1f}%"


def _price(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _lifecycle(state: str, reason: str, at: str | None = None) -> dict:
    return {"state": state, "reason": reason, "at": at}


def has_real_bounds(pred: dict | None) -> bool:
    if not pred:
        return False
    return (
        pred.get("prediction_ready") is True
        and _number(pred.get("upside_bound_pct")) is not None
        and _number(pred.get("downside_bound_pct")) is not None
        and pred.get("window_start")
        and pred.get("window_end")
        and pred.get("state") != "missing"
    )


def prediction_badge(pred: dict | None) -> str:
    """Overview badge bound to a real Prediction — never fake 10%/-5%."""
    if not pred:
        return "到期未产出"
    if not has_real_bounds(pred):
        return (
            pred.get("missing_label")
            or pred.get("one_liner")
            or MISSING_LINE
        )
    window = pred.get("window_label") or "窗口"
    state = STATE_LABELS.get(pred.get("state") or "", pred.get("state") or "")
    return (
        f"{window} 上{_fmt_pct(pred.get('upside_bound_pct'))} / "
        f"下{_fmt_pct(pred.get('downside_bound_pct'))} · {state}"
    )


def _therefore_from_pred(pred: dict | None) -> str | None:
    """A-card line: only 因此：窗+上下沿, or a named missing list."""
    pred = pred or {}
    thesis = str(pred.get("thesis") or "")
    if "因此：" in thesis and pred.get("prediction_ready") and pred.get("state") != "missing":
        return "因此：" + thesis.split("因此：", 1)[1].rstrip("。")
    if pred.get("prediction_ready") and pred.get("state") != "missing":
        window = pred.get("window_label") or "窗口"
        if pred.get("upside_bound_pct") is not None and pred.get("downside_bound_pct") is not None:
            return (
                f"因此：{window} 上{_fmt_pct(pred.get('upside_bound_pct'))} / "
                f"下{_fmt_pct(pred.get('downside_bound_pct'))}"
            )
    flags = list(pred.get("missingFlags") or [])
    if flags:
        return named_missing_line(flags)
    stored = pred.get("therefore") or pred.get("missing_label")
    return stored


def prediction_therefore(pred: dict | None) -> str:
    if pred and pred.get("therefore"):
        return str(pred["therefore"])
    return _therefore_from_pred(pred) or MISSING_LINE


def is_legacy_outlook(text: str | None) -> bool:
    return bool(text) and QUALIFIED_EXAMPLE.split("约")[0] not in (text or "")


def _action_from_premises(tape: dict | None, environment: dict | None) -> str | None:
    tape = tape or {}
    form = ((tape.get("volume_price") or {}).get("form") or "")
    judgment = ((tape.get("env_link") or {}).get("judgment") or "")
    atmosphere = ""
    struct = (environment or {}).get("struct") or {}
    sentiment = struct.get("sentiment") or {}
    if isinstance(sentiment, dict):
        atmosphere = str(sentiment.get("atmosphere") or sentiment.get("clause") or "")
    if "吸筹" in judgment or "补涨" in atmosphere:
        return "补涨"
    if form.startswith("放量涨") or form.startswith("缩量涨") or form.startswith("平量涨"):
        if "诱多" in judgment:
            return None
        return "续涨"
    if form.startswith("放量跌") or form.startswith("缩量跌") or form.startswith("平量跌"):
        if "逃跑" in judgment or "诱多" in judgment:
            return None
        return "补涨"
    if "转势" in judgment:
        return "续涨"
    return None


def _bounds_from_sr(
    entry: float | None, support: float | None, resistance: float | None
) -> tuple[dict | None, list[str]]:
    missing: list[str] = []
    if entry is None or entry <= 0:
        missing.append("entry_price")
    if support is None:
        missing.append("support")
    if resistance is None:
        missing.append("resistance")
    if missing:
        return None, missing
    upside = 100.0 * (resistance - entry) / entry
    downside = 100.0 * (support - entry) / entry
    if upside < MIN_BOUND_PCT or upside > MAX_BOUND_PCT:
        missing.append("resistance")
    if downside > -MIN_BOUND_PCT or downside < -MAX_BOUND_PCT:
        missing.append("support")
    if missing:
        return None, missing
    return {
        "upside_bound_pct": _round_pct(upside),
        "downside_bound_pct": _round_pct(downside),
        "upside_price": round(entry * (1 + upside / 100.0), 4),
        "downside_price": round(entry * (1 + downside / 100.0), 4),
    }, []


def _window_for_bounds(as_of: date | None, upside: float, downside: float) -> dict:
    start = next_trading_day(as_of) if as_of else None
    tight = upside <= SAME_DAY_BOUND_PCT and abs(downside) <= SAME_DAY_BOUND_PCT
    days = SAME_DAY_WINDOW_DAYS if tight else DEFAULT_WINDOW_DAYS
    label = "当天" if days == 1 else "两周内"
    end = add_trading_days(start, days - 1) if start else None
    return {
        "window_days": days,
        "window_label": label,
        "window_start": start.isoformat() if start else None,
        "window_end": end.isoformat() if end else None,
    }


def _premise_ready(tape: dict | None, environment: dict | None) -> list[str]:
    missing: list[str] = []
    tape = tape or {}
    env = environment or {}
    form = (tape.get("volume_price") or {}).get("form")
    if not form or tape.get("publishState") == "missing":
        missing.append("tape")
    if env.get("publishState") == "missing" or not (
        env.get("one_liner") or env.get("synthesis") or env.get("row_thesis")
    ):
        missing.append("environment")
    return missing


def failed_prediction(
    symbol: str,
    as_of_date: str | None,
    error: str,
    *,
    flags: list[str] | None = None,
    missing_label: str | None = None,
) -> dict:
    line = missing_label or MISSING_LINE
    return {
        "as_of_date": as_of_date,
        "symbol": symbol.upper(),
        "state": "missing",
        "state_label": STATE_LABELS["missing"],
        "window_start": None,
        "window_end": None,
        "window_days": None,
        "window_label": None,
        "thesis": line,
        "therefore": None,
        "one_liner": line,
        "entry_price": None,
        "upside_bound_pct": None,
        "downside_bound_pct": None,
        "upside_price": None,
        "downside_price": None,
        "struct": {"error": error, "lifecycle": [_lifecycle("missing", error)]},
        "missingFlags": list(flags or PRED_FIELD_FLAGS),
        "publishState": "missing",
        "prediction_ready": False,
        "missing_label": line,
        "supersedes_id": None,
        "superseded_by_id": None,
        "change_reason": None,
        "source": "failed",
        "legacy": False,
    }


def snapshot_from_row(row: dict | None) -> dict | None:
    if not row:
        return None
    flags = row.get("missing_flags")
    if flags is None:
        flags = row.get("missingFlags") or []
    struct = row.get("struct") or {}
    as_of = row.get("as_of_date")
    created = row.get("created_at")
    state = row.get("state") or "missing"
    ready = bool(struct.get("prediction_ready")) if "prediction_ready" in struct else False
    if ready is False and state != "missing":
        ready = (
            _number(row.get("upside_bound_pct")) is not None
            and _number(row.get("downside_bound_pct")) is not None
            and row.get("window_start")
            and row.get("window_end")
        )
    window_start = row.get("window_start")
    window_end = row.get("window_end")
    payload = {
        "id": row.get("id"),
        "as_of_date": str(as_of)[:10] if as_of else None,
        "symbol": row.get("symbol"),
        "state": state,
        "state_label": STATE_LABELS.get(state, state),
        "window_start": str(window_start)[:10] if window_start else None,
        "window_end": str(window_end)[:10] if window_end else None,
        "window_days": row.get("window_days"),
        "window_label": row.get("window_label") or (struct.get("window_label") if isinstance(struct, dict) else None),
        "thesis": row.get("thesis"),
        "therefore": (struct.get("therefore") if isinstance(struct, dict) else None)
        or _therefore_from_pred(
            {
                "window_label": row.get("window_label")
                or (struct.get("window_label") if isinstance(struct, dict) else None),
                "upside_bound_pct": row.get("upside_bound_pct"),
                "downside_bound_pct": row.get("downside_bound_pct"),
                "prediction_ready": ready and state != "missing",
                "state": state,
                "missingFlags": list(flags),
                "missing_label": struct.get("missing_label") if isinstance(struct, dict) else None,
                "thesis": row.get("thesis"),
            }
        ),
        "one_liner": row.get("thesis"),
        "entry_price": _number(row.get("entry_price")),
        "upside_bound_pct": _number(row.get("upside_bound_pct")),
        "downside_bound_pct": _number(row.get("downside_bound_pct")),
        "upside_price": _number(row.get("upside_price")),
        "downside_price": _number(row.get("downside_price")),
        "struct": struct,
        "missingFlags": list(flags),
        "publishState": row.get("publish_state") or row.get("publishState") or "draft",
        "prediction_ready": ready and state != "missing",
        "missing_label": struct.get("missing_label") if isinstance(struct, dict) else None,
        "supersedes_id": row.get("supersedes_id"),
        "superseded_by_id": row.get("superseded_by_id"),
        "change_reason": row.get("change_reason"),
        "alert_id": parse_alert_id(row.get("alert_id"))
        or parse_alert_id((struct or {}).get("alert_id") if isinstance(struct, dict) else None)
        or parse_alert_id(((struct or {}).get("supersedes") or {}).get("alert_id") if isinstance(struct, dict) else None),
        "created_at": str(created) if created else None,
        "source": row.get("source") or (struct.get("source") if isinstance(struct, dict) else None) or "stored",
        "legacy": False,
    }
    payload["badge"] = prediction_badge(payload)
    return payload


def check_from_row(row: dict | None) -> dict | None:
    if not row:
        return None
    as_of = row.get("as_of_date")
    created = row.get("created_at")
    return {
        "id": row.get("id"),
        "prediction_id": row.get("prediction_id"),
        "as_of_date": str(as_of)[:10] if as_of else None,
        "symbol": row.get("symbol"),
        "close_price": _number(row.get("close_price")),
        "high_price": _number(row.get("high_price")),
        "low_price": _number(row.get("low_price")),
        "max_gain_pct": _number(row.get("max_gain_pct")),
        "max_drawdown_pct": _number(row.get("max_drawdown_pct")),
        "in_bounds": row.get("in_bounds"),
        "outcome": row.get("outcome"),
        "reason": row.get("reason"),
        "struct": row.get("struct") or {},
        "created_at": str(created) if created else None,
        "source": "stored",
    }


def synthesize_prediction(
    *,
    as_of_date: str | None,
    symbol: str,
    environment: dict | None = None,
    tape: dict | None = None,
    review_note: dict | None = None,
    entry_price: float | None = None,
    support: float | None = None,
    resistance: float | None = None,
    session: dict | None = None,
    source: str = "auto",
    supersedes_id: int | None = None,
    change_reason: str | None = None,
) -> dict:
    """Build a verifiable Prediction from 环境→昨盘→解释, or honest missing."""
    symbol_u = symbol.upper()
    as_of = _as_date(as_of_date)
    tape = tape or {}
    environment = environment or {}
    review_note = review_note or {}
    chips = tape.get("chips") or {}
    entry = _number(entry_price) or _number(chips.get("close"))
    support = _number(support) if support is not None else _number(chips.get("support"))
    resistance = (
        _number(resistance) if resistance is not None else _number(chips.get("resistance"))
    )
    missing = _premise_ready(tape, environment)
    bounds, bound_flags = _bounds_from_sr(entry, support, resistance)
    missing.extend(flag for flag in bound_flags if flag not in missing)
    action = _action_from_premises(tape, environment)
    unexplained = bool(review_note.get("unexplained"))
    if unexplained and not action:
        if "tape" not in missing:
            missing.append("tape")

    if session and session.get("is_trading_day") is False:
        line = f"{as_of_date or ''} {session.get('label') or '美股休市'}，不编当日预测边界。".strip()
        pred = failed_prediction(symbol_u, as_of_date, "session_closed", missing_label=line)
        pred["publishState"] = "stale"
        pred["one_liner"] = line
        pred["thesis"] = line
        return pred

    if missing or bounds is None or action is None or as_of is None:
        flags = missing or list(PRED_FIELD_FLAGS)
        if action is None and "tape" not in flags:
            flags.append("tape")
        if as_of is None and "window" not in flags:
            flags.append("window")
        label = named_missing_line(flags) if flags else MISSING_LINE
        return failed_prediction(
            symbol_u,
            as_of_date,
            "quality_gate",
            flags=flags,
            missing_label=label,
        )

    window = _window_for_bounds(as_of, bounds["upside_bound_pct"], bounds["downside_bound_pct"])
    env_disp = _as_clause(
        environment.get("synthesis")
        or environment.get("one_liner")
        or environment.get("row_thesis"),
        "结论不足",
    )
    tape_disp = _as_clause(tape.get("one_liner"), "结论不足")
    explain = review_note.get("explanation") or ""
    if unexplained or "解释不了" in explain:
        explain_disp = "解释不了，仍按昨盘与支撑压力给可验证边界，不硬编因果"
    else:
        explain_disp = _as_clause(explain, "依据不足")
    target = (
        f"{window['window_label']}{action}约{_fmt_pct(bounds['upside_bound_pct'])}"
        f"，期间跌幅不超过{_fmt_pct(bounds['downside_bound_pct'])}"
    )
    therefore = f"因此：{target}"
    thesis = (
        f"环境：{env_disp}。昨盘：{tape_disp}。解释：{explain_disp}。"
        f"{therefore}。"
    )
    lifecycle = [
        _lifecycle("auto_gen", "盘后自动生成"),
        _lifecycle("pending", "依据已齐，等待窗口开始"),
    ]
    if change_reason:
        lifecycle.append(_lifecycle("pending", f"改口留痕：{change_reason}"))
    struct = {
        "action": action,
        "target": target,
        "therefore": therefore,
        "window_label": window["window_label"],
        "lifecycle": lifecycle,
        "prediction_ready": True,
        "source": source,
        "premises": {
            "environment": environment.get("one_liner"),
            "tape": tape.get("one_liner"),
            "review": review_note.get("summary"),
        },
        "bounds_source": "support_resistance",
        "missing_label": None,
    }
    payload = {
        "as_of_date": as_of_date,
        "symbol": symbol_u,
        "state": "pending",
        "state_label": STATE_LABELS["pending"],
        "window_start": window["window_start"],
        "window_end": window["window_end"],
        "window_days": window["window_days"],
        "window_label": window["window_label"],
        "thesis": thesis,
        "therefore": therefore,
        "one_liner": target + "。",
        "entry_price": round(entry, 4),
        "upside_bound_pct": bounds["upside_bound_pct"],
        "downside_bound_pct": bounds["downside_bound_pct"],
        "upside_price": bounds["upside_price"],
        "downside_price": bounds["downside_price"],
        "struct": struct,
        "missingFlags": [],
        "publishState": "published",
        "prediction_ready": True,
        "missing_label": None,
        "supersedes_id": supersedes_id,
        "superseded_by_id": None,
        "change_reason": change_reason,
        "source": source,
        "legacy": False,
    }
    decision_thesis = build_thesis(
        direction="bullish",
        bull_drivers=[item for item in (environment.get("one_liner"), tape.get("one_liner")) if item][:3],
        bear_drivers=[f"下跌边界 {_price(bounds['downside_price'])}"],
        key_disagreement="现有盘面与环境证据能否在预测窗口内兑现",
        invalidation={
            "market": {
                "type": "price",
                "price": bounds["downside_price"],
                "rule": "窗口内低点触及或跌破下跌边界",
            }
        },
        evidence_quality="medium" if not unexplained else "weak",
    )
    forecast_snapshot = {
        "symbol": symbol_u,
        "direction": decision_thesis["direction"],
        "window_start": window["window_start"],
        "window_end": window["window_end"],
        "expected_return_range": [
            bounds["downside_bound_pct"],
            bounds["upside_bound_pct"],
        ],
        "thesis": decision_thesis,
    }
    struct["decision"] = {
        "schema_version": 1,
        "what_changed": None,
        "expectation_gap": None,
        "thesis": decision_thesis,
        "note": "What Changed 与预期差在有前序快照/一致预期时填充；缺失时不编造。",
    }
    struct["frozen_prediction"] = freeze_prediction(
        forecast_snapshot,
        generated_at=datetime.now(timezone.utc),
        model_version="support-resistance-v1",
        data_snapshot_id={
            "as_of_date": as_of_date,
            "environment_id": environment.get("id"),
            "tape_id": tape.get("id"),
            "review_note_id": review_note.get("id"),
        },
    )
    payload["struct"] = struct
    payload["badge"] = prediction_badge(payload)
    return payload


def activate_if_due(prediction: dict, as_of_date: str | None) -> dict:
    """auto-gen / pending → active when the window has started."""
    pred = dict(prediction)
    state = pred.get("state")
    if state not in {"auto_gen", "pending"}:
        return pred
    start = _as_date(pred.get("window_start"))
    as_of = _as_date(as_of_date)
    if start is None or as_of is None or as_of < start:
        return pred
    pred["state"] = "active"
    pred["state_label"] = STATE_LABELS["active"]
    struct = dict(pred.get("struct") or {})
    life = list(struct.get("lifecycle") or [])
    life.append(_lifecycle("active", "窗口开始，进入跟踪"))
    struct["lifecycle"] = life
    pred["struct"] = struct
    pred["badge"] = prediction_badge(pred)
    return pred


def run_prediction_check(
    prediction: dict,
    *,
    as_of_date: str | None,
    close: float | None = None,
    high: float | None = None,
    low: float | None = None,
    prior_max_gain_pct: float | None = None,
    prior_max_drawdown_pct: float | None = None,
) -> dict:
    """After-close check. Breaks bounds → face-slap. Small noise does not rewrite."""
    pred = activate_if_due(prediction, as_of_date)
    close_n = _number(close)
    high_n = _number(high) if high is not None else close_n
    low_n = _number(low) if low is not None else close_n
    entry = _number(pred.get("entry_price"))
    upside_px = _number(pred.get("upside_price"))
    downside_px = _number(pred.get("downside_price"))
    window_end = _as_date(pred.get("window_end"))
    as_of = _as_date(as_of_date)
    next_state = pred.get("state")
    outcome = "tracking"
    reason = "仍在框内"

    if close_n is None or high_n is None or low_n is None or entry is None:
        outcome = "missing_price"
        reason = "对照价格暂缺，不判对错，也不改口。"
        check = {
            "prediction_id": pred.get("id"),
            "as_of_date": as_of_date,
            "symbol": pred.get("symbol"),
            "close_price": close_n,
            "high_price": high_n,
            "low_price": low_n,
            "max_gain_pct": prior_max_gain_pct,
            "max_drawdown_pct": prior_max_drawdown_pct,
            "in_bounds": None,
            "outcome": outcome,
            "reason": reason,
            "next_state": next_state,
            "prediction": pred,
            "alert": None,
        }
        return check

    day_gain = 100.0 * (high_n / entry - 1)
    day_dd = 100.0 * (low_n / entry - 1)
    max_gain = day_gain if prior_max_gain_pct is None else max(prior_max_gain_pct, day_gain)
    max_dd = day_dd if prior_max_drawdown_pct is None else min(prior_max_drawdown_pct, day_dd)
    in_bounds = True

    if pred.get("state") in TERMINAL_STATES:
        outcome = "already_terminal"
        reason = f"预测已是{STATE_LABELS.get(pred.get('state'), pred.get('state'))}，不再改写。"
    elif downside_px is not None and low_n <= downside_px:
        in_bounds = False
        outcome = "downside_break"
        next_state = "invalidated"
        reason = (
            f"期间低点 {_price(low_n)} 跌破下跌边界 {_price(downside_px)}"
            f"（{_fmt_pct(pred.get('downside_bound_pct'))}），判定打脸。"
        )
    elif upside_px is not None and high_n >= upside_px:
        in_bounds = False
        outcome = "hit"
        next_state = "hit"
        reason = (
            f"期间高点 {_price(high_n)} 触及上涨边界 {_price(upside_px)}"
            f"（约{_fmt_pct(pred.get('upside_bound_pct'))}），判定兑现。"
        )
    elif window_end is not None and as_of is not None and as_of >= window_end:
        in_bounds = True
        outcome = "expired"
        next_state = "invalidated"
        reason = (
            f"窗口已到 {window_end.isoformat()} 仍未走出"
            f"约{_fmt_pct(pred.get('upside_bound_pct'))}，判定打脸（到期未兑现）。"
        )
    else:
        reason = (
            f"现走到 {_price(close_n)}，高 {_fmt_pct(max_gain, signed=True)} / "
            f"低 {_fmt_pct(max_dd, signed=True)}，仍在框内。小波动不改口。"
        )

    updated = dict(pred)
    if next_state != pred.get("state"):
        updated["state"] = next_state
        updated["state_label"] = STATE_LABELS.get(next_state, next_state)
        struct = dict(updated.get("struct") or {})
        life = list(struct.get("lifecycle") or [])
        life.append(_lifecycle(next_state, reason, as_of_date))
        struct["lifecycle"] = life
        updated["struct"] = struct
        updated["badge"] = prediction_badge(updated)

    alert = None
    if next_state == "invalidated" and pred.get("state") != "invalidated":
        alert = {
            "alert_key": f"face_slap:{pred.get('symbol')}:{pred.get('id') or pred.get('as_of_date')}",
            "severity": "severe",
            "title": "打脸待核验",
            "message": (
                f"{pred.get('symbol')} {reason} "
                "请判断是否改口（留痕）。小噪声不要自动改口。"
            ),
            "symbol": pred.get("symbol"),
            "cta": "judgment_change",
            "prediction_id": pred.get("id"),
        }

    return {
        "prediction_id": pred.get("id"),
        "as_of_date": as_of_date,
        "symbol": pred.get("symbol"),
        "close_price": close_n,
        "high_price": high_n,
        "low_price": low_n,
        "max_gain_pct": round(max_gain, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "in_bounds": in_bounds,
        "outcome": outcome,
        "reason": reason,
        "next_state": next_state,
        "prediction": updated,
        "alert": alert,
    }


def parse_alert_id(value: Any) -> int | None:
    if value in (None, "", False):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def require_judgment_alert(
    alert: dict | None,
    *,
    symbol: str,
    prediction_id: int | None,
    alert_id: Any = None,
) -> int:
    """CHANGE-01: supersede only after a severe alert tied to this prediction."""
    parsed = parse_alert_id(alert_id if alert_id is not None else (alert or {}).get("id"))
    if parsed is None:
        raise ValueError("改口必须引用严重预警 alert_id")
    if not alert:
        raise ValueError("alert_id 未知，不能改口")
    stored_id = parse_alert_id(alert.get("id"))
    if stored_id is None or stored_id != parsed:
        raise ValueError("alert_id 未知，不能改口")
    if str(alert.get("severity") or "") != "severe":
        raise ValueError("alert_id 不是严重预警，不能改口")
    alert_symbol = str(alert.get("symbol") or "").upper()
    wanted = symbol.upper()
    if alert_symbol and alert_symbol != wanted:
        raise ValueError("alert_id 不属于该标的，不能改口")
    if prediction_id is None:
        raise ValueError("alert_id 不属于该预测打脸，不能改口")
    pred_ref = parse_alert_id(alert.get("prediction_id"))
    key = str(alert.get("alert_key") or "")
    expected_key = f"face_slap:{wanted}:{int(prediction_id)}"
    if pred_ref != int(prediction_id) and key != expected_key:
        raise ValueError("alert_id 不属于该预测打脸，不能改口")
    if alert.get("active") is False:
        raise ValueError("alert_id 已解除，不能改口")
    return parsed


def apply_supersede(
    old: dict,
    new: dict,
    *,
    change_reason: str,
    alert_id: Any,
    alert: dict | None = None,
) -> tuple[dict, dict]:
    """Human judgment-change. Leave-trace; never auto-called on noise."""
    reason = (change_reason or "").strip()
    if not reason:
        raise ValueError("改口必须写原因，留痕")
    if old.get("state") == "missing" or not has_real_bounds(old):
        raise ValueError("没有可改口的真实预测")
    tied = require_judgment_alert(
        alert,
        symbol=str(old.get("symbol") or ""),
        prediction_id=old.get("id"),
        alert_id=alert_id,
    )
    superseded = dict(old)
    superseded["state"] = "superseded"
    superseded["state_label"] = STATE_LABELS["superseded"]
    superseded["change_reason"] = reason
    superseded["alert_id"] = tied
    struct = dict(superseded.get("struct") or {})
    life = list(struct.get("lifecycle") or [])
    life.append(_lifecycle("superseded", f"改口留痕：{reason}（alert_id={tied}）"))
    struct["lifecycle"] = life
    struct["alert_id"] = tied
    superseded["struct"] = struct
    superseded["badge"] = prediction_badge(superseded)

    replacement = dict(new)
    replacement["supersedes_id"] = old.get("id")
    replacement["change_reason"] = reason
    replacement["alert_id"] = tied
    replacement["source"] = "human"
    nstruct = dict(replacement.get("struct") or {})
    nstruct["source"] = "human"
    nstruct["alert_id"] = tied
    nstruct["supersedes"] = {
        "id": old.get("id"),
        "thesis": old.get("thesis"),
        "state": old.get("state"),
        "reason": reason,
        "alert_id": tied,
    }
    replacement["struct"] = nstruct
    replacement["badge"] = prediction_badge(replacement)
    return superseded, replacement


def prediction_hit_rate(rows: list[dict]) -> dict:
    """Window-bound hit/miss. Not the old llm_outlook / outcome_vs_bias 对照."""
    scored = [
        row
        for row in rows
        if row.get("state") in {"hit", "invalidated"}
    ]
    hits = sum(1 for row in scored if row.get("state") == "hit")
    slaps = sum(1 for row in scored if row.get("state") == "invalidated")
    total = len(scored)
    return {
        "label": PREDICTION_HIT_LABEL,
        "legacy": False,
        "samples": total,
        "hits": hits,
        "face_slaps": slaps,
        "rate_pct": round(100 * hits / total, 1) if total else None,
    }


def mark_legacy_hit_rate(hit_rate: dict | None) -> dict:
    payload = dict(hit_rate or {})
    payload["legacy"] = True
    payload["label"] = LEGACY_LABEL
    payload["disclaimer"] = LEGACY_DISCLAIMER
    return payload
