#!/usr/bin/env python3
"""Audit a completed visible-execution matrix without running candidate code.

Run with Python 3.11 so sys.stdlib_module_names matches the execution protocol:
    .local/eval-venv/bin/python scripts/audit_execution.py --run-dir RUN

Reads only raw/tasks.jsonl and its completed manifest. Hidden labels, reference
inputs, exception messages and candidate source are never copied to the report.
"""

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile


CONCERNS = ('timeout', 'MemoryError', 'ImportError', 'ModuleNotFoundError', 'ChildProcessExit')


def digest(content):
    return hashlib.sha256(content).hexdigest()


def finite_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('execution seconds must be numeric')
    if not math.isfinite(value) or value < 0:
        raise ValueError('execution seconds must be finite and nonnegative')
    return float(value)


def timing_summary(values, missing):
    ordered = sorted(values)

    def quantile(probability):
        position = (len(ordered) - 1) * probability
        lower = math.floor(position)
        upper = math.ceil(position)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {
        'observed_count': len(ordered), 'missing_count': missing,
        'sum': math.fsum(ordered), 'max': ordered[-1] if ordered else None,
        'quantile_method': 'linear interpolation at (n-1)*p',
        'quantiles': {name: quantile(probability) if ordered else None
                      for name, probability in [('p0', 0), ('p25', .25), ('p50', .5),
                                                 ('p75', .75), ('p90', .9),
                                                 ('p95', .95), ('p99', .99), ('p100', 1)]},
    }


def static_imports(source):
    """Inspect syntax only; neither import nor execute generated code."""
    tree = ast.parse(source)
    imports = Counter()
    relative = dynamic = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative = True
            elif node.module:
                imports[node.module.split('.')[0]] += 1
        elif isinstance(node, ast.Call):
            function = node.func
            if ((isinstance(function, ast.Name) and function.id == '__import__') or
                    (isinstance(function, ast.Attribute) and function.attr in {'import_module', '__import__'})):
                dynamic = True
    bare_python = any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Name)
                      and node.value.id == 'python' for node in tree.body)
    return imports, relative, dynamic, bare_python


def read_completed(run_dir):
    matrix_path = run_dir / 'raw' / 'tasks.jsonl'
    manifest_path = run_dir / 'raw' / 'tasks.manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get('status') != 'completed':
        raise ValueError('matrix manifest is not completed; partial runs cannot be audited')
    matrix_bytes = matrix_path.read_bytes()
    if manifest.get('matrix_sha256') != digest(matrix_bytes):
        raise ValueError('matrix SHA-256 differs from completed manifest')
    tasks = [json.loads(line) for line in matrix_bytes.splitlines() if line.strip()]
    ids = [task['task_id'] for task in tasks]
    planned = manifest.get('planned_task_ids')
    if (any(not isinstance(task_id, str) for task_id in ids) or len(set(ids)) != len(ids)
            or not isinstance(planned, list) or any(not isinstance(task_id, str) for task_id in planned)
            or len(set(planned)) != len(planned) or set(ids) != set(planned)
            or manifest.get('tasks') != len(tasks)
            or manifest.get('expected_n', len(tasks)) != len(tasks)):
        raise ValueError('completed matrix task set/count differs from manifest')
    if any(task.get('split') != manifest.get('split') for task in tasks):
        raise ValueError('matrix split differs from completed manifest')
    return tasks, [(matrix_path, digest(matrix_bytes)), (manifest_path, digest(manifest_bytes))]


def audit(run_dir):
    if sys.version_info[:2] != (3, 11):
        raise ValueError('audit requires Python 3.11 for stdlib classification')
    run_dir = Path(run_dir).resolve()
    tasks, inputs = read_completed(run_dir)
    statuses, exceptions = Counter(), Counter()
    imports = defaultdict(lambda: {'ast_occurrences': 0, 'task_ids': set(), 'candidate_ids': set()})
    concerns = {name: {'count': 0, 'task_ids': set(), 'candidate_ids': set()}
                for name in CONCERNS}
    candidate_records, task_records = [], []
    nonstdlib_ids, bare_ids, relative_ids, dynamic_ids = [], [], [], []
    parse_error_ids, zero_test_ids, case_times, wall_times = [], [], [], []
    seen_candidates = set()
    case_missing = wall_missing = 0
    runtime_versions = Counter()

    for task in tasks:
        task_id = task['task_id']
        candidates, tests, matrix = task['candidates'], task['tests'], task['matrix']
        test_ids = [test['test_id'] for test in tests]
        candidate_ids = [candidate['candidate_id'] for candidate in candidates]
        if (len(test_ids) != len(set(test_ids)) or len(candidate_ids) != len(set(candidate_ids))
                or seen_candidates.intersection(candidate_ids)):
            raise ValueError('duplicate candidate or test identifiers')
        seen_candidates.update(candidate_ids)
        if set(task['executions']) != set(candidate_ids) or len(matrix) != len(candidates):
            raise ValueError('candidate execution set/matrix rows are incomplete')
        if not tests:
            zero_test_ids.append(task_id)
        task_statuses, task_exceptions = Counter(), Counter()

        for candidate, row in zip(candidates, matrix):
            candidate_id = candidate['candidate_id']
            execution = task['executions'][candidate_id]
            results = execution['results']
            if (execution.get('execution_count') != len(tests)
                    or [result['test_id'] for result in results] != test_ids
                    or len(row) != len(tests) or any(value not in (0, 1) for value in row)):
                raise ValueError('candidate case results/matrix are incomplete or misaligned')
            candidate_statuses, candidate_exceptions = Counter(), Counter()
            for value, result in zip(row, results):
                status = result['status']
                exception = result.get('exception')
                if not isinstance(status, str) or (exception is not None and not isinstance(exception, str)):
                    raise ValueError('execution status/exception must be strings')
                if value != int(status == 'pass'):
                    raise ValueError('matrix pass bit differs from execution status')
                candidate_statuses[status] += 1
                if exception:
                    candidate_exceptions[exception] += 1
                for name in CONCERNS:
                    affected = status == 'timeout' if name == 'timeout' else exception == name
                    if affected:
                        concerns[name]['count'] += 1
                        concerns[name]['task_ids'].add(task_id)
                        concerns[name]['candidate_ids'].add(candidate_id)
                if 'seconds' in result:
                    case_times.append(finite_seconds(result['seconds']))
                else:
                    case_missing += 1
            statuses.update(candidate_statuses)
            exceptions.update(candidate_exceptions)
            task_statuses.update(candidate_statuses)
            task_exceptions.update(candidate_exceptions)
            wall = execution.get('wall_seconds')
            if wall is None:
                wall_missing += 1
            else:
                wall = finite_seconds(wall)
                wall_times.append(wall)
            runtime_versions[str(execution.get('python_version', 'not_recorded'))] += 1
            try:
                declared, relative, dynamic, bare = static_imports(candidate['source'])
                syntax_error = None
            except (SyntaxError, ValueError, TypeError, RecursionError) as exc:
                declared, relative, dynamic, bare = Counter(), False, False, False
                syntax_error = type(exc).__name__
                parse_error_ids.append(candidate_id)
            for module, count in declared.items():
                imports[module]['ast_occurrences'] += count
                imports[module]['task_ids'].add(task_id)
                imports[module]['candidate_ids'].add(candidate_id)
            nonstdlib = sorted(module for module in declared if module not in sys.stdlib_module_names)
            if nonstdlib:
                nonstdlib_ids.append(candidate_id)
            for condition, collection in [(relative, relative_ids), (dynamic, dynamic_ids), (bare, bare_ids)]:
                if condition:
                    collection.append(candidate_id)
            candidate_records.append({
                'task_id': task_id, 'candidate_id': candidate_id, 'test_count': len(tests),
                'status_counts': dict(sorted(candidate_statuses.items())),
                'exceptions_counts': dict(sorted(candidate_exceptions.items())),
                'wall_seconds': wall, 'import_top_modules': sorted(declared),
                'nonstdlib_top_modules': nonstdlib, 'ast_parse_error': syntax_error,
                'bare_python_toplevel_expression': bare,
                'relative_import_syntax': relative, 'dynamic_import_syntax': dynamic,
            })
        task_records.append({'task_id': task_id, 'candidate_count': len(candidates), 'test_count': len(tests),
                             'status_counts': dict(sorted(task_statuses.items())),
                             'exceptions_counts': dict(sorted(task_exceptions.items()))})

    def finalize_sets(record):
        return {key: sorted(value) if isinstance(value, set) else value for key, value in record.items()}

    report = {
        'schema_version': 'tgselect-execution-audit-v1', 'status': 'completed',
        'scope': 'all frozen visible-execution candidates; no hidden labels read or exclusions applied',
        'inputs': {str(path): expected for path, expected in inputs},
        'audit_script_sha256': digest(Path(__file__).read_bytes()),
        'classification_python_version': sys.version.split()[0],
        'recorded_execution_python_versions': dict(sorted(runtime_versions.items())),
        'stdlib_classification': 'top module membership in Python 3.11 sys.stdlib_module_names; not an importability test',
        'counts': {'tasks': len(tasks), 'candidates': len(candidate_records),
                   'case_results': sum(statuses.values()), 'ast_parse_errors': len(parse_error_ids)},
        'status_counts': dict(sorted(statuses.items())),
        'exceptions_counts': dict(sorted(exceptions.items())),
        'imports': {module: {**finalize_sets(record), 'candidate_count': len(record['candidate_ids']),
                             'is_stdlib': module in sys.stdlib_module_names}
                    for module, record in sorted(imports.items())},
        'nonstdlib_candidate_ids': sorted(nonstdlib_ids), 'bare_python_candidate_ids': sorted(bare_ids),
        'relative_import_candidate_ids': sorted(relative_ids),
        'dynamic_import_candidate_ids': sorted(dynamic_ids), 'ast_parse_error_candidate_ids': sorted(parse_error_ids),
        'zero_test_task_ids': sorted(zero_test_ids),
        'concerns': {name: finalize_sets(record) for name, record in concerns.items()},
        'case_seconds': {
            **timing_summary(case_times, case_missing),
            'unit': 'seconds recorded in the program child; not sandbox or stage wall time',
            'timeout_seconds_semantics': 'timeout records contain the configured per-test budget, not measured completion time',
        },
        'candidate_wall_seconds': {
            **timing_summary(wall_times, wall_missing),
            'unit': 'candidate executor elapsed seconds including sandbox startup and all test processes',
            'aggregation_warning': 'sum is accumulated candidate elapsed time; overlapping workers mean it is not actual stage wall time',
        },
        'tasks': task_records, 'candidates': candidate_records,
        'limitations': [
            'AST imports include conditional and function-local declarations, whether reached or not.',
            'Dynamic imports, alias-based import calls and runtime module availability are not resolved.',
            'Relative imports are separately flagged and are not classified as absolute top modules.',
            'No candidate source, generated assertions, exception details or hidden inputs are included.',
            'No candidate execution or dependency import is performed by this audit.',
        ],
    }
    for path, expected in inputs:
        if digest(path.read_bytes()) != expected:
            raise ValueError('frozen audit inputs changed while being inspected')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(args.run_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f'audit refused: {exc}\n')
    output = args.run_dir.resolve() / 'execution-audit.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                                         prefix='.execution-audit-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'output': str(output), **report['counts']}, sort_keys=True))


if __name__ == '__main__':
    main()
