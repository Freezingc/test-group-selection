#!/usr/bin/env python3
"""Recompute reported paired coverage directly from the committed task metrics."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def check(run_dir):
    rows = [json.loads(line) for line in (run_dir / 'task_metrics.jsonl').read_text().splitlines()]
    summary = json.loads((run_dir / 'summary.json').read_text())
    usage = json.loads((run_dir / 'usage.json').read_text())
    assert hashlib.sha256((run_dir / 'task_metrics.jsonl').read_bytes()).hexdigest() == usage['compact_files']['task_metrics.jsonl']['sha256']
    n = summary['n_tasks']
    assert len(rows) == len({row['task_id'] for row in rows}) == n
    planned = json.loads((run_dir / 'tasks.manifest.json').read_text())['planned_task_ids']
    assert set(planned) == {row['task_id'] for row in rows}
    assert sum(row['pool_correct'] for row in rows) == summary['pool']['coverage']['q']
    assert sum(row['usable_candidates'] for row in rows) == summary['pool']['candidate_count']['total']
    settings = summary['inference']
    rng = np.random.default_rng(settings['seed'])
    resamples = rng.integers(0, n, size=(settings['bootstrap_replicates'], n))
    comparisons = 0
    for selector, reported in summary['selectors'].items():
        values = [row['selectors'][selector] for row in rows]
        base = np.array([value['base_correct'] for value in values])
        assert int(base.sum()) == reported['base_accuracy']['q']
        coverage = {method: np.array([value['methods'][method]['coverage'] for value in values])
                    for method in ['top2', 'diverse', 'perturbed', 'raw_w']}
        for row, selected in zip(rows, values):
            truth = {candidate['candidate_id']: candidate['correct'] for candidate in row['candidates']}
            assert row['pool_correct'] == int(any(truth.values()))
            assert selected['base_correct'] == truth.get(selected['base_id'], 0)
            for method, pair in selected['methods'].items():
                assert pair['coverage'] == int(any(truth[cid] for cid in pair['selected_ids']))
                assert len(pair['selected_ids']) == len(set(pair['selected_ids']))
                if truth:
                    assert selected['base_id'] in pair['selected_ids']
                if method != 'raw_w':
                    assert len(pair['selected_ids']) <= 2
            assert set(selected['random_coverage']) == {str(seed) for seed in range(20)}
            for seed, ids in selected['random_selected_ids'].items():
                assert selected['random_coverage'][seed] == int(any(truth[cid] for cid in ids))
        for method in ['top2', 'diverse', 'perturbed']:
            counts = reported['methods'][method]
            chosen = coverage[method]
            top2 = coverage['top2']
            assert int(chosen.sum()) == counts['coverage']['q']
            assert int(np.sum(chosen * (1 - base))) == counts['u']['q']
            pairs = {'gain': (chosen == 1) & (top2 == 0), 'loss': (chosen == 0) & (top2 == 1),
                     'both': (chosen == 1) & (top2 == 1), 'neither': (chosen == 0) & (top2 == 0)}
            for key, indicator in pairs.items():
                assert int(indicator.sum()) == counts['vs_top2'][key]['q']
        random = np.array([[value['random_coverage'][str(seed)] for value in values] for seed in range(20)])
        for seed in range(20):
            assert int(random[seed].sum()) == reported['random']['coverage_by_seed'][seed]['q']
        random_mean = random.mean(axis=0)
        assert np.isclose(random_mean.sum(), reported['random']['coverage_mean']['q'], atol=1e-12, rtol=0)
        assert int(coverage['raw_w'].sum()) == reported['raw_w']['coverage']['q']
        for key in ['baseline_wrong_pool_correct', 'identical_row_blind_spot', 'no_alternative_winner']:
            assert sum(value[key] for value in values) == reported['mechanisms'][key]['q']
        for key, reference in [('top2', coverage['top2']), ('diverse', coverage['diverse']), ('random_mean', random_mean)]:
            delta = coverage['perturbed'] - reference
            interval = np.percentile(delta[resamples].mean(axis=1), [2.5, 97.5])
            target = reported['paired_differences']['perturbed_minus_' + key]
            assert np.isclose(delta.mean(), target['difference'], atol=1e-12, rtol=0)
            assert np.allclose(interval, target['ci95'], atol=1e-12, rtol=0)
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
