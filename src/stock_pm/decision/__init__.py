"""Investment Decision Kernel v1 — pure functions, no I/O."""

from .causal import (
    CHANNEL_COMMODITY_REVENUE,
    CHANNEL_DURATION,
    CHANNEL_FUEL_COST,
    OIL_CONSUMER_MECHANISM,
    OIL_PRODUCER_MECHANISM,
    RATES_DISCOUNT_MECHANISM,
    UNCONFIRMED,
    CausalImpact,
    ClaimSource,
    Exposure,
    MarketConfirmation,
    assess_market_confirmation,
    build_causal_impact,
    canonical_metric,
)
from .change import NO_MATERIAL_CHANGE, ChangeSnapshot, build_change_snapshot
from .expectation import ExpectationGap, ExpectationPoint, build_expectation_gap
from .facts import (
    FactValidationError,
    OhlcCheck,
    ValidatedBar,
    ValidatedFact,
    require_valid_bar,
    require_valid_fact,
    validate_ohlc,
)
from .tension import PriceExpectationTension, build_price_expectation_tension
from .thesis import Driver, ThesisSnapshot, build_thesis_snapshot, thesis_changed_fields
from .types import FactRef, MaterialityRule
from .what_changed import (
    NO_MATERIAL_CHANGE_THESIS,
    WhatChanged,
    WhatChangedItem,
    build_what_changed,
)

__all__ = [
    "CHANNEL_COMMODITY_REVENUE",
    "CHANNEL_DURATION",
    "CHANNEL_FUEL_COST",
    "ChangeSnapshot",
    "CausalImpact",
    "ClaimSource",
    "Driver",
    "ExpectationGap",
    "ExpectationPoint",
    "Exposure",
    "FactRef",
    "FactValidationError",
    "MarketConfirmation",
    "MaterialityRule",
    "NO_MATERIAL_CHANGE",
    "NO_MATERIAL_CHANGE_THESIS",
    "OIL_CONSUMER_MECHANISM",
    "OIL_PRODUCER_MECHANISM",
    "OhlcCheck",
    "PriceExpectationTension",
    "RATES_DISCOUNT_MECHANISM",
    "ThesisSnapshot",
    "UNCONFIRMED",
    "ValidatedBar",
    "ValidatedFact",
    "WhatChanged",
    "WhatChangedItem",
    "assess_market_confirmation",
    "build_causal_impact",
    "build_change_snapshot",
    "build_expectation_gap",
    "build_price_expectation_tension",
    "build_thesis_snapshot",
    "build_what_changed",
    "canonical_metric",
    "require_valid_bar",
    "require_valid_fact",
    "thesis_changed_fields",
    "validate_ohlc",
]
