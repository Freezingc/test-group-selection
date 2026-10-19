"""Separate visible execution, immutable selection, hidden evaluation, analysis."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import resource
import subprocess
import sys
import time

from .execution import execute_candidate, sandbox_command
from .generation import build_requests, parse_record
from .selection import select_task
from . import data


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, content):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


def _receipt(path, *, completed=True):
    try:
        content = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f'missing or invalid manifest/receipt: {path}') from exc
    if not isinstance(content, dict) or (completed and content.get('status') != 'completed'):
        raise ValueError(f'manifest/receipt is not completed: {path}')
    return content


def _check_hashes(receipt, expected, context):
    for key, actual in expected.items():
        if receipt.get(key) != actual:
            raise ValueError(f'{context} frozen hash mismatch: {key}')


def _planned_count(config, split):
    try:
        total, pilot = config['development_tasks'], config['pilot_tasks']
    except KeyError as exc:
        raise ValueError('config must predeclare development and pilot task counts') from exc
    if (not all(isinstance(value, int) and not isinstance(value, bool) for value in (total, pilot))
            or not 0 <= pilot <= total):
        raise ValueError('invalid config planned task counts')
    if split not in {'e0', 'e1'}:
        raise ValueError('matrix split must be e0 or e1')
    return pilot if split == 'e0' else total - pilot


def _unique_task_ids(rows, context):
    try:
        ids = [row['task_id'] for row in rows]
    except (KeyError, TypeError) as exc:
        raise ValueError(f'{context} missing task identifiers') from exc
    if any(not isinstance(task_id, str) for task_id in ids) or len(ids) != len(set(ids)):
        raise ValueError(f'{context} task set has invalid or duplicate identifiers')
    return ids


def validate_frozen_inputs(tasks_path, config_path, selections_path=None):
    """Validate freeze receipts, bytes, split and the predeclared denominator.

    Selection generation calls this without selections_path; hidden evaluation
    and analysis must supply the already frozen selections. Fresh hashes never
    replace a missing receipt or override any recorded hash.
    """
    config = json.loads(Path(config_path).read_text())
    tasks = read_jsonl(tasks_path)
    matrix_hash, config_hash = sha(tasks_path), sha(config_path)
    manifest_path = Path(tasks_path).with_suffix('.manifest.json')
    matrix_manifest = _receipt(manifest_path)
    _check_hashes(matrix_manifest, {'matrix_sha256': matrix_hash, 'config_sha256': config_hash}, 'matrix manifest')
    split = matrix_manifest.get('split')
    expected_n = _planned_count(config, split)
    ids = _unique_task_ids(tasks, 'matrix')
    planned = matrix_manifest.get('planned_task_ids')
    if (not isinstance(planned, list) or any(not isinstance(task_id, str) for task_id in planned)
            or len(planned) != len(set(planned)) or len(planned) != expected_n
            or len(ids) != expected_n or set(ids) != set(planned)
            or matrix_manifest.get('tasks') != expected_n):
        raise ValueError('matrix planned task set/count differs from the config denominator')
    if any(task.get('split') != split for task in tasks):
        raise ValueError('all matrix tasks must have the same frozen split')
    checked = {'tasks': tasks, 'config': config, 'split': split, 'planned_task_ids': planned,
               'matrix_sha256': matrix_hash, 'config_sha256': config_hash,
               'matrix_manifest': matrix_manifest, 'matrix_manifest_path': manifest_path}
    if selections_path is not None:
        selection_manifest_path = Path(selections_path).with_suffix('.manifest.json')
        selection_manifest = _receipt(selection_manifest_path)
        selection_hash = sha(selections_path)
        _check_hashes(selection_manifest, {'matrix_sha256': matrix_hash, 'config_sha256': config_hash,
                                           'selection_sha256': selection_hash}, 'selection manifest')
        selections = read_jsonl(selections_path)
        selection_ids = _unique_task_ids(selections, 'selection')
        if len(selection_ids) != expected_n or set(selection_ids) != set(planned):
            raise ValueError('selection planned task set/count differs from matrix/config')
        if ('planned_task_ids' in selection_manifest
                and selection_manifest['planned_task_ids'] != planned):
            raise ValueError('selection manifest planned task set differs from matrix')
        checked.update(selections=selections, selection_sha256=selection_hash,
                       selection_manifest=selection_manifest, selection_manifest_path=selection_manifest_path)
    return checked


def _validate_public_views(views_path, config):
    root = Path(views_path).parent.parent
    manifest = _receipt(root / 'manifest.json', completed=False)
    try:
        files, counts, sampling = manifest['files'], manifest['counts'], manifest['sampling']
        if (manifest['dataset'] != 'MBPP+' or manifest['dataset_version'] != data.DATASET_VERSION
                or manifest['package_version'] != data.EVALPLUS_VERSION):
            raise ValueError('dataset manifest identity differs from the pinned official dataset')
        if (files['private/mbppplus.jsonl']['sha256'] != data.DATASET_SHA256
                or sha(root / 'private' / 'mbppplus.jsonl') != data.DATASET_SHA256):
            raise ValueError('dataset manifest/private snapshot differs from the pinned official hash')
        if files['public/views.jsonl']['sha256'] != sha(views_path):
            raise ValueError('dataset manifest public view hash mismatch')
        expected_e0 = _planned_count(config, 'e0')
        expected_e1 = _planned_count(config, 'e1')
        if sampling != {'total': config['development_tasks'], 'pilot': config['pilot_tasks']}:
            raise ValueError('dataset sampling differs from config planned counts')
        views = read_jsonl(views_path)
        ids = _unique_task_ids(views, 'public views')
        actual = Counter(view['split'] for view in views)
        if (set(actual) - {'e0', 'e1', 'heldout'} or actual['e0'] != expected_e0
                or actual['e1'] != expected_e1 or counts['e0'] != expected_e0
                or counts['e1'] != expected_e1 or counts['heldout'] != actual['heldout']
                or counts['supported'] != len(views)
                or counts['total'] != counts['supported'] + counts['excluded']):
            raise ValueError('dataset manifest task counts/total differ from public views/config')
        splits = data.split_tasks(ids, total=config['development_tasks'], pilot=config['pilot_tasks'])
        if any(view['split'] != splits[view['task_id']] for view in views):
            raise ValueError('public view splits differ from the planned hash allocation')
    except (KeyError, TypeError, OSError) as exc:
        raise ValueError(f'invalid dataset manifest: {exc}') from exc
    return views, manifest


def _ensure_unchanged(paths_and_hashes):
    for path, expected in paths_and_hashes:
        if sha(path) != expected:
            raise ValueError(f'frozen input hash changed during execution: {path}')


def assemble_task(view, raw_records, config, config_hash):
    expected = build_requests([view], config['candidate_count'], config['group_count'], config['tests_per_group'])
    actual = [r for r in raw_records if r['task_id'] == view['task_id']]
    lookup = {r['request_id']: r for r in actual}
    if len(lookup) != len(actual) or set(lookup) != {r['request_id'] for r in expected}:
        raise ValueError(f"missing, unexpected or duplicate generation request for {view['task_id']}")
    parsed = []
    for request in expected:
        record = lookup[request['request_id']]
        if record['config_sha256'] != config_hash:
            raise ValueError('generation config hash differs from frozen experiment config')
        if any(record.get(key) != value for key, value in request.items()):
            raise ValueError('generation request identity/prompt drift')
        parsed.append(parse_record(record))
    candidates = [p for p in parsed if 'candidate_id' in p]
    batches = [p for p in parsed if 'generation_batch_id' in p]
    valid = [{'candidate_id': p['candidate_id'], 'source': p['source']}
             for p in candidates if p['status'] == 'usable']
    tests = [test for batch in batches for test in batch['tests']]
    return {
        'task_id': view['task_id'], 'split': view['split'], 'task_hash': hashlib.sha256(view['prompt'].encode()).hexdigest(),
        'candidates': valid, 'tests': tests, 'groups': [t['generation_batch_id'] for t in tests],
        'candidate_parse_records': candidates, 'test_batch_records': batches,
        'counts': {'requested_candidates': len(candidates), 'usable_candidates': len(valid),
                   'unique_sources': len({hashlib.sha256(c['source'].encode()).hexdigest() for c in valid}),
                   'candidate_statuses': dict(Counter(p['status'] for p in candidates)),
                   'requested_test_batches': len(batches), 'valid_tests': len(tests),
                   'test_parse_failures': sum(len(b['failures']) for b in batches)},
    }


def _execute(job):
    source, tests, timeout = job
    return execute_candidate(source, tests, per_test_timeout=timeout)


def build_matrices(views_path, generation_path, config_path, split, output_path):
    if Path(output_path).exists():
        raise ValueError('matrix output already exists; retain it and use a new run directory')
    config = json.loads(Path(config_path).read_text())
    all_views, dataset_manifest = _validate_public_views(views_path, config)
    expected_n = _planned_count(config, split)
    views = [v for v in all_views if v['split'] == split]
    if len(views) != expected_n:
        raise ValueError('public views planned task count differs from config')
    planned_ids = [view['task_id'] for view in views]
    input_hashes = [(path, sha(path)) for path in [config_path, views_path, generation_path]]
    config_hash = input_hashes[0][1]
    raw = read_jsonl(generation_path)
    if {r['task_id'] for r in raw} != {v['task_id'] for v in views}:
        raise ValueError('generation task set differs from the planned split')
    tasks = [assemble_task(v, raw, config, config_hash) for v in views]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with Path(output_path).open('w') as stream, ProcessPoolExecutor(max_workers=config['matrix_workers']) as pool:
        for index, task in enumerate(tasks):
            jobs = [(c['source'], task['tests'], config['per_test_timeout_seconds']) for c in task['candidates']]
            executions = list(pool.map(_execute, jobs))
            task['executions'] = {c['candidate_id']: execution for c, execution in zip(task['candidates'], executions, strict=True)}
            task['matrix'] = [[int(r['status'] == 'pass') for r in execution['results']] for execution in executions]
            task['execution_statuses'] = dict(Counter(r['status'] for e in executions for r in e['results']))
            stream.write(json.dumps(task, ensure_ascii=False, sort_keys=True) + '\n')
            stream.flush()
            print(json.dumps({'phase': 'matrix', 'completed': index + 1, 'total': len(tasks),
                              'task_id': task['task_id'], 'counts': task['counts'],
                              'elapsed_seconds': time.monotonic() - started}), flush=True)
    _ensure_unchanged(input_hashes)
    write_json(Path(output_path).with_suffix('.manifest.json'), {
        'status': 'completed', 'tasks': len(tasks), 'split': split, 'config_sha256': config_hash,
        'planned_task_ids': planned_ids, 'expected_n': expected_n,
        'public_views_sha256': input_hashes[1][1], 'generation_sha256': input_hashes[2][1],
        'dataset_sha256': dataset_manifest['files']['private/mbppplus.jsonl']['sha256'],
        'matrix_sha256': sha(output_path), 'seconds': time.monotonic() - started,
        'python_version': sys.version, 'sandbox': 'bubblewrap unshare-all, readonly runtime, fresh test process',
    })


def run_selection(tasks_path, config_path, output_path):
    frozen = validate_frozen_inputs(tasks_path, config_path)
    config = frozen['config']
    if Path(output_path).exists():
        raise ValueError('selection output already exists; use a new output for replay')
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(output_path).open('w') as stream:
        for task in frozen['tasks']:
            selections = {}
            for selector in config['selectors']:
                selections[selector] = select_task(task['task_id'], task['candidates'], task['matrix'], task['groups'], selector=selector)
                for seed in config['random_group_seeds']:
                    selections[f'{selector}__random_{seed}'] = select_task(
                        task['task_id'], task['candidates'], task['matrix'], task['groups'],
                        selector=selector, random_seed=seed)
            stream.write(json.dumps({'task_id': task['task_id'], 'selections': selections}, ensure_ascii=False, sort_keys=True) + '\n')
    _ensure_unchanged([(tasks_path, frozen['matrix_sha256']), (config_path, frozen['config_sha256'])])
    write_json(Path(output_path).with_suffix('.manifest.json'), {
        'status': 'completed', 'matrix_sha256': frozen['matrix_sha256'], 'config_sha256': frozen['config_sha256'],
        'planned_task_ids': frozen['planned_task_ids'],
        'selection_sha256': sha(output_path), 'labels_used': False,
    })


def read_evaluation(result, index):
    grouped = defaultdict(list)
    for row in index:
        grouped[row['task_id']].append(row)
    if set(result['eval']) != set(grouped):
        raise ValueError('hidden evaluation task set mismatch')
    labels = {}
    for task_id, rows in grouped.items():
        outcomes = result['eval'][task_id]
        if len(rows) != len(outcomes):
            raise ValueError('hidden evaluation candidate count mismatch')
        labels[task_id] = {}
        for row, outcome in zip(rows, outcomes, strict=True):
            if row['source'] != outcome['solution']:
                raise ValueError('hidden evaluation candidate source/row-order mismatch')
            if outcome['base_status'] not in {'pass', 'fail', 'timeout'} or outcome['plus_status'] not in {'pass', 'fail', 'timeout', None}:
                raise ValueError('unknown hidden evaluation status')
            labels[task_id][row['candidate_id']] = int(outcome['base_status'] == outcome['plus_status'] == 'pass')
    return labels


def _evaluation_limits(timeout_seconds):
    """Apply inherited process limits without applying host-UID NPROC limits."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('evaluation timeout must be positive and finite')
    cpu_seconds = math.ceil(timeout_seconds)

    def apply():
        resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024**2, 256 * 1024**2))
        resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
    return apply


def _hidden_job(job):
    from .evaluation import evaluate_candidate
    source, entry_point, suites, atol = job
    return evaluate_candidate(source, entry_point, suites, atol)


def _evaluate_pool(tasks, private, output_dir, timeout_seconds):
    """Trusted host supervisor, with no host result/data mounts in candidates."""
    from .evaluation import reference_suites
    from evalplus.data.mbpp import mbpp_deserialize_inputs
    problems = {p['task_id']: dict(p) for p in private}
    result = {'eval': {}}
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=8) as pool:
        for task in tasks:
            if not task['candidates']:
                continue
            if time.monotonic() - started >= timeout_seconds:
                raise subprocess.TimeoutExpired('official_kernel_pool', timeout_seconds)
            problem = problems[task['task_id']]
            for suite in ['base', 'plus']:
                problem[f'{suite}_input'] = mbpp_deserialize_inputs(problem['task_id'], problem[f'{suite}_input'])
            suites = reference_suites(problem)
            jobs = [(c['source'], problem['entry_point'], suites, problem['atol']) for c in task['candidates']]
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired('official_kernel_pool', timeout_seconds)
            try:
                outcomes = list(pool.map(_hidden_job, jobs, timeout=remaining))
            except TimeoutError as exc:
                raise subprocess.TimeoutExpired('official_kernel_pool', timeout_seconds) from exc
            if time.monotonic() - started >= timeout_seconds:
                raise subprocess.TimeoutExpired('official_kernel_pool', timeout_seconds)
            result['eval'][task['task_id']] = outcomes
            write_json(output_dir / 'partial_results.json', result)
            print(json.dumps({'phase': 'hidden_evaluation', 'task_id': task['task_id'],
                              'completed': len(result['eval']), 'total': len(problems),
                              'seconds': time.monotonic() - started}), flush=True)
    return result


def evaluate(tasks_path, snapshot_path, output_dir, timeout_seconds=1800, *, selections_path, config_path):
    frozen = validate_frozen_inputs(tasks_path, config_path, selections_path)
    limits = _evaluation_limits(timeout_seconds)
    if sha(snapshot_path) != data.DATASET_SHA256:
        raise ValueError('evaluation snapshot bytes differ from the pinned official SHA-256')
    tasks = frozen['tasks']
    task_ids = {t['task_id'] for t in tasks if t['candidates']}
    snapshot = read_jsonl(snapshot_path)
    private = [t for t in snapshot if t['task_id'] in task_ids]
    if {t['task_id'] for t in private} != task_ids:
        raise ValueError('evaluation snapshot missing planned tasks')
    index = [{'task_id': t['task_id'], **c} for t in tasks for c in t['candidates']]
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = {
        'status': 'running', 'matrix_sha256': frozen['matrix_sha256'],
        'selection_sha256': frozen['selection_sha256'], 'config_sha256': frozen['config_sha256'],
        'planned_task_ids': frozen['planned_task_ids'], 'private_snapshot_sha256': data.DATASET_SHA256,
        'correctness_definition': 'official MBPP+ base_status and plus_status both pass',
        'evaluation_mode': 'official_evalplus_0.3.1_untrusted_check_in_per_suite_bubblewrap',
        'resource_limits': {'kernel_supervisor_address_space_bytes': 8 * 1024**3,
                            'candidate_address_space_bytes': 4 * 1024**3,
                            'kernel_cpu_seconds': 75, 'kernel_wall_seconds': 80,
                            'stage_budget_seconds': timeout_seconds, 'file_size_bytes': 10 * 1024**2,
                            'nproc_enforced': True, 'nproc_namespace_limit': 64,
                            'host_result_directory_mounted': False,
                            'reference_source_mounted': False},
    }
    receipt_path = output_dir / 'receipt.json'
    write_json(receipt_path, receipt)
    failure_kind = 'evaluation_error'
    try:
        (output_dir / 'dataset.jsonl').write_text(''.join(json.dumps(t) + '\n' for t in private))
        (output_dir / 'samples.jsonl').write_text(''.join(json.dumps({'task_id': row['task_id'], 'solution': row['source']}) + '\n' for row in index))
        write_json(output_dir / 'candidate_index.json', index)
        if index:
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired('official_kernel_pool', timeout_seconds)
            results = _evaluate_pool(tasks, private, output_dir, remaining)
            if time.monotonic() - started >= timeout_seconds:
                raise subprocess.TimeoutExpired('official_kernel_pool', timeout_seconds)
            result_path = output_dir / 'samples_eval_results.json'
            write_json(result_path, results)
            labels = read_evaluation(results, index)
            receipt['result_sha256'] = sha(result_path)
        else:
            labels = {}
            receipt['evaluation_mode'] = 'no_usable_candidates'
        for task in tasks:
            labels.setdefault(task['task_id'], {})
        _ensure_unchanged([(tasks_path, frozen['matrix_sha256']), (config_path, frozen['config_sha256']),
                           (selections_path, frozen['selection_sha256']), (snapshot_path, data.DATASET_SHA256)])
        write_json(output_dir / 'labels.json', labels)
        receipt.update(status='completed', labels_sha256=sha(output_dir / 'labels.json'),
                       seconds=time.monotonic() - started)
        write_json(receipt_path, receipt)
    except Exception as exc:
        failure_kind = 'timeout' if isinstance(exc, subprocess.TimeoutExpired) else failure_kind
        receipt.update(status='failed', failure_kind=failure_kind, error=str(exc), seconds=time.monotonic() - started)
        write_json(receipt_path, receipt)
        if isinstance(exc, subprocess.TimeoutExpired):
            raise RuntimeError('EvalPlus evaluation timed out; failed receipt retained') from exc
        raise


def analyse(tasks_path, selections_path, labels_path, config_path, output_dir):
    from .analysis import summarize, render_markdown
    frozen = validate_frozen_inputs(tasks_path, config_path, selections_path)
    config, tasks = frozen['config'], frozen['tasks']
    receipt_path = Path(labels_path).parent / 'receipt.json'
    receipt = _receipt(receipt_path)
    labels_hash = sha(labels_path)
    _check_hashes(receipt, {'matrix_sha256': frozen['matrix_sha256'],
                           'selection_sha256': frozen['selection_sha256'],
                           'config_sha256': frozen['config_sha256'],
                           'labels_sha256': labels_hash,
                           'private_snapshot_sha256': data.DATASET_SHA256}, 'evaluation receipt')
    if 'planned_task_ids' in receipt and receipt['planned_task_ids'] != frozen['planned_task_ids']:
        raise ValueError('evaluation receipt planned task set differs from matrix')
    selections = {s['task_id']: s['selections'] for s in frozen['selections']}
    labels = json.loads(Path(labels_path).read_text())
    ids = {t['task_id'] for t in tasks}
    if set(selections) != ids or set(labels) != ids:
        raise ValueError('analysis requires complete aligned task sets including failed tasks')
    records = [{'task_id': t['task_id'], 'labels': labels[t['task_id']], 'selections': selections[t['task_id']],
                'candidates': t['candidates'], 'matrix': t['matrix']} for t in tasks]
    summary = summarize(records, bootstrap_replicates=config['bootstrap_replicates'], seed=config['bootstrap_seed'])
    if summary['evidence_type'] != 'synthetic_unit_fixture':
        summary['evidence_type'] = 'natural_local_generation'
    summary['frozen_config'] = config
    summary['verification'] = {'status': 'ANALYZED', 'hash_chain': 'validated', 'external_receipt': 'not_provided'}
    bound_inputs = [(tasks_path, frozen['matrix_sha256']), (selections_path, frozen['selection_sha256']),
                    (labels_path, labels_hash), (config_path, frozen['config_sha256'])]
    summary['provenance'] = {str(path): digest for path, digest in bound_inputs}
    summary['pipeline_counts'] = {
        'candidate_statuses': dict(sum((Counter(t['counts']['candidate_statuses']) for t in tasks), Counter())),
        'execution_statuses': dict(sum((Counter(t['execution_statuses']) for t in tasks), Counter())),
        'valid_tests': sum(t['counts']['valid_tests'] for t in tasks),
        'test_parse_failures': sum(t['counts']['test_parse_failures'] for t in tasks),
    }
    _ensure_unchanged(bound_inputs)
    write_json(Path(output_dir) / 'summary.json', summary)
    (Path(output_dir) / 'results.md').write_text(render_markdown(summary, stage=frozen['split']))
    write_json(Path(output_dir) / 'inputs.manifest.json', {
        'status': 'completed', 'inputs': summary['provenance'],
        'matrix_manifest_sha256': sha(frozen['matrix_manifest_path']),
        'selection_manifest_sha256': sha(frozen['selection_manifest_path']),
        'evaluation_receipt_sha256': sha(receipt_path), 'planned_task_ids': frozen['planned_task_ids'],
    })


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='phase', required=True)
    p = commands.add_parser('matrix')
    for key in ['views', 'generation', 'config', 'output']:
        p.add_argument('--' + key, type=Path, required=True)
    p.add_argument('--split', choices=['e0', 'e1'], required=True)
    p = commands.add_parser('select')
    for key in ['tasks', 'config', 'output']:
        p.add_argument('--' + key, type=Path, required=True)
    p = commands.add_parser('evaluate')
    for key in ['tasks', 'snapshot', 'selections', 'config', 'output_dir']:
        p.add_argument('--' + key.replace('_', '-'), type=Path, required=True)
    p.add_argument('--timeout', type=int, default=1800)
    p = commands.add_parser('analyse')
    for key in ['tasks', 'selections', 'labels', 'config', 'output_dir']:
        p.add_argument('--' + key.replace('_', '-'), type=Path, required=True)
    args = parser.parse_args()
    if args.phase == 'matrix':
        build_matrices(args.views, args.generation, args.config, args.split, args.output)
    elif args.phase == 'select':
        run_selection(args.tasks, args.config, args.output)
    elif args.phase == 'evaluate':
        evaluate(args.tasks, args.snapshot, args.output_dir, args.timeout,
                 selections_path=args.selections, config_path=args.config)
    else:
        analyse(args.tasks, args.selections, args.labels, args.config, args.output_dir)


if __name__ == '__main__':
    main()
