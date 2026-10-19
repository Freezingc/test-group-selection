"""Synthetic unit fixtures only: these are never natural experiment evidence."""

from copy import deepcopy
import json

import pytest

from tgselect import analysis


SELECTORS = ("uniform", "aces_c", "dedup_uniform", "group_equal", "group_rep")


def synthetic_record(name="gain", empty=False):
    candidates = [] if empty else [
        {"candidate_id": "base", "source": "synthetic wrong source"},
        {"candidate_id": "correct", "source": "synthetic correct source"},
        {"candidate_id": "wrong", "source": "synthetic other wrong source"},
    ]
    selection = {
        "base": None if empty else "base",
        "top2": [] if empty else ["base", "wrong"],
        "diverse": [] if empty else ["base", "wrong"],
        "perturbed": [] if empty else ["base", "correct"],
        "raw_w": [] if empty else ["base", "correct"],
    }
    selections = {}
    for selector in SELECTORS:
        selections[selector] = deepcopy(selection)
        for seed in range(20):
            random_selection = deepcopy(selection)
            if not empty and seed >= 10:
                random_selection["perturbed"] = ["base", "wrong"]
            selections[f"{selector}__random_{seed}"] = random_selection
    return {
        "task_id": f"synthetic/{name}",
        "labels": {} if empty else {"base": 0, "correct": 1, "wrong": 0},
        "candidates": candidates,
        "matrix": [] if empty else [[1, 0], [1, 0], [0, 0]],
        "selections": selections,
    }


def synthetic_four_task_fixture():
    gain = synthetic_record()
    loss = synthetic_record("loss")
    loss["matrix"] = [[1, 0], [0, 1], [0, 0]]
    correct = synthetic_record("base_correct")
    correct["labels"] = {"base": 1, "correct": 0, "wrong": 1}
    correct["candidates"][2]["source"] = correct["candidates"][0]["source"]
    for selector in SELECTORS:
        loss["selections"][selector].update(
            top2=["base", "correct"], diverse=["base", "correct"],
            perturbed=["base", "wrong"], raw_w=["base"],
        )
        correct["selections"][selector].update(raw_w=["base", "wrong"])
        for seed in range(20):
            loss["selections"][f"{selector}__random_{seed}"]["perturbed"] = ["base", "correct"]
    return [gain, loss, correct, synthetic_record("empty", empty=True)]


def test_all_task_denominator_rescue_ceiling_and_gain_loss_decomposition():
    summary = analysis.summarize(synthetic_four_task_fixture(), bootstrap_replicates=200)
    assert summary["n_tasks"] == 4
    assert summary["pool"]["coverage"] == {"q": 3, "n": 4, "rate": 0.75}
    assert summary["pool"]["candidate_count"]["total"] == 9
    assert summary["pool"]["unique_source_count"]["total"] == 8
    result = summary["selectors"]["uniform"]
    assert result["base_accuracy"] == {"q": 1, "n": 4, "rate": 0.25}
    method = result["methods"]["perturbed"]
    assert method["coverage"] == {"q": 2, "n": 4, "rate": 0.5}
    assert method["u"] == {"q": 1, "n": 4, "rate": 0.25}
    assert {k: v["q"] for k, v in method["vs_top2"].items()} == {
        "gain": 1, "loss": 1, "both": 1, "neither": 1,
    }
    mechanisms = result["mechanisms"]
    assert mechanisms["baseline_wrong_pool_correct"]["q"] == 2
    assert mechanisms["identical_row_blind_spot"]["q"] == 1
    assert mechanisms["no_alternative_winner"]["q"] == 3
    assert result["raw_w"]["coverage"]["q"] == 2


def test_random_seed_mean_is_formed_within_task_before_paired_bootstrap():
    records = [synthetic_record("a"), synthetic_record("b")]
    summary = analysis.summarize(records, bootstrap_replicates=1000, seed=13)
    result = summary["selectors"]["uniform"]
    random = result["random"]
    assert random["n_seeds"] == 20
    assert random["coverage_mean"] == {"q": 1.0, "n": 2, "rate": 0.5}
    assert len(random["coverage_by_seed"]) == 20
    paired = result["paired_differences"]["perturbed_minus_random_mean"]
    assert paired["difference"] == 0.5
    assert paired["ci95"] == [0.5, 0.5]
    assert paired["n"] == 2


def test_bootstrap_is_reproducible_and_json_contains_no_nan():
    records = synthetic_four_task_fixture()
    first = analysis.summarize(records, bootstrap_replicates=1000, seed=91)
    assert first == analysis.summarize(records, bootstrap_replicates=1000, seed=91)
    paired = first["selectors"]["uniform"]["paired_differences"]["perturbed_minus_top2"]
    assert paired["difference"] == 0
    assert paired["ci95"][0] < 0 < paired["ci95"][1]
    json.dumps(first, allow_nan=False)


def test_empty_dataset_reports_missing_rates_instead_of_nan():
    summary = analysis.summarize([], bootstrap_replicates=100)
    assert summary["n_tasks"] == 0
    assert summary["pool"]["coverage"]["rate"] is None
    paired = summary["selectors"]["uniform"]["paired_differences"]["perturbed_minus_top2"]
    assert paired["ci95"] is None
    json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize("broken", ["missing_label", "missing_seed", "duplicate_task", "bad_row"])
def test_incomplete_or_misaligned_evaluation_records_are_rejected(broken):
    records = [synthetic_record()]
    if broken == "missing_label":
        del records[0]["labels"]["correct"]
    elif broken == "missing_seed":
        del records[0]["selections"]["uniform__random_19"]
    elif broken == "duplicate_task":
        records.append(deepcopy(records[0]))
    else:
        records[0]["matrix"].pop()
    with pytest.raises(ValueError):
        analysis.summarize(records, bootstrap_replicates=100)


def test_markdown_labels_synthetic_stage_and_limits_candidate_coverage_claims():
    summary = analysis.summarize(synthetic_four_task_fixture(), bootstrap_replicates=100)
    markdown = analysis.render_markdown(summary, stage="synthetic-unit-fixture")
    assert markdown.startswith("## Material Passport")
    assert "synthetic-unit-fixture" in markdown
    assert "探索" in markdown
    assert "审核" in markdown
    assert "20" in markdown
    assert "2/4" in markdown
    assert "95%" in markdown
