#!/usr/bin/env python3
"""Export deterministic, descriptive coverage figures from completed runs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile

PLOT_VERSION = "tgselect-coverage-plot-v1"
SELECTORS = ("uniform", "aces_c", "dedup_uniform", "group_equal", "group_rep")
SELECTOR_LABELS = ("Uniform", "ACES-C", "Column dedup.", "Equal group weight", "Group representative")
METHODS = ("top2", "diverse", "perturbed", "random_mean")
METHOD_LABELS = ("Top-2", "Behavior-diverse", "Source-group perturbation", "Random groups: 20-seed mean")
COLORS = ("#0072B2", "#E69F00", "#009E73", "#CC79A7")
MARKERS = ("o", "s", "D", "^")
COMPARISONS = ("perturbed_minus_top2", "perturbed_minus_random_mean")
COMPARISON_LABELS = ("Perturbed minus Top-2", "Perturbed minus random mean")


def _load(path):
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Missing or invalid completed-run JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value, raw


def _finite(value, context):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Expected finite numeric {context}")
    return float(value)


def _coverage(metric, n, context):
    if not isinstance(metric, dict) or metric.get("n") != n:
        raise ValueError(f"Coverage denominator mismatch: {context}")
    rate = _finite(metric.get("rate"), f"coverage rate ({context})")
    q = _finite(metric.get("q"), f"coverage count ({context})")
    if not 0 <= rate <= 1 or not math.isclose(rate * n, q, abs_tol=1e-9):
        raise ValueError(f"Coverage q/N differs from its recorded rate: {context}")
    return 100 * rate


def _plot_data(summary, usage):
    """Validate denominators and map recorded proportions to plot units only."""
    stage = usage.get("split")
    expected_n = {"e0": 20, "e1": 140}.get(stage)
    if (usage.get("status") != "completed" or expected_n is None
            or usage.get("n_tasks") != expected_n or summary.get("n_tasks") != expected_n):
        raise ValueError("Require a completed 20-task E0 or 140-task E1 summary and usage receipt")
    if summary.get("evidence_type") != "natural_local_generation" or usage.get("evidence_type") != "natural_local_generation":
        raise ValueError("This figure requires completed natural experiment evidence")
    if usage.get("hash_chain", "").split(";")[0] != "validated":
        raise ValueError("Usage receipt must attest a validated frozen hash chain")
    inference = summary.get("inference", {})
    if (inference.get("resampling_unit") != "task" or inference.get("interval") != "percentile"
            or inference.get("confidence") != 0.95 or inference.get("e2_review_executed") is not False):
        raise ValueError("Require task bootstrap 95% percentile intervals and no E2 review")
    rows = []
    for selector in SELECTORS:
        result = summary["selectors"][selector]
        random = result["random"]
        if (random.get("n_seeds") != 20 or random.get("seeds") != list(range(20))
                or len(random.get("coverage_by_seed", [])) != 20):
            raise ValueError(f"Require all 20 fixed random grouping seeds: {selector}")
        for index, seed_metric in enumerate(random["coverage_by_seed"]):
            if seed_metric.get("seed") != index:
                raise ValueError(f"Random seed ordering differs from the frozen protocol: {selector}")
            _coverage(seed_metric, expected_n, f"{selector}/random/{index}")
        coverage = {method: _coverage(result["methods"][method]["coverage"], expected_n, f"{selector}/{method}")
                    for method in METHODS[:3]}
        coverage["random_mean"] = _coverage(random["coverage_mean"], expected_n, f"{selector}/random_mean")
        differences = {}
        for comparison in COMPARISONS:
            value = result["paired_differences"][comparison]
            if value.get("n") != expected_n or value.get("unit") != "task":
                raise ValueError(f"Paired difference task denominator mismatch: {selector}/{comparison}")
            point = _finite(value.get("difference"), "paired difference")
            ci = value.get("ci95")
            if not isinstance(ci, list) or len(ci) != 2:
                raise ValueError(f"Missing paired 95% interval: {selector}/{comparison}")
            low, high = (_finite(item, "CI endpoint") for item in ci)
            if low > high or any(abs(item) > 1 for item in (point, low, high)):
                raise ValueError(f"Invalid paired difference/interval: {selector}/{comparison}")
            comparator = "top2" if comparison.endswith("top2") else "random_mean"
            if not math.isclose(100 * point, coverage["perturbed"] - coverage[comparator], abs_tol=1e-9):
                raise ValueError(f"Paired point estimate differs from recorded coverages: {selector}/{comparison}")
            differences[comparison] = {"difference_pp": 100 * point, "ci95_pp": [100 * low, 100 * high]}
        rows.append({"selector": selector, "coverage_percent": coverage, "paired_differences": differences})
    return stage, expected_n, rows


def plot_results(run_dir: Path, output: Path | None = None) -> dict:
    run_dir = Path(run_dir).resolve()
    output = Path(output).resolve() if output is not None else run_dir / "coverage.svg"
    if output.suffix.lower() != ".svg":
        raise ValueError("--output must use .svg for a vector scientific figure")
    summary, summary_raw = _load(run_dir / "summary.json")
    usage, usage_raw = _load(run_dir / "usage.json")
    stage, n, rows = _plot_data(summary, usage)
    input_hashes = {"summary.json": hashlib.sha256(summary_raw).hexdigest(),
                    "usage.json": hashlib.sha256(usage_raw).hexdigest()}
    mapping = {"plot_version": PLOT_VERSION, "stage": stage, "n_tasks": n,
               "input_sha256": input_hashes, "rows": rows,
               "interpretation": "Exploratory oracle candidate-set coverage; no E2 reviewer was run; random seeds averaged within task"}

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    settings = {
        "font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11,
        "axes.labelsize": 10, "xtick.labelsize": 9, "ytick.labelsize": 10,
        "svg.hashsalt": PLOT_VERSION, "svg.fonttype": "none",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.axisbelow": True, "savefig.facecolor": "white",
    }
    with plt.rc_context(settings):
        figure, (coverage_ax, difference_ax) = plt.subplots(
            1, 2, figsize=(11.8, 5.7), sharey=True, gridspec_kw={"width_ratios": [1.05, 1]},
        )
        figure.subplots_adjust(left=0.175, right=0.975, bottom=0.31, top=0.79, wspace=0.16)
        figure.suptitle(f"{stage.upper()} exploratory candidate selection | n = {n} tasks", x=0.175, y=0.955,
                       ha="left", fontsize=14, fontweight="bold")
        figure.text(0.175, 0.89, "Fixed candidate pool; candidate-set oracle coverage (no E2 review)",
                    ha="left", fontsize=10, color="#444444")
        y_positions = list(range(len(SELECTORS)))
        offsets = (-0.24, -0.08, 0.08, 0.24)
        for method, label, color, marker, offset in zip(METHODS, METHOD_LABELS, COLORS, MARKERS, offsets, strict=True):
            coverage_ax.scatter(
                [row["coverage_percent"][method] for row in rows],
                [position + offset for position in y_positions],
                label=label, color=color, marker=marker, s=43, edgecolors="white", linewidths=0.45, zorder=3,
            )
        coverage_ax.set_xlim(0, 102)
        coverage_ax.set_xticks([0, 20, 40, 60, 80, 100])
        coverage_ax.set_yticks(y_positions, SELECTOR_LABELS)
        coverage_ax.set_ylim(len(SELECTORS) - 0.5, -0.5)
        coverage_ax.set_xlabel("Candidate-set coverage (%)")
        coverage_ax.set_title("(a) Review sets of at most two programs", loc="left", pad=12)
        coverage_ax.grid(axis="x", color="#D8D8D8", linewidth=0.6)
        coverage_ax.tick_params(axis="y", length=0, pad=8)
        coverage_ax.legend(loc="upper left", bbox_to_anchor=(-0.015, -0.19), frameon=False,
                           ncol=2, fontsize=8.1, handletextpad=0.3, columnspacing=1.1, borderaxespad=0)

        bounds = [abs(value) for row in rows for comparison in COMPARISONS
                  for value in [row["paired_differences"][comparison]["difference_pp"],
                                *row["paired_differences"][comparison]["ci95_pp"]]]
        limit = max(1.0, max(bounds, default=0) * 1.20)
        for comparison, label, color, marker, offset in zip(
            COMPARISONS, COMPARISON_LABELS, (COLORS[0], COLORS[3]), ("o", "^"), (-0.12, 0.12), strict=True,
        ):
            for index, row in enumerate(rows):
                point = row["paired_differences"][comparison]["difference_pp"]
                low, high = row["paired_differences"][comparison]["ci95_pp"]
                y = index + offset
                difference_ax.hlines(y, low, high, color=color, linewidth=1.6, zorder=2)
                difference_ax.vlines([low, high], y - 0.045, y + 0.045, color=color, linewidth=1.0, zorder=2)
                difference_ax.scatter([point], [y], color=color, marker=marker, s=43,
                                      edgecolors="white", linewidths=0.45, zorder=3,
                                      label=label if index == 0 else None)
        difference_ax.axvline(0, color="#555555", linewidth=0.9, linestyle="--", zorder=1)
        difference_ax.set_xlim(-limit, limit)
        difference_ax.xaxis.set_major_locator(MaxNLocator(nbins=5, symmetric=True))
        difference_ax.grid(axis="x", color="#D8D8D8", linewidth=0.6)
        difference_ax.tick_params(axis="y", left=False, labelleft=False)
        difference_ax.spines["left"].set_visible(False)
        difference_ax.set_xlabel("Paired coverage difference (percentage points)")
        difference_ax.set_title("(b) Perturbation contrasts with 95% CI", loc="left", pad=12)
        difference_ax.legend(loc="upper left", bbox_to_anchor=(-0.015, -0.19), frameon=False,
                             fontsize=8.1, handletextpad=0.3, borderaxespad=0)
        figure.text(0.175, 0.09, "All planned tasks remain in the denominator. Random grouping: mean of 20 fixed seeds within each task.",
                    ha="left", fontsize=8.7, color="#444444")
        figure.text(0.175, 0.047, "95% percentile CIs resample paired tasks; intervals are unadjusted and exploratory. Coverage is not reviewer accuracy.",
                    ha="left", fontsize=8.7, color="#444444")
        buffer = io.BytesIO()
        try:
            figure.savefig(buffer, format="svg", metadata={
                "Date": None, "Creator": PLOT_VERSION,
                "Title": f"{stage.upper()} exploratory candidate-set coverage, n={n}",
                "Description": json.dumps(mapping, sort_keys=True, separators=(",", ":"), allow_nan=False),
            })
        finally:
            plt.close(figure)
    # Recheck read-only sources before publishing a deterministic replacement.
    for name, digest in input_hashes.items():
        if hashlib.sha256((run_dir / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Plot input changed while rendering: {name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    content = b'\n'.join(line.rstrip() for line in buffer.getvalue().splitlines()) + b'\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"status": "completed", "plot_version": PLOT_VERSION, "output": str(output),
            "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), **mapping}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="SVG path; defaults to RUN_DIR/coverage.svg")
    args = parser.parse_args()
    try:
        receipt = plot_results(args.run_dir, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Plot export failed: {exc}\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
