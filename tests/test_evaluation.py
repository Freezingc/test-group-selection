import pytest

pytest.importorskip('evalplus')

from tgselect.evaluation import evaluate_candidate


def test_official_kernel_compares_correct_and_incorrect_programs():
    suites = {'base': {'inputs': [[2], [3]], 'expected': [4, 6], 'ref_time': [0.001, 0.001]},
              'plus': {'inputs': [[-5]], 'expected': [-10], 'ref_time': [0.001]}}
    correct = evaluate_candidate('def twice(x): return 2*x', 'twice', suites)
    wrong = evaluate_candidate('def twice(x): return x', 'twice', suites)
    assert correct['base_status'] == correct['plus_status'] == 'pass'
    assert wrong['base_status'] == wrong['plus_status'] == 'fail'


def test_official_mbpp_set_equivalence_is_preserved():
    suites = {'base': {'inputs': [[[1, 2], [2, 3]]], 'expected': [[2, 1]], 'ref_time': [0.001]},
              'plus': {'inputs': [[[1, 2], [2, 3]]], 'expected': [[2, 1]], 'ref_time': [0.001]}}
    result = evaluate_candidate('def similar_elements(a, b): return [1, 2]', 'similar_elements', suites)
    assert result['base_status'] == result['plus_status'] == 'pass'


def test_eval_worker_does_not_receive_reference_source_or_result_directory():
    # Check the actual public IPC contract without running adversarial code.
    from tgselect.evaluation import make_payload
    payload = make_payload('def f(): return 1', 'f', {'inputs': [[]], 'expected': [1], 'ref_time': [0.001]}, 0)
    assert set(payload) == {'source', 'entry_point', 'inputs', 'expected', 'ref_time', 'atol'}
    assert 'canonical_solution' not in payload
    assert 'output_dir' not in payload
