"""Pinned MBPP+ snapshots and generation-only public views.

This module never executes dataset code. Only the original public prompt and
entry point reach generation; even the input contract remains private. MBPP+
does not publish a function signature in its prompt, so its original example
supplies positional arity and generic parameter names avoid inspecting the
reference implementation.
"""

from __future__ import annotations

import ast
import hashlib
import json
import keyword
import os
from collections.abc import Iterable, Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Any

EVALPLUS_VERSION = "0.3.1"
DATASET_VERSION = "v0.2.0"
# Audited directly against the official v0.2.0 release before any model output.
DATASET_SHA256 = "b54e762755248ca411b523c917fa9f93c07b5ff2966bf60b3917b853926a3dad"
ADAPTER_VERSION = "mbpp-public-v1"


class UnsupportedTask(ValueError):
    """A task does not fit the preregistered public interface adapter."""


def split_tasks(task_ids: Iterable[str], total: int = 160, pilot: int = 20) -> dict[str, str]:
    """Allocate supported task IDs before generation or hidden evaluation."""
    ids = list(task_ids)
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate task identifiers")
    if not 0 <= pilot <= total <= len(ids):
        raise ValueError("Require 0 <= pilot <= total <= number of tasks")
    ordered = sorted(
        ids,
        key=lambda task_id: (
            hashlib.sha256(f"tgselect-v1:{task_id}".encode("utf-8")).hexdigest(),
            task_id,
        ),
    )
    return {
        task_id: "e0" if i < pilot else "e1" if i < total else "heldout"
        for i, task_id in enumerate(ordered)
    }


def public_view(task: Mapping[str, Any]) -> dict[str, str]:
    """Project allowlisted fields and append a signature from public arity.

    Structural exclusions are independent of model output and hidden labels:
    prompts must consist solely of the original module docstring, and public
    assertions must reveal a consistent positional call interface.
    """
    try:
        task_id, prompt, entry = (task[k] for k in ("task_id", "prompt", "entry_point"))
    except KeyError as exc:
        raise UnsupportedTask(f"missing public field: {exc.args[0]}") from exc
    if not all(isinstance(x, str) for x in (task_id, prompt, entry)):
        raise UnsupportedTask("public fields must be strings")
    if not entry.isidentifier() or keyword.iskeyword(entry):
        raise UnsupportedTask("entry point is not a Python identifier")
    try:
        module = ast.parse(prompt)
    except SyntaxError as exc:
        raise UnsupportedTask("prompt is not a Python module docstring") from exc
    doc = ast.get_docstring(module, clean=False)
    if doc is None or len(module.body) != 1:
        raise UnsupportedTask("prompt must contain only the original module docstring")

    arities = set()
    for line in doc.splitlines():
        if not line.strip().startswith("assert "):
            continue
        try:
            assertion = ast.parse(line.strip())
        except SyntaxError as exc:
            raise UnsupportedTask("public assertion cannot be parsed") from exc
        for node in ast.walk(assertion):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == entry
            ):
                continue
            if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
                raise UnsupportedTask("public interface uses keyword or starred arguments")
            arities.add(len(node.args))
    if len(arities) != 1:
        raise UnsupportedTask("public examples do not define a consistent positional arity")
    arity = arities.pop()
    parameters = ", ".join(f"arg{i}" for i in range(arity))
    interface = (
        "\n# Required interface; placeholders retain the public example's positional order.\n"
        f"def {entry}({parameters}):\n    ...\n"
    )
    return {"task_id": task_id, "prompt": prompt + interface, "entry_point": entry}


def _load_official_snapshot():
    """Use the pinned official loader, preserving the original JSONL bytes.

    EvalPlus deserializes some hidden inputs to complex numbers or sets. Copying
    its raw cache avoids lossy reserialization and records the actual release
    content. Overrides are forbidden during initial dataset preparation.
    """
    package_version = version("evalplus")
    if package_version != EVALPLUS_VERSION:
        raise RuntimeError(f"Expected evalplus=={EVALPLUS_VERSION}; found {package_version}")
    from evalplus.data import mbpp
    from evalplus.data.utils import get_dataset_metadata

    if os.environ.get("MBPP_OVERRIDE_PATH") or mbpp.MBPP_OVERRIDE_PATH:
        raise RuntimeError("MBPP_OVERRIDE_PATH must be unset when preparing the official snapshot")
    loaded = mbpp.get_mbpp_plus(version=DATASET_VERSION)
    source_url, cache_path = get_dataset_metadata("MbppPlus", DATASET_VERSION, False, False)
    raw = Path(cache_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != DATASET_SHA256:
        raise RuntimeError("Official MBPP+ release bytes differ from the pinned SHA-256")
    official_md5 = mbpp.get_mbpp_plus_hash(version=DATASET_VERSION)
    if hashlib.md5(raw).hexdigest() != official_md5:
        raise RuntimeError("Dataset changed while loading its official snapshot")
    raw_ids = [json.loads(line)["task_id"] for line in raw.splitlines() if line.strip()]
    if set(raw_ids) != set(loaded) or len(raw_ids) != len(loaded):
        raise RuntimeError("Raw dataset and official loader disagree on task identifiers")
    return raw, {
        "package_version": package_version,
        "dataset_version": DATASET_VERSION,
        "source_url": source_url,
        "official_md5": official_md5,
    }


def prepare_dataset(output_dir: Path, total: int = 160, pilot: int = 20) -> dict:
    """Freeze an official snapshot, public projection, exclusions and hashes."""
    raw, metadata = _load_official_snapshot()
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    public = {}
    exclusions = []
    seen = set()
    for task in records:
        task_id = task["task_id"]
        if task_id in seen:
            raise ValueError(f"Duplicate task identifier: {task_id}")
        seen.add(task_id)
        try:
            public[task_id] = public_view(task)
        except UnsupportedTask as exc:
            exclusions.append({"task_id": task_id, "reason": str(exc)})
    splits = split_tasks(public, total=total, pilot=pilot)
    views = [{**public[task_id], "split": split} for task_id, split in splits.items()]
    public_raw = "".join(
        json.dumps(view, ensure_ascii=False, sort_keys=True) + "\n" for view in views
    ).encode("utf-8")

    output_dir = Path(output_dir)
    private_dir = output_dir / "private"
    private_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    (output_dir / "public").mkdir(parents=True, exist_ok=True)
    private_path = private_dir / "mbppplus.jsonl"
    private_path.write_bytes(raw)
    private_path.chmod(0o600)
    (output_dir / "public" / "views.jsonl").write_bytes(public_raw)

    manifest = {
        "dataset": "MBPP+",
        **metadata,
        "adapter_version": ADAPTER_VERSION,
        "public_fields": ["task_id", "prompt", "entry_point", "split"],
        "interface_rule": (
            "Preserve original public prompt; infer consistent positional arity only from its "
            "public assertions and append generic arg0, arg1, ... signature. Do not inspect "
            "canonical_solution, input contract, hidden inputs, tolerance or hidden labels."
        ),
        "exclusion_rule": (
            "Before sampling: missing/non-string public fields, invalid entry identifier, "
            "non-docstring-only prompt, absent/inconsistent public call arity, or keyword/starred calls. "
            "No evaluation-performance exclusions."
        ),
        "split_rule": (
            "Among structurally supported tasks, sort ascending SHA256('tgselect-v1:' + task_id), "
            "with task_id as hash-collision tiebreak; first pilot -> e0, next total-pilot -> e1, "
            "remainder -> heldout. Heldout prompts are saved but not generated in E0/E1."
        ),
        "sampling": {"total": total, "pilot": pilot},
        "counts": {
            "total": len(records), "supported": len(public), "excluded": len(exclusions),
            "e0": pilot, "e1": total - pilot, "heldout": len(public) - total,
        },
        "adapter_exclusions": sorted(exclusions, key=lambda item: item["task_id"]),
        "files": {
            name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            for name, content in (("private/mbppplus.jsonl", raw), ("public/views.jsonl", public_raw))
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
