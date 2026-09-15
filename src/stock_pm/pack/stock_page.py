"""Stock-page view-model: five frozen sections + folded materials."""

from __future__ import annotations

from typing import Any

from .cards import event_card, stock_judge
from .copy import action_verbs, judgment_headline, judgment_reason, main_path_copy, strip_holdings


def _yesterday_line(history: list[dict[str, Any]] | None, today: dict[str, Any] | None) -> tuple[str, str, bool]:
    rows = list(history or [])
    today_raw = (today or {}).get("one_liner") or (today or {}).get("synthesis") or ""
    today_line = judgment_headline(today_raw, fallback="判断暂缺")
    today_disp = today_line if today_line.startswith("今") else f"今：{today_line}"
    if len(rows) >= 2:
        older = rows[1]
        prior_raw = older.get("one_liner") or older.get("synthesis") or ""
        prior_line = judgment_headline(prior_raw, fallback="数据暂缺")
        prior_disp = prior_line if prior_line.startswith("昨") else f"昨：{prior_line}"
        changed = prior_line != today_line and "暂缺" not in prior_line and "暂缺" not in today_line
        return prior_disp, today_disp, changed
    if len(rows) == 1 and today:
        return "昨：仅有一条环境快照，不能对照", today_disp, False
    return "昨：数据暂缺", today_disp, False


def build_stock_payload(
    *,
    symbol: str,
    watch: list[dict[str, Any]],
    briefing_row: dict[str, Any] | None,
    events: list[Any],
    environment: dict[str, Any] | None,
    env_history: list[dict[str, Any]] | None,
    tape: dict[str, Any] | None,
    prediction: dict[str, Any] | None,
    decision: dict[str, Any] | None,
    name: str | None = None,
) -> dict[str, Any]:
    symbol_u = symbol.upper()
    live = next((row for row in watch or [] if str(row.get("symbol") or "").upper() == symbol_u), None)
    cards = [event_card(event, watch) for event in events or []]
    mapped: list[dict[str, Any]] = []
    for card in cards:
        mapped.extend(card.get("mapping") or [])
    row = dict(briefing_row or {})
    if environment:
        row.setdefault("environment", environment)
    if tape:
        row.setdefault("tape_analysis", tape)
    if prediction:
        row.setdefault("prediction", prediction)
    judge = stock_judge(row, mapped)
    yesterday, today_line, changed = _yesterday_line(env_history, environment or row.get("environment"))
    mid_unchanged = True
    mid_text = "中期逻辑暂缺对照，维持观察"
    thesis = (decision or {}).get("thesis") or {}
    if thesis.get("direction") and not (decision or {}).get("cannot_form_judgment"):
        mid_text = "中期主线未改；仅近端弹性可能变化" if changed else "中期与近端都未形成改写"
        mid_unchanged = True
    drivers = []
    for index, card in enumerate(sorted(cards, key=lambda item: int(item.get("rank", 9)))[:3], start=1):
        tick = next((row for row in (card.get("tickers") or []) if row.get("symbol") == symbol_u), None)
        drivers.append(
            {
                "rank": index,
                "impact_class": (tick or {}).get("impact_class") or card.get("impact_class"),
                "impact_label": (tick or {}).get("label") or card.get("impact_label"),
                "title": card.get("title"),
                "why": main_path_copy((tick or {}).get("why") or card.get("transmit") or "依据暂缺"),
            }
        )
    if not drivers:
        kernel_drivers = list(((decision or {}).get("thesis") or {}).get("bull_drivers") or []) + list(
            ((decision or {}).get("thesis") or {}).get("bear_drivers") or []
        )
        for index, item in enumerate(kernel_drivers[:3], start=1):
            text = item.get("text") if isinstance(item, dict) else str(item)
            drivers.append(
                {
                    "rank": index,
                    "impact_class": "gray",
                    "impact_label": "灰",
                    "title": main_path_copy(text)[:80],
                    "why": "基于已有判断链",
                }
            )
    risks = []
    for card in cards[:3]:
        inv = (card.get("basis") or {}).get("invalidation")
        if inv:
            risks.append(main_path_copy(inv))
    disagreement = ((decision or {}).get("thesis") or {}).get("key_disagreement")
    if disagreement:
        risks.append(main_path_copy(disagreement))
    if (tape or {}).get("weak_vs_env") and (tape["weak_vs_env"] or {}).get("status") == "weak":
        risks.append("相对环境偏弱，判断并非全面同向")
    if not risks:
        risks = ["尚无明确反证；出现与当前判断相反的公司或行业变化时需重估"]
    observe = main_path_copy(
        (cards[0].get("basis") or {}).get("expectation") if cards else ""
    ) or "观察条件暂缺：留意是否出现可改变判断的新信息"
    invalidate = main_path_copy(
        ((decision or {}).get("thesis") or {}).get("invalidation")
        or ((cards[0].get("basis") or {}).get("invalidation") if cards else "")
        or (prediction or {}).get("thesis")
        or "失效条件暂缺：出现与当前判断相反的硬证据时原判断作废"
    )
    delta = "近端判断有变化；中期未动" if changed else "判断未形成可对照变化"
    if mapped and changed:
        delta = f"近端因「{(mapped[0].get('why') or cards[0].get('title') if cards else '')}」调整；中期未动"
    return {
        "symbol": symbol_u,
        "name": (live or {}).get("name") or name or symbol_u,
        "on_watchlist": live is not None,
        "judge": judge,
        "thesis_change": {
            "yesterday": yesterday if yesterday.startswith("昨") else f"昨：{yesterday}",
            "today": today_line if today_line.startswith("今") else f"今：{today_line}",
            "changed": changed,
            "delta": delta,
            "reason": judgment_reason((mapped[0].get("why") if mapped else None) or "没有新的可核对信息"),
            "midterm": {"unchanged": mid_unchanged, "text": mid_text},
            "today_action": {
                "verbs": list(action_verbs(judge["side"])),
                "hint": main_path_copy(
                    (cards[0].get("basis") or {}).get("invalidation") if cards else "留意：是否出现可改变判断的新信息"
                ),
            },
        },
        "drivers": drivers,
        "risks": risks[:5],
        "observe": observe[:200],
        "invalidate": invalidate[:200],
        "events": cards,
    }
