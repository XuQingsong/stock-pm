"""WhatChanged: material deltas, not a count of facts or notes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .causal import CausalImpact
from .change import ChangeSnapshot
from .expectation import ExpectationGap
from .thesis import ThesisSnapshot


NO_MATERIAL_CHANGE_THESIS = "无重大变化，原判断不变"


@dataclass(frozen=True)
class WhatChangedItem:
    kind: str
    what: str
    why_it_matters: str
    affects: str
    thesis_effect: str
    why_thesis_effect: str
    ref_id: str | None


@dataclass(frozen=True)
class WhatChanged:
    summary: str
    items: tuple[WhatChangedItem, ...]
    thesis_changed: bool
    synthetic: bool = True


def _thesis_shifted(previous: ThesisSnapshot | None, current: ThesisSnapshot | None) -> bool:
    if previous is None or current is None:
        return False
    if current.status == "incomplete":
        return False
    return previous.direction != current.direction


def build_what_changed(
    *,
    changes: Iterable[ChangeSnapshot] = (),
    expectations: Iterable[ExpectationGap] = (),
    impacts: Iterable[CausalImpact] = (),
    previous_thesis: ThesisSnapshot | None = None,
    current_thesis: ThesisSnapshot | None = None,
    synthetic: bool = True,
) -> WhatChanged:
    shifted = _thesis_shifted(previous_thesis, current_thesis)
    items: list[WhatChangedItem] = []

    for impact in impacts:
        if impact.status != "valid":
            continue
        items.append(
            WhatChangedItem(
                kind="causal",
                what=" → ".join(impact.chain) if impact.chain else (impact.mechanism or "因果"),
                why_it_matters=impact.reason,
                affects=impact.effect_target or "",
                thesis_effect="changed" if shifted else "unchanged",
                why_thesis_effect=(
                    "因果链改变了方向陈述"
                    if shifted
                    else "已有判断已覆盖该机制，方向未改"
                ),
                ref_id=impact.id,
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
                why_thesis_effect="预期修订尚未单独推翻 Thesis" if not shifted else "预期修订参与了 Thesis 更新",
                ref_id=gap.id,
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
                why_thesis_effect="数值变化未跨过判断阈值" if not shifted else "该变化进入了新的 Thesis",
                ref_id=change.id,
            )
        )

    if shifted and current_thesis is not None:
        items.append(
            WhatChangedItem(
                kind="thesis",
                what=f"Thesis {previous_thesis.direction if previous_thesis else None} → {current_thesis.direction}",
                why_it_matters=current_thesis.reason,
                affects="thesis",
                thesis_effect="changed",
                why_thesis_effect="方向或核心结构已更新",
                ref_id=None,
            )
        )

    if not items:
        return WhatChanged(
            summary=NO_MATERIAL_CHANGE_THESIS,
            items=(),
            thesis_changed=False,
            synthetic=synthetic,
        )

    summary = items[0].what if shifted else "有变化但 Thesis 未改" if items else NO_MATERIAL_CHANGE_THESIS
    if shifted:
        summary = items[-1].what if items and items[-1].kind == "thesis" else "Thesis 已改变"
    return WhatChanged(
        summary=summary,
        items=tuple(items),
        thesis_changed=shifted,
        synthetic=synthetic,
    )
