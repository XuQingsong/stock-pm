"""Structured earnings evidence. Numbers are never inferred."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .policy import sanitize_untrusted
from .types import EventDocument


FROZEN_EARNINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "events_5c_b_frozen_earnings.json"
RULE_ID = "earnings_implication.v1"
ALIGN_ID = "period_align.v1"
EPS_UNIT = "USD/share"
AV_EARNINGS_SOURCE = "https://www.alphavantage.co/query?function=EARNINGS&symbol={symbol}"
AV_ESTIMATES_SOURCE = "https://www.alphavantage.co/query?function=EARNINGS_ESTIMATES&symbol={symbol}"
AV_TRANSCRIPT_SOURCE = "https://www.alphavantage.co/query?function=EARNINGS_CALL_TRANSCRIPT&symbol={symbol}&quarter={quarter}"

_REGISTRY: dict[str, "EarningsEvidence"] = {}


class FrozenEarningsError(RuntimeError):
    """Tampered or malformed frozen earnings pack."""


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

    def key(self) -> str:
        return f"{self.symbol}|{self.metric}|{self.fiscal_date_ending[:7]}"

    def complete(self) -> bool:
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
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reset_earnings_registry() -> None:
    _REGISTRY.clear()


def register_earnings(row: EarningsEvidence) -> EarningsEvidence:
    compute_changes(row)
    _REGISTRY[row.key()] = row
    return row


def earnings_for(symbol: str, *, metric: str = "eps", fiscal_date_ending: str = "") -> EarningsEvidence | None:
    if fiscal_date_ending:
        return _REGISTRY.get(f"{symbol.upper()}|{metric}|{fiscal_date_ending[:7]}")
    prefix = f"{symbol.upper()}|{metric}|"
    rows = [row for key, row in _REGISTRY.items() if key.startswith(prefix)]
    rows.sort(key=lambda item: item.fiscal_date_ending, reverse=True)
    return rows[0] if rows else None


def earnings_for_event(event: Any) -> EarningsEvidence | None:
    entities = [str(item).upper() for item in getattr(event, "entities", []) or []]
    symbol = next((item for item in entities if item.isalpha() and len(item) <= 5), "")
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


def period_month_key(fiscal_date_ending: str) -> str:
    text = str(fiscal_date_ending or "")
    return text[:7] if len(text) >= 7 else ""


def prior_month_key(fiscal_date_ending: str) -> str:
    key = period_month_key(fiscal_date_ending)
    if len(key) != 7:
        return ""
    return f"{int(key[:4]) - 1}{key[4:]}"


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
    }
    row.surprise_inputs = {
        "actual": row.actual,
        "consensus": row.consensus,
        "formula": "(actual - consensus) / abs(consensus)",
        "align": ALIGN_ID,
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


def frozen_earnings_material(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_id": payload.get("audit_id"),
        "sec_filing": payload.get("sec_filing") or {},
        "av_earnings": payload.get("av_earnings") or {},
        "av_estimates": payload.get("av_estimates") or {},
        "av_transcript": payload.get("av_transcript") or {},
        "stored_fmp": payload.get("stored_fmp") or [],
    }


def compute_frozen_earnings_integrity(payload: dict[str, Any]) -> str:
    encoded = json.dumps(frozen_earnings_material(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_frozen_earnings(path: Path | None = None) -> dict[str, Any]:
    target = path or FROZEN_EARNINGS_PATH
    if not target.is_file():
        raise FrozenEarningsError("frozen_earnings_missing")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("live") is True:
        raise FrozenEarningsError("frozen_earnings_marked_live")
    if payload.get("data_class") != "frozen_official_audit":
        raise FrozenEarningsError("frozen_earnings_not_audit")
    expected = str(payload.get("integrity_sha256") or "")
    actual = compute_frozen_earnings_integrity(payload)
    if not expected or expected != actual:
        raise FrozenEarningsError("frozen_earnings_hash_mismatch")
    return payload


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
    current = None
    if fiscal_date_ending:
        current = next((row for row in rows if str(row.get("fiscalDateEnding") or "")[:7] == fiscal_date_ending[:7]), None)
    if current is None and rows:
        current = rows[0]
    ending = str((current or {}).get("fiscalDateEnding") or fiscal_date_ending or "")
    actual = parse_number((current or {}).get("reportedEPS"))
    prior = None
    want_prior = prior_month_key(ending)
    for row in rows:
        if period_month_key(str(row.get("fiscalDateEnding") or "")) == want_prior:
            if str(row.get("fiscalDateEnding") or "")[5:7] != ending[5:7]:
                continue
            prior = parse_number(row.get("reportedEPS"))
            break
    used_consensus = consensus if consensus is not None else parse_number((current or {}).get("estimatedEPS"))
    gap = None
    if consensus_stale:
        gap = "stale_estimate"
        used_consensus = None
    evidence = EarningsEvidence(
        symbol=symbol.upper(),
        fiscal_period=ending[:7],
        fiscal_date_ending=ending,
        metric="eps",
        actual=actual,
        prior_year_actual=prior,
        consensus=used_consensus,
        unit=unit,
        currency=currency,
        source_url=source_url,
        provider="alpha_vantage",
        published_at=str((current or {}).get("reportedDate") or "") or None,
        as_of=str((current or {}).get("reportedDate") or "") or None,
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
    )
    return register_earnings(evidence)


def attach_transcript(row: EarningsEvidence, excerpts: list[dict[str, Any]], *, quarter: str) -> EarningsEvidence:
    cleaned: list[dict[str, str]] = []
    for item in excerpts:
        text = sanitize_untrusted(str(item.get("content") or item.get("excerpt") or ""), max_len=480)
        if not text.strip():
            continue
        cleaned.append(
            {
                "speaker": sanitize_untrusted(str(item.get("speaker") or ""), max_len=80),
                "title": sanitize_untrusted(str(item.get("title") or ""), max_len=120),
                "content": text,
                "quarter": str(item.get("quarter") or quarter),
                "source_url": str(item.get("source_url") or AV_TRANSCRIPT_SOURCE.format(symbol=row.symbol, quarter=quarter)),
            }
        )
    row.transcript_excerpts = cleaned[:4]
    return row


def documents_from_evidence(row: EarningsEvidence, *, sec_url: str = "") -> list[EventDocument]:
    fact = (
        f"{row.symbol} {row.fiscal_period} EPS actual {row.actual} {row.unit}"
        if row.actual is not None
        else f"{row.symbol} {row.fiscal_period} EPS actual missing"
    )
    body = (
        f"{fact}. Prior-year actual {row.prior_year_actual}. Consensus {row.consensus}. "
        f"Currency {row.currency}. Provider {row.provider}."
    )
    published = f"{row.published_at}T16:00:00+00:00" if row.published_at and "T" not in row.published_at else row.published_at
    official = EventDocument(
        title=f"{row.symbol} {row.fiscal_period} EPS {row.actual} vs consensus {row.consensus}",
        url=sec_url or row.source_url,
        publisher="SEC EDGAR" if sec_url else "Alpha Vantage",
        published_at=published,
        event_type="company_earnings",
        entities=[row.symbol, row.fiscal_period, row.fiscal_date_ending, "EPS"],
        countries=["US"],
        claims=[fact],
        body=body,
        provider="official" if sec_url else "alpha_vantage",
        last_fetched_at=row.fetched_at,
        body_source="structured_earnings",
        document_role="earnings_print",
    )
    vendor = EventDocument(
        title=f"{row.symbol} structured EPS print {row.fiscal_period}",
        url=row.source_url,
        publisher="Alpha Vantage",
        published_at=published,
        event_type="company_earnings",
        entities=[row.symbol, row.fiscal_period, row.fiscal_date_ending, "EPS"],
        countries=["US"],
        claims=[fact],
        body=body,
        provider="alpha_vantage",
        last_fetched_at=row.fetched_at,
        body_source="structured_earnings",
        document_role="earnings_print",
    )
    return [official, vendor]


def load_frozen_earnings_documents(path: Path | None = None) -> list[EventDocument]:
    pack = load_frozen_earnings(path)
    av = pack.get("av_earnings") or {}
    tr = pack.get("av_transcript") or {}
    sec = pack.get("sec_filing") or {}
    row = evidence_from_av_quarters(
        list(av.get("quarterlyEarnings") or []),
        symbol=str(av.get("symbol") or "AAPL"),
        fetched_at=str(pack.get("fetched_at") or ""),
        source_url=str(av.get("http_source") or AV_EARNINGS_SOURCE.format(symbol="AAPL")),
        extra_refs=[
            {
                "provider": "alpha_vantage",
                "function": "EARNINGS_ESTIMATES",
                "source_url": (pack.get("av_estimates") or {}).get("http_source"),
            },
            {
                "provider": "fmp",
                "function": "stored_earnings_reports",
                "raw": (pack.get("stored_fmp") or [None])[0],
            },
        ],
    )
    attach_transcript(row, list(tr.get("excerpts") or []), quarter=str(tr.get("quarter") or ""))
    return documents_from_evidence(row, sec_url=str(sec.get("url") or ""))
