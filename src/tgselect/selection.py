"""Deterministic, label-free candidate selection on frozen pass matrices.

ACES-C follows arXiv:2604.03922v2, Eq. (8), using an algebraically
equivalent integer scale. Candidate-score hash ties and uniform zero-weight
fallback are this project's protocol choices, not the paper's random ties.
"""

from bisect import bisect_left, bisect_right
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import random


SELECTORS = frozenset({"uniform", "aces_c", "dedup_uniform", "group_equal", "group_rep"})


def _validate_matrix(matrix: list[list[int]], groups: list[str], selector: str) -> None:
    if selector not in SELECTORS:
        raise ValueError(f"Unknown selector: {selector!r}")
    if not all(isinstance(group, str) for group in groups):
        raise ValueError("Group labels must be strings")
    for row in matrix:
        if len(row) != len(groups):
            raise ValueError("Every matrix row must match the number of group labels")
        if any(not isinstance(value, (int, bool)) or value not in (0, 1) for value in row):
            raise ValueError("Pass matrix values must be binary integers")


def regroup(groups: list[str], seed: int) -> list[str]:
    """Assign group slots to a seeded permutation of processed column indices."""
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("Random grouping seed must be an integer")
    indices = list(range(len(groups)))
    random.Random(seed).shuffle(indices)
    result = list(groups)
    for index, group in zip(indices, groups):
        result[index] = group
    return result


def _score(
    matrix: list[list[int]], groups: list[str], selector: str,
    task_id: str, column_ids: list[int],
) -> tuple[list, dict]:
    """Return exact internal scores and JSON-compatible scoring metadata."""
    n, m = len(matrix), len(groups)
    weights: list = [0] * m
    metadata = {"selector": selector, "fallback": None, "column_ids": column_ids,
                "scoring_groups": list(groups)}
    if not n or not m:
        metadata["fallback"] = "no_candidates" if not n else "no_tests"
        metadata["column_weights"] = weights
        return [0] * n, metadata

    if selector == "uniform":
        weights = [1] * m
    elif selector == "dedup_uniform":
        seen = set()
        for j in range(m):
            pattern = tuple(row[j] for row in matrix)
            if pattern not in seen:
                seen.add(pattern)
                weights[j] = 1
    elif selector == "group_equal":
        group_sizes = Counter(groups)
        weights = [Fraction(1, group_sizes[group]) for group in groups]
    elif selector == "group_rep":
        representatives = {}
        for j, group in enumerate(groups):
            key = sha256(f"tgselect-v1:{task_id}:test:{column_ids[j]}".encode("utf-8")).digest()
            if group not in representatives or key < representatives[group][0]:
                representatives[group] = (key, j)
        for _, j in representatives.values():
            weights[j] = 1
        metadata["representative_columns"] = [column_ids[j] for j in range(m) if weights[j]]
    elif selector == "aces_c":
        passing = [sum(row[j] for row in matrix) for j in range(m)]
        retained = [j for j in range(m) if 0 < passing[j] < n]
        metadata["retained_columns"] = [column_ids[j] for j in retained]
        metadata["removed_constant_columns"] = [column_ids[j] for j in range(m) if j not in retained]
        metadata["weight_formula"] = "max(0, 2*strict_wins + ties - n_pass*n_fail)"
        metadata["weight_denominator"] = 2 * n * n
        metadata["score_scale"] = "paper_weights_times_2n_squared"
        row_totals = [sum(row[j] for j in retained) for row in matrix]
        aucs = [None] * m
        for j in retained:
            negative_scores = sorted(row_totals[i] - matrix[i][j] for i in range(n) if not matrix[i][j])
            strict_wins = ties = 0
            for i in range(n):
                if matrix[i][j]:
                    loo = row_totals[i] - 1
                    lower = bisect_left(negative_scores, loo)
                    upper = bisect_right(negative_scores, loo)
                    strict_wins += lower
                    ties += upper - lower
            pairs = passing[j] * (n - passing[j])
            aucs[j] = (2 * strict_wins + ties) / (2 * pairs)
            weights[j] = max(0, 2 * strict_wins + ties - pairs)
        metadata["loo_auc"] = aucs
        if not retained:
            metadata["fallback"] = "no_discriminating_tests"
        elif not any(weights):
            weights = [int(j in retained) for j in range(m)]
            metadata["fallback"] = "zero_positive_weights"
            metadata["score_scale"] = "uniform_retained_columns"

    values = [sum(weight * value for weight, value in zip(weights, row)) for row in matrix]
    metadata["column_weights"] = [float(weight) if isinstance(weight, Fraction) else weight for weight in weights]
    return values, metadata


def scores(
    matrix: list[list[int]], groups: list[str], selector: str = "uniform", task_id: str = "",
) -> list:
    """Score candidates in matrix-row order; no labels or source deduplication."""
    _validate_matrix(matrix, groups, selector)
    values, _ = _score(matrix, groups, selector, task_id, list(range(len(groups))))
    return [float(value) if isinstance(value, Fraction) else value for value in values]


def select_task(
    task_id: str, candidates: list[dict], matrix: list[list[int]], groups: list[str],
    *, selector: str = "uniform", random_seed: int | None = None,
) -> dict:
    """Construct source-distinct review sets of at most two candidates.

    Candidate dictionaries deliberately accept only the public fields
    ``candidate_id`` and ``source``. Hidden evaluation labels are not inputs.
    Randomization changes only the deletion groups; the selector always uses
    the true source groups and refits them on the remaining matrix.
    """
    _validate_matrix(matrix, groups, selector)
    if len(candidates) != len(matrix):
        raise ValueError("Candidates and matrix rows must have the same length")
    for candidate in candidates:
        if set(candidate) != {"candidate_id", "source"}:
            raise ValueError("Allowed candidate fields are candidate_id and source only")
        if not isinstance(candidate["candidate_id"], str) or not isinstance(candidate["source"], str):
            raise ValueError("Candidate identifiers and source must be strings")
    ids = [candidate["candidate_id"] for candidate in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("Candidate identifiers must be unique")
    effective_groups = list(groups) if random_seed is None else regroup(groups, random_seed)
    group_sizes = dict(Counter(effective_groups))
    column_ids = list(range(len(groups)))
    values, score_metadata = _score(matrix, groups, selector, task_id, column_ids)
    ties = [sha256(f"tgselect-v1:{task_id}:{cid}".encode("utf-8")).digest() for cid in ids]

    def rank(value_list):
        return sorted(range(len(candidates)), key=lambda i: (-value_list[i], ties[i]))

    ordering = rank(values)
    result = {
        "ranking": [ids[i] for i in ordering],
        "scores": [float(value) if isinstance(value, Fraction) else value for value in values],
        "base": ids[ordering[0]] if ordering else None,
        "top2": [], "diverse": [], "perturbed": [], "raw_w": [], "deletions": [],
        "group_sizes": group_sizes,
        "selector_metadata": score_metadata,
        "scoring_groups": list(groups),
        "effective_groups": effective_groups,
        "random_seed": random_seed,
    }
    if not ordering:
        return result

    source_hashes = [sha256(candidate["source"].encode("utf-8")).hexdigest() for candidate in candidates]
    representatives = {}
    for i in ordering:
        representatives.setdefault(source_hashes[i], i)
    base = ordering[0]
    base_source = source_hashes[base]
    different_sources = [i for i in representatives.values() if source_hashes[i] != base_source]
    top_alternative = different_sources[0] if different_sources else None
    diverse_alternative = next((i for i in different_sources if matrix[i] != matrix[base]), top_alternative)

    def pair(alternative):
        return [ids[base]] if alternative is None else [ids[base], ids[alternative]]

    result["top2"] = pair(top_alternative)
    result["diverse"] = pair(diverse_alternative)
    votes = Counter()
    for group in group_sizes:
        retained_columns = [j for j, label in enumerate(effective_groups) if label != group]
        deleted_matrix = [[row[j] for j in retained_columns] for row in matrix]
        deleted_groups = [groups[j] for j in retained_columns]
        deleted_scores, deleted_metadata = _score(deleted_matrix, deleted_groups, selector, task_id, retained_columns)
        deleted_order = rank(deleted_scores)
        winner = deleted_order[0]
        votes[source_hashes[winner]] += 1
        result["deletions"].append({
            "group": group, "ranking": [ids[i] for i in deleted_order],
            "winner": ids[winner], "selector_metadata": deleted_metadata,
        })

    original_rank = {i: position for position, i in enumerate(ordering)}
    alternatives = [source for source in votes if source != base_source]
    if alternatives:
        selected_source = min(alternatives, key=lambda source: (
            -votes[source], original_rank[representatives[source]], ties[representatives[source]],
        ))
        alternative = representatives[selected_source]
    else:
        alternative = top_alternative
    result["perturbed"] = pair(alternative)
    raw_sources = set(votes) | {base_source}
    result["raw_w"] = [ids[i] for source, i in representatives.items() if source in raw_sources]
    result["source_votes"] = {ids[i]: votes[source] for source, i in representatives.items() if votes[source]}
    return result
