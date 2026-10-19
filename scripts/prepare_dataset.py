#!/usr/bin/env python3
"""Freeze public/private MBPP+ views before generating any model outputs."""
import argparse
import json
from pathlib import Path

from tgselect.data import prepare_dataset

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=Path('.local/dataset'))
parser.add_argument('--total', type=int, default=160)
parser.add_argument('--pilot', type=int, default=20)
args = parser.parse_args()
print(json.dumps(prepare_dataset(args.output, args.total, args.pilot), indent=2))
