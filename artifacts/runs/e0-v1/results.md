## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: run (offline analysis)
- Origin Date: 2026-10-19
- Verification Status: ANALYZED (input provenance and replay verification external)
- Version Label: tgselect-analysis-v1
- Repro Lock: null (frozen configuration and input-hash receipts are provided separately)
- Stage: e0
- Evidence Type: natural_local_generation

## e0 候选覆盖描述

N=20；所有任务保留在分母，包括空候选池。结果为探索性描述。
候选池覆盖：17/20 (85.0%)；候选数=320，不同源码数之和=297。

| Selector | Method | Coverage q/N | U q/N | Gain vs Top-2 | Loss vs Top-2 | Both | Neither |
|---|---|---|---|---|---|---|---|
| uniform | top2 | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| uniform | diverse | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| uniform | perturbed | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| aces_c | top2 | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| aces_c | diverse | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| aces_c | perturbed | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| dedup_uniform | top2 | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| dedup_uniform | diverse | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| dedup_uniform | perturbed | 16/20 (80.0%) | 1/20 (5.0%) | 1/20 (5.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 4/20 (20.0%) |
| group_equal | top2 | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| group_equal | diverse | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| group_equal | perturbed | 15/20 (75.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| group_rep | top2 | 15/20 (75.0%) | 1/20 (5.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| group_rep | diverse | 15/20 (75.0%) | 1/20 (5.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |
| group_rep | perturbed | 15/20 (75.0%) | 1/20 (5.0%) | 0/20 (0.0%) | 0/20 (0.0%) | 15/20 (75.0%) | 5/20 (25.0%) |

| Selector | Base accuracy | Raw W coverage (untruncated) | Raw W mean source count | Wrong base, pool correct | Identical-row blind spot | No alternative winner |
|---|---|---|---|---|---|---|
| uniform | 15/20 (75.0%) | 15/20 (75.0%) | 1.100 | 2/20 (10.0%) | 1/20 (5.0%) | 18/20 (90.0%) |
| aces_c | 15/20 (75.0%) | 15/20 (75.0%) | 1.100 | 2/20 (10.0%) | 1/20 (5.0%) | 18/20 (90.0%) |
| dedup_uniform | 15/20 (75.0%) | 16/20 (80.0%) | 1.200 | 2/20 (10.0%) | 1/20 (5.0%) | 16/20 (80.0%) |
| group_equal | 15/20 (75.0%) | 15/20 (75.0%) | 1.100 | 2/20 (10.0%) | 1/20 (5.0%) | 18/20 (90.0%) |
| group_rep | 14/20 (70.0%) | 14/20 (70.0%) | 1.150 | 3/20 (15.0%) | 1/20 (5.0%) | 17/20 (85.0%) |

| Selector | Random 20-seed mean coverage (equivalent q/N) | Seed SD | Seed min–max |
|---|---|---|---|
| uniform | 15/20 (75.0%) | 0.000 | 0.750–0.750 |
| aces_c | 15.1/20 (75.5%) | 0.015 | 0.750–0.800 |
| dedup_uniform | 16/20 (80.0%) | 0.000 | 0.800–0.800 |
| group_equal | 15/20 (75.0%) | 0.000 | 0.750–0.750 |
| group_rep | 15.5/20 (77.5%) | 0.025 | 0.750–0.800 |

| Selector | Paired coverage difference | Difference (percentage points) | 95% percentile CI (percentage points) |
|---|---|---|---|
| uniform | perturbed_minus_top2 | +0.00 | [+0.00, +0.00] |
| uniform | perturbed_minus_diverse | +0.00 | [+0.00, +0.00] |
| uniform | perturbed_minus_random_mean | +0.00 | [+0.00, +0.00] |
| aces_c | perturbed_minus_top2 | +0.00 | [+0.00, +0.00] |
| aces_c | perturbed_minus_diverse | +0.00 | [+0.00, +0.00] |
| aces_c | perturbed_minus_random_mean | -0.50 | [-1.50, +0.00] |
| dedup_uniform | perturbed_minus_top2 | +5.00 | [+0.00, +15.00] |
| dedup_uniform | perturbed_minus_diverse | +5.00 | [+0.00, +15.00] |
| dedup_uniform | perturbed_minus_random_mean | +0.00 | [+0.00, +0.00] |
| group_equal | perturbed_minus_top2 | +0.00 | [+0.00, +0.00] |
| group_equal | perturbed_minus_diverse | +0.00 | [+0.00, +0.00] |
| group_equal | perturbed_minus_random_mean | +0.00 | [+0.00, +0.00] |
| group_rep | perturbed_minus_top2 | +0.00 | [+0.00, +0.00] |
| group_rep | perturbed_minus_diverse | +0.00 | [+0.00, +0.00] |
| group_rep | perturbed_minus_random_mean | -2.50 | [-7.50, +0.00] |

## 限制

- Coverage 与 U 是候选集合内完美选择的潜力和救援上限；本次没有执行 E2 审核，不能解释为真实审核准确率或收益。
- 随机分组先在每题内平均全部 20 个固定种子，再按题配对 bootstrap；种子×任务及矩阵单元均不是独立样本。每个种子的结果保留在 JSON。
- 95% percentile 区间使用 10000 次任务重采样，seed=20261019。区间未作多重比较校正，仅用于探索；小样本和 E0 不支持确认性结论。
- 若样本中完全没有配对差异，经验 bootstrap 区间会退化为 [0,0]；这不能证明总体差异严格为零，也不能证明方法等效。
- 所有比例使用完整 N；没有替代赢家包含空池。完整行相同盲区仅在原赢家错误且存在同完整行的正确候选时计数。Raw W 单列，集合大小不与 k=2 覆盖混用。
- 输入来源、隐藏评测完整性及选择先于评测的冻结哈希需由运行 manifest 另行核验；分析函数不将缺失标签或缺失随机种子填成失败。
