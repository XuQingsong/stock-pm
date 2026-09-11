"""Thesis layer: both sides, disagreement, invalidation. No range or odds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .causal import CausalImpact
from .change import ChangeSnapshot
from .expectation import ExpectationGap
from .types import SCOPE_GLOBAL, SCOPE_SECTOR, SCOPE_SYMBOL


MAX_DRIVERS = 3

QUALIFIED_CHANGE = "change"
QUALIFIED_EXPECTATION = "expectation"
QUALIFIED_CAUSAL = "causal"


@dataclass(frozen=True)
class Driver:
    text: str
    based_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThesisSnapshot:
    direction: str
    bull_drivers: tuple[Driver, ...]
    bear_drivers: tuple[Driver, ...]
    key_disagreement: str | None
    invalidation: str | None
    evidence_quality: str
    based_on_change_ids: tuple[str, ...]
    based_on_expectation_ids: tuple[str, ...]
    based_on_causal_impact_ids: tuple[str, ...]
    generated_at: str
    status: str
    reason: str
    symbol: str | None = None
    code: str = ""
    synthetic: bool = True


def _trim(drivers: Iterable[Driver | str]) -> tuple[Driver, ...]:
    out: list[Driver] = []
    for item in drivers:
        if isinstance(item, Driver):
            row = item
        else:
            text = str(item or "").strip()
            if not text:
                continue
            row = Driver(text=text, based_on=())
        if row.text:
            out.append(row)
        if len(out) >= MAX_DRIVERS:
            break
    return tuple(out)


def _catalog(
    changes: Iterable[ChangeSnapshot] | None,
    expectations: Iterable[ExpectationGap] | None,
    impacts: Iterable[CausalImpact] | None,
) -> dict[str, tuple[str, object]]:
    catalog: dict[str, tuple[str, object]] = {}
    for item in changes or ():
        catalog[item.id] = (QUALIFIED_CHANGE, item)
    for item in expectations or ():
        catalog[item.id] = (QUALIFIED_EXPECTATION, item)
    for item in impacts or ():
        catalog[item.id] = (QUALIFIED_CAUSAL, item)
    return catalog


def _is_qualified(kind: str, obj: object) -> bool:
    if kind == QUALIFIED_CHANGE:
        return isinstance(obj, ChangeSnapshot) and obj.materiality == "material"
    if kind == QUALIFIED_EXPECTATION:
        return isinstance(obj, ExpectationGap) and obj.status == "ok"
    if kind == QUALIFIED_CAUSAL:
        return isinstance(obj, CausalImpact) and obj.status == "valid"
    return False


def _scope_problem(kind: str, obj: object, symbol: str | None) -> str | None:
    if kind == QUALIFIED_CAUSAL and isinstance(obj, CausalImpact):
        target = obj.effect_target or (obj.exposure.target if obj.exposure else None)
        if symbol and target and target != symbol:
            return "cross_symbol"
        return None
    scope = getattr(obj, "scope", SCOPE_GLOBAL)
    subject = getattr(obj, "subject", None)
    if scope in {SCOPE_GLOBAL, SCOPE_SECTOR}:
        return "macro_requires_causal"
    if scope == SCOPE_SYMBOL:
        if not symbol or not subject or subject != symbol:
            return "cross_symbol"
    return None


def _citation_problem(
    drivers: tuple[Driver, ...],
    catalog: dict[str, tuple[str, object]],
    symbol: str | None,
) -> tuple[str, str] | None:
    for driver in drivers:
        if not driver.based_on:
            return ("free_text", "自由文本不得生成 Thesis：每个 driver 必须引用存在且合格的证据 ID")
        for eid in driver.based_on:
            if eid not in catalog:
                return ("missing_citation", "引用不存在：driver 指向了未知的 Change/Expectation/CausalImpact ID")
            kind, obj = catalog[eid]
            if not _is_qualified(kind, obj):
                return ("unqualified_citation", "引用不合格：driver 必须引用 material Change、ok Expectation 或 valid CausalImpact")
            scope_code = _scope_problem(kind, obj, symbol)
            if scope_code == "cross_symbol":
                return ("cross_symbol", "跨标的引用：证据 subject/target 与 Thesis 标的不一致")
            if scope_code == "macro_requires_causal":
                return ("macro_requires_causal", "全局/行业证据只能经 CausalImpact 进入公司 Thesis")
    return None


def _polarity_problem(
    bulls: tuple[Driver, ...],
    bears: tuple[Driver, ...],
    catalog: dict[str, tuple[str, object]],
) -> tuple[str, str] | None:
    def cited_impact_dirs(drivers: tuple[Driver, ...]) -> set[str]:
        dirs: set[str] = set()
        for driver in drivers:
            for eid in driver.based_on:
                kind, obj = catalog[eid]
                if kind == QUALIFIED_CAUSAL and isinstance(obj, CausalImpact) and obj.direction:
                    dirs.add(obj.direction)
        return dirs

    bull_dirs = cited_impact_dirs(bulls)
    bear_dirs = cited_impact_dirs(bears)
    if "bearish" in bull_dirs or (bull_dirs - {"bullish"}):
        return ("polarity_mismatch", "bull driver 引用了非 bullish 的方向性 CausalImpact")
    if "bullish" in bear_dirs or (bear_dirs - {"bearish"}):
        return ("polarity_mismatch", "bear driver 引用了非 bearish 的方向性 CausalImpact")
    return None


def _cited_ids(drivers: tuple[Driver, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for driver in drivers:
        for eid in driver.based_on:
            if eid not in seen:
                seen.append(eid)
    return tuple(seen)


def _partition_citations(
    cited: tuple[str, ...],
    catalog: dict[str, tuple[str, object]],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], list[CausalImpact]]:
    changes: list[str] = []
    gaps: list[str] = []
    causals: list[str] = []
    impact_objs: list[CausalImpact] = []
    for eid in cited:
        kind, obj = catalog[eid]
        if kind == QUALIFIED_CHANGE:
            changes.append(eid)
        elif kind == QUALIFIED_EXPECTATION:
            gaps.append(eid)
        elif kind == QUALIFIED_CAUSAL and isinstance(obj, CausalImpact):
            causals.append(eid)
            impact_objs.append(obj)
    return tuple(changes), tuple(gaps), tuple(causals), impact_objs


def _drivers_key(bulls: tuple[Driver, ...], bears: tuple[Driver, ...]) -> tuple:
    def pack(rows: tuple[Driver, ...]) -> tuple:
        return tuple((row.text, row.based_on) for row in rows)

    return (pack(bulls), pack(bears))


def thesis_changed_fields(
    previous: ThesisSnapshot | None,
    current: ThesisSnapshot | None,
) -> tuple[str, ...]:
    if previous is None or current is None:
        return ()
    changed: list[str] = []
    if previous.direction != current.direction:
        changed.append("direction")
    if _drivers_key(previous.bull_drivers, previous.bear_drivers) != _drivers_key(
        current.bull_drivers, current.bear_drivers
    ):
        changed.append("drivers")
    if (previous.key_disagreement or "").strip() != (current.key_disagreement or "").strip():
        changed.append("key_disagreement")
    if (previous.invalidation or "").strip() != (current.invalidation or "").strip():
        changed.append("invalidation")
    if previous.evidence_quality != current.evidence_quality:
        changed.append("evidence_quality")
    prev_cites = (
        set(previous.based_on_change_ids),
        set(previous.based_on_expectation_ids),
        set(previous.based_on_causal_impact_ids),
    )
    curr_cites = (
        set(current.based_on_change_ids),
        set(current.based_on_expectation_ids),
        set(current.based_on_causal_impact_ids),
    )
    if prev_cites != curr_cites:
        changed.append("citations")
    return tuple(changed)


def build_thesis_snapshot(
    *,
    bull_drivers: Iterable[Driver | str],
    bear_drivers: Iterable[Driver | str],
    key_disagreement: str | None,
    invalidation: str | None,
    changes: Iterable[ChangeSnapshot] | None = None,
    expectations: Iterable[ExpectationGap] | None = None,
    impacts: Iterable[CausalImpact] | None = None,
    generated_at: str | None = None,
    symbol: str | None = None,
    synthetic: bool = True,
) -> ThesisSnapshot:
    bulls = _trim(bull_drivers)
    bears = _trim(bear_drivers)
    catalog = _catalog(changes, expectations, impacts)
    stamp = generated_at or datetime.now(timezone.utc).isoformat()
    all_drivers = bulls + bears
    citation_error = _citation_problem(all_drivers, catalog, symbol) if all_drivers else ("missing_side", "缺支持或反方，不得生成强方向")
    cited = _cited_ids(all_drivers)
    change_ids, exp_ids, cau_ids, cited_impacts = (
        _partition_citations(cited, catalog) if not citation_error else ((), (), (), [])
    )

    def incomplete(code: str, reason: str, *, quality: str = "insufficient") -> ThesisSnapshot:
        return ThesisSnapshot(
            direction="incomplete",
            bull_drivers=bulls,
            bear_drivers=bears,
            key_disagreement=key_disagreement,
            invalidation=invalidation,
            evidence_quality=quality,
            based_on_change_ids=change_ids,
            based_on_expectation_ids=exp_ids,
            based_on_causal_impact_ids=cau_ids,
            generated_at=stamp,
            status="incomplete",
            reason=reason,
            symbol=symbol,
            code=code,
            synthetic=synthetic,
        )

    if not bulls or not bears:
        return incomplete("missing_side", "缺支持或反方，不得生成强方向")
    if citation_error:
        return incomplete(*citation_error)
    polarity_error = _polarity_problem(bulls, bears, catalog)
    if polarity_error:
        return incomplete(*polarity_error)
    if not (key_disagreement or "").strip() or not (invalidation or "").strip():
        return incomplete("missing_structure", "缺核心分歧或失效条件，不得生成强方向")

    valid_cited = [item for item in cited_impacts if item.status == "valid" and item.direction]
    dirs = {item.direction for item in valid_cited}
    if "bullish" in dirs and "bearish" in dirs:
        direction = "neutral"
        status = "neutral"
        code = "evidence_conflict"
        reason = "证据冲突：两侧均引用了方向相反的 valid CausalImpact；保留两侧，不按单一权重强行选择"
        quality = "partial"
    elif dirs == {"bullish"}:
        direction = "bullish"
        status = "ok"
        code = "ok"
        reason = "无对立的 valid CausalImpact；引用的确认路径支持偏多，仍保留反方 driver"
        quality = "complete" if cau_ids else "partial"
    elif dirs == {"bearish"}:
        direction = "bearish"
        status = "ok"
        code = "ok"
        reason = "无对立的 valid CausalImpact；引用的确认路径支持偏空，仍保留反方 driver"
        quality = "complete" if cau_ids else "partial"
    else:
        direction = "neutral"
        status = "neutral"
        code = "neutral"
        reason = "支持与反方同时存在，没有单一有效因果压过反方"
        quality = "partial"

    return ThesisSnapshot(
        direction=direction,
        bull_drivers=bulls,
        bear_drivers=bears,
        key_disagreement=key_disagreement,
        invalidation=invalidation,
        evidence_quality=quality,
        based_on_change_ids=change_ids,
        based_on_expectation_ids=exp_ids,
        based_on_causal_impact_ids=cau_ids,
        generated_at=stamp,
        status=status,
        reason=reason,
        symbol=symbol,
        code=code,
        synthetic=synthetic,
    )
