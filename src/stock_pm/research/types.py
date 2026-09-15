from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Mapping


ACTOR_PM = "pm_judge"
ACTOR_API = "human_api"
ACTOR_WORKFLOW = "workflow"

ASSUMPTION_STATUSES = ("unverified", "strengthened", "unchanged", "weakened", "broken")
THESIS_ROLES = ("core", "supporting", "watch", "risk", "none", "monitoring")
THESIS_ROLE_ALIASES = {
    "core": "core",
    "supporting": "supporting",
    "watch": "monitoring",
    "monitoring": "monitoring",
    "risk": "risk",
    "none": "none",
}
IMPORTANCE_LEVELS = ("low", "medium", "high", "critical")
LINK_DIRECTIONS = ("support", "oppose", "contextual")
LINK_STRENGTHS = ("strong", "moderate", "weak")
LINK_RELEVANCE = ("direct", "indirect", "background")
SOURCE_QUALITIES = (
    "primary",
    "high_quality_secondary",
    "secondary",
    "weak",
)
EVIDENCE_DIRECTIONS = ("support", "oppose", "neutral")
TASK_STATUSES = ("pending", "running", "completed", "blocked", "cancelled")

CASE_KEYS = (
    "horizon",
    "revenue",
    "earnings",
    "eps",
    "fcf",
    "growth_assumptions",
    "margin_assumptions",
    "multiple",
    "multiple_reason",
    "valuation_method",
    "target_value",
    "target_display",
    "upside_downside",
    "key_assumption_ids",
    "notes",
    "sensitivity",
)


def to_plain(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if is_dataclass(row):
        return asdict(row)
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError(f"unsupported research object: {type(row)!r}")


def empty_valuation_case() -> dict[str, Any]:
    return {
        "horizon": None,
        "revenue": None,
        "earnings": None,
        "eps": None,
        "fcf": None,
        "growth_assumptions": None,
        "margin_assumptions": None,
        "multiple": None,
        "multiple_reason": None,
        "valuation_method": None,
        "target_value": None,
        "target_display": None,
        "upside_downside": None,
        "key_assumption_ids": [],
        "notes": "",
        "sensitivity": [],
    }


def normalize_valuation_case(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    out = empty_valuation_case()
    for key in CASE_KEYS:
        if key not in raw:
            continue
        out[key] = raw[key]
    if out["key_assumption_ids"] is None:
        out["key_assumption_ids"] = []
    return out


TASK_SOURCE_TYPES = (
    "template_seed",
    "evidence_discovered",
    "assumption_gap",
    "agent_followup",
    "pm_request",
)


@dataclass(slots=True)
class FollowUpSpec:
    title: str
    description: str = ""
    task_type: str = "verify_assumption"
    assigned_agents: tuple[str, ...] = ()
    required_data: tuple[str, ...] = ()
    priority: int = 50
    source_reason: str = "agent_follow_up"
    source_type: str = "agent_followup"


@dataclass(slots=True)
class AgentInput:
    ticker: str
    task: dict[str, Any]
    research_pack: dict[str, Any] = field(default_factory=dict)
    current_thesis: dict[str, Any] | None = None
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    market_context: dict[str, Any] = field(default_factory=dict)


AGENT_SEARCH = "search_data"
AGENT_FUNDAMENTAL = "fundamental"
AGENT_INDUSTRY = "industry"
AGENT_QUANT = "quant"
AGENT_RISK = "risk"
AGENT_ASSUMPTION_ENGINE = "assumption_engine"
AGENT_PM = "pm_judge"

QUALITY_LEVELS = ("sufficient", "partial", "insufficient")
QUALITY_AXES = (
    "quality_for_discovery",
    "quality_for_fundamental_analysis",
    "quality_for_valuation",
    "quality_for_final_thesis",
)

PROPOSED_ASSUMPTION_STATUSES = ("strengthen", "weaken", "unchanged", "broken")
PROPOSED_STATUS_ALIASES = {
    "strengthen": "strengthen",
    "strengthened": "strengthen",
    "weaken": "weaken",
    "weakened": "weaken",
    "unchanged": "unchanged",
    "broken": "broken",
}
TENSION_STATES = ("fundamentals_ahead", "price_ahead", "aligned", "unclear")
NEGATIVE_MARKET_REACTION_TASK = (
    "Explain the negative market reaction despite positive fundamental evidence"
)

AGENT_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["findings", "new_evidence", "follow_up_tasks", "confidence"],
    "properties": {
        "findings": {"type": "array", "items": {"type": "string"}},
        "new_evidence": {"type": "array", "items": {"type": "object"}},
        "new_assumptions": {"type": "array", "items": {"type": "object"}},
        "supported_assumption_ids": {"type": "array", "items": {"type": "string"}},
        "challenged_assumption_ids": {"type": "array", "items": {"type": "string"}},
        "assumption_links": {"type": "array", "items": {"type": "object"}},
        "proposed_assumption_changes": {"type": "array", "items": {"type": "object"}},
        "follow_up_tasks": {"type": "array"},
        "missing_data": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
}


@dataclass(slots=True)
class AgentOutput:
    findings: list[str] = field(default_factory=list)
    new_evidence: list[dict[str, Any]] = field(default_factory=list)
    new_assumptions: list[dict[str, Any]] = field(default_factory=list)
    supported_assumption_ids: list[str] = field(default_factory=list)
    challenged_assumption_ids: list[str] = field(default_factory=list)
    assumption_links: list[dict[str, Any]] = field(default_factory=list)
    follow_up_tasks: list[FollowUpSpec | dict[str, Any]] = field(default_factory=list)
    proposed_assumption_changes: list[dict[str, Any]] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    confidence: float | None = None
    agent_name: str = ""
    model: str | None = None
    prompt_version: str | None = None


def follow_up_from_payload(item: FollowUpSpec | Mapping[str, Any]) -> FollowUpSpec:
    if isinstance(item, FollowUpSpec):
        return item
    agents = item.get("assigned_agents") or ()
    required = item.get("required_data") or ()
    return FollowUpSpec(
        title=str(item.get("title") or "").strip() or "follow-up",
        description=str(item.get("description") or ""),
        task_type=str(item.get("task_type") or "verify_assumption"),
        assigned_agents=tuple(agents),
        required_data=tuple(required) if not isinstance(required, dict) else tuple(required),
        priority=int(item.get("priority") or 50),
        source_reason=str(item.get("source_reason") or "agent_follow_up"),
        source_type=str(item.get("source_type") or "agent_followup"),
    )
