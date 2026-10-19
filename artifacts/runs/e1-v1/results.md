## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: run (offline analysis)
- Origin Date: 2026-10-19
- Verification Status: ANALYZED (input provenance and replay verification external)
- Version Label: tgselect-analysis-v1
- Repro Lock: null (frozen configuration and input-hash receipts are provided separately)
- Stage: e1
- Evidence Type: natural_local_generation

## e1 候选覆盖描述

N=140；所有任务保留在分母，包括空候选池。结果为探索性描述。
候选池覆盖：121/140 (86.4%)；候选数=2240，不同源码数之和=2087。

| Selector | Method | Coverage q/N | U q/N | Gain vs Top-2 | Loss vs Top-2 | Both | Neither |
|---|---|---|---|---|---|---|---|
| uniform | top2 | 111/140 (79.3%) | 1/140 (0.7%) | 0/140 (0.0%) | 0/140 (0.0%) | 111/140 (79.3%) | 29/140 (20.7%) |
| uniform | diverse | 116/140 (82.9%) | 6/140 (4.3%) | 6/140 (4.3%) | 1/140 (0.7%) | 110/140 (78.6%) | 23/140 (16.4%) |
| uniform | perturbed | 112/140 (80.0%) | 2/140 (1.4%) | 1/140 (0.7%) | 0/140 (0.0%) | 111/140 (79.3%) | 28/140 (20.0%) |
| aces_c | top2 | 111/140 (79.3%) | 1/140 (0.7%) | 0/140 (0.0%) | 0/140 (0.0%) | 111/140 (79.3%) | 29/140 (20.7%) |
| aces_c | diverse | 116/140 (82.9%) | 6/140 (4.3%) | 6/140 (4.3%) | 1/140 (0.7%) | 110/140 (78.6%) | 23/140 (16.4%) |
| aces_c | perturbed | 112/140 (80.0%) | 2/140 (1.4%) | 1/140 (0.7%) | 0/140 (0.0%) | 111/140 (79.3%) | 28/140 (20.0%) |
| dedup_uniform | top2 | 109/140 (77.9%) | 5/140 (3.6%) | 0/140 (0.0%) | 0/140 (0.0%) | 109/140 (77.9%) | 31/140 (22.1%) |
| dedup_uniform | diverse | 115/140 (82.1%) | 11/140 (7.9%) | 7/140 (5.0%) | 1/140 (0.7%) | 108/140 (77.1%) | 24/140 (17.1%) |
| dedup_uniform | perturbed | 110/140 (78.6%) | 6/140 (4.3%) | 1/140 (0.7%) | 0/140 (0.0%) | 109/140 (77.9%) | 30/140 (21.4%) |
| group_equal | top2 | 111/140 (79.3%) | 1/140 (0.7%) | 0/140 (0.0%) | 0/140 (0.0%) | 111/140 (79.3%) | 29/140 (20.7%) |
| group_equal | diverse | 116/140 (82.9%) | 6/140 (4.3%) | 6/140 (4.3%) | 1/140 (0.7%) | 110/140 (78.6%) | 23/140 (16.4%) |
| group_equal | perturbed | 112/140 (80.0%) | 2/140 (1.4%) | 1/140 (0.7%) | 0/140 (0.0%) | 111/140 (79.3%) | 28/140 (20.0%) |
| group_rep | top2 | 113/140 (80.7%) | 5/140 (3.6%) | 0/140 (0.0%) | 0/140 (0.0%) | 113/140 (80.7%) | 27/140 (19.3%) |
| group_rep | diverse | 116/140 (82.9%) | 8/140 (5.7%) | 4/140 (2.9%) | 1/140 (0.7%) | 112/140 (80.0%) | 23/140 (16.4%) |
| group_rep | perturbed | 115/140 (82.1%) | 7/140 (5.0%) | 2/140 (1.4%) | 0/140 (0.0%) | 113/140 (80.7%) | 25/140 (17.9%) |

| Selector | Base accuracy | Raw W coverage (untruncated) | Raw W mean source count | Wrong base, pool correct | Identical-row blind spot | No alternative winner |
|---|---|---|---|---|---|---|
| uniform | 110/140 (78.6%) | 111/140 (79.3%) | 1.029 | 11/140 (7.9%) | 2/140 (1.4%) | 136/140 (97.1%) |
| aces_c | 110/140 (78.6%) | 111/140 (79.3%) | 1.043 | 11/140 (7.9%) | 2/140 (1.4%) | 135/140 (96.4%) |
| dedup_uniform | 104/140 (74.3%) | 106/140 (75.7%) | 1.036 | 17/140 (12.1%) | 2/140 (1.4%) | 135/140 (96.4%) |
| group_equal | 110/140 (78.6%) | 111/140 (79.3%) | 1.029 | 11/140 (7.9%) | 2/140 (1.4%) | 136/140 (97.1%) |
| group_rep | 108/140 (77.1%) | 112/140 (80.0%) | 1.107 | 13/140 (9.3%) | 3/140 (2.1%) | 125/140 (89.3%) |

| Selector | Random 20-seed mean coverage (equivalent q/N) | Seed SD | Seed min–max |
|---|---|---|---|
| uniform | 112.05/140 (80.0%) | 0.002 | 0.800–0.807 |
| aces_c | 112.5/140 (80.4%) | 0.004 | 0.800–0.807 |
| dedup_uniform | 110.25/140 (78.8%) | 0.004 | 0.786–0.800 |
| group_equal | 112.1/140 (80.1%) | 0.002 | 0.800–0.807 |
| group_rep | 114.7/140 (81.9%) | 0.007 | 0.807–0.829 |

| Selector | Paired coverage difference | Difference (percentage points) | 95% percentile CI (percentage points) |
|---|---|---|---|
| uniform | perturbed_minus_top2 | +0.71 | [+0.00, +2.14] |
| uniform | perturbed_minus_diverse | -2.86 | [-6.43, +0.00] |
| uniform | perturbed_minus_random_mean | -0.04 | [-0.11, +0.00] |
| aces_c | perturbed_minus_top2 | +0.71 | [+0.00, +2.14] |
| aces_c | perturbed_minus_diverse | -2.86 | [-6.43, +0.00] |
| aces_c | perturbed_minus_random_mean | -0.36 | [-0.96, +0.00] |
| dedup_uniform | perturbed_minus_top2 | +0.71 | [+0.00, +2.14] |
| dedup_uniform | perturbed_minus_diverse | -3.57 | [-7.14, +0.00] |
| dedup_uniform | perturbed_minus_random_mean | -0.18 | [-0.50, +0.00] |
| group_equal | perturbed_minus_top2 | +0.71 | [+0.00, +2.14] |
| group_equal | perturbed_minus_diverse | -2.86 | [-6.43, +0.00] |
| group_equal | perturbed_minus_random_mean | -0.07 | [-0.21, +0.00] |
| group_rep | perturbed_minus_top2 | +1.43 | [+0.00, +3.57] |
| group_rep | perturbed_minus_diverse | -0.71 | [-2.86, +1.43] |
| group_rep | perturbed_minus_random_mean | +0.21 | [-0.43, +1.00] |

## 限制

- Coverage 与 U 是候选集合内完美选择的潜力和救援上限；本次没有执行 E2 审核，不能解释为真实审核准确率或收益。
- 随机分组先在每题内平均全部 20 个固定种子，再按题配对 bootstrap；种子×任务及矩阵单元均不是独立样本。每个种子的结果保留在 JSON。
- 95% percentile 区间使用 10000 次任务重采样，seed=20261019。区间未作多重比较校正，仅用于探索；小样本和 E0 不支持确认性结论。
- 若样本中完全没有配对差异，经验 bootstrap 区间会退化为 [0,0]；这不能证明总体差异严格为零，也不能证明方法等效。
- 所有比例使用完整 N；没有替代赢家包含空池。完整行相同盲区仅在原赢家错误且存在同完整行的正确候选时计数。Raw W 单列，集合大小不与 k=2 覆盖混用。
- 输入来源、隐藏评测完整性及选择先于评测的冻结哈希需由运行 manifest 另行核验；分析函数不将缺失标签或缺失随机种子填成失败。
