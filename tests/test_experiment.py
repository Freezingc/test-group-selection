import hashlib
import json

import pytest

from tgselect.experiment import assemble_task, read_evaluation
from tgselect.generation import build_requests


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
