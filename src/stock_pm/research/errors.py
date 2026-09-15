"""Research-layer errors. Distinct from daily-desk DatabaseError."""

from __future__ import annotations


class ResearchError(ValueError):
    """Base error for Brain research invariants."""


class ProvenanceError(ResearchError):
    """A claim is missing source, time, or a traceable reference."""


class ResearchPermissionError(ResearchError):
    """Only pm_judge may change Assumption status or write a Thesis."""


class VersionConflict(ResearchError):
    """Thesis versioning refused an in-place update or stale version."""


class CrossTickerError(ResearchError):
    """Evidence, Assumption, or Thesis mixed two tickers."""


class DepthLimitError(ResearchError):
    """Follow-up task exceeded the workflow max_depth."""
