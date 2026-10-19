"""Separate visible execution, immutable selection, hidden evaluation, analysis."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

from .execution import execute_candidate, sandbox_command
from .generation import build_requests, parse_record
from .selection import select_task


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, content):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


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
    views = [v for v in read_jsonl(views_path) if v['split'] == split]
    raw = read_jsonl(generation_path)
    if {r['task_id'] for r in raw} != {v['task_id'] for v in views}:
        raise ValueError('generation task set differs from the planned split')
    tasks = [assemble_task(v, raw, config, sha(config_path)) for v in views]
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
    write_json(Path(output_path).with_suffix('.manifest.json'), {
        'status': 'completed', 'tasks': len(tasks), 'split': split, 'config_sha256': sha(config_path),
        'public_views_sha256': sha(views_path), 'generation_sha256': sha(generation_path),
        'matrix_sha256': sha(output_path), 'seconds': time.monotonic() - started,
        'python_version': sys.version, 'sandbox': 'bubblewrap unshare-all, readonly runtime, fresh test process',
    })


def run_selection(tasks_path, config_path, output_path):
    config = json.loads(Path(config_path).read_text())
    if Path(output_path).exists():
        raise ValueError('selection output already exists; use a new output for replay')
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(output_path).open('w') as stream:
        for task in read_jsonl(tasks_path):
            selections = {}
            for selector in config['selectors']:
                selections[selector] = select_task(task['task_id'], task['candidates'], task['matrix'], task['groups'], selector=selector)
                for seed in config['random_group_seeds']:
                    selections[f'{selector}__random_{seed}'] = select_task(
                        task['task_id'], task['candidates'], task['matrix'], task['groups'],
                        selector=selector, random_seed=seed)
            stream.write(json.dumps({'task_id': task['task_id'], 'selections': selections}, ensure_ascii=False, sort_keys=True) + '\n')
    write_json(Path(output_path).with_suffix('.manifest.json'), {
        'status': 'completed', 'matrix_sha256': sha(tasks_path), 'config_sha256': sha(config_path),
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


def evaluate(tasks_path, snapshot_path, output_dir, timeout_seconds=1800):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    tasks = read_jsonl(tasks_path)
    task_ids = {t['task_id'] for t in tasks if t['candidates']}
    snapshot = read_jsonl(snapshot_path)
    private = [t for t in snapshot if t['task_id'] in task_ids]
    if {t['task_id'] for t in private} != task_ids:
        raise ValueError('evaluation snapshot missing planned tasks')
    index = [{'task_id': t['task_id'], **c} for t in tasks for c in t['candidates']]
    (output_dir / 'dataset.jsonl').write_text(''.join(json.dumps(t) + '\n' for t in private))
    (output_dir / 'samples.jsonl').write_text(''.join(json.dumps({'task_id': row['task_id'], 'solution': row['source']}) + '\n' for row in index))
    write_json(output_dir / 'candidate_index.json', index)
    if not index:
        write_json(output_dir / 'labels.json', {t['task_id']: {} for t in tasks})
        return
    runtime_prefix = str(Path(sys.base_prefix).resolve())
    venv_prefix = str(Path(sys.prefix).resolve())
    source_prefix = str(Path(__file__).resolve().parents[1])
    interpreter = str(Path(sys.executable).absolute())
    cmd = sandbox_command(
        readonly={runtime_prefix: runtime_prefix, venv_prefix: venv_prefix, source_prefix: source_prefix},
        writable={str(output_dir): '/work/evaluation'}, python=interpreter,
        extra_env={'MBPP_OVERRIDE_PATH': '/work/evaluation/dataset.jsonl', 'EVALPLUS_CACHE_DIR': '/tmp/evalplus'},
        arguments=['-m', 'evalplus.evaluate', '--dataset', 'mbpp', '--version', 'v0.2.0',
                   '--samples', '/work/evaluation/samples.jsonl', '--parallel', '8',
                   '--min_time_limit', '1.0', '--gt_time_limit_factor', '4.0'])
    started = time.monotonic()
    with (output_dir / 'stdout.log').open('w') as stdout, (output_dir / 'stderr.log').open('w') as stderr:
        proc = subprocess.run(cmd, stdout=stdout, stderr=stderr, timeout=timeout_seconds)
    if proc.returncode:
        write_json(output_dir / 'receipt.json', {'status': 'crashed', 'exit_code': proc.returncode,
                                                'command': cmd, 'seconds': time.monotonic() - started})
        raise RuntimeError(f'EvalPlus failed; inspect {output_dir}/stderr.log; no labels were inferred')
    result_path = output_dir / 'samples_eval_results.json'
    labels = read_evaluation(json.loads(result_path.read_text()), index)
    for task in tasks:
        labels.setdefault(task['task_id'], {})
    write_json(output_dir / 'labels.json', labels)
    write_json(output_dir / 'receipt.json', {
        'status': 'completed', 'command': cmd, 'seconds': time.monotonic() - started,
        'matrix_sha256': sha(tasks_path), 'private_snapshot_sha256': sha(snapshot_path),
        'result_sha256': sha(result_path), 'labels_sha256': sha(output_dir / 'labels.json'),
        'correctness_definition': 'official MBPP+ base_status and plus_status both pass',
    })


def analyse(tasks_path, selections_path, labels_path, config_path, output_dir):
    from .analysis import summarize, render_markdown
    config = json.loads(Path(config_path).read_text())
    tasks = read_jsonl(tasks_path)
    selections = {s['task_id']: s['selections'] for s in read_jsonl(selections_path)}
    labels = json.loads(Path(labels_path).read_text())
    ids = {t['task_id'] for t in tasks}
    if set(selections) != ids or set(labels) != ids:
        raise ValueError('analysis requires complete aligned task sets including failed tasks')
    records = [{'task_id': t['task_id'], 'labels': labels[t['task_id']], 'selections': selections[t['task_id']],
                'candidates': t['candidates'], 'matrix': t['matrix']} for t in tasks]
    summary = summarize(records, bootstrap_replicates=config['bootstrap_replicates'], seed=config['bootstrap_seed'])
    summary['provenance'] = {str(path): sha(path) for path in [tasks_path, selections_path, labels_path, config_path]}
    summary['pipeline_counts'] = {
        'candidate_statuses': dict(sum((Counter(t['counts']['candidate_statuses']) for t in tasks), Counter())),
        'execution_statuses': dict(sum((Counter(t['execution_statuses']) for t in tasks), Counter())),
        'valid_tests': sum(t['counts']['valid_tests'] for t in tasks),
        'test_parse_failures': sum(t['counts']['test_parse_failures'] for t in tasks),
    }
    write_json(Path(output_dir) / 'summary.json', summary)
    (Path(output_dir) / 'results.md').write_text(render_markdown(summary, stage=tasks[0]['split']))
    write_json(Path(output_dir) / 'inputs.manifest.json', {'status': 'completed', 'inputs': summary['provenance']})


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
    for key in ['tasks', 'snapshot', 'output_dir']:
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
        evaluate(args.tasks, args.snapshot, args.output_dir, args.timeout)
    else:
        analyse(args.tasks, args.selections, args.labels, args.config, args.output_dir)


if __name__ == '__main__':
    main()
