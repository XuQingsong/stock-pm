"""Brain research chain: Evidence → Assumption → Thesis. Independent of the daily desk."""

from .classify import classify_template
from .errors import (
    CrossTickerError,
    DepthLimitError,
    ProvenanceError,
    ResearchError,
    ResearchPermissionError,
)
from .issuer import cik_for, fiscal_year_end_month_for, merge_identity
from .service import ResearchService
from .types import ACTOR_API, ACTOR_PM, AgentInput, AgentOutput, FollowUpSpec

__all__ = [
    "ACTOR_API",
    "ACTOR_PM",
    "AgentInput",
    "AgentOutput",
    "CrossTickerError",
    "DepthLimitError",
    "FollowUpSpec",
    "ProvenanceError",
    "ResearchError",
    "ResearchPermissionError",
    "ResearchService",
    "cik_for",
    "classify_template",
    "fiscal_year_end_month_for",
    "merge_identity",
]
