#!/usr/bin/env python3
"""Download the frozen public model revision; no remote inference calls."""
import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download

parser = argparse.ArgumentParser()
parser.add_argument('--config', type=Path, default=Path('configs/e0-e1-v1.json'))
parser.add_argument('--path-file', type=Path, default=Path('.local/model-path.txt'))
args = parser.parse_args()
config = json.loads(args.config.read_text())
path = snapshot_download(config['model_id'], revision=config['model_revision'],
                         allow_patterns=['*.safetensors', '*.json', '*.txt', '*.model'],
                         token=False, max_workers=4)
args.path_file.parent.mkdir(parents=True, exist_ok=True)
args.path_file.write_text(path + '\n')
print(path)
