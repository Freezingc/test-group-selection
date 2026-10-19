#!/usr/bin/env python3
"""Run one authorized experiment command with process and hard-timeout receipts."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import psutil


parser = argparse.ArgumentParser()
parser.add_argument('--receipt', type=Path, required=True)
parser.add_argument('--log', type=Path, required=True)
parser.add_argument('--timeout', type=int, required=True)
parser.add_argument('--gpu', type=int)
parser.add_argument('command', nargs=argparse.REMAINDER)
args = parser.parse_args()
command = args.command[1:] if args.command[:1] == ['--'] else args.command
if not command or args.timeout <= 0:
    parser.error('a command and positive hard timeout are required')
args.receipt.parent.mkdir(parents=True, exist_ok=True)
args.log.parent.mkdir(parents=True, exist_ok=True)
started = time.monotonic()
record = {'command': command, 'cwd': str(Path.cwd()),
          'start_utc': datetime.now(timezone.utc).isoformat(), 'status': 'running',
          'timeout_seconds': args.timeout, 'log': str(args.log), 'peak_process_tree_rss_bytes': 0,
          'gpu_index': args.gpu, 'peak_gpu_used_mib': 0}
def save():
    args.receipt.write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
with args.log.open('w') as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    record['pid'] = process.pid
    save()
    while process.poll() is None:
        elapsed = time.monotonic() - started
        record['elapsed_seconds'] = elapsed
        try:
            parent = psutil.Process(process.pid)
            rss = sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)] if p.is_running())
            record['peak_process_tree_rss_bytes'] = max(record['peak_process_tree_rss_bytes'], rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        if args.gpu is not None:
            try:
                usage = subprocess.check_output(['nvidia-smi', f'--id={args.gpu}',
                    '--query-gpu=memory.used', '--format=csv,noheader,nounits'], timeout=5, text=True)
                record['peak_gpu_used_mib'] = max(record['peak_gpu_used_mib'], int(usage.strip()))
            except (OSError, ValueError, subprocess.SubprocessError):
                record['gpu_monitor_degraded'] = True
        if elapsed >= args.timeout:
            print('Hard timeout reached; terminating this experiment process group.', flush=True)
            record['status'] = 'timeout'
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            break
        save()
        print(json.dumps({'monitor': 'alive', 'elapsed_seconds': round(elapsed, 1),
                          'log_bytes': args.log.stat().st_size,
                          'peak_gpu_used_mib': record['peak_gpu_used_mib']}), flush=True)
        try:
            process.wait(timeout=min(30, max(0.1, args.timeout - elapsed)))
        except subprocess.TimeoutExpired:
            pass
record.update(exit_code=process.returncode, elapsed_seconds=time.monotonic() - started,
              end_utc=datetime.now(timezone.utc).isoformat())
if record['status'] == 'running':
    record['status'] = 'completed' if process.returncode == 0 else 'crashed'
save()
print(json.dumps(record, ensure_ascii=False), flush=True)
sys.exit(0 if record['status'] == 'completed' else 1)
