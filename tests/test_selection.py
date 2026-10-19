"""Selection checks use synthetic matrices, never evidence of research efficacy."""

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import importlib
import random

import pytest


@pytest.fixture
def selection():
    # A missing implementation should fail a behavior test, not collection.
    try:
        return importlib.import_module("tgselect.selection")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Selection feature is missing: {exc}")


def candidate(candidate_id, source=None):
    return {"candidate_id": candidate_id, "source": source or f"def f():\n    return {candidate_id!r}\n"}


def test_aces_c_matches_hand_computed_auc_half_credit_and_variance():
    try:
        selection = importlib.import_module("tgselect.selection")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Selection feature is missing: {exc}")
    matrix = [[1, 1, 1], [1, 1, 0], [1, 0, 0], [0, 0, 0]]
    # AUC=(5/6, 7/8, 5/6), w=(2,3,2)/32. Common integer scaling.
    assert selection.scores(matrix, ["g1", "g2", "g3"], "aces_c", "aces") == [7, 5, 2, 0]


def test_aces_c_removes_constant_columns_before_uniform_fallback(selection):
    # Only the middle column discriminates. Its LOO AUC is exactly 1/2.
    assert selection.scores([[1, 0, 1], [1, 1, 1]], ["g"] * 3, "aces_c", "x") == [0, 1]


def test_aces_c_zero_positive_weights_fall_back_without_nan(selection):
    assert selection.scores([[1, 0], [0, 1]], ["a", "b"], "aces_c", "x") == [1, 1]
    assert selection.scores([[1, 0], [1, 0]], ["a", "b"], "aces_c", "x") == [0, 0]


@pytest.mark.parametrize("selector", ["uniform", "aces_c", "dedup_uniform", "group_equal", "group_rep"])
def test_empty_candidate_pool_is_an_explicit_failure(selection, selector):
    result = selection.select_task("empty", [], [], ["a", "a", "b"], selector=selector)
    assert result["base"] is None
    for field in ["ranking", "scores", "top2", "diverse", "perturbed", "raw_w", "deletions"]:
        assert result[field] == []
    assert result["group_sizes"] == {"a": 2, "b": 1}


@pytest.mark.parametrize("selector", ["uniform", "aces_c", "dedup_uniform", "group_equal", "group_rep"])
def test_zero_tests_rank_by_same_fixed_order_and_keep_distinct_sources(selection, selector):
    candidates = [candidate("a"), candidate("b"), candidate("c")]
    result = selection.select_task("ties", candidates, [[], [], []], [], selector=selector)
    assert result["ranking"] == ["c", "b", "a"]
    assert result["scores"] == [0, 0, 0]
    assert result["base"] == "c"
    assert result["top2"] == result["diverse"] == result["perturbed"] == ["c", "b"]
    assert result["raw_w"] == ["c"]
    assert result["deletions"] == []


@pytest.mark.parametrize("selector", ["uniform", "aces_c", "dedup_uniform", "group_equal", "group_rep"])
def test_identical_rows_never_create_an_alternative_deletion_winner(selection, selector):
    result = selection.select_task(
        "ties", [candidate("a"), candidate("b"), candidate("c")],
        [[1, 0, 1]] * 3, ["one", "two", "two"], selector=selector,
    )
    assert result["ranking"] == ["c", "b", "a"]
    assert result["raw_w"] == ["c"]
    assert all(item["winner"] == "c" for item in result["deletions"])
    assert result["perturbed"] == ["c", "b"]


def test_deletion_refits_aces_instead_of_only_removing_old_contribution(selection):
    matrix = [[1, 0, 0, 1, 0], [1, 0, 0, 0, 0], [1, 0, 0, 1, 1],
              [0, 1, 1, 0, 0], [0, 0, 0, 0, 0]]
    result = selection.select_task("refit", [candidate(str(i)) for i in range(5)], matrix,
                                   ["drop", "b", "c", "d", "e"], selector="aces_c")
    assert result["base"] == "2"
    deletion = next(item for item in result["deletions"] if item["group"] == "drop")
    assert deletion["winner"] == "3"  # Frozen weights would still choose row 2.
    assert selection.scores([row[1:] for row in matrix], ["b", "c", "d", "e"], "aces_c", "refit") == [0, 0, 1, 2, 0]


def test_source_duplicates_collapse_only_in_review_sets(selection):
    src = "def f():\n    return 1\n"
    result = selection.select_task("copies", [candidate("a", src), candidate("b", src), candidate("c")],
                                   [[1, 1], [1, 1], [0, 0]], ["x", "y"])
    assert len(result["ranking"]) == 3
    assert result["scores"] == [2, 2, 0]
    assert result["top2"] == result["diverse"] == result["perturbed"] == [result["base"], "c"]
    assert len(result["raw_w"]) == 1


def test_delete_votes_aggregate_by_source_and_choose_original_rank_representative(selection):
    # An algebraic stress fixture with conflicting rows for two source aliases.
    # Selection must aggregate source identity even if upstream execution varied.
    shared = "def f():\n    return 1\n"
    candidates = [candidate("base"), candidate("alias1", shared), candidate("alias2", shared), candidate("other")]
    matrix = [[1, 1, 0, 0, 1, 1], [1, 0, 0, 0, 1, 1],
              [0, 1, 1, 0, 0, 1], [1, 1, 1, 0, 1, 0]]
    result = selection.select_task("vote-case", candidates, matrix, [str(i) for i in range(6)])
    assert result["ranking"] == ["base", "other", "alias2", "alias1"]
    assert [item["winner"] for item in result["deletions"]] == ["alias2", "alias1", "base", "base", "alias2", "other"]
    assert result["top2"] == ["base", "other"]
    assert result["perturbed"] == ["base", "alias2"]
    assert result["raw_w"] == ["base", "other", "alias2"]


def test_behavior_diversity_skips_identical_rows_but_keeps_source_fallback(selection):
    candidates = [candidate("a"), candidate("b"), candidate("c")]
    result = selection.select_task("ties", candidates, [[0, 0], [1, 1], [1, 1]], ["g", "g"])
    assert result["top2"] == ["c", "b"]
    assert result["diverse"] == ["c", "a"]


def test_single_source_cannot_manufacture_second_review_candidate(selection):
    src = "def f():\n    return 1\n"
    result = selection.select_task("same", [candidate("a", src), candidate("b", src)], [[1], [1]], ["g"])
    assert result["top2"] == result["diverse"] == result["perturbed"] == [result["base"]]


def test_execution_column_dedup_counts_each_distinct_pattern_once(selection):
    matrix = [[1, 1, 0], [0, 0, 1]]
    assert selection.scores(matrix, ["a", "a", "b"], "uniform", "x") == [2, 1]
    assert selection.scores(matrix, ["a", "a", "b"], "dedup_uniform", "x") == [1, 1]


def test_group_equal_gives_one_total_weight_per_group(selection):
    assert selection.scores([[1, 0, 0], [0, 1, 1]], ["large", "large", "small"], "group_equal", "x") == [0.5, 1.5]


def test_group_representative_retains_original_test_identity_after_deleting_other_group(selection):
    # For task rep-case, test hashes order indices 2 < 3 and 1 < 0.
    result = selection.select_task("rep-case", [candidate("a"), candidate("b")],
                                   [[0, 0, 1, 0], [0, 0, 0, 1]],
                                   ["drop", "drop", "keep", "keep"], selector="group_rep")
    assert result["scores"] == [1, 0]
    assert next(d for d in result["deletions"] if d["group"] == "drop")["winner"] == "a"


def test_random_groups_match_all_processed_sizes_without_reordering_matrix(selection):
    groups = ["large"] * 5 + ["medium"] * 3 + ["one"]
    original = groups[:]
    state = random.getstate()
    outputs = [selection.regroup(groups, seed) for seed in range(20)]
    assert all(Counter(output) == Counter(groups) for output in outputs)
    assert outputs[7] == selection.regroup(groups, 7)
    assert any(output != groups for output in outputs)
    assert groups == original
    assert random.getstate() == state
    candidates = [candidate("a"), candidate("b")]
    matrix = [[1] * 6 + [0] * 3, [0] * 6 + [1] * 3]
    result = selection.select_task("random", candidates, matrix, groups, random_seed=7)
    assert result["scores"] == [6, 3]
    assert result["group_sizes"] == dict(Counter(groups))
    assert result == selection.select_task("random", candidates, matrix, groups, random_seed=7)


@pytest.mark.parametrize("selector", ["uniform", "aces_c", "dedup_uniform", "group_equal", "group_rep"])
def test_random_control_keeps_original_selector_and_base_ranking_fixed(selection, selector):
    candidates = [candidate("a"), candidate("b"), candidate("c")]
    groups = ["large"] * 5 + ["medium"] * 3 + ["one"]
    matrix = [[1] * 6 + [0] * 3, [0] * 6 + [1] * 3, [0, 1, 0, 1, 0, 1, 0, 1, 0]]
    real = selection.select_task("control", candidates, matrix, groups, selector=selector)
    for seed in range(20):
        control = selection.select_task("control", candidates, matrix, groups,
                                        selector=selector, random_seed=seed)
        for field in ["scores", "base", "ranking", "top2", "diverse"]:
            assert control[field] == real[field], (selector, seed, field)


@pytest.mark.parametrize("selector", ["group_equal", "group_rep"])
def test_random_deletions_refit_remaining_true_source_groups(selection, selector):
    candidates = [candidate("a"), candidate("b"), candidate("c")]
    groups = ["large"] * 5 + ["medium"] * 3 + ["one"]
    matrix = [[1] * 6 + [0] * 3, [0] * 6 + [1] * 3, [0, 1, 0, 1, 0, 1, 0, 1, 0]]
    control = selection.select_task("control", candidates, matrix, groups,
                                    selector=selector, random_seed=7)
    assert control["scoring_groups"] == groups
    assert control["selector_metadata"]["scoring_groups"] == groups
    for deletion in control["deletions"]:
        retained = [j for j, group in enumerate(control["effective_groups"]) if group != deletion["group"]]
        metadata = deletion["selector_metadata"]
        true_groups = [groups[j] for j in retained]
        assert metadata["column_ids"] == retained
        assert metadata["scoring_groups"] == true_groups
        if selector == "group_equal":
            sizes = Counter(true_groups)
            assert metadata["column_weights"] == [1 / sizes[group] for group in true_groups]
        else:
            selected = metadata["representative_columns"]
            assert len(selected) == len(set(true_groups))
            assert len({groups[j] for j in selected}) == len(selected)
            for chosen in selected:
                same_source = [j for j in retained if groups[j] == groups[chosen]]
                expected = min(same_source, key=lambda j: sha256(f"tgselect-v1:control:test:{j}".encode()).digest())
                assert chosen == expected


def test_candidate_input_order_cannot_change_ties(selection):
    candidates = [candidate("a"), candidate("b"), candidate("c")]
    original = selection.select_task("ties", candidates, [[1], [1], [1]], ["g"])
    reversed_result = selection.select_task("ties", list(reversed(candidates)), [[1], [1], [1]], ["g"])
    assert original["ranking"] == reversed_result["ranking"] == ["c", "b", "a"]
    expected = sorted(["a", "b", "c"], key=lambda cid: sha256(f"tgselect-v1:ties:{cid}".encode()).digest())
    assert original["ranking"] == expected


def test_selection_does_not_mutate_frozen_inputs(selection):
    candidates = [candidate("a"), candidate("b")]
    matrix, groups = [[1, 0], [0, 1]], ["a", "b"]
    before = deepcopy((candidates, matrix, groups))
    selection.select_task("x", candidates, matrix, groups, random_seed=42)
    assert (candidates, matrix, groups) == before


def test_hidden_labels_have_no_accepted_selection_interface(selection):
    with pytest.raises(TypeError):
        selection.select_task("x", [candidate("a")], [[1]], ["g"], gold_labels=[1])
    leaked = {**candidate("a"), "gold_label": 1}
    with pytest.raises(ValueError, match="candidate fields"):
        selection.select_task("x", [leaked], [[1]], ["g"])


@pytest.mark.parametrize("matrix,groups", [([[1, 2]], ["a", "b"]), ([[1]], []), ([[1], []], ["a"])])
def test_malformed_matrices_are_rejected_instead_of_silently_truncated(selection, matrix, groups):
    with pytest.raises(ValueError):
        selection.scores(matrix, groups, "uniform", "x")


def test_row_count_duplicate_ids_and_unknown_selector_are_rejected(selection):
    with pytest.raises(ValueError):
        selection.select_task("x", [candidate("a")], [], [])
    with pytest.raises(ValueError):
        selection.select_task("x", [candidate("a"), candidate("a")], [[], []], [])
    with pytest.raises(ValueError):
        selection.scores([[1]], ["g"], "unknown", "x")
