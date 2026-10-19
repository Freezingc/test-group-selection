"""Archive evidence must restore to portable paths without overwriting itself."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile

import pytest


@pytest.fixture
def packager(monkeypatch, tmp_path):
    source = Path(__file__).resolve().parents[1] / 'scripts/package_raw.py'
    spec = importlib.util.spec_from_file_location('package_raw', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'validate_frozen_inputs', lambda *args: None)
    monkeypatch.chdir(tmp_path)
    run = tmp_path / 'artifacts/runs/e0-v1'
    relative_files = ['raw/generation.jsonl', 'raw/tasks.jsonl', 'raw/tasks.manifest.json',
                      'raw/selections.jsonl', 'raw/selections.manifest.json',
                      'evaluation/labels.json', 'evaluation/receipt.json',
                      'evaluation/samples_eval_results.json']
    hashes = {}
    for relative in relative_files:
        path = run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (json.dumps({'file': relative}) + '\n').encode()
        path.write_bytes(content)
        hashes[relative] = hashlib.sha256(content).hexdigest()
    (run / 'usage.json').write_text(json.dumps({'status': 'completed', 'source_hashes': hashes}))
    return module, run


def invoke(module, monkeypatch, run, output, manifest):
    monkeypatch.setattr(sys, 'argv', ['package_raw.py', '--runs', str(run),
                                     '--output', str(output), '--manifest', str(manifest)])
    module.main()


def test_archive_and_manifest_cannot_resolve_to_same_path(packager, monkeypatch, tmp_path):
    module, run = packager
    output = tmp_path / 'colliding.tar.gz'
    with pytest.raises(SystemExit):
        invoke(module, monkeypatch, run, output, output)
    assert not output.exists()


def test_absolute_run_path_produces_portable_members(packager, monkeypatch, tmp_path):
    module, run = packager
    output, manifest = tmp_path / 'raw.tar.gz', tmp_path / 'raw.manifest.json'
    invoke(module, monkeypatch, run, output, manifest)
    with tarfile.open(output) as archive:
        names = archive.getnames()
    assert all(name.startswith('artifacts/runs/e0-v1/') for name in names)
    assert all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in names)
    record = json.loads(manifest.read_text())
    assert [item['path'] for item in record['files']] == names


def test_relative_and_absolute_runs_have_identical_archive_bytes(packager, monkeypatch, tmp_path):
    module, run = packager
    first, second = tmp_path / 'first.tar.gz', tmp_path / 'second.tar.gz'
    invoke(module, monkeypatch, run.relative_to(tmp_path), first, tmp_path / 'first.json')
    invoke(module, monkeypatch, run, second, tmp_path / 'second.json')
    assert first.read_bytes() == second.read_bytes()
