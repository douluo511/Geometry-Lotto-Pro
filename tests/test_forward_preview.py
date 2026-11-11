"""Forward preview checks: no future leak, overwrite, source/target mismatch."""
from copy import deepcopy
from pathlib import Path

import pytest

from research.inverse_formula import forward_preview as preview
from research.inverse_formula.probe import SSQ, DLT, Draw


def test_current_verified_ssq_dlt_targets_are_distinct_and_not_yet_drawn():
    result = preview.run()
    assert result["target_issue_pair"] == {"SSQ": 2026130, "DLT": 26130}
    for game in (SSQ, DLT):
        x = result["forecasts"][game.name]
        assert x["prior_confirmed_issue"] + 1 == x["target_issue"]
        assert x["historical_in_memory_rows"] >= 90
        assert len(x["issuer_result_reference_urls"]) == 2
        assert x["official_target_and_cutoff_verified"] is False
        assert x["formal_a"] == 0
        assert x["research_status"] == "NO_EDGE"
        assert x["research_null"]["not_formal_v47_null"] is True
        assert x["paid_model_calls"] == 0
        p = x["prediction"]
        assert len(p["front"]) == game.front_pick
        assert len(p["back"]) == game.back_pick
        assert len(p["d2_pair"]) == 2
        assert set(p["d2_pair"]).issubset(p["front"])
        assert p["front"] == sorted(set(p["front"]))
        assert p["back"] == sorted(set(p["back"]))


def test_manual_latest_dlt_issue_is_appended_only_in_memory():
    latest = preview.LATEST_DRAW["DLT"]
    rows, original, flag = preview.candidate_history(DLT, latest)
    assert rows[-1].issue == 26129
    assert len(rows) == 91
    assert flag == "APPENDED_MANUALLY_CORROBORATED_LATEST_TO_COPY"
    assert original


def test_source_manually_entered_latest_result_cannot_replace_known_issue():
    original = deepcopy(preview.LATEST_DRAW["SSQ"])
    original["front"] = [1, 2, 3, 4, 5, 6]
    with pytest.raises(ValueError, match="conflicts"):
        preview.candidate_history(SSQ, original)


def test_cannot_claim_asof_future_target_without_consecutive_history():
    altered = deepcopy(preview.LATEST_DRAW["DLT"])
    altered["issue"] = 26131
    altered["target_issue"] = 26132
    with pytest.raises(ValueError, match="missing or future"):
        preview.candidate_history(DLT, altered)


def test_never_fabricates_postdraw_score_at_forecast_time():
    x = preview.forecast_research(DLT, preview.LATEST_DRAW["DLT"])
    assert "outcome" not in x
    assert "score" not in x
    assert x["independent_predraw_timestamp_approved"] is False
    assert x["issuer_page_raw_bytes_authenticated"] is False


def test_postdraw_same_issue_scoring_and_research_null_determinism():
    x = preview.forecast_research(DLT, preview.LATEST_DRAW["DLT"])
    front = x["prediction"]["front"]
    back = x["prediction"]["back"]
    # Pure arithmetic synthetic example, not a draw result.
    result = preview.score_if_future_publication_confirmed(x, {
        "issue": 26130, "front": front, "back": back
    })
    assert result["research_full_hit"] == 1
    assert result["research_d2_hit"] == 1
    assert result["research_front_hits"] == 5
    assert result["research_back_hits"] == 2
    assert result["issuer_outcome_authentication"] == "UNVERIFIED_BY_THIS_FUNCTION"
    assert result["formal_a"] == 0


def test_postdraw_rejects_wrong_issue_and_changed_null_control():
    x = preview.forecast_research(SSQ, preview.LATEST_DRAW["SSQ"])
    base = {"issue": 2026130, "front": [1, 2, 3, 4, 5, 6], "back": [7]}
    with pytest.raises(ValueError, match="issue"):
        preview.score_if_future_publication_confirmed(
            x, {**base, "issue": 2026129})
    tampered = deepcopy(x)
    tampered["research_null"]["d2_pair"] = [1, 2]
    if tampered["research_null"]["d2_pair"] == x["research_null"]["d2_pair"]:
        tampered["research_null"]["d2_pair"] = [2, 3]
    with pytest.raises(ValueError, match="control changed"):
        preview.score_if_future_publication_confirmed(tampered, base)


def test_replay_is_deterministic_excluding_untrusted_clock():
    a = preview.run()["forecasts"]
    b = preview.run()["forecasts"]
    for game in ("SSQ", "DLT"):
        assert a[game]["content_sha256"] == b[game]["content_sha256"]
        assert a[game]["prediction"] == b[game]["prediction"]
