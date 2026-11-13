"""Independent fail-closed M1/M2/M3+fusion review of a synthetic V4.7 run.

Recomputes fair probabilities, Monte-Carlo arithmetic, paired synthetic D2
comparison, real geometry adapter/experimental invariants, fixed NULL roster,
and physics=nonpredictive. Neither this reviewer nor any p-value authenticates
a lottery draw, preregistration, predraw time seal or genuine future result.
"""
from __future__ import annotations

from math import isclose

from . import core
from .experimental_fusion import FUSION_ID
from .physics_audit import d2_probability
from .statistics import clopper_pearson, exact_binomial_upper_tail


def _require(condition: bool, code: str):
    if not condition:
        raise ValueError("V47_RESEARCH_REVIEW_BLOCKED:" + code)


def _is_hash(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _bit(v):
    return type(v) is int and v in (0, 1)


def review_synthetic_stack(report: dict) -> dict:
    """Return audit receipt; never grant performance or production eligibility."""
    try:
        return _review(report)
    except (KeyError, TypeError, IndexError, ArithmeticError) as exc:
        raise ValueError("V47_RESEARCH_REVIEW_BLOCKED:MALFORMED_REPORT") from exc


def _review(report: dict) -> dict:
    _require(isinstance(report, dict), "INVALID_REPORT")
    _require(report.get("schema") == "V47-UNIFIED-SYNTHETIC-RESEARCH-v1"
             and report.get("status") == "SYNTHETIC_RESEARCH_ONLY"
             and report.get("formal_A") == 0 and report.get("edge") == "NO_EDGE"
             and report.get("official_source_authenticated") is False
             and report.get("independent_predraw_time_seal") is False
             and report.get("prospective_calibration_valid") is False
             and report.get("physical_forecast_supported") is False,
             "UNVERIFIED_SOURCE_OR_INCORRECT_SHADOW_STATUS")
    physical = report.get("physics")
    _require(isinstance(physical, dict)
             and physical.get("status") == "UNCALIBRATED_TWO_BALL_BOX_DIAGNOSTIC"
             and physical.get("machine_measured") is False
             and physical.get("physical_forecast_supported") is False
             and physical.get("formal_A") == 0 and physical.get("edge") == "NO_EDGE"
             and len(physical.get("ball_state", [])) == 2,
             "PHYSICAL_RESEARCH_CANNOT_PREDICT")
    games = report.get("games")
    _require(isinstance(games, dict) and set(games) == set(core.RULES),
             "BOTH_GAMES_REQUIRED")
    by_game = {}
    for game in ("SSQ", "DLT"):
        row = games[game]
        rules = core.RULES[game]
        fair = float(d2_probability(rules["pool"], rules["front"]))
        m1 = row["m1_math"]
        _require(m1.get("model_ids") == list(core.MODELS)
                 and m1.get("verified_deterministic_models") == 6
                 and isclose(m1.get("fair_d2"), fair, rel_tol=0, abs_tol=1e-14),
                 "M1_MODEL_ROSTER_OR_D2_BASELINE_" + game)
        m2 = row["m2_adversarial"]
        _require(m2.get("independent_pairwise_check") == "PASS"
                 and m2.get("null_history_invariance") == "PASS",
                 "M2_INDEPENDENT_FALSIFICATION_" + game)
        m3 = row["m3_probability"]
        n, hits = m3.get("trials"), m3.get("observed_hits")
        _require(m3.get("status") == "SYNTHETIC_NULL_CALIBRATION_ONLY"
                 and m3.get("sampling") == "uniform_without_replacement"
                 and m3.get("authentic_forecasts_or_outcomes") is False
                 and m3.get("proof_of_predictive_advantage") is False
                 and type(n) is int and n > 0
                 and type(hits) is int and 0 <= hits <= n
                 and isclose(m3.get("fair_rate"), fair, rel_tol=0, abs_tol=1e-14)
                 and isclose(m3.get("observed_rate"), hits/n, rel_tol=0, abs_tol=1e-14)
                 and isclose(m3.get("brier_empirical"),
                             (hits*(1-fair)**2 + (n-hits)*fair**2)/n,
                             rel_tol=0, abs_tol=1e-14),
                 "M3_FAIR_NULL_ARITHMETIC_" + game)

        geo = row["geometry"]
        fusion = row["research_fusion"]
        _require(row.get("provenance") == "SYNTHETIC_FIXTURE_NOT_OFFICIAL"
                 and geo.get("source_engine") == game
                 and geo.get("real_machine_geometry_observed") is False
                 and geo.get("physical_forecast_supported") is False
                 and fusion.get("model") == FUSION_ID
                 and fusion.get("lottery") == game
                 and fusion.get("status") == "UNREGISTERED_SYNTHETIC_RESEARCH_ONLY"
                 and fusion.get("physical_signal_weight") == 0.0
                 and fusion.get("physical_forecast_supported") is False
                 and fusion.get("formal_a_eligible") is False
                 and fusion.get("formal_A") == 0
                 and fusion.get("edge") == "NO_EDGE"
                 and fusion.get("prospective_calibration") == "NOT_RUN",
                 "EXPERIMENTAL_FUSION_OR_PROVENANCE_" + game)
        pool = rules["pool"]
        _require(sorted(fusion.get("ranked_front", [])) == list(range(1, pool+1))
                 and fusion.get("candidates_1_to_5") == fusion["ranked_front"][:5]
                 and fusion.get("primary_d2") == fusion["ranked_front"][:2],
                 "EXPERIMENTAL_FUSION_RANKING_" + game)

        walk = row["walk_forward"]
        periods = walk.get("periods")
        per_period = walk.get("walk_forward")
        _require(walk.get("status") == "SYNTHETIC_LOCAL_ONLY"
                 and walk.get("game") == game
                 and walk.get("source") == "INVENTED_DRAW_HISTORY"
                 and walk.get("db_location") == "MEMORY_ONLY"
                 and walk.get("models") == list(core.MODELS)
                 and walk.get("random_null_model") == "random_null"
                 and walk.get("trusted_predraw_seal") is False
                 and walk.get("official_draws_admitted") is False
                 and walk.get("real_predictive_edge_claimed") is False
                 and walk.get("formal_A") == 0 and walk.get("edge") == "NO_EDGE"
                 and type(periods) is int and 1 <= periods <= 5
                 and isinstance(per_period, list) and len(per_period) == periods
                 and walk.get("frozen_predictions") == periods*6
                 and walk.get("freeze_audit_events") == periods*6
                 and walk.get("scores_computed") == periods*6
                 and walk.get("experimental_frozen") == periods
                 and walk.get("experimental_scored") == periods,
                 "FROZEN_FORECAST_AND_NULL_ROSTER_" + game)
        experiment_bits, null_bits = [], []
        wins = losses = 0
        for pindex, period in enumerate(per_period):
            _require(period.get("period_index") == pindex + 1
                     and period.get("frozen_count") == 6
                     and period.get("score_count") == 6
                     and period.get("evidence_class") == "SYNTHETIC_SHADOW_ONLY",
                     "INVALID_SYNTHETIC_PERIOD_" + game)
            models = period.get("models")
            _require(isinstance(models, dict) and set(models) == set(core.MODELS),
                     "MISSING_SIX_FROZEN_MODELS_" + game)
            outcomes = []
            for model in core.MODELS:
                record = models[model]
                _require(_is_hash(record.get("frozen_sha256"))
                         and _bit(record.get("D2")),
                         "INVALID_FROZEN_SIX_MODEL_" + game)
                outcome = record.get("synthetic_outcome_front")
                picks = record.get("ranking_first_two")
                _require(isinstance(outcome, list)
                         and len(outcome) == rules["front"]
                         and all(type(v) is int and 1 <= v <= pool for v in outcome)
                         and sorted(set(outcome)) == outcome
                         and isinstance(picks, list) and len(picks) == 2
                         and all(type(v) is int and 1 <= v <= pool for v in picks)
                         and len(set(picks)) == 2
                         and record["D2"] == int(set(picks).issubset(outcome)),
                         "SCORE_OR_OUTCOME_MISMATCH_" + game)
                outcomes.append(outcome)
            _require(all(v == outcomes[0] for v in outcomes),
                     "OUTCOME_MUST_BE_SAME_FOR_NULL_AND_FUSION_" + game)
            exp = period.get("experimental")
            _require(isinstance(exp, dict) and exp.get("model") == FUSION_ID
                     and _is_hash(exp.get("frozen_sha256"))
                     and exp.get("official_draw_admitted") is False,
                     "MISSING_EXPERIMENTAL_FROZEN_RECEIPT_" + game)
            e_picks = exp.get("primary_d2")
            e_score = exp.get("score")
            _require(isinstance(e_picks, list) and len(e_picks) == 2
                     and all(type(v) is int and 1 <= v <= pool for v in e_picks)
                     and len(set(e_picks)) == 2 and isinstance(e_score, dict)
                     and _bit(e_score.get("D2"))
                     and e_score["D2"] == int(set(e_picks).issubset(outcomes[0])),
                     "EXPERIMENTAL_D2_SCORE_MISMATCH_" + game)
            ebit, nbit = e_score["D2"], models["random_null"]["D2"]
            experiment_bits.append(ebit)
            null_bits.append(nbit)
            wins += int(ebit == 1 and nbit == 0)
            losses += int(ebit == 0 and nbit == 1)
        comparison = walk["experimental_against_random_null"]
        _require(comparison.get("status") == "TOO_FEW_SYNTHETIC_ISSUES_NO_EDGE_CLAIM"
                 and comparison.get("periods") == periods
                 and comparison.get("experimental_d2_hits") == sum(experiment_bits)
                 and comparison.get("random_null_d2_hits") == sum(null_bits)
                 and comparison.get("official_prospective_evidence") is False
                 and comparison.get("probability_calibration") == "NOT_RUN_NO_REAL_FORECASTS",
                 "INVALID_NULL_HEAD_TO_HEAD_" + game)
        # Exact intervals and paired-tail arithmetic are exploratory only;
        # two invented outcomes cannot qualify a model or establish calibration.
        e_ci = clopper_pearson(sum(experiment_bits), periods)
        n_ci = clopper_pearson(sum(null_bits), periods)
        paired_exact = exact_binomial_upper_tail(wins, wins + losses, 0.5)
        by_game[game] = {
            "fair_d2": fair,
            "experimental_d2_ci95": list(e_ci),
            "random_null_d2_ci95": list(n_ci),
            "synthetic_comparison": {
                "periods": periods,
                "experimental_hits": sum(experiment_bits),
                "null_hits": sum(null_bits),
                "paired_wins": wins,
                "paired_losses": losses,
                "paired_p_exploratory": paired_exact,
                "family_eligible_for_inference": False,
                "calibration_valid": False,
            },
        }
    return {
        "status": "SYNTHETIC_CONTRACT_PASS_NOT_REAL_CALIBRATION",
        "m1_exact_fair_d2": "PASS",
        "m2_independent_falsification": "PASS",
        "m3_null_arithmetic": "PASS_DIAGNOSTIC_ONLY",
        "unregistered_fusion": "AUDITED_SHADOW_ONLY",
        "physical_predictor_status": "DISABLED_UNCALIBRATED",
        "official_prospective_calibration": "BLOCKED_NO_AUTHENTICATED_FUTURE",
        "by_game": by_game,
        "formal_A": 0,
        "edge": "NO_EDGE",
    }
