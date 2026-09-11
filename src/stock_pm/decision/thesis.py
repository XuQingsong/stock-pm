"""Thesis layer: both sides, disagreement, invalidation. No range or odds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .causal import CausalImpact
from .change import ChangeSnapshot
from .expectation import ExpectationGap


MAX_DRIVERS = 3


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
            row = Driver(text=text)
        if row.text:
            out.append(row)
        if len(out) >= MAX_DRIVERS:
            break
    return tuple(out)


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
    synthetic: bool = True,
) -> ThesisSnapshot:
    bulls = _trim(bull_drivers)
    bears = _trim(bear_drivers)
    change_ids = tuple(item.id for item in (changes or ()) if item.materiality == "material")
    exp_ids = tuple(item.id for item in (expectations or ()) if item.status == "ok")
    cau_ids = tuple(item.id for item in (impacts or ()) if item.status == "valid")
    stamp = generated_at or datetime.now(timezone.utc).isoformat()

    if not bulls or not bears:
        return ThesisSnapshot(
            direction="incomplete",
            bull_drivers=bulls,
            bear_drivers=bears,
            key_disagreement=key_disagreement,
            invalidation=invalidation,
            evidence_quality="insufficient",
            based_on_change_ids=change_ids,
            based_on_expectation_ids=exp_ids,
            based_on_causal_impact_ids=cau_ids,
            generated_at=stamp,
            status="incomplete",
            reason="缺支持或反方，不得生成强方向",
            synthetic=synthetic,
        )
    if not (key_disagreement or "").strip() or not (invalidation or "").strip():
        return ThesisSnapshot(
            direction="incomplete",
            bull_drivers=bulls,
            bear_drivers=bears,
            key_disagreement=key_disagreement,
            invalidation=invalidation,
            evidence_quality="insufficient",
            based_on_change_ids=change_ids,
            based_on_expectation_ids=exp_ids,
            based_on_causal_impact_ids=cau_ids,
            generated_at=stamp,
            status="incomplete",
            reason="缺核心分歧或失效条件，不得生成强方向",
            synthetic=synthetic,
        )

    valid_impacts = [item for item in (impacts or ()) if item.status == "valid" and item.direction]
    dirs = {item.direction for item in valid_impacts}
    if len(dirs) > 1 or (bulls and bears and (not valid_impacts or dirs == {"bullish", "bearish"})):
        direction = "neutral"
        status = "neutral"
        reason = "支持与反方冲突，保留两侧，不隐藏反方、不强行选择方向"
        quality = "partial"
    elif dirs == {"bullish"}:
        direction = "bullish"
        status = "ok"
        reason = "有效因果与多空结构可陈述，仍保留反方"
        quality = "complete" if cau_ids else "partial"
    elif dirs == {"bearish"}:
        direction = "bearish"
        status = "ok"
        reason = "有效因果与多空结构可陈述，仍保留反方"
        quality = "complete" if cau_ids else "partial"
    else:
        direction = "neutral"
        status = "neutral"
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
        synthetic=synthetic,
    )
