import json
import socket

import pytest

from tgselect.execution import execute_candidate, extract_source, parse_tests


def test_parser_accepts_literals_and_rejects_executable_arguments():
    raw = json.dumps([
        'assert f([1, 2], reverse=True) == (2, 1)',
        'assert f(__import__("os").system("id")) == 0',
        'assert other(1) == 1',
        'assert f(1) != 2',
    ])
    tests, rejected = parse_tests(raw, 'f', 'batch0')
    assert len(tests) == 1
    assert len(rejected) == 3
    assert tests[0]['generation_batch_id'] == 'batch0'


def test_parser_retains_wrong_expected_value_without_gold_filter():
    tests, rejected = parse_tests('["assert f(2) == 999"]', 'f', 'batch0')
    assert not rejected
    assert tests[0]['assertion'] == 'assert f(2) == 999'


def test_extract_source_preserves_bytes_inside_fence_and_parse_failure():
    assert extract_source('```python\ndef f(x):\n    return x\n```')['source'] == 'def f(x):\n    return x\n'
    assert extract_source('def f(:')['status'] == 'syntax_error'


def test_sandbox_classifies_results_and_resets_program_state():
    source = 'n = 0\ndef f(x):\n    global n\n    n += 1\n    return x + n\n'
    tests, _ = parse_tests('["assert f(1) == 2", "assert f(1) == 2", "assert f(1) == 99"]', 'f', 'b')
    result = execute_candidate(source, tests, per_test_timeout=0.3)
    assert [x['status'] for x in result['results']] == ['pass', 'pass', 'assertion_fail']


def test_sandbox_times_out_one_test_and_preserves_other_results():
    tests, _ = parse_tests('["assert f(0) == 0", "assert f(1) == 1"]', 'f', 'b')
    source = 'def f(x):\n    if x == 0:\n        while True: pass\n    return x\n'
    result = execute_candidate(source, tests, per_test_timeout=0.15)
    assert [x['status'] for x in result['results']] == ['timeout', 'pass']


def test_sandbox_has_no_host_home_or_network(tmp_path):
    secret = tmp_path / 'host-secret'
    secret.write_text('not visible in sandbox')
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen()
    port = server.getsockname()[1]
    source = f'''import socket, pathlib
def f():
    hidden = not pathlib.Path({str(secret)!r}).exists()
    try:
        socket.create_connection(('127.0.0.1', {port}), timeout=0.1)
        return False
    except OSError:
        return hidden
'''
    tests, _ = parse_tests('["assert f() == True"]', 'f', 'b')
    try:
        assert execute_candidate(source, tests)['results'][0]['status'] == 'pass'
    finally:
        server.close()


def test_invalid_sandbox_is_infrastructure_failure():
    with pytest.raises(RuntimeError, match='sandbox'):
        execute_candidate('def f(): return 1', [], sandbox_binary='/missing/bwrap')


def test_filesystem_state_is_reset_between_tests():
    source = '''from pathlib import Path
def f():
    marker = Path('/tmp/marker')
    old = marker.exists()
    marker.write_text('created')
    return old
'''
    tests, _ = parse_tests('["assert f() == False", "assert f() == False"]', 'f', 'b')
    assert [r['status'] for r in execute_candidate(source, tests)['results']] == ['pass', 'pass']


def test_timeout_does_not_leave_descendants_for_next_test():
    source = '''import os, time
from pathlib import Path
def f(x):
    if x == 0:
        if os.fork() == 0:
            time.sleep(0.4)
            Path('/tmp/marker').write_text('child survived')
            os._exit(0)
        while True: pass
    time.sleep(0.2)
    return Path('/tmp/marker').exists()
'''
    tests, _ = parse_tests('["assert f(0) == False", "assert f(1) == False"]', 'f', 'b')
    assert [r['status'] for r in execute_candidate(source, tests, per_test_timeout=0.3)['results']] == ['timeout', 'pass']
