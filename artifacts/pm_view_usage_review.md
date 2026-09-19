# PM View usage review — AVGO / LITE

Source of truth: persisted v2 artifacts (Postgres has no v2 Brain tables).
- AVGO: `artifacts/brain_token_stabilization/after_run/final_brain.json`
- LITE: `artifacts/brain_lite_cross_ticker/final_brain.json` (Slow layer empty; bootstrap object text was not persisted)

No Brain reasoning was changed. Display-only filters: drop placeholder hypotheses / expectations, drop process RQs and near-duplicates, cap lists, collapse What Changed to latest delta per object, lead with live thesis claims, hide empty support/counter rows.

## AVGO page — human review

**30–60s answers: yes, after display tightening.**

| Question | Found in | Time | Answer a PM can read |
|---|---|---|---|
| 当前最重要的投资逻辑 | Core Claims #1–3 | ~15s | AI demand durability is the length of the ramp; the ramp is concentrated in a few hyperscalers; AI is approaching a majority of revenue. Margin quality and the multiple are unverified, not the lead thesis. |
| 最近真正发生的变化 | What Changed | ~5s | Empty. This dump has no persisted history. Honest: the page does not invent a delta. |
| 市场可能在交易什么 | Market View + Now Chain Q4 | ~15s | Q3 AI semiconductor revenue 16.0 vs 17.2 (below, falling). FY2026 AI revenue 58 vs 56 (above). Live hypotheses: hyperscaler AI demand, and rising customer-concentration concern. Price is not fully explained. |
| 下一步最需要验证什么 | Open RQs (5 of 27) | ~15s | How much of the −12.59% was SOX vs the 16.0/17.2 miss; Google share of the $21.7B Q4 AI guide; why AI revenue missed despite “very strong”; whether 143% AI growth is sustainable. |

**Helpful**
- Five Core Claim *titles* are the thesis. Lead order is now durability → concentration → mix → margin → multiple.
- Numbered expectations (16.0 vs 17.2, 2.68 vs 2.83, 58 vs 56) are the fastest market read.
- The five kept RQs are checkable and named.

**Noise / remaining gaps**
- Claim statements are the same truncated Exhibit 99.1 sentence. Titles carry the logic; statements do not.
- Support / counter / recent change are not persisted on this Brain. The page no longer repeats “none persisted” five times.
- What Changed is empty because history was not in the artifact. Cannot be a change log until incremental history is stored.
- Now Chain has no latest event (`No event.`). Market View is the usable market section; Now Chain Q1–Q3 are weak on this dump.
- Hidden as display noise (still in Brain): 22 process RQs (`Can we confirm:`, `missing Market Driver/Edge`, `No core claim exists` — stale), hypotheses `other` / `unresolved` / `Sector / macro move` / slug `avgo_post_print_ai_revenue_shortfall`.

**Claim support vs thesis:** cannot match or mismatch — links were not persisted. Not a display bug.

## LITE page — human review

**30–60s answers: partial. Not a daily homepage yet.**

| Question | Found in | Time | Answer |
|---|---|---|---|
| 当前最重要的投资逻辑 | Core Claims | ~5s | **Cannot.** Slow layer is empty (`NEW_TICKER` / no Core Claims). Page correctly refuses to invent a thesis. Bootstrap produced 3/8/3 objects in-memory; they were not written into this persisted dump. |
| 最近真正发生的变化 | What Changed | ~5s | Empty. No history. |
| 市场可能在交易什么 | Market View | ~15s | Yes. Q3 GAAP EPS 1.50 vs 1.81; Q4 nGAAP EPS 3.23 vs 2.95; Q1 FY27 revenue guide ~1.25. Market may be trading AI/datacenter optical demand (~90% YoY) and customer concentration. |
| 下一步最需要验证什么 | Open RQs (5 of 30) | ~15s | Segment mix behind 90.1% growth; Q4 guidance / margin; whether $808.4M / $2.37 beat; what the print actually said so a state→driver chain can be built. |

**Helpful**
- Numbered expectations survive without a Slow Brain.
- `ai_demand` hypothesis is LITE-specific (optical / 90% YoY), not an AVGO copy.
- Top RQs are about mix, print vs street, and CPO/supply — the live tape issues.

**Noise / remaining gaps**
- No Core Claims, no States, no Drivers. Investment logic is missing. This is a persistence gap, not a PM View bug.
- Now Chain exposures are recovered stubs (`LITE is exposed to …`).
- `comparison=in_line` on 1.50 vs 1.81 is a Brain recording error from the tape; display does not rewrite it.
- Hidden: 25 process RQs (`Brain lacks…`, `missing Exposure/Edge`, `Can we confirm:`), hypotheses `other` / `unresolved`, duplicate Q4 EPS row, nameless `expectation`.

## Can this be the daily investment homepage?

**AVGO: yes, as a morning scan — with caveats.**
A PM can read the live thesis, the print-vs-expect numbers, and the next five checks in under a minute. It is not yet a change log (no history) and not yet an evidence page (no support/counter). Do not treat Now Chain as the homepage until events are persisted.

**LITE: not yet.**
Useful as a market/RQ side panel. Not usable as “open LITE and know the thesis.” Re-persist the Cold-Start Slow Brain (states / drivers / claims) before this ticker can be a homepage.

**Display-only changes made (no reasoning change)**
- Lead Core Claims with live thesis status, not unverified valuation.
- Hide empty support/counter/recent-change rows.
- Hide placeholder / slug hypotheses and nameless or null/null expectations; dedup near-identical prints.
- Show 5 of N RQs; drop process/stale/duplicate questions.
- Collapse What Changed to the latest real delta per object (cap 8).
- Feed Now Chain a short filtered subset so Market View is not repeated as a paragraph.
