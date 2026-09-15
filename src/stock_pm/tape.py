"""Knife 3 / Slice C: yesterday TapeAnalysis + ReviewNote.

Pure module (no database). Callers pass analyze_bars metrics plus an
EnvironmentSnapshot. This file judges volume-price, chips/S-R, break
aftermath, and the env link. It does not invent prediction bounds.
"""

from __future__ import annotations

from typing import Any

from .analytics import _number
from .environment import FLAG_LABELS as ENV_FLAG_LABELS
from .environment import _as_clause, news_stance

PUBLISH_STATES = ("published", "draft", "stale", "missing")
VOLUME_PRICE_FORMS = ("放量涨", "缩量涨", "放量跌", "缩量跌", "平量涨", "平量跌", "量价平稳")
AFTERMATHS = ("拉回", "续杀", "假突破", "续涨", "待确认", "未破位")
ENV_LINK_JUDGMENTS = ("诱多", "转势", "吸筹", "逃跑", "观察")

TAPE_FIELD_FLAGS = (
    "volume_price",
    "chips",
    "break",
    "env_link",
    "weak_vs_env",
)

FLAG_LABELS = {
    **ENV_FLAG_LABELS,
    "volume_price": "量价形态",
    "chips": "筹码与支撑压力",
    "break": "破位走法",
    "env_link": "环境对照",
    "weak_vs_env": "弱于环境",
    "tape": "昨盘",
    "review_note": "复盘总结",
}

TAPE_PLACEHOLDER = "昨盘结论未就绪"
TAPE_MISSING_LINE = "昨盘信息不足，当前判断主要依据消息与环境。"
REVIEW_UNEXPLAINED = "消息与情绪依据不足，暂不能解释昨天为何这样走。"

EXPAND_VOL = 1.2
SHRINK_VOL = 0.8
SIGNIFICANT_LAG_PP = 1.0
SECTOR_THEMES = frozenset({"semis", "consumer_electronics", "telecom"})
WEAK_MISSING_CLAUSE = "相对收益或破位路径不足，暂不能判断是否弱于环境。"


def flag_labels(flags: list[str]) -> str:
    return "、".join(FLAG_LABELS.get(flag, flag) for flag in flags)


def _price(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def _clean(text: str | None, fallback: str = "") -> str:
    cleaned = " ".join((text or "").replace("。", "").strip().split())
    return cleaned or fallback


def volume_price_form(
    day_change_pct: float | None,
    relative_volume: float | None,
) -> tuple[str | None, bool]:
    """Judgment, not a raw volume reprint. Empty inputs stay missing."""
    if day_change_pct is None or relative_volume is None:
        return None, True
    up = day_change_pct > 0
    down = day_change_pct < 0
    heavy = relative_volume >= EXPAND_VOL
    light = relative_volume < SHRINK_VOL
    if heavy and up:
        return "放量涨", False
    if light and up:
        return "缩量涨", False
    if heavy and down:
        return "放量跌", False
    if light and down:
        return "缩量跌", False
    if up:
        return "平量涨", False
    if down:
        return "平量跌", False
    return "量价平稳", False


def _ma_context(metrics: dict) -> str | None:
    close = _number(metrics.get("close"))
    bits: list[str] = []
    for key, label in (("ma5", "MA5"), ("ma20", "MA20"), ("ma50", "MA50"), ("ma200", "MA200")):
        value = _number(metrics.get(key))
        if close is None or value is None:
            bits.append(f"{label}不足")
            continue
        bits.append(f"{label}{'上方' if close >= value else '下方'}")
    if not bits or all(item.endswith("不足") for item in bits):
        return None
    return "收盘相对 " + "、".join(bits)


def _chip_block(metrics: dict) -> tuple[dict | None, bool]:
    poc = _number(metrics.get("poc_60d"))
    value_low = _number(metrics.get("value_area_low"))
    value_high = _number(metrics.get("value_area_high"))
    support = _number(metrics.get("support"))
    resistance = _number(metrics.get("resistance"))
    position = (metrics.get("position") or "").strip()
    if poc is None and support is None and resistance is None:
        return None, True
    band = None
    if poc is not None:
        band = f"60日成交密集成本 {_price(poc)}"
        if value_low is not None and value_high is not None:
            band += f"，价值区 {_price(value_low)}–{_price(value_high)}"
    bits: list[str] = []
    if band:
        bits.append(band)
    if support is not None or resistance is not None:
        bits.append(f"支撑 {_price(support)} / 压力 {_price(resistance)}")
    else:
        bits.append("支撑压力暂缺，暂不给出具体价位")
    if position:
        bits.append(position)
    ma_text = _ma_context(metrics)
    if ma_text:
        bits.append(ma_text)
    missing_sr = support is None or resistance is None
    return {
        "poc": poc,
        "value_low": value_low,
        "value_high": value_high,
        "support": support,
        "resistance": resistance,
        "band": band,
        "position": position or None,
        "ma_context": ma_text,
        "clause": "；".join(bits),
        "missing_sr": missing_sr,
    }, False


def _aftermath_from_breakout(
    breakout: str,
    support_test: str,
    close_location: float | None,
    form: str | None,
    segments: list[dict] | None,
) -> str:
    if "突破失败" in breakout or "冲高突破失败" in breakout:
        return "假突破"
    if "跌破后收回" in breakout or support_test == "盘中测试支撑后收回":
        return "拉回"
    if "有效跌破" in breakout or support_test == "收盘跌破最近支撑":
        largest_down = None
        largest_up = None
        for row in segments or []:
            change = _number(row.get("change_pct"))
            if change is None:
                continue
            if change < 0 and (largest_down is None or change < largest_down):
                largest_down = change
            if change > 0 and (largest_up is None or change > largest_up):
                largest_up = change
        if largest_up is not None and largest_down is not None and abs(largest_up) >= abs(largest_down) * 0.8:
            return "拉回"
        if close_location is not None and close_location <= 0.30:
            return "续杀"
        if form == "放量跌":
            return "续杀"
        return "续杀"
    if "有效突破" in breakout:
        if close_location is not None and close_location < 0.45:
            return "假突破"
        return "续涨"
    if "待确认" in breakout:
        return "待确认"
    return "未破位"


def _break_block(
    metrics: dict,
    form: str | None,
    segments: list[dict] | None,
) -> tuple[dict | None, bool]:
    breakout = (metrics.get("breakout") or "").strip()
    support_test = (metrics.get("support_test") or "").strip()
    if not breakout and not support_test:
        return None, True
    close_location = _number(metrics.get("close_location"))
    aftermath = _aftermath_from_breakout(
        breakout, support_test, close_location, form, segments
    )
    broken = aftermath != "未破位" or "突破" in breakout or "跌破" in breakout
    clause = f"{breakout or '破位状态不足'}"
    if support_test:
        clause += f"，{support_test}"
    clause += f"；破后走法{aftermath}"
    return {
        "status": breakout or None,
        "support_test": support_test or None,
        "broken": broken and aftermath != "未破位",
        "aftermath": aftermath,
        "clause": clause,
    }, False


def _env_news_stance(environment: dict | None) -> tuple[str | None, str | None]:
    env = environment or {}
    struct = env.get("struct") or {}
    news = struct.get("news") or {}
    dirs: list[str] = []
    bits: list[str] = []
    for key, label in (("macro", "宏观"), ("sector", "行业"), ("company", "公司")):
        layer = news.get(key) if isinstance(news, dict) else None
        if not isinstance(layer, dict):
            continue
        bias = layer.get("bias")
        headline = layer.get("headline")
        if bias:
            dirs.append(bias)
            piece = f"{label}{bias}"
            if headline:
                piece += f"（{_as_clause(str(headline), '')}）"
            bits.append(piece)
        elif layer.get("clause"):
            bits.append(f"{label}信息暂未形成对该股的明确影响")
    sentiment = struct.get("sentiment") if isinstance(struct.get("sentiment"), dict) else None
    atmosphere = (sentiment or {}).get("atmosphere")
    if atmosphere:
        bits.append(f"氛围{atmosphere}")
    year = ((struct.get("fundamentals") or {}).get("year_move") or {}) if isinstance(struct.get("fundamentals"), dict) else {}
    if year.get("clause"):
        bits.append(year["clause"])
    stance = news_stance(dirs)
    if stance is None and atmosphere:
        if atmosphere in {"恐慌", "承压"}:
            stance = "bear"
        elif atmosphere in {"过热", "补涨"}:
            stance = "bull"
    return ("，".join(bits) if bits else None), stance


def _form_direction(form: str | None) -> str | None:
    if not form:
        return None
    if "涨" in form:
        return "up"
    if "跌" in form:
        return "down"
    return None


def _env_link_block(
    *,
    form: str | None,
    break_block: dict | None,
    environment: dict | None,
) -> tuple[dict | None, bool]:
    env_text, env_stance = _env_news_stance(environment)
    if not env_text and env_stance is None:
        return None, True
    direction = _form_direction(form)
    aftermath = (break_block or {}).get("aftermath")
    inferred = True
    judgment = "观察"
    if direction == "up":
        if env_stance == "bear" or (environment or {}).get("struct", {}).get("sentiment", {}).get("atmosphere") in {
            "恐慌",
            "承压",
        }:
            judgment = "诱多"
        elif env_stance == "bull" and aftermath in {"续涨", "待确认"}:
            judgment = "转势"
        elif (environment or {}).get("struct", {}).get("sentiment", {}).get("atmosphere") == "过热":
            judgment = "诱多"
    elif direction == "down":
        atmosphere = ((environment or {}).get("struct") or {}).get("sentiment") or {}
        atm = atmosphere.get("atmosphere") if isinstance(atmosphere, dict) else None
        if env_stance == "bull" or atm == "过热":
            judgment = "吸筹" if form in {"缩量跌", "平量跌"} or aftermath == "拉回" else "观察"
        elif env_stance == "bear" or atm in {"恐慌", "承压"}:
            judgment = "逃跑" if form == "放量跌" or aftermath == "续杀" else "观察"
    why = {
        "诱多": "环境偏空或承压，昨盘却上涨，更像诱多而不是转势",
        "转势": "环境偏多且昨盘向上突破，更像结构转势",
        "吸筹": "环境并不配合大跌，缩量或拉回更像吸筹而不是逃跑",
        "逃跑": "环境偏空且昨盘放量下跌/续杀，更像逃跑",
        "观察": "环境与昨盘对得上的证据不够，只标观察",
    }[judgment]
    clause = f"{why}（推断：{judgment}）"
    if env_text:
        clause = f"对照环境（{env_text}）：{clause}"
    return {
        "judgment": judgment,
        "inferred": inferred,
        "env_text": env_text,
        "env_stance": env_stance,
        "clause": clause,
    }, False


def _structure_break(break_block: dict | None) -> bool | None:
    if not break_block:
        return None
    status = str(break_block.get("status") or "")
    aftermath = str(break_block.get("aftermath") or "")
    if "跌破" in status or aftermath == "续杀":
        return True
    return False


def _missing_weak_block(**extra: Any) -> dict:
    return _with_weak_facts(
        {
            "status": "missing",
            "inferred": False,
            "lags_significantly": extra.get("lags_significantly"),
            "structure_break": extra.get("structure_break"),
            "volume_down": extra.get("volume_down"),
            "structure_or_volume_down": extra.get("structure_or_volume_down"),
            "benchmark": extra.get("benchmark"),
            "benchmark_kind": extra.get("benchmark_kind"),
            "prior_stock_return_pct": extra.get("prior_stock_return_pct"),
            "prior_benchmark_return_pct": extra.get("prior_benchmark_return_pct"),
            "prior_relative_return_pct": extra.get("prior_relative_return_pct"),
            "confirm_5d_relative_return_pct": extra.get("confirm_5d_relative_return_pct"),
            "lag_threshold_pp": SIGNIFICANT_LAG_PP,
            "clause": extra.get("clause") or WEAK_MISSING_CLAUSE,
        }
    )


def weak_vs_env_facts_line(weak: dict | None) -> str:
    """UI/API contract: benchmark, prior relative, break-or-volume, conclusion."""
    weak = weak or {}
    bench = weak.get("benchmark") or "暂缺"
    rel = weak.get("prior_relative_return_pct")
    rel_s = "暂缺" if rel is None else f"{rel:+.1f}%"
    path = weak.get("structure_or_volume_down")
    if path is True:
        path_s = "是"
    elif path is False:
        path_s = "否"
    else:
        path_s = "暂缺"
    status = weak.get("status")
    if status == "weak":
        conc = "弱于环境"
    elif status == "not_weak":
        conc = "并非弱于环境"
    else:
        conc = "无法判定"
    return f"基准 {bench} · 昨收相对 {rel_s} · 破位或放量跌 {path_s} · 结论 {conc}"


def _with_weak_facts(block: dict) -> dict:
    block["facts_line"] = weak_vs_env_facts_line(block)
    return block


def _weak_vs_env(
    metrics: dict | None,
    form: str | None,
    break_block: dict | None,
) -> tuple[dict, bool]:
    """METRIC_LOGIC §0.3: relative lag vs sector/market + (break OR 放量跌).

    Tape-form vs env-stance conflict is not 弱于环境. Same-direction beta
    is not 弱于环境. Missing inputs stay missing — never invent 偏弱, never 推断.
    """
    metrics = metrics or {}
    stock_1d = _number(metrics.get("day_change_pct"))
    bench_1d = _number(metrics.get("benchmark_day_change_pct"))
    stock_5d = _number(metrics.get("return_5d_pct"))
    bench_5d = _number(metrics.get("benchmark_return_5d_pct"))
    name = metrics.get("benchmark_name")
    kind = metrics.get("benchmark_kind")
    relative_1d = (
        None if stock_1d is None or bench_1d is None else round(stock_1d - bench_1d, 2)
    )
    relative_5d = (
        None if stock_5d is None or bench_5d is None else round(stock_5d - bench_5d, 2)
    )
    volume_down = None if form is None else form == "放量跌"
    structure = _structure_break(break_block)
    lags = None if relative_1d is None else relative_1d <= -SIGNIFICANT_LAG_PP
    path_true = structure is True or volume_down is True
    path_false = structure is False and volume_down is False
    facts = {
        "benchmark": name,
        "benchmark_kind": kind,
        "prior_stock_return_pct": stock_1d,
        "prior_benchmark_return_pct": bench_1d,
        "prior_relative_return_pct": relative_1d,
        "confirm_5d_relative_return_pct": relative_5d,
        "lags_significantly": lags,
        "structure_break": structure,
        "volume_down": volume_down,
        "structure_or_volume_down": True if path_true else False if path_false else None,
        "lag_threshold_pp": SIGNIFICANT_LAG_PP,
        "inferred": False,
    }
    if relative_1d is None or not name:
        return _missing_weak_block(**facts), True
    if lags and not path_true and not path_false:
        return _missing_weak_block(
            **facts,
            clause="破位路径或放量下跌材料不足，暂不能判断是否弱于环境。",
        ), True
    five_led = relative_5d is not None and relative_5d > 0
    if lags and path_true and not five_led:
        bits = [f"相对{name}昨收{_pct(relative_1d)}，显著落后"]
        if structure:
            bits.append("结构破位")
        if volume_down:
            bits.append("放量下跌")
        if relative_5d is not None:
            bits.append(f"近5日相对{_pct(relative_5d)}确认落后")
        clause = "；".join(bits) + "；判定弱于环境。"
        return _with_weak_facts({**facts, "status": "weak", "clause": clause}), False
    if (
        not lags
        and stock_1d is not None
        and bench_1d is not None
        and stock_1d < 0
        and bench_1d < 0
    ):
        clause = (
            f"相对{name}昨收{_pct(relative_1d)}，未显著落后；"
            "与基准同向下跌只是同向贝塔，不等于弱于环境。"
        )
    elif lags and five_led:
        clause = (
            f"昨收相对{name}落后，但近5日相对{_pct(relative_5d)}未确认，"
            "不判定弱于环境。"
        )
    elif lags and not path_true:
        clause = (
            f"相对{name}昨收落后，但无结构破位也无放量下跌，不判定弱于环境。"
        )
    else:
        clause = (
            f"相对{name}昨收{_pct(relative_1d)}，"
            "不满足显著落后且（破位或放量跌），不判定弱于环境。"
        )
    return _with_weak_facts({**facts, "status": "not_weak", "clause": clause}), False


def env_tape_conflict_sentence(environment: dict | None, tape: dict | None) -> str:
    """One 环境 → 昨盘 → 因此 sentence. Never two pretty columns."""
    env_text, _ = _env_news_stance(environment)
    env_disp = _as_clause(env_text or (environment or {}).get("one_liner"), "结论不足")
    form = None
    if tape:
        form = (tape.get("volume_price") or {}).get("form") or tape.get("one_liner")
    tape_disp = _as_clause(form, "结论不足")
    return (
        f"环境：{env_disp}；"
        f"昨盘：{tape_disp}；"
        f"因此：环境与昨盘方向相反，当前先按昨盘收盘读。"
    )


def is_env_tape_conflict_sentence(text: str | None) -> bool:
    if not text:
        return False
    i_env = text.find("环境")
    i_tape = text.find("昨盘")
    i_so = text.find("因此")
    if min(i_env, i_tape, i_so) < 0 or not (i_env < i_tape < i_so):
        return False
    first_stop = text.find("。")
    if first_stop != -1 and first_stop < i_so:
        return False
    return "方向相反" in text


def _publish_state(*, missing: list[str], has_form: bool, session: dict | None) -> str:
    if session and session.get("is_trading_day") is False:
        return "stale"
    if not has_form:
        return "missing"
    if len(missing) >= 2:
        return "draft"
    return "published"


def snapshot_from_row(row: dict | None) -> dict | None:
    if not row:
        return None
    flags = row.get("missing_flags")
    if flags is None:
        flags = row.get("missingFlags") or []
    as_of = row.get("as_of_date")
    created = row.get("created_at")
    struct = row.get("struct") or {}
    return {
        "id": row.get("id"),
        "as_of_date": str(as_of)[:10] if as_of else None,
        "symbol": row.get("symbol"),
        "one_liner": row.get("one_liner"),
        "conclusion": row.get("conclusion") or row.get("one_liner"),
        "volume_price": struct.get("volume_price"),
        "chips": struct.get("chips"),
        "break": struct.get("break"),
        "env_link": struct.get("env_link"),
        "weak_vs_env": struct.get("weak_vs_env"),
        "struct": struct,
        "missingFlags": list(flags),
        "publishState": row.get("publish_state") or row.get("publishState") or "draft",
        "prediction_ready": False,
        "conflict": bool(struct.get("conflict")) if isinstance(struct, dict) else False,
        "created_at": str(created) if created else None,
        "source": "stored",
    }


def review_note_from_row(row: dict | None) -> dict | None:
    if not row:
        return None
    flags = row.get("missing_flags")
    if flags is None:
        flags = row.get("missingFlags") or []
    as_of = row.get("as_of_date")
    created = row.get("created_at")
    return {
        "id": row.get("id"),
        "as_of_date": str(as_of)[:10] if as_of else None,
        "symbol": row.get("symbol"),
        "summary": row.get("summary"),
        "explanation": row.get("explanation"),
        "unexplained": bool(row.get("unexplained")),
        "struct": row.get("struct") or {},
        "missingFlags": list(flags),
        "publishState": row.get("publish_state") or row.get("publishState") or "draft",
        "prediction_ready": False,
        "created_at": str(created) if created else None,
        "source": "stored",
    }


def failed_tape(symbol: str, as_of_date: str | None, error: str) -> dict:
    line = TAPE_MISSING_LINE
    return {
        "as_of_date": as_of_date,
        "symbol": symbol.upper(),
        "one_liner": line,
        "conclusion": line,
        "volume_price": None,
        "chips": None,
        "break": None,
        "env_link": None,
        "weak_vs_env": _missing_weak_block(),
        "struct": {
            "volume_price": None,
            "chips": None,
            "break": None,
            "env_link": None,
            "weak_vs_env": _missing_weak_block(),
            "error": error,
            "conflict": False,
        },
        "missingFlags": list(TAPE_FIELD_FLAGS),
        "publishState": "missing",
        "prediction_ready": False,
        "conflict": False,
        "source": "failed",
    }


def failed_review_note(symbol: str, as_of_date: str | None, error: str) -> dict:
    return {
        "as_of_date": as_of_date,
        "symbol": symbol.upper(),
        "summary": "复盘总结暂缺，尚不能解释昨天为何这样走。",
        "explanation": REVIEW_UNEXPLAINED,
        "unexplained": True,
        "struct": {"error": error},
        "missingFlags": ["review_note"],
        "publishState": "missing",
        "prediction_ready": False,
        "source": "failed",
    }


def synthesize_tape_analysis(
    *,
    as_of_date: str | None,
    symbol: str,
    metrics: dict | None = None,
    environment: dict | None = None,
    segments: list[dict] | None = None,
    session: dict | None = None,
    source: str = "live",
) -> dict:
    """Yesterday tape for ACCEPTANCE_M2 Q1–Q4. Honest missing, no fake form."""
    symbol_u = symbol.upper()
    metrics = metrics or {}
    missing: list[str] = []

    form, form_missing = volume_price_form(
        _number(metrics.get("day_change_pct")),
        _number(metrics.get("relative_volume")),
    )
    if form_missing:
        missing.append("volume_price")
        volume_block = None
    else:
        rel = _number(metrics.get("relative_volume"))
        change = _number(metrics.get("day_change_pct"))
        tape_text = _clean(metrics.get("tape"))
        clause = f"{form}（日涨跌 {_pct(change)}，量比 {rel:.2f}x）"
        if tape_text:
            clause += f"：{tape_text}"
        volume_block = {
            "form": form,
            "day_change_pct": change,
            "relative_volume": rel,
            "clause": clause,
        }

    chips, chips_missing = _chip_block(metrics)
    if chips_missing:
        missing.append("chips")
    brk, break_missing = _break_block(metrics, form, segments)
    if break_missing:
        missing.append("break")
    env_link, env_missing = _env_link_block(
        form=form, break_block=brk, environment=environment
    )
    if env_missing:
        missing.append("env_link")
    weak, weak_missing = _weak_vs_env(metrics, form, brk)
    if weak_missing:
        missing.append("weak_vs_env")

    env_stance = (env_link or {}).get("env_stance")
    direction = _form_direction(form)
    conflict = (direction == "up" and env_stance == "bear") or (
        direction == "down" and env_stance == "bull"
    )
    has_form = volume_block is not None
    if session and session.get("is_trading_day") is False:
        label = session.get("label") or "美股休市"
        one_liner = f"{as_of_date or ''} {label}，今日休市，沿用最近交易日盘面作为背景。".strip()
        conclusion = one_liner
        publish_state = "stale"
    elif not has_form:
        one_liner = TAPE_MISSING_LINE
        conclusion = one_liner
        publish_state = "missing"
    else:
        bits = [form or ""]
        if brk and brk.get("aftermath"):
            bits.append(brk["aftermath"])
        if chips and chips.get("band"):
            bits.append(chips["band"])
        elif "chips" in missing:
            bits.append("筹码暂缺")
        if env_link and env_link.get("judgment"):
            bits.append(f"{env_link['judgment']}（推断）")
        one_liner = "，".join(bit for bit in bits if bit)
        conclusion = volume_block["clause"]
        if brk:
            conclusion += f"；{brk['clause']}"
        publish_state = _publish_state(missing=missing, has_form=True, session=session)

    answers = {
        "q1_volume_price": (volume_block or {}).get("form")
        or "量价形态暂缺，暂不判断放量或缩量",
        "q2_chips": (chips or {}).get("clause") or "筹码带与支撑压力暂缺，暂不给出具体价位",
        "q3_break": (brk or {}).get("clause") or "破位走法暂缺，暂不判断拉回或续杀",
        "q4_env_link": (env_link or {}).get("clause")
        or "环境依据不足，暂不判断诱多、转势、吸筹或逃跑",
        "q5_weak_vs_env": (weak or {}).get("clause") or WEAK_MISSING_CLAUSE,
    }
    struct = {
        "volume_price": volume_block,
        "chips": chips,
        "break": brk,
        "env_link": env_link,
        "weak_vs_env": weak,
        "answers": answers,
        "conflict": conflict,
        "session": session or None,
    }
    return {
        "as_of_date": as_of_date,
        "symbol": symbol_u,
        "one_liner": one_liner,
        "conclusion": conclusion,
        "volume_price": volume_block,
        "chips": chips,
        "break": brk,
        "env_link": env_link,
        "weak_vs_env": weak,
        "struct": struct,
        "missingFlags": missing,
        "publishState": publish_state,
        "prediction_ready": False,
        "conflict": conflict,
        "source": source,
    }


def synthesize_review_note(
    *,
    as_of_date: str | None,
    symbol: str,
    tape: dict | None = None,
    environment: dict | None = None,
    session: dict | None = None,
    source: str = "live",
) -> dict:
    """Vernacular summary from tape + causal chain, or honest 解释不了."""
    symbol_u = symbol.upper()
    tape = tape or {}
    volume = tape.get("volume_price") or {}
    brk = tape.get("break") or {}
    chips = tape.get("chips") or {}
    env_link = tape.get("env_link") or {}
    form = volume.get("form")
    missing: list[str] = []

    if not form:
        missing.append("volume_price")
        summary = "昨天盘面量价不足，复盘总结暂缺，尚不能解释昨天为何这样走。"
    else:
        change = volume.get("day_change_pct")
        aftermath = brk.get("aftermath")
        chip_bit = chips.get("band") or ("筹码暂缺" if not chips else None)
        parts = [f"昨天{symbol_u}{form}"]
        if change is not None:
            parts.append(f"收盘{_pct(change)}")
        if aftermath:
            parts.append(f"破后{aftermath}")
        if chip_bit:
            parts.append(chip_bit)
        summary = "，".join(parts) + "。"

    env_text, env_stance = _env_news_stance(environment)
    has_env_evidence = bool(env_text and env_stance) or bool(
        env_text and ((environment or {}).get("struct") or {}).get("sentiment")
    )
    if session and session.get("is_trading_day") is False:
        explanation = f"{as_of_date or ''} {session.get('label') or '美股休市'}，今日休市，沿用最近交易日解释作为背景。".strip()
        unexplained = False
        publish_state = "stale"
    elif not form:
        explanation = REVIEW_UNEXPLAINED
        unexplained = True
        publish_state = "missing"
    elif not has_env_evidence:
        explanation = REVIEW_UNEXPLAINED
        unexplained = True
        missing.append("env_link")
        publish_state = "draft"
    else:
        env_disp = _as_clause(env_text, "结论不足")
        tape_disp = _as_clause(
            f"{form}，{brk.get('aftermath') or '未破位'}", "结论不足"
        )
        therefore = _as_clause(
            (env_link or {}).get("clause") or "证据不够，暂不能解释昨天为何这样走",
            "证据不够，暂不能解释昨天为何这样走",
        )
        explanation = f"环境：{env_disp}。昨盘：{tape_disp}。因此：{therefore}。"
        unexplained = False
        publish_state = tape.get("publishState") or "published"

    return {
        "as_of_date": as_of_date,
        "symbol": symbol_u,
        "summary": summary,
        "explanation": explanation,
        "unexplained": unexplained,
        "struct": {
            "from_tape": tape.get("one_liner"),
            "env_text": env_text,
        },
        "missingFlags": missing,
        "publishState": publish_state,
        "prediction_ready": False,
        "source": source,
    }


def tape_half_display(tape: dict | None) -> str:
    """Overview 昨盘半句: real one_liner, honest missing, never a fake form."""
    if not tape:
        return TAPE_PLACEHOLDER
    state = tape.get("publishState")
    line = (tape.get("one_liner") or "").strip()
    if state == "missing" or not line:
        return TAPE_MISSING_LINE if state == "missing" else TAPE_PLACEHOLDER
    if line == TAPE_MISSING_LINE:
        return line
    return line
