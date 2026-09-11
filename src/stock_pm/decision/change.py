"""Change layer: previous vs current on one metric."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .numbers import as_number, pct_delta, round_pct, signed_delta
from .types import FactRef, MaterialityRule


NO_MATERIAL_CHANGE = "今日无重大变化"


@dataclass(frozen=True)
class ChangeSnapshot:
    id: str
    metric: str
    previous_value: float | None
    current_value: float | None
    previous_as_of: str | None
    current_as_of: str | None
    delta: float | None
    delta_pct: float | None
    comparison_window: str | None
    direction: str
    materiality: str
    fact_refs: tuple[FactRef, ...]
    summary: str
    unit: str | None = None
    synthetic: bool = True

    def to_dict(self) -> dict[str, Any]:
        from .types import to_dict

        return to_dict(self)


def _direction(delta: float | None, *, has_baseline: bool) -> str:
    if not has_baseline or delta is None:
        return "unknown"
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "unchanged"


def _is_material(delta: float | None, delta_pct: float | None, rule: MaterialityRule | None) -> str:
    if delta is None and delta_pct is None:
        return "unknown"
    rule = rule or MaterialityRule()
    if rule.abs_delta is None and rule.pct_delta is None:
        if delta == 0 or delta_pct == 0:
            return "immaterial"
        return "unknown"
    if rule.abs_delta is not None and delta is not None and abs(delta) >= rule.abs_delta:
        return "material"
    if rule.pct_delta is not None and delta_pct is not None and abs(delta_pct) >= rule.pct_delta:
        return "material"
    return "immaterial"


def _summary(direction: str, materiality: str, *, has_baseline: bool) -> str:
    if not has_baseline:
        return "无比较基准，不能声称上升或下降"
    if materiality == "immaterial":
        return NO_MATERIAL_CHANGE
    if direction == "up":
        return "上升且达到重要性阈值"
    if direction == "down":
        return "下降且达到重要性阈值"
    if direction == "unchanged":
        return NO_MATERIAL_CHANGE
    return "变化无法判定"


def build_change_snapshot(
    *,
    metric: str,
    current_value: Any,
    current_as_of: str | None,
    previous_value: Any = None,
    previous_as_of: str | None = None,
    comparison_window: str | None = None,
    materiality_rule: MaterialityRule | None = None,
    fact_refs: Iterable[FactRef] | None = None,
    unit: str | None = None,
    change_id: str | None = None,
    synthetic: bool = True,
) -> ChangeSnapshot:
    current = as_number(current_value)
    previous = as_number(previous_value)
    has_baseline = previous is not None
    delta = signed_delta(current, previous)
    rel = round_pct(pct_delta(current, previous))
    direction = _direction(delta, has_baseline=has_baseline)
    materiality = _is_material(delta, rel, materiality_rule)
    refs = tuple(fact_refs or ())
    ident = change_id or f"chg|{metric}|{current_as_of or ''}|{previous_as_of or ''}"
    return ChangeSnapshot(
        id=ident,
        metric=metric,
        previous_value=previous,
        current_value=current,
        previous_as_of=previous_as_of,
        current_as_of=current_as_of,
        delta=delta,
        delta_pct=rel,
        comparison_window=comparison_window,
        direction=direction,
        materiality=materiality,
        fact_refs=refs,
        summary=_summary(direction, materiality, has_baseline=has_baseline),
        unit=unit,
        synthetic=synthetic,
    )
