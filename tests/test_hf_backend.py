"""CPU-only sampler and fake-decoder checks; no natural model is loaded."""

from types import SimpleNamespace

import pytest
torch = pytest.importorskip('torch', reason='local generation dependencies are optional')

from tgselect import hf_backend


def generators(seeds):
    return [torch.Generator(device="cpu").manual_seed(seed) for seed in seeds]


def draw_sequence(seeds, steps=20):
    streams = generators(seeds)
    logits = torch.tensor([[0.1, 0.7, 0.2, -0.3]]).repeat(len(seeds), 1)
    return torch.stack([hf_backend.sample_next(logits, streams, 0.7, 0.95) for _ in range(steps)])


def test_each_request_rng_is_independent_of_batch_size_order_and_global_rng():
    original_global_state = torch.random.get_rng_state().clone()
    alone = draw_sequence([17])[:, 0]
    batched = draw_sequence([99, 17, 42])[:, 1]
    reordered = draw_sequence([17, 99])[:, 0]
    assert torch.equal(alone, batched)
    assert torch.equal(alone, reordered)
    assert torch.equal(original_global_state, torch.random.get_rng_state())


def test_top_p_keeps_at_least_one_token_even_below_its_probability():
    logits = torch.tensor([[10.0, 0.0, -2.0]]).repeat(10, 1)
    chosen = hf_backend.sample_next(logits, generators(range(10)), 0.7, 0.01)
    assert chosen.tolist() == [0] * 10


def test_top_p_ties_use_stable_token_order_and_minimal_prefix_at_exact_boundary():
    logits = torch.zeros((40, 4))
    chosen = hf_backend.sample_next(logits, generators(range(40)), 1.0, 0.5)
    assert set(chosen.tolist()) == {0, 1}
    assert torch.equal(chosen, hf_backend.sample_next(logits, generators(range(40)), 1.0, 0.5))


def test_zero_temperature_argmax_does_not_advance_generators():
    streams = generators([3, 4])
    before = [stream.get_state().clone() for stream in streams]
    chosen = hf_backend.sample_next(torch.tensor([[1.0, 1.0], [0.0, 1.0]]), streams, 0.0, 1.0)
    assert chosen.tolist() == [0, 1]
    assert all(torch.equal(state, stream.get_state()) for state, stream in zip(before, streams))


@pytest.mark.parametrize("logits,temperature,top_p", [
    ([[0.0, 1.0]], -0.1, 0.95),
    ([[0.0, 1.0]], 0.7, 0.0),
    ([[0.0, 1.0]], 0.7, 1.01),
    ([[float('nan'), 1.0]], 0.7, 0.95),
    ([[float('-inf'), float('-inf')]], 0.7, 0.95),
])
def test_invalid_sampling_inputs_fail_explicitly(logits, temperature, top_p):
    with pytest.raises(ValueError):
        hf_backend.sample_next(torch.tensor(logits), generators([1]), temperature, top_p)


class FakeTokenizer:
    eos_token_id = 9
    pad_token_id = 0

    def __call__(self, prompts, **kwargs):
        assert kwargs == {"return_tensors": "pt", "padding": True, "add_special_tokens": False}
        tokens = [[int(part) for part in prompt.split()] for prompt in prompts]
        width = max(map(len, tokens))
        return {
            "input_ids": torch.tensor([[0] * (width - len(row)) + row for row in tokens]),
            "attention_mask": torch.tensor([[0] * (width - len(row)) + [1] * len(row) for row in tokens]),
        }

    def decode(self, ids, **kwargs):
        assert kwargs == {"skip_special_tokens": True, "clean_up_tokenization_spaces": False}
        return " ".join(str(token) for token in ids if token not in (0, 7, 8, 9))


class FakeModel:
    config = SimpleNamespace(eos_token_id=[7, 8], _attn_implementation="sdpa")
    generation_config = SimpleNamespace(eos_token_id=8)

    def __init__(self, first_stop=7, never_stop=False):
        self.calls = []
        self.first_stop = first_stop
        self.never_stop = never_stop

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["use_cache"] is True
        assert kwargs["logits_to_keep"] == 1
        batch = kwargs["input_ids"].shape[0]
        logits = torch.full((batch, 1, 10), float("-inf"))
        for row in range(batch):
            token = 4 if self.never_stop else (self.first_stop if row == 0 else (4 if len(self.calls) == 1 else 8))
            logits[row, 0, token] = 0.0
        return SimpleNamespace(logits=logits, past_key_values=f"cache-{len(self.calls)}")

    def eval(self):
        return self


def fake_backend(first_stop=7, never_stop=False):
    backend = object.__new__(hf_backend.HFBackend)
    backend.model = FakeModel(first_stop=first_stop, never_stop=never_stop)
    backend.tokenizer = FakeTokenizer()
    backend.device = torch.device("cpu")
    backend.temperature = 0.7
    backend.top_p = 0.95
    backend.max_tokens = 3
    backend.max_model_len = 8192
    backend.batch_size = 24
    backend.pad_id = 0
    backend.eos_ids = hf_backend._collect_eos_ids(backend.model, backend.tokenizer)
    return backend


@pytest.mark.parametrize("stop_id", [7, 8, 9])
def test_decoder_uses_left_padding_cache_and_all_eos_ids_without_sampling_finished_rows(stop_id, monkeypatch):
    backend = fake_backend(first_stop=stop_id)
    calls = []
    real_sample = hf_backend.sample_next

    def tracked_sample(logits, streams, temperature, top_p):
        calls.append([stream.initial_seed() for stream in streams])
        return real_sample(logits, streams, temperature, top_p)

    monkeypatch.setattr(hf_backend, "sample_next", tracked_sample)
    output = backend.generate(["11", "21 22"], [10, 20])
    assert calls == [[10, 20], [20]]
    assert output == [
        {"response": "", "finish_reason": "stop", "input_tokens": 1, "output_tokens": 1},
        {"response": "4", "finish_reason": "stop", "input_tokens": 2, "output_tokens": 2},
    ]
    first, second = backend.model.calls
    assert first["input_ids"].tolist() == [[0, 11], [21, 22]]
    assert first["position_ids"].tolist() == [[0, 0], [0, 1]]
    assert second["past_key_values"] == "cache-1"
    assert second["input_ids"].shape == (2, 1)
    assert second["position_ids"].tolist() == [[1], [2]]


def test_decoder_records_truncation_and_guards_context_without_running_model():
    backend = fake_backend(never_stop=True)
    backend.max_tokens = 2
    output = backend.generate(["11"], [10])
    assert output[0] == {"response": "4 4", "finish_reason": "length", "input_tokens": 1, "output_tokens": 2}
    backend.model.calls.clear()
    backend.max_model_len = 3
    with pytest.raises(ValueError, match="context"):
        backend.generate(["11 12"], [10])
    assert backend.model.calls == []


def test_constructor_uses_only_local_files_bfloat16_one_cuda_and_records_backend(monkeypatch):
    import transformers

    tokenizer_calls, model_calls = [], []
    tokenizer, model = FakeTokenizer(), FakeModel()
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", lambda *a, **kw: tokenizer_calls.append((a, kw)) or tokenizer)
    monkeypatch.setattr(transformers.AutoModelForCausalLM, "from_pretrained", lambda *a, **kw: model_calls.append((a, kw)) or model)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    backend = hf_backend.HFBackend("/offline/model", {"temperature": 0.7, "top_p": 0.95, "max_tokens": 2048})
    assert tokenizer_calls[0][1]["local_files_only"] is True
    assert tokenizer_calls[0][1]["trust_remote_code"] is False
    assert tokenizer.padding_side == "left"
    assert model_calls[0][1]["local_files_only"] is True
    assert model_calls[0][1]["trust_remote_code"] is False
    assert model_calls[0][1]["dtype"] == torch.bfloat16
    assert model_calls[0][1]["device_map"] == {"": "cuda:0"}
    assert backend.metadata["backend_version"] == hf_backend.BACKEND_VERSION
    assert backend.metadata["output_tokens_include_eos"] is True
    assert backend.metadata["vllm_output_equivalence"] is False


def test_cached_left_padded_decoder_matches_individual_greedy_tiny_qwen_models():
    # A randomly initialized tiny architecture exercises the real HF cache API;
    # no pretrained model, network access, or natural task is involved.
    from transformers import Qwen2Config, Qwen2ForCausalLM

    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(123)
        model = Qwen2ForCausalLM(Qwen2Config(
            vocab_size=32, hidden_size=32, intermediate_size=64,
            num_hidden_layers=1, num_attention_heads=4, num_key_value_heads=2,
            max_position_embeddings=64, eos_token_id=31, pad_token_id=0,
        )).eval()
    backend = fake_backend()
    backend.model = model
    backend.eos_ids = hf_backend._collect_eos_ids(model, backend.tokenizer)
    backend.temperature = 0.0
    backend.max_tokens = 3
    prompts = ["11", "21 22"]
    actual = backend.generate(prompts, [10, 20])
    expected = []
    with torch.inference_mode():
        for prompt in prompts:
            tokens = [int(part) for part in prompt.split()]
            original_count = len(tokens)
            generated = []
            finish = "length"
            for step in range(backend.max_tokens):
                logits = model(input_ids=torch.tensor([tokens]), use_cache=False, logits_to_keep=1).logits
                token = int(logits[0, -1].argmax())
                generated.append(token)
                tokens.append(token)
                if token in backend.eos_ids:
                    finish = "stop"
                    break
            expected.append({
                "response": backend.tokenizer.decode(
                    generated[:-1] if finish == "stop" else generated,
                    skip_special_tokens=True, clean_up_tokenization_spaces=False,
                ),
                "finish_reason": finish, "input_tokens": original_count, "output_tokens": len(generated),
            })
    assert actual == expected
