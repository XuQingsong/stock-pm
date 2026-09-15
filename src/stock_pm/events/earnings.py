"""Structured earnings evidence. Numbers are never inferred from display text."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .policy import sanitize_untrusted
from .types import EventDocument


FROZEN_EARNINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "events_5c_b_frozen_earnings.json"
FROZEN_COVERAGE_PATH = Path(__file__).resolve().parent.parent / "data" / "events_5c_c_frozen_earnings.json"
FROZEN_EARNINGS_DATA_CLASS = "frozen_provider_audit"
RULE_ID = "earnings_implication.v1"
ALIGN_ID = "period_align.v2"
QUARTER_ID = "fiscal_quarter.v1"
EPS_UNIT = "USD/share"
PERIOD_END_TOLERANCE_DAYS = 3
AV_EARNINGS_SOURCE = "https://www.alphavantage.co/query?function=EARNINGS&symbol={symbol}"
AV_ESTIMATES_SOURCE = "https://www.alphavantage.co/query?function=EARNINGS_ESTIMATES&symbol={symbol}"
AV_TRANSCRIPT_SOURCE = "https://www.alphavantage.co/query?function=EARNINGS_CALL_TRANSCRIPT&symbol={symbol}&quarter={quarter}"
CONSENSUS_ROLE = "provider_reported_consensus_at_print"
# Issuer FYE month. October-start FY for September FYE (AAPL). Calendar FY for December FYE.
# Issuer FYE month. Unknown issuers omit a quarter id and skip transcript; do not invent numbers.
FISCAL_YEAR_END_MONTH = {
    "AAPL": 9,
    "NVDA": 1,
    "XOM": 12,
    "JPM": 12,
    "INTC": 12,
    "GOOGL": 12,
    "NOK": 12,
    "MU": 8,
    "AVGO": 10,
}

_REGISTRY: dict[str, "EarningsEvidence"] = {}


class FrozenEarningsError(RuntimeError):
    """Tampered or malformed frozen earnings pack."""


def field_binding(
    *,
    name: str,
    value: float | None,
    function: str,
    raw_field: str,
    as_of: str | None,
    fetched_at: str,
    source_url: str,
    role: str,
    provider: str = "alpha_vantage",
) -> dict[str, Any]:
    return {
        "field": name,
        "value": value,
        "provider": provider,
        "function": function,
        "raw_field": raw_field,
        "as_of": as_of,
        "fetched_at": fetched_at,
        "source_url": source_url,
        "role": role,
    }


@dataclass(slots=True)
class EarningsEvidence:
    symbol: str
    fiscal_period: str
    fiscal_date_ending: str
    metric: str
    actual: float | None
    prior_year_actual: float | None
    consensus: float | None
    unit: str
    currency: str
    source_url: str
    provider: str
    published_at: str | None
    as_of: str | None
    fetched_at: str
    raw_refs: list[dict[str, Any]] = field(default_factory=list)
    transcript_excerpts: list[dict[str, str]] = field(default_factory=list)
    gap: str | None = None
    yoy: float | None = None
    surprise: float | None = None
    yoy_inputs: dict[str, Any] = field(default_factory=dict)
    surprise_inputs: dict[str, Any] = field(default_factory=dict)
    implication: str | None = None
    rule_id: str = RULE_ID
    fiscal_quarter: str = ""
    field_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    consensus_role: str | None = None
    estimate_snapshot: dict[str, Any] | None = None
    sec_association: dict[str, Any] | None = None
    endpoints_called: list[str] = field(default_factory=list)

    def key(self) -> str:
        return f"{self.symbol}|{self.metric}|{self.fiscal_date_ending}"

    def complete(self) -> bool:
        bindings = self.field_bindings or {}
        return (
            self.actual is not None
            and self.prior_year_actual is not None
            and self.consensus is not None
            and self.yoy is not None
            and self.surprise is not None
            and self.implication is not None
            and self.gap is None
            and bool(self.source_url)
            and bool(self.unit)
            and bool(self.currency)
            and all(key in bindings and bindings[key].get("source_url") for key in ("actual", "prior_year_actual", "consensus"))
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reset_earnings_registry() -> None:
    _REGISTRY.clear()


def _values_conflict(left: EarningsEvidence, right: EarningsEvidence) -> bool:
    return (left.actual, left.prior_year_actual, left.consensus) != (
        right.actual,
        right.prior_year_actual,
        right.consensus,
    )


def register_earnings(row: EarningsEvidence) -> EarningsEvidence:
    compute_changes(row)
    previous = _REGISTRY.get(row.key())
    if previous and _values_conflict(previous, row):
        for item in (previous, row):
            item.gap = "restatement_or_ambiguous"
            item.yoy = None
            item.surprise = None
            item.implication = None
    _REGISTRY[row.key()] = row
    return row


def earnings_for(symbol: str, *, metric: str = "eps", fiscal_date_ending: str = "") -> EarningsEvidence | None:
    symbol = symbol.upper()
    if len(fiscal_date_ending) >= 10:
        return _REGISTRY.get(f"{symbol}|{metric}|{fiscal_date_ending[:10]}")
    prefix = f"{symbol}|{metric}|"
    rows = [row for key, row in _REGISTRY.items() if key.startswith(prefix)]
    if fiscal_date_ending:
        month = fiscal_date_ending[:7]
        rows = [row for row in rows if row.fiscal_date_ending[:7] == month]
        if len(rows) != 1:
            return None
        return rows[0]
    rows.sort(key=lambda item: item.fiscal_date_ending, reverse=True)
    return rows[0] if rows else None


def earnings_for_event(event: Any) -> EarningsEvidence | None:
    entities = [str(item).upper() for item in getattr(event, "entities", []) or []]
    metric_tokens = {"EPS", "REV", "REVENUE", "EARNINGS", "USD"}
    symbol = next(
        (item for item in entities if item.isalpha() and 1 <= len(item) <= 5 and item not in metric_tokens),
        "",
    )
    ending = next((item for item in entities if len(item) >= 7 and item[4:5] == "-"), "")
    if not symbol:
        return None
    return earnings_for(symbol, fiscal_date_ending=ending)


def parse_number(value: Any) -> float | None:
    if value in (None, "", "."):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_date(text: str) -> date | None:
    raw = str(text or "")[:10]
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def period_month_key(fiscal_date_ending: str) -> str:
    text = str(fiscal_date_ending or "")
    return text[:7] if len(text) >= 7 else ""


def fiscal_quarter_id(symbol: str, fiscal_date_ending: str) -> str:
    """Map period-end to issuer fiscal quarter under fiscal_quarter.v1."""
    ending = _as_date(fiscal_date_ending)
    try:
        from stock_pm.research.issuer import fiscal_year_end_month_for

        fye = fiscal_year_end_month_for(str(symbol or ""))
    except Exception:
        fye = None
    if fye is None:
        fye = FISCAL_YEAR_END_MONTH.get(str(symbol or "").upper())
    if ending is None or fye is None:
        return ""
    if fye == 12:
        return f"{ending.year}Q{(ending.month - 1) // 3 + 1}"
    fy_start_month = (fye % 12) + 1
    fy_year = ending.year + 1 if ending.month > fye else ending.year
    months_from_start = (ending.month - fy_start_month) % 12
    quarter = months_from_start // 3 + 1
    return f"{fy_year}Q{quarter}"


def compute_changes(row: EarningsEvidence) -> EarningsEvidence:
    """YoY and surprise only when period/units match and the denominator is usable."""
    row.yoy = None
    row.surprise = None
    row.implication = None
    row.yoy_inputs = {
        "actual": row.actual,
        "prior_year_actual": row.prior_year_actual,
        "formula": "(actual - prior_year_actual) / prior_year_actual",
        "align": ALIGN_ID,
        "bindings": ["actual", "prior_year_actual"],
    }
    row.surprise_inputs = {
        "actual": row.actual,
        "consensus": row.consensus,
        "formula": "(actual - consensus) / abs(consensus)",
        "align": ALIGN_ID,
        "consensus_role": row.consensus_role,
        "bindings": ["actual", "consensus"],
    }
    if row.gap:
        return row
    if row.actual is None:
        row.gap = "baseline_missing"
        return row
    if row.unit != EPS_UNIT or row.currency != "USD":
        row.gap = "period_mismatch"
        return row
    if row.prior_year_actual is None or row.consensus is None:
        row.gap = "baseline_missing"
        return row
    if row.prior_year_actual <= 0:
        row.gap = "undefined_change"
        return row
    if row.consensus <= 0:
        row.gap = "undefined_change"
        return row
    row.yoy = round((row.actual - row.prior_year_actual) / row.prior_year_actual, 6)
    row.surprise = round((row.actual - row.consensus) / abs(row.consensus), 6)
    row.implication = _implication(row.yoy, row.surprise)
    row.rule_id = RULE_ID
    return row


def _implication(yoy: float, surprise: float) -> str:
    beat = surprise > 0
    miss = surprise < 0
    grow = yoy > 0
    contract = yoy < 0
    if beat and grow:
        return "beat_and_grow"
    if beat and contract:
        return "beat_but_contract"
    if miss and grow:
        return "miss_but_grow"
    if miss and contract:
        return "miss_and_contract"
    if beat:
        return "beat_flat"
    if miss:
        return "miss_flat"
    if grow:
        return "inline_and_grow"
    return "inline_or_mixed"


def implication_text(row: EarningsEvidence) -> str:
    labels = {
        "beat_and_grow": "实际值高于共识且同比上升",
        "beat_but_contract": "实际值高于共识但同比下降",
        "miss_but_grow": "实际值低于共识但同比上升",
        "miss_and_contract": "实际值低于共识且同比下降",
        "beat_flat": "实际值高于共识，同比持平",
        "miss_flat": "实际值低于共识，同比持平",
        "inline_and_grow": "实际值贴近共识且同比上升",
        "inline_or_mixed": "实际值贴近共识",
    }
    label = labels.get(row.implication or "", "盈利含义未形成")
    return f"{label}（规则 {row.rule_id}）。不是股价方向或价格区间"


def binding_refs(row: EarningsEvidence, names: tuple[str, ...]) -> list[dict[str, Any]]:
    refs = []
    for name in names:
        item = (row.field_bindings or {}).get(name) or {}
        url = str(item.get("source_url") or "")
        if not url:
            continue
        refs.append(
            {
                "source_url": url,
                "publisher": item.get("provider") or row.provider,
                "content_type": "aggregator",
                "fact_or_opinion": "opinion",
                "field": name,
                "function": item.get("function"),
                "raw_field": item.get("raw_field"),
                "as_of": item.get("as_of"),
                "fetched_at": item.get("fetched_at"),
                "role": item.get("role"),
                "value": item.get("value"),
            }
        )
    return refs


def frozen_earnings_material(payload: dict[str, Any]) -> dict[str, Any]:
    """Hash the full pack except the integrity field itself."""
    return {key: value for key, value in payload.items() if key != "integrity_sha256"}


def compute_frozen_earnings_integrity(payload: dict[str, Any]) -> str:
    encoded = json.dumps(frozen_earnings_material(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def derive_frozen_acceptance(payload: dict[str, Any]) -> dict[str, Any]:
    """Acceptance counts come from locked source material, not editable after-fields."""
    reset_earnings_registry()
    from .analyze import analyze_event, inspect_closed_loop
    from .dedupe import build_events

    events = build_events(load_frozen_earnings_documents(payload=payload))
    for event in events:
        analyze_event(event)
    valid = sum(1 for event in events if inspect_closed_loop(event)["valid"])
    complete = sum(1 for event in events if (event.analysis or {}).get("earnings_chain_complete"))
    return {
        "valid_conclusion_count": valid,
        "earnings_chain_complete_count": complete,
        "event_ids": [event.event_id for event in events],
        "gained_valid_event_ids": [event.event_id for event in events if inspect_closed_loop(event)["valid"]],
    }


def load_frozen_earnings(path: Path | None = None) -> dict[str, Any]:
    target = path or FROZEN_EARNINGS_PATH
    if not target.is_file():
        raise FrozenEarningsError("frozen_earnings_missing")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("live") is True:
        raise FrozenEarningsError("frozen_earnings_marked_live")
    if payload.get("data_class") != FROZEN_EARNINGS_DATA_CLASS:
        raise FrozenEarningsError("frozen_earnings_not_provider_audit")
    expected = str(payload.get("integrity_sha256") or "")
    actual = compute_frozen_earnings_integrity(payload)
    if not expected or expected != actual:
        raise FrozenEarningsError("frozen_earnings_hash_mismatch")
    return payload


def _select_print(
    rows: list[dict[str, Any]], fiscal_date_ending: str | None
) -> tuple[dict[str, Any] | None, str | None]:
    if not rows:
        return None, "baseline_missing"
    if fiscal_date_ending and len(fiscal_date_ending) >= 10:
        exact = [row for row in rows if str(row.get("fiscalDateEnding") or "") == fiscal_date_ending[:10]]
        if len(exact) == 1:
            return exact[0], None
        if len(exact) > 1:
            values = {str(row.get("reportedEPS")) for row in exact}
            return exact[0], ("restatement_or_ambiguous" if len(values) > 1 else None)
        month = fiscal_date_ending[:7]
        month_hits = [row for row in rows if str(row.get("fiscalDateEnding") or "")[:7] == month]
        if len(month_hits) != 1:
            return None, "restatement_or_ambiguous" if month_hits else "baseline_missing"
        hit_date = _as_date(str(month_hits[0].get("fiscalDateEnding") or ""))
        want = _as_date(fiscal_date_ending)
        if hit_date and want and abs((hit_date - want).days) <= PERIOD_END_TOLERANCE_DAYS:
            return month_hits[0], None
        return None, "period_mismatch"
    current = rows[0]
    twins = [row for row in rows if str(row.get("fiscalDateEnding") or "") == str(current.get("fiscalDateEnding") or "")]
    values = {str(row.get("reportedEPS")) for row in twins}
    if len(values) > 1:
        return current, "restatement_or_ambiguous"
    return current, None


def _select_prior(
    rows: list[dict[str, Any]], ending: str
) -> tuple[float | None, dict[str, Any] | None, str | None]:
    current = _as_date(ending)
    if current is None:
        return None, None, "period_mismatch"
    want_year = current.year - 1
    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = _as_date(str(row.get("fiscalDateEnding") or ""))
        if item is None or item.year != want_year or item.month != current.month:
            continue
        if abs((item - date(want_year, current.month, current.day)).days) > PERIOD_END_TOLERANCE_DAYS:
            continue
        candidates.append(row)
    if len(candidates) > 1:
        values = {str(row.get("reportedEPS")) for row in candidates}
        if len(values) > 1:
            return None, None, "restatement_or_ambiguous"
    if len(candidates) == 1:
        return parse_number(candidates[0].get("reportedEPS")), candidates[0], None
    if not candidates:
        return None, None, None
    return parse_number(candidates[0].get("reportedEPS")), candidates[0], None


def evidence_from_av_quarters(
    quarters: list[dict[str, Any]],
    *,
    symbol: str,
    fetched_at: str,
    source_url: str,
    fiscal_date_ending: str | None = None,
    consensus: float | None = None,
    consensus_stale: bool = False,
    unit: str = EPS_UNIT,
    currency: str = "USD",
    extra_refs: list[dict[str, Any]] | None = None,
) -> EarningsEvidence:
    rows = [row for row in quarters if isinstance(row, dict)]
    rows.sort(key=lambda item: str(item.get("fiscalDateEnding") or ""), reverse=True)
    current, select_gap = _select_print(rows, fiscal_date_ending)
    ending = str((current or {}).get("fiscalDateEnding") or fiscal_date_ending or "")
    actual = parse_number((current or {}).get("reportedEPS"))
    prior, prior_row, prior_gap = _select_prior(rows, ending) if ending else (None, None, None)
    used_consensus = consensus if consensus is not None else parse_number((current or {}).get("estimatedEPS"))
    gap = select_gap or prior_gap
    if consensus_stale:
        gap = "stale_estimate"
        used_consensus = None
    reported = str((current or {}).get("reportedDate") or "") or None
    bindings: dict[str, dict[str, Any]] = {}
    if actual is not None:
        bindings["actual"] = field_binding(
            name="actual",
            value=actual,
            function="EARNINGS",
            raw_field="reportedEPS",
            as_of=reported,
            fetched_at=fetched_at,
            source_url=source_url,
            role="reported_actual",
        )
    if prior is not None and prior_row is not None:
        bindings["prior_year_actual"] = field_binding(
            name="prior_year_actual",
            value=prior,
            function="EARNINGS",
            raw_field="reportedEPS",
            as_of=str(prior_row.get("reportedDate") or "") or None,
            fetched_at=fetched_at,
            source_url=source_url,
            role="reported_prior",
        )
    if used_consensus is not None and not consensus_stale:
        bindings["consensus"] = field_binding(
            name="consensus",
            value=used_consensus,
            function="EARNINGS",
            raw_field="estimatedEPS",
            as_of=reported,
            fetched_at=fetched_at,
            source_url=source_url,
            role=CONSENSUS_ROLE,
        )
    quarter = fiscal_quarter_id(symbol, ending)
    evidence = EarningsEvidence(
        symbol=symbol.upper(),
        fiscal_period=quarter or ending[:7],
        fiscal_date_ending=ending,
        metric="eps",
        actual=actual,
        prior_year_actual=prior,
        consensus=used_consensus,
        unit=unit,
        currency=currency,
        source_url=source_url,
        provider="alpha_vantage",
        published_at=reported,
        as_of=reported,
        fetched_at=fetched_at,
        raw_refs=[
            {
                "provider": "alpha_vantage",
                "function": "EARNINGS",
                "source_url": source_url,
                "raw": current or {},
            },
            *(extra_refs or []),
        ],
        gap=gap,
        fiscal_quarter=quarter,
        field_bindings=bindings,
        consensus_role=CONSENSUS_ROLE if used_consensus is not None and not consensus_stale else None,
        endpoints_called=["EARNINGS"],
    )
    return register_earnings(evidence)


def apply_estimate_snapshot(
    row: EarningsEvidence, estimates: list[dict[str, Any]], *, fetched_at: str, source_url: str
) -> EarningsEvidence:
    """Current/future snapshots only. Never a historical pre-report consensus."""
    reported = _as_date(row.published_at or row.fiscal_date_ending)
    current_future: list[dict[str, Any]] = []
    for item in estimates:
        if not isinstance(item, dict):
            continue
        horizon = str(item.get("horizon") or "").lower()
        item_date = _as_date(str(item.get("date") or item.get("fiscalDateEnding") or ""))
        if "historical" in horizon:
            continue
        if "next" in horizon:
            current_future.append(item)
            continue
        if reported and item_date and item_date <= reported:
            continue
        if item_date is not None:
            current_future.append(item)
    chosen = None
    if current_future:
        chosen = min(current_future, key=lambda item: str(item.get("date") or item.get("fiscalDateEnding") or ""))
    row.estimate_snapshot = {
        "source_url": source_url,
        "provider": "alpha_vantage",
        "function": "EARNINGS_ESTIMATES",
        "as_of": fetched_at,
        "fetched_at": fetched_at,
        "used_for_surprise": False,
        "role": "current_or_future_revision_snapshot",
        "horizon": str((chosen or {}).get("horizon") or "") or None,
        "row": chosen,
    }
    if "EARNINGS_ESTIMATES" not in row.endpoints_called:
        row.endpoints_called.append("EARNINGS_ESTIMATES")
    return row


def attach_transcript(
    row: EarningsEvidence,
    excerpts: list[dict[str, Any]],
    *,
    quarter: str,
    fetched_at: str = "",
    symbol: str | None = None,
) -> EarningsEvidence:
    want_quarter = row.fiscal_quarter or quarter
    want_symbol = (symbol or row.symbol or "").upper()
    cleaned: list[dict[str, str]] = []
    for item in excerpts:
        text = sanitize_untrusted(str(item.get("content") or item.get("excerpt") or ""), max_len=480)
        item_quarter = str(item.get("quarter") or quarter or "")
        item_symbol = str(item.get("symbol") or want_symbol).upper()
        if not text.strip():
            continue
        if item_quarter != want_quarter or item_symbol != want_symbol:
            continue
        cleaned.append(
            {
                "speaker": sanitize_untrusted(str(item.get("speaker") or ""), max_len=80),
                "title": sanitize_untrusted(str(item.get("title") or ""), max_len=120),
                "content": text,
                "quarter": item_quarter,
                "symbol": item_symbol,
                "source_url": str(
                    item.get("source_url") or AV_TRANSCRIPT_SOURCE.format(symbol=row.symbol, quarter=want_quarter)
                ),
                "fetched_at": str(item.get("fetched_at") or fetched_at or row.fetched_at),
            }
        )
    row.transcript_excerpts = cleaned[:4]
    if "EARNINGS_CALL_TRANSCRIPT" not in row.endpoints_called:
        row.endpoints_called.append("EARNINGS_CALL_TRANSCRIPT")
    return row


def associate_sec_filing(
    row: EarningsEvidence, sec_url: str = "", *, reason_code: str | None = None
) -> EarningsEvidence:
    """Same-day 8-K is filing metadata until a primary excerpt supports the actual."""
    note = (
        "SEC Atom skipped until a real contact User-Agent is configured"
        if reason_code == "sec_user_agent_not_configured"
        else "Accession proves a filing exists, not that it contains this EPS print"
    )
    row.sec_association = {
        "url": sec_url or "",
        "role": "filing_metadata",
        "verified": False,
        "note": note,
        "reason_code": reason_code,
    }
    return row


def documents_from_evidence(row: EarningsEvidence, *, sec_url: str = "") -> list[EventDocument]:
    if sec_url:
        associate_sec_filing(row, sec_url)
    published = f"{row.published_at}T16:00:00+00:00" if row.published_at and "T" not in str(row.published_at) else row.published_at
    vendor = EventDocument(
        title=f"{row.symbol} {row.fiscal_period} structured EPS print",
        url=row.source_url,
        publisher="Alpha Vantage",
        published_at=published,
        event_type="company_earnings",
        entities=[row.symbol, row.fiscal_period, row.fiscal_date_ending, "EPS"],
        countries=["US"],
        claims=[],
        body="",
        provider="alpha_vantage",
        last_fetched_at=row.fetched_at,
        body_source="",
        document_role="vendor_structured_print",
        evidence_role="structured_field_bindings",
    )
    return [vendor]


def documents_from_frozen_symbol(
    av: dict[str, Any],
    tr: dict[str, Any],
    estimates: dict[str, Any],
    sec: dict[str, Any],
    fetched_at: str,
    *,
    extra_refs: list[dict[str, Any]] | None = None,
) -> list[EventDocument]:
    symbol = str(av.get("symbol") or "AAPL").upper()
    source = str(av.get("http_source") or AV_EARNINGS_SOURCE.format(symbol=symbol))
    row = evidence_from_av_quarters(
        list(av.get("quarterlyEarnings") or []),
        symbol=symbol,
        fetched_at=fetched_at,
        source_url=source,
        extra_refs=extra_refs or [
            {
                "provider": "alpha_vantage",
                "function": "EARNINGS_ESTIMATES",
                "source_url": estimates.get("http_source"),
                "role": "current_or_future_revision_snapshot",
                "used_for_surprise": False,
            }
        ],
    )
    apply_estimate_snapshot(
        row,
        list(estimates.get("estimates") or []),
        fetched_at=fetched_at,
        source_url=str(estimates.get("http_source") or AV_ESTIMATES_SOURCE.format(symbol=row.symbol)),
    )
    attach_transcript(
        row,
        list(tr.get("excerpts") or []),
        quarter=str(tr.get("quarter") or row.fiscal_quarter),
        fetched_at=fetched_at,
        symbol=row.symbol,
    )
    return documents_from_evidence(row, sec_url=str(sec.get("url") or ""))


def load_frozen_earnings_documents(path: Path | None = None, payload: dict[str, Any] | None = None) -> list[EventDocument]:
    pack = payload or load_frozen_earnings(path)
    return documents_from_frozen_symbol(
        pack.get("av_earnings") or {},
        pack.get("av_transcript") or {},
        pack.get("av_estimates") or {},
        pack.get("sec_filing") or {},
        str(pack.get("fetched_at") or ""),
        extra_refs=[
            {
                "provider": "alpha_vantage",
                "function": "EARNINGS_ESTIMATES",
                "source_url": (pack.get("av_estimates") or {}).get("http_source"),
                "role": "current_or_future_revision_snapshot",
                "used_for_surprise": False,
            },
            {
                "provider": "fmp",
                "function": "stored_earnings_reports",
                "raw": (pack.get("stored_fmp") or [None])[0],
                "used_for_surprise": False,
            },
        ],
    )


def load_frozen_coverage(path: Path | None = None) -> dict[str, Any]:
    return load_frozen_earnings(path or FROZEN_COVERAGE_PATH)


def load_frozen_coverage_documents(path: Path | None = None, payload: dict[str, Any] | None = None) -> list[EventDocument]:
    pack = payload or load_frozen_coverage(path)
    fetched_at = str(pack.get("fetched_at") or "")
    rows: list[EventDocument] = []
    for item in pack.get("symbols") or []:
        if not isinstance(item, dict):
            continue
        av = item.get("av_earnings") or {}
        if not av.get("quarterlyEarnings") and not av.get("symbol"):
            continue
        rows.extend(
            documents_from_frozen_symbol(
                av,
                item.get("av_transcript") or {},
                item.get("av_estimates") or {},
                item.get("sec_filing") or {},
                str(item.get("fetched_at") or fetched_at),
            )
        )
    return rows


def local_degraded_earnings_documents() -> list[EventDocument]:
    """Local-only incomplete print. Missing prior/consensus so the chain stays degraded."""
    fetched_at = "local-degraded"
    source_url = "https://www.alphavantage.co/query?function=EARNINGS&symbol=AAPL&local=degraded"
    row = EarningsEvidence(
        symbol="AAPL",
        fiscal_period="2019Q3",
        fiscal_date_ending="2019-06-29",
        metric="eps",
        actual=0.55,
        prior_year_actual=None,
        consensus=None,
        unit=EPS_UNIT,
        currency="USD",
        source_url=source_url,
        provider="alpha_vantage",
        published_at="2019-07-30",
        as_of="2019-07-30",
        fetched_at=fetched_at,
        fiscal_quarter="2019Q3",
        field_bindings={
            "actual": field_binding(
                name="actual",
                value=0.55,
                function="EARNINGS",
                raw_field="reportedEPS",
                as_of="2019-07-30",
                fetched_at=fetched_at,
                source_url=source_url,
                role="reported_actual",
            )
        },
        consensus_role=None,
        endpoints_called=["EARNINGS"],
    )
    return documents_from_evidence(register_earnings(row))
