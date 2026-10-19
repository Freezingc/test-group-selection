# Test-group perturbations for code candidate selection

An exploratory implementation of **Selecting Candidates for Verification through Test-Group Perturbations**. It tests whether source-batch deletion exposes better alternatives than ordinary Top-2 and simple diversity controls, while freezing the candidate pool, test pool and review-set size.

The starting research report is in [docs/research/research-report.md](docs/research/research-report.md). It contains hypotheses, not established results. The authorized first implementation covers E0–E1; no paid API auditor or E2 benefit is assumed.

The experiment assessment is in [docs/experiment-results.md](docs/experiment-results.md). The completed E0 engineering run is in [artifacts/runs/e0-v1/results.md](artifacts/runs/e0-v1/results.md). Its 20 tasks are excluded from E1. Compact per-task indicators and their SHA-256 receipts allow all 15 paired coverage comparisons in each completed run to be recomputed without loading a model or accessing hidden benchmark inputs:

```bash
.local/eval-venv/bin/python scripts/check_compact_results.py --run-dir artifacts/runs/e0-v1
```

## Protocol

- Official EvalPlus 0.3.1 checking kernel / MBPP+ v0.2.0, pinned content hash. A trusted supervisor and per-suite bubblewrap wrapper replace the original CLI's shared execution directory.
- Hash-selected 160-task development pool: 20 E0 engineering tasks, 140 E1 exploratory tasks. Remaining 218 tasks and HumanEval+ are reserved.
- Qwen2.5-Coder-7B-Instruct revision `c03e6d358207e414f1eca0bb1891e29f1db0e242`; 16 program samples and 8 independently seeded requests for up to 8 tests each per task. Local Hugging Face autoregressive decoding uses separate RNG streams per request; it is not expected to reproduce vLLM outputs.
- Five base selectors: uniform, ACES-C, execution-column deduplication, equal group weight and one representative per group.
- Compare source-distinct Top-2, behavioral diversity, source-group perturbation and 20 size-matched random grouping seeds. Random grouping changes deletions only; it preserves each base selector and its original winner.
- Exact ACES-C integer-equivalent weights; common deterministic candidate hash ties. Constant columns, zero-weight fallback and protocol differences are documented.
- Public task views contain no reference code, contracts, hidden inputs or labels. Selections freeze before official hidden evaluation. Empty pools remain in the task denominator.
- Generated-test syntax: one literal equality assertion against the task entry point. Invalid format and truncated generations remain logged. Expected outputs are never gold-filtered.
- Every generated-test execution gets its own bubblewrap filesystem, network and PID namespaces, a fresh Python process, a 0.5 s program timeout, 1 GiB address-space limit and process/file limits.

## Environment

Linux with unprivileged user namespaces and `bubblewrap` is required for execution. Model generation needs one available GPU; the initial experiment uses an A800. Keep Python 3.11 execution/evaluation separate from Python 3.12 generation:

```bash
uv venv --python 3.11 .local/eval-venv
uv pip install --python .local/eval-venv/bin/python -e '.[dev]'
uv venv --python 3.12 .local/generation-venv
uv pip install --python .local/generation-venv/bin/python -e '.[dev,generation]'
.local/eval-venv/bin/python -m pytest -q
.local/generation-venv/bin/python -m pytest tests/test_hf_backend.py -q
.local/eval-venv/bin/python scripts/prepare_dataset.py --output .local/dataset
HF_HUB_DISABLE_XET=1 .local/generation-venv/bin/python scripts/download_model.py
```

The actual run reused an existing owned PyTorch environment through `--system-site-packages`; exact versions are in `artifacts/environment/generation.json`, including the CUDA 12.6 PyTorch build. Installing the optional dependencies alone does not pin a CUDA wheel index or guarantee identical outputs across hardware. Evaluation dependencies are recorded in `artifacts/environment/requirements-evaluation.txt`. If a host cannot create namespaces, execution fails as infrastructure failure.

## Run E0

Read the downloaded model path from `.local/model-path.txt` and supply it below. Choose a free GPU in `CUDA_VISIBLE_DEVICES`; this example uses GPU 2. Generation has an explicit hard timeout. Do not launch it on a GPU used by someone else.

```bash
mkdir -p artifacts/runs/e0-v1/raw
CUDA_VISIBLE_DEVICES=2 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .local/eval-venv/bin/python scripts/run_monitored.py \
  --receipt artifacts/runs/e0-v1/generation.process.json \
  --log .local/e0-generation.log --timeout 3600 --gpu 2 -- \
  .local/generation-venv/bin/python -m tgselect.generation \
  --views .local/dataset/public/views.jsonl --config configs/e0-e1-v1.json \
  --split e0 --model-path /absolute/path/from/model-path.txt \
  --output artifacts/runs/e0-v1/raw/generation.jsonl
.local/eval-venv/bin/python -m tgselect.experiment matrix \
  --views .local/dataset/public/views.jsonl --generation artifacts/runs/e0-v1/raw/generation.jsonl \
  --config configs/e0-e1-v1.json --split e0 --output artifacts/runs/e0-v1/raw/tasks.jsonl
.local/eval-venv/bin/python -m tgselect.experiment select \
  --tasks artifacts/runs/e0-v1/raw/tasks.jsonl --config configs/e0-e1-v1.json \
  --output artifacts/runs/e0-v1/raw/selections.jsonl
.local/eval-venv/bin/python -m tgselect.experiment evaluate \
  --tasks artifacts/runs/e0-v1/raw/tasks.jsonl --snapshot .local/dataset/private/mbppplus.jsonl \
  --selections artifacts/runs/e0-v1/raw/selections.jsonl --config configs/e0-e1-v1.json \
  --output-dir artifacts/runs/e0-v1/evaluation
.local/eval-venv/bin/python -m tgselect.experiment analyse \
  --tasks artifacts/runs/e0-v1/raw/tasks.jsonl --selections artifacts/runs/e0-v1/raw/selections.jsonl \
  --labels artifacts/runs/e0-v1/evaluation/labels.json --config configs/e0-e1-v1.json \
  --output-dir artifacts/runs/e0-v1
```

Replay `select` to a new output and compare SHA-256 hashes; generated programs do not need to run again for a selection replay. Resume generation is explicit and validates full request identity. Crashed runs retain receipts and require diagnosis before continuation.

After all stages complete, run `scripts/finalize_run.py --run-dir artifacts/runs/e0-v1` with the evaluation interpreter. It checks the hash chain and re-derives summary metrics, then exports usage, task indicators and compact receipts. Resource peaks are observations sampled roughly every 30 seconds; short-lived peaks can be missed.

Install the optional `plots` dependencies and run `scripts/plot_results.py --run-dir artifacts/runs/e0-v1` to export the scientific SVG. The plot uses saved summary intervals and explicitly distinguishes oracle coverage from E2 reviewer accuracy.

After a reliable E0, repeat with `--split e1` and a new run directory. Keep E0 out of the E1 inference denominator. Every comparison uses whole tasks as the sampling unit, with task-paired intervals; the 20 random seeds are averaged within each task before bootstrap.

## Saved evidence and limits

Version control contains source, protocol, unit tests, environment metadata and compact result artifacts. Raw generations, execution records and hidden outcome files use a separate compressed evidence archive. The archive excludes the official benchmark snapshot, reference implementations, hidden test inputs and credentials. Restore it only from the recorded release asset after verifying the archive SHA-256 against the committed manifest. A clone plus that archive supports replay of selection and reanalysis; independently rerunning hidden evaluation still requires preparing the pinned official dataset.

Use a separate checkout to restore the archive, because its paths reproduce the frozen run directories. Compare each extracted file's SHA-256 against the member list in the archive manifest. The original `generation.jsonl`, `tasks.jsonl` and `selections.jsonl` must remain unchanged. To replay selection, choose a new output such as `.local/replayed-selections.jsonl` and compare its SHA-256 to the run's `selection-replay.json`. The compact checker verifies saved numerical results and does not itself regenerate model samples or execute the official benchmark.

Oracle pair coverage measures available rescue space. It is not an observed real-reviewer accuracy improvement, and finite MBPP+ tests do not prove semantic correctness. Development observations cannot establish a small effect or general novelty. No human-read attestation or independent cross-model research review is claimed.

## Method sources

- [EvalPlus official repository](https://github.com/evalplus/evalplus)
- [Qwen2.5-Coder-7B-Instruct model card](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct)
- [ACES v2, sections 2.1, 3.1 and Algorithm 1](https://arxiv.org/html/2604.03922v2)

ACES-C implementation uses the paper's formula. Candidate tie-breaking and all-zero-weight fallback follow this project's protocol. CodeT was source-audited but is not implemented or claimed as reproduced.
