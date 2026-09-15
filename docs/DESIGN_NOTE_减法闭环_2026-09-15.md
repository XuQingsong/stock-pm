# DESIGN_NOTE · 减法闭环落地差异（2026-09-15）

> Brief：`DESIGN_BRIEF_减法闭环_主结构冻结_2026-09-15.md`  
> 交付：三页 hi-fi HTML + states（牵动）+ 本注记；**PNG 由父级统一重出**。不加模块 · IA 不变 · 开发仍冻。

## 七项对照

| # | 锁项 | 落地 |
| --- | --- | --- |
| 1 | 主路径去系统词 | 去掉 A/B/C 层标、R 编号、L0、PredictionCheck、v0、重评队列。强度理由改白话（暴露/传导）。细则进诊断/折叠。 |
| 2 | 个股重复标签收敛 | 当前判断与今日动作各只留「研究倾向偏多 · 不追高（观察）」一句，不堆流程态 pill。 |
| 3 | 总览结构不变 | 仍：主事件 → 今日重点关注 → 其余事件；依据默认折叠；「可先不点开：N只」默认收起。 |
| 4 | 个股五段 + 昨→今·中期 | 五段保留；第 2 段强化昨/今分栏 + 中期「不变」高亮。 |
| 5 | thesis 变化一眼可见 | 第 2 段顶部 `昨 → 今` 条 +「判断变了」chip。 |
| 6 | 复盘分家 + 错误归因/学习 | 正式/观察分家保留；正式侧下新增「错误归因 · 学习」两卡（对在哪/错在哪/下次）。 |
| 7 | 统一终稿 PNG | **本席不截**；父级按 `design-hifi/*.html` 重出 overview / stock / review（states 已牵动）。 |

## 文件

- `design-hifi/overview.html` · `stock.html` · `review.html` · `states.html` · `index.html` · `shared.css`
- 未改：无持仓口径、强度逻辑、事件默认折叠策略

## 交审

只交 **PM → 用户十秒验收**。Coding FROZEN。


## item7 终稿 PNG（2026-09-15 重出）

| 文件 | mtime (UTC) |
| --- | --- |
| hifi-overview.png | 03:24 |
| hifi-stock-NVDA.png | 03:25 |
| hifi-review.png | 03:25 |
| hifi-states.png | 03:25 |
| hifi-states-B.png | 03:27 |
| hifi-states-C.png | 03:28 |

软修：overview 展开链「事实→变化→预期」；review 卡头「正式预测 · 日期」（去掉 PRED- 编号）。
