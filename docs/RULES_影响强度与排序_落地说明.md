# Strength / sort notes (repo freeze)

The files named in the 2026-09-15 brief (`RULES_影响强度分档.md`,
`DESIGN_事件排序.md`, `DESIGN_判断变化与行动口径.md`,
`DESIGN_NOTE_自选无持仓_2026-09-15.md`) were **not in this git tree**.
Implementation follows:

- Hi-fi chips: 深绿 / 浅绿 / 灰 / 黄 / 浅红 / 深红
- Existing `events.exposure.why_relevant` (channel + mechanism + why), not
  headline ticker paste
- Deep colors only when exposure is inspectable **and** the event closed-loop
  is observable; otherwise gray/yellow
- Sort: mapped watchlist first, then strength, closed-loop, scope, recency
- Copy: 研究倾向 / 不追高（观察） / 近端转谨慎; no 持有/减仓/加仓

If those rule docs land later, replace labels in `stock_pm/pack/strength.py`
and `stock_pm/pack/sort.py` only — do not add modules.
