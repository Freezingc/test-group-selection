#!/usr/bin/env python3
"""Validate a completed frozen run and export compact, source-free evidence."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tgselect import data
from tgselect.analysis import RANDOM_SEEDS, SELECTORS, summarize
from tgselect.experiment import read_jsonl, validate_frozen_inputs


def _bytes_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _sha(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"Missing or invalid required JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _require_completed(value, path):
    if value.get("status") != "completed":
        raise ValueError(f"Required evidence is not completed: {path}")


def _match(value, expected, context):
    for key, actual in expected.items():
        if value.get(key) != actual:
            raise ValueError(f"{context} mismatch: {key}")


def _bound_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _count(value, context):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"Invalid non-negative integer: {context}")
    return value


def _generation_usage(records, tasks, config, config_hash):
    expected = {
        f"{task['task_id']}/{kind}/{index:02d}": (task["task_id"], kind)
        for task in tasks for kind, count in (("candidate", config["candidate_count"]), ("tests", config["group_count"]))
        for index in range(count)
    }
    ids = [record.get("request_id") for record in records]
    if len(set(ids)) != len(ids) or set(ids) != set(expected):
        raise ValueError("Generation requests are missing, duplicated or outside the planned task set")
    task_hashes = {task["task_id"]: task["task_hash"] for task in tasks}
    counters = {kind: {"requests": 0, "input_tokens": 0, "output_tokens": 0, "finish_reasons": Counter()}
                for kind in ("candidate", "tests")}
    variants = {}
    parameters = {key: config[key] for key in ("temperature", "top_p", "max_tokens")}
    for record in records:
        task_id, kind = expected[record["request_id"]]
        _match(record, {"task_id": task_id, "kind": kind, "config_sha256": config_hash,
                        "task_hash": task_hashes[task_id], "model_id": config["model_id"],
                        "model_revision": config["model_revision"],
                        "generation_backend": config["generation_backend"],
                        "generation_parameters": parameters}, "Generation identity")
        identifier = "candidate_id" if kind == "candidate" else "generation_batch_id"
        if record.get(identifier) != record["request_id"]:
            raise ValueError("Generation request identifier does not match candidate/batch identifier")
        if not isinstance(record.get("prompt"), str) or record.get("prompt_hash") != _sha_bytes(record["prompt"].encode()):
            raise ValueError("Generation prompt hash mismatch")
        finish = record.get("finish_reason")
        if not isinstance(finish, str) or not finish:
            raise ValueError("Missing generation finish status")
        counter = counters[kind]
        counter["requests"] += 1
        for key in ("input_tokens", "output_tokens"):
            counter[key] += _count(record.get(key), f"generation {key}")
        counter["finish_reasons"][finish] += 1
        metadata = record.get("backend_metadata")
        if not isinstance(metadata, dict) or metadata.get("backend_version") != config["generation_backend"]:
            raise ValueError("Missing or inconsistent generation backend metadata")
        canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        key = _sha_bytes(canonical)
        if key not in variants:
            variants[key] = {"sha256": key, "requests": 0, "metadata": metadata}
        variants[key]["requests"] += 1
    total = {"requests": sum(counter["requests"] for counter in counters.values()),
             "input_tokens": sum(counter["input_tokens"] for counter in counters.values()),
             "output_tokens": sum(counter["output_tokens"] for counter in counters.values()),
             "finish_reasons": dict(sum((counter["finish_reasons"] for counter in counters.values()), Counter()))}
    for counter in counters.values():
        counter["finish_reasons"] = dict(counter["finish_reasons"])
    return {**counters, "total": total, "backend_variants": [variants[key] for key in sorted(variants)],
            "token_accounting": "Exact sum of recorded per-request tokenizer counts; EOS convention retained in backend metadata"}


def _process_usage(run_dir):
    phases, hashes, starts, ends = [], {}, [], []
    for path in sorted(run_dir.rglob("*.process.json")):
        receipt = _read(path)
        _require_completed(receipt, path)
        if receipt.get("exit_code") != 0:
            raise ValueError(f"Process receipt has a non-zero or missing exit code: {path}")
        elapsed = receipt.get("elapsed_seconds")
        if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError(f"Process receipt lacks a valid elapsed time: {path}")
        phase = {"receipt": str(path.relative_to(run_dir)), "status": "completed", "exit_code": 0,
                 "elapsed_seconds": elapsed,
                 "peak_process_tree_rss_bytes": receipt.get("peak_process_tree_rss_bytes"),
                 "gpu_index": receipt.get("gpu_index"), "peak_gpu_used_mib": receipt.get("peak_gpu_used_mib"),
                 "gpu_monitor_degraded": receipt.get("gpu_monitor_degraded", False),
                 "start_utc": receipt.get("start_utc"), "end_utc": receipt.get("end_utc")}
        for key in ("peak_process_tree_rss_bytes", "peak_gpu_used_mib"):
            if phase[key] is not None:
                _count(phase[key], f"process {key}")
        if phase["start_utc"] and phase["end_utc"]:
            starts.append(datetime.fromisoformat(phase["start_utc"]))
            ends.append(datetime.fromisoformat(phase["end_utc"]))
        phases.append(phase)
        hashes[path] = _sha(path)
    rss = [phase["peak_process_tree_rss_bytes"] for phase in phases if phase["peak_process_tree_rss_bytes"] is not None]
    gpu = [phase["peak_gpu_used_mib"] for phase in phases if phase["gpu_index"] is not None and phase["peak_gpu_used_mib"] is not None]
    return {
        "phases": phases,
        "sum_phase_elapsed_seconds": sum(phase["elapsed_seconds"] for phase in phases) if phases else None,
        "wall_span_seconds": (max(ends) - min(starts)).total_seconds() if phases and len(starts) == len(phases) else None,
        "max_phase_peak_process_tree_rss_bytes": max(rss) if rss else None,
        "peak_observed_device_memory_used_mib": max(gpu) if gpu else None,
        "gpu_associated_stage_elapsed_seconds": sum(phase["elapsed_seconds"] for phase in phases if phase["gpu_index"] is not None) if phases else None,
        "actual_gpu_compute_seconds": None,
        "timing_scope": "Stage elapsed times may overlap; their sum is not a claim about total wall time or active GPU compute",
        "gpu_memory_scope": "nvidia-smi whole-device memory.used; may include other processes; zero samples do not prove zero usage",
    }, hashes


def _task_metrics(tasks, labels, selections):
    output = []
    for task in tasks:
        task_id = task["task_id"]
        truth = labels[task_id]
        sources = {candidate["candidate_id"]: _sha_bytes(candidate["source"].encode()) for candidate in task["candidates"]}
        rows = {candidate["candidate_id"]: row for candidate, row in zip(task["candidates"], task["matrix"], strict=True)}
        candidate_evidence = [{"candidate_id": candidate["candidate_id"], "source_sha256": sources[candidate["candidate_id"]],
                               "row_sha256": _sha_bytes(json.dumps([int(value) for value in rows[candidate["candidate_id"]]], separators=(",", ":")).encode()),
                               "correct": int(truth[candidate["candidate_id"]])} for candidate in task["candidates"]]
        pool_correct = int(any(truth.values()))
        selector_evidence = {}
        for selector in SELECTORS:
            selected = selections[task_id][selector]
            base = selected["base"]
            base_correct = int(truth.get(base, 0))
            methods = {
                method: {"selected_ids": selected[method], "coverage": int(any(truth[cid] for cid in selected[method]))}
                for method in ("top2", "diverse", "perturbed", "raw_w")
            }
            random_ids = {str(seed): selections[task_id][f"{selector}__random_{seed}"]["perturbed"] for seed in RANDOM_SEEDS}
            selector_evidence[selector] = {
                "base_id": base, "base_correct": base_correct, "methods": methods,
                "random_coverage": {seed: int(any(truth[cid] for cid in chosen)) for seed, chosen in random_ids.items()},
                "random_selected_ids": random_ids,
                "baseline_wrong_pool_correct": int(not base_correct and pool_correct),
                "identical_row_blind_spot": int(base is not None and not base_correct and any(
                    truth[cid] and rows[cid] == rows[base] for cid in truth)),
                "no_alternative_winner": int(base is None or not any(sources[cid] != sources[base] for cid in selected["raw_w"])),
            }
        counts = task["counts"]
        if (counts["usable_candidates"] != len(task["candidates"])
                or counts["unique_sources"] != len(set(sources.values()))
                or counts["valid_tests"] != len(task["tests"])
                or len(task["groups"]) != len(task["tests"])
                or any(len(row) != len(task["tests"]) for row in rows.values())
                or sum(counts["candidate_statuses"].values()) != counts["requested_candidates"]):
            raise ValueError(f"Task candidate/test counts do not match frozen records: {task_id}")
        output.append({
            "schema_version": "tgselect-task-metrics-v1", "task_id": task_id, "split": task["split"],
            "requested_candidates": counts["requested_candidates"], "usable_candidates": len(task["candidates"]),
            "unique_sources": len(set(sources.values())), "candidate_parse_statuses": counts["candidate_statuses"],
            "requested_test_batches": counts["requested_test_batches"], "valid_tests": len(task["tests"]),
            "test_parse_failures": counts["test_parse_failures"], "execution_statuses": task.get("execution_statuses", {}),
            "pool_correct": pool_correct, "candidates": candidate_evidence, "selectors": selector_evidence,
            "row_hash_encoding": "SHA256 of compact JSON array of the complete binary generated-test row",
        })
    return output


def _ensure_unchanged(hashes):
    for path, expected in hashes.items():
        if _sha(path) != expected:
            raise ValueError(f"Frozen input changed during finalization: {path}")


def _atomic_write(path, content):
    if path.exists():
        return  # All existing bytes were compared before any output was written.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def finalize_run(run_dir: Path) -> dict:
    """Only completed inputs may produce compact artifacts; raw files stay intact."""
    run_dir = Path(run_dir).resolve()
    paths = {name: run_dir / relative for name, relative in {
        "summary": "summary.json", "inputs": "inputs.manifest.json", "tasks": "raw/tasks.jsonl",
        "selections": "raw/selections.jsonl", "generation": "raw/generation.jsonl",
        "matrix_manifest": "raw/tasks.manifest.json", "selection_manifest": "raw/selections.manifest.json",
        "evaluation_receipt": "evaluation/receipt.json", "labels": "evaluation/labels.json",
    }.items()}
    for path in paths.values():
        if not path.is_file():
            raise ValueError(f"Missing required completed-run evidence: {path}")
    snapshot_hashes = {path: _sha(path) for path in paths.values()}
    summary, inputs = _read(paths["summary"]), _read(paths["inputs"])
    _require_completed(inputs, paths["inputs"])
    bound = inputs.get("inputs")
    if not isinstance(bound, dict) or len(bound) != 4:
        raise ValueError("Analysis inputs manifest must bind tasks, selections, labels and config")
    resolved = {_bound_path(name): digest for name, digest in bound.items()}
    if len(resolved) != 4 or not {paths[name] for name in ("tasks", "selections", "labels")} <= set(resolved):
        raise ValueError("Analysis input paths do not bind this run's raw tasks, selections and labels")
    for path, digest in resolved.items():
        if not path.is_file() or _sha(path) != digest:
            raise ValueError(f"Analysis input hash mismatch: {path}")
    config_path = next(iter(set(resolved) - {paths[name] for name in ("tasks", "selections", "labels")}))
    snapshot_hashes.update(resolved)
    frozen = validate_frozen_inputs(paths["tasks"], config_path, paths["selections"])
    tasks, config = frozen["tasks"], frozen["config"]
    _match(inputs, {"matrix_manifest_sha256": snapshot_hashes[paths["matrix_manifest"]],
                    "selection_manifest_sha256": snapshot_hashes[paths["selection_manifest"]],
                    "evaluation_receipt_sha256": snapshot_hashes[paths["evaluation_receipt"]],
                    "planned_task_ids": frozen["planned_task_ids"]}, "Analysis manifest")
    _match(frozen["matrix_manifest"], {"generation_sha256": snapshot_hashes[paths["generation"]],
                                        "dataset_sha256": data.DATASET_SHA256}, "Matrix provenance")
    if frozen["selection_manifest"].get("labels_used") is not False:
        raise ValueError("Selection manifest does not attest that hidden labels were excluded")
    if config.get("selectors") != list(SELECTORS) or config.get("random_group_seeds") != list(RANDOM_SEEDS):
        raise ValueError("Finalization requires all five frozen selectors and all 20 fixed random seeds")
    receipt = _read(paths["evaluation_receipt"])
    _require_completed(receipt, paths["evaluation_receipt"])
    _match(receipt, {"matrix_sha256": frozen["matrix_sha256"], "config_sha256": frozen["config_sha256"],
                     "selection_sha256": frozen["selection_sha256"], "labels_sha256": snapshot_hashes[paths["labels"]],
                     "private_snapshot_sha256": data.DATASET_SHA256,
                     "planned_task_ids": frozen["planned_task_ids"]}, "Evaluation receipt")
    has_candidates = any(task["candidates"] for task in tasks)
    if has_candidates or "result_sha256" in receipt:
        result_path = run_dir / "evaluation" / "samples_eval_results.json"
        if not result_path.is_file() or receipt.get("result_sha256") != _sha(result_path):
            raise ValueError("Completed evaluation result is missing or its frozen hash differs")
        snapshot_hashes[result_path] = _sha(result_path)
    if not has_candidates and receipt.get("evaluation_mode") != "no_usable_candidates":
        raise ValueError("Empty-pool evaluation lacks its explicit completed no-candidate receipt")
    labels = _read(paths["labels"])
    selections = {row["task_id"]: row["selections"] for row in frozen["selections"]}
    if set(labels) != {task["task_id"] for task in tasks}:
        raise ValueError("Hidden labels do not cover every planned task")
    records = [{"task_id": task["task_id"], "candidates": task["candidates"], "matrix": task["matrix"],
                "labels": labels[task["task_id"]], "selections": selections[task["task_id"]]} for task in tasks]
    recomputed = summarize(records, bootstrap_replicates=config["bootstrap_replicates"], seed=config["bootstrap_seed"])
    for key in ("schema_version", "n_tasks", "pool", "selectors", "inference"):
        if summary.get(key) != recomputed[key]:
            raise ValueError(f"Summary differs from frozen-record recomputation: {key}")
    if summary.get("frozen_config") != config or summary.get("provenance") != bound:
        raise ValueError("Summary config/provenance differs from the completed input manifest")
    generation = _generation_usage(read_jsonl(paths["generation"]), tasks, config, frozen["config_sha256"])
    processes, process_hashes = _process_usage(run_dir)
    snapshot_hashes.update(process_hashes)
    metrics = _task_metrics(tasks, labels, selections)
    metric_bytes = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode() for row in metrics)
    compact = {"tasks.manifest.json": paths["matrix_manifest"].read_bytes(),
               "selections.manifest.json": paths["selection_manifest"].read_bytes(),
               "evaluation.receipt.json": paths["evaluation_receipt"].read_bytes(),
               "task_metrics.jsonl": metric_bytes}
    usage = {
        "schema_version": "tgselect-usage-v1", "status": "completed", "split": frozen["split"],
        "evidence_type": summary.get("evidence_type"), "n_tasks": len(tasks),
        "model_id": config["model_id"], "model_revision": config["model_revision"],
        "generation": generation, "processes": processes,
        "cost": {"paid_api_cost_usd": 0, "gpu_monetary_cost_usd": None,
                 "scope": "Local inference; GPU hardware, electricity, allocation and monetary costs were not estimated and are not claimed to be zero"},
        "hash_chain": "validated; summary metrics independently recomputed from frozen task/selection/label inputs",
        "source_hashes": {str(path.relative_to(run_dir)) if path.is_relative_to(run_dir) else str(path): digest
                          for path, digest in sorted(snapshot_hashes.items())},
        "compact_files": {name: {"sha256": _sha_bytes(content), "bytes": len(content)} for name, content in compact.items()},
        "privacy": "Contains aggregate usage, candidate/source/row hashes, candidate correctness labels and selected IDs; no candidate source, model response, reference or hidden input content",
    }
    outputs = {**compact, "usage.json": _bytes_json(usage)}
    # A repeat with identical evidence is idempotent; conflicting prior output
    # must remain available for review instead of being silently overwritten.
    for name, content in outputs.items():
        path = run_dir / name
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"Conflicting existing compact artifact: {path}")
    _ensure_unchanged(snapshot_hashes)
    if set(run_dir.rglob("*.process.json")) != set(process_hashes):
        raise ValueError("Process receipt set changed during finalization")
    for name, content in compact.items():
        _atomic_write(run_dir / name, content)
    _ensure_unchanged(snapshot_hashes)
    if set(run_dir.rglob("*.process.json")) != set(process_hashes):
        raise ValueError("Process receipt set changed during finalization")
    _atomic_write(run_dir / "usage.json", outputs["usage.json"])
    return {"status": "completed", "run_dir": str(run_dir), "n_tasks": len(tasks),
            "files": {name: _sha_bytes(content) for name, content in outputs.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = finalize_run(args.run_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Finalization failed: {exc}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
