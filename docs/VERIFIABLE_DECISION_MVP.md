# Verifiable decision MVP

This iteration succeeds only if it makes the private decision loop faster and auditable. It does not redesign the site.

## MVP scope

1. **What Changed** compares two observations, ranks material deltas, and never fills missing values.
2. **Expectation Gap** compares actuals with the latest available consensus and separately records consensus revision.
3. **Structured Thesis** requires 1–3 bull drivers, 1–3 bear drivers, the key disagreement, evidence quality, and an explicit invalidation condition.
4. **Frozen Prediction** records generation time, model version, snapshot ID, and a content hash that fails verification after any rewrite.
5. **Prediction Review / Attribution** reports direction, benchmark-relative return, drawdown, whether invalidation occurred first, and one controlled attribution category. Known evidence must predate the prediction; new information must postdate it.

## Measurable acceptance criteria

- 100% of newly evaluated predictions have a valid frozen hash, model version, and data snapshot ID.
- 100% of reviewable predictions receive `hit`, `miss`, `inconclusive`, or `invalid_data`; missing inputs never become a hit or miss.
- 100% of reviews expose absolute and, when available, benchmark-relative return.
- 100% of `known_but_underweighted` and `new_information` evidence passes timestamp validation.
- What Changed shows only measurable deltas and sorts material changes first.
- Thesis records cannot be created without both bull and bear evidence plus invalidation.

## Product success experiment

Run the MVP on the user's real watchlist for four weeks. Record, without changing the existing UI layout:

- median seconds from opening a stock to writing/confirming a decision (target: <= 30 seconds);
- percentage of sessions where What Changed removes the need to reread unchanged material (target: >= 60%);
- frozen-prediction coverage (target: 100% of new predictions);
- review completion within two trading days of horizon end (target: >= 90%);
- percentage of misses with timestamp-valid attribution (target: >= 90%);
- direction hit rate and excess return versus QQQ, reported separately and never treated as the sole success metric.

The product experiment fails if these targets are not met; adding more indicators or UI is not a substitute.
