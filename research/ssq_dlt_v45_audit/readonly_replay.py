"""Independent closed-ledger research scoring; never writes the input SQLite.

No Store, original producer, competition or original replay module is imported.
Local ledger chronology is evidence of internal consistency, not trusted custody.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from math import comb
from pathlib import Path
import random
import re
import sqlite3

RULES = {"SSQ": (33, 6, 16, 1), "DLT": (35, 5, 12, 2)}
MODELS = ("R45-HOT60", "R45-EWMA", "R45-SHRINKMIX", "R45-PAIRWISE-D2", "R45-RANDOM-NULL")
PRIMARY, NULL = MODELS[3:]
REGISTRY = "a245146c4ac6b3746a474e60e29d80a0facc7d690a5dc61d879670d5b013114a"
MODEL_SOURCE = "bc74e74af18dca2f0c0f8e7c869444c7104bbe7d2c2a084ac1cde64174c75bf4"
FROZEN_MANIFEST = "d2292f5d53d6d61931d1f60e0b3b6c972e4638b3695f87f8a3c30937db12af74"
BOUNDARY = dict(admission="RESEARCH_ONLY", formal_A=0, qualified_prospective_samples=0,
                decision="NO_EDGE", R2="BLOCKED", repository_independence="FAIL", final_gate="FAIL")


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("NONFINITE_JSON")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def time(value):
    require(type(value) is str, "AWARE_TIME_REQUIRED")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None and result.utcoffset() is not None, "AWARE_TIME_REQUIRED")
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError("AWARE_TIME_REQUIRED") from exc


def numbers(value, count, upper):
    require(type(value) is list and len(value) == count
            and all(type(x) is int and 1 <= x <= upper for x in value)
            and len(set(value)) == count, "INVALID_DISTINCT_NUMBERS")


def boundary(event):
    for key, wanted in dict(admission="RESEARCH_ONLY", formal_A=0, decision="NO_EDGE").items():
        require(type(event.get(key)) is type(wanted) and event[key] == wanted, "RESEARCH_BOUNDARY_CHANGED")


def source_binding():
    root = Path(__file__).resolve().parents[2]
    path = Path(__file__).with_name("FROZEN_SCIENCE_SHA256.json")
    require(hashlib.sha256(path.read_bytes()).hexdigest() == FROZEN_MANIFEST, "FROZEN_MANIFEST_CHANGED")
    pins = parse(path.read_bytes())["files"]
    require(len(pins) == 49, "FROZEN_49_REQUIRED")
    require(all(hashlib.sha256((root / n).read_bytes()).hexdigest() == h for n, h in pins.items()), "FROZEN_SCIENCE_CHANGED")
    return dict(reader_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                frozen_manifest_sha256=FROZEN_MANIFEST, frozen_sources=49, registry_sha256=REGISTRY)


def evidence_files(path):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [path, *(Path(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal"))] if p.exists()}


def load_events(path):
    require(path.is_file() and not path.is_symlink(), "EXISTING_REGULAR_LEDGER_REQUIRED")
    require(not any(Path(str(path) + s).exists() for s in ("-wal", "-shm", "-journal")),
            "CLOSED_CHECKPOINTED_LEDGER_REQUIRED")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        require(db.execute("PRAGMA application_id").fetchone()[0] == 0x47565035
                and db.execute("PRAGMA user_version").fetchone()[0] == 1, "ORIGINAL_LEDGER_SCHEMA_REQUIRED")
        require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLITE_INTEGRITY_REQUIRED")
        require({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"events"}, "ORIGINAL_EVENT_TABLE_REQUIRED")
        require([r[1] for r in db.execute("PRAGMA table_info(events)")] == ["kind", "key", "payload", "sha256"], "EVENT_COLUMNS_CHANGED")
        events = {}
        for kind, key, raw, sha in db.execute("SELECT kind,key,payload,sha256 FROM events ORDER BY kind,key"):
            require(type(kind) is type(key) is type(raw) is type(sha) is str and (kind, key) not in events, "EVENT_IDENTITIES_REQUIRED")
            value = parse(raw)
            require(type(value) is dict and canonical(value) == raw and digest(value) == sha, "EVENT_CANONICAL_SHA_MISMATCH")
            events[kind, key] = value
        return events
    finally:
        db.close()


def plan(trial_id, event):
    boundary(event)
    p = event.get("plan")
    require(type(p) is dict and event.get("trial_id") == trial_id and digest(p) == trial_id, "TRIAL_PLAN_SHA_IDENTITY")
    game, issues = p.get("game"), p.get("expected_issues")
    require(type(game) is str and game in RULES, "UNKNOWN_GAME")
    require(type(issues) is list and issues and all(type(i) is str and re.fullmatch(r"[0-9]+", i) and int(i) > 0 for i in issues)
            and len(set(issues)) == len(issues) and len({len(i) for i in issues}) == 1
            and issues == sorted(issues, key=int), "COMPLETE_ORDERED_ISSUE_PLAN_REQUIRED")
    require(type(p.get("seed")) is int and p["seed"] >= 0
            and type(p.get("independent_series_id")) is str and p["independent_series_id"].strip(), "FIXED_SEED_SERIES_REQUIRED")
    expected = dict(schema="ssq-dlt-v45-research-plan-1", game=game, expected_issues=issues,
                    registered_at=p["registered_at"], independent_series_id=p["independent_series_id"],
                    registry_sha256=REGISTRY, model_versions={m: "1.0.0" for m in MODELS},
                    primary_model=PRIMARY, null_model=NULL, alpha=0.05, seed=p["seed"],
                    family="RESEARCH_FOUR_VS_SAME_ISSUE_NULL_D2")
    require(canonical(p) == canonical(expected), "FIXED_RESEARCH_PLAN_CHANGED")
    require(time(p["registered_at"]) <= time(event["accepted_at"]), "BACKDATED_TRIAL_ACCEPTANCE")
    return p


def prediction(value, p, issue):
    boundary(value)
    require(value.get("schema") == "ssq-dlt-v45-research-prediction-1" and value.get("game") == p["game"]
            and value.get("issue") == issue and value.get("target_status") == "CALLER_TARGET_REQUIRES_OFFICIAL_ADMISSION", "PREDICTION_TARGET_IDENTITY")
    require(type(value.get("seed")) is int and value["seed"] == p["seed"]
            and type(value.get("history_size")) is int and value["history_size"] >= 0
            and type(value.get("history_sha256")) is str and re.fullmatch(r"[0-9a-f]{64}", value["history_sha256"]), "PREDICTION_FIXED_SEED_HISTORY_BINDING")
    require(value.get("model_source_sha256") == MODEL_SOURCE and value.get("registry_sha256") == REGISTRY
            and value.get("primary_model") == PRIMARY, "FROZEN_PRODUCER_IDENTITY_CHANGED")
    candidates = value.get("models")
    require(type(candidates) is dict and set(candidates) == set(MODELS), "EXACT_FIVE_RESEARCH_MODELS_REQUIRED")
    upper, count, back_upper, back_count = RULES[p["game"]]
    for model in MODELS:
        c = candidates[model]
        require(type(c) is dict and c.get("version") == "1.0.0" and type(c.get("dan")) is dict
                and set(c["dan"]) == set("12345"), "MODEL_VERSION_OR_DK_IDENTITY")
        for k in range(1, 6):
            numbers(c["dan"][str(k)], k, upper)
            if model == NULL:
                seed_bytes = canonical([p["seed"], p["game"], issue, NULL, "dan", k]).encode("utf-8")
                selected = sorted(random.Random(int.from_bytes(hashlib.sha256(seed_bytes).digest(), "big")).sample(range(1, upper + 1), k))
                require(c["dan"][str(k)] == selected, "FIXED_NULL_DOMAIN_OR_NUMBERS_CHANGED")
        numbers(c.get("primary_d2"), 2, upper)
        require(c["primary_d2"] == c["dan"]["2"], "PRIMARY_D2_MUST_BE_OWN_D2")
        ticket = c.get("ticket")
        require(type(ticket) is dict, "LEGAL_SINGLE_TICKET_REQUIRED")
        numbers(ticket.get("front"), count, upper)
        numbers(ticket.get("back"), back_count, back_upper)
        require(set(c["primary_d2"]) <= set(ticket["front"]), "SAME_MODEL_TICKET_D2_REQUIRED")
    require(value.get("primary_d2") == candidates[PRIMARY]["primary_d2"], "UNIQUE_PRIMARY_D2_CHANGED")


def score_period(trial_id, trial, p, issue, events):
    key = trial_id + ":" + issue
    pred, draw = [events[kind, key] for kind in ("r45_prediction", "r45_draw")]
    for event in (pred, draw):
        boundary(event)
        require(event.get("trial_id") == trial_id and event.get("issue") == issue, "TRIAL_EVENT_IDENTITY_CHANGED")
    value = pred.get("prediction")
    require(type(value) is dict and digest(value) == pred.get("prediction_sha256"), "FROZEN_PREDICTION_SHA_MISMATCH")
    prediction(value, p, issue)
    require(draw.get("game") == p["game"], "DRAW_GAME_MISMATCH")
    upper, count, back_upper, back_count = RULES[p["game"]]
    numbers(draw.get("front"), count, upper); numbers(draw.get("back"), back_count, back_upper)
    frozen, accepted, drawn = time(pred["frozen_at"]), time(pred["accepted_at"]), time(draw["draw_at"])
    require(time(trial["accepted_at"]) <= accepted == frozen < drawn <= time(draw["accepted_at"]), "TRIAL_FREEZE_DRAW_ACCEPTANCE_CHRONOLOGY")
    observed = events.get(("r45_observed_draw", p["game"] + ":" + issue))
    require(type(observed) is dict, "GLOBAL_OBSERVED_DRAW_REQUIRED")
    boundary(observed)
    fields = ("game", "issue", "front", "back", "draw_at")
    require(canonical({k: draw[k] for k in fields}) == canonical({k: observed[k] for k in fields})
            and drawn <= time(observed["accepted_at"]), "GLOBAL_DRAW_CONFLICT_OR_FUTURE_ACCEPTANCE")
    scores = {}
    for model in MODELS:
        scores[model] = {}
        for k in range(1, 6):
            chosen = value["models"][model]["dan"][str(k)]
            hits = sum(n in draw["front"] for n in chosen)
            scores[model]["D" + str(k)] = dict(numbers=chosen, hits=hits, full=int(hits == k), p0=comb(count, k)/comb(upper, k))
    return dict(issue=issue, game=p["game"], status="SCORED_RESEARCH_ONLY",
                prediction_sha256=pred["prediction_sha256"], frozen_at=pred["frozen_at"],
                draw_at=draw["draw_at"], models=scores)


def score_trial(trial_id, trial, events):
    p = plan(trial_id, trial)
    issues = p["expected_issues"]
    missing = {kind: [i for i in issues if (kind, trial_id + ":" + i) not in events]
               for kind in ("r45_prediction", "r45_draw")}
    require(not any(kind in ("r45_prediction", "r45_draw") and event.get("trial_id") == trial_id
                    and key not in {trial_id + ":" + i for i in issues} for (kind, key), event in events.items()), "UNASSIGNED_EXTRA_TRIAL_EVENT")
    totals = {m: {"D" + str(k): 0 for k in range(1, 6)} for m in MODELS}
    d2 = {m: [] for m in MODELS}
    periods, period_records, failures, previous_draw = [], [], [], None
    for issue in issues:
        absent = [kind for kind, values in missing.items() if issue in values]
        if absent:
            period_records.append(dict(issue=issue, status="BLOCKED_MISSING_ISSUE_EVIDENCE", missing_event_kinds=absent))
            continue
        try:
            entry = score_period(trial_id, trial, p, issue, events)
            drawn = time(entry["draw_at"])
            require(previous_draw is None or previous_draw < drawn, "DISTINCT_ORDERED_DRAW_TIMES_REQUIRED")
            previous_draw = drawn
            periods.append(entry); period_records.append(entry)
            for model in MODELS:
                for k in range(1, 6):
                    totals[model]["D" + str(k)] += entry["models"][model]["D" + str(k)]["full"]
                d2[model].append(entry["models"][model]["D2"]["full"])
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            error = dict(issue=issue, status="BLOCKED_INVALID_PERIOD_EVIDENCE", reason=str(exc))
            failures.append(error); period_records.append(error)
    complete = len(periods) == len(issues) and not failures
    comparisons = []
    for model in (MODELS[:-1] if complete else ()):
        wins = sum(a == 1 and b == 0 for a, b in zip(d2[model], d2[NULL]))
        losses = sum(a == 0 and b == 1 for a, b in zip(d2[model], d2[NULL]))
        discordant = wins + losses
        pvalue = sum(comb(discordant, k) for k in range(wins, discordant + 1)) / 2**discordant
        comparisons.append(dict(model=model, null_model=NULL, wins=wins, losses=losses,
                                ties=len(issues)-discordant, paired_delta=(wins-losses)/len(issues), p_one_sided=pvalue))
    maximum = 0.0
    for rank, c in enumerate(sorted(comparisons, key=lambda c: (c["p_one_sided"], c["model"]))):
        maximum = max(maximum, (4-rank)*c["p_one_sided"])
        c["p_holm_research"] = min(1.0, maximum)
    return dict(trial_id=trial_id, status="PASS_READONLY_RESEARCH_SCORES" if complete else "BLOCKED_INCOMPLETE_PLAN_SCORES_RETAINED",
                game=p["game"], n=len(periods), expected_n=len(issues), complete_plan=complete,
                missing_predictions=missing["r45_prediction"], missing_draws=missing["r45_draw"], failures=failures,
                period_records=period_records,
                issues=issues, scored_periods=periods, D1_D5_full=totals, pairwise_vs_null=comparisons,
                interim_inferential_tests="NOT_RUN" if not complete else "COMPLETE_RESEARCH_PLAN_ONLY",
                primary_model=PRIMARY, holm_scope="RESEARCH_FOUR_VS_SAME_ISSUE_NULL_D2",
                formal_12_family="BLOCKED_ORIGINAL_FORMAL_12_IDS_SHA_AND_STOPPING_RULES_REQUIRED", **BOUNDARY)


def replay(path):
    path = Path(path).absolute()
    binding = source_binding()
    before = evidence_files(path)
    try:
        events = load_events(path)
        trials = []
        for (kind, key), trial in events.items():
            if kind != "r45_trial":
                continue
            try:
                trials.append(score_trial(key, trial, events))
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                trials.append(dict(trial_id=key, status="BLOCKED_INVALID_RESEARCH_EVIDENCE", reason=str(exc), **BOUNDARY))
        used_trials = {t["trial_id"] for t in trials}
        require(not any(k in ("r45_prediction", "r45_draw") and v.get("trial_id") not in used_trials
                        for (k, _), v in events.items()), "ORPHAN_PREDICTION_OR_DRAW")
        good = bool(trials) and all(t["status"] == "PASS_READONLY_RESEARCH_SCORES" for t in trials)
        return dict(schema="V45_INDEPENDENT_READONLY_REPLAY_1", status="PASS_READONLY_RESEARCH_REPLAY" if good else "BLOCKED_INCOMPLETE_OR_INVALID_TRIALS",
                    input_ledger=str(path), input_sha256=before[str(path)], verified_event_count=len(events), trials=trials,
                    source_binding=binding, original_input_files_unchanged=True, input_sqlite_write_calls=0,
                    original_producer_store_replay_or_statistics_imported=False, independently_regenerated_null_dan=True,
                    official_sources_as_of_and_candidate_TSA="NOT_ADMITTED", formal_eight_slots="NOT_ADMITTED",
                    costs_and_formal_stopping_rules="NOT_REGISTERED_BY_RESEARCH_PLAN",
                    original_69_2880_admission="FALSIFIED_REPRODUCED_NOT_FIXED_CAUSE_UNRESOLVED",
                    affected_source_cohort_promotion="BLOCKED",
                    history_or_model_training_reexecuted=False, **BOUNDARY)
    finally:
        require(evidence_files(path) == before and source_binding() == binding, "INPUT_OR_READER_SOURCE_CHANGED")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-ledger", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    require(not args.output.exists(), "NEW_OUTPUT_DIRECTORY_REQUIRED")
    result = replay(args.input_ledger)
    args.output.mkdir(parents=True, exist_ok=False)
    raw = (canonical(result) + "\n").encode("utf-8")
    (args.output / "replay.json").write_bytes(raw)
    columns = ["trial_id", "game", "issue", "status", "model", "dan_k", "numbers", "hits", "full", "p0", "reason", "formal_A", "decision"]
    with (args.output / "periods.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader()
        for trial in result["trials"]:
            base = dict(trial_id=trial["trial_id"], game=trial.get("game", ""), formal_A=0, decision="NO_EDGE")
            for period in trial.get("period_records", [dict(issue="", status=trial["status"], reason=trial.get("reason", ""))]):
                row = dict(base, issue=period["issue"], status=period["status"], reason=period.get("reason", ""))
                if period["status"] != "SCORED_RESEARCH_ONLY":
                    writer.writerow(row); continue
                for model in MODELS:
                    for k in range(1, 6):
                        values = period["models"][model]["D"+str(k)]
                        writer.writerow(dict(row, model=model, dan_k=k, numbers=canonical(values["numbers"]),
                                             hits=values["hits"], full=values["full"], p0=values["p0"]))
    manifest = {name: hashlib.sha256((args.output / name).read_bytes()).hexdigest() for name in ("replay.json", "periods.csv")}
    (args.output / "SHA256.json").write_text(canonical(dict(files=manifest, **BOUNDARY)) + "\n", encoding="utf-8")
    print(canonical(result))
    return 0 if result["status"] == "PASS_READONLY_RESEARCH_REPLAY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
