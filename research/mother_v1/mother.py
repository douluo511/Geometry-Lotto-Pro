"""SSQ/DLT unified research mother V1: all model arms, one audited output.

Every registered model appears exactly once per game. The mother does NOT
promote either statistical or mechanical prediction effectiveness. Physical
arms fail closed when observed source evidence is absent or not pre-draw
available; the separate NULL fallback is display-only, never a physical claim.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

from research.harness_v46 import core
from research.harness_v46.d2_challenger_lab import (
    ablation_rank, challenger_contract_sha256, pick_recency_pair,
)
from research.supercompute import engine as legacy_engine
from research.supercompute.automation import dlt_physical_source, ssq_physical_source
from .native_provider import native_models
from .source_identity import committed_source_sha256
from .registry import (
    ALL_MODELS, REGISTERED_V47, EXPLORATORY_V47, LEGACY_SUPERCOMPUTE,
    NATIVE_FEATURES, PHYSICAL, MODEL_FAMILIES, SCHEMA, NO_EDGE, FORMAL_A,
)

PHYSICAL_MIN_ROWS = 60
SUPPORTED_PROVENANCE = {
    "UNVERIFIED_TRANSCRIPTION",
    "HISTORICAL_REPLAY_UNVERIFIED",
    "LOCAL_RAW_HASH_VERIFIED_NOT_AUTHENTICATED",
}
PHYSICAL_ABORT = ("ABSTAIN_NO_VERIFIED_PREDRAW_PHYSICAL_FEATURE", 
                  "ABSTAIN_INSUFFICIENT_PHYSICAL_HISTORY")


class MotherBlocked(ValueError):
    """Critical provenance, snapshot, or model output gate."""


def _bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value: object) -> str:
    return sha256(_bytes(value)).hexdigest()


def _valid_ticket(game: str, ticket: dict) -> dict:
    r = core.RULES[game]
    if not isinstance(ticket, dict) or set(ticket) != {"front", "back"}:
        raise MotherBlocked("TICKET_SHAPE_INVALID")
    core._balls(ticket["front"], r["pool"], r["front"])
    core._balls(ticket["back"], r["back_pool"], r["back"])
    return ticket


def _next_issue(game: str, previous: str, current: str) -> bool:
    if len(previous) != len(current) or not previous.isascii() or not current.isascii():
        return False
    if int(current) == int(previous) + 1:
        return True
    # Issue suffix resets when the year's published issue sequence rolls over.
    prefix = 4 if game == "SSQ" else 2
    return (int(current[:prefix]) == int(previous[:prefix]) + 1
            and current[prefix:] == "001"
            and previous[prefix:] != "000")


def _validate_history(game: str, ctx: dict) -> dict:
    if game not in core.RULES or not isinstance(ctx, dict):
        raise MotherBlocked("GAME_OR_CONTEXT_INVALID")
    required = {"target_issue", "target_draw_date", "as_of_utc", "provenance", "history"}
    if set(ctx) != required:
        raise MotherBlocked("INPUT_CONTEXT_EXTRA_OR_MISSING_FIELDS")
    target_issue, history, target_day = ctx["target_issue"], ctx["history"], ctx["target_draw_date"]
    if (not isinstance(target_issue, str) or not target_issue.isascii()
            or not target_issue.isdigit() or len(target_issue) != (7 if game == "SSQ" else 5)):
        raise MotherBlocked("TARGET_ISSUE_INVALID")
    if not isinstance(target_day, str):
        raise MotherBlocked("TARGET_DATE_INVALID")
    try:
        d_target = date.fromisoformat(target_day)
        as_of = datetime.fromisoformat(ctx["as_of_utc"].replace("Z", "+00:00"))
        if not as_of.tzinfo or as_of.utcoffset() != timedelta(0):
            raise ValueError("UTC required")
        if d_target.isoformat() != target_day:
            raise ValueError("canonical date required")
    except (ValueError, TypeError, AttributeError) as exc:
        raise MotherBlocked("DATE_OR_AS_OF_INVALID") from exc
    if ctx["provenance"] not in SUPPORTED_PROVENANCE:
        raise MotherBlocked("INPUT_AUTHENTICITY_UNSUPPORTED")
    if not isinstance(history, list) or len(history) < 120:
        raise MotherBlocked("MODEL_WARMUP_120_REQUIRED")
    previous_issue, previous_date = None, None
    r = core.RULES[game]
    for row in history:
        if not isinstance(row, dict) or set(row) != {"issue", "draw_date", "front", "back"}:
            raise MotherBlocked("HISTORY_ROW_SCHEMA_INVALID")
        issue, day = row["issue"], row["draw_date"]
        if (not isinstance(issue, str) or not issue.isascii() or not issue.isdigit()
                or len(issue) != len(target_issue)):
            raise MotherBlocked("HISTORY_ISSUE_INVALID")
        try:
            d = date.fromisoformat(day)
        except (ValueError, TypeError) as exc:
            raise MotherBlocked("HISTORY_DRAW_DATE_INVALID") from exc
        if (d.isoformat() != day or (previous_date is not None and d <= previous_date)
                or (previous_issue is not None and not _next_issue(game, previous_issue, issue))):
            raise MotherBlocked("HISTORY_GAP_OR_UNORDERED")
        if d >= d_target or d > as_of.date():
            raise MotherBlocked("FUTURE_INFORMATION_LEAK")
        core._balls(row["front"], r["pool"], r["front"])
        core._balls(row["back"], r["back_pool"], r["back"])
        previous_issue, previous_date = issue, d
    if not _next_issue(game, previous_issue, target_issue):
        raise MotherBlocked("TARGET_NOT_NEXT_AFTER_HISTORY")
    if as_of.date() >= d_target:
        raise MotherBlocked("AS_OF_NOT_PRE_DRAW_DAY")
    return {"target_issue": target_issue, "target_draw_date": target_day,
            "last_training_issue": previous_issue, "last_training_date": previous_date.isoformat(),
            "as_of_utc_untrusted": ctx["as_of_utc"],
            "history_count": len(history), "history_sha256": sha(history),
            "input_provenance": ctx["provenance"],
            "source_authenticity": "NOT_EXTERNALLY_VERIFIED",
            "publication_time_authenticity": "NOT_VERIFIED"}


def _rank_ticket(game: str, issue: str, model: str, ranking: list[int]) -> tuple[dict, list[int]]:
    r = core.RULES[game]
    if (not isinstance(ranking, list) or len(ranking) != r["pool"]
            or len(set(ranking)) != r["pool"]
            or set(ranking) != set(range(1, r["pool"] + 1))):
        raise MotherBlocked("MODEL_RANKING_PERMUTATION_INVALID")
    front = sorted(ranking[:r["front"]])
    back_ranking = core._stable_permutation(
        list(range(1, r["back_pool"] + 1)), core.NULL_SEED,
        game, issue, model, "back"
    )
    ticket = {"front": front, "back": sorted(back_ranking[:r["back"]])}
    return _valid_ticket(game, ticket), ranking[:5]


def _physical_observations(game: str, ledger_root: Path | None, history: list[dict],
                           target_issue: str) -> tuple[list[dict], str]:
    if ledger_root is None:
        return [], "NO_LEDGER_MOUNTED"
    if ledger_root.is_symlink():
        raise MotherBlocked("PHYSICAL_LEDGER_SYMLINK_BLOCKED")
    game_root = ledger_root / game
    if not game_root.is_dir():
        return [], "NO_GAME_LEDGER"
    verifier = dlt_physical_source.verify if game == "DLT" else ssq_physical_source.verify
    try:
        verifier(game_root)  # replays original raw hash for every canonical draw
    except Exception as exc:
        raise MotherBlocked("PHYSICAL_CANONICAL_LEDGER_INVALID:" + type(exc).__name__) from exc
    lookup = {row["issue"]: row for row in history}
    accepted = []
    for path in sorted((game_root / "draws").glob("*.json")):
        if path.is_symlink():
            raise MotherBlocked("PHYSICAL_OBSERVATION_SYMLINK_BLOCKED")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise MotherBlocked("PHYSICAL_RECORD_INVALID") from exc
        issue = raw.get("issue")
        if (not isinstance(issue, str) or issue not in lookup
                or int(issue) >= int(target_issue)
                or raw.get("draw_date") != lookup[issue]["draw_date"]):
            raise MotherBlocked("PHYSICAL_OBSERVATION_OUTSIDE_TRAINING_SNAPSHOT")
        if game == "DLT":
            if (raw.get("front_sorted") != lookup[issue]["front"]
                    or raw.get("back_sorted") != lookup[issue]["back"]):
                raise MotherBlocked("PHYSICAL_VS_HISTORY_BALL_CONFLICT")
            if (not isinstance(raw.get("front_order"), list)
                    or not isinstance(raw.get("back_order"), list)
                    or type(raw.get("ball_group")) is not int):
                raise MotherBlocked("PHYSICAL_BALL_ORDER_OR_GROUP_MISSING")
            accepted.append(raw)
        elif raw.get("red_order") is not None:
            # SSQ's current issuer table is sorted only; do not infer sequence.
            raise MotherBlocked("SSQ_SORTED_RESULTS_NOT_PHYSICAL_ORDER")
    return accepted, ("VERIFIED_HISTORICAL_ORDER_ONLY" if accepted
                      else "NO_PHYSICAL_EXIT_ORDER_IN_SOURCE")


def _physical_exit_rank(game: str, physical: list[dict]) -> list[int]:
    if game != "DLT":
        raise MotherBlocked("SSQ_PHYSICAL_EXIT_NOT_AVAILABLE")
    r = core.RULES[game]
    pool = r["pool"]
    score = Counter()
    # "Earliest exit" hypothesis for audit only, not an established mechanism.
    for age, record in enumerate(reversed(physical)):
        decay = 2.0 ** (-age / 45)
        for position, ball in enumerate(record["front_order"]):
            score[ball] += decay * (r["front"] - position) / r["front"]
    return sorted(range(1, pool + 1), key=lambda n: (-score[n], n))


def _one_regular(ctx: dict, game: str, name: str, native: dict | None = None) -> dict:
    issue, history = ctx["target_issue"], ctx["history"]
    state = {"lottery": game, "target_issue": issue, "draws": history}
    if name in REGISTERED_V47:
        ranking = core._model_ranking(state, name)
        ticket, first5 = _rank_ticket(game, issue, name, ranking)
        psha = core.digest(core.parameter_contract(name))
        source = core.model_source_sha256()
        provider = "v47_frozen_core"
    elif name in EXPLORATORY_V47:
        if name == "recency_pair_h45_120":
            pair = pick_recency_pair(history, game)
            fill = core._model_ranking(state, "hot60")
            ranking = list(pair) + [n for n in fill if n not in pair]
            psha = challenger_contract_sha256()
        else:
            arm = {"hot30": "HOT30", "hot120": "HOT120",
                   "pair_margin": "P-MARGIN", "pair_residual": "P-RESIDUAL"}[name]
            ranking = ablation_rank(history, game, arm, target_issue=issue)
            psha = core.digest({"arm": arm, "source": "d2_challenger_lab_v47",
                                "rules": core.RULES[game]})
        ticket, first5 = _rank_ticket(game, issue, name, ranking)
        source = committed_source_sha256(ablation_rank.__code__.co_filename)
        provider = "v47_exploratory"
    elif name in LEGACY_SUPERCOMPUTE:
        raw_name = {"supercompute_hot60": "HOT60",
                    "supercompute_ewma30": "EWMA30",
                    "supercompute_random_null": "RANDOM_NULL"}[name]
        ticket = legacy_engine.ticket(history, game.lower(), raw_name, seed=2026)
        ticket = _valid_ticket(game, {"front": ticket["front"], "back": ticket["back"]})
        first5 = ticket["front"][:5]
        psha = sha({"model": raw_name, "seed": 2026,
                    "protocol": "legacy_supercompute_original_ticket_v1"})
        source = committed_source_sha256(legacy_engine.__file__)
        provider = "legacy_supercompute_engine"
    elif name in NATIVE_FEATURES:
        if native is None:
            raise MotherBlocked("NATIVE_PROVIDER_NOT_EXECUTED")
        rawname = name.removeprefix("native_")
        front_rank = native["front_rankings"][rawname]
        back_rank = native["back_rankings"][rawname]
        r = core.RULES[game]
        if (set(front_rank) != set(range(1, r["pool"] + 1))
                or set(back_rank) != set(range(1, r["back_pool"] + 1))):
            raise MotherBlocked("NATIVE_RANKING_INVALID")
        ticket = _valid_ticket(game, {
            "front": sorted(front_rank[:r["front"]]),
            "back": sorted(back_rank[:r["back"]]),
        })
        first5 = front_rank[:5]
        psha = sha({"model": rawname, "identity": native["identity"],
                    "native_source_sha256": native["source_sha256"],
                    "rank_tie_policy": "original_native_engine"})
        source = native["source_sha256"]
        provider = "native_engine_separate_python_process"
    else:
        raise MotherBlocked("UNREGISTERED_MODEL")
    return {
        "name": name, "family": MODEL_FAMILIES[name], "provider": provider,
        "status": "PREDICTED_SHADOW_NO_EDGE", "ticket": ticket,
        "ordered_first_five": first5, "primary_d2": first5[:2],
        "model_source_sha256": source, "parameters_sha256": psha,
        "physical_prediction_verified": False, "formal_A": 0,
    }


def _physical_model(ctx: dict, game: str, name: str, physical: list[dict],
                    physical_status: str, null_ticket: dict) -> dict:
    issue = ctx["target_issue"]
    base = {"name": name, "family": MODEL_FAMILIES[name],
            "provider": "issuer_physical_raw_evidence", "physical_history_rows": len(physical),
            "physical_data_state": physical_status, "formal_A": 0,
            "physical_prediction_verified": False,
            "model_source_sha256": committed_source_sha256(__file__),
            "parameters_sha256": sha({"name": name, "min_rows": PHYSICAL_MIN_ROWS,
                                       "algorithm": "early_exit_weighted_decay_45"
                                       if name == "physical_exit_order"
                                       else "requires_verified_future_ball_group_pre_draw"}),
            "ticket": None, "ordered_first_five": None, "primary_d2": None,
            "display_only_random_null_fallback": null_ticket,
            "fallback_is_physical_forecast": False}
    if name == "physical_ball_group":
        # Future ball set is usually only known at/after the draw.
        base["status"] = "ABSTAIN_NO_VERIFIED_PREDRAW_BALL_GROUP"
    elif name == "physical_exit_order":
        if len(physical) < PHYSICAL_MIN_ROWS:
            base["status"] = "ABSTAIN_INSUFFICIENT_VERIFIED_PHYSICAL_HISTORY"
        elif game != "DLT":
            base["status"] = "ABSTAIN_NO_VERIFIED_SSQ_EXIT_ORDER"
        else:
            ticket, first5 = _rank_ticket(
                game, issue, name, _physical_exit_rank(game, physical))
            base.update(status="PREDICTED_SHADOW_PHYSICAL_EXPLORATORY_NO_EDGE",
                        ticket=ticket, ordered_first_five=first5,
                        primary_d2=first5[:2], display_only_random_null_fallback=None)
    else:
        raise MotherBlocked("PHYSICAL_MODEL_UNREGISTERED")
    return base


def _validate_outputs(outputs: list[dict], game: str) -> None:
    if len(outputs) != len(ALL_MODELS) or [x["name"] for x in outputs] != list(ALL_MODELS):
        raise MotherBlocked("MISSING_OR_DUPLICATE_MODEL_ROW")
    for row in outputs:
        if row["family"] != MODEL_FAMILIES[row["name"]] or row["formal_A"] != 0:
            raise MotherBlocked("MODEL_IDENTITY_OR_FORMAL_A_INVALID")
        if row["name"] in PHYSICAL and row["ticket"] is None:
            if not row["status"].startswith("ABSTAIN_"):
                raise MotherBlocked("MISSING_PHYSICAL_TICKET_NOT_ABSTAINED")
            _valid_ticket(game, row["display_only_random_null_fallback"])
            if row["fallback_is_physical_forecast"] is not False:
                raise MotherBlocked("MISLABELED_PHYSICAL_FALLBACK")
        else:
            _valid_ticket(game, row["ticket"])
            if row["name"] not in PHYSICAL and not row["status"].startswith("PREDICTED_SHADOW"):
                raise MotherBlocked("UNEXPECTED_NONPHYSICAL_ABSTENTION")


def forecast_all(bundle: dict, *, physical_ledger: Path | None = None) -> dict:
    if not isinstance(bundle, dict) or set(bundle) != {"SSQ", "DLT"}:
        raise MotherBlocked("EXACT_TWO_GAMES_REQUIRED")
    result = {
        "schema": SCHEMA, "registry": list(ALL_MODELS),
        "registry_sha256": sha({"registry": list(ALL_MODELS), "families": MODEL_FAMILIES}),
        "formal_A": FORMAL_A, "decision": NO_EDGE,
        "evidence_class": "SHADOW_NOT_FORMAL_PROSPECTIVE",
        "source_authenticity": "NOT_EXTERNALLY_VERIFIED",
        "timestamp_authenticity": "NOT_TRUSTED_TSA",
        "purchase_performed": False,
        "physical_missing_policy": "ABSTAIN_AND_SHOW_SEPARATE_NULL_FALLBACK_ONLY",
        "games": {},
    }
    for game in ("SSQ", "DLT"):
        ctx = bundle[game]
        metadata = _validate_history(game, ctx)
        native = native_models(game, ctx["history"])
        regular = [_one_regular(ctx, game, name, native) for name in ALL_MODELS
                   if name not in PHYSICAL]
        null_row = next(row for row in regular if row["name"] == "random_null")
        physical, state = _physical_observations(
            game, physical_ledger, ctx["history"], ctx["target_issue"])
        outputs = regular + [_physical_model(ctx, game, name, physical, state,
                                            null_row["ticket"]) for name in PHYSICAL]
        _validate_outputs(outputs, game)
        result["games"][game] = {**metadata, "models": outputs,
                                 "physical_count": len(physical),
                                 "model_count": len(outputs)}
    result["input_sha256"] = sha(bundle)
    return result
