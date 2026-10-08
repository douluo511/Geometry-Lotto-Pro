from __future__ import annotations

import hashlib
import json
import random
import re
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .constants import PROMOTION_POLICY
from .domain import Draw, Prediction
from .engine import make_prediction, model_identity, replay_prediction
from .evidence import bootstrap_ci, permutation_p
from .util import atomic_json, next_draw_date, next_issue, parse_date, sha256_json, utc_now


PROTOCOL_VERSION = "dlt-prospective-only-v2-behavior-identity"
SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
BEHAVIOR_PATHS = (
    "src/glp/constants.py",
    "src/glp/domain.py",
    "src/glp/net_client.py",
    "src/glp/sources.py",
    "src/glp/storage.py",
    "src/glp/engine.py",
    "src/glp/evidence.py",
    "src/glp/prospective.py",
    "src/glp/background.py",
    "src/glp/service.py",
    "src/glp/util.py",
    "src/main.py",
    "scripts/prospective_snapshot.py",
)


def _require_source_commit(value: str) -> str:
    value = str(value or "").strip().lower()
    if not SOURCE_COMMIT_RE.fullmatch(value):
        raise ValueError("prospective source_commit must be an exact 40/64 hex commit id")
    return value


def _behavior_hash_from_files(hashes: dict[str, str]) -> str:
    return sha256_json(dict(sorted(hashes.items())))


def _behavior_fingerprint(override: str | None = None) -> dict[str, Any]:
    if override is not None:
        value = str(override).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("behavior hash override must be 64 lowercase hex characters")
        return {
            "behavior_hash": value,
            "behavior_files": {"test_override": value},
        }

    dlt_root = Path(__file__).resolve().parents[2]
    hashes: dict[str, str] = {}
    for rel in BEHAVIOR_PATHS:
        path = dlt_root / rel
        if not path.is_file():
            raise FileNotFoundError(f"behavior identity file missing: {rel}")
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "behavior_hash": _behavior_hash_from_files(hashes),
        "behavior_files": hashes,
    }


def _identity(
    source_commit: str,
    *,
    behavior_hash_override: str | None = None,
) -> dict[str, Any]:
    source_commit = _require_source_commit(source_commit)
    ident = model_identity()
    behavior = _behavior_fingerprint(behavior_hash_override)
    protocol_spec = {
        "protocol_version": PROTOCOL_VERSION,
        "behavior_hash": behavior["behavior_hash"],
        "behavior_files": behavior["behavior_files"],
        "model_hash": ident["model_hash"],
        "selector_hash": ident["selector_hash"],
        "model_spec": ident["spec"],
        "promotion_policy": dict(PROMOTION_POLICY),
        "qualification": {
            "minimum_valid_replays": int(PROMOTION_POLICY["min_prospective_replays"]),
            "areas": ("front", "back"),
            "baseline": "same-target deterministic uniform random rankings",
            "bootstrap_lower_must_exceed": 0.0,
            "permutation_alpha": float(PROMOTION_POLICY["alpha"]),
            "split_half_required": True,
        },
    }
    protocol_spec = json.loads(json.dumps(protocol_spec, ensure_ascii=False, sort_keys=True))
    protocol_hash = sha256_json(protocol_spec)
    cohort_id = sha256_json(
        {
            "protocol_hash": protocol_hash,
            "behavior_hash": behavior["behavior_hash"],
            "model_hash": ident["model_hash"],
            "selector_hash": ident["selector_hash"],
        }
    )[:24]
    return {
        "cohort_id": cohort_id,
        "protocol_hash": protocol_hash,
        "initial_source_commit": source_commit,
        "behavior_hash": behavior["behavior_hash"],
        "behavior_files": behavior["behavior_files"],
        "model_hash": ident["model_hash"],
        "selector_hash": ident["selector_hash"],
        "protocol_spec": protocol_spec,
    }

def _random_ranking(max_n: int, seed_material: Any) -> list[int]:
    seed = int(sha256_json(seed_material)[:16], 16)
    rng = random.Random(seed)
    values = list(range(1, max_n + 1))
    rng.shuffle(values)
    return values


def _recall(ranking: list[int], actual: tuple[int, ...], k: int) -> float:
    return len(set(ranking[:k]) & set(actual)) / float(k)


# Chinese DLT draws use China civil dates. A same-day Freeze is excluded until a
# separately verified official draw cutoff-time contract is available. This
# conservative boundary prevents back-dated / stale-history qualification.
DRAW_TIMEZONE = timezone(timedelta(hours=8))


def _require_utc_timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not (value.endswith("Z") or value.endswith("+00:00")):
        raise ValueError(f"{field} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} invalid UTC timestamp") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc)


def _require_pre_draw_freeze(
    *,
    registered_at: str,
    prediction_created_at: str,
    target_date: str,
) -> None:
    registered = _require_utc_timestamp(registered_at, "freeze registration")
    predicted = _require_utc_timestamp(prediction_created_at, "prediction creation")
    try:
        target = date.fromisoformat(target_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("prospective target date invalid") from exc
    if predicted > registered:
        raise ValueError("late/post-draw prospective freeze: prediction created after registration")
    if registered.astimezone(DRAW_TIMEZONE).date() >= target:
        raise ValueError("late/post-draw prospective freeze: registered on/after China target date")


def _validate_prediction_shape(prediction: Prediction) -> None:
    """Reject malformed candidate lists/rankings before they become research evidence.

    Hashing a malformed ranking only makes a malformed result immutable; it does
    not make its denominator, score or claimed dan scientifically meaningful.
    """
    for name, picked, count, universe in (
        ("front", prediction.front, 5, 35),
        ("back", prediction.back, 2, 12),
    ):
        if (
            not isinstance(picked, (tuple, list))
            or len(picked) != count
            or any(type(x) is not int for x in picked)
            or sorted(picked) != list(picked)
            or len(set(picked)) != count
            or not all(1 <= x <= universe for x in picked)
        ):
            raise ValueError(f"prospective {name} combination malformed")
        ranking = getattr(prediction, f"{name}_ranking")
        if (
            not isinstance(ranking, (tuple, list))
            or len(ranking) != universe
            or any(type(x) is not int for x in ranking)
            or set(ranking) != set(range(1, universe + 1))
        ):
            raise ValueError(f"prospective {name} ranking invalid or incomplete")

    if prediction.edge_state != "NO_EDGE" or prediction.dan_state != "NULL_DAN":
        raise ValueError("prospective research cohort must stay NO_EDGE / NULL_DAN")

    front_dan, back_dan = prediction.research_dan_front, prediction.research_dan_back
    if (
        not isinstance(front_dan, (tuple, list))
        or len(front_dan) not in (1, 2)
        or list(front_dan) != list(prediction.front_ranking[:len(front_dan)])
    ):
        raise ValueError("prospective front research dan does not match exact ranking")
    if (
        not isinstance(back_dan, (tuple, list))
        or len(back_dan) != 1
        or list(back_dan) != list(prediction.back_ranking[:1])
    ):
        raise ValueError("prospective back research dan does not match exact ranking")

    for field in ("canonical_hash", "model_hash", "selector_hash", "score_hash"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(getattr(prediction, field))):
            raise ValueError(f"prospective {field} must be SHA-256")
    if not re.fullmatch(r"[0-9a-f]{20}", str(prediction.prediction_id)):
        raise ValueError("prospective prediction_id must be 20 lowercase hex chars")
    _require_utc_timestamp(prediction.created_at, "prediction creation")


def _freeze_hash(payload: dict[str, Any]) -> str:
    value = json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    value["freeze_hash"] = ""
    return sha256_json(value)


def _write_immutable_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if current != value:
            raise ValueError(f"immutable prospective evidence differs: {path.name}")
        return
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as fh:
        fh.write(data)


@dataclass(frozen=True)
class CohortPaths:
    root: Path
    cohort_id: str

    @property
    def cohort_dir(self) -> Path:
        return self.root / "cohorts" / self.cohort_id

    @property
    def manifest(self) -> Path:
        return self.cohort_dir / "manifest.json"

    @property
    def freezes(self) -> Path:
        return self.cohort_dir / "freezes"

    @property
    def replays(self) -> Path:
        return self.cohort_dir / "replays"

    @property
    def status(self) -> Path:
        return self.cohort_dir / "status.json"


class ProspectiveLedger:
    """
    File-backed, Git-friendly prospective evidence ledger.

    Immutable evidence lives in per-target freeze/replay files. Mutable index/status
    files are summaries only; their entire history remains auditable when committed
    to Git. Cohort reset is driven by behavior/model/selector/protocol identity.
    Exact source commits remain per-Freeze provenance and docs-only commits do not reset.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"

    def activate(
        self,
        source_commit: str,
        *,
        behavior_hash_override: str | None = None,
    ) -> dict[str, Any]:
        ident = _identity(source_commit, behavior_hash_override=behavior_hash_override)
        now = utc_now()
        paths = CohortPaths(self.root, ident["cohort_id"])
        manifest = {
            "schema": "dlt-prospective-cohort-v2",
            "status": "ACTIVE",
            "created_at": now,
            **ident,
            "production_rho": 0.0,
            "production_edge_state": "NO_EDGE",
            "production_dan_state": "NULL_DAN",
            "promotion_authorized": False,
        }
        if paths.manifest.exists():
            existing = json.loads(paths.manifest.read_text(encoding="utf-8"))
            immutable_keys = (
                "cohort_id", "protocol_hash", "behavior_hash", "behavior_files",
                "model_hash", "selector_hash", "protocol_spec",
            )
            if any(existing.get(k) != manifest.get(k) for k in immutable_keys):
                raise ValueError("existing cohort manifest identity mismatch")
            manifest = existing
        else:
            _write_immutable_json(paths.manifest, manifest)

        index: dict[str, Any]
        if self.index_path.exists():
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        else:
            index = {
                "schema": "dlt-prospective-index-v1",
                "created_at": now,
                "active_cohort_id": None,
                "cohort_history": [],
            }

        old_id = index.get("active_cohort_id")
        if old_id != ident["cohort_id"]:
            if old_id:
                index.setdefault("cohort_history", []).append(
                    {
                        "cohort_id": old_id,
                        "ended_at": now,
                        "reason": "PROTOCOL_IDENTITY_CHANGED",
                        "replacement_cohort_id": ident["cohort_id"],
                    }
                )
            index["active_cohort_id"] = ident["cohort_id"]
            index["activated_at"] = now
            index["reset_count"] = int(index.get("reset_count", 0)) + (1 if old_id else 0)
            atomic_json(self.index_path, index)
        return manifest

    def active_manifest(self) -> dict[str, Any]:
        if not self.index_path.exists():
            raise FileNotFoundError("prospective cohort is not activated")
        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        cohort_id = str(index.get("active_cohort_id") or "")
        if not cohort_id:
            raise ValueError("prospective active cohort id missing")
        path = CohortPaths(self.root, cohort_id).manifest
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("cohort_id") != cohort_id:
            raise ValueError("prospective active cohort manifest mismatch")
        return value

    def register_freeze(
        self,
        prediction: Prediction,
        *,
        draws: list[Draw],
        canonical_hash: str,
        source_commit: str,
        behavior_hash_override: str | None = None,
    ) -> dict[str, Any]:
        source_commit = _require_source_commit(source_commit)
        manifest = self.activate(
            source_commit,
            behavior_hash_override=behavior_hash_override,
        )
        existing_issues = {d.issue for d in draws}
        if prediction.target_issue in existing_issues:
            raise ValueError(
                f"late/post-draw prospective freeze rejected: target {prediction.target_issue} already exists"
            )
        if prediction.canonical_hash != canonical_hash:
            raise ValueError("prediction canonical hash mismatch")
        if prediction.model_hash != manifest["model_hash"]:
            raise ValueError("prediction model hash differs from active cohort")
        if prediction.selector_hash != manifest["selector_hash"]:
            raise ValueError("prediction selector hash differs from active cohort")
        if prediction.edge_state != "NO_EDGE" or prediction.dan_state != "NULL_DAN":
            raise ValueError("prospective research cohort must stay NO_EDGE / NULL_DAN")
        if prediction.target_date <= draws[-1].draw_date:
            raise ValueError("prospective target date is not after latest official draw")
        _validate_prediction_shape(prediction)
        expected_issue = next_issue(draws[-1].issue, draws[-1].draw_date)
        expected_date = next_draw_date(parse_date(draws[-1].draw_date)).isoformat()
        if prediction.target_issue != expected_issue or prediction.target_date != expected_date:
            raise ValueError("prospective target issue/date inconsistent with canonical schedule")

        # Do not trust a stale-but-structurally-valid official baseline: its next
        # target may already have happened even if that issue is absent in draws.
        registration_time = utc_now()
        _require_pre_draw_freeze(
            registered_at=registration_time,
            prediction_created_at=prediction.created_at,
            target_date=prediction.target_date,
        )

        paths = CohortPaths(self.root, manifest["cohort_id"])
        existing_path = paths.freezes / f"{prediction.target_issue}.json"
        if existing_path.exists():
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            existing_pred = Prediction(**existing["prediction"])
            if (
                existing.get("cohort_id") != manifest["cohort_id"]
                or existing.get("protocol_hash") != manifest["protocol_hash"]
                or existing_pred.model_hash != manifest["model_hash"]
                or existing_pred.selector_hash != manifest["selector_hash"]
                or existing_pred.canonical_hash != canonical_hash
            ):
                raise ValueError("existing prospective freeze identity mismatch")
            if _freeze_hash(existing_pred.to_dict()) != existing_pred.freeze_hash:
                raise ValueError("existing prospective freeze hash mismatch")
            _require_pre_draw_freeze(
                registered_at=existing["registered_at"],
                prediction_created_at=existing_pred.created_at,
                target_date=existing["target_date"],
            )
            return existing

        p = prediction.to_dict()
        p["freeze_hash"] = ""
        p["freeze_hash"] = _freeze_hash(p)
        frozen = Prediction(**p)
        evidence = {
            "schema": "dlt-prospective-freeze-v1",
            "cohort_id": manifest["cohort_id"],
            "protocol_hash": manifest["protocol_hash"],
            "source_commit": source_commit,
            "registered_at": registration_time,
            "canonical_hash": canonical_hash,
            "latest_observed_issue": draws[-1].issue,
            "target_issue": frozen.target_issue,
            "target_date": frozen.target_date,
            "research_only": True,
            "production_rho": 0.0,
            "promotion_authorized": False,
            "prediction": frozen.to_dict(),
        }
        evidence["record_hash"] = sha256_json(evidence)
        path = paths.freezes / f"{frozen.target_issue}.json"
        _write_immutable_json(path, evidence)
        return evidence

    def freeze_records(self, cohort_id: str | None = None) -> list[dict[str, Any]]:
        if cohort_id is None:
            cohort_id = self.active_manifest()["cohort_id"]
        path = CohortPaths(self.root, cohort_id).freezes
        if not path.exists():
            return []
        values = []
        for file in sorted(path.glob("*.json")):
            value = json.loads(file.read_text(encoding="utf-8"))
            expected = value.get("record_hash")
            check = dict(value)
            check.pop("record_hash", None)
            if expected != sha256_json(check):
                raise ValueError(f"prospective freeze record hash mismatch: {file.name}")
            pred = Prediction(**value["prediction"])
            _validate_prediction_shape(pred)
            _require_pre_draw_freeze(
                registered_at=value.get("registered_at"),
                prediction_created_at=pred.created_at,
                target_date=value.get("target_date"),
            )
            if _freeze_hash(pred.to_dict()) != pred.freeze_hash:
                raise ValueError(f"prospective prediction freeze hash mismatch: {file.name}")
            values.append(value)
        return values

    def replay_available(self, draws: list[Draw]) -> list[dict[str, Any]]:
        manifest = self.active_manifest()
        actual_by_issue = {d.issue: d for d in draws}
        created: list[dict[str, Any]] = []
        for freeze in self.freeze_records(manifest["cohort_id"]):
            target = str(freeze["target_issue"])
            actual = actual_by_issue.get(target)
            if actual is None:
                continue
            pred = Prediction(**freeze["prediction"])
            replay_path = CohortPaths(self.root, manifest["cohort_id"]).replays / f"{target}.json"
            if replay_path.exists():
                continue
            replay = replay_prediction(pred, actual)
            seeds = tuple(PROMOTION_POLICY["seeds"])
            front_random = statistics.mean(
                _recall(
                    _random_ranking(35, [PROTOCOL_VERSION, "front", seed, target]),
                    actual.front,
                    5,
                )
                for seed in seeds
            )
            back_random = statistics.mean(
                _recall(
                    _random_ranking(12, [PROTOCOL_VERSION, "back", seed, target]),
                    actual.back,
                    2,
                )
                for seed in seeds
            )
            front_recall = _recall(pred.front_ranking, actual.front, 5)
            back_recall = _recall(pred.back_ranking, actual.back, 2)
            row = {
                "schema": "dlt-prospective-replay-v1",
                "cohort_id": manifest["cohort_id"],
                "protocol_hash": manifest["protocol_hash"],
                "source_commit": freeze["source_commit"],
                "replayed_at": utc_now(),
                "target_issue": target,
                "freeze_hash": pred.freeze_hash,
                "selector_hash": pred.selector_hash,
                "model_hash": pred.model_hash,
                "actual": actual.to_dict(),
                "front_recall": front_recall,
                "back_recall": back_recall,
                "front_random_recall": front_random,
                "back_random_recall": back_random,
                "front_gain_vs_random": front_recall - front_random,
                "back_gain_vs_random": back_recall - back_random,
                "replay": replay,
            }
            row["record_hash"] = sha256_json(row)
            _write_immutable_json(replay_path, row)
            created.append(row)
        return created

    def replay_records(self, cohort_id: str | None = None) -> list[dict[str, Any]]:
        if cohort_id is None:
            cohort_id = self.active_manifest()["cohort_id"]
        path = CohortPaths(self.root, cohort_id).replays
        if not path.exists():
            return []
        values = []
        freezes = {x["target_issue"]: x for x in self.freeze_records(cohort_id)}
        for file in sorted(path.glob("*.json")):
            value = json.loads(file.read_text(encoding="utf-8"))
            expected = value.get("record_hash")
            check = dict(value)
            check.pop("record_hash", None)
            if expected != sha256_json(check):
                raise ValueError(f"prospective replay record hash mismatch: {file.name}")
            freeze = freezes.get(value.get("target_issue"))
            valid = (
                freeze is not None
                and value.get("cohort_id") == cohort_id
                and value.get("protocol_hash") == freeze.get("protocol_hash")
                and value.get("source_commit") == freeze.get("source_commit")
                and value.get("freeze_hash") == freeze["prediction"].get("freeze_hash")
                and value.get("selector_hash") == freeze["prediction"].get("selector_hash")
                and value.get("model_hash") == freeze["prediction"].get("model_hash")
                and value.get("target_issue") == value.get("actual", {}).get("issue")
                and value.get("actual", {}).get("draw_date") == freeze.get("target_date")
                and value.get("target_issue") == value.get("replay", {}).get("actual_issue")
            )
            if not valid:
                raise ValueError(f"prospective replay identity mismatch: {file.name}")

            # A digest over self-reported scores does not certify those scores.
            # Recompute every replay field from the immutable Freeze and the
            # official winning draw, including the frozen random seed baseline.
            pred = Prediction(**freeze["prediction"])
            try:
                actual = Draw.from_dict(value["actual"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"prospective replay actual is invalid: {file.name}") from exc
            if actual.draw_date != freeze.get("target_date"):
                raise ValueError(f"prospective replay actual date mismatch: {file.name}")
            if value.get("replay") != replay_prediction(pred, actual):
                raise ValueError(f"prospective replay recomputed hits/ranks mismatch: {file.name}")

            seeds = tuple(PROMOTION_POLICY["seeds"])
            expected = {
                "front_recall": _recall(pred.front_ranking, actual.front, 5),
                "back_recall": _recall(pred.back_ranking, actual.back, 2),
                "front_random_recall": statistics.mean(
                    _recall(
                        _random_ranking(35, [PROTOCOL_VERSION, "front", seed, actual.issue]),
                        actual.front, 5,
                    ) for seed in seeds
                ),
                "back_random_recall": statistics.mean(
                    _recall(
                        _random_ranking(12, [PROTOCOL_VERSION, "back", seed, actual.issue]),
                        actual.back, 2,
                    ) for seed in seeds
                ),
            }
            expected["front_gain_vs_random"] = expected["front_recall"] - expected["front_random_recall"]
            expected["back_gain_vs_random"] = expected["back_recall"] - expected["back_random_recall"]
            for field_name, expected_value in expected.items():
                given = value.get(field_name)
                if (
                    isinstance(given, bool) or not isinstance(given, (int, float))
                    or abs(given - expected_value) > 1e-12
                ):
                    raise ValueError(
                        f"prospective replay recomputed {field_name} mismatch: {file.name}"
                    )
            values.append(value)
        return values

    @staticmethod
    def _metric(values: list[float], seed: int) -> dict[str, Any]:
        mean = statistics.mean(values) if values else 0.0
        lo, hi = bootstrap_ci(values, seed=seed)
        p = permutation_p(values, seed=seed + 1000)
        return {
            "n": len(values),
            "mean_gain": mean,
            "bootstrap95": [lo, hi],
            "permutation_p": p,
            "pass": bool(values) and mean > 0.0 and lo > 0.0 and p < float(PROMOTION_POLICY["alpha"]),
        }

    def qualification(
        self,
        cohort_id: str | None = None,
        *,
        official_draws: list[Draw] | None = None,
    ) -> dict[str, Any]:
        manifest = self.active_manifest() if cohort_id is None else json.loads(
            CohortPaths(self.root, cohort_id).manifest.read_text(encoding="utf-8")
        )
        rows = self.replay_records(manifest["cohort_id"])
        required = int(PROMOTION_POLICY["min_prospective_replays"])

        # Internal self-consistency and SHA-256 alone cannot prove a reported
        # winner is the official actual result. No live canonical -> no
        # qualifying replay count, even when self-reported scores are positive.
        if official_draws is None:
            return {
                "decision": "NOT_READY",
                "reason": "OFFICIAL_ACTUALS_NOT_BOUND",
                "valid_replays": 0,
                "unverified_replay_files": len(rows),
                "required_replays": required,
                "front": None,
                "back": None,
                "split_halves": [],
                "promotion_authorized": False,
                "production_rho": 0.0,
            }

        actual_by_issue: dict[str, Draw] = {}
        for actual in official_draws:
            actual.validate()
            if actual.issue in actual_by_issue:
                raise ValueError("official canonical prospective draws contain duplicate issue")
            actual_by_issue[actual.issue] = actual
        for row in rows:
            target_issue = row["target_issue"]
            official_actual = actual_by_issue.get(target_issue)
            if official_actual is None or row.get("actual") != official_actual.to_dict():
                raise ValueError(
                    f"prospective replay actual differs from live official canonical: {target_issue}"
                )

        front = [float(x["front_gain_vs_random"]) for x in rows]
        back = [float(x["back_gain_vs_random"]) for x in rows]
        if len(rows) < required:
            return {
                "decision": "NOT_READY",
                "valid_replays": len(rows),
                "required_replays": required,
                "front": None,
                "back": None,
                "split_halves": [],
                "promotion_authorized": False,
                "production_rho": 0.0,
            }

        front_result = self._metric(front, 71000)
        back_result = self._metric(back, 72000)
        half = len(rows) // 2
        split_halves = []
        split_pass = True
        for i, (fvals, bvals) in enumerate(
            ((front[:half], back[:half]), (front[half:], back[half:])),
            start=1,
        ):
            f = self._metric(fvals, 73000 + i * 100)
            b = self._metric(bvals, 74000 + i * 100)
            passed = f["pass"] and b["pass"]
            split_pass = split_pass and passed
            split_halves.append({"half": i, "front": f, "back": b, "pass": passed})

        candidate = front_result["pass"] and back_result["pass"] and split_pass
        return {
            "decision": "PROSPECTIVE_EDGE_CANDIDATE" if candidate else "NO_EDGE",
            "valid_replays": len(rows),
            "required_replays": required,
            "front": front_result,
            "back": back_result,
            "split_halves": split_halves,
            # This protocol never promotes production by itself. Existing Evidence Court remains mandatory.
            "promotion_authorized": False,
            "production_rho": 0.0,
        }

    def status(self, *, official_draws: list[Draw] | None = None) -> dict[str, Any]:
        manifest = self.active_manifest()
        freezes = self.freeze_records(manifest["cohort_id"])
        replays = self.replay_records(manifest["cohort_id"])
        replayed = {x["target_issue"] for x in replays}
        qualification = self.qualification(
            manifest["cohort_id"], official_draws=official_draws
        )
        status = {
            "schema": "dlt-prospective-status-v1",
            "created_at": utc_now(),
            "cohort_id": manifest["cohort_id"],
            "protocol_hash": manifest["protocol_hash"],
            "initial_source_commit": manifest["initial_source_commit"],
            "behavior_hash": manifest["behavior_hash"],
            "model_hash": manifest["model_hash"],
            "selector_hash": manifest["selector_hash"],
            "freeze_count": len(freezes),
            "valid_replays": qualification["valid_replays"],
            "unverified_replay_files": len(replays) if official_draws is None else 0,
            "official_actuals_bound": official_draws is not None,
            "pending_targets": [x["target_issue"] for x in freezes if x["target_issue"] not in replayed],
            "qualification": qualification,
            "edge_state": "NO_EDGE",
            "dan_state": "NULL_DAN",
            "production_rho": 0.0,
            "promotion_authorized": False,
        }
        atomic_json(CohortPaths(self.root, manifest["cohort_id"]).status, status)
        return status


def run_prospective_cycle(
    draws: list[Draw],
    canonical_hash: str,
    *,
    ledger_root: Path,
    source_commit: str,
    behavior_hash_override: str | None = None,
    prediction_builder: Callable[[list[Draw], str, dict | None], tuple[Prediction, dict[str, Any]]] = make_prediction,
) -> dict[str, Any]:
    if not draws:
        raise ValueError("prospective cycle requires official history")
    for draw in draws:
        draw.validate()
    if draws != sorted(draws, key=lambda d: (d.draw_date, d.issue)):
        raise ValueError("prospective cycle requires chronological draws")
    if len({d.issue for d in draws}) != len(draws):
        raise ValueError("prospective cycle rejects duplicate issues")

    ledger = ProspectiveLedger(ledger_root)
    source_commit = _require_source_commit(source_commit)
    manifest = ledger.activate(
        source_commit,
        behavior_hash_override=behavior_hash_override,
    )
    replayed = ledger.replay_available(draws)

    prediction, trace = prediction_builder(draws, canonical_hash, None)
    freeze = ledger.register_freeze(
        prediction,
        draws=draws,
        canonical_hash=canonical_hash,
        source_commit=source_commit,
        behavior_hash_override=behavior_hash_override,
    )
    status = ledger.status(official_draws=draws)
    return {
        "schema": "dlt-prospective-cycle-v1",
        "created_at": utc_now(),
        "cohort": manifest,
        "cycle_source_commit": source_commit,
        "behavior_hash": manifest["behavior_hash"],
        "new_replays": [x["target_issue"] for x in replayed],
        "freeze": freeze,
        "status": status,
        "effect_trace": trace,
        "production_rho": 0.0,
        "promotion_authorized": False,
    }
