"""Build frozen event-card and focus-row payloads from real events + briefing."""

from __future__ import annotations

from typing import Any

from stock_pm.events.types import TrustedEvent
from stock_pm.ux_copy import display_title, is_english_headline, is_http_url

from .copy import (
    action_verbs,
    horizon_label,
    judgment_reason,
    main_path_copy,
    near_state,
    research_lean,
    strip_holdings,
)
from .mapping import (
    _analysis,
    _event_dict,
    event_scope,
    event_side,
    map_news_to_watchlist,
    ticker_impacts,
)
from .sort import split_events
from .strength import grade_impact


def _layer_text(analysis: dict[str, Any], name: str) -> str:
    chain = analysis.get("causal_chain") or {}
    for row in chain.get("layers") or []:
        if isinstance(row, dict) and row.get("id") == name:
            return str(row.get("text") or "").strip()
    return ""


def _layer_field(analysis: dict[str, Any], name: str, field: str) -> str:
    chain = analysis.get("causal_chain") or {}
    for row in chain.get("layers") or []:
        if isinstance(row, dict) and row.get("id") == name:
            return str(row.get(field) or "").strip()
    return ""


def _news_link(event: dict[str, Any]) -> dict[str, Any] | None:
    for source in event.get("sources") or []:
        url = source.get("source_url") or source.get("canonical_url")
        if is_http_url(url):
            title = source.get("title") or event.get("canonical_title") or "原文"
            label = "可点新闻" if is_english_headline(title) else f"可点新闻 · {title[:40]}"
            return {"url": url, "label": label}
    return None


def _ticker_chip(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row["symbol"],
        "impact_class": row.get("kind") or row.get("impact_class") or "gray",
        "kind": row.get("kind") or row.get("impact_class") or "gray",
        "label": row.get("label") or "",
        "bars": row.get("bars") or 1,
        "why": main_path_copy(row.get("why")) if row.get("why") else row.get("why"),
        "side": row.get("side"),
        "directness": row.get("directness"),
        "rank": row.get("rank", 9),
    }


def event_card(event: TrustedEvent | dict[str, Any], watch: list[dict[str, Any]] | None) -> dict[str, Any]:
    payload = _event_dict(event)
    analysis = _analysis(event)
    mapped = ticker_impacts(event, watch)
    side = event_side(analysis)
    withheld = (analysis.get("withheld") or {}).get("status") != "observable"
    closed = bool(analysis.get("closed_loop"))
    confidence = None
    bound = analysis.get("confidence")
    if isinstance(bound, dict):
        confidence = bound.get("text")
    conflict = int(analysis.get("conflict_count") or 0) > 0
    overall = grade_impact(
        side=side,
        hit=mapped[0] if mapped else None,
        closed_loop=closed,
        confidence=confidence,
        withheld=withheld or not mapped,
        conflict=conflict,
    )
    fact = _layer_text(analysis, "fact") or str((analysis.get("answers") or {}).get("what_happened") or "")
    change = _layer_text(analysis, "change") or str((analysis.get("change_vs_baseline") or {}).get("text") or "")
    expectation = _layer_text(analysis, "expectation")
    invalidation = _layer_field(analysis, "what_changes", "invalidation") or str(
        (analysis.get("invalidation") or {}).get("text") or payload.get("invalidation") or ""
    )
    why_strength = "；".join(
        f"{row['symbol']}：{row.get('why') or row.get('label')}" for row in mapped[:4]
    ) or "暂未形成对自选股的明确影响"
    transmit = str((analysis.get("mechanism") or {}).get("text") or "") or _layer_text(analysis, "impact")
    # Diagnostic withheld reasons stay in analysis for events/expand — never
    # as the main-path conclusion.
    what = strip_holdings((analysis.get("answers") or {}).get("what_happened") or "")
    conclusion = main_path_copy(what) or main_path_copy(expectation)
    if not conclusion:
        conclusion = (
            "当前条件不足，暂不形成明确方向"
            if (withheld or not closed)
            else "结论暂缺"
        )
    conclusion = main_path_copy(conclusion) or "结论暂缺"
    horizon = horizon_label(
        _layer_field(analysis, "expectation", "horizon")
        or payload.get("duration")
        or (analysis.get("horizon") or {}).get("text")
    )
    raw_title = payload.get("canonical_title") or payload.get("title") or "未命名事件"
    title = display_title(raw_title, fallback=conclusion[:40] if conclusion else "市场事件")
    return {
        "event_id": payload.get("event_id"),
        "title": title,
        "conclusion": conclusion[:160] if conclusion else "结论暂缺",
        "scope_label": event_scope(event, mapped),
        "impact_class": overall["kind"],
        "impact_label": overall["label"],
        "rank": overall["rank"],
        "horizon": horizon,
        "tickers": [_ticker_chip(row) for row in mapped],
        "mapping": mapped,
        "mapped": bool(mapped),
        "transmit": main_path_copy(transmit)[:180] if transmit else "",
        "basis": {
            "fact": fact or "事实暂缺",
            "change": change or "相对基线变化暂缺",
            "expectation": expectation or "预期暂缺",
            "why_strength": why_strength,
            "invalidation": invalidation or "失效条件暂缺",
        },
        "news": _news_link(payload),
        "closed_loop": closed,
        "published_at": payload.get("published_at") or payload.get("event_time"),
        "event_type": payload.get("event_type"),
        "side": side,
        "featured_ok": True,
        "source_kind": "trusted",
    }


def news_card(item: dict[str, Any], watch: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Ingested article card. Never featured; mapping is inspectable, not headline paste."""
    hits = map_news_to_watchlist(item, watch)
    stance = item.get("stance_line") or item.get("sentiment") or ""
    side = event_side({"direction": stance}) if stance else "watch"
    if side == "none":
        side = "watch"
    mapped: list[dict[str, Any]] = []
    for hit in hits:
        grade = grade_impact(side=side, hit=hit, closed_loop=False, withheld=False)
        if hit.get("mechanism") == "watchlist_ingested_article":
            grade = {
                **grade,
                "kind": "yellow",
                "label": "黄 · 留意",
                "bars": 2,
                "rank": 2,
                "side": "watch",
            }
        else:
            grade = {**grade, "kind": "gray", "label": "灰", "bars": 1, "rank": 3}
        mapped.append(
            {
                "symbol": hit["symbol"],
                "channel": hit.get("channel"),
                "mechanism": hit.get("mechanism"),
                "why": hit.get("why_relevant"),
                "inspectable": True,
                **grade,
            }
        )
    url = item.get("url") if is_http_url(item.get("url")) else None
    headline = strip_holdings(item.get("headline") or "") or "未命名新闻"
    summary = main_path_copy(item.get("summary") or "")
    title = display_title(headline, fallback=summary[:40] if summary else "相关新闻")
    news_label = "可点新闻" if is_english_headline(headline) else f"可点新闻 · {headline[:40]}"
    return {
        "event_id": None,
        "title": title[:120],
        "conclusion": (summary or title)[:160],
        "scope_label": (
            "公司级"
            if any(row.get("mechanism") == "watchlist_ingested_article" for row in mapped)
            else "行业级"
        ),
        "impact_class": mapped[0]["kind"] if mapped else "gray",
        "impact_label": mapped[0]["label"] if mapped else "灰",
        "rank": mapped[0]["rank"] if mapped else 9,
        "horizon": "期限暂缺",
        "tickers": [_ticker_chip(row) for row in mapped],
        "mapping": mapped,
        "mapped": bool(mapped),
        "transmit": main_path_copy((mapped[0].get("why") if mapped else "") or ""),
        "basis": {
            "fact": headline,
            "change": "来自新闻，尚未被官方事实确认",
            "expectation": "预期暂缺",
            "why_strength": "；".join(f"{row['symbol']}：{row.get('why')}" for row in mapped[:4])
            or "暂未形成对自选股的明确影响",
            "invalidation": "后续官方否认或财报证伪则作废",
        },
        "news": {"url": url, "label": news_label} if url else None,
        "closed_loop": False,
        "featured_ok": False,
        "source_kind": "news",
        "published_at": item.get("published_at"),
        "event_type": "news_article",
        "side": side,
    }


def build_event_cards(
    events: list[Any],
    watch: list[dict[str, Any]] | None,
    news: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cards = [event_card(event, watch) for event in events or []]
    news_cards = [news_card(item, watch) for item in news or []]
    trusted = split_events(cards)
    extra = split_events(news_cards)
    return {
        "featured": trusted["featured"],
        "carousel": trusted["carousel"] + extra["carousel"],
        "unmapped": trusted["unmapped"] + extra["unmapped"],
    }


def _briefing_side(row: dict[str, Any]) -> str:
    pred = row.get("prediction") or {}
    thesis = str(pred.get("thesis") or pred.get("therefore") or "")
    if pred.get("state") == "invalidated":
        return "bear"
    if "偏空" in thesis or "谨慎" in thesis:
        return "bear"
    if "偏多" in thesis or "补涨" in thesis or "续涨" in thesis:
        return "bull"
    env = row.get("environment") or {}
    one = str(env.get("one_liner") or row.get("env_half") or "")
    if "利空" in one or "走坏" in one:
        return "bear"
    if "利多" in one or "走好" in one:
        return "bull"
    tape = row.get("tape_analysis") or {}
    if (tape.get("weak_vs_env") or {}).get("status") == "weak":
        return "watch"
    return "none"


def focus_rows(
    watch: list[dict[str, Any]],
    briefing_rows: list[dict[str, Any]],
    event_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    by_symbol = {str(row.get("symbol") or "").upper(): row for row in briefing_rows or []}
    strongest: dict[str, dict[str, Any]] = {}
    for card in event_cards:
        for ticker in card.get("tickers") or []:
            symbol = str(ticker.get("symbol") or "").upper()
            prev = strongest.get(symbol)
            if prev is None or int(ticker.get("rank", 9)) < int(prev.get("rank", 9)):
                strongest[symbol] = {**ticker, "event_title": card.get("title"), "card": card}

    priority: list[dict[str, Any]] = []
    watch_group: list[dict[str, Any]] = []
    skip: list[dict[str, Any]] = []
    for item in watch or []:
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        brief = by_symbol.get(symbol) or {}
        mapped = strongest.get(symbol)
        attn = brief.get("attention") or {}
        side = _briefing_side(brief)
        direct = bool(mapped and mapped.get("directness") == "direct")
        if mapped:
            side = mapped.get("side") or side
            direct = mapped.get("directness") == "direct"
        changed = bool(
            attn.get("key") in {"severe_alert", "face_slap", "env_tape_conflict"}
            or (mapped and mapped.get("kind") in {"deep-green", "deep-red", "light-red", "light-green"})
        )
        if mapped and mapped.get("kind") in {"deep-green", "deep-red", "light-red"}:
            group = "priority"
            urgency = "bull" if (mapped.get("side") == "bull") else "bear"
        elif changed and side in {"bull", "bear"}:
            group = "priority"
            urgency = "bull" if side == "bull" else "bear"
        elif mapped and mapped.get("kind") in {"light-green", "yellow"}:
            group = "watch"
            urgency = "watch"
        elif mapped:
            group = "skip"
            urgency = "mute"
        else:
            group = "skip"
            urgency = "mute"
            side = "none" if side == "none" else side
        why = judgment_reason(
            (mapped.get("why") if mapped else None)
            or brief.get("row_thesis")
            or brief.get("env_half")
            or (brief.get("environment") or {}).get("one_liner")
            or ("暂未形成对公司级影响" if group == "skip" else "依据暂缺，维持观察")
        )
        hint = main_path_copy(
            (brief.get("prediction") or {}).get("missing_label")
            or "留意：是否出现可改变判断的新信息"
        )
        if hint and not str(hint).startswith("留意"):
            hint = f"留意：{hint}"
        row = {
            "symbol": symbol,
            "name": item.get("name") or symbol,
            "state": near_state(side, direct=direct) if group != "skip" or mapped else (
                "观望" if not mapped else near_state(side)
            ),
            "why": why[:120],
            "hint": hint[:80],
            "urgency": urgency,
            "href": f"/stock/{symbol}",
            "verbs": list(action_verbs(side)),
        }
        if group == "skip" and not mapped:
            row["state"] = "无新变化"
        if group == "priority":
            priority.append(row)
        elif group == "watch":
            watch_group.append(row)
        else:
            skip.append(row)
    return {
        "priority": priority,
        "watch": watch_group,
        "skip": skip,
        "skip_count": len(skip),
    }


def stock_judge(row: dict[str, Any], mapped: list[dict[str, Any]] | None) -> dict[str, Any]:
    side = _briefing_side(row)
    hit = None
    if mapped:
        hit = min(mapped, key=lambda item: int(item.get("rank", 9)))
        side = hit.get("side") or side
    lean = research_lean(
        side,
        confidence=(hit or {}).get("label"),
        horizon=None,
    )
    quote = judgment_reason(
        (hit or {}).get("why")
        or (row.get("environment") or {}).get("one_liner")
        or row.get("env_half")
        or row.get("row_thesis")
        or "依据暂缺，维持观察"
    )
    return {
        "stance": lean,
        "quote": quote[:160],
        "actions": list(action_verbs(side)),
        "impact_class": (hit or {}).get("kind") or "gray",
        "side": side,
    }
