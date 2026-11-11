from pathlib import Path

import pytest

from research.inverse_formula.probe import (
    DLT, SSQ, Formula, compare, experiment, load_history, normalize,
)

BASE = Path(__file__).parents[1] / "research" / "inverse_formula"


def test_training_exact_and_holdout_is_unseen():
    for game, file in [(SSQ, "ssq_2026.txt"), (DLT, "dlt_2026.txt")]:
        result = experiment(BASE / file, game)
        assert result["train_size"] == 60
        assert result["holdout_size"] == 30
        assert all(t["train_exact"] == 60 for t in result["formulas"])
        assert result["train_issues"][1] < result["holdout_issues"][0]
        assert result["status"] == "EXPLORATORY_ONLY_NO_EDGE"


def test_multiple_perfect_training_formulas_disagree_on_future():
    draws, _ = load_history(BASE / "ssq_2026.txt", SSQ)
    train = draws[-90:-30]
    a = Formula(train, SSQ, 65537, 0)
    b = Formula(train, SSQ, 65537, 1)
    assert all(a.predict(i) == (row.front, row.back) for i, row in enumerate(train))
    assert all(b.predict(i) == (row.front, row.back) for i, row in enumerate(train))
    assert a.predict(60) != b.predict(60)


def test_future_leakage_is_impossible_without_refit():
    draws, _ = load_history(BASE / "dlt_2026.txt", DLT)
    first = Formula(draws[-90:-30], DLT, 257, 0)
    prediction = first.predict(60)
    # Altering a held-out outcome cannot influence the trained formula.
    altered = list(draws)
    altered[-30] = altered[-1]
    second = Formula(altered[-90:-30], DLT, 257, 0)
    assert second.predict(60) == prediction


def test_validation_rejects_corrupt_rows(tmp_path):
    dst = tmp_path / "bad.txt"
    dst.write_text("26100:0101010203+0102;26101:0102030405+0102")
    with pytest.raises(ValueError, match="invalid ticket"):
        load_history(dst, DLT)
    dst.write_text("26100:0102030405+0102;26100:0102030405+0102")
    with pytest.raises(ValueError, match="unique contiguous"):
        load_history(dst, DLT)


def test_legal_unique_normalization_and_d2():
    assert normalize([0, 0, 0, 36, 36], 35) == (1, 2, 3, 4, 35)
    assert compare(((1, 2, 3, 4, 5), (1, 2)), type("D", (), {"front": (1, 2, 3, 4, 5), "back": (1, 2)})()) == {
        "full": 1, "d2": 1, "front_hits": 5, "back_hits": 2}


# Multi-family inverse formula mining: do not confuse post-hoc reconstruction
# with a genuinely past-only prediction.
from research.inverse_formula.reverse_search import (
    METHODS, apply_formula, oracle_reconstruction, reverse_fit,
    select_from_past, walk_forward,
)


def test_inverse_families_reconstruct_all_observed_targets_posthoc():
    for game, file in [(SSQ, "ssq_2026.txt"), (DLT, "dlt_2026.txt")]:
        draws, _ = load_history(BASE / file, game)
        oracle = oracle_reconstruction(draws, game)
        assert oracle["retrospective_fit_trials"] == (len(draws) - 2) * len(METHODS)
        assert oracle["retrospective_exact_matches"] == oracle["retrospective_fit_trials"]
        assert oracle["retrospective_exact_rate"] == 1.0
        for method in METHODS:
            formula = reverse_fit(draws, game, 32, method)
            assert apply_formula(formula, draws[:32], game) == (
                draws[32].front, draws[32].back
            )


def test_inverse_selection_uses_only_past_draws_and_legal_tickets():
    draws, _ = load_history(BASE / "ssq_2026.txt", SSQ)
    cutoff = 60
    chosen, evidence = select_from_past(draws[:cutoff], SSQ)
    prediction = apply_formula(chosen, draws[:cutoff], SSQ)
    assert chosen.anchor_index < cutoff - 5
    assert evidence["post_anchor_known_evaluations"] >= 5
    assert len(prediction[0]) == 6 and len(set(prediction[0])) == 6
    assert len(prediction[1]) == 1 and len(set(prediction[1])) == 1
    # Changing or replacing a future target cannot alter a past-only call.
    tampered = list(draws)
    tampered[cutoff] = draws[cutoff + 1]
    chosen_again, evidence_again = select_from_past(tampered[:cutoff], SSQ)
    assert (chosen_again, evidence_again) == (chosen, evidence)
    assert apply_formula(chosen_again, tampered[:cutoff], SSQ) == prediction
    with pytest.raises(ValueError, match="past-only"):
        apply_formula(chosen, draws[:cutoff - 1], SSQ)


def test_inverse_walk_forward_scores_only_after_forecasts():
    draws, _ = load_history(BASE / "dlt_2026.txt", DLT)
    report = walk_forward(draws[:40], DLT, min_history=30)
    assert report["evaluated_issues"] == 10
    assert report["status"] == "RESEARCH_ONLY_NO_ESTABLISHED_EDGE"
    for row in report["per_issue_audit"]:
        assert row["asof_issue"] < row["issue"]
        assert row["formula_anchor_issue"] <= row["asof_issue"]
        assert row["score"]["full"] in (0, 1)
