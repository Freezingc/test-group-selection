"""Offline, paired task analysis after immutable selections and evaluation."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np


SELECTORS = ("uniform", "aces_c", "dedup_uniform", "group_equal", "group_rep")
METHODS = ("top2", "diverse", "perturbed")
RANDOM_SEEDS = tuple(range(20))


def _validate(records):
    seen = set()
    required = [name for selector in SELECTORS for name in (
        selector, *(f"{selector}__random_{seed}" for seed in RANDOM_SEEDS),
    )]
    for record in records:
        try:
            task_id = record["task_id"]
            if task_id in seen:
                raise ValueError(f"Duplicate task identifier: {task_id}")
            seen.add(task_id)
            candidates, matrix, labels = (record[k] for k in ("candidates", "matrix", "labels"))
            ids = [candidate["candidate_id"] for candidate in candidates]
            if any(not isinstance(cid, str) for cid in ids) or len(set(ids)) != len(ids):
                raise ValueError("Candidate identifiers must be unique strings")
            if any(not isinstance(candidate["source"], str) for candidate in candidates):
                raise ValueError("Candidate sources must be strings")
            if set(labels) != set(ids):
                raise ValueError("Evaluation labels must cover exactly the candidate pool")
            if any(not isinstance(value, (int, bool)) or value not in (0, 1) for value in labels.values()):
                raise ValueError("Evaluation labels must be binary integers")
            if len(matrix) != len(ids) or len({len(row) for row in matrix}) > 1:
                raise ValueError("Matrix rows must align with candidates and share column count")
            if any(not isinstance(value, (int, bool)) or value not in (0, 1) for row in matrix for value in row):
                raise ValueError("Matrix must contain binary integers")
            for name in required:
                selection = record["selections"][name]
                base = selection["base"]
                if (ids and base not in labels) or (not ids and base is not None):
                    raise ValueError("Base candidate does not match the available candidate pool")
                for method in (*METHODS, "raw_w"):
                    chosen = selection[method]
                    if not isinstance(chosen, list) or len(set(chosen)) != len(chosen):
                        raise ValueError("Review sets must be lists of unique candidate IDs")
                    if any(cid not in labels for cid in chosen):
                        raise ValueError("Selection refers to an unknown candidate")
                    if base is not None and base not in chosen:
                        raise ValueError("Every review set must retain its baseline candidate")
                    if method != "raw_w" and len(chosen) > 2:
                        raise ValueError("Review pairs may contain at most two candidates")
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Incomplete or invalid analysis record: {exc}") from exc


def _metric(values):
    values = list(values)
    q = sum(values)
    # Preserve integer counts and avoid numpy scalars in JSON output.
    q = int(q) if float(q).is_integer() else float(q)
    return {"q": q, "n": len(values), "rate": float(q / len(values)) if values else None}


def _coverage(record, selection, method):
    return int(any(record["labels"][cid] for cid in selection[method]))


def _count_summary(values):
    return {"total": sum(values), "mean": sum(values) / len(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def summarize(records: list[dict], bootstrap_replicates=10000, seed=20261019) -> dict:
    """Describe frozen selections; intervals resample whole paired tasks only.

    Missing labels or random-group runs are errors, never zero-filled failures.
    Empty candidate pools remain denominator tasks. Synthetic fixtures are
    identified explicitly and cannot be mixed with other experiment records.
    """
    if not isinstance(bootstrap_replicates, int) or isinstance(bootstrap_replicates, bool) or bootstrap_replicates < 1:
        raise ValueError("bootstrap_replicates must be a positive integer")
    _validate(records)
    synthetic = [record["task_id"].startswith("synthetic/") for record in records]
    if any(synthetic) and not all(synthetic):
        raise ValueError("Synthetic fixtures cannot be mixed with experiment records")
    n = len(records)
    rng = np.random.default_rng(seed)
    resamples = rng.integers(0, n, size=(bootstrap_replicates, n)) if n else None

    def paired(left, right):
        difference = np.asarray(left, dtype=float) - np.asarray(right, dtype=float)
        if n:
            distribution = difference[resamples].mean(axis=1)
            ci = [float(value) for value in np.percentile(distribution, [2.5, 97.5])]
            point = float(difference.mean())
        else:
            ci, point = None, None
        return {"difference": point, "ci95": ci, "n": n,
                "q_difference": float(difference.sum()), "unit": "task"}

    pool_coverage = [int(any(record["labels"].values())) for record in records]
    result = {
        "schema_version": "tgselect-analysis-v1", "n_tasks": n,
        "evidence_type": "synthetic_unit_fixture" if synthetic and all(synthetic) else "provided_offline_records",
        "provenance": "Input provenance and selection-freeze hashes must be verified against the run manifest externally.",
        "inference": {
            "status": "exploratory", "bootstrap_replicates": bootstrap_replicates,
            "seed": seed, "confidence": 0.95, "interval": "percentile",
            "resampling_unit": "task", "denominator": "all supplied task records, including empty pools",
            "multiplicity": "Unadjusted descriptive intervals; no confirmatory significance claims",
            "random_aggregation": "Mean across 20 fixed seeds within each task before paired task bootstrap",
            "e2_review_executed": False,
        },
        "pool": {
            "coverage": _metric(pool_coverage),
            "candidate_count": _count_summary([len(record["candidates"]) for record in records]),
            "unique_source_count": _count_summary([
                len({candidate["source"] for candidate in record["candidates"]}) for record in records
            ]),
            "empty_pool": _metric([int(not record["candidates"]) for record in records]),
        },
        "selectors": {},
    }
    for selector in SELECTORS:
        selections = [record["selections"][selector] for record in records]
        base_correct = [int(record["labels"].get(selection["base"], 0))
                        for record, selection in zip(records, selections)]
        cover = {method: [_coverage(record, selection, method)
                          for record, selection in zip(records, selections)]
                 for method in (*METHODS, "raw_w")}
        methods = {}
        for method in METHODS:
            pairs = list(zip(cover[method], cover["top2"]))
            methods[method] = {
                "coverage": _metric(cover[method]),
                "u": _metric([int(c and not b) for c, b in zip(cover[method], base_correct)]),
                "vs_top2": {
                    "gain": _metric([int(c and not t) for c, t in pairs]),
                    "loss": _metric([int(t and not c) for c, t in pairs]),
                    "both": _metric([int(c and t) for c, t in pairs]),
                    "neither": _metric([int(not c and not t) for c, t in pairs]),
                },
            }

        blind, no_alternative, raw_sizes = [], [], []
        for record, selection, b in zip(records, selections, base_correct):
            ids = [candidate["candidate_id"] for candidate in record["candidates"]]
            row_for = dict(zip(ids, record["matrix"]))
            source_for = {candidate["candidate_id"]: candidate["source"] for candidate in record["candidates"]}
            base = selection["base"]
            blind.append(int(base is not None and not b and any(
                record["labels"][cid] and row_for[cid] == row_for[base] for cid in ids
            )))
            raw_sources = {source_for[cid] for cid in selection["raw_w"]}
            no_alternative.append(int(base is None or not (raw_sources - {source_for[base]})))
            raw_sizes.append(len(raw_sources))

        random_coverage = [
            [_coverage(record, record["selections"][f"{selector}__random_{random_seed}"], "perturbed")
             for record in records] for random_seed in RANDOM_SEEDS
        ]
        random_task_mean = np.asarray(random_coverage, dtype=float).mean(axis=0).tolist()
        seed_metrics = [{"seed": random_seed, **_metric(values)}
                        for random_seed, values in zip(RANDOM_SEEDS, random_coverage)]
        seed_rates = [metric["rate"] for metric in seed_metrics]
        result["selectors"][selector] = {
            "base_accuracy": _metric(base_correct), "methods": methods,
            "raw_w": {"coverage": _metric(cover["raw_w"]), "unique_source_count": _count_summary(raw_sizes),
                      "untruncated": True},
            "mechanisms": {
                "baseline_wrong_pool_correct": _metric([int(p and not b) for p, b in zip(pool_coverage, base_correct)]),
                "identical_row_blind_spot": _metric(blind),
                "no_alternative_winner": _metric(no_alternative),
            },
            "random": {
                "n_seeds": len(RANDOM_SEEDS), "seeds": list(RANDOM_SEEDS),
                "coverage_mean": _metric(random_task_mean), "coverage_by_seed": seed_metrics,
                "coverage_seed_std": float(np.std(seed_rates)) if n else None,
                "coverage_seed_min": min(seed_rates) if n else None,
                "coverage_seed_max": max(seed_rates) if n else None,
                "q_interpretation": "Sum of per-task seed-mean coverage; fractional equivalent count, not extra tasks",
            },
            "paired_differences": {
                "perturbed_minus_top2": paired(cover["perturbed"], cover["top2"]),
                "perturbed_minus_diverse": paired(cover["perturbed"], cover["diverse"]),
                "perturbed_minus_random_mean": paired(cover["perturbed"], random_task_mean),
            },
        }
    return result


def render_markdown(summary: dict, stage="e0") -> str:
    """Render descriptive coverage evidence with an ARS Material Passport."""
    def metric(item):
        rate = "NA" if item["rate"] is None else f"{100 * item['rate']:.1f}%"
        return f"{item['q']:g}/{item['n']} ({rate})"

    def number(value):
        return "NA" if value is None else f"{value:.3f}"

    date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    lines = [
        "## Material Passport", "", "- Origin Skill: experiment-agent", "- Origin Mode: run (offline analysis)",
        f"- Origin Date: {date}", "- Verification Status: ANALYZED (input provenance and replay verification external)",
        "- Version Label: tgselect-analysis-v1", f"- Stage: {stage}",
        f"- Evidence Type: {summary['evidence_type']}", "",
        f"## {stage} 候选覆盖描述", "",
        f"N={summary['n_tasks']}；所有任务保留在分母，包括空候选池。结果为探索性描述。",
        f"候选池覆盖：{metric(summary['pool']['coverage'])}；"
        f"候选数={summary['pool']['candidate_count']['total']}，不同源码数之和={summary['pool']['unique_source_count']['total']}。", "",
        "| Selector | Method | Coverage q/N | U q/N | Gain vs Top-2 | Loss vs Top-2 | Both | Neither |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for selector, result in summary["selectors"].items():
        for method, values in result["methods"].items():
            versus = values["vs_top2"]
            cells = [selector, method, metric(values["coverage"]), metric(values["u"])]
            cells += [metric(versus[key]) for key in ("gain", "loss", "both", "neither")]
            lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "| Selector | Base accuracy | Raw W coverage (untruncated) | Raw W mean source count | Wrong base, pool correct | Identical-row blind spot | No alternative winner |",
              "|---|---|---|---|---|---|---|"]
    for selector, result in summary["selectors"].items():
        mechanisms = result["mechanisms"]
        cells = [selector, metric(result["base_accuracy"]), metric(result["raw_w"]["coverage"]),
                 number(result["raw_w"]["unique_source_count"]["mean"])]
        cells += [metric(mechanisms[key]) for key in ("baseline_wrong_pool_correct", "identical_row_blind_spot", "no_alternative_winner")]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "| Selector | Random 20-seed mean coverage (equivalent q/N) | Seed SD | Seed min–max |",
              "|---|---|---|---|"]
    for selector, result in summary["selectors"].items():
        random = result["random"]
        lines.append(f"| {selector} | {metric(random['coverage_mean'])} | {number(random['coverage_seed_std'])} | "
                     f"{number(random['coverage_seed_min'])}–{number(random['coverage_seed_max'])} |")
    lines += ["", "| Selector | Paired coverage difference | Difference (percentage points) | 95% percentile CI (percentage points) |",
              "|---|---|---|---|"]
    for selector, result in summary["selectors"].items():
        for comparison, values in result["paired_differences"].items():
            point = "NA" if values["difference"] is None else f"{100 * values['difference']:+.2f}"
            ci = "NA" if values["ci95"] is None else f"[{100 * values['ci95'][0]:+.2f}, {100 * values['ci95'][1]:+.2f}]"
            lines.append(f"| {selector} | {comparison} | {point} | {ci} |")
    lines += ["", "## 限制", "",
              "- Coverage 与 U 是候选集合内完美选择的潜力和救援上限；本次没有执行 E2 审核，不能解释为真实审核准确率或收益。",
              "- 随机分组先在每题内平均全部 20 个固定种子，再按题配对 bootstrap；种子×任务及矩阵单元均不是独立样本。每个种子的结果保留在 JSON。",
              f"- 95% percentile 区间使用 {summary['inference']['bootstrap_replicates']} 次任务重采样，seed={summary['inference']['seed']}。区间未作多重比较校正，仅用于探索；小样本和 E0 不支持确认性结论。",
              "- 所有比例使用完整 N；没有替代赢家包含空池。完整行相同盲区仅在原赢家错误且存在同完整行的正确候选时计数。Raw W 单列，集合大小不与 k=2 覆盖混用。",
              "- 输入来源、隐藏评测完整性及选择先于评测的冻结哈希需由运行 manifest 另行核验；分析函数不将缺失标签或缺失随机种子填成失败。"]
    if summary["evidence_type"] == "synthetic_unit_fixture":
        lines += ["- 本表仅为 synthetic unit fixture；不得合入自然实验结果或用于检验研究假设。"]
    return "\n".join(lines) + "\n"
