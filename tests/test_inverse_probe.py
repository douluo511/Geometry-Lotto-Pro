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
