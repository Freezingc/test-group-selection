#!/usr/bin/env python3
"""Package completed raw experiment evidence, excluding benchmark reference data."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile

from tgselect.experiment import validate_frozen_inputs


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--runs', nargs='+', type=Path, required=True)
    p.add_argument('--config', type=Path, default=Path('configs/e0-e1-v1.json'))
    args = p.parse_args()
    if args.output.resolve() == args.manifest.resolve():
        p.error('Archive and manifest must resolve to different paths')
    if args.output.exists() or args.manifest.exists():
        p.error('Use a new archive and manifest path; existing evidence is retained')
    allowed = ['raw/generation.jsonl', 'raw/tasks.jsonl', 'raw/tasks.manifest.json',
               'raw/selections.jsonl', 'raw/selections.manifest.json',
               'evaluation/labels.json', 'evaluation/receipt.json', 'evaluation/samples_eval_results.json']
    files, source_paths, member_names = [], [], set()
    for run in args.runs:
        run_name = run.resolve().name
        if not run_name or run_name in {'.', '..'}:
            p.error('Run directory must have a portable directory name')
        validate_frozen_inputs(run / 'raw/tasks.jsonl', args.config, run / 'raw/selections.jsonl')
        usage = json.loads((run / 'usage.json').read_text())
        if usage['status'] != 'completed':
            raise ValueError('Run is incomplete')
        for relative in allowed:
            path = run / relative
            expected = usage['source_hashes'][relative]
            if digest(path) != expected:
                raise ValueError('Changed archive input: ' + str(path))
            member_name = (Path('artifacts/runs') / run_name / relative).as_posix()
            if member_name in member_names:
                p.error('Duplicate archive member: ' + member_name)
            member_names.add(member_name)
            source_paths.append(path)
            files.append({'path': member_name, 'bytes': path.stat().st_size, 'sha256': expected})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as archive:
            for path, record in zip(source_paths, files, strict=True):
                info = tarfile.TarInfo(record['path'])
                info.size = record['bytes']
                info.mode = 0o600
                info.mtime = 0
                with path.open('rb') as stream:
                    archive.addfile(info, stream)
    with tarfile.open(args.output, 'r:gz') as archive:
        members = archive.getmembers()
        if [member.name for member in members] != [record['path'] for record in files]:
            raise ValueError('Archive members differ')
        for member, record in zip(members, files, strict=True):
            h = hashlib.sha256()
            with archive.extractfile(member) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(chunk)
            if h.hexdigest() != record['sha256']:
                raise ValueError('Archive content differs: ' + member.name)
    manifest = {'status': 'verified', 'archive_name': args.output.name, 'bytes': args.output.stat().st_size,
                'sha256': digest(args.output), 'compression': 'deterministic gzip + PAX tar; timestamps/owners normalized',
                'files': files, 'scope': 'Frozen model generations, generated-test execution matrices, selections and official outcome receipts. No official hidden inputs, reference source, private dataset snapshot or credentials.'}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'status': 'verified', 'bytes': manifest['bytes'], 'sha256': manifest['sha256']}))


if __name__ == '__main__':
    main()
