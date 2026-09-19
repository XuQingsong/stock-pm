"""One-shot offline materialize: research_* / related tables → persisted brain_*.

Page views keep reading BrainStore only. This job never calls GLM, never
schedules a rerun, and stops after the upserts.

Prefer existing JSON / table fields. If a Brain field cannot be copied or
mechanically classified from those fields, leave it empty (see GAPS).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from typing import Any

from stock_pm.research.llm_reason import compact_text

from .product_read import ISSUER_ACTION, MARKET_WIDE_KEYS, THEME_DISPLAY_ZH, is_trigger_event, theme_key
from .store import BrainStore


SOURCE_KIND = "research_materialize"
MISSING_ENV = "环境信息暂缺"
PLACEHOLDER_ENV = ("环境信息暂缺", "当前判断置信度有限")

# Fields this job will not invent. Empty is honest.
GAPS = {
    "causal_edges": "No structural graph is synthesized. Existing research has no persisted causal edges.",
    "exposures": "Written only when a key_economic_driver already has mechanism / valuation_channel text.",
    "scenarios": "brain_scenarios stay empty unless a later mapper is added; valuation cases are copied onto valuation_state.supporting_data only.",
    "financial_impacts": "Not derived. Research valuations do not carry claim-linked impact rows.",
    "what_would_invalidate": "Copied from assumption.invalidation_condition or thesis.invalidation_conditions only.",
    "price_divergences": "Not inferred from tape. Requires an existing unresolved-price object.",
    "cross_asset_summary": "Stays empty until persisted cross-asset rows exist.",
    "sector_summary": "Stays empty until persisted sector rows exist.",
    "llm_fields": "Competing-hypothesis how_to_test / impact_if_true copied only if already present. No GLM rewrite.",
    "unlinked_evidence": "research_evidence rows that are not linked to an assumption or snapshot are not reinterpreted as claims.",
}

THEME_KIND = {
    "ai_capex_expectations": ("ai_demand", "ai_demand"),
    "sector_macro": ("sector_macro", "sector_macro"),
    "real_yields": ("real_yields", "real_yields"),
}

# Stable labels that product_read.theme_key still clusters (needles in the name).
MARKET_THEME_LABELS = {
    "ai_capex_expectations": "AI capex expectations",
    "real_yields": "real yields",
    "sector_macro": "sector / macro",
}

# Extra phrases already in research JSON / Chinese desk copy that theme_key's tighter list misses.
MATERIALIZE_THEME_NEEDLES = (
    (
        "ai_capex_expectations",
        (
            "ai demand",
            "ai capex",
            "ai spend",
            "ai spending",
            "ai infrastructure",
            "capital expenditure",
            "hyperscaler",
            "hyperscale",
            "custom silicon",
            "asic",
            "xpu",
            "ai 资本",
            "ai资本",
            "资本开支",
            "算力",
            "ai 开支",
            "ai开支",
        ),
    ),
    (
        "real_yields",
        (
            "real yield",
            "real yields",
            "treasury",
            "rates",
            "利率",
            "美债",
            "fed funds",
            "fomc",
            "国债收益率",
            "收益率",
            "降息",
            "加息",
            "实际利率",
        ),
    ),
    (
        "sector_macro",
        ("sector", "macro", "sox", "semiconductor cycle", "板块", "半导体周期", "sector rotation"),
    ),
)

ENV_THEME_TAGS = {
    "rates": "real_yields",
    "real_yields": "real_yields",
    "semis": "sector_macro",
    "high_valuation_growth": "sector_macro",
}

MARKET_FRAME_RE = re.compile(
    r"market (is |are )?(trading|pricing)|live market|market variable|cross[- ]asset|"
    r"across (the )?(tape|semis|names|sector)|tape is (still )?trading|"
    r"市场在交易|市场变量|市场主轴|盘面(仍)?在交易|资本开支预期|ai capex expectation|"
    r"降息预期|加息预期|收益率",
    re.I,
)

# Issuer execution / product-delivery language. Not a market-wide theme unless
# the same sentence also names capex / rates / tape-pricing (see MARKET_FRAME_RE).
COMPANY_EXECUTION_RE = re.compile(
    r"management can deliver|management (is )?(executing|delivering)|"
    r"\b(ai )?accelerators?\b|custom silicon (revenue|backlog|guide)|"
    r"兑现(指引|指导|业绩)|管理层.{0,16}(兑现|交付|执行)",
    re.I,
)

DESK_SPLIT_RE = re.compile(r"(?:盘面|消息|因此)[：:]")

CLAIM_STATUS = {
    "unverified": "unverified",
    "strengthened": "strongly_supported",
    "unchanged": "partially_supported",
    "weakened": "challenged",
    "broken": "contradicted",
}

HYP_STATUS = {
    "unverified": "candidate",
    "strengthened": "supported",
    "unchanged": "active",
    "weakened": "weakened",
    "broken": "rejected",
}

SLUG_RE = re.compile(r"[^a-z0-9]+")


def parse_tickers(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.replace(";", ",").split(",")
    else:
        parts = list(raw)
    out: list[str] = []
    for part in parts:
        symbol = str(part or "").strip().upper()
        if symbol and symbol not in out:
            out.append(symbol)
    return out


def _research_store(research: Any) -> Any:
    return getattr(research, "store", research)


def _slug(value: Any, *, limit: int = 40) -> str:
    text = SLUG_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return (text or "item")[:limit]


def _band_confidence(value: Any) -> str:
    if value is None or value == "":
        return "low"
    token = str(value).strip().lower()
    if token in {"high", "medium", "low"}:
        return token
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "low"
    if number >= 0.75:
        return "high"
    if number >= 0.4:
        return "medium"
    return "low"


def _importance(value: Any) -> str:
    token = str(value or "medium").strip().lower()
    if token in {"critical", "high"}:
        return "high"
    if token == "low":
        return "low"
    return "medium"


def _collect_text(value: Any, *, limit: int = 8, min_len: int = 8) -> list[str]:
    preferred = (
        "statement",
        "hypothesis",
        "summary",
        "narrative",
        "description",
        "text",
        "one_liner",
        "row_thesis",
        "synthesis",
        "core_thesis",
        "industry",
        "cycle",
        "demand",
        "outlook",
        "comment",
        "why_it_matters",
        "driver",
        "name",
        "title",
        "fact",
        "legal_name",
        "sector",
    )
    out: list[str] = []

    def walk(item: Any, *, preferred_only: bool = False) -> None:
        if len(out) >= limit:
            return
        if isinstance(item, str):
            text = compact_text(item, 400)
            if len(text) >= min_len and not any(token in text for token in PLACEHOLDER_ENV):
                if text not in out:
                    out.append(text)
            return
        if isinstance(item, dict):
            for key in preferred:
                if key in item:
                    walk(item.get(key))
            if not preferred_only:
                for nested in item.values():
                    if isinstance(nested, (dict, list, str)):
                        walk(nested)
            return
        if isinstance(item, list):
            for nested in item[:16]:
                walk(nested)

    walk(value, preferred_only=True)
    if not out:
        walk(value, preferred_only=False)
    return out


def _first_text(*values: Any, limit: int = 280) -> str:
    for value in values:
        if isinstance(value, (list, tuple)):
            for item in value:
                text = compact_text(item, limit)
                if len(text) >= 8:
                    return text
            continue
        text = compact_text(value, limit)
        if len(text) >= 8:
            return text
    return ""


def _theme_row(**fields: Any) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value not in (None, "")}


def _theme_for(row: dict[str, Any]) -> str | None:
    return _classify_market_theme(
        row.get("name"),
        row.get("statement"),
        row.get("hypothesis"),
        extra=row,
    )


def _theme_needles(theme: str) -> tuple[str, ...]:
    for token, needles in MATERIALIZE_THEME_NEEDLES:
        if token == theme:
            return needles
    return ()


def _desk_fragments(text: str) -> list[str]:
    raw = compact_text(text, 400)
    if not raw:
        return []
    parts = [compact_text(part.strip("；;，, "), 240) for part in DESK_SPLIT_RE.split(raw)]
    return [part for part in parts if part] or [raw]


def _extract_theme_copy(texts: list[str], theme: str) -> tuple[str, str]:
    """Name/statement from existing desk text. No GLM paraphrase."""
    needles = _theme_needles(theme)
    hits: list[str] = []
    for text in texts:
        for fragment in _desk_fragments(text):
            lowered = fragment.lower()
            if needles and any(needle in lowered for needle in needles) and fragment not in hits:
                hits.append(fragment)
    statement = hits[0] if hits else compact_text(next((item for item in texts if compact_text(item, 8)), ""), 280)
    name = compact_text(min(hits, key=len) if hits else statement, 40)
    if not name:
        name = THEME_DISPLAY_ZH.get(theme) or MARKET_THEME_LABELS.get(theme) or theme
    return name, compact_text(statement, 280)


def _is_company_execution_only(blob: str) -> bool:
    """Issuer delivery / accelerator guidance — not a market-wide theme by itself."""
    if not COMPANY_EXECUTION_RE.search(blob):
        return False
    if MARKET_FRAME_RE.search(blob):
        return False
    lowered = blob.lower()
    market_wide = (
        "ai capex",
        "资本开支",
        "降息",
        "加息",
        "收益率",
        "利率",
        "real yield",
        "hyperscaler",
        "market is trading",
        "市场在交易",
        "市场主轴",
    )
    return not any(token in lowered for token in market_wide)


def _needle_themes(blob: str) -> list[str]:
    lowered = blob.lower()
    out: list[str] = []
    for token, needles in MATERIALIZE_THEME_NEEDLES:
        if any(needle in lowered for needle in needles) and token not in out:
            out.append(token)
    return out


def _kind_for_theme(theme: str | None) -> tuple[str, str]:
    if not theme:
        return "other", "other"
    if theme in THEME_KIND:
        return THEME_KIND[theme]
    if theme in MARKET_WIDE_KEYS:
        mapped = MARKET_WIDE_KEYS[theme]
        return THEME_KIND.get(mapped, (theme, theme))
    return "other", theme


def _is_company_specific_trigger(row: dict[str, Any] | None) -> bool:
    """Issuer print / capex headline. Market-framed theme statements that cite issuers stay themes."""
    item = row or {}
    if item.get("event_id") or str(item.get("event_type") or "").lower() in {
        "capex",
        "guidance",
        "earnings",
        "product",
        "customer",
    }:
        return True
    if str(item.get("kind") or "").lower() == "company_specific":
        return True
    blob = " ".join(str(item.get(name) or "") for name in ("name", "title", "statement", "hypothesis", "reason"))
    if not ISSUER_ACTION.search(blob):
        return False
    return MARKET_FRAME_RE.search(blob) is None


def _classify_market_theme(*texts: Any, extra: dict[str, Any] | None = None) -> str | None:
    found = _classify_all_market_themes(*texts, extra=extra)
    return found[0] if found else None


def _classify_all_market_themes(*texts: Any, extra: dict[str, Any] | None = None) -> list[str]:
    extra = dict(extra or {})
    parts = [str(text).strip() for text in texts if text and str(text).strip()]
    blob = " ".join(parts + [str(extra.get(name) or "") for name in ("name", "statement", "hypothesis", "title")])
    if len(compact_text(blob, 400)) < 8:
        return []
    if _is_company_execution_only(blob):
        return []
    probe = {
        **extra,
        "name": extra.get("name") or blob,
        "statement": extra.get("statement") or blob,
        "hypothesis": extra.get("hypothesis") or blob,
        "title": extra.get("title") or "",
    }
    # Drop state_type so product_read.theme_key cannot slug the raw Chinese desk sentence.
    probe.pop("state_type", None)
    if _is_company_specific_trigger(probe):
        return []
    out: list[str] = []
    for tag in extra.get("theme_tags") or extra.get("themes") or []:
        mapped = ENV_THEME_TAGS.get(str(tag).lower())
        if mapped and mapped not in out:
            out.append(mapped)
    key = theme_key({k: v for k, v in probe.items() if k not in {"event_type", "state_type", "state_key"}})
    if key in MARKET_WIDE_KEYS:
        mapped = MARKET_WIDE_KEYS[key]
        if mapped not in out:
            out.append(mapped)
    for token in _needle_themes(blob):
        if token not in out:
            out.append(token)
    return [token for token in out if token in MARKET_THEME_LABELS]


def _theme_label(theme: str) -> str:
    return MARKET_THEME_LABELS.get(theme) or theme.replace("_", " ")


def _persistable_theme_text(text: str, theme: str) -> str:
    """Keep issuer-action headlines off hyp/attention fields so product_read.theme_key can cluster."""
    label = _theme_label(theme)
    if is_trigger_event({"name": text, "statement": text, "hypothesis": text, "reason": text}):
        return label
    return text


def _walk_theme_tags(value: Any, out: list[str]) -> None:
    if isinstance(value, dict):
        raw = value.get("themes") if "themes" in value else value.get("theme")
        if isinstance(raw, str) and raw.strip():
            out.append(raw.strip())
        elif isinstance(raw, list):
            out.extend(str(item).strip() for item in raw if str(item).strip())
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                _walk_theme_tags(nested, out)
        return
    if isinstance(value, list):
        for nested in value[:24]:
            _walk_theme_tags(nested, out)


def _note_market_theme(
    hyp_acc: dict[str, dict[str, Any]],
    att_acc: dict[str, dict[str, Any]],
    ticker: str,
    statement: str,
    *,
    confidence: str = "low",
    status: str = "candidate",
    supporting: list[str] | None = None,
    counter: list[str] | None = None,
    reason: str = "",
    alignment: str = "unknown",
    extra: dict[str, Any] | None = None,
) -> str | None:
    text = compact_text(statement, 400)
    if len(text) < 8:
        return None
    theme = _classify_market_theme(text, extra=extra)
    if not theme:
        return None
    kind, canonical = _kind_for_theme(theme)
    if kind not in MARKET_WIDE_KEYS and theme not in MARKET_THEME_LABELS:
        return None
    label = _theme_label(theme)
    persist = _persistable_theme_text(text, theme)
    safe_reason = reason if reason and not is_trigger_event({"reason": reason, "statement": reason}) else (reason or persist)
    if is_trigger_event({"reason": safe_reason, "statement": persist, "hypothesis": persist}):
        persist = label
        safe_reason = reason if reason and not is_trigger_event({"reason": reason}) else f"mapped from research {theme}"
    support_ids = [str(item) for item in (supporting or []) if str(item).strip()]
    oppose_ids = [str(item) for item in (counter or []) if str(item).strip()]
    bucket = hyp_acc.setdefault(
        canonical,
        _hypothesis_payload(
            ticker,
            canonical_key=canonical,
            kind=kind,
            statement=persist,
            name=label,
            confidence=confidence,
            status=status,
            supporting=support_ids,
            counter=oppose_ids,
            reason=safe_reason,
        ),
    )
    bucket["supporting_observations"] = list(dict.fromkeys(list(bucket.get("supporting_observations") or []) + support_ids))
    bucket["counter_observations"] = list(dict.fromkeys(list(bucket.get("counter_observations") or []) + oppose_ids))
    if confidence == "high":
        bucket["confidence"] = "high"
    elif confidence == "medium" and bucket.get("confidence") != "high":
        bucket["confidence"] = "medium"
    if status in {"supported", "active"} and bucket.get("status") == "candidate":
        bucket["status"] = status
    if persist != label and MARKET_FRAME_RE.search(text) and len(persist) >= len(str(bucket.get("hypothesis") or "")):
        bucket["hypothesis"] = persist
        bucket["reason"] = safe_reason
    att = att_acc.setdefault(
        label,
        {
            "ticker": ticker,
            "name": label,
            "statement": persist,
            "source_kind": SOURCE_KIND,
            "alignment": alignment,
            "evidence_ids": support_ids + oppose_ids,
            "reason": safe_reason,
        },
    )
    att["evidence_ids"] = list(dict.fromkeys(list(att.get("evidence_ids") or []) + support_ids + oppose_ids))
    if alignment != "unknown":
        att["alignment"] = alignment
    return theme


def _flush_market_themes(
    brain: BrainStore,
    hyp_acc: dict[str, dict[str, Any]],
    att_acc: dict[str, dict[str, Any]],
    counts: dict[str, int],
) -> None:
    for payload in hyp_acc.values():
        brain.upsert_hypothesis(payload)
        _add(counts, "hypotheses", True)
    for payload in att_acc.values():
        brain.upsert_market_attention(payload)
        _add(counts, "attentions", True)


def _agent_statement_rows(run: dict[str, Any]) -> list[dict[str, Any]]:
    payload = run.get("output_json") if isinstance(run.get("output_json"), dict) else {}
    reasoning = payload.get("reasoning") if isinstance(payload.get("reasoning"), dict) else {}
    pm = payload.get("pm_reasoning") if isinstance(payload.get("pm_reasoning"), dict) else {}
    thesis = payload.get("thesis") if isinstance(payload.get("thesis"), dict) else {}
    rows: list[dict[str, Any]] = []
    agent = str(run.get("agent_name") or "agent")

    def add(statement: Any, *, reason: str, confidence: Any = None) -> None:
        text = compact_text(statement, 400)
        if len(text) < 8:
            return
        rows.append({"statement": text, "reason": reason, "confidence": confidence})

    for item in payload.get("findings") or []:
        add(item, reason=f"mapped from research_agent_runs.{agent} findings")
    for bucket in (payload, reasoning, pm):
        for item in bucket.get("competing_hypotheses") or []:
            if isinstance(item, dict):
                add(
                    item.get("statement") or item.get("hypothesis"),
                    reason=f"mapped from research_agent_runs.{agent} competing_hypotheses",
                    confidence=item.get("confidence") or item.get("probability_band"),
                )
            else:
                add(item, reason=f"mapped from research_agent_runs.{agent} competing_hypotheses")
        for item in bucket.get("key_economic_drivers") or bucket.get("economic_drivers") or []:
            if not isinstance(item, dict):
                add(item, reason=f"mapped from research_agent_runs.{agent} key_economic_drivers")
                continue
            add(
                item.get("driver") or item.get("name") or item.get("why_it_matters") or item.get("statement"),
                reason=f"mapped from research_agent_runs.{agent} key_economic_drivers",
                confidence=item.get("confidence"),
            )
        for item in bucket.get("decisive_variables") or []:
            if isinstance(item, dict):
                add(item.get("name") or item.get("variable") or item.get("statement"), reason=f"mapped from research_agent_runs.{agent} decisive_variables")
            else:
                add(item, reason=f"mapped from research_agent_runs.{agent} decisive_variables")
        add(bucket.get("core_thesis"), reason=f"mapped from research_agent_runs.{agent} core_thesis")
        add(bucket.get("valuation_driver_judgment"), reason=f"mapped from research_agent_runs.{agent} valuation_driver_judgment")
    for item in payload.get("proposed_assumption_changes") or reasoning.get("proposed_assumption_changes") or []:
        if not isinstance(item, dict):
            continue
        add(item.get("statement"), reason=f"mapped from research_agent_runs.{agent} proposed_assumption_changes")
        add(item.get("reason"), reason=f"mapped from research_agent_runs.{agent} proposed_assumption_changes.reason")
    add(thesis.get("core_thesis"), reason=f"mapped from research_agent_runs.{agent} thesis")
    return rows


def _is_placeholder_env(text: str) -> bool:
    if not text:
        return True
    if MISSING_ENV in text and not _needle_themes(text):
        return True
    if any(token in text for token in PLACEHOLDER_ENV) and not _needle_themes(text):
        return True
    return False


def _collect_env_texts(row: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in ("one_liner", "row_thesis", "synthesis"):
        raw = compact_text(row.get(key) or "", 400)
        if raw:
            texts.append(raw)
        texts.extend(_collect_text(row.get(key), limit=4, min_len=8))
    struct = row.get("struct") if isinstance(row.get("struct"), dict) else {}
    texts.extend(_collect_text(struct.get("synthesis"), limit=2, min_len=8))
    news = struct.get("news") if isinstance(struct.get("news"), dict) else {}
    for layer in news.values():
        if not isinstance(layer, dict):
            continue
        texts.extend(_collect_text(layer.get("clause") or layer.get("headline"), limit=4, min_len=6))
        for item in list(layer.get("items") or [])[:8]:
            if isinstance(item, dict):
                texts.extend(_collect_text(item.get("headline") or item.get("name") or item.get("narrative"), limit=2, min_len=8))
    funds = struct.get("fundamentals") if isinstance(struct.get("fundamentals"), dict) else {}
    industry = funds.get("industry") if isinstance(funds.get("industry"), dict) else {}
    texts.extend(_collect_text(industry.get("clause"), limit=2, min_len=8))
    for bullet in list(struct.get("bullets") or [])[:8]:
        if isinstance(bullet, dict):
            texts.extend(_collect_text(bullet.get("clause"), limit=2, min_len=8))
    out: list[str] = []
    for text in texts:
        if _is_placeholder_env(text):
            continue
        if text not in out:
            out.append(text)
        for fragment in _desk_fragments(text):
            if _is_placeholder_env(fragment) or fragment in out:
                continue
            out.append(fragment)
    return out


def _env_theme_tags(row: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    _walk_theme_tags(row.get("struct") if isinstance(row.get("struct"), dict) else {}, tags)
    _walk_theme_tags(row.get("themes"), tags)
    mapped: list[str] = []
    for tag in tags:
        theme = ENV_THEME_TAGS.get(str(tag).lower())
        if theme and theme not in mapped:
            mapped.append(theme)
    return mapped


def _empty_counts() -> dict[str, int]:
    return {
        "hypotheses": 0,
        "attentions": 0,
        "expectations": 0,
        "states": 0,
        "claims": 0,
        "claim_links": 0,
        "thesis": 0,
        "drivers": 0,
        "events": 0,
        "questions": 0,
        "valuation": 0,
        "exposures": 0,
    }


def _add(counts: dict[str, int], key: str, written: bool) -> None:
    if written:
        counts[key] = counts.get(key, 0) + 1


def _latest_agent_runs(store: Any, ticker: str) -> list[dict[str, Any]]:
    symbol = ticker.upper()
    if hasattr(store, "_execute"):
        try:
            return list(
                store._execute(
                    """
                    SELECT DISTINCT ON (agent_name) *
                    FROM research_agent_runs
                    WHERE ticker = %(ticker)s AND status = 'success'
                    ORDER BY agent_name, started_at DESC
                    """,
                    {"ticker": symbol},
                )
                or []
            )
        except Exception:
            pass
    rows = list(store.list_agent_runs(symbol) if hasattr(store, "list_agent_runs") else [])
    latest: dict[str, dict[str, Any]] = {}
    rows.sort(key=lambda item: str(item.get("started_at") or item.get("completed_at") or ""), reverse=True)
    for row in rows:
        if str(row.get("status") or "") not in {"", "success"}:
            continue
        name = str(row.get("agent_name") or "agent")
        latest.setdefault(name, row)
    return list(latest.values())


def _load_environment(market: Any | None, tickers: list[str]) -> list[dict[str, Any]]:
    if market is None:
        return []
    rows: list[dict[str, Any]] = []
    if hasattr(market, "fetch_all"):
        try:
            fetched = market.fetch_all(
                """
                SELECT DISTINCT ON (scope, COALESCE(symbol, ''))
                       id, as_of_date, scope, symbol, one_liner, row_thesis,
                       struct, missing_flags, publish_state, created_at
                FROM environment_snapshots
                WHERE publish_state IS DISTINCT FROM 'missing'
                  AND (scope = 'market' OR symbol = ANY(%s))
                ORDER BY scope, COALESCE(symbol, ''), created_at DESC
                """,
                (tickers,),
            )
            from stock_pm.environment import snapshot_from_row

            rows.extend(item for item in (snapshot_from_row(row) for row in fetched or []) if item)
        except Exception:
            rows = []
    if not rows and hasattr(market, "market_session") and hasattr(market, "latest_environment_snapshots"):
        try:
            session = market.market_session(None) or {}
            date = session.get("default_review_date") or session.get("date")
            rows.extend(market.latest_environment_snapshots(date) or [])
        except Exception:
            pass
    if hasattr(market, "environment_history"):
        for symbol in tickers:
            try:
                rows.extend(market.environment_history(symbol, limit=3) or [])
            except Exception:
                continue
    if hasattr(market, "environment_snapshots"):
        rows.extend(list(market.environment_snapshots or []))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = f"{row.get('scope')}|{row.get('symbol')}|{row.get('id')}|{row.get('as_of_date')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _load_market_events(market: Any | None, ticker: str, *, limit: int = 25) -> list[dict[str, Any]]:
    if market is None:
        return []
    if hasattr(market, "market_events"):
        try:
            return list(market.market_events(ticker, limit) or [])
        except TypeError:
            try:
                return list(market.market_events(ticker) or [])[:limit]
            except Exception:
                return []
        except Exception:
            return []
    rows = [row for row in list(getattr(market, "events", None) or []) if str(row.get("symbol") or row.get("ticker") or "").upper() == ticker]
    return rows[:limit]


def load_research_bundle(store: Any, ticker: str) -> dict[str, Any]:
    symbol = ticker.upper()
    pack = store.get_pack(symbol) if hasattr(store, "get_pack") else None
    if isinstance(pack, dict) and pack.get("status") == "missing":
        pack = None
    assumptions = list(store.list_assumptions(symbol) if hasattr(store, "list_assumptions") else [])
    links = list(store.list_links(ticker=symbol) if hasattr(store, "list_links") else [])
    thesis = store.get_latest_thesis(symbol) if hasattr(store, "get_latest_thesis") else None
    snapshot = None
    if hasattr(store, "get_latest_snapshot"):
        snapshot = store.get_latest_snapshot(symbol, include_fixture=False)
        if snapshot is None:
            snapshot = store.get_latest_snapshot(symbol, include_fixture=True)
    valuation = None
    if thesis and thesis.get("valuation_id") and hasattr(store, "get_valuation"):
        valuation = store.get_valuation(thesis["valuation_id"])
    elif thesis and hasattr(store, "get_valuation_for_thesis"):
        valuation = store.get_valuation_for_thesis(thesis["id"])
    evidence: list[dict[str, Any]] = []
    seen_eids: set[str] = set()
    for link in links:
        eid = str(link.get("evidence_id") or "")
        if not eid or eid in seen_eids or not hasattr(store, "get_evidence"):
            continue
        row = store.get_evidence(eid)
        if row:
            evidence.append(row)
            seen_eids.add(eid)
    if snapshot:
        for row in list(snapshot.get("evidence") or snapshot.get("evidence_payload") or []):
            if not isinstance(row, dict):
                continue
            eid = str(row.get("id") or row.get("evidence_id") or "")
            if eid and eid not in seen_eids:
                evidence.append(row)
                seen_eids.add(eid)
    return {
        "ticker": symbol,
        "pack": pack,
        "assumptions": assumptions,
        "links": links,
        "thesis": thesis,
        "snapshot": snapshot,
        "valuation": valuation,
        "evidence": evidence,
        "agent_runs": _latest_agent_runs(store, symbol),
    }


def research_present(bundle: dict[str, Any]) -> bool:
    pack = bundle.get("pack") or {}
    has_pack = bool(pack) and (
        pack.get("industry_context")
        or pack.get("major_events")
        or pack.get("earnings_history")
        or (pack.get("company_profile") or {}).get("legal_name")
        or pack.get("competitive_context")
    )
    return bool(
        has_pack
        or bundle.get("assumptions")
        or bundle.get("thesis")
        or bundle.get("snapshot")
        or bundle.get("evidence")
    )


def _find_state(brain: BrainStore, ticker: str | None, state_key: str) -> dict[str, Any] | None:
    if ticker:
        found = brain.get_state_by_key(ticker, state_key)
        if found:
            return found
    for row in brain.list_all_states():
        if row.get("state_key") == state_key and (row.get("ticker") or None) == (ticker or None):
            return row
    return None


def _write_state(brain: BrainStore, row: dict[str, Any]) -> bool:
    key = str(row.get("state_key") or "")
    ticker = row.get("ticker")
    existing = _find_state(brain, str(ticker) if ticker else None, key) if key else None
    if existing:
        updated = brain.upsert_state({**row, "state_id": existing.get("state_id")})
        return bool(updated)
    brain.insert_state(row)
    return True


def _write_claim(brain: BrainStore, row: dict[str, Any]) -> dict[str, Any]:
    key = str(row.get("claim_key") or "")
    existing = brain.get_claim_by_key(row["ticker"], key) if key else None
    if existing:
        return brain.update_claim_pointer(existing["claim_id"], {**row, "claim_id": existing["claim_id"]})
    return brain.insert_claim(row)


def _write_event(brain: BrainStore, row: dict[str, Any]) -> bool:
    fingerprint = str(row.get("fingerprint") or "")
    if fingerprint:
        existing = brain.get_event_by_fingerprint(row["ticker"], fingerprint)
        if existing:
            return False
    brain.insert_event(row)
    return True


def _write_question(brain: BrainStore, row: dict[str, Any]) -> bool:
    qid = str(row.get("question_id") or "")
    text = " ".join(str(row.get("question") or "").lower().split())
    for existing in brain.list_questions(row["ticker"]):
        if existing.get("question_id") == qid:
            return False
        if " ".join(str(existing.get("question") or "").lower().split()) == text:
            return False
    brain.insert_question(row)
    return True


def _write_link(brain: BrainStore, claim_id: str, evidence_id: str, *, direction: str) -> bool:
    if not claim_id or not evidence_id:
        return False
    if brain.list_links(claim_id=claim_id, evidence_id=evidence_id):
        return False
    mapped = {"support": "support", "oppose": "oppose", "contextual": "contextual"}.get(direction, "contextual")
    brain.insert_link(
        {
            "claim_id": claim_id,
            "evidence_id": evidence_id,
            "direction": mapped,
            "reason": "mapped from assumption_evidence_links",
            "source_relationship": "unknown",
        }
    )
    return True


def _write_thesis(brain: BrainStore, row: dict[str, Any]) -> bool:
    prior = brain.latest_thesis(row["ticker"])
    current = compact_text(row.get("current_thesis") or "", 2000)
    if prior:
        return False
    if len(current) < 8:
        return False
    brain.upsert_thesis(row)
    return True


def _write_exposure(brain: BrainStore, row: dict[str, Any]) -> bool:
    eid = str(row.get("exposure_id") or "")
    for existing in brain.list_exposures(row["ticker"]):
        if existing.get("exposure_id") == eid:
            return False
        if existing.get("object_name") == row.get("object_name") and existing.get("mechanism") == row.get("mechanism"):
            return False
    brain.insert_exposure(row)
    return True


def _hypothesis_payload(
    ticker: str,
    *,
    canonical_key: str,
    kind: str,
    statement: str,
    name: str = "",
    confidence: str = "low",
    status: str = "candidate",
    supporting: list[str] | None = None,
    counter: list[str] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "canonical_key": canonical_key,
        "kind": kind,
        "hypothesis": statement,
        "name": name or compact_text(statement, 80) or canonical_key,
        "confidence": confidence,
        "status": status,
        "supporting_observations": list(supporting or []),
        "counter_observations": list(counter or []),
        "source_kind": SOURCE_KIND,
        "reason": reason or statement,
    }


def _map_pack(brain: BrainStore, ticker: str, pack: dict[str, Any], counts: dict[str, int]) -> None:
    profile = dict(pack.get("company_profile") or {})
    legal = compact_text(profile.get("legal_name") or "", 80)
    sector = compact_text(profile.get("sector") or "", 80)
    summary = _first_text(profile.get("summary"), profile.get("description"), " ".join(part for part in (legal, sector) if part), limit=280)
    if legal or sector or summary:
        _add(
            counts,
            "states",
            _write_state(
                brain,
                {
                    "ticker": ticker,
                    "state_type": "company",
                    "state_key": "company_profile",
                    "name": legal or ticker,
                    "statement": summary or legal,
                    "subject": ticker,
                    "source": SOURCE_KIND,
                    "confidence": "medium" if legal else "low",
                },
            ),
        )
    industry_texts = _collect_text(pack.get("industry_context"))
    hyp_acc: dict[str, dict[str, Any]] = {}
    att_acc: dict[str, dict[str, Any]] = {}
    if industry_texts:
        statement = industry_texts[0]
        theme = _classify_market_theme(statement)
        _add(
            counts,
            "states",
            _write_state(
                brain,
                {
                    "ticker": ticker,
                    "state_type": "industry",
                    "state_key": theme or "industry_context",
                    "name": _theme_label(theme) if theme else compact_text(statement, 80),
                    "statement": _persistable_theme_text(statement, theme) if theme else statement,
                    "source": SOURCE_KIND,
                    "confidence": "medium",
                },
            ),
        )
        for text in industry_texts:
            _note_market_theme(
                hyp_acc,
                att_acc,
                ticker,
                text,
                confidence="medium",
                status="active",
                reason="mapped from research_packs.industry_context",
                alignment="support",
            )
    _flush_market_themes(brain, hyp_acc, att_acc, counts)
    for idx, event in enumerate(list(pack.get("major_events") or [])[:12]):
        if not isinstance(event, dict):
            title = compact_text(event, 160)
            event = {"title": title} if title else {}
        title = _first_text(event.get("title"), event.get("name"), event.get("statement"), event.get("fact"), limit=160)
        if not title:
            continue
        event_type = str(event.get("event_type") or event.get("type") or "other").lower()
        fingerprint = f"pack:{ticker}:major:{_slug(event.get('id') or title)}"
        _add(
            counts,
            "events",
            _write_event(
                brain,
                {
                    "ticker": ticker,
                    "event_id": f"bev_pack_{ticker.lower()}_{_slug(event.get('id') or idx)}",
                    "event_type": event_type,
                    "title": title,
                    "subject": compact_text(event.get("subject") or title, 80),
                    "event_date": event.get("event_date") or event.get("date") or event.get("published_at"),
                    "fingerprint": fingerprint,
                    "reason": "mapped from research_packs.major_events",
                    "materiality": "material" if is_trigger_event({**event, "title": title, "event_type": event_type}) else "context",
                },
            ),
        )
    for print_row in list(pack.get("earnings_history") or [])[:8]:
        if not isinstance(print_row, dict):
            continue
        actual = print_row.get("eps") if print_row.get("eps") is not None else print_row.get("eps_actual")
        expected = print_row.get("eps_estimate")
        period = compact_text(print_row.get("fiscal_period") or print_row.get("period") or "", 40)
        if actual is None or expected is None or not period:
            continue
        brain.upsert_expectation(
            {
                "ticker": ticker,
                "name": f"{period} EPS",
                "subject": f"{period} EPS",
                "actual": actual,
                "expected": expected,
                "source_kind": SOURCE_KIND,
                "reason": "mapped from research_packs.earnings_history",
                "supporting_evidence_ids": [],
            }
        )
        _add(counts, "expectations", True)
    for print_row in list(pack.get("guidance_history") or [])[:6]:
        if not isinstance(print_row, dict):
            continue
        actual = print_row.get("actual") if print_row.get("actual") is not None else print_row.get("guided")
        expected = print_row.get("expected") if print_row.get("expected") is not None else print_row.get("consensus")
        name = _first_text(print_row.get("name"), print_row.get("metric"), print_row.get("fiscal_period"), limit=40)
        if actual is None or expected is None or not name:
            continue
        brain.upsert_expectation(
            {
                "ticker": ticker,
                "name": f"{name} guidance",
                "subject": name,
                "actual": actual,
                "expected": expected,
                "source_kind": SOURCE_KIND,
                "reason": "mapped from research_packs.guidance_history",
            }
        )
        _add(counts, "expectations", True)


def _map_assumptions(
    brain: BrainStore,
    ticker: str,
    assumptions: list[dict[str, Any]],
    links: list[dict[str, Any]],
    counts: dict[str, int],
) -> dict[str, str]:
    claim_ids: dict[str, str] = {}
    by_assumption: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in links:
        by_assumption[str(link.get("assumption_id") or "")].append(link)
    hyp_acc: dict[str, dict[str, Any]] = {}
    att_acc: dict[str, dict[str, Any]] = {}
    for row in assumptions:
        statement = compact_text(row.get("statement") or "", 400)
        if len(statement) < 8:
            continue
        aid = str(row.get("id") or "")
        role = str(row.get("thesis_role") or "supporting")
        status = str(row.get("status") or "unverified")
        confidence = _band_confidence(row.get("confidence"))
        linked = by_assumption.get(aid) or []
        support_ids = [str(item.get("evidence_id")) for item in linked if item.get("direction") == "support" and item.get("evidence_id")]
        oppose_ids = [str(item.get("evidence_id")) for item in linked if item.get("direction") == "oppose" and item.get("evidence_id")]
        _note_market_theme(
            hyp_acc,
            att_acc,
            ticker,
            statement,
            confidence=confidence,
            status=HYP_STATUS.get(status, "candidate"),
            supporting=support_ids,
            counter=oppose_ids,
            reason=f"mapped from research_assumptions {aid}",
            alignment="support" if status in {"strengthened", "unchanged"} else ("counter" if status in {"weakened", "broken"} else "unknown"),
        )
        if role == "none":
            continue
        claim = _write_claim(
            brain,
            {
                "ticker": ticker,
                "claim_id": f"bclm_rasm_{aid}" if aid else None,
                "claim_key": f"rasm:{aid}" if aid else _slug(statement),
                "title": compact_text(statement, 80),
                "statement": statement,
                "claim_type": "operating",
                "status": CLAIM_STATUS.get(status, "unverified"),
                "importance": _importance(row.get("importance")),
                "confidence": confidence,
                "is_core": role in {"core", "risk"},
                "why_it_matters": compact_text(row.get("why_it_matters") or "", 240),
                "what_would_invalidate": compact_text(row.get("invalidation_condition") or "", 240),
                "lifecycle": "core" if role in {"core", "risk"} else "emerging",
            },
        )
        cid = str(claim.get("claim_id") or "")
        if aid and cid:
            claim_ids[aid] = cid
        _add(counts, "claims", True)
        for link in linked:
            if _write_link(brain, cid, str(link.get("evidence_id") or ""), direction=str(link.get("direction") or "contextual")):
                _add(counts, "claim_links", True)
        next_q = compact_text(row.get("next_verification") or "", 240)
        if next_q:
            _add(
                counts,
                "questions",
                _write_question(
                    brain,
                    {
                        "ticker": ticker,
                        "question_id": f"brq_rasm_{aid}" if aid else f"brq_{ticker.lower()}_{_slug(next_q)}",
                        "related_claim_id": cid or None,
                        "question": next_q,
                        "why_it_matters": statement,
                        "priority": _importance(row.get("importance")),
                        "status": "open",
                    },
                ),
            )
    _flush_market_themes(brain, hyp_acc, att_acc, counts)
    return claim_ids


def _map_snapshot_and_agents(brain: BrainStore, ticker: str, bundle: dict[str, Any], counts: dict[str, int]) -> None:
    hyps: list[Any] = []
    drivers: list[Any] = []
    snapshot = bundle.get("snapshot") or {}
    hyps.extend(snapshot.get("competing_hypotheses") or [])
    drivers.extend(snapshot.get("economic_drivers") or snapshot.get("key_economic_drivers") or [])
    hyp_acc: dict[str, dict[str, Any]] = {}
    att_acc: dict[str, dict[str, Any]] = {}
    for run in bundle.get("agent_runs") or []:
        payload = run.get("output_json") if isinstance(run.get("output_json"), dict) else {}
        reasoning = payload.get("reasoning") if isinstance(payload.get("reasoning"), dict) else {}
        hyps.extend(payload.get("competing_hypotheses") or reasoning.get("competing_hypotheses") or [])
        drivers.extend(payload.get("key_economic_drivers") or reasoning.get("key_economic_drivers") or [])
        for row in _agent_statement_rows(run):
            _note_market_theme(
                hyp_acc,
                att_acc,
                ticker,
                row["statement"],
                confidence=_band_confidence(row.get("confidence")),
                status="candidate",
                reason=row.get("reason") or "mapped from research_agent_runs",
            )
    seen_hyp: set[str] = set()
    for item in hyps:
        if isinstance(item, str):
            statement = compact_text(item, 280)
            item = {"statement": statement}
        if not isinstance(item, dict):
            continue
        statement = compact_text(item.get("statement") or item.get("hypothesis") or "", 280)
        if len(statement) < 8 or statement.lower() in seen_hyp:
            continue
        seen_hyp.add(statement.lower())
        support = [str(eid) for eid in (item.get("supporting_evidence_ids") or []) if str(eid).strip()]
        oppose = [str(eid) for eid in (item.get("opposing_evidence_ids") or item.get("counter_evidence_ids") or []) if str(eid).strip()]
        noted = _note_market_theme(
            hyp_acc,
            att_acc,
            ticker,
            statement,
            confidence=_band_confidence(item.get("confidence") or item.get("probability_band")),
            status="candidate",
            supporting=support,
            counter=oppose,
            reason="mapped from research competing_hypotheses",
        )
        if not noted:
            continue
        how = compact_text(item.get("how_to_test") or "", 240)
        if how:
            _add(
                counts,
                "questions",
                _write_question(
                    brain,
                    {
                        "ticker": ticker,
                        "question_id": f"brq_hyp_{ticker.lower()}_{_slug(statement, limit=24)}",
                        "question": how,
                        "why_it_matters": statement,
                        "priority": "medium",
                    },
                ),
            )
    _flush_market_themes(brain, hyp_acc, att_acc, counts)
    seen_drv: set[str] = set()
    for item in drivers:
        if not isinstance(item, dict):
            continue
        name = compact_text(item.get("driver") or item.get("name") or "", 120)
        if len(name) < 4 or name.lower() in seen_drv:
            continue
        seen_drv.add(name.lower())
        key = _slug(name, limit=48)
        why = compact_text(item.get("why_it_matters") or "", 280)
        mechanism = compact_text(item.get("valuation_channel") or item.get("mechanism") or "", 200)
        brain.upsert_driver(
            {
                "ticker": ticker,
                "canonical_key": key,
                "name": name,
                "description": why,
                "category": "demand" if _theme_for({"name": name, "statement": why}) == "ai_capex_expectations" else "macro",
                "why_it_matters": why,
                "current_state": why,
                "evidence_ids": [str(eid) for eid in (item.get("evidence_ids") or []) if str(eid).strip()][:8],
                "importance": _band_confidence(item.get("confidence")),
                "status": "active",
            }
        )
        _add(counts, "drivers", True)
        if mechanism:
            _add(
                counts,
                "exposures",
                _write_exposure(
                    brain,
                    {
                        "ticker": ticker,
                        "exposure_id": f"bexp_mat_{ticker.lower()}_{key}",
                        "object_name": name,
                        "mechanism": mechanism,
                        "magnitude": "medium",
                        "reason": "mapped from key_economic_drivers.valuation_channel",
                    },
                ),
            )


def _map_thesis(
    brain: BrainStore,
    ticker: str,
    thesis: dict[str, Any] | None,
    claim_ids: dict[str, str],
    counts: dict[str, int],
) -> None:
    if not thesis:
        return
    core = compact_text(thesis.get("core_thesis") or "", 2000)
    if len(core) < 8:
        return
    risks = thesis.get("key_risks") or []
    invalid = thesis.get("invalidation_conditions") or []
    catalysts = thesis.get("key_catalysts") or []
    support = [claim_ids[aid] for aid in list(thesis.get("core_assumption_ids") or thesis.get("key_assumption_ids") or []) if aid in claim_ids]
    risk_ids = [
        claim_ids[aid]
        for aid in list(thesis.get("supporting_assumption_ids") or [])
        if aid in claim_ids
    ]
    _add(
        counts,
        "thesis",
        _write_thesis(
            brain,
            {
                "ticker": ticker,
                "thesis_id": f"bths_research_{ticker.lower()}",
                "current_thesis": core,
                "top_supporting_claim_ids": support[:6],
                "top_risk_claim_ids": risk_ids[:6],
                "key_upside_condition": _first_text(*catalysts, limit=200),
                "key_downside_condition": _first_text(*risks, limit=200),
                "what_would_change_thesis": _first_text(*invalid, limit=240),
                "confidence": _band_confidence(thesis.get("confidence")),
                "reason": "mapped from investment_theses",
            },
        ),
    )
    for idx, item in enumerate(list(thesis.get("monitoring_items") or [])[:8]):
        question = compact_text(item if not isinstance(item, dict) else item.get("item") or item.get("question") or item.get("text") or "", 240)
        if len(question) < 8:
            continue
        _add(
            counts,
            "questions",
            _write_question(
                brain,
                {
                    "ticker": ticker,
                    "question_id": f"brq_mon_{ticker.lower()}_{idx}",
                    "question": question,
                    "why_it_matters": core,
                    "priority": "medium",
                },
            ),
        )


def _map_valuation(brain: BrainStore, ticker: str, valuation: dict[str, Any] | None, counts: dict[str, int]) -> None:
    if not valuation:
        return
    base = valuation.get("base_case") if isinstance(valuation.get("base_case"), dict) else {}
    supporting = {
        "bear_case": valuation.get("bear_case") or {},
        "base_case": valuation.get("base_case") or {},
        "bull_case": valuation.get("bull_case") or {},
        "spot_price": valuation.get("spot_price"),
        "horizon": valuation.get("horizon"),
    }
    has_number = valuation.get("spot_price") is not None or any(
        isinstance(case, dict) and any(case.get(key) not in (None, "", {}) for key in case)
        for case in supporting.values()
        if isinstance(case, dict)
    )
    direction = str(base.get("direction") or valuation.get("valuation_direction") or "").strip().lower()
    if direction not in {"up", "down", "neutral", "uncertain"}:
        direction = "uncertain"
    context = _first_text(base.get("narrative"), base.get("summary"), valuation.get("horizon"), limit=200)
    brain.upsert_valuation_state(
        {
            "ticker": ticker,
            "valuation_context": context,
            "valuation_direction": direction,
            "confidence": "low",
            "valuation_data_missing": not has_number,
            "supporting_data": supporting,
            "reason": "mapped from research_valuations",
        }
    )
    _add(counts, "valuation", True)


def _map_market_events(brain: BrainStore, ticker: str, events: list[dict[str, Any]], counts: dict[str, int]) -> None:
    for row in events:
        title = compact_text(row.get("title") or "", 160)
        if len(title) < 8:
            continue
        event_type = str(row.get("event_type") or "other").lower()
        stamp = row.get("event_time") or row.get("detected_at") or ""
        fingerprint = f"mkt:{ticker}:{event_type}:{_slug(title, limit=32)}:{_slug(stamp, limit=20)}"
        _add(
            counts,
            "events",
            _write_event(
                brain,
                {
                    "ticker": ticker,
                    "event_id": f"bev_mkt_{ticker.lower()}_{_slug(title, limit=20)}_{_slug(stamp, limit=12)}",
                    "event_type": event_type,
                    "title": title,
                    "subject": title,
                    "event_date": row.get("event_time"),
                    "fingerprint": fingerprint,
                    "reason": "mapped from market_events",
                    "materiality": "material" if str(row.get("severity") or "") == "high" else "context",
                    "url": (row.get("details") or {}).get("url") if isinstance(row.get("details"), dict) else None,
                },
            ),
        )


def _map_environment(
    brain: BrainStore,
    tickers: list[str],
    snapshots: list[dict[str, Any]],
    counts: dict[str, int],
) -> dict[str, dict[str, Any]]:
    del tickers
    by_theme: dict[str, dict[str, Any]] = {}
    for row in snapshots:
        if str(row.get("publishState") or row.get("publish_state") or "") == "missing":
            continue
        texts = _collect_env_texts(row)
        tags = _env_theme_tags(row)
        if not texts and not tags:
            continue
        usable = [text for text in texts if MISSING_ENV not in text]
        themes = _classify_all_market_themes(*usable, extra={"themes": tags, "theme_tags": tags})
        if not themes and tags:
            themes = list(tags)
        if not themes or not usable:
            continue
        scope = str(row.get("scope") or "market")
        for theme in themes:
            if theme not in MARKET_THEME_LABELS:
                continue
            name, statement = _extract_theme_copy(usable, theme)
            if not statement or MISSING_ENV in statement:
                continue
            prior = by_theme.get(theme)
            if prior and scope != "market" and prior.get("scope") == "market":
                continue
            by_theme[theme] = {
                "theme": theme,
                "name": name,
                "statement": statement,
                "scope": scope,
            }
    for item in by_theme.values():
        theme = item["theme"]
        statement = _persistable_theme_text(item["statement"], theme)
        name = item.get("name") or THEME_DISPLAY_ZH.get(theme) or _theme_label(theme)
        _add(
            counts,
            "states",
            _write_state(
                brain,
                {
                    "ticker": None,
                    "state_type": "macro",
                    "state_key": theme,
                    "name": name,
                    "statement": statement,
                    "subject": _theme_label(theme),
                    "source": SOURCE_KIND,
                    "confidence": "medium",
                },
            ),
        )
    return by_theme


def _apply_env_themes(
    brain: BrainStore,
    ticker: str,
    env_themes: dict[str, dict[str, Any]],
    counts: dict[str, int],
) -> None:
    """Ticker hyp/attention from already-classified env themes so promote can fire."""
    if not env_themes:
        return
    hyp_acc: dict[str, dict[str, Any]] = {}
    att_acc: dict[str, dict[str, Any]] = {}
    for theme, item in env_themes.items():
        label = _theme_label(theme)
        statement = item.get("statement") or label
        _note_market_theme(
            hyp_acc,
            att_acc,
            ticker,
            statement,
            extra={
                "name": label,
                "kind": theme,
                "canonical_key": theme,
                "statement": statement,
            },
            confidence="medium",
            status="active",
            reason="mapped from environment_snapshots",
            alignment="support",
        )
    _flush_market_themes(brain, hyp_acc, att_acc, counts)


def materialize_ticker(
    *,
    ticker: str,
    research: Any,
    brain: BrainStore,
    market: Any | None = None,
    env_themes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    store = _research_store(research)
    bundle = load_research_bundle(store, symbol)
    counts = _empty_counts()
    present = research_present(bundle)
    if present:
        if bundle.get("pack"):
            _map_pack(brain, symbol, bundle["pack"], counts)
        claim_ids = _map_assumptions(brain, symbol, bundle.get("assumptions") or [], bundle.get("links") or [], counts)
        _map_snapshot_and_agents(brain, symbol, bundle, counts)
        _map_thesis(brain, symbol, bundle.get("thesis"), claim_ids, counts)
        _map_valuation(brain, symbol, bundle.get("valuation"), counts)
        _map_market_events(brain, symbol, _load_market_events(market, symbol), counts)
        _apply_env_themes(brain, symbol, env_themes or {}, counts)
    return {
        "ticker": symbol,
        "status": "written" if present else "empty",
        "reason": None if present else "no research pack, assumptions, thesis, or snapshot",
        "written": counts,
        "sources": {
            "pack": bool(bundle.get("pack")),
            "assumptions": len(bundle.get("assumptions") or []),
            "thesis": bool(bundle.get("thesis")),
            "snapshot": bool(bundle.get("snapshot")),
            "evidence_used": len(bundle.get("evidence") or []),
            "agent_runs_used": len(bundle.get("agent_runs") or []),
        },
        "llm_invoked": False,
    }


def materialize_from_research(
    tickers: str | list[str],
    *,
    research: Any,
    brain: BrainStore | None = None,
    market: Any | None = None,
) -> dict[str, Any]:
    """Map existing research artifacts into brain_* and stop. No LLM. No schedule."""
    symbols = parse_tickers(tickers)
    store = _research_store(research)
    brain_store = brain or BrainStore(getattr(store, "database", None))
    env_counts = _empty_counts()
    snapshots = _load_environment(market, symbols)
    env_themes = _map_environment(brain_store, symbols, snapshots, env_counts)
    results = [
        materialize_ticker(
            ticker=symbol,
            research=research,
            brain=brain_store,
            market=market,
            env_themes=env_themes,
        )
        for symbol in symbols
    ]
    return {
        "ok": True,
        "llm_invoked": False,
        "scheduled": False,
        "source_kind": SOURCE_KIND,
        "tickers": symbols,
        "results": results,
        "market_environment": {
            "snapshots_seen": len(snapshots),
            "states_written": env_counts["states"],
        },
        "gaps": GAPS,
    }


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        description="One-shot: upsert brain_* from research_* / related tables. Does not call GLM or schedule reruns."
    )
    parser.add_argument(
        "--tickers",
        default="AVGO,LITE",
        help="Comma-separated tickers (default: AVGO,LITE). Missing research stays honestly empty.",
    )
    args = parser.parse_args(argv)
    from stock_pm.database import Database
    from stock_pm.research.store import ResearchStore

    database = Database()
    try:
        database.initialize()
        payload = materialize_from_research(
            args.tickers,
            research=ResearchStore(database),
            brain=BrainStore(database),
            market=database,
        )
    finally:
        database.close()
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
    return payload


if __name__ == "__main__":
    main()
