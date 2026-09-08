# 刀4 预测 / 打脸收口清单（ACCEPTANCE_M3）

对照 gate。每条都有证据路径。不编 M4 周洞察。环境与昨盘只作前提，不重开刀 2/3。

```text
1) TC-M3-PRED-01: 时间窗口 + 上涨边界 + 下跌边界（合格例：两周内补涨约10%，期间跌幅不超过5%）
2) TC-M3-PRED-02: 因果链 环境→昨盘→解释→因此（边界）
3) TC-M3-SM-01: 状态机 auto-gen → pending → active → hit / invalidated / superseded
4) TC-M3-CHECK-01: 盘后 PredictionCheck，价格破界自动打脸
5) TC-M3-CHECK-02: 窗口到期未兑现 = 打脸；对照价缺失不静默判对
6) TC-M3-CHANGE-01: 严重预警 alert_id 前置（需求方硬项）→ 人工改口 CTA；supersedes 留痕
7) TC-M3-CHANGE-02: 小噪声不自动改口
8) TC-M3-UI-01: 总览预测徽章绑真实 Prediction，不编假边界
9) TC-M3-NEG-01: 质量门失败 / 到期未产出 / 缺数可见
10) TC-M3-LEGACY: llm_outlook / 旧命中率标「旧口径」
11) TC-M3-ARCH-01: 历史只追加；无每日确认门槛；材料仍折叠 C
```

## 映射

| 验收 | 代码 | 测试 |
| --- | --- | --- |
| 合格预测 | `prediction.synthesize_prediction` | `tests/test_prediction.py::test_qualified_example_has_window_and_both_bounds` |
| 因果链 | `thesis` 环境→昨盘→解释→因此 | 同上 |
| 状态机 | lifecycle + `activate_if_due` / `run_prediction_check` | `test_state_machine_auto_gen_pending_active_hit` |
| 自动打脸 | 低点 ≤ 下跌价 → `invalidated` + alert CTA | `test_face_slap_on_downside_break_not_small_noise` |
| 到期未兑现 | `outcome=expired` | `test_expired_window_is_face_slap` |
| 改口留痕 | `apply_supersede` / `POST .../supersede` 必须带严重 `alert_id` | `test_human_supersede_leaves_trace_and_is_not_automatic`、`test_require_judgment_alert_rejects_unusable_alerts`、`tests/test_api.py` |
| 小噪声 | 未破界保持 tracking | `test_face_slap_on_downside_break_not_small_noise` |
| 总览徽章 | `prediction_badge`；overview「预测」列 | `test_badge_never_fakes_bounds`、`tests/test_api.py` |
| 诚实缺失 | `failed_prediction` / 质量门 | `test_quality_gate_failure_is_visible_missing` |
| 旧口径 | `mark_legacy_hit_rate`；UI「旧口径」 | `test_legacy_hit_rate_is_labeled`、`test_face_slap_shell_does_not_claim_prediction` |
| 自动发布 | `prediction_job.publish_predictions_and_checks` | `tests/test_prediction_job.py` |

## 样句

| 角色 | 句子 |
| --- | --- |
| 合格预测 | `环境：…。昨盘：…。解释：…。因此：两周内补涨约10%，期间跌幅不超过5%。` |
| 徽章 | `两周内 上10% / 下5% · 跟踪中` |
| 缺失 | `缺数，未编造时间窗口或涨跌边界。` / `到期未产出` |
| 打脸 | `期间低点 $18.70 跌破下跌边界 $19.00（5%），判定打脸。` |
| 改口 | `改口必须写原因，留痕` |
| 旧口径 | `这是旧口径（规则/模型偏向对照），不是新 Prediction 时间窗口或涨跌边界。` |

## 明确不做

M4 周洞察。不重开刀 2/3 环境/昨盘实现，只消费它们当前提。
