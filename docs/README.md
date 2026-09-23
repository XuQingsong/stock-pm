# 过程文档（中间产物）

讨论里生成的评估、方案、对照表会同时留两份：

1. **仓库里（跟代码一起上 GitHub）**：本目录。换电脑或过几个月，打开这个仓库就能找到。
2. **Cursor 里可交互打开**：`C:\Users\11737\.cursor\projects\d-workspace-stock-pm\canvases\`。在 Cursor 中点开 `.canvas.tsx` 可在聊天旁渲染。

聊天记录本身在 `C:\Users\11737\.cursor\projects\d-workspace-stock-pm\agent-transcripts\`，不是这些评估文件。

## canvases/

| 文件 | 内容 |
| --- | --- |
| [../CURSOR_BRIEF.md](../CURSOR_BRIEF.md) | 连续切片说明：A/P0 → 环境（刀 2）→ 盘面（刀 3）→ 预测打脸（刀 4 已落地）；主路径无每日确认门槛 |
| [DESIGN_CHECK_刀2_PR3.md](DESIGN_CHECK_刀2_PR3.md) | PR #3 三条核验：因果半句、材料折叠 C、环境 A/B/C；含证据路径与中文样句 |
| [DESIGN_CHECK_刀3.md](DESIGN_CHECK_刀3.md) | 刀 3 ACCEPTANCE_M2：昨盘四问、复盘总结/解释、自动发布、材料折叠 C |
| [DESIGN_CHECK_刀4.md](DESIGN_CHECK_刀4.md) | 刀 4 ACCEPTANCE_M3：预测边界、状态机、自动打脸、改口留痕、旧口径 |
| [postgres.md](postgres.md) | 阶段 4B：可复现 Postgres 启动、迁移、安全 DATABASE_URL、真实写入/读回 |
| [DEPLOY_43.md](DEPLOY_43.md) | 现网 `http://43.166.2.31/` tip-tar 部署；缺密钥时诚实降级 |
| [DEV_BRIEF_决策系统整包_2026-09-15.md](DEV_BRIEF_决策系统整包_2026-09-15.md) | 总览+个股+复盘整包真数据一次上线 |
| [DESIGN_BRIEF_减法闭环_主结构冻结_2026-09-15.md](DESIGN_BRIEF_减法闭环_主结构冻结_2026-09-15.md) | IA 冻结：去系统词、五段个股、复盘分家 |
| [DESIGN_NOTE_减法闭环_2026-09-15.md](DESIGN_NOTE_减法闭环_2026-09-15.md) | 减法闭环落地差异；hi-fi 对照 |
| [BRAIN_V1_DESIGN.md](BRAIN_V1_DESIGN.md) | Brain V1：从新闻聚合升级为 Evidence→Assumption→Thesis 研究系统；现网复用评估、评审修订与 Sprint 1 验收 |
| [V1_STEP1_API_MAPPING.md](V1_STEP1_API_MAPPING.md) | V1 第一阶段 Step 1：Persisted Brain → MarketDominantDriver / TickerMarketSensitivity / 三读 API 映射（无第二套 kernel） |
| [V1_STEP2_MARKET_PAGE.md](V1_STEP2_MARKET_PAGE.md) | V1 第一阶段 Step 2：市场总览页 `/market` 只读 overview API；空状态与分层自验 |
| [BRAIN_MATERIALIZE_FROM_RESEARCH.md](BRAIN_MATERIALIZE_FROM_RESEARCH.md) | 一次性离线：research_* → brain_*；零 LLM；不调度重跑；页路径只读已落盘 Brain |
| [DESIGN_NOTE_V1_市场总览对齐_2026-09-19.md](DESIGN_NOTE_V1_市场总览对齐_2026-09-19.md) | 市场总览对齐锁：分条主轴、触发分层、空状态、中文枚举 |
| [NEWS_LAYER_N0_对接评估_2026-09-23.md](NEWS_LAYER_N0_对接评估_2026-09-23.md) | 新闻层 N0：现有美股数据源清单、RawArticle 对接缺口、冗余缺口、调度问题、`schema/news.sql` 并入规则 |
| [NEWS_LAYER_四个核心问题_2026-09-23.md](NEWS_LAYER_四个核心问题_2026-09-23.md) | 新闻层四个核心问题（覆盖与实时、分类、重要度、关联）的解决方案、生产指标、动态探索闭环与 N1–N4 落地顺序 |
| [canvases/product-fit-evaluation.canvas.tsx](canvases/product-fit-evaluation.canvas.tsx) | Product Fit Evaluation：对照「基本面 / 隔日盘面 / 复盘迭代」三块目标 |
| [canvases/redesign-plan.canvas.tsx](canvases/redesign-plan.canvas.tsx) | 重构方案：四页信息架构、分段量价、事件→板块、自选入库 |
| [canvases/code-review.canvas.tsx](canvases/code-review.canvas.tsx) | 早期代码评估与必须先修的问题 |
| [canvases/data-source-conflicts.canvas.tsx](canvases/data-source-conflicts.canvas.tsx) | FMP/Nasdaq/Cboe/Alpaca 数据源是否打架 |
