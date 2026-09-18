# Brain v2 Phase 2 validation

Generated: 2026-09-18T18:14:34.027973+00:00
Runtime: `phase2`

## Metrics

- 新增 causal edge 数: 1
- candidate / observed / supported / established: {'candidate': 2, 'observed': 0, 'supported': 22, 'established': 0, 'challenged': 1, 'deprecated': 0}
- 成功 transmission 数: 2
- blocked transmission 数: 1
- blocked reason: ['unsupported_causal_edge:bced_d225b1e9adff4d3fbd0d470b6a94e8a5:candidate']
- 新 Causal Gap 数: 1
- Research Question 数: 3
- 每个 material event 平均读取 causal edge 数: 2.75
- GLM-5.3 causal context token: 1969
- unsupported jump 数: 0
- unexpected Claim change 数: 0

## Cases

- Case 1 complete supported causal path: **PASS**
- Case 2 candidate edge stops transmission: **PASS**
- Case 3 new relationship is candidate not established: **PASS**
- Case 4 counter evidence challenges edge, history remains: **PASS**
- Case 5 causal gap creates research question, no jump: **PASS**
- Case 6 driver to financial metric, no base case rewrite: **PASS**

## Checklist

- [x] causal_edge_in_runtime
- [x] graph_reuses_brain_objects
- [x] exposure_expressed
- [x] glm_can_propose_candidate_edge
- [x] new_edge_not_established
- [x] unsupported_edge_blocks_transmission
- [x] claim_can_trace_causal_path
- [x] driver_to_financial_metric
- [x] causal_gap_creates_research_question
- [x] phase1_targeted_context_holds
- [x] no_full_graph_dump
- [x] no_unsupported_event_claim_jump
- [x] phase0_phase1_regression

Overall: PASS
