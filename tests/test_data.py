"""Dataset isolation and deterministic task allocation, without network access."""

import hashlib
import json
import sys
import types

import pytest

from tgselect import data


def task(task_id="Mbpp/2"):
    return {
        "task_id": task_id,
        "prompt": '"""\nFind shared items.\nassert shared((1, 2), (2, 3)) == (2,)\n"""\n',
        "entry_point": "shared",
        "canonical_solution": "PRIVATE_REFERENCE_SENTINEL",
        "base_input": [["PRIVATE_BASE_SENTINEL"]],
        "plus_input": [["PRIVATE_PLUS_SENTINEL"]],
        "contract": "\n  assert isinstance(left, tuple)\n  assert isinstance(right, tuple)\n",
        "atol": 0.123456789,
        "assertion": "PRIVATE_ASSERTION_SENTINEL",
    }


def test_split_uses_task_hash_and_is_independent_of_input_order():
    ids = [f"Mbpp/{i}" for i in range(220)]
    expected = sorted(ids, key=lambda x: hashlib.sha256(f"tgselect-v1:{x}".encode()).hexdigest())
    split = data.split_tasks(ids)
    assert split == data.split_tasks(reversed(ids))
    assert {i for i, s in split.items() if s == "e0"} == set(expected[:20])
    assert {i for i, s in split.items() if s == "e1"} == set(expected[20:160])
    assert {i for i, s in split.items() if s == "heldout"} == set(expected[160:])


@pytest.mark.parametrize("total,pilot", [(3, 4), (-1, 0), (1, -1), (5, 1)])
def test_split_rejects_impossible_counts(total, pilot):
    with pytest.raises(ValueError):
        data.split_tasks(["Mbpp/1", "Mbpp/2"], total, pilot)


def test_duplicate_identifiers_are_rejected_before_sampling():
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        data.split_tasks(["Mbpp/1", "Mbpp/1"], total=1, pilot=0)


def test_public_view_preserves_original_example_and_adds_positional_interface():
    source = task()
    view = data.public_view(source)
    assert set(view) == {"task_id", "prompt", "entry_point"}
    assert source["prompt"] in view["prompt"]
    assert "def shared(arg0, arg1):" in view["prompt"]
    assert "PRIVATE_" not in json.dumps(view)
    assert "atol" not in json.dumps(view)
    assert "isinstance" not in view["prompt"]


def test_public_view_does_not_read_private_reference_or_hidden_inputs():
    # The generation view must work from the allowlisted public fields alone.
    source = task()
    visible = {k: source[k] for k in ("task_id", "prompt", "entry_point")}
    assert data.public_view(visible) == data.public_view(source)


@pytest.mark.parametrize("prompt", [
    '"""A task with no public function call."""\n',
    '"""A task.\nassert shared(*xs) == 1\n"""\n',
    '"""A task.\nassert shared(1) == 1\nassert shared(1, 2) == 2\n"""\n',
    '"""A task.\nassert shared(1) == 1\n"""\nsecret = "executable"\n',
])
def test_unsupported_public_interfaces_are_explicit_structural_exclusions(prompt):
    source = task()
    source["prompt"] = prompt
    with pytest.raises(data.UnsupportedTask):
        data.public_view(source)


def test_prepare_writes_full_private_snapshot_separate_from_public_and_hashes(tmp_path, monkeypatch):
    records = [task(f"Mbpp/{i}") for i in range(5)]
    unsupported = task("Mbpp/unsupported")
    unsupported["prompt"] = '"""No visible call."""\n'
    records.append(unsupported)
    raw = b"".join((json.dumps(record) + "\n").encode() for record in records)
    monkeypatch.setattr(data, "_load_official_snapshot", lambda: (raw, {
        "package_version": "0.3.1", "dataset_version": "v0.2.0",
        "source_url": "https://github.com/evalplus/mbppplus_release/releases/download/v0.2.0/MbppPlus.jsonl.gz",
        "official_md5": hashlib.md5(raw).hexdigest(),
    }))
    manifest = data.prepare_dataset(tmp_path, total=3, pilot=1)
    private = tmp_path / "private" / "mbppplus.jsonl"
    public = tmp_path / "public" / "views.jsonl"
    assert private.read_bytes() == raw
    views = [json.loads(line) for line in public.read_text().splitlines()]
    assert len(views) == 5
    assert {v["split"] for v in views} == {"e0", "e1", "heldout"}
    assert "PRIVATE_" not in public.read_text()
    assert all(set(v) == {"task_id", "prompt", "entry_point", "split"} for v in views)
    assert manifest["files"]["private/mbppplus.jsonl"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert manifest["files"]["public/views.jsonl"]["sha256"] == hashlib.sha256(public.read_bytes()).hexdigest()
    assert manifest["counts"] == {"total": 6, "supported": 5, "excluded": 1, "e0": 1, "e1": 2, "heldout": 2}
    assert manifest["adapter_exclusions"][0]["task_id"] == "Mbpp/unsupported"
    assert json.loads((tmp_path / "manifest.json").read_text()) == manifest


def test_official_loader_rejects_an_unpinned_evalplus_package(monkeypatch):
    monkeypatch.setattr(data, "version", lambda name: "0.3.0")
    with pytest.raises(RuntimeError, match="Expected evalplus==0.3.1"):
        data._load_official_snapshot()


def fake_official_loader(tmp_path, monkeypatch):
    raw = (json.dumps(task()) + "\n").encode()
    cache_path = tmp_path / "cache.jsonl"
    cache_path.write_bytes(raw)
    package = types.ModuleType("evalplus.data")
    package.mbpp = types.SimpleNamespace(
        MBPP_OVERRIDE_PATH=None,
        get_mbpp_plus=lambda **kwargs: {"Mbpp/2": task()},
        get_mbpp_plus_hash=lambda **kwargs: hashlib.md5(raw).hexdigest(),
    )
    utils = types.ModuleType("evalplus.data.utils")
    utils.get_dataset_metadata = lambda *args: ("https://github.com/evalplus/official", cache_path)
    monkeypatch.setitem(sys.modules, "evalplus.data", package)
    monkeypatch.setitem(sys.modules, "evalplus.data.utils", utils)
    monkeypatch.setattr(data, "version", lambda name: "0.3.1")
    monkeypatch.delenv("MBPP_OVERRIDE_PATH", raising=False)


def test_official_loader_rejects_custom_data_override(tmp_path, monkeypatch):
    fake_official_loader(tmp_path, monkeypatch)
    monkeypatch.setenv("MBPP_OVERRIDE_PATH", "/tmp/custom.jsonl")
    with pytest.raises(RuntimeError, match="MBPP_OVERRIDE_PATH"):
        data._load_official_snapshot()


def test_official_loader_rejects_changed_release_bytes_even_if_local_md5_agrees(tmp_path, monkeypatch):
    fake_official_loader(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="SHA-256"):
        data._load_official_snapshot()
