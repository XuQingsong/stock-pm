"""Change layer: previous vs current on one metric."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .facts import ValidatedBar, ValidatedFact, is_price_metric
from .numbers import as_number, pct_delta, round_pct, signed_delta
from .types import (
    SCOPE_GLOBAL,
    FactRef,
    FactValidationError,
    MaterialityRule,
    infer_scope,
    make_evidence_id,
    normalize_subject,
)


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
    scope: str = SCOPE_GLOBAL
    subject: str | None = None
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


def _require_bar(bar: Any, *, role: str) -> ValidatedBar:
    if not isinstance(bar, ValidatedBar):
        raise TypeError(
            f"price Change requires ValidatedBar for {role}; "
            "raw current_value is not accepted"
        )
    return bar


def _identity_of(obj: ValidatedBar | ValidatedFact | None) -> tuple[str, str] | None:
    if obj is None:
        return None
    scope = obj.scope or infer_scope(getattr(obj, "metric", "close"))
    subject = normalize_subject(scope, obj.subject)
    if not subject:
        raise FactValidationError("input fact/bar is missing subject")
    return scope, subject


def _reject_relabel(derived: tuple[str, str], scope: str | None, subject: str | None) -> None:
    derived_scope, derived_subject = derived
    if scope is not None and scope != derived_scope:
        raise FactValidationError("cannot relabel Change scope from builder arguments")
    if subject is not None and normalize_subject(derived_scope, subject) != derived_subject:
        raise FactValidationError("cannot relabel Change subject from builder arguments")


def build_change_snapshot(
    *,
    metric: str,
    current_as_of: str | None = None,
    previous_as_of: str | None = None,
    current_value: Any = None,
    previous_value: Any = None,
    current_bar: ValidatedBar | None = None,
    previous_bar: ValidatedBar | None = None,
    current_fact: ValidatedFact | None = None,
    previous_fact: ValidatedFact | None = None,
    comparison_window: str | None = None,
    materiality_rule: MaterialityRule | None = None,
    fact_refs: Iterable[FactRef] | None = None,
    unit: str | None = None,
    change_id: str | None = None,
    scope: str | None = None,
    subject: str | None = None,
    synthetic: bool = True,
) -> ChangeSnapshot:
    refs: list[FactRef] = list(fact_refs or ())
    identities: list[tuple[str, str]] = []
    if is_price_metric(metric):
        current = _require_bar(current_bar, role="current_bar")
        current_value = current.price_for(metric)
        current_as_of = current.as_of or current_as_of
        refs.extend(current.refs)
        identities.append(_identity_of(current))  # type: ignore[arg-type]
        if previous_bar is not None:
            previous = _require_bar(previous_bar, role="previous_bar")
            previous_value = previous.price_for(metric)
            previous_as_of = previous.as_of or previous_as_of
            refs.extend(previous.refs)
            identities.append(_identity_of(previous))  # type: ignore[arg-type]
        elif previous_value is not None:
            raise TypeError(
                "price Change previous baseline must be ValidatedBar; "
                "raw previous_value is not accepted"
            )
    else:
        if current_fact is not None:
            if not isinstance(current_fact, ValidatedFact):
                raise TypeError("current_fact must be ValidatedFact")
            if current_fact.metric != metric:
                raise FactValidationError("ValidatedFact metric does not match Change metric")
            current_value = current_fact.value
            current_as_of = current_fact.as_of or current_as_of
            unit = current_fact.unit if unit is None else unit
            refs.extend(current_fact.refs)
            identities.append(_identity_of(current_fact))  # type: ignore[arg-type]
        if previous_fact is not None:
            if not isinstance(previous_fact, ValidatedFact):
                raise TypeError("previous_fact must be ValidatedFact")
            if previous_fact.metric != metric:
                raise FactValidationError("ValidatedFact metric does not match Change metric")
            previous_value = previous_fact.value
            previous_as_of = previous_fact.as_of or previous_as_of
            refs.extend(previous_fact.refs)
            identities.append(_identity_of(previous_fact))  # type: ignore[arg-type]

    if identities:
        unique = set(identities)
        if len(unique) > 1:
            raise FactValidationError("previous/current subject or scope mismatch")
        derived_scope, derived_subject = identities[0]
        _reject_relabel((derived_scope, derived_subject), scope, subject)
    else:
        derived_scope = infer_scope(metric)
        if derived_scope != SCOPE_GLOBAL:
            raise FactValidationError("symbol-scoped Change requires ValidatedFact/ValidatedBar identity")
        derived_subject = "global"
        if scope is not None and scope != derived_scope:
            raise FactValidationError("cannot relabel Change scope from builder arguments")
        if subject is not None and normalize_subject(derived_scope, subject) != derived_subject:
            raise FactValidationError("cannot relabel Change subject from builder arguments")

    current_n = as_number(current_value)
    previous_n = as_number(previous_value)
    has_baseline = previous_n is not None
    delta = signed_delta(current_n, previous_n)
    rel = round_pct(pct_delta(current_n, previous_n))
    direction = _direction(delta, has_baseline=has_baseline)
    materiality = _is_material(delta, rel, materiality_rule)
    ident = change_id or make_evidence_id(
        "chg", derived_scope, derived_subject, metric, current_as_of or "", previous_as_of or ""
    )
    return ChangeSnapshot(
        id=ident,
        metric=metric,
        previous_value=previous_n,
        current_value=current_n,
        previous_as_of=previous_as_of,
        current_as_of=current_as_of,
        delta=delta,
        delta_pct=rel,
        comparison_window=comparison_window,
        direction=direction,
        materiality=materiality,
        fact_refs=tuple(dict.fromkeys(refs)),
        summary=_summary(direction, materiality, has_baseline=has_baseline),
        unit=unit,
        scope=derived_scope,
        subject=derived_subject,
        synthetic=synthetic,
    )
