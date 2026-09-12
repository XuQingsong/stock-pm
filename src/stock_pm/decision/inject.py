"""Test/preview-only fault injection. Production cannot enable this."""

from __future__ import annotations

import os
from typing import Any, Iterable

from stock_pm.config import Settings

INJECT_ENV_ALLOWLIST = frozenset({"development", "test", "local"})
INJECT_KEYS = frozenset({
    "missing_gold",
    "missing_nfp",
    "missing_prior_consensus",
    "missing_news",
    "missing_options",
})


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def inject_allowed(settings: Settings | None = None) -> bool:
    """Dual opt-in. Missing APP_ENV is production-like and never injects."""
    if settings is None:
        enabled = _truthy(os.getenv("ENABLE_DECISION_INJECT"))
        env = (os.getenv("APP_ENV") or "").strip().lower()
    else:
        enabled = bool(getattr(settings, "enable_decision_inject", False))
        env = (settings.app_env or "").strip().lower()
    return enabled and env in INJECT_ENV_ALLOWLIST


def parse_inject_tokens(raw: Iterable[str] | str | None) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        parts = raw.replace("|", ",").split(",")
    else:
        parts = []
        for item in raw:
            parts.extend(str(item).replace("|", ",").split(","))
    return frozenset(part.strip().lower() for part in parts if part.strip().lower() in INJECT_KEYS)


def apply_inject(bundle: dict[str, Any], tokens: Iterable[str]) -> dict[str, Any]:
    wanted = parse_inject_tokens(tokens)
    if not wanted:
        return bundle
    payload = dict(bundle)
    payload["inject"] = sorted(wanted)
    if "missing_nfp" in wanted:
        payload["macro_events"] = [
            row for row in list(payload.get("macro_events") or [])
            if str(row.get("event_type") or "").lower() != "nfp"
        ]
    if "missing_gold" in wanted:
        payload["macro_events"] = [
            row for row in list(payload.get("macro_events") or [])
            if str(row.get("event_type") or "").lower() != "gold"
        ]
    if "missing_news" in wanted:
        payload["news"] = []
    if "missing_options" in wanted:
        payload["option_wall"] = []
        payload["options"] = []
    if "missing_prior_consensus" in wanted:
        earnings = []
        for row in list(payload.get("earnings") or []):
            item = dict(row)
            item["prior_consensus"] = None
            item["prior_consensus_as_of"] = None
            earnings.append(item)
        payload["earnings"] = earnings
    return payload
