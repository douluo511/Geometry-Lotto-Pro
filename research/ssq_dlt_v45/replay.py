"""Append-only local prospective research replay. No formal admission or TSA.

The runtime supplies an aware local datetime as `now`. Test clocks may be
injected explicitly. This clock is not external trusted timestamp custody and
does not defend against a privileged administrator or OS clock compromise.
"""
from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import html
import io
from pathlib import Path
import uuid

from . import competition
from .competition import evaluate_registered, make_plan
from .models import RULES, validate_numbers, validate_prediction
from .store import canonical, digest


BOUNDARY = {"admission": "RESEARCH_ONLY", "formal_A": 0, "decision": "NO_EDGE",
            "formal_eligibility": "BLOCKED_EXTERNAL_TSA_01_02_03_04_AND_FORMAL_12_FAMILY"}


class ReplayBlocked(ValueError):
    """A missing plan, changed immutable record, or late/backdated prediction."""


def _now(value: datetime | None) -> datetime:
    value = datetime.now(timezone.utc) if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReplayBlocked("AWARE_LOCAL_DATETIME_REQUIRED")
    return value.astimezone(timezone.utc)


def _time(value: object) -> datetime:
    if isinstance(value, datetime):
        return _now(value)
    if type(value) is not str:
        raise ReplayBlocked("AWARE_TIME_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _now(parsed)
    except (ValueError, OverflowError) as exc:
        raise ReplayBlocked("AWARE_TIME_REQUIRED") from exc


def _get(store, db, kind: str, key: str):
    return store.checked(db.execute("SELECT payload,sha256 FROM events WHERE kind=? AND key=?",
                                    (kind, key)).fetchone())


def _insert(db, kind: str, key: str, value: dict) -> None:
    # The surrounding transaction owns the draw-known check and this INSERT.
    db.execute("INSERT INTO events VALUES(?,?,?,?)", (kind, key, canonical(value), digest(value)))


def _trial(store, db, trial_id: str) -> dict:
    if type(trial_id) is not str or len(trial_id) != 64:
        raise ReplayBlocked("REGISTERED_TRIAL_REQUIRED")
    event = _get(store, db, "r45_trial", trial_id)
    if event is None:
        raise ReplayBlocked("REGISTERED_TRIAL_REQUIRED")
    plan = event.get("plan")
    if type(plan) is not dict or digest(plan) != trial_id or event.get("trial_id") != trial_id:
        raise ReplayBlocked("TRIAL_PLAN_SHA_MISMATCH")
    expected = make_plan(plan.get("game"), plan.get("expected_issues"), plan.get("registered_at"),
                         plan.get("independent_series_id"), seed=plan.get("seed"))
    if expected != plan:
        raise ReplayBlocked("TRIAL_REGISTRY_OR_FAMILY_REPLACED")
    _time(event.get("accepted_at"))
    return event


def _key(trial_id: str, issue: str, trial: dict) -> str:
    if type(issue) is not str or issue not in trial["plan"]["expected_issues"]:
        raise ReplayBlocked("ASSIGNED_ISSUE_MUST_BE_IN_REGISTERED_PLAN")
    return trial_id + ":" + issue


def _clock_floor(store, db, trial: dict, current: datetime) -> None:
    latest = _time(trial["accepted_at"])
    for kind in ("r45_prediction", "r45_draw"):
        for row in db.execute("SELECT payload,sha256 FROM events WHERE kind=?", (kind,)):
            event = store.checked(row)
            if event.get("trial_id") == trial["trial_id"]:
                latest = max(latest, _time(event.get("accepted_at")))
    if current < latest:
        raise ReplayBlocked("LOCAL_CLOCK_ROLLBACK_OR_BACKDATING")


def register_plan(store, plan: dict, *, now: datetime | None = None) -> str:
    """Persist a fixed research plan and its actual local acceptance time.

    A claimed old plan.registered_at is retained as a statement. Prediction
    admission uses accepted_at, so it cannot backdate a newly registered trial.
    """
    if type(plan) is not dict:
        raise ReplayBlocked("REGISTERED_PLAN_REQUIRED")
    expected = make_plan(plan.get("game"), plan.get("expected_issues"), plan.get("registered_at"),
                         plan.get("independent_series_id"), seed=plan.get("seed"))
    if plan != expected:
        raise ReplayBlocked("REGISTRY_OR_FAMILY_PLAN_REPLACED")
    current = _now(now)
    if _time(plan["registered_at"]) > current:
        raise ReplayBlocked("PLAN_CANNOT_BE_ACCEPTED_IN_ITS_FUTURE")
    trial_id = digest(plan)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            old = _get(store, db, "r45_trial", trial_id)
            if old is not None:
                _trial(store, db, trial_id)
                db.rollback()
                return trial_id
            for issue in plan["expected_issues"]:
                if _get(store, db, "r45_observed_draw", plan["game"] + ":" + issue) is not None:
                    raise ReplayBlocked("CANNOT_REGISTER_TRIAL_AFTER_OUTCOME_OBSERVED")
            event = {"trial_id": trial_id, "plan": plan,
                     "accepted_at": current.isoformat(), **BOUNDARY}
            _insert(db, "r45_trial", trial_id, event)
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return trial_id


def record_prediction(store, trial_id: str, prediction: dict,
                      frozen_at: str | datetime, now: datetime) -> bool:
    """Freeze only at the current local acceptance instant; refuse known draws.

    Exact retries of an already stored freeze return False. A retry cannot
    change its predictions or claimed freeze time, even after a process restart.
    """
    validate_prediction(prediction)
    current, requested_freeze = _now(now), _time(frozen_at)
    prediction_sha = digest(prediction)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            trial = _trial(store, db, trial_id)
            plan = trial["plan"]
            key = _key(trial_id, prediction["issue"], trial)
            if prediction["game"] != plan["game"] or prediction["seed"] != plan["seed"]:
                raise ReplayBlocked("PREDICTION_GAME_OR_FIXED_SEED_MISMATCH")
            old = _get(store, db, "r45_prediction", key)
            if old is not None:
                if (old["prediction_sha256"] != prediction_sha
                        or _time(old["frozen_at"]) != requested_freeze):
                    raise ReplayBlocked("IMMUTABLE_PREDICTION_CONFLICT")
                db.rollback()
                return False
            _clock_floor(store, db, trial, current)
            if requested_freeze != current:
                raise ReplayBlocked("BACKDATED_FREEZE_REJECTED_USE_LOCAL_NOW")
            observed_key = prediction["game"] + ":" + prediction["issue"]
            if (_get(store, db, "r45_observed_draw", observed_key) is not None
                    or _get(store, db, "r45_draw", key) is not None):
                raise ReplayBlocked("POST_DRAW_PREDICTION_REJECTED")
            event = {"trial_id": trial_id, "issue": prediction["issue"],
                     "prediction": prediction, "prediction_sha256": prediction_sha,
                     "frozen_at": current.isoformat(), "accepted_at": current.isoformat(),
                     "timestamp_status": "LOCAL_CLOCK_ONLY_NOT_EXTERNAL_TSA", **BOUNDARY}
            _insert(db, "r45_prediction", key, event)
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return True


def record_draw(store, trial_id: str, issue: str, front: list[int], back: list[int],
                draw_at: str | datetime, now: datetime, *, source_evidence: list[dict] | None = None) -> bool:
    """Record an observed research outcome; receipt metadata grants no authority.

    Source retrieval and agreement belong to the official-byte adapter. This API
    stores caller-supplied receipts as untrusted metadata, never as official or
    external publication-time verification. Synthetic callers stay research.
    """
    current, drawn = _now(now), _time(draw_at)
    if drawn > current:
        raise ReplayBlocked("F01_FUTURE_DRAW_REJECTED")
    if source_evidence is not None and (type(source_evidence) is not list
                                       or any(type(value) is not dict for value in source_evidence)):
        raise ReplayBlocked("SOURCE_RECEIPTS_MUST_BE_UNTRUSTED_METADATA_LIST")
    evidence = [] if source_evidence is None else source_evidence
    # Serialize before touching SQLite; rejects nonfinite or non-JSON metadata.
    canonical(evidence)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            trial = _trial(store, db, trial_id)
            game = trial["plan"]["game"]
            key = _key(trial_id, issue, trial)
            front_upper, front_count, back_upper, back_count = RULES[game]
            validate_numbers(front, front_count, front_upper)
            validate_numbers(back, back_count, back_upper)
            identity = {"game": game, "issue": issue, "front": sorted(front),
                        "back": sorted(back), "draw_at": drawn.isoformat()}
            old = _get(store, db, "r45_draw", key)
            if old is not None:
                if (any(old[field] != value for field, value in identity.items())
                        or old["source_evidence"] != evidence):
                    raise ReplayBlocked("IMMUTABLE_DRAW_OR_SOURCE_CONFLICT")
                db.rollback()
                return False
            _clock_floor(store, db, trial, current)
            prediction = _get(store, db, "r45_prediction", key)
            if prediction is not None and not _time(prediction["frozen_at"]) < drawn:
                raise ReplayBlocked("F01_PREDICTION_WAS_NOT_BEFORE_DRAW")
            observed_key = game + ":" + issue
            observed = _get(store, db, "r45_observed_draw", observed_key)
            if observed is not None and any(observed[field] != value for field, value in identity.items()):
                raise ReplayBlocked("GLOBAL_OBSERVED_DRAW_CONFLICT")
            event = {"trial_id": trial_id, **identity, "accepted_at": current.isoformat(),
                     "source_evidence": evidence,
                     "source_status": "CALLER_METADATA_ONLY_OFFICIAL_ADMISSION_BLOCKED", **BOUNDARY}
            if observed is None:
                _insert(db, "r45_observed_draw", observed_key,
                        {**identity, "accepted_at": current.isoformat(), **BOUNDARY})
            _insert(db, "r45_draw", key, event)
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return True


def replay_ready(store) -> dict:
    """Replay complete trials; missing periods stay visible, with no substitution."""
    trials = store.rows("r45_trial")
    if not trials:
        return {"status": "BLOCKED_NO_REGISTERED_TRIALS", "trials": [], **BOUNDARY}
    results = []
    for entry in trials:
        trial_id = entry.get("trial_id")
        try:
            with store.connect(True) as db:
                db.execute("BEGIN")
                trial = _trial(store, db, trial_id)
                rows, freezes, missing_predictions, missing_draws = [], {}, [], []
                for issue in trial["plan"]["expected_issues"]:
                    key = _key(trial_id, issue, trial)
                    prediction = _get(store, db, "r45_prediction", key)
                    draw = _get(store, db, "r45_draw", key)
                    if prediction is None:
                        missing_predictions.append(issue)
                    if draw is None:
                        missing_draws.append(issue)
                    if prediction is None or draw is None:
                        continue
                    if (prediction.get("trial_id") != trial_id or draw.get("trial_id") != trial_id
                            or prediction.get("issue") != issue or draw.get("issue") != issue
                            or prediction.get("prediction_sha256") != digest(prediction.get("prediction"))
                            or _time(prediction["frozen_at"]) != _time(prediction["accepted_at"])
                            or _time(prediction["accepted_at"]) < _time(trial["accepted_at"])):
                        raise ReplayBlocked("PERSISTED_FREEZE_IDENTITY_OR_SHA_MISMATCH")
                    freezes[issue] = prediction["prediction_sha256"]
                    rows.append({"game": trial["plan"]["game"], "issue": issue,
                                 "prediction": prediction["prediction"], "frozen_at": prediction["frozen_at"],
                                 "draw_at": draw["draw_at"], "draw_front": draw["front"], "draw_back": draw["back"]})
                db.rollback()
            if missing_predictions or missing_draws:
                results.append({"trial_id": trial_id, "status": "BLOCKED_MISSING_ISSUES",
                                "missing_predictions": missing_predictions, "missing_draws": missing_draws,
                                **BOUNDARY})
                continue
            evaluation = evaluate_registered(trial["plan"]["game"], rows, trial["plan"], freezes,
                                              plan_sha256=trial_id)
            result = {"trial_id": trial_id, "status": "REPLAYED_RESEARCH_ONLY",
                      "evaluation": evaluation,
                      "replay_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "competition_source_sha256": hashlib.sha256(Path(competition.__file__).read_bytes()).hexdigest(),
                      **BOUNDARY}
            # One result per trial. Exact process retries are no-ops; changes fail.
            store.append("r45_replay_result", trial_id, result)
            results.append(result)
        except (ValueError, KeyError, TypeError) as exc:
            results.append({"trial_id": trial_id, "status": "BLOCKED_INVALID_REPLAY_EVIDENCE",
                            "reason": str(exc), **BOUNDARY})
    status = ("REPLAYED_RESEARCH_ONLY" if all(r["status"] == "REPLAYED_RESEARCH_ONLY" for r in results)
              else "BLOCKED_INCOMPLETE_OR_INVALID_TRIALS")
    return {"status": status, "trials": results, **BOUNDARY}


def write_replay_report(directory, result: dict) -> Path:
    """Write a content-addressed, immutable JSON/CSV/HTML report plus SHA manifest.

    Missing trials also produce explicit BLOCKED artifacts. Exact retries reuse
    verified files. A changed or incomplete existing artifact fails closed.
    """
    directory = Path(directory)
    if not directory.is_absolute():
        raise ReplayBlocked("ABSOLUTE_REPLAY_REPORT_DIRECTORY_REQUIRED")
    if (type(result) is not dict or type(result.get("status")) is not str
            or type(result.get("trials")) is not list
            or any(result.get(key) != value for key, value in BOUNDARY.items())):
        raise ReplayBlocked("REPLAY_REPORT_RESEARCH_BOUNDARY_REQUIRED")
    body = canonical(result).encode("utf-8")
    writer_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report_id = digest({"result": result, "writer_source_sha256": writer_sha})
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / report_id

    def verify_existing():
        from .store import parse
        try:
            if (target / "replay.json").read_bytes() != body:
                raise ReplayBlocked("IMMUTABLE_REPLAY_JSON_CONFLICT")
            manifest = parse((target / "SHA256.json").read_bytes())
            if (manifest.get("report_id") != report_id
                    or manifest.get("writer_source_sha256") != writer_sha
                    or set(manifest.get("files", {})) != {"replay.json", "replay.csv", "replay.html"}):
                raise ReplayBlocked("REPLAY_MANIFEST_IDENTITY_MISMATCH")
            for name, expected_sha in manifest["files"].items():
                if hashlib.sha256((target / name).read_bytes()).hexdigest() != expected_sha:
                    raise ReplayBlocked("REPLAY_REPORT_FILE_SHA_MISMATCH")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, ReplayBlocked):
                raise
            raise ReplayBlocked("INCOMPLETE_OR_INVALID_EXISTING_REPLAY_REPORT") from exc

    if target.exists():
        verify_existing()
        return target
    stage = directory / ("." + uuid.uuid4().hex)
    stage.mkdir(exist_ok=False)
    (stage / "replay.json").write_bytes(body)
    fields = ["row_type", "trial_id", "status", "game", "issue", "model", "dan_k",
              "hits", "full", "p0", "wins", "losses", "ties", "p_one_sided",
              "p_holm_research", "reason", "formal_A", "decision"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerow({"row_type": "overall", "status": result["status"],
                     "formal_A": 0, "decision": "NO_EDGE"})
    for trial in result["trials"]:
        base = {"trial_id": trial.get("trial_id", ""), "status": trial.get("status", ""),
                "formal_A": 0, "decision": "NO_EDGE"}
        evaluation = trial.get("evaluation", {})
        writer.writerow({**base, "row_type": "trial", "game": evaluation.get("game", ""),
                         "reason": trial.get("reason", "") or canonical({key: trial[key] for key in
                                    ("missing_predictions", "missing_draws") if key in trial})})
        for period in evaluation.get("period_scores", []):
            for model, scores in period["models"].items():
                for dan_k, score in scores.items():
                    writer.writerow({**base, "row_type": "period", "game": evaluation["game"],
                                     "issue": period["issue"], "model": model, "dan_k": dan_k,
                                     "hits": score["hits"], "full": score["full"], "p0": score["p0"]})
        for comparison in evaluation.get("pairwise_vs_null", []):
            writer.writerow({**base, "row_type": "paired_comparison", "game": evaluation["game"],
                             **{key: comparison[key] for key in ("model", "wins", "losses", "ties",
                                                                 "p_one_sided", "p_holm_research")}})
    (stage / "replay.csv").write_text(stream.getvalue(), encoding="utf-8-sig", newline="")
    page = ("<!doctype html><html lang='zh-Hant'><meta charset='utf-8'>"
            "<title>SSQ＋DLT V4.5 研究 Replay</title>"
            "<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse}"
            "td,th{border:1px solid #bbb;padding:8px;text-align:left}</style>"
            "<h1>SSQ＋DLT V4.5 非正式研究 Replay</h1><p>狀態：" + html.escape(result["status"]) +
            "</p><p>formal_A=0 · NO_EDGE · 正式資格 BLOCKED</p>"
            "<p>公平 D2：SSQ=15/528；DLT=10/595。研究 Holm 只涵蓋四個模型對同期固定種子 Random NULL。"
            "正式十二項檢驗、01／02／03／04批准、外部可信事前時間封存及獨立前瞻資格尚未取得。</p>")
    if not result["trials"]:
        page += "<p>BLOCKED：沒有已登錄的合法目標期研究試驗。尚無可重放事前預測。</p>"
    for trial in result["trials"]:
        page += ("<h2>試驗 " + html.escape(str(trial.get("trial_id", ""))) + "</h2><p>" +
                 html.escape(str(trial.get("status", ""))) + "</p>")
        evaluation = trial.get("evaluation", {})
        if evaluation:
            page += ("<p>彩種：" + html.escape(evaluation["game"]) + "；完整期次：" +
                     html.escape(str(evaluation["n"])) + "</p><table><tr><th>模型</th><th>勝／負／同</th>"
                     "<th>配對單尾 p</th><th>研究 Holm p</th></tr>")
            for comparison in evaluation["pairwise_vs_null"]:
                page += ("<tr><td>" + html.escape(comparison["model"]) + "</td><td>" +
                         "/".join(html.escape(str(comparison[key])) for key in ("wins", "losses", "ties")) +
                         "</td><td>" + html.escape(str(comparison["p_one_sided"])) + "</td><td>" +
                         html.escape(str(comparison["p_holm_research"])) + "</td></tr>")
            page += "</table>"
    page += "<h2>完整證據資料</h2><pre>" + html.escape(body.decode("utf-8")) + "</pre></html>"
    (stage / "replay.html").write_text(page, encoding="utf-8")
    manifest = {"report_id": report_id, "writer_source_sha256": writer_sha,
                "files": {name: hashlib.sha256((stage / name).read_bytes()).hexdigest()
                          for name in ("replay.json", "replay.csv", "replay.html")}, **BOUNDARY}
    (stage / "SHA256.json").write_text(canonical(manifest), encoding="utf-8")
    try:
        stage.rename(target)
    except FileExistsError:
        verify_existing()
        # Preserve the redundant staging copy for forensic diagnosis.
    return target
