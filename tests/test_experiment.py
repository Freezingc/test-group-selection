import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tgselect.experiment import assemble_task, read_evaluation
from tgselect.generation import build_requests
from tgselect import data, experiment


def raw_fixture():
    view = {'task_id': 'Mbpp/1', 'prompt': 'Double x.', 'entry_point': 'twice', 'split': 'e0'}
    requests = build_requests([view], candidate_count=2, group_count=2, tests_per_group=1)
    records = [{**r, 'config_sha256': 'frozen', 'finish_reason': 'stop',
                'response': 'def twice(x): return 2*x' if r['kind'] == 'candidate'
                else '["assert twice(2) == 99"]'} for r in requests]
    config = {'candidate_count': 2, 'group_count': 2, 'tests_per_group': 1}
    return view, records, config


def test_assemble_frozen_requests_does_not_gold_filter_tests():
    view, raw, config = raw_fixture()
    result = assemble_task(view, raw, config, 'frozen')
    assert len(result['candidates']) == 2
    assert len(result['tests']) == 2
    assert result['tests'][0]['assertion'].endswith('== 99')
    assert result['groups'] == ['Mbpp/1/tests/00', 'Mbpp/1/tests/01']


def test_incomplete_or_duplicate_generation_is_not_an_empty_candidate_pool():
    view, raw, config = raw_fixture()
    with pytest.raises(ValueError, match='request'):
        assemble_task(view, raw[:-1], config, 'frozen')
    with pytest.raises(ValueError, match='request'):
        assemble_task(view, raw + [raw[0]], config, 'frozen')


def test_config_drift_refuses_analysis():
    view, raw, config = raw_fixture()
    with pytest.raises(ValueError, match='config'):
        assemble_task(view, raw, config, 'different')


def test_all_truncated_candidates_remain_as_a_planned_failed_task():
    view, raw, config = raw_fixture()
    for r in raw:
        if r['kind'] == 'candidate':
            r['finish_reason'] = 'length'
    result = assemble_task(view, raw, config, 'frozen')
    assert result['candidates'] == []
    assert result['counts']['requested_candidates'] == 2
    assert result['counts']['candidate_statuses'] == {'truncated': 2}


def test_hidden_labels_are_bound_to_candidate_source_and_row_order():
    index = [{'task_id': 'Mbpp/1', 'candidate_id': 'c0', 'source': 'def f(): return 1'}]
    results = {'eval': {'Mbpp/1': [{'solution': 'def f(): return 1',
                                   'base_status': 'pass', 'plus_status': 'fail'}]}}
    assert read_evaluation(results, index) == {'Mbpp/1': {'c0': 0}}
    results['eval']['Mbpp/1'][0]['solution'] = 'def f(): return 2'
    with pytest.raises(ValueError, match='source'):
        read_evaluation(results, index)


def dump_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(record, sort_keys=True) + '\n' for record in records))


@pytest.fixture
def frozen_run(tmp_path, monkeypatch):
    config = {'development_tasks': 2, 'pilot_tasks': 2, 'selectors': list(experiment.select_task.__globals__['SELECTORS']),
              'random_group_seeds': list(range(20)), 'bootstrap_replicates': 10, 'bootstrap_seed': 7,
              'model_id': 'local/test-model', 'model_revision': 'fixed-revision',
              'candidate_count': 1, 'group_count': 1, 'tests_per_group': 1,
              'matrix_workers': 1, 'per_test_timeout_seconds': 0.1}
    config_path = tmp_path / 'config.json'
    experiment.write_json(config_path, config)
    tasks = [{'task_id': f'Mbpp/{i}', 'split': 'e0',
              'candidates': [{'candidate_id': 'c0', 'source': f'def f(x): return x + {i}'}],
              'tests': [], 'groups': ['g'], 'matrix': [[1]],
              'counts': {'candidate_statuses': {'usable': 1}, 'valid_tests': 1, 'test_parse_failures': 0},
              'execution_statuses': {'pass': 1}} for i in (1, 2)]
    tasks_path = tmp_path / 'tasks.jsonl'
    dump_jsonl(tasks_path, tasks)
    planned = [task['task_id'] for task in tasks]
    matrix_manifest = {'status': 'completed', 'tasks': 2, 'split': 'e0',
                       'planned_task_ids': planned, 'matrix_sha256': experiment.sha(tasks_path),
                       'config_sha256': experiment.sha(config_path)}
    experiment.write_json(tasks_path.with_suffix('.manifest.json'), matrix_manifest)
    selections_path = tmp_path / 'selections.jsonl'
    experiment.run_selection(tasks_path, config_path, selections_path)
    labels_path = tmp_path / 'evaluation' / 'labels.json'
    experiment.write_json(labels_path, {task_id: {'c0': 1} for task_id in planned})
    snapshot_path = tmp_path / 'snapshot.jsonl'
    dump_jsonl(snapshot_path, [{'task_id': task_id, 'canonical_solution': 'private'} for task_id in planned]
               + [{'task_id': 'Mbpp/heldout', 'canonical_solution': 'private'}])
    monkeypatch.setattr(data, 'DATASET_SHA256', experiment.sha(snapshot_path))
    receipt = {'status': 'completed', 'matrix_sha256': experiment.sha(tasks_path),
               'selection_sha256': experiment.sha(selections_path),
               'config_sha256': experiment.sha(config_path),
               'labels_sha256': experiment.sha(labels_path),
               'private_snapshot_sha256': experiment.sha(snapshot_path)}
    experiment.write_json(labels_path.parent / 'receipt.json', receipt)
    return SimpleNamespace(root=tmp_path, config=config, config_path=config_path,
                           tasks=tasks, tasks_path=tasks_path, selections_path=selections_path,
                           labels_path=labels_path, snapshot_path=snapshot_path, planned=planned)


def test_frozen_inputs_accept_complete_hash_bound_run(frozen_run):
    run = frozen_run
    checked = experiment.validate_frozen_inputs(run.tasks_path, run.config_path, run.selections_path)
    assert checked['planned_task_ids'] == run.planned
    assert checked['matrix_sha256'] == experiment.sha(run.tasks_path)
    assert checked['selection_sha256'] == experiment.sha(run.selections_path)


@pytest.mark.parametrize('changed', ['matrix', 'source', 'selection', 'config', 'labels'])
def test_analysis_rejects_changed_bytes_even_when_task_ids_still_align(frozen_run, changed):
    run = frozen_run
    if changed in {'matrix', 'source'}:
        tasks = json.loads(json.dumps(run.tasks))
        if changed == 'matrix':
            tasks[0]['matrix'][0][0] = 0
        else:
            tasks[0]['candidates'][0]['source'] = 'def f(x): return 999'
        dump_jsonl(run.tasks_path, tasks)
    elif changed == 'selection':
        run.selections_path.write_text(run.selections_path.read_text() + '\n')
    elif changed == 'config':
        experiment.write_json(run.config_path, {**run.config, 'model_revision': 'changed'})
    else:
        experiment.write_json(run.labels_path, {task_id: {'c0': 0} for task_id in run.planned})
    with pytest.raises(ValueError, match='hash|SHA|sha|frozen|receipt'):
        experiment.analyse(run.tasks_path, run.selections_path, run.labels_path, run.config_path,
                           run.root / 'analysis')
    assert not (run.root / 'analysis' / 'summary.json').exists()


@pytest.mark.parametrize('phase', ['select', 'evaluate', 'analyse'])
def test_aligned_but_shrunk_task_sets_cannot_change_planned_denominator(frozen_run, phase):
    run = frozen_run
    dump_jsonl(run.tasks_path, run.tasks[:1])
    manifest_path = run.tasks_path.with_suffix('.manifest.json')
    manifest = json.loads(manifest_path.read_text())
    manifest.update(matrix_sha256=experiment.sha(run.tasks_path), planned_task_ids=run.planned[:1], tasks=1)
    experiment.write_json(manifest_path, manifest)
    # Keep downstream files mutually aligned too: config still declares N=2.
    rows = experiment.read_jsonl(run.selections_path)[:1]
    dump_jsonl(run.selections_path, rows)
    selection_manifest_path = run.selections_path.with_suffix('.manifest.json')
    selection_manifest = json.loads(selection_manifest_path.read_text())
    selection_manifest.update(matrix_sha256=experiment.sha(run.tasks_path),
                              selection_sha256=experiment.sha(run.selections_path))
    experiment.write_json(selection_manifest_path, selection_manifest)
    experiment.write_json(run.labels_path, {run.planned[0]: {'c0': 1}})
    receipt_path = run.labels_path.parent / 'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt.update(matrix_sha256=experiment.sha(run.tasks_path), selection_sha256=experiment.sha(run.selections_path),
                   labels_sha256=experiment.sha(run.labels_path))
    experiment.write_json(receipt_path, receipt)
    with pytest.raises(ValueError, match='planned|count|denominator|task set'):
        if phase == 'select':
            experiment.run_selection(run.tasks_path, run.config_path, run.root / 'new-selection.jsonl')
        elif phase == 'evaluate':
            experiment.evaluate(run.tasks_path, run.snapshot_path, run.root / 'new-evaluation',
                                selections_path=run.selections_path, config_path=run.config_path)
        else:
            experiment.analyse(run.tasks_path, run.selections_path, run.labels_path, run.config_path,
                               run.root / 'analysis')


def test_matrix_must_have_one_split_matching_its_manifest(frozen_run):
    run = frozen_run
    run.tasks[1]['split'] = 'e1'
    dump_jsonl(run.tasks_path, run.tasks)
    manifest_path = run.tasks_path.with_suffix('.manifest.json')
    manifest = json.loads(manifest_path.read_text())
    manifest['matrix_sha256'] = experiment.sha(run.tasks_path)
    experiment.write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match='split'):
        experiment.validate_frozen_inputs(run.tasks_path, run.config_path)


@pytest.mark.parametrize('missing', ['matrix', 'selection', 'evaluation'])
def test_missing_freeze_or_evaluation_receipt_cannot_be_replaced_with_fresh_hashes(frozen_run, missing):
    run = frozen_run
    {'matrix': run.tasks_path.with_suffix('.manifest.json'),
     'selection': run.selections_path.with_suffix('.manifest.json'),
     'evaluation': run.labels_path.parent / 'receipt.json'}[missing].unlink()
    with pytest.raises(ValueError, match='manifest|receipt'):
        experiment.analyse(run.tasks_path, run.selections_path, run.labels_path, run.config_path,
                           run.root / 'analysis')


@pytest.mark.parametrize('status', ['running', 'failed', 'crashed'])
def test_incomplete_evaluation_receipts_are_never_analysed(frozen_run, status):
    run = frozen_run
    receipt_path = run.labels_path.parent / 'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['status'] = status
    experiment.write_json(receipt_path, receipt)
    with pytest.raises(ValueError, match='completed|receipt'):
        experiment.analyse(run.tasks_path, run.selections_path, run.labels_path, run.config_path,
                           run.root / 'analysis')


def test_analysis_marks_natural_lineage_but_does_not_claim_external_verification(frozen_run):
    run = frozen_run
    output = run.root / 'analysis'
    experiment.analyse(run.tasks_path, run.selections_path, run.labels_path, run.config_path, output)
    summary = json.loads((output / 'summary.json').read_text())
    assert summary['evidence_type'] == 'natural_local_generation'
    assert summary['frozen_config'] == run.config
    assert summary['verification']['status'] == 'ANALYZED'
    assert summary['verification']['external_receipt'] == 'not_provided'
    assert 'VERIFIED' not in (output / 'results.md').read_text()


def test_evaluation_requires_selection_and_config_before_starting(frozen_run):
    run = frozen_run
    with pytest.raises(TypeError):
        experiment.evaluate(run.tasks_path, run.snapshot_path, run.root / 'new-evaluation')
    assert not (run.root / 'new-evaluation').exists()


def test_evaluation_rejects_unpinned_snapshot_before_starting(frozen_run):
    run = frozen_run
    run.snapshot_path.write_text(run.snapshot_path.read_text() + '\n')
    with pytest.raises(ValueError, match='snapshot|pinned|SHA'):
        experiment.evaluate(run.tasks_path, run.snapshot_path, run.root / 'new-evaluation',
                            selections_path=run.selections_path, config_path=run.config_path)
    assert not (run.root / 'new-evaluation').exists()


def test_evaluation_timeout_leaves_failed_bound_receipt(frozen_run, monkeypatch):
    run = frozen_run
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('official_kernel_pool', 3)
    monkeypatch.setattr(experiment, '_evaluate_pool', timeout)
    output = run.root / 'new-evaluation'
    with pytest.raises(RuntimeError, match='timeout|timed out'):
        experiment.evaluate(run.tasks_path, run.snapshot_path, output, timeout_seconds=3,
                            selections_path=run.selections_path, config_path=run.config_path)
    receipt = json.loads((output / 'receipt.json').read_text())
    assert receipt['status'] == 'failed'
    assert receipt['failure_kind'] == 'timeout'
    assert receipt['matrix_sha256'] == experiment.sha(run.tasks_path)
    assert receipt['selection_sha256'] == experiment.sha(run.selections_path)
    assert receipt['config_sha256'] == experiment.sha(run.config_path)
    assert not (output / 'labels.json').exists()


def test_successful_evaluation_receipt_binds_frozen_inputs_and_exact_labels(frozen_run, monkeypatch):
    run = frozen_run
    output = run.root / 'new-evaluation'
    def evaluator(*args, **kwargs):
        index = json.loads((output / 'candidate_index.json').read_text())
        results = {'eval': {task_id: [{'solution': row['source'], 'base_status': 'pass', 'plus_status': 'pass'}
                                     for row in index if row['task_id'] == task_id] for task_id in run.planned}}
        return results
    monkeypatch.setattr(experiment, '_evaluate_pool', evaluator)
    experiment.evaluate(run.tasks_path, run.snapshot_path, output,
                        selections_path=run.selections_path, config_path=run.config_path)
    receipt = json.loads((output / 'receipt.json').read_text())
    assert receipt['status'] == 'completed'
    for key, path in [('matrix_sha256', run.tasks_path), ('selection_sha256', run.selections_path),
                      ('config_sha256', run.config_path), ('labels_sha256', output / 'labels.json')]:
        assert receipt[key] == experiment.sha(path)
    assert {r['task_id'] for r in experiment.read_jsonl(output / 'dataset.jsonl')} == set(run.planned)
    assert receipt['resource_limits']['candidate_address_space_bytes'] == 4 * 1024**3
    assert receipt['resource_limits']['file_size_bytes'] == 10 * 1024**2
    assert receipt['resource_limits']['nproc_enforced'] is True
    assert receipt['resource_limits']['host_result_directory_mounted'] is False
    assert receipt['resource_limits']['reference_source_mounted'] is False


def test_final_task_over_budget_cannot_be_published_as_completed(frozen_run, monkeypatch):
    run = frozen_run
    output = run.root / 'late-evaluation'
    clock = [0.0]
    monkeypatch.setattr(experiment.time, 'monotonic', lambda: clock[0])
    def evaluator(*args, **kwargs):
        index = json.loads((output / 'candidate_index.json').read_text())
        clock[0] = 4.0
        return {'eval': {task_id: [
            {'solution': row['source'], 'base_status': 'pass', 'plus_status': 'pass'}
            for row in index if row['task_id'] == task_id] for task_id in run.planned}}
    monkeypatch.setattr(experiment, '_evaluate_pool', evaluator)
    with pytest.raises(RuntimeError, match='timed out'):
        experiment.evaluate(run.tasks_path, run.snapshot_path, output, timeout_seconds=3,
                            selections_path=run.selections_path, config_path=run.config_path)
    assert json.loads((output / 'receipt.json').read_text())['status'] == 'failed'
    assert not (output / 'labels.json').exists()


def test_evaluation_limits_apply_in_child_without_changing_parent():
    before = resource.getrlimit(resource.RLIMIT_AS)
    proc = subprocess.run([sys.executable, '-c',
                           'import json,resource;print(json.dumps([resource.getrlimit(x) for x in '
                           '(resource.RLIMIT_AS,resource.RLIMIT_CPU,resource.RLIMIT_FSIZE)]))'],
                          preexec_fn=experiment._evaluation_limits(7), capture_output=True, text=True, check=True)
    assert json.loads(proc.stdout) == [[16 * 1024**3] * 2, [7] * 2, [256 * 1024**2] * 2]
    assert resource.getrlimit(resource.RLIMIT_AS) == before


@pytest.fixture
def prepared_views(tmp_path, monkeypatch):
    root = tmp_path / 'data'
    views_path = root / 'public' / 'views.jsonl'
    ids = ['Mbpp/1', 'Mbpp/2', 'Mbpp/3']
    splits = data.split_tasks(ids, total=2, pilot=1)
    views = [{'task_id': task_id, 'split': splits[task_id], 'prompt': 'Double x.', 'entry_point': 'twice'}
             for task_id in ids]
    dump_jsonl(views_path, views)
    private_path = root / 'private' / 'mbppplus.jsonl'
    dump_jsonl(private_path, [{'task_id': task_id} for task_id in ids])
    monkeypatch.setattr(data, 'DATASET_SHA256', experiment.sha(private_path))
    manifest = {'dataset': 'MBPP+', 'dataset_version': data.DATASET_VERSION,
                'package_version': data.EVALPLUS_VERSION, 'sampling': {'total': 2, 'pilot': 1},
                'counts': {'total': 3, 'supported': 3, 'excluded': 0, 'e0': 1, 'e1': 1, 'heldout': 1},
                'files': {'public/views.jsonl': {'sha256': experiment.sha(views_path)},
                          'private/mbppplus.jsonl': {'sha256': experiment.sha(private_path)}}}
    experiment.write_json(root / 'manifest.json', manifest)
    config_path = tmp_path / 'config.json'
    config = {'development_tasks': 2, 'pilot_tasks': 1, 'candidate_count': 2,
              'group_count': 2, 'tests_per_group': 1, 'matrix_workers': 1, 'per_test_timeout_seconds': 0.1}
    experiment.write_json(config_path, config)
    raw = []
    for view in views:
        if view['split'] != 'e0':
            continue
        raw += [{**request, 'config_sha256': experiment.sha(config_path), 'finish_reason': 'stop',
                 'response': 'def twice(x): return 2*x' if request['kind'] == 'candidate'
                 else '["assert twice(2) == 4"]'}
                for request in build_requests([view], candidate_count=2, group_count=2, tests_per_group=1)]
    raw_path = tmp_path / 'generation.jsonl'
    dump_jsonl(raw_path, raw)
    return SimpleNamespace(root=root, views_path=views_path, views=views, config_path=config_path,
                           raw_path=raw_path, manifest=manifest)


@pytest.mark.parametrize('tamper', ['public_hash', 'official_hash', 'sampling', 'counts', 'total'])
def test_build_matrices_rejects_unverified_dataset_or_unplanned_counts(prepared_views, tamper, tmp_path):
    run = prepared_views
    if tamper == 'public_hash':
        run.views_path.write_text(run.views_path.read_text() + '\n')
    elif tamper == 'official_hash':
        run.manifest['files']['private/mbppplus.jsonl']['sha256'] = '0' * 64
    elif tamper == 'sampling':
        run.manifest['sampling']['pilot'] = 2
    elif tamper == 'counts':
        run.manifest['counts']['e0'] = 0
    else:
        run.manifest['counts']['total'] = 2
    experiment.write_json(run.root / 'manifest.json', run.manifest)
    with pytest.raises(ValueError, match='manifest|hash|pinned|sampling|count|total'):
        experiment.build_matrices(run.views_path, run.raw_path, run.config_path, 'e0', tmp_path / 'matrix.jsonl')
    assert not (tmp_path / 'matrix.jsonl').exists()
