"""WhatChanged: material deltas, not a count of facts or notes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .causal import CausalImpact
from .change import ChangeSnapshot
from .expectation import ExpectationGap
from .thesis import ThesisSnapshot, thesis_changed_fields
from .timeparse import parse_as_of


NO_MATERIAL_CHANGE_THESIS = "无重大变化，原判断不变"
FORBIDDEN_THRESHOLD_CLAIM = "数值变化未跨过判断阈值"
FORBIDDEN_COVERED_CLAIM = "已有判断已覆盖该机制"
FORBIDDEN_REVISION_CLAIM = "预期修订尚未单独推翻 Thesis"

_LAYER_RANK = {"causal": 0, "expectation": 1, "change": 2, "thesis": 3}


@dataclass(frozen=True)
class WhatChangedItem:
    kind: str
    what: str
    why_it_matters: str
    affects: str
    thesis_effect: str
    why_thesis_effect: str
    ref_id: str | None
    as_of: str | None = None
    material: bool = True


@dataclass(frozen=True)
class WhatChanged:
    summary: str
    items: tuple[WhatChangedItem, ...]
    thesis_changed: bool
    changed_fields: tuple[str, ...] = ()
    synthetic: bool = True


def _parse_recency(value: str | None) -> datetime:
    dt = parse_as_of(value)
    if dt is None or dt == "invalid":
        return datetime.min.replace(tzinfo=None)
    return dt.replace(tzinfo=None)


def _sort_key(item: WhatChangedItem) -> tuple:
    material_rank = 0 if item.material else 1
    recency = _parse_recency(item.as_of)
    try:
        recency_score = -recency.timestamp() if recency != datetime.min else 0.0
    except (OverflowError, OSError, ValueError):
        recency_score = 0.0
    layer = _LAYER_RANK.get(item.kind, 9)
    return (material_rank, recency_score, layer, item.ref_id or item.what)


def _thesis_effect_reason(
    *,
    shifted: bool,
    changed_fields: tuple[str, ...],
    current_thesis: ThesisSnapshot | None,
    linkage: str,
) -> str:
    if shifted:
        fields = ", ".join(changed_fields) if changed_fields else "semantic fields"
        return f"{linkage}；Thesis 已变化字段：{fields}"
    if current_thesis is not None:
        return f"{linkage}；Thesis semantic fields unchanged ({current_thesis.reason})"
    return linkage


def build_what_changed(
    *,
    changes: Iterable[ChangeSnapshot] = (),
    expectations: Iterable[ExpectationGap] = (),
    impacts: Iterable[CausalImpact] = (),
    previous_thesis: ThesisSnapshot | None = None,
    current_thesis: ThesisSnapshot | None = None,
    synthetic: bool = True,
) -> WhatChanged:
    changed_fields = thesis_changed_fields(previous_thesis, current_thesis)
    shifted = bool(changed_fields)
    items: list[WhatChangedItem] = []

    for impact in impacts:
        if impact.status != "valid":
            continue
        as_of = impact.cause.current_as_of if impact.cause else None
        items.append(
            WhatChangedItem(
                kind="causal",
                what=" → ".join(impact.chain) if impact.chain else (impact.mechanism or "因果"),
                why_it_matters=impact.reason,
                affects=impact.effect_target or "",
                thesis_effect="changed" if shifted else "unchanged",
                why_thesis_effect=_thesis_effect_reason(
                    shifted=shifted,
                    changed_fields=changed_fields,
                    current_thesis=current_thesis,
                    linkage=impact.reason,
                ),
                ref_id=impact.id,
                as_of=as_of,
                material=True,
            )
        )

    for gap in expectations:
        if gap.status != "ok":
            continue
        if gap.revision_pct is None and gap.surprise_pct is None:
            continue
        if gap.revision_pct == 0 and (gap.surprise_pct == 0 or gap.surprise_pct is None):
            continue
        what = f"{gap.metric} surprise {gap.surprise_pct}%, revision {gap.revision_pct}%"
        items.append(
            WhatChangedItem(
                kind="expectation",
                what=what,
                why_it_matters=gap.reason,
                affects=gap.fiscal_period or gap.metric,
                thesis_effect="changed" if shifted else "unchanged",
                why_thesis_effect=_thesis_effect_reason(
                    shifted=shifted,
                    changed_fields=changed_fields,
                    current_thesis=current_thesis,
                    linkage=gap.reason,
                ),
                ref_id=gap.id,
                as_of=gap.actual_as_of or gap.latest_consensus_as_of,
                material=True,
            )
        )

    for change in changes:
        if change.materiality != "material":
            continue
        items.append(
            WhatChangedItem(
                kind="change",
                what=f"{change.metric} {change.direction} {change.delta}",
                why_it_matters=change.summary,
                affects=change.metric,
                thesis_effect="changed" if shifted else "unchanged",
                why_thesis_effect=_thesis_effect_reason(
                    shifted=shifted,
                    changed_fields=changed_fields,
                    current_thesis=current_thesis,
                    linkage=change.summary,
                ),
                ref_id=change.id,
                as_of=change.current_as_of,
                material=True,
            )
        )

    if shifted and current_thesis is not None:
        items.append(
            WhatChangedItem(
                kind="thesis",
                what=(
                    f"Thesis {previous_thesis.direction if previous_thesis else None} → {current_thesis.direction}"
                    if "direction" in changed_fields
                    else f"Thesis fields changed: {', '.join(changed_fields)}"
                ),
                why_it_matters=current_thesis.reason,
                affects="thesis",
                thesis_effect="changed",
                why_thesis_effect=f"semantic diff: {', '.join(changed_fields)}",
                ref_id=None,
                as_of=current_thesis.generated_at,
                material=True,
            )
        )

    items.sort(key=_sort_key)

    for item in items:
        if FORBIDDEN_THRESHOLD_CLAIM in item.why_thesis_effect:
            raise ValueError("WhatChanged must not claim a material change is below the thesis threshold")
        if FORBIDDEN_COVERED_CLAIM in item.why_thesis_effect or FORBIDDEN_REVISION_CLAIM in item.why_thesis_effect:
            raise ValueError("WhatChanged must not invent uncovered thesis-effect copy")

    if not items:
        return WhatChanged(
            summary=NO_MATERIAL_CHANGE_THESIS,
            items=(),
            thesis_changed=False,
            changed_fields=(),
            synthetic=synthetic,
        )

    if shifted:
        thesis_items = [item for item in items if item.kind == "thesis"]
        summary = thesis_items[0].what if thesis_items else "Thesis 已改变"
    else:
        summary = "有变化但 Thesis 未改"

    return WhatChanged(
        summary=summary,
        items=tuple(items),
        thesis_changed=shifted,
        changed_fields=changed_fields,
        synthetic=synthetic,
    )
