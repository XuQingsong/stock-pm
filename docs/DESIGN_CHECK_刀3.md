# 刀3 昨盘 / 复盘收口清单（ACCEPTANCE_M2）

对照 gate。每条都有证据路径。不编预测边界 / 打脸 CTA / 判断变更，那些留给刀 4。

```text
1) TC-M2-TAPE-01..04: 量价形态、筹码+支撑压力、破位走法、对照环境（诱多/转势/吸筹/逃跑，标推断）
2) TC-M2-REV-01..02: 白话总结来自昨盘；因果链或「解释不了」
3) TC-M2-ARCH-01: 盘后自动发布，无每日确认门槛
4) TC-M2-NEG-01: K 线 / MA5/20/50/200 / 图仍是折叠 C，不代替结论
5) 环境 vs 昨盘冲突：一句因果，不并排两列
6) 昨盘半句用真实 one_liner；缺失诚实，不编量价
```

## 映射

| 验收 | 代码 | 测试 |
| --- | --- | --- |
| Q1 量价形态 | `tape.volume_price_form` / `synthesize_tape_analysis` | `tests/test_tape.py::test_volume_price_is_judgment_not_raw_volume`、`test_tape_answers_acceptance_m2_questions` |
| Q2 筹码+S/R | `_chip_block`；缺则 missingFlags | `test_honest_missing_chips_and_env` |
| Q3 破后走法 | `_break_block`：拉回/续杀/假突破 | `test_break_aftermath_pullback_and_fake_break` |
| Q4 环境对照 | `_env_link_block` 消费 EnvironmentSnapshot | `test_tape_env_link_is_not_tape_restatement` |
| 白话总结 | `synthesize_review_note.summary` | `test_review_note_vernacular_and_causal_or_unexplained` |
| 解释 / 解释不了 | 环境→昨盘→因此 或 `REVIEW_UNEXPLAINED` | 同上 |
| 自动发布 | `tape_job.publish_tape_and_reviews`；`review.main` 盘后调用 | `tests/test_tape_job.py` |
| 无确认门槛 | 不新增 confirm gate；`confirm_required` 仍 False | `tests/test_api.py`、`tests/test_philosophy.py` |
| 材料折叠 C | overview `details.materials`；个股 shell `data-zone="C"` | `test_static_shell_assets` |
| 冲突一句 | `env_tape_conflict_sentence`；overview `colspan=2` | `test_conflict_row_is_one_causal_sentence` |
| 昨盘半句 | `tape_half_display` | `test_tape_half_display_never_fakes_form` |

## 样句

| 角色 | 句子 |
| --- | --- |
| 昨盘半句 | `放量跌，续杀，60日成交密集成本 $130.00，逃跑（推断）` |
| 冲突一行 | `环境：宏观利空（加息预期升温），行业利空（存储去杠杆），氛围恐慌；昨盘：放量涨；因此：环境与昨盘反向，先按昨盘收盘读，不当成两套并列结论。` |
| 复盘解释 | `环境：宏观利空（加息预期升温），…。昨盘：放量跌，续杀。因此：对照环境（…）：…（推断：逃跑）。` |
| 解释不了 | `解释不了：消息与情绪依据不足，不硬编诱多、转势、吸筹或逃跑。` |
| 缺失 | `昨盘数据暂缺，未编造量价。` |

## 刀 4 明确不做

预测时间窗口与涨跌边界、自动打脸状态机、判断变更 CTA、M4 周洞察。
