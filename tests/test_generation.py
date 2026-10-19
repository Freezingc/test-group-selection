import json

import pytest

from tgselect.generation import build_requests, parse_record, validate_resume


def view():
    return {'task_id': 'Mbpp/1', 'prompt': 'Return x doubled.', 'entry_point': 'twice', 'split': 'e0'}


def test_grouped_request_identity_is_reproducible_and_independent_of_task_order():
    requests = build_requests([view()], candidate_count=16, group_count=8, tests_per_group=8)
    assert len(requests) == 24
    assert len({r['seed'] for r in requests}) == 24
    assert len({r['generation_batch_id'] for r in requests if r['kind'] == 'tests'}) == 8
    assert requests == build_requests([view()], candidate_count=16, group_count=8, tests_per_group=8)


def test_generation_refuses_hidden_fields():
    with pytest.raises(ValueError, match='public'):
        build_requests([{**view(), 'canonical_solution': 'def twice(x): return x*2'}])


def test_truncated_candidate_remains_logged_but_unusable():
    request = build_requests([view()])[0]
    record = {**request, 'response': 'def twice(x): return x*2', 'finish_reason': 'length'}
    parsed = parse_record(record)
    assert parsed['status'] == 'truncated'
    assert parsed['source'] == record['response']


def test_test_batch_parser_does_not_repair_false_assertions():
    request = [r for r in build_requests([view()]) if r['kind'] == 'tests'][0]
    parsed = parse_record({**request, 'response': json.dumps(['assert twice(3) == 5']), 'finish_reason': 'stop'})
    assert parsed['tests'][0]['assertion'] == 'assert twice(3) == 5'


def test_test_batch_preserves_the_preregistered_size_cap():
    request = [r for r in build_requests([view()]) if r['kind'] == 'tests'][0]
    parsed = parse_record({**request, 'response': json.dumps([f'assert twice({i}) == {i*2}' for i in range(10)]),
                           'finish_reason': 'stop'})
    assert len(parsed['tests']) == 8
    assert parsed['failures'][0]['discarded_count'] == 2


def test_resume_rejects_changed_prompt_duplicate_or_unexpected_requests():
    requests = build_requests([view()])
    records = [{**r, 'config_sha256': 'frozen'} for r in requests]
    assert validate_resume(records, requests, 'frozen') == {r['request_id'] for r in requests}
    changed = build_requests([{**view(), 'prompt': 'Return x tripled.'}])
    with pytest.raises(ValueError, match='request'):
        validate_resume(records, changed, 'frozen')
    with pytest.raises(ValueError, match='request'):
        validate_resume(records + [records[0]], requests, 'frozen')
    with pytest.raises(ValueError, match='request'):
        validate_resume(records, requests[1:], 'frozen')
