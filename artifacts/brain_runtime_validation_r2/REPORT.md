# Phase 0 + Phase 1.1 第二次验证报告

生成时间: 2026-09-18T17:45:17+00:00
范围: 原来的 6 个 AVGO Case。修复 Targeted Context / Constitution-Budget / L0 顺序后的 Before→After。未进入 Phase 2。

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
- Snapshot evidence: []
- Snapshot counter evidence: []
- Context score: recall=None precision=None missed=None irrelevant=None
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
- Snapshot evidence: []
- Snapshot counter evidence: []
- Context score: recall=None precision=None missed=None irrelevant=None
- GLM-5.3 called: False
- Proposal count: 0
- Phase 0 approve/reject/review: {"approve": 0, "reject": 0, "requires_review": 0, "items": []}
- Brain changed: []
- Full review: False reason=None
- Context miss count: 0
- Anomalies: []
- Latency ms: 5623

### Case C — 明确、重要、已确认的 customer / demand event

- 历史依据: Google has been a confirmed Broadcom custom-TPU/ASIC customer for years. This case uses that known relationship as a post-print confirmation of an expanded custom-silicon order, not a rumor.
- Input: `Google confirmed a Broadcom custom-silicon order expansion for next-generation TPU`
- Path: `incremental`
- L0: stop=False reason=pass duplicate=False
- GLM-5.2 extract: called=True type=customer novelty=new material=True
- Extract fact: Google, a named Broadcom customer, confirmed it will expand custom ASIC / TPU orders with Broadcom for the next-generation accelerator deployment. The update is an issuer-linked customer demand event, not a rumor.
- Materiality: True — Material operating or customer information.
- Affected objects: {"states": [], "drivers": ["bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "bdrv_e605ec342c0a4888bec050bd17106982"], "claims": ["bclm_2f3b915b62064c8a98300c530fa331ff", "bclm_f4454cfe04e94211a79b23116bcf5de8"], "exposures": []}
- Snapshot counts: {"states": 0, "drivers": 2, "claims": 2, "exposures": 0, "evidence": 2, "counter_evidence": 1, "history": 2, "causal_edges": 2}
- Snapshot states: []
- Snapshot drivers: ['hyperscaler_customer_concentration', 'ai_semiconductor_demand_durability']
- Snapshot claims: ['The AI ramp implies unquantified dependence on a few hyperscaler buyers', 'AI semiconductor demand durability sets the length of the growth ramp']
- Snapshot evidence: ['rev_a65ae2866d404168b4b90236ae2f13a6', 'rev_d608e3e7661a49dfb06a59bd5c45927b']
- Snapshot counter evidence: ['rev_marvell_hyperscaler_win_in_claim']
- Context score: recall=1.0 precision=1.0 missed=0 irrelevant=0
- GLM-5.3 called: True
- Proposal count: 3
- Phase 0 approve/reject/review: {"approve": 0, "reject": 3, "requires_review": 0, "items": [{"proposal_id": "bcpr_f34bbcf13077411e9e3de2430171cd5a", "object_type": "value_driver", "object_id": "bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "decision": "reject", "reason_code": "driver_slower_than_state", "reason": "Confirmed direct-fact customer news (Reuters, high confidence, issuer-linked, not a rumor) names Google as a hyperscaler customer and confirms an order expansion for next-generation TPU, partially fi…"}, {"proposal_id": "bcpr_5e7a22d8dd534ed1ad10bebb2336831a", "object_type": "value_driver", "object_id": "bdrv_e605ec342c0a4888bec050bd17106982", "decision": "reject", "reason_code": "driver_slower_than_state", "reason": "A confirmed next-generation order expansion from a named hyperscaler is direct customer-side evidence that AI accelerator demand extends into future product generations, adding named-customer confirm…"}, {"proposal_id": "bcpr_b03dab69ec0c4cfb8fed907679f24ee6", "object_type": "core_claim", "object_id": "bclm_2f3b915b62064c8a98300c530fa331ff", "decision": "reject", "reason_code": "news_cannot_modify_core_claim", "reason": "The event is confirmed direct-fact news (not a rumor), so the core claim may be updated. Google's confirmed expansion adds a named hyperscaler customer to the claim's evidence base and directly count…"}]}
- Brain changed: []
- Full review: False reason=None
- Context miss count: 0
- Anomalies: []
- Latency ms: 119586

Proposals:
- `value_driver` bdrv_414ad8bb1d8343bea291e8dc5eb44bba / news: Confirmed direct-fact customer news (Reuters, high confidence, issuer-linked, not a rumor) names Google as a hyperscaler customer and confirms an order expansion for next-generation TPU, partially filling the order-pipeline gap in this dri…
- `value_driver` bdrv_e605ec342c0a4888bec050bd17106982 / news: A confirmed next-generation order expansion from a named hyperscaler is direct customer-side evidence that AI accelerator demand extends into future product generations, adding named-customer confirmation (not management guidance alone) to…
- `core_claim` bclm_2f3b915b62064c8a98300c530fa331ff / news: The event is confirmed direct-fact news (not a rumor), so the core claim may be updated. Google's confirmed expansion adds a named hyperscaler customer to the claim's evidence base and directly counters the Marvell competitive-displacement…

Phase 0 rejects:
- `value_driver` reason_code=driver_slower_than_state rules=[{'rule': 'driver_slower_than_state', 'reason': 'Value Driver must change slower than State.'}]
- `value_driver` reason_code=driver_slower_than_state rules=[{'rule': 'driver_slower_than_state', 'reason': 'Value Driver must change slower than State.'}]
- `core_claim` reason_code=news_cannot_modify_core_claim rules=[{'rule': 'news_cannot_modify_core_claim', 'reason': 'News or Event cannot directly modify a Core Claim.'}]

### Case D — 重要但未经确认的 rumor

- 历史依据: Markets have repeatedly priced unconfirmed Google in-house silicon / TPU order-cut rumors against Broadcom. The rumor is decision-relevant if true, but unconfirmed.
- Input: `Unconfirmed: Google may reduce Broadcom custom TPU orders`
- Path: `incremental`
- L0: stop=False reason=pass duplicate=False
- GLM-5.2 extract: called=True type=customer novelty=new material=True
- Extract fact: Rumor that Google may reduce Broadcom ASIC / TPU orders as it expands in-house silicon. The report is unconfirmed and uses anonymous sources.
- Materiality: True — Unconfirmed but potentially material; GLM-5.3 may only propose Shadow State / Research Questions.
- Affected objects: {"states": [], "drivers": ["bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "bdrv_e605ec342c0a4888bec050bd17106982"], "claims": ["bclm_2f3b915b62064c8a98300c530fa331ff", "bclm_f4454cfe04e94211a79b23116bcf5de8"], "exposures": []}
- Snapshot counts: {"states": 0, "drivers": 2, "claims": 2, "exposures": 0, "evidence": 2, "counter_evidence": 1, "history": 2, "causal_edges": 2}
- Snapshot states: []
- Snapshot drivers: ['hyperscaler_customer_concentration', 'ai_semiconductor_demand_durability']
- Snapshot claims: ['The AI ramp implies unquantified dependence on a few hyperscaler buyers', 'AI semiconductor demand durability sets the length of the growth ramp']
- Snapshot evidence: ['rev_a65ae2866d404168b4b90236ae2f13a6', 'rev_d608e3e7661a49dfb06a59bd5c45927b']
- Snapshot counter evidence: ['rev_marvell_hyperscaler_win_in_claim']
- Context score: recall=1.0 precision=1.0 missed=0 irrelevant=0
- GLM-5.3 called: True
- Proposal count: 3
- Phase 0 approve/reject/review: {"approve": 3, "reject": 0, "requires_review": 0, "items": [{"proposal_id": "bcpr_499244ae29b5454f868a74220e889c47", "object_type": "shadow_state", "object_id": "bssh_avgo_google_tpu_order_reduction", "decision": "approve", "reason_code": "", "reason": "The event is an unconfirmed rumor (confidence: low, fact_reliability: rumor, source_tier: 3, anonymous sources). Rules prohibit rumor-driven changes to Current State, Value Drivers, or Core Claims, s…"}, {"proposal_id": "bcpr_a99ae1760fe445e28c9a13ecb6161bc7", "object_type": "research_question", "object_id": "brq_avgo_google_custom_silicon_exposure", "decision": "approve", "reason_code": "", "reason": "A rumor requires verification and quantification before any state or claim change; the Brain currently lacks customer-level revenue data for Google, so this question gates whether the shadow state is…"}, {"proposal_id": "bcpr_114513616abd41b0875fef43fdd544da", "object_type": "market_attention", "object_id": "batt_avgo_google_tpu_rumor_202609", "decision": "approve", "reason_code": "", "reason": "Counter-evidence already in the Brain shows unconfirmed/secondary hyperscaler-silicon news moved AVGO 3.9% (Marvell award). Tracking this rumor's market traction helps interpret price action without…"}]}
- Brain changed: ['shadow_state:bssh_avgo_google_tpu_order_reduction', 'research_question:brq_avgo_google_custom_silicon_exposure', 'market_attention:batt_avgo_google_tpu_rumor_202609', 'shadow:bshd_47ec3e778158481dae2316d5a553e077', 'question:brq_52ae573894bf4998ae63baf5be824b6d']
- Full review: False reason=None
- Context miss count: 0
- Anomalies: []
- Latency ms: 103672

Proposals:
- `shadow_state` bssh_avgo_google_tpu_order_reduction / rumor: The event is an unconfirmed rumor (confidence: low, fact_reliability: rumor, source_tier: 3, anonymous sources). Rules prohibit rumor-driven changes to Current State, Value Drivers, or Core Claims, so the potential state is captured as a s…
- `research_question` brq_avgo_google_custom_silicon_exposure / rumor: A rumor requires verification and quantification before any state or claim change; the Brain currently lacks customer-level revenue data for Google, so this question gates whether the shadow state is promoted, revised, or discarded.
- `market_attention` batt_avgo_google_tpu_rumor_202609 / rumor: Counter-evidence already in the Brain shows unconfirmed/secondary hyperscaler-silicon news moved AVGO 3.9% (Marvell award). Tracking this rumor's market traction helps interpret price action without asserting the rumor as fact.

### Case E — 与已有 Core Claim 明显相关的新反面证据

- 历史依据: The seeded AVGO Brain already records that a hyperscaler awarding custom AI chip work to Marvell moved AVGO 3.9%. This case is a follow-on confirmed competitive loss.
- Input: `Marvell wins a hyperscaler custom ASIC program Broadcom had been expected to supply`
- Path: `incremental`
- L0: stop=False reason=pass duplicate=False
- GLM-5.2 extract: called=True type=competition novelty=new material=True
- Extract fact: Marvell Technology announced a hyperscaler custom ASIC design win that had been expected to go to Broadcom, adding counter evidence against Broadcom's AI accelerator competitive position and customer concentration.
- Materiality: True — Material operating or customer information.
- Affected objects: {"states": [], "drivers": ["bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "bdrv_4469e497110847e7a3961129f05e5a33"], "claims": ["bclm_f4454cfe04e94211a79b23116bcf5de8", "bclm_2f3b915b62064c8a98300c530fa331ff"], "exposures": []}
- Snapshot counts: {"states": 0, "drivers": 2, "claims": 2, "exposures": 0, "evidence": 1, "counter_evidence": 1, "history": 2, "causal_edges": 2}
- Snapshot states: []
- Snapshot drivers: ['hyperscaler_customer_concentration', 'ai_silicon_competitive_position']
- Snapshot claims: ['AI semiconductor demand durability sets the length of the growth ramp', 'The AI ramp implies unquantified dependence on a few hyperscaler buyers']
- Snapshot evidence: ['rev_a65ae2866d404168b4b90236ae2f13a6']
- Snapshot counter evidence: ['rev_marvell_hyperscaler_win_in_claim']
- Context score: recall=1.0 precision=1.0 missed=0 irrelevant=0
- GLM-5.3 called: True
- Proposal count: 4
- Phase 0 approve/reject/review: {"approve": 2, "reject": 2, "requires_review": 0, "items": [{"proposal_id": "bcpr_38c9218a06484ca196aff80e856c5010", "object_type": "core_claim", "object_id": "bclm_2f3b915b62064c8a98300c530fa331ff", "decision": "approve", "reason_code": "", "reason": "The claim already cites a Marvell hyperscaler award as counter-evidence, but only via a derived claim-statement source; the underlying event is now confirmed by Reuters (direct fact, 2026-09-12) with…"}, {"proposal_id": "bcpr_0039643ba7ed4d90bc167e8a5ea4b509", "object_type": "research_question", "object_id": "", "decision": "approve", "reason_code": "", "reason": "Whether this loss is financially material or the leading edge of share erosion depends on program size and recurrence, neither of which is disclosed in the event; the answer determines how much weigh…"}, {"proposal_id": "bcpr_e2827814143c4eadb3c3529597703fba", "object_type": "value_driver", "object_id": "bdrv_4469e497110847e7a3961129f05e5a33", "decision": "reject", "reason_code": "driver_slower_than_state", "reason": "The driver's current_state explicitly noted no evidence on competitor moves or design win pipeline; this confirmed Reuters report (direct fact, high confidence) supplies the first such data point — a…"}, {"proposal_id": "bcpr_67a0f3d317354c529e22dfe0493a62e6", "object_type": "value_driver", "object_id": "bdrv_414ad8bb1d8343bea291e8dc5eb44bba", "decision": "reject", "reason_code": "driver_slower_than_state", "reason": "The event is a confirmed instance of a hyperscaler exercising an alternative-supplier option on a program Broadcom expected to win, converting this driver's risk from hypothetical to observed; concen…"}]}
- Brain changed: ['core_claim:bclm_2f3b915b62064c8a98300c530fa331ff', 'research_question:research_question']
- Full review: False reason=None
- Context miss count: 0
- Anomalies: []
- Latency ms: 175607

Proposals:
- `value_driver` bdrv_4469e497110847e7a3961129f05e5a33 / news: The driver's current_state explicitly noted no evidence on competitor moves or design win pipeline; this confirmed Reuters report (direct fact, high confidence) supplies the first such data point — an expected hyperscaler ASIC program lost…
- `value_driver` bdrv_414ad8bb1d8343bea291e8dc5eb44bba / news: The event is a confirmed instance of a hyperscaler exercising an alternative-supplier option on a program Broadcom expected to win, converting this driver's risk from hypothetical to observed; concentration ratios remain unquantified, so n…
- `core_claim` bclm_2f3b915b62064c8a98300c530fa331ff / news: The claim already cites a Marvell hyperscaler award as counter-evidence, but only via a derived claim-statement source; the underlying event is now confirmed by Reuters (direct fact, 2026-09-12) with the added detail that the program was e…
- `research_question`  / news: Whether this loss is financially material or the leading edge of share erosion depends on program size and recurrence, neither of which is disclosed in the event; the answer determines how much weight the negative tilt on the competitive-p…

Phase 0 rejects:
- `value_driver` reason_code=driver_slower_than_state rules=[{'rule': 'driver_slower_than_state', 'reason': 'Value Driver must change slower than State.'}]
- `value_driver` reason_code=driver_slower_than_state rules=[{'rule': 'driver_slower_than_state', 'reason': 'Value Driver must change slower than State.'}]

### Case F — Earnings / major guidance

- 历史依据: Broadcom 8-K / Exhibit 99.1 dated 2026-09-02: Q3 FY2026 revenue $29.6B; management expects AI semiconductor revenue to accelerate to $21.7B, up 236%.
- Input: `Broadcom reports fiscal Q3 FY2026 earnings and guides Q4 AI semiconductor revenue to $21.7 billion`
- Path: `full_review`
- L0: L0 ran first: stop=False duplicate=False; then full_review reason=earnings
- GLM-5.2 extract: called=False type=None novelty=None material=None
- Extract fact: (none)
- Materiality: True — earnings
- Affected objects: {}
- Snapshot counts: {"states": 0, "drivers": 0, "claims": 0, "exposures": 0, "evidence": 0, "counter_evidence": 0, "history": 0, "causal_edges": 0}
- Snapshot states: []
- Snapshot drivers: []
- Snapshot claims: []
- Snapshot evidence: []
- Snapshot counter evidence: []
- Context score: recall=None precision=None missed=None irrelevant=None
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
  "avg_targeted_snapshot_size": 10.67,
  "avg_snapshot_object_count": 10.67,
  "avg_snapshot_object_reduction": 0.79,
  "avg_glm53_tokens": 20128.33,
  "avg_glm53_input_tokens": 4504.0,
  "full_review_input_tokens_avgo_v1": 81207,
  "full_review_total_tokens_avgo_v1": 278739,
  "token_reduction_vs_old_full_review_input": 0.9445,
  "avg_latency_ms": 67414.67,
  "avg_affected_object_count": 2.0,
  "avg_affected_object_count_incremental": 4.0,
  "avg_proposal_count": 1.67,
  "approve": 5,
  "reject": 5,
  "requires_review": 0,
  "full_review_triggers": 1,
  "context_miss_count": 0,
  "unexpected_brain_change_count": 0,
  "avg_core_claim_retrieval_count": 2.0,
  "avg_relevant_object_recall": 1.0,
  "avg_context_precision": 1.0,
  "avg_irrelevant_object_count": 0.0,
  "avg_evidence_body_retrieval_count": 2.67,
  "support_evidence_miss_cases": 0,
  "counter_evidence_miss_cases": 0,
  "runtime_anomaly_count": 0
}
```

## 3. Context miss 列表

无 context_miss。

## 4. Runtime anomaly 列表

无 Runtime Anomaly。

## 5. 哪些地方符合预期

- Case A 重复新闻在 L0 停止，未调用 GLM-5.3。
- Case B 低价值新闻停在 observation memory，未进入 reasoning。
- Case C 已确认 customer event 进入 incremental 并调用 GLM-5.3。
- Case D rumor 可以 material，但 Current State / Core Claim 未被直接改写。
- Case D 的未确认信息进入 Shadow / Research Question 通道。
- Case E 竞争/反面证据进入 incremental reasoning，没有短路成 Full Review。
- Case F 首次 earnings/guidance 在 L0 通过后触发 Full Review。
- Incremental 路径声明 snapshot.targeted=True / full_brain=False。
- Case C 的 Exhibit 99.1 supporting evidence 进入了 snapshot。
- Case C 不再默认塞入全部 5 条 Core Claim。
- Case D 命中了 AI demand durability 相关对象。
- Case D Current State / Core Claim 保持不变。
- Case E 同时拿到相关 support evidence 正文和 Marvell counter evidence。
- Case C 对 Event→Core Claim 给出 constitution reject，而不是被 Change Budget 盖成 review。

## 6. 哪些地方和设计存在偏差

无新增设计偏差。

## 7. 当前是否已经真正实现 Incremental Brain Runtime

Routing 仍然正确，Targeted Context 已经按结构关系变窄，关键 Evidence 正文进入 snapshot，Constitution reject 不再被 Change Budget 覆盖。可以认为 Incremental Runtime 在信息论意义上成立，停止 Phase 1。

## 8. Before → After（第一次 baseline vs 本轮）

```json
{
  "avg_targeted_snapshot_size": {
    "before": 28.0,
    "after": 10.67
  },
  "avg_snapshot_object_count": {
    "before": null,
    "after": 10.67
  },
  "avg_glm53_input_tokens": {
    "before": 10640.33,
    "after": 4504.0
  },
  "context_miss_count": {
    "before": 5,
    "after": 0
  },
  "approve": {
    "before": 3,
    "after": 5
  },
  "reject": {
    "before": 0,
    "after": 5
  },
  "requires_review": {
    "before": 7,
    "after": 0
  },
  "avg_core_claim_retrieval_count": {
    "before": null,
    "after": 2.0
  },
  "avg_irrelevant_object_count": {
    "before": null,
    "after": 0.0
  },
  "avg_evidence_body_retrieval_count": {
    "before": null,
    "after": 2.67
  },
  "avg_relevant_object_recall": {
    "before": null,
    "after": 1.0
  },
  "avg_context_precision": {
    "before": null,
    "after": 1.0
  },
  "support_evidence_miss_cases": {
    "before": null,
    "after": 0
  },
  "counter_evidence_miss_cases": {
    "before": null,
    "after": 0
  },
  "unexpected_brain_change_count": {
    "before": 0,
    "after": 0
  },
  "glm53_calls": {
    "before": 3,
    "after": 3
  },
  "l0_duplicate_stop": {
    "before": 1,
    "after": 1
  },
  "full_review_triggers": {
    "before": 1,
    "after": 1
  }
}
```

- 1. Routing 是否仍然正确？ L0 stop 1→1; full review 1→1; GLM-5.3 calls 3→3.
- 2. Targeted Context 是否真正变窄？ snapshot 28.0→10.67; Core Claim retrieval/event 2.0.
- 3. 关键 Evidence 是否已经进入？ evidence bodies 2.67; support miss cases 0; counter miss cases 0.
- 4. 重要 Context 是否还有遗漏？ context_miss 5→0; recall 1.0.
- 5. 无关对象是否明显减少？ irrelevant 0.0; precision 1.0.
- 6. Constitution / Budget decision 是否恢复正确语义？ approve/reject/review 3/0/7 → 5/5/0.
- 7. Incremental Runtime 是否已经可以认为真正成立？ unexpected writes 0→0.

## 9. 发现的问题（本轮不修架构）

- context_miss 改为对照 golden expected objects，不再用 Broadcom/AI 宽关键词自我验证 retrieval。
- Change Budget 先看 Constitution reject，再对剩余合法 proposal 判断 related vs unrelated scope。
- Full Review 只在 L0 判定非 duplicate 之后触发。
- 本轮没有进入 Phase 2，没有建立完整 Causal Graph，也没有退回 Full Brain Context。
