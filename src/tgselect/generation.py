"""Local frozen-pool generation. No evaluator imports or hidden-data inputs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from .execution import extract_source, parse_tests


PROMPT_VERSION = 'tgselect-prompts-v1'
PUBLIC_KEYS = {'task_id', 'prompt', 'entry_point', 'split'}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def build_requests(views, candidate_count=16, group_count=8, tests_per_group=8):
    requests = []
    for view in views:
        if set(view) - PUBLIC_KEYS:
            raise ValueError('generation accepts only the public task view')
        task_id, entry = view['task_id'], view['entry_point']
        for kind, count in [('candidate', candidate_count), ('tests', group_count)]:
            for index in range(count):
                request_id = f'{task_id}/{kind}/{index:02d}'
                if kind == 'candidate':
                    instruction = (
                        'Write a complete Python 3 solution for the task below. '
                        'Use the Python standard library only and include required imports. '
                        f'Define the function {entry} with positional parameters matching the task. '
                        'Return only the complete source code in a python code block.\n\n'
                    )
                else:
                    instruction = (
                        f'Independently write {tests_per_group} diverse test cases for the Python function '
                        f'{entry} described below. Include edge cases. Infer the expected outputs yourself. '
                        'Return ONLY a valid JSON array of strings. Each string must be a single '
                        f'Python assertion of the form assert {entry}(literal_arguments) == literal_expected. '
                        'Arguments and expected outputs must be Python literals (including lists, tuples, sets, '
                        'strings, numbers, booleans or None). Do not use helper variables, imports, function '
                        'calls inside arguments, approximate comparisons, or code outside the JSON array.\n\n'
                    )
                prompt = instruction + view['prompt']
                request = {
                    'request_id': request_id, 'task_id': task_id, 'kind': kind,
                    'entry_point': entry, 'seed': int(digest('tgselect-generation-v1:' + request_id)[:8], 16),
                    'prompt': prompt, 'prompt_hash': digest(prompt), 'task_hash': digest(view['prompt']),
                    'prompt_version': PROMPT_VERSION,
                }
                if kind == 'candidate':
                    request['candidate_id'] = request_id
                else:
                    request['generation_batch_id'] = request_id
                    request['requested_tests'] = tests_per_group
                requests.append(request)
    return requests


def parse_record(record):
    if record['kind'] == 'candidate':
        result = extract_source(record['response'])
        if record['finish_reason'] != 'stop':
            result['status'] = 'truncated' if record['finish_reason'] == 'length' else 'generation_failure'
        return {**result, 'candidate_id': record['candidate_id'], 'task_id': record['task_id']}
    tests, failures = parse_tests(record['response'], record['entry_point'], record['generation_batch_id'])
    limit = record.get('requested_tests', 8)
    if len(tests) > limit:
        failures.append({'reason': 'over_requested_test_limit', 'discarded_count': len(tests) - limit})
        tests = tests[:limit]
    if record['finish_reason'] != 'stop':
        tests = []
        failures.append({'reason': 'truncated_or_failed_batch', 'finish_reason': record['finish_reason']})
    return {'task_id': record['task_id'], 'generation_batch_id': record['generation_batch_id'],
            'tests': tests, 'failures': failures}


def validate_resume(records, requests, config_hash):
    expected = {request['request_id']: request for request in requests}
    done = set()
    for record in records:
        rid = record['request_id']
        if rid in done or rid not in expected:
            raise ValueError('duplicate or unexpected resume request')
        if record['config_sha256'] != config_hash:
            raise ValueError('Resume config hash mismatch')
        if any(record.get(key) != value for key, value in expected[rid].items()):
            raise ValueError('resume request content, task, prompt or seed differs')
        done.add(rid)
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--views', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--split', choices=['e0', 'e1'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-path', type=Path, required=True)
    parser.add_argument('--resume', action='store_true', help='Continue only requests without a recorded response')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    views = [json.loads(line) for line in args.views.read_text().splitlines() if line.strip()]
    views = [view for view in views if view['split'] == args.split]
    requests = build_requests(views, config['candidate_count'], config['group_count'], config['tests_per_group'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and not args.resume:
        raise SystemExit('Output exists: use a new run directory or explicitly --resume')
    done = set()
    if args.output.exists():
        receipts = [json.loads(line) for line in args.output.read_text().splitlines() if line.strip()]
        done = validate_resume(receipts, requests, hashlib.sha256(args.config.read_bytes()).hexdigest())
    pending = [request for request in requests if request['request_id'] not in done]
    if not pending:
        print(json.dumps({'status': 'already_complete', 'requests': len(done)}), flush=True)
        return
    from .hf_backend import HFBackend
    backend = HFBackend(args.model_path, config)
    tokenizer = backend.tokenizer
    runtime = {
        'model_id': config['model_id'], 'model_revision': config['model_revision'],
        'config_sha256': hashlib.sha256(args.config.read_bytes()).hexdigest(),
        'generation_backend': config['generation_backend'],
        'backend_metadata': backend.metadata,
        'generation_parameters': {key: config[key] for key in ['temperature', 'top_p', 'max_tokens']},
    }
    started = time.monotonic()
    with args.output.open('a') as stream:
        for start in range(0, len(pending), config['request_batch_size']):
            batch = pending[start:start + config['request_batch_size']]
            prompts = [tokenizer.apply_chat_template(
                [{'role': 'user', 'content': request['prompt']}], tokenize=False,
                add_generation_prompt=True) for request in batch]
            outputs = backend.generate(prompts, [request['seed'] for request in batch])
            for request, output in zip(batch, outputs, strict=True):
                record = {**request, **runtime, **output,
                          'elapsed_seconds_at_receipt': time.monotonic() - started}
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
            print(json.dumps({'status': 'progress', 'completed': len(done) + start + len(batch),
                              'total': len(requests), 'elapsed_seconds': time.monotonic() - started}), flush=True)
    print(json.dumps({'status': 'completed', 'requests': len(requests),
                      'elapsed_seconds': time.monotonic() - started}), flush=True)


if __name__ == '__main__':
    main()
