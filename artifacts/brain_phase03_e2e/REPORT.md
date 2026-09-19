# Stock-PM Brain v2 — Phase 0–3 连续功能验证

Generated: 2026-09-19T02:53:05+00:00
Ticker: `AVGO`
Window: 2026-06-03T20:05:00+00:00 → 2026-09-16T19:30:00+00:00
Seed: golden `brun_b1c268aae8b345559ac2dc93176a70ab` once; events replayed in time order on the same Brain.

## LLM ping

{
  "mechanical": {
    "ok": true,
    "status": "ok",
    "model": "glm-5.2",
    "base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "llm_called": true,
    "error": null,
    "input_tokens": 43,
    "output_tokens": 111,
    "latency_ms": 2958,
    "elapsed_s": 2.958462
  },
  "reasoning": {
    "ok": true,
    "status": "ok",
    "model": "glm-5.3",
    "base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "llm_called": true,
    "error": null,
    "input_tokens": 42,
    "output_tokens": 155,
    "latency_ms": 3256,
    "elapsed_s": 3.256362
  }
}

## Metrics

- 总 Event 数: 18
- duplicate stop: 3
- non-material stop: 4
- material incremental: 5
- Full Review 次数: 2
- GLM-5.3 调用率: 1.0
- 平均 snapshot objects: 3.78
- 平均 GLM-5.3 tokens: 24733.6
- context miss (events with miss): 3
- unexpected Brain write: 0

- State changes: 0
- Value Driver changes: 0
- Core Claim changes: 0
- Causal Edge changes: 0
- Expectation changes: 4
- Market Attention changes: 2

- Hypothesis created: 6
- Hypothesis updated: 4
- Hypothesis strengthened: 3
- Hypothesis weakened: 0
- Hypothesis closed: 0
- Average competing hypotheses: 4.56

- Successful transmission: 0
- Blocked transmission: 0
- Causal gaps: 6
- Research Questions: 27

- Price → Fundamental violation: 0
- Price → Core Claim violation: 0
- Unsupported Event → Claim jump: 0

- single-hypothesis events: 1
- multi-hypothesis events: 0
- unresolved events: 4

## Quality scores

- Brain Stability (slow writes / ordinary event): 1.0
- Memory Continuity (material events that retrieved leftover objects): 0.8
- Hypothesis Continuity (updates / (updates+new keys)): 0.25
- Context Recall (avg): 0.4
- Context Precision (avg): 0.6667

## Exposed problems (not fixed this round)

1. **Constitution crash on malformed `causal_edges`.** Four material events (`e09` Q3 print-vs-expect, `e13` six XPU / 58 vs 56, `e14` Google confirm, `e16` Marvell win) died in `edge_can_transmit` because GLM-5.3 put strings into `causal_edges`. Incremental writes and Now Chain were lost. This is a runtime robustness hole, not a fixture issue.
2. **Full Review is a stub.** Q2 and Q3 official releases (`e01`, `e08`) correctly route to Full Review, then return without Now Chain, without GLM-5.3, and without updating the Brain.
3. **Causal graph cannot carry a live event.** Seeded edges are mostly Driver→Claim. `successful_transmission = 0`, `blocked_transmission = 0`, `causal_gaps = 6`. The graph stopped Claim jumps (unsupported jump = 0) but almost never produced “through what path”.
4. **Expectation object vs Now Chain display.** `e02` did persist `Q3 AI semiconductor revenue` as below/falling (16 vs 17.2) and left Claim/State unchanged. Now Chain later preferred another row named `expectation` with `expected = None`, `in_line`.
5. **Hypothesis continuity is weak (0.25).** New keys are still created (`other`, `unresolved`) instead of only updating named drivers. No hypothesis was weakened or closed. The later Google *confirm* never landed, so the rumor could not be challenged by confirmation.
6. **A large unexplained tape was dropped.** `e18` AVGO −6.2% with no filing went `observation_memory` / non-material, so unresolved + RQ did not fire on the event that most needed it.
7. **Exposure text is generic.** Several Now Chains say “Issuer-linked exposure” because golden exposures lack `object_name` / mechanism.

These are left in the artifacts. No architecture or prompt change was made.

## Cognitive Drift

- none recorded (Claim/Driver/State/Edge statuses did not oscillate; the bigger failure mode was crash-and-drop, not flip-flop)

## Runtime anomalies

- e01_q2_filing: Full Review path produced no Now Chain and did not run incremental reasoning.
- e08_q3_filing: Full Review path produced no Now Chain and did not run incremental reasoning.
- e09_q3_print_vs_expect: exception 'str' object has no attribute 'get'
- e13_xpu_customers: exception 'str' object has no attribute 'get'
- e14_google_confirm: exception 'str' object has no attribute 'get'
- e16_marvell_win: exception 'str' object has no attribute 'get'

## Research Questions (graded)

- [useful] Missing relationship: the event's most direct financial effect is on AI semiconductor revenue (~$1.2B below street for Q3) and total revenue guidance, but the targeted snapshot contains no value_driver for AI semiconduc… — Names a concrete entity, metric, or gap that can be checked.
- [useful] How exposed is the issuer to AVGO AI semiconductor next-quarter figure 16 billion versus street 17.2 billion, such that it would move Whether the guided 66% non-GAAP operating margin is structural or peak-cycle? — Names a concrete entity, metric, or gap that can be checked.
- [useful] Did Q3 FY2026 actual AI semiconductor revenue meet, beat, or miss the $16B guide (and the $17.2B street figure)? — Names a concrete entity, metric, or gap that can be checked.
- [useful] Does the Q2 adjusted EPS beat ($2.44 vs $2.40 street) contradict driver bdrv_8dd8af15e6a84090b239eb0c00f6917f's assertion that reported EPS came in below estimates in each of the last three quarters, or does that assert… — Names a concrete entity, metric, or gap that can be checked.
- [mixed] Was the -12.59% one-day post-earnings reaction driven primarily by the AI guide miss, or did concurrent factors (positioning, sector AI de-rating, valuation) contribute materially? — Possibly useful, but not tightly bound to a named gap.
- [mixed] What is the market pricing that the current Brain does not explain? — Possibly useful, but not tightly bound to a named gap.
- [useful] How exposed is the issuer to AVGO shares move -12.6% with semiconductor peers, such that it would move The AI ramp implies unquantified dependence on a few hyperscaler buyers? — Names a concrete entity, metric, or gap that can be checked.
- [mixed] How much of AVGO's -12.59% decline on 2026-06-04 is sector beta (SOX -10.26%) versus company-specific? The ~2.3pp excess decline versus SOX is currently unexplained; Market Driver = unresolved until the move is decompos… — Possibly useful, but not tightly bound to a named gap.
- [useful] Did any fundamental news (e.g., hyperscaler capex changes, AI demand data, competitive awards) accompany or trigger the sector-wide selloff, or is it sentiment/positioning? If fundamental, it would enter the Brain throu… — Names a concrete entity, metric, or gap that can be checked.
- [useful] Can we confirm: Google custom silicon volume? — Names a concrete entity, metric, or gap that can be checked.
- [useful] The rumor's impact cannot be sized and the existing causal gaps from e07_google_rumor to both core claims cannot be closed without two facts: (1) what fraction of Broadcom's AI semiconductor / custom silicon revenue and… — Names a concrete entity, metric, or gap that can be checked.
- [useful] How exposed is the issuer to Unconfirmed rumor that Google may delay custom silicon volume, such that it would move The AI ramp implies unquantified dependence on a few hyperscaler buyers? — Names a concrete entity, metric, or gap that can be checked.
- [useful] How exposed is the issuer to Unconfirmed rumor that Google may delay custom silicon volume, such that it would move AI semiconductor demand durability sets the length of the growth ramp? — Names a concrete entity, metric, or gap that can be checked.
- [useful] What share of Broadcom's AI semiconductor and custom silicon revenue and pipeline is attributable to Google, and is there any confirming or refuting evidence (Google capex or TPU roadmap commentary, supply-chain order d… — Names a concrete entity, metric, or gap that can be checked.
- [useful] Does the guided Q4 FY2026 AI semiconductor revenue of $21.7B (+236%) and the reported plan to double AI semiconductor revenue in each of the next two years depend on Google TPU volume, or is the ramp driven by other nam… — Names a concrete entity, metric, or gap that can be checked.
- [useful] If AVGO sells off around this rumor, is the tape trading the Google delay, the below-expectation AI semiconductor guide (16.0 vs 17.2), or a sector-wide move — and what evidence would distinguish them? — Names a concrete entity, metric, or gap that can be checked.
- [useful] What happened: the tape points to company-specific content, and the only fundamental content visible in this snapshot is the below-consensus AI semiconductor revenue guide. Why it matters: for that content to affect val… — Names a concrete entity, metric, or gap that can be checked.
- [useful] What is the AVGO tape trading in this post-print session — the below-consensus AI semiconductor revenue guide (16.0 vs 17.2), the unconfirmed Google custom-silicon delay rumor, or another company-specific factor? — Names a concrete entity, metric, or gap that can be checked.
- [useful] Does the Q3 print or management commentary confirm or refute the unconfirmed rumor that Google may delay custom silicon volume? — Names a concrete entity, metric, or gap that can be checked.
- [useful] What value driver and financial metric does AVGO's AI semiconductor revenue guidance feed, and does the below-consensus guide change the Base Case through that path? — Names a concrete entity, metric, or gap that can be checked.
- [mixed] Can we confirm: AVGO shares move -2.74% after the latest print? — Possibly useful, but not tightly bound to a named gap.
- [useful] Can we confirm: Unconfirmed: Google may reduce Broadcom custom TPU orders? — Names a concrete entity, metric, or gap that can be checked.
- [useful] How exposed is the issuer to Unconfirmed: Google may reduce Broadcom custom TPU orders, such that it would move The AI ramp implies unquantified dependence on a few hyperscaler buyers? — Names a concrete entity, metric, or gap that can be checked.
- [useful] How exposed is the issuer to Unconfirmed: Google may reduce Broadcom custom TPU orders, such that it would move AI semiconductor demand durability sets the length of the growth ramp? — Names a concrete entity, metric, or gap that can be checked.
- [useful] What fraction of Broadcom's AI semiconductor revenue (Q4 FY2026 guided $21.7B, +236% YoY) is attributable to Google custom TPU programs, and what volumes/prices are contractually committed vs discretionary? — Names a concrete entity, metric, or gap that can be checked.
- [useful] Is there any primary-source confirmation — from Google, Broadcom, supply-chain checks, or a tier-1/2 outlet — that Google TPU order volumes with Broadcom are being reduced or delayed, and is this report independent of t… — Names a concrete entity, metric, or gap that can be checked.
- [mixed] What was AVGO's price reaction around the rumor's publication window (2026-09-11/12), with MRVL and SOX as controls? — Possibly useful, but not tightly bound to a named gap.

## Review questions

### 1. Brain 是否对噪声稳定？

普通/噪声事件 6 条中，慢变量变化 0 次，稳定分 1.0。普通新闻没有大规模改写 Claim/Driver。

### 2. Brain 是否对真正重要的信息敏感？

material incremental 5，Full Review 2。Expectation 变化 4，Hypothesis 创建/更新 6/4。重要 customer/demand/print 进入了 incremental 或 Full Review。

### 3. Slow Brain 是否真的比 Fast Brain 更稳定？

慢层变化合计 0（State 0 / Driver 0 / Claim 0 / Edge 0）。快层变化合计 16（Expectation 4 / Attention 2 / Hypothesis +6/~4）。快层更敏感、慢层更稳。

### 4. 新 Event 是否在利用历史，而不是重新研究？

Memory Continuity 0.8。4/5 个 material incremental 事件的 snapshot 含有 seed 阶段已有对象。

### 5. Causal Graph 是否真实约束了推理？

successful 0 / blocked 0 / gaps 6 / unsupported jump 0。Golden graph 主要是 Driver→Claim。若 blocked/gap 多而 successful 少，说明连续环境里 Causal Brain 更多是在停写，而不是送完整路径。

### 6. Expectation 和 Fundamental 是否真的分开？

Print-vs-expect 事件: [{'event_id': 'e02_q2_print_vs_expect', 'expectation': {'actual': 16.0, 'expected': None, 'comparison': 'in_line', 'trend': 'unchanged', 'confidence': 'medium', 'last_material_change': ''}, 'core_claims_unchanged': True, 'current_state_unchanged': True}, {'event_id': 'e09_q3_print_vs_expect', 'expectation': None, 'core_claims_unchanged': None, 'current_state_unchanged': None}]. 期末 Core Claim status 相对 seed 未变。Q2 AI 16 vs 17.2 与 Q3 EPS 2.68 vs 2.83 是 Fundamental 仍可偏正、Expectation 下降的真实样本。

### 7. Market Driver Hypothesis 是否真正会竞争和演化？

created 6, updated 4, strengthened 3, weakened 0, closed 0, avg competing 4.56, continuity 0.25。若 updated 远小于 created，说明 Market Memory 仍在重复建假设。

### 8. Brain 是否能够承认“目前无法解释”？

unresolved events 4。存在 unresolved + Research Question，这是正确结果而不是失败。

### 9. Research Question 是否真的来自认知缺口？

共 27 条。useful 22 / mixed 5 / weak 0。弱问题是泛问；有用问题应点名客户、路径或 expectation gap。

### 10. Now Chain 是否已经能够帮助投资者理解发生了什么、为什么重要、怎么影响投资逻辑、市场可能在交易什么？

12/18 条事件产出了 Now Chain。 Full Review 路径不产 Now Chain 是当前 runtime 行为，已记入 anomaly。 multi=0 single=1 unresolved=4。


## Timeline (compact)

### e01_q2_filing — 2026-06-03T20:05:00+00:00 — `full_review`

- title: Broadcom reports fiscal Q2 FY2026 earnings and quarterly dividend
- material: True | glm53: False | stopped: False
- Now Chain: not produced (see anomalies)

### e02_q2_print_vs_expect — 2026-06-03T21:10:00+00:00 — `incremental`

- title: AVGO AI semiconductor next-quarter figure 16 billion versus street 17.2 billion
- material: True | glm53: True | stopped: False
- 发生了什么: AVGO AI semiconductor next-quarter figure 16 billion versus street 17.2 billion
- 为什么影响公司: Issuer-linked exposure; Issuer-linked exposure; Issuer-linked exposure
- causal path: No complete causal path. Research first: How exposed is the issuer to AVGO AI semiconductor next-quarter figure 16 billion versus street 17.2 billion, such that it would move Whether the guided 66% no…
- 市场怎么理解: Attention: How the market currently understands the print: Q2 revenue and EPS were roughly in line, yet shares fell 12.59% the day after on 3.5x the 20-day average volume… Expectation: actual 16.0 vs expected None (in_line, unchanged) Candidate drivers: 1. other. Price alignment: unexplained Confidence: medium

### e03_q2_sector_tape — 2026-06-04T20:00:00+00:00 — `incremental`

- title: AVGO shares move -12.6% with semiconductor peers
- material: True | glm53: True | stopped: False
- 发生了什么: AVGO shares move -12.6% with semiconductor peers
- 为什么影响公司: Issuer-linked exposure; Issuer-linked exposure; Issuer-linked exposure
- causal path: No complete causal path. Research first: How exposed is the issuer to AVGO shares move -12.6% with semiconductor peers, such that it would move The AI ramp implies unquantified dependence on a few hyp…
- 市场怎么理解: Attention: What happened: on 2026-06-04 AVGO fell -12.59% in the session after its Q2 print, with NVDA -8.0%, AMD -7.0%, and SOX -10.26% — a broad semiconductor selloff i… Expectation: actual 16.0 vs expected None (in_line, unchanged) Candidate drivers: 1. other; 2. Sector / macro move; 3. Market driver is unresolved. Which driver dominates is not established. Price alignment: unexplained Confide…

### e04_noise_druckenmiller — 2026-06-15T14:00:00+00:00 — `l0_stop`

- title: Billionaire Stanley Druckenmiller Dumped Broadcom and 11X'd His Fund's Stake in This Trillion-Dollar Dual-Industry Leader
- material: False | glm53: False | stopped: True
- 发生了什么: Billionaire Stanley Druckenmiller Dumped Broadcom and 11X'd His Fund's Stake in This Trillion-Dollar Dual-Industry Leader (duplicate)
- 为什么影响公司: No company exposure is linked yet.
- causal path: No targeted causal path is available for this event.
- 市场怎么理解: Price alignment: unknown Confidence: low

### e05_tender_notes — 2026-06-20T16:00:00+00:00 — `observation_memory`

- title: Broadcom priced cash tender offers for certain outstanding notes
- material: False | glm53: False | stopped: True
- 发生了什么: Broadcom priced cash tender offers for certain outstanding notes (non_material)
- 为什么影响公司: No company exposure is linked yet.
- causal path: No targeted causal path is available for this event.
- 市场怎么理解: Price alignment: unknown Confidence: low

### e06_noise_arista — 2026-07-20T13:30:00+00:00 — `l0_stop`

- title: Arista Networks highlighted as Zacks Bull and Yum! Brands Bear of the Day
- material: False | glm53: False | stopped: True
- 发生了什么: Arista Networks highlighted as Zacks Bull and Yum! Brands Bear of the Day (duplicate)
- 为什么影响公司: No company exposure is linked yet.
- causal path: No targeted causal path is available for this event.
- 市场怎么理解: Price alignment: unknown Confidence: low

### e07_google_rumor — 2026-08-12T18:00:00+00:00 — `incremental`

- title: Unconfirmed rumor that Google may delay custom silicon volume
- material: True | glm53: True | stopped: False
- 发生了什么: Unconfirmed rumor that Google may delay custom silicon volume
- 为什么影响公司: No company exposure is linked yet.
- causal path: No complete causal path. Research first: How exposed is the issuer to Unconfirmed rumor that Google may delay custom silicon volume, such that it would move The AI ramp implies unquantified dependence…
- 市场怎么理解: Attention: What happened: the Google TPU delay rumor is a hyperscaler custom-silicon allocation headline directly relevant to AVGO. Why it matters: the market demonstrabl… Expectation: actual 16.0 vs expected None (in_line, unchanged) Candidate drivers: 1. other; 2. Sector / macro move; 3. Market driver is unresolved; 4. Customer concentration concern is increasing. Which driver dominates is not…

### e08_q3_filing — 2026-09-02T20:05:00+00:00 — `full_review`

- title: Broadcom reports fiscal Q3 FY2026 earnings and guides Q4 AI semiconductor revenue to 21.7 billion
- material: True | glm53: False | stopped: False
- Now Chain: not produced (see anomalies)

### e09_q3_print_vs_expect — 2026-09-02T21:20:00+00:00 — `error`

- title: AVGO AI semiconductor printed 16.7 billion; EPS 2.68 versus 2.83 expected
- material: None | glm53: None | stopped: True
- Now Chain: not produced (see anomalies)

### e10_q3_company_tape — 2026-09-03T20:00:00+00:00 — `incremental`

- title: AVGO shares move -2.74% after the latest print
- material: True | glm53: True | stopped: False
- 发生了什么: AVGO shares move -2.74% after the latest print
- 为什么影响公司: Issuer-linked exposure; Issuer-linked exposure; Issuer-linked exposure
- causal path: No targeted causal path is available for this event.
- 市场怎么理解: Attention: avgo_q3_ai_guide_attention Expectation: actual 16.0 vs expected None (in_line, unchanged) Candidate drivers: 1. other; 2. Sector / macro move; 3. Market driver is unresolved; 4. Customer concentration concern is increasing. Which driver dominates is not established. Price alignment: unexplained Confidence: low Unresolved: the tape move does not yet have a supported market driver.

### e11_duplicate_demand — 2026-09-03T21:10:00+00:00 — `observation_memory`

- title: Broadcom says demand for AI accelerators and networking continues to be very strong
- material: False | glm53: False | stopped: True
- 发生了什么: Broadcom says demand for AI accelerators and networking continues to be very strong (non_material)
- 为什么影响公司: No company exposure is linked yet.
- causal path: No targeted causal path is available for this event.
- 市场怎么理解: Price alignment: unknown Confidence: low

### e12_conference_noise — 2026-09-08T14:00:00+00:00 — `observation_memory`

- title: Broadcom CEO Hock Tan scheduled for Goldman Sachs conference appearance
- material: False | glm53: False | stopped: True
- 发生了什么: Broadcom CEO Hock Tan scheduled for Goldman Sachs conference appearance (non_material)
- 为什么影响公司: No company exposure is linked yet.
- causal path: No targeted causal path is available for this event.
- 市场怎么理解: Price alignment: unknown Confidence: low

### e13_xpu_customers — 2026-09-09T17:00:00+00:00 — `error`

- title: Hock Tan said Broadcom has six XPU customers and fiscal 2026 AI revenue of 58 billion versus prior 56 billion
- material: None | glm53: None | stopped: True
- Now Chain: not produced (see anomalies)

### e14_google_confirm — 2026-09-10T16:20:00+00:00 — `error`

- title: Google confirmed a Broadcom custom-silicon order expansion for next-generation TPU
- material: None | glm53: None | stopped: True
- Now Chain: not produced (see anomalies)

### e15_google_rumor_again — 2026-09-11T18:05:00+00:00 — `incremental`

- title: Unconfirmed: Google may reduce Broadcom custom TPU orders
- material: True | glm53: True | stopped: False
- 发生了什么: Unconfirmed: Google may reduce Broadcom custom TPU orders
- 为什么影响公司: No company exposure is linked yet.
- causal path: No complete causal path. Research first: How exposed is the issuer to Unconfirmed: Google may reduce Broadcom custom TPU orders, such that it would move The AI ramp implies unquantified dependence on…
- 市场怎么理解: Attention: What happened: a second unconfirmed report in the same direction pointing at Google reducing/delaying Broadcom custom silicon. Why it matters: the market has a… Expectation: actual 16.0 vs expected None (in_line, unchanged) Candidate drivers: 1. other; 2. Sector / macro move; 3. Market driver is unresolved; 4. Customer concentration concern is increasing. Which driver dominates is not…

### e16_marvell_win — 2026-09-12T15:30:00+00:00 — `error`

- title: Marvell wins a hyperscaler custom ASIC program Broadcom had been expected to supply
- material: None | glm53: None | stopped: True
- Now Chain: not produced (see anomalies)

### e17_230b_feature — 2026-09-14T12:00:00+00:00 — `l0_stop`

- title: Hock Tan Just Guided Broadcom's AI Revenue to Reach $230 Billion by 2028. Should You Believe Him?
- material: False | glm53: False | stopped: True
- 发生了什么: Hock Tan Just Guided Broadcom's AI Revenue to Reach $230 Billion by 2028. Should You Believe Him? (duplicate)
- 为什么影响公司: No company exposure is linked yet.
- causal path: No targeted causal path is available for this event.
- 市场怎么理解: Price alignment: unknown Confidence: low

### e18_unexplained_tape — 2026-09-16T19:30:00+00:00 — `observation_memory`

- title: AVGO shares move -6.2% with no new filing
- material: False | glm53: False | stopped: True
- 发生了什么: AVGO shares move -6.2% with no new filing (non_material)
- 为什么影响公司: No company exposure is linked yet.
- causal path: No targeted causal path is available for this event.
- 市场怎么理解: Price alignment: unexplained Confidence: low

Validation finished. No Phase 4 work. No architecture change. Waiting for review.
