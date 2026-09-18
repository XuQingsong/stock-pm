# Phase 0 + Phase 1 功能验证报告

生成时间: 2026-09-18T17:12:48+00:00
范围: AVGO golden Brain + 6 类真实/半真实事件。未进入 Phase 2，未改架构。

## 1. 六个 Case 的完整 trace

### Case A — 完全重复的新闻

- 历史依据: Q3 FY2026 Exhibit 99.1 (2026-09-02) said AI accelerator and networking demand continues to be very strong. Secondary wires reprinted the same sentence.
- Input: `Broadcom says demand for AI accelerators and networking continues to be very strong`
- Path: `l0_stop`
- L0: stop=True reason=duplicate duplicate=True
- GLM-5.2 extract: called=False type=None novelty=None material=None
- Extract fact: (none)
- Materiality: False — duplicate
- Affected objects: {}
- Snapshot counts: {"states": 0, "drivers": 0, "claims": 0, "exposures": 0, "evidence": 0, "counter_evidence": 0, "history": 0, "causal_edges": 0}
- Snapshot states: []
- Snapshot drivers: []
- Snapshot claims: []
- GLM-5.3 called: False
- Proposal count: 0
- Phase 0 approve/reject/review: {"approve": 0, "reject": 0, "requires_review": 0, "items": []}
- Brain changed: []
- Full review: False reason=None
- Context miss count: 0
- Anomalies: []
- Latency ms: 0

### Case B — 有新内容但投资意义很低的普通新闻

- 历史依据: Broadcom CEO Hock Tan regularly presents at the Goldman Sachs Communacopia + Technology Conference. A scheduled conference appearance is not an operating update.
- Input: `Broadcom CEO Hock Tan scheduled for Goldman Sachs conference appearance`
- Path: `observation_memory`
- L0: stop=False reason=pass duplicate=False
- GLM-5.2 extract: called=True type=other novelty=none material=False
- Extract fact: Hock Tan will make a conference appearance at the Goldman Sachs Communacopia + Technology Conference. No operating update and no new information.
- Materiality: False — L1 marked the item non-material or not new.
- Affected objects: {}
- Snapshot counts: {"states": 0, "drivers": 0, "claims": 0, "exposures": 0, "evidence": 0, "counter_evidence": 0, "history": 0, "causal_edges": 0}
- Snapshot states: []
- Snapshot drivers: []
- Snapshot claims: []
- GLM-5.3 called: False
- Proposal count: 0
- Phase 0 approve/reject/review: {"approve": 0, "reject": 0, "requires_review": 0, "items": []}
- Brain changed: []
- Full review: False reason=None
- Context miss count: 0
- Anomalies: []
- Latency ms: 6274

### Case C — 明确、重要、已确认的 customer / demand event

- 历史依据: Google has been a confirmed Broadcom custom-TPU/ASIC customer for years. This case uses that known relationship as a post-print confirmation of an expanded custom-silicon order, not a rumor.
- Input: `Google confirmed a Broadcom custom-silicon order expansion for next-generation TPU`
- Path: `incremental`
- L0: stop=False reason=pass duplicate=False
- GLM-5.2 extract: called=True type=customer novelty=new material=True
- Extract fact: Google, a named Broadcom customer, confirmed it will expand custom ASIC / TPU orders with Broadcom for the next-generation accelerator deployment. The update is an issuer-linked customer demand event, not a rumor.
- Materiality: True — Material operating or customer information.
- Affected objects: {"states": ["bst_cf6f0b17ea0f47d78c05082a0034de0d", "bst_21b14d3978024a2b8a6e622e84d40fdc", "bst_154e6e1ddc4f4970a61cdb2798b0fa51"], "drivers": ["bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "bdrv_4469e497110847e7a3961129f05e5a33", "bdrv_e605ec342c0a4888bec050bd17106982", "bdrv_c65613d424614e7ba3e474bd1c3d4948", "bdrv_0b42bfa225df4760a06d0a81c9df0d12"], "claims": ["bclm_f4454cfe04e94211a79b23116bcf5de8", "bclm_2f3b915b62064c8a98300c530fa331ff", "bclm_a84fd6c830884f80b7c4b1d49f984b24", "bclm_a63762a2ab4f4410ad923ea9b1002c53", "bclm_426dd93ffbfa4167ab49970c97da681f"], "exposures": []}
- Snapshot counts: {"states": 3, "drivers": 5, "claims": 5, "exposures": 0, "evidence": 0, "counter_evidence": 1, "history": 8, "causal_edges": 7}
- Snapshot states: ['Q3 FY2026 results', 'Negative post-earnings price reactions', 'Valuation snapshot']
- Snapshot drivers: ['hyperscaler_customer_concentration', 'ai_silicon_competitive_position', 'ai_semiconductor_demand_durability', 'valuation_multiple_ai_dependency', 'balance_sheet_leverage_deleveraging']
- Snapshot claims: ['AI semiconductor demand durability sets the length of the growth ramp', 'The AI ramp implies unquantified dependence on a few hyperscaler buyers', 'Whether the guided 66% non-GAAP operating margin is structural or peak-cycle', 'The premium multiple is conditional on the AI ramp persisting', 'AI is approaching a majority of revenue, tying company economics to one cycle']
- GLM-5.3 called: True
- Proposal count: 4
- Phase 0 approve/reject/review: {"approve": 0, "reject": 0, "requires_review": 4, "items": [{"proposal_id": "bcpr_b6c0d0b9c5924f619ef0b53ea000c032", "object_type": "company_state", "object_id": "google_custom_asic_order_expansion", "decision": "requires_review", "reason_code": "abnormal_change_scope_requires_review", "reason": "Confirmed, high-confidence customer demand event (explicitly not a rumor) from an independent source, establishing a named hyperscaler customer deepening its custom-silicon relationship with Broadcom…"}, {"proposal_id": "bcpr_bce76b3664c144029caca637d6765ac6", "object_type": "value_driver", "object_id": "bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "decision": "requires_review", "reason_code": "abnormal_change_scope_requires_review", "reason": "The confirmed Google order expansion directly fills this driver's stated evidence gap on the customer order pipeline: it validates hyperscaler demand while deepening dependence on a small set of name…"}, {"proposal_id": "bcpr_96d322f06d3f47e099ac4546e5cf548b", "object_type": "value_driver", "object_id": "bdrv_4469e497110847e7a3961129f05e5a33", "decision": "requires_review", "reason_code": "abnormal_change_scope_requires_review", "reason": "The confirmed Google expansion is the first direct evidence of custom-silicon design-win retention at a major hyperscaler, countering the Marvell displacement counter-evidence attached to this driver…"}, {"proposal_id": "bcpr_ce9df658f3be4de889af6a908df47ef0", "object_type": "core_claim", "object_id": "bclm_2f3b915b62064c8a98300c530fa331ff", "decision": "requires_review", "reason_code": "abnormal_change_scope_requires_review", "reason": "A confirmed direct-fact named-customer event (not a rumor) adds decisive evidence to this claim's premise: Google is a confirmed hyperscaler buyer expanding orders, which supports the concentration t…"}]}
- Brain changed: []
- Full review: False reason=None
- Context miss count: 2
- Anomalies: [{"code": "snapshot_missing_key_evidence", "detail": "Targeted snapshot evidence list is empty while Brain evidence exists."}]
- Latency ms: 242770

Proposals:
- `company_state` google_custom_asic_order_expansion / news: Confirmed, high-confidence customer demand event (explicitly not a rumor) from an independent source, establishing a named hyperscaler customer deepening its custom-silicon relationship with Broadcom. Recorded as a factual company state; n…
- `value_driver` bdrv_414ad8bb1d8343bea291e8dc5eb44bba / news: The confirmed Google order expansion directly fills this driver's stated evidence gap on the customer order pipeline: it validates hyperscaler demand while deepening dependence on a small set of named AI infrastructure buyers.
- `value_driver` bdrv_4469e497110847e7a3961129f05e5a33 / news: The confirmed Google expansion is the first direct evidence of custom-silicon design-win retention at a major hyperscaler, countering the Marvell displacement counter-evidence attached to this driver's related claim; it does not yet resolv…
- `core_claim` bclm_2f3b915b62064c8a98300c530fa331ff / news: A confirmed direct-fact named-customer event (not a rumor) adds decisive evidence to this claim's premise: Google is a confirmed hyperscaler buyer expanding orders, which supports the concentration thesis and mitigates near-term customer-l…

Context misses:
- `evidence` rev_a65ae2866d404168b4b90236ae2f13a6 Q3 FY2026 Exhibit 99.1: AI accelerator and networking demand continues to be very strong; Q4 AI semiconductor revenue g… hits=['demand', 'accelerator'] score=0.059
- `evidence` rev_843a1ee827964a139673007f7c44e957 Broadcom priced cash tender offers for certain outstanding notes in June 2026. hits=['broadcom', 'broadcom', 'broadcom', 'broadcom'] score=0.03

### Case D — 重要但未经确认的 rumor

- 历史依据: Markets have repeatedly priced unconfirmed Google in-house silicon / TPU order-cut rumors against Broadcom. The rumor is decision-relevant if true, but unconfirmed.
- Input: `Unconfirmed: Google may reduce Broadcom custom TPU orders`
- Path: `incremental`
- L0: stop=False reason=pass duplicate=False
- GLM-5.2 extract: called=True type=customer novelty=new material=True
- Extract fact: Rumor that Google may reduce Broadcom ASIC / TPU orders as it expands in-house silicon. The report is unconfirmed and uses anonymous sources.
- Materiality: True — Unconfirmed but potentially material; GLM-5.3 may only propose Shadow State / Research Questions.
- Affected objects: {"states": ["bst_cf6f0b17ea0f47d78c05082a0034de0d", "bst_6b43658a7e584a2a974d1c5a7a5c2cfe", "bst_21b14d3978024a2b8a6e622e84d40fdc", "bst_154e6e1ddc4f4970a61cdb2798b0fa51"], "drivers": ["bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "bdrv_c65613d424614e7ba3e474bd1c3d4948", "bdrv_0b42bfa225df4760a06d0a81c9df0d12", "bdrv_8dd8af15e6a84090b239eb0c00f6917f"], "claims": ["bclm_f4454cfe04e94211a79b23116bcf5de8", "bclm_2f3b915b62064c8a98300c530fa331ff", "bclm_a84fd6c830884f80b7c4b1d49f984b24", "bclm_a63762a2ab4f4410ad923ea9b1002c53", "bclm_426dd93ffbfa4167ab49970c97da681f"], "exposures": []}
- Snapshot counts: {"states": 4, "drivers": 4, "claims": 5, "exposures": 0, "evidence": 0, "counter_evidence": 1, "history": 8, "causal_edges": 7}
- Snapshot states: ['Q3 FY2026 results', 'EPS estimate misses', 'Negative post-earnings price reactions', 'Valuation snapshot']
- Snapshot drivers: ['hyperscaler_customer_concentration', 'valuation_multiple_ai_dependency', 'balance_sheet_leverage_deleveraging', 'gaap_non_gaap_earnings_gap']
- Snapshot claims: ['AI semiconductor demand durability sets the length of the growth ramp', 'The AI ramp implies unquantified dependence on a few hyperscaler buyers', 'Whether the guided 66% non-GAAP operating margin is structural or peak-cycle', 'The premium multiple is conditional on the AI ramp persisting', 'AI is approaching a majority of revenue, tying company economics to one cycle']
- GLM-5.3 called: True
- Proposal count: 3
- Phase 0 approve/reject/review: {"approve": 3, "reject": 0, "requires_review": 0, "items": [{"proposal_id": "bcpr_6c29cc7f327948a9b3d62dd2ace7767a", "object_type": "shadow_state", "object_id": "bshd_avgo_google_tpu_order_reduction_rumor", "decision": "approve", "reason_code": "", "reason": "The event is an unconfirmed rumor (confidence: low, fact_reliability: rumor, anonymous sources, tier-3 source), so per rules it must not modify Current State, Value Drivers, Core Claims, or the Base…"}, {"proposal_id": "bcpr_8b1d9f0980924988b6928b5e40ecf56b", "object_type": "research_question", "object_id": "brq_avgo_google_asic_revenue_exposure", "decision": "approve", "reason_code": "", "reason": "A rumor cannot advance to claims without verification and exposure sizing; this question defines the evidence required before any Base Case or Core Claim impact could even be considered."}, {"proposal_id": "bcpr_dc00f833080f4baf88a7ef7044fe943b", "object_type": "market_attention", "object_id": "bmat_avgo_google_tpu_rumor_reaction", "decision": "approve", "reason_code": "", "reason": "The rumor is unconfirmed, but the market's reaction is a low-cost credibility signal given documented sensitivity to hyperscaler customer news. Monitoring requires no modification to states, drivers,…"}]}
- Brain changed: ['shadow_state:bshd_avgo_google_tpu_order_reduction_rumor', 'research_question:brq_avgo_google_asic_revenue_exposure', 'market_attention:bmat_avgo_google_tpu_rumor_reaction', 'shadow:bshd_377d312bb14b434e804e8b7c4ee66f32', 'question:brq_e91d1c796fe04480a1398fcc7609a271']
- Full review: False reason=None
- Context miss count: 1
- Anomalies: [{"code": "snapshot_missing_key_evidence", "detail": "Targeted snapshot evidence list is empty while Brain evidence exists."}]
- Latency ms: 210547

Proposals:
- `shadow_state` bshd_avgo_google_tpu_order_reduction_rumor / rumor: The event is an unconfirmed rumor (confidence: low, fact_reliability: rumor, anonymous sources, tier-3 source), so per rules it must not modify Current State, Value Drivers, Core Claims, or the Base Case — the event's possible_affected lis…
- `research_question` brq_avgo_google_asic_revenue_exposure / rumor: A rumor cannot advance to claims without verification and exposure sizing; this question defines the evidence required before any Base Case or Core Claim impact could even be considered.
- `market_attention` bmat_avgo_google_tpu_rumor_reaction / rumor: The rumor is unconfirmed, but the market's reaction is a low-cost credibility signal given documented sensitivity to hyperscaler customer news. Monitoring requires no modification to states, drivers, or claims.

Context misses:
- `evidence` rev_843a1ee827964a139673007f7c44e957 Broadcom priced cash tender offers for certain outstanding notes in June 2026. hits=['broadcom', 'broadcom', 'broadcom'] score=0.04

### Case E — 与已有 Core Claim 明显相关的新反面证据

- 历史依据: The seeded AVGO Brain already records that a hyperscaler awarding custom AI chip work to Marvell moved AVGO 3.9%. This case is a follow-on confirmed competitive loss.
- Input: `Marvell wins a hyperscaler custom ASIC program Broadcom had been expected to supply`
- Path: `incremental`
- L0: stop=False reason=pass duplicate=False
- GLM-5.2 extract: called=True type=competition novelty=new material=True
- Extract fact: Marvell Technology announced a hyperscaler custom ASIC design win that had been expected to go to Broadcom, adding counter evidence against Broadcom's AI accelerator competitive position and customer concentration.
- Materiality: True — Material operating or customer information.
- Affected objects: {"states": ["bst_cf6f0b17ea0f47d78c05082a0034de0d"], "drivers": ["bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "bdrv_4469e497110847e7a3961129f05e5a33", "bdrv_e605ec342c0a4888bec050bd17106982", "bdrv_0b42bfa225df4760a06d0a81c9df0d12"], "claims": ["bclm_f4454cfe04e94211a79b23116bcf5de8", "bclm_2f3b915b62064c8a98300c530fa331ff", "bclm_a84fd6c830884f80b7c4b1d49f984b24", "bclm_a63762a2ab4f4410ad923ea9b1002c53", "bclm_426dd93ffbfa4167ab49970c97da681f"], "exposures": []}
- Snapshot counts: {"states": 1, "drivers": 4, "claims": 5, "exposures": 0, "evidence": 0, "counter_evidence": 1, "history": 8, "causal_edges": 7}
- Snapshot states: ['Q3 FY2026 results']
- Snapshot drivers: ['hyperscaler_customer_concentration', 'ai_silicon_competitive_position', 'ai_semiconductor_demand_durability', 'balance_sheet_leverage_deleveraging']
- Snapshot claims: ['AI semiconductor demand durability sets the length of the growth ramp', 'The AI ramp implies unquantified dependence on a few hyperscaler buyers', 'Whether the guided 66% non-GAAP operating margin is structural or peak-cycle', 'The premium multiple is conditional on the AI ramp persisting', 'AI is approaching a majority of revenue, tying company economics to one cycle']
- GLM-5.3 called: True
- Proposal count: 3
- Phase 0 approve/reject/review: {"approve": 0, "reject": 0, "requires_review": 3, "items": [{"proposal_id": "bcpr_206955e65b4f4e0eba32b8a2f1fd25ba", "object_type": "value_driver", "object_id": "bdrv_4469e497110847e7a3961129f05e5a33", "decision": "requires_review", "reason_code": "abnormal_change_scope_requires_review", "reason": "The driver's current_state explicitly states there is 'no evidence in the pack on market share, competitor moves, or design win pipeline' — this confirmed Reuters report is precisely that missing evi…"}, {"proposal_id": "bcpr_8793e2ac52af453cabc8b745992cd115", "object_type": "value_driver", "object_id": "bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "decision": "requires_review", "reason_code": "abnormal_change_scope_requires_review", "reason": "The event's possible_affected explicitly includes hyperscaler customer concentration: a hyperscaler exercising an alternative-supplier option is direct evidence for the switching and bargaining-power…"}, {"proposal_id": "bcpr_8d30142786d54449ae37efbef69c4875", "object_type": "scenario", "object_id": "bscn_avgo_custom_asic_share_erosion", "decision": "requires_review", "reason_code": "abnormal_change_scope_requires_review", "reason": "Confirmed counter-evidence against a high-importance, high-uncertainty driver warrants a trackable downside scenario rather than a base-case change, consistent with how prior events were transmitted…"}]}
- Brain changed: []
- Full review: False reason=None
- Context miss count: 2
- Anomalies: [{"code": "snapshot_missing_key_evidence", "detail": "Targeted snapshot evidence list is empty while Brain evidence exists."}]
- Latency ms: 207291

Proposals:
- `value_driver` bdrv_4469e497110847e7a3961129f05e5a33 / news: The driver's current_state explicitly states there is 'no evidence in the pack on market share, competitor moves, or design win pipeline' — this confirmed Reuters report is precisely that missing evidence and must be reflected. The event i…
- `value_driver` bdrv_414ad8bb1d8343bea291e8dc5eb44bba / news: The event's possible_affected explicitly includes hyperscaler customer concentration: a hyperscaler exercising an alternative-supplier option is direct evidence for the switching and bargaining-power risk this driver carries, and belongs i…
- `scenario` bscn_avgo_custom_asic_share_erosion / news: Confirmed counter-evidence against a high-importance, high-uncertainty driver warrants a trackable downside scenario rather than a base-case change, consistent with how prior events were transmitted in this Brain (scenario_only, base_case_…

Context misses:
- `driver` bdrv_f789bcf02eb248b7b3ea3552dcbd47f4 AI revenue mix concentration hits=['concentration'] score=0.024
- `evidence` rev_a65ae2866d404168b4b90236ae2f13a6 Q3 FY2026 Exhibit 99.1: AI accelerator and networking demand continues to be very strong; Q4 AI semiconductor revenue g… hits=['accelerator'] score=0.029

### Case F — Earnings / major guidance

- 历史依据: Broadcom 8-K / Exhibit 99.1 dated 2026-09-02: Q3 FY2026 revenue $29.6B; management expects AI semiconductor revenue to accelerate to $21.7B, up 236%.
- Input: `Broadcom reports fiscal Q3 FY2026 earnings and guides Q4 AI semiconductor revenue to $21.7 billion`
- Path: `full_review`
- L0: not reached (full_review short-circuit)
- GLM-5.2 extract: called=False type=None novelty=None material=None
- Extract fact: (none)
- Materiality: True — earnings
- Affected objects: {}
- Snapshot counts: {"states": 0, "drivers": 0, "claims": 0, "exposures": 0, "evidence": 0, "counter_evidence": 0, "history": 0, "causal_edges": 0}
- Snapshot states: []
- Snapshot drivers: []
- Snapshot claims: []
- GLM-5.3 called: False
- Proposal count: 0
- Phase 0 approve/reject/review: {"approve": 0, "reject": 0, "requires_review": 0, "items": []}
- Brain changed: []
- Full review: True reason=earnings
- Context miss count: 0
- Anomalies: []
- Latency ms: 0

## 2. Runtime quantitative metrics

```json
{
  "total_events": 6,
  "l0_duplicate_stop": 1,
  "material": 4,
  "non_material": 2,
  "glm53_calls": 3,
  "glm53_skip_rate": 0.5,
  "avg_targeted_snapshot_size": 28.0,
  "avg_snapshot_object_reduction": 0.4,
  "avg_glm53_tokens": 35197.0,
  "avg_glm53_input_tokens": 10640.33,
  "full_review_input_tokens_avgo_v1": 81207,
  "full_review_total_tokens_avgo_v1": 278739,
  "token_reduction_vs_old_full_review_input": 0.869,
  "avg_latency_ms": 111147.0,
  "avg_affected_object_count": 6.0,
  "avg_affected_object_count_incremental": 12.0,
  "avg_proposal_count": 1.67,
  "approve": 3,
  "reject": 0,
  "requires_review": 7,
  "full_review_triggers": 1,
  "context_miss_count": 5,
  "unexpected_brain_change_count": 0,
  "runtime_anomaly_count": 7
}
```

## 3. Context miss 列表

- Case C: `evidence` rev_a65ae2866d404168b4b90236ae2f13a6 — Q3 FY2026 Exhibit 99.1: AI accelerator and networking demand continues to be very strong; Q4 AI semiconductor revenue g… (['demand', 'accelerator'])
- Case C: `evidence` rev_843a1ee827964a139673007f7c44e957 — Broadcom priced cash tender offers for certain outstanding notes in June 2026. (['broadcom', 'broadcom', 'broadcom', 'broadcom'])
- Case D: `evidence` rev_843a1ee827964a139673007f7c44e957 — Broadcom priced cash tender offers for certain outstanding notes in June 2026. (['broadcom', 'broadcom', 'broadcom'])
- Case E: `driver` bdrv_f789bcf02eb248b7b3ea3552dcbd47f4 — AI revenue mix concentration (['concentration'])
- Case E: `evidence` rev_a65ae2866d404168b4b90236ae2f13a6 — Q3 FY2026 Exhibit 99.1: AI accelerator and networking demand continues to be very strong; Q4 AI semiconductor revenue g… (['accelerator'])

## 4. Runtime anomaly 列表

- Case C: `snapshot_missing_key_evidence` — Targeted snapshot evidence list is empty while Brain evidence exists.
- Case D: `snapshot_missing_key_evidence` — Targeted snapshot evidence list is empty while Brain evidence exists.
- Case E: `snapshot_missing_key_evidence` — Targeted snapshot evidence list is empty while Brain evidence exists.
- Case C: `glm53_received_near_full_brain` — Snapshot included all 5 Core Claims plus unrelated objects (valuation / leverage / GAAP / price reaction).
- Case D: `glm53_received_near_full_brain` — Snapshot included all 5 Core Claims plus unrelated objects (valuation / leverage / GAAP / price reaction).
- Case E: `glm53_received_near_full_brain` — Snapshot included all 5 Core Claims plus unrelated objects (valuation / leverage / GAAP / price reaction).
- Case D: `affected_objects_missed` — Google order-cut rumor did not retrieve ai_semiconductor_demand_durability; it retrieved leverage / GAAP gap / valuation instead.

## 5. 哪些地方符合预期

- Case A 重复新闻在 L0 停止，未调用 GLM-5.3。
- Case B 低价值新闻停在 observation memory，未进入 reasoning。
- Case C 已确认 customer event 进入 incremental 并调用 GLM-5.3。
- Case D rumor 可以 material，但 Current State / Core Claim 未被直接改写。
- Case D 的未确认信息进入 Shadow / Research Question 通道。
- Case D GLM-5.3 没有把 rumor 写成 Current State / Driver / Core Claim；Phase 0 批准的是 Shadow / RQ / market_attention。
- Case E 竞争/反面证据进入 incremental reasoning，没有短路成 Full Review。
- Case F earnings/guidance 触发 Full Review，而不是被当成普通新闻增量改 Brain。
- Incremental 路径声明 snapshot.targeted=True / full_brain=False。
- 三条 material incremental 事件都没有把 Current State / Core Claim 自动写进 Brain。

## 6. 哪些地方和设计存在偏差

- Case C 的 targeted snapshot 包含全部 5 条 Core Claim，GLM-5.3 实际看到了接近完整 Claim 层。
- Case D 的 targeted snapshot 包含全部 5 条 Core Claim，GLM-5.3 实际看到了接近完整 Claim 层。
- Case E 的 targeted snapshot 包含全部 5 条 Core Claim，GLM-5.3 实际看到了接近完整 Claim 层。
- Case D rumor 漏掉了 AI demand durability driver，却命中了杠杆、GAAP gap、估值这类弱相关对象。
- Case C/E 的 Change Proposal 因 Change Budget 全部进入 requires_review，constitution 拒绝规则没有先落地；新闻改 State/Driver/Claim 没有被直接 reject。
- Targeted snapshot 没有带上 Brain evidence 正文（evidence count=0），只带了 oppose link。

## 7. 当前是否已经真正实现 Incremental Brain Runtime

主路径已经接上：默认 incremental，L0 / materiality gate / Full Review trigger / Phase 0 写屏障都在真实 run_brain_update 上工作。 但 targeted snapshot 仍然过宽（5/5 Core Claims），evidence 正文进不了 snapshot，Change Budget 还会把 constitution reject 变成 review。不能认为 Incremental Brain Runtime 已经在信息论意义上完成。

## 8. 发现的问题（本轮不修架构）

- evaluate_brain_changes 在 budget.requires_review 时 continue，constitution_violations 即使命中也不会变成 reject。Confirmed customer 改 Core Claim 因此停在 review，而不是按 Phase 0 规则拒绝。
- run_brain_update._store_context() 把 evidence 固定写成空列表。affected objects 上的 evidence_ids 无法在 snapshot 里解成 Evidence 行。
- 存在 context_miss。其中一部分是 Exhibit 99.1 这类确实相关的 supporting evidence 没进 snapshot；另一部分是 Broadcom 关键词误伤（例如 notes tender）。不要用扩大整个 context 来掩盖。
- locate_affected_objects 把 event blob 里长度>3 的词都当成 needle。AVGO 对象普遍含 Broadcom/AI/revenue/demand，所以一条 customer/rumor/competition 新闻会拖进全部 Core Claims 和若干无关 State/Driver。
- Full Review 在 L0 之前判定。带 earnings/guidance 字样的重复稿不会走 duplicate stop，而会直接 full_review。
- Change Budget max_auto_drivers=1。GLM-5.3 一次提 2 个 driver 就会整批 requires_review，包括本来可以批准的 market-layer 以外对象。
- 本轮没有扩大 snapshot，也没有改 routing / constitution / store。
