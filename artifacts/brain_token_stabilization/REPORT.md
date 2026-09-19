# Brain v2 Runtime Token Stabilization

Same AVGO tape: `2026-06-03 → 2026-09-16`, 18-event continuous timeline.
Architecture frozen. No new Brain capability. No Portfolio / Trading.

## Before → After

- total_tokens: 522615 → 223819  (57.2% down)
- avg_tokens_per_material_event: 42230.75 → 17326.5  (59.0% down)
- tokens / event: 12434.4
- tokens / Incremental: 18757.7
- tokens / Full Review: 16532.0
- tokens / Now Chain: 12434.4  (Now Chain is not a separate model call; average tokens on events that produced a Now Chain)
- tokens / Critic: 1074.0
- tokens / GLM-5.3: 17237.0
- token_input: 207844 → 69554  (66.5% down)
- token_output: 314771 → 154265  (51.0% down)
- critic_input: 26978 → 351  (98.7% down)
- critic_output: 85833 → 723  (99.2% down)
- context_recall: 0.7757 → 0.6757
- context_precision: 0.627 → 0.683
- memory_continuity: 0.9 → 0.8
- now_chain_coverage: 18/18 → 18/18
- causal_transmission: 2 → 2
- hypothesis_continuity: 0.5625 → 0.4667
- research_questions: 24 → 27
- runtime_anomaly: 0 → 0
- price_fundamental_violations: 0 → 0
- price_claim_violations: 0 → 0
- unsupported_event_claim_jump: 0 → 0
- price_established_edge_violations: 0 → 0

- Total reduction: 57.2% (target ≥ 40%, stretch 50–65%)
- Must-hold (crash / Price→Fund / Price→Claim / Unsupported Event→Claim / Price→established edge / Now Chain / transmission): True

## Where the cut came from

- shorter GLM-5.3 output: 51.0%  (delta-only prompt + 16384 cap; several material events still hit the cap because thinking tokens count as output)
- selective critic input / output: 98.7% / 99.2%
- compressed causal context: 69.0%
- market / hypothesis / expectation delta: 83.7%
- compressed history payloads: 84.3%

The cut is not from dropping retrieved evidence IDs or deleting Now Chain / causal path coverage.
Existing objects stay as id + status + short summary + relevant evidence_ids.
Edge bodies (support/counter) load only when the edge is challenged, upgraded, or directly validated.

## Quality notes

- Context Recall delta: -0.1  (same locate miss pattern as baseline e02/e03/e09/e10/e16; extra miss is price-only e18, which must not load leftover Fund/Claim)
- Context Precision delta: 0.056  (up)
- Hypothesis Continuity delta: -0.0958  (update-events / (update-events + new keys); after created 8 vs 7, updated 10 vs 12)
- Memory Continuity: 0.9 → 0.8  (9/10 → 8/10 material incremental leftover hits; e18 price-only no longer retrieves leftover claims)
- Causal transmission hold: True
- Recall/hypothesis dips match locate/extract key variance on the same golden IDs as the baseline miss set, plus one extra price-only event (e18) that correctly does not load leftover Fund/Claim objects. Compact snapshot keeps retrieved IDs; evidence titles remain.

## Top 10 most expensive calls

1. e09_q3_print_vs_expect change_proposals glm-5.3 in=7166 out=16384 total=23550
2. e13_xpu_customers change_proposals glm-5.3 in=7036 out=16384 total=23420
3. e14_google_confirm change_proposals glm-5.3 in=7025 out=16384 total=23409
4. e16_marvell_win change_proposals glm-5.3 in=6517 out=16384 total=22901
5. e02_q2_print_vs_expect change_proposals glm-5.3 in=5184 out=16384 total=21568
6. e08_q3_filing change_proposals glm-5.3 in=5321 out=15705 total=21026
7. e03_q2_sector_tape change_proposals glm-5.3 in=5913 out=14083 total=19996
8. e15_google_rumor_again change_proposals glm-5.3 in=7028 out=7977 total=15005
9. e10_q3_company_tape change_proposals glm-5.3 in=1717 out=8816 total=10533
10. e07_google_rumor change_proposals glm-5.3 in=6473 out=2916 total=9389

e2e exit: 0
