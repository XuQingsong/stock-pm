"""Brain research chain: Evidence → Assumption → Thesis. Independent of the daily desk."""

from .backfill import ResearchDataBackfill
from .classify import classify_template
from .errors import (
    CrossTickerError,
    DepthLimitError,
    ProvenanceError,
    ResearchError,
    ResearchPermissionError,
    SchemaError,
)
from .issuer import cik_for, fiscal_year_end_month_for, merge_identity
from .service import ResearchService
from .types import ACTOR_API, ACTOR_PM, AGENT_FUNDAMENTAL, AGENT_SEARCH, AgentInput, AgentOutput, FollowUpSpec
from .workflow import run_new_ticker_research

__all__ = [
    "ACTOR_API",
    "ACTOR_PM",
    "AGENT_FUNDAMENTAL",
    "AGENT_SEARCH",
    "AgentInput",
    "AgentOutput",
    "CrossTickerError",
    "DepthLimitError",
    "FollowUpSpec",
    "ProvenanceError",
    "ResearchDataBackfill",
    "ResearchError",
    "ResearchPermissionError",
    "ResearchService",
    "SchemaError",
    "cik_for",
    "classify_template",
    "fiscal_year_end_month_for",
    "merge_identity",
    "run_new_ticker_research",
]
