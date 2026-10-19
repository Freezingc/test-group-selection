#!/usr/bin/env python3
"""Recompute reported paired coverage directly from the committed task metrics."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


SELECTORS = {'uniform', 'aces_c', 'dedup_uniform', 'group_equal', 'group_rep'}


def require(condition, message):
    """Integrity checks must remain active under -O and PYTHONOPTIMIZE."""
    if not condition:
        raise ValueError(message)


def metric_matches(reported, q, n, context):
    require(isinstance(reported, dict), f'{context}: missing metric object')
    denominator = reported.get('n')
    require(isinstance(denominator, int) and not isinstance(denominator, bool) and denominator == n,
            f'{context}: denominator n differs from all planned tasks')
    for key, expected in [('q', float(q)), ('rate', float(q) / n)]:
        actual = reported.get(key)
        require(isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual)
                and math.isclose(actual, expected, abs_tol=1e-12, rel_tol=0),
                f'{context}: {key} differs from compact task indicators')


def check(run_dir):
    run_dir = Path(run_dir)
    rows = [json.loads(line) for line in (run_dir / 'task_metrics.jsonl').read_text().splitlines()]
    summary = json.loads((run_dir / 'summary.json').read_text())
    usage = json.loads((run_dir / 'usage.json').read_text())
    require(hashlib.sha256((run_dir / 'task_metrics.jsonl').read_bytes()).hexdigest()
            == usage['compact_files']['task_metrics.jsonl']['sha256'], 'Compact task-metrics SHA-256 mismatch')
    n = summary['n_tasks']
    require(isinstance(n, int) and not isinstance(n, bool) and n > 0, 'Summary must contain a positive task count')
    require(usage.get('status') == 'completed' and usage.get('n_tasks') == n,
            'Usage receipt is incomplete or has a different task count')
    require(len(rows) == len({row['task_id'] for row in rows}) == n, 'Compact task count/identifiers mismatch')
    planned = json.loads((run_dir / 'tasks.manifest.json').read_text())['planned_task_ids']
    require(len(planned) == n and set(planned) == {row['task_id'] for row in rows}, 'Planned task set mismatch')
    metric_matches(summary['pool']['coverage'], sum(row['pool_correct'] for row in rows), n, 'Pool coverage')
    require(sum(row['usable_candidates'] for row in rows) == summary['pool']['candidate_count']['total'],
            'Candidate count differs from compact records')
    require(set(summary['selectors']) == SELECTORS, 'Summary must include all five protocol selectors')
    settings = summary['inference']
    rng = np.random.default_rng(settings['seed'])
    resamples = rng.integers(0, n, size=(settings['bootstrap_replicates'], n))
    comparisons = 0
    for selector, reported in summary['selectors'].items():
        values = [row['selectors'][selector] for row in rows]
        base = np.array([value['base_correct'] for value in values])
        metric_matches(reported['base_accuracy'], int(base.sum()), n, f'{selector}/base_accuracy')
        coverage = {method: np.array([value['methods'][method]['coverage'] for value in values])
                    for method in ['top2', 'diverse', 'perturbed', 'raw_w']}
        for row, selected in zip(rows, values):
            truth = {candidate['candidate_id']: candidate['correct'] for candidate in row['candidates']}
            require(row['pool_correct'] == int(any(truth.values())), f"{row['task_id']}: pool indicator differs from labels")
            require(selected['base_correct'] == truth.get(selected['base_id'], 0),
                    f"{row['task_id']}/{selector}: baseline indicator differs from labels")
            for method, pair in selected['methods'].items():
                require(pair['coverage'] == int(any(truth[cid] for cid in pair['selected_ids'])),
                        f"{row['task_id']}/{selector}/{method}: coverage differs from selected labels")
                require(len(pair['selected_ids']) == len(set(pair['selected_ids'])),
                        f"{row['task_id']}/{selector}/{method}: duplicate selected candidate")
                if truth:
                    require(selected['base_id'] in pair['selected_ids'],
                            f"{row['task_id']}/{selector}/{method}: baseline missing from review set")
                if method != 'raw_w':
                    require(len(pair['selected_ids']) <= 2, f"{row['task_id']}/{selector}/{method}: review set exceeds k=2")
            require(set(selected['random_coverage']) == {str(seed) for seed in range(20)},
                    f"{row['task_id']}/{selector}: missing or extra random coverage seed")
            require(set(selected['random_selected_ids']) == set(selected['random_coverage']),
                    f"{row['task_id']}/{selector}: random selection seed set mismatch")
            for seed, ids in selected['random_selected_ids'].items():
                require(selected['random_coverage'][seed] == int(any(truth[cid] for cid in ids)),
                        f"{row['task_id']}/{selector}/random_{seed}: coverage differs from selected labels")
        for method in ['top2', 'diverse', 'perturbed']:
            counts = reported['methods'][method]
            chosen = coverage[method]
            top2 = coverage['top2']
            metric_matches(counts['coverage'], int(chosen.sum()), n, f'{selector}/{method}/coverage')
            metric_matches(counts['u'], int(np.sum(chosen * (1 - base))), n, f'{selector}/{method}/u')
            pairs = {'gain': (chosen == 1) & (top2 == 0), 'loss': (chosen == 0) & (top2 == 1),
                     'both': (chosen == 1) & (top2 == 1), 'neither': (chosen == 0) & (top2 == 0)}
            for key, indicator in pairs.items():
                metric_matches(counts['vs_top2'][key], int(indicator.sum()), n, f'{selector}/{method}/vs_top2/{key}')
        random = np.array([[value['random_coverage'][str(seed)] for value in values] for seed in range(20)])
        require(reported['random']['n_seeds'] == 20 and reported['random']['seeds'] == list(range(20))
                and len(reported['random']['coverage_by_seed']) == 20, f'{selector}: reported random seeds mismatch')
        for seed in range(20):
            seed_metric = reported['random']['coverage_by_seed'][seed]
            require(seed_metric.get('seed') == seed, f'{selector}: reported seed ordering mismatch')
            metric_matches(seed_metric, int(random[seed].sum()), n, f'{selector}/random_{seed}/coverage')
        random_mean = random.mean(axis=0)
        metric_matches(reported['random']['coverage_mean'], random_mean.sum(), n, f'{selector}/random_mean/coverage')
        metric_matches(reported['raw_w']['coverage'], int(coverage['raw_w'].sum()), n, f'{selector}/raw_w/coverage')
        for key in ['baseline_wrong_pool_correct', 'identical_row_blind_spot', 'no_alternative_winner']:
            metric_matches(reported['mechanisms'][key], sum(value[key] for value in values), n, f'{selector}/{key}')
        for key, reference in [('top2', coverage['top2']), ('diverse', coverage['diverse']), ('random_mean', random_mean)]:
            delta = coverage['perturbed'] - reference
            interval = np.percentile(delta[resamples].mean(axis=1), [2.5, 97.5])
            target = reported['paired_differences']['perturbed_minus_' + key]
            require(target.get('n') == n and target.get('unit') == 'task', f'{selector}/{key}: paired task denominator mismatch')
            require(np.isclose(delta.mean(), target['difference'], atol=1e-12, rtol=0),
                    f'{selector}/{key}: paired difference mismatch')
            require(np.allclose(interval, target['ci95'], atol=1e-12, rtol=0), f'{selector}/{key}: paired interval mismatch')
            comparisons += 1
    return {'status': 'matched', 'n_tasks': n, 'paired_comparisons': comparisons,
            'scope': 'Independent arithmetic from compact task indicators; does not rerun generation, selection or hidden evaluation'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.run_dir), sort_keys=True))


if __name__ == '__main__':
    main()
