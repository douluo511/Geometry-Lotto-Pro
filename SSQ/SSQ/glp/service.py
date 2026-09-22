from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from glp.constants import APP_VERSION, BACK_MAX, BACK_PICK, FRONT_MAX, FRONT_PICK, GAME
from glp.engine import make_prediction, model_identity
from glp.domain import Draw
from glp.evidence import run_evidence_court
from glp.ors import build_ors_record
from glp.sources import build_canonical
from glp.storage import Store
from glp.util import sha256_bytes, sha256_json, utc_now


def resource_path(name: str) -> Path:
    roots = []
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        roots.append(Path(frozen))
    roots.append(Path(__file__).resolve().parent.parent)
    for root in roots:
        p = root / "resources" / name
        if p.exists():
            return p
    raise FileNotFoundError(name)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class LottoService:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def _load_draws(self):
        draws, canonical_hash = self.store.load_draws()
        if canonical_hash != self._canonical_hash():
            raise ValueError("canonical hash mismatch in storage adapter")
        return draws

    def _db(self) -> sqlite3.Connection:
        return self.store._connect()  # baseline Store owns schema + immutable triggers

    def _append_experiment(self, kind: str, status: str, input_hash: str, payload: dict[str, Any]) -> int:
        code_hash = sha256_json({"app_version": APP_VERSION, "module": kind})
        db = self._db()
        try:
            cur = db.execute(
                "INSERT INTO experiments(created_at,kind,status,input_hash,code_hash,payload_json) VALUES(?,?,?,?,?,?)",
                (utc_now(), kind, status, input_hash, code_hash, _json_dumps(payload)),
            )
            db.commit()
            return int(cur.lastrowid)
        finally:
            db.close()

    def _history_payload(self) -> dict[str, Any]:
        return json.loads(Path(self.store.history_path).read_text(encoding="utf-8"))

    def _canonical_hash(self) -> str:
        payload = self._history_payload()
        return str(payload.get("canonical_hash") or sha256_json(payload.get("draws", [])))

    def _ensure_seed_files(self) -> None:
        """Create missing baseline files without trusting or validating existing bytes."""
        history = Path(self.store.history_path)
        evidence = Path(self.store.evidence_path)
        history.parent.mkdir(parents=True, exist_ok=True)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        if not history.exists():
            shutil.copyfile(resource_path("official_seed.json"), history)
        if not evidence.exists():
            shutil.copyfile(resource_path("official_seed_evidence.json"), evidence)

    def ensure_seed(self) -> None:
        self._ensure_seed_files()
        history = Path(self.store.history_path)
        # Validate that the baseline really is SSQ; never silently accept DLT data.
        payload = json.loads(history.read_text(encoding="utf-8"))
        if payload.get("game") != "SSQ":
            raise RuntimeError("dataset game mismatch: expected SSQ")
        draws = payload.get("draws", [])
        if not draws:
            raise RuntimeError("empty SSQ canonical history")
        for d in draws[-min(50, len(draws)):]:
            front = list(d.get("front", [])); back = list(d.get("back", []))
            if len(front) != FRONT_PICK or len(set(front)) != FRONT_PICK or not all(1 <= int(x) <= FRONT_MAX for x in front):
                raise RuntimeError("invalid SSQ red-ball record")
            if len(back) != BACK_PICK or len(set(back)) != BACK_PICK or not all(1 <= int(x) <= BACK_MAX for x in back):
                raise RuntimeError("invalid SSQ blue-ball record")

    def _prospective_replays(self, selector_hash: str) -> list[dict[str, Any]]:
        db = self._db()
        try:
            rows = db.execute(
                "SELECT r.payload_json FROM replays r JOIN freezes f ON f.prediction_id=r.prediction_id "
                "WHERE f.selector_hash=? ORDER BY f.target_issue",
                (selector_hash,),
            ).fetchall()
            return [json.loads(r[0]) for r in rows]
        finally:
            db.close()

    def _existing_freeze(self, target_issue: str) -> dict[str, Any] | None:
        db = self._db()
        try:
            row = db.execute("SELECT payload_json FROM freezes WHERE target_issue=?", (target_issue,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def _existing_gate(self, target_issue: str) -> dict[str, Any] | None:
        db = self._db()
        try:
            row = db.execute("SELECT payload_json FROM final_gate_decisions WHERE target_issue=?", (target_issue,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def _save_context(self, context_hash: str, payload: dict[str, Any]) -> None:
        db = self._db()
        try:
            db.execute(
                "INSERT OR IGNORE INTO canonical_contexts(context_hash,created_at,payload_json) VALUES(?,?,?)",
                (context_hash, utc_now(), _json_dumps(payload)),
            )
            db.commit()
        finally:
            db.close()

    def _save_freeze(self, prediction_dict: dict[str, Any], canonical_hash: str) -> None:
        db = self._db()
        try:
            db.execute(
                "INSERT INTO freezes(prediction_id,target_issue,created_at,canonical_hash,model_hash,selector_hash,freeze_hash,payload_json) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    prediction_dict["prediction_id"], prediction_dict["target_issue"], prediction_dict["created_at"],
                    canonical_hash, prediction_dict["model_hash"], prediction_dict["selector_hash"],
                    prediction_dict["freeze_hash"], _json_dumps(prediction_dict),
                ),
            )
            db.commit()
        finally:
            db.close()

    def _save_final_gate(self, gate: dict[str, Any]) -> None:
        db = self._db()
        try:
            db.execute(
                "INSERT INTO final_gate_decisions(gate_hash,target_issue,created_at,status,payload_json) VALUES(?,?,?,?,?)",
                (gate["gate_hash"], gate["target_issue"], gate["created_at"], gate["status"], _json_dumps(gate)),
            )
            db.commit()
        finally:
            db.close()

    def update(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        self.ensure_seed()
        # A provincial fallback is allowed to extend only an integrity-verified
        # local baseline.  Structurally valid but tampered history must not be
        # "washed clean" by matching only the recent provincial window.
        baseline_integrity = self._integrity_check()
        if not baseline_integrity.get("ok"):
            raise RuntimeError("local canonical baseline integrity FAIL; run 一键修复 before network update")
        if progress:
            progress("连接多官方源并构建 SSQ Canonical Dataset…")
        baseline_draws = self._load_draws()
        dataset, evidences = build_canonical(progress=progress, baseline_draws=baseline_draws)
        if getattr(dataset, "crosscheck_status", None) != "PASS":
            raise RuntimeError("official source crosscheck did not PASS")
        self.store.save_dataset(dataset, evidences)
        replay_result = self.replay_all(progress=progress)
        latest = dataset.draws[-1]
        receipts = [asdict(r) for r in dataset.receipts]
        payload = {
            "schema": "official-update-v8.3",
            "game": "SSQ",
            "latest": latest.to_dict(),
            "latest_issue": latest.issue,
            "latest_date": latest.draw_date,
            "draw_count": len(dataset.draws),
            "canonical_hash": dataset.canonical_hash,
            "crosscheck_count": dataset.crosscheck_count,
            "crosscheck_status": dataset.crosscheck_status,
            "verification": evidences.get("verification"),
            "source": "official-source-quorum",
            "baseline_integrity": baseline_integrity,
            "source_receipts": receipts,
            "replayed": replay_result.get("replayed", 0),
        }
        self._append_experiment("official_update", "PASS", dataset.canonical_hash, payload)
        return payload

    def latest_court(self) -> dict[str, Any] | None:
        db = self._db()
        try:
            row = db.execute(
                "SELECT payload_json FROM experiments WHERE kind='evidence_court' AND status='PASS' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def _court(self, draws, canonical_hash: str, progress=None) -> dict[str, Any]:
        identity = model_identity()
        cached = self.latest_court()
        if cached:
            unsigned = dict(cached)
            recorded_hash = unsigned.pop("court_hash", None)
            if (recorded_hash and recorded_hash == sha256_json(unsigned)
                and cached.get("canonical_hash") == canonical_hash
                and cached.get("model_hash") == identity["model_hash"]
                and cached.get("selector_hash") == identity["selector_hash"]
                and cached.get("software_verdict") == "PASS"
                and cached.get("final_validation", {}).get("status") == "PASS"):
                return cached
        prospective = self._prospective_replays(identity["selector_hash"])
        court = run_evidence_court(draws, prospective=prospective, progress=progress)
        court["canonical_hash"] = canonical_hash
        court.pop("court_hash", None)
        court["court_hash"] = sha256_json(court)
        self._append_experiment("evidence_court", "PASS" if court.get("software_verdict") == "PASS" else "FAIL", canonical_hash, court)
        return court

    @staticmethod
    def _release_gate(
        prediction_dict: dict[str, Any], trace: dict[str, Any], court: dict[str, Any],
        canonical_hash: str, source_verified: bool, integrity_ok: bool,
    ) -> dict[str, Any]:
        weights = dict(trace.get("production_weights", {}))
        edge = court.get("edge_state") == "EDGE_PROVEN"
        dan = court.get("dan_state") == "CERTIFIED_DAN"
        isolation_ok = (
            (edge and dan and weights.get("research_ensemble") == 1.0 and weights.get("uniform_baseline") == 0.0)
            or ((not edge or not dan) and weights.get("uniform_baseline") == 1.0 and weights.get("research_ensemble") == 0.0)
        )
        lineage = {
            "canonical_context": trace.get("canonical_hash") == canonical_hash,
            "single_formal_source": (
                prediction_dict.get("model_hash") == trace.get("model_hash")
                and prediction_dict.get("selector_hash") == trace.get("selector_hash")
                and prediction_dict.get("score_hash") == trace.get("score_hash")
                and trace.get("canonical_hash") == canonical_hash
            ),
            "source_freshness": bool(source_verified),
            "data_integrity": bool(integrity_ok),
            "evidence_court_execution": (
                court.get("software_verdict") == "PASS"
                and court.get("final_validation", {}).get("status") == "PASS"
            ),
            "evidence_state_consistency": (
                prediction_dict.get("edge_state") == court.get("edge_state")
                and prediction_dict.get("dan_state") == court.get("dan_state")
            ),
            "evidence_hash_binding": (
                bool(court.get("court_hash"))
                and trace.get("court_hash") == court.get("court_hash")
            ),
            "production_research_isolation": isolation_ok,
            "dan_gate": prediction_dict.get("dan_state") in ("NULL_DAN", "CERTIFIED_DAN"),
            "freeze_lineage": bool(prediction_dict.get("freeze_hash")),
        }
        hard_fail_count = sum(1 for ok in lineage.values() if not ok)
        status = "PASS" if hard_fail_count == 0 else "FAIL"
        gate = {
            "schema": "final-gate-v8",
            "created_at": utc_now(),
            "target_issue": prediction_dict.get("target_issue"),
            "status": status,
            "hard_fail_count": hard_fail_count,
            "checks": lineage,
            "rule": "PASS = (hard_fail_count == 0) AND (final_gate == PASS)",
        }
        gate["gate_hash"] = sha256_json(gate)
        return gate

    def predict(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        self.ensure_seed()
        update_result = None
        update_error = None
        try:
            update_result = self.update(progress=progress)
        except Exception as exc:
            update_error = f"{type(exc).__name__}: {exc}"
            if progress:
                progress("官方更新不可用；Fail-Closed：可计算研究结果，但禁止正式 Freeze/PASS")

        draws = self._load_draws()
        canonical_hash = self._canonical_hash()
        court = self._court(draws, canonical_hash, progress=progress)
        prediction, trace = make_prediction(draws, canonical_hash, evidence=court, formal=True)
        pred_dict = prediction.to_dict()

        # Exact target immutability check happens before any write.
        existing = self._existing_freeze(pred_dict["target_issue"])
        existing_gate = self._existing_gate(pred_dict["target_issue"])
        if existing is not None:
            return {
                "prediction": existing,
                "effect_trace": trace,
                "court": court,
                "final_gate": existing_gate or {
                    "status": "FAIL", "target_issue": pred_dict["target_issue"],
                    "hard_fail_count": 1, "checks": {"immutable_gate_record": False},
                    "rule": "existing immutable freeze without matching gate cannot be upgraded after the fact",
                },
                "auto_update": update_result,
                "auto_update_error": update_error,
                "immutable_freeze_preserved": True,
            }

        integrity = self._integrity_check()
        gate = self._release_gate(
            pred_dict, trace, court, canonical_hash,
            source_verified=update_result is not None,
            integrity_ok=bool(integrity.get("ok")),
        )
        context = {
            "schema": "canonical-context-v8",
            "target_issue": pred_dict["target_issue"],
            "canonical_hash": canonical_hash,
            "model_hash": pred_dict["model_hash"],
            "selector_hash": pred_dict["selector_hash"],
            "score_hash": pred_dict["score_hash"],
            "freeze_hash": pred_dict["freeze_hash"],
            "court_hash": court.get("court_hash"),
            "effect_trace_hash": trace.get("effect_trace_hash"),
        }
        context_hash = sha256_json(context)
        context["context_hash"] = context_hash
        self._save_context(context_hash, context)

        if gate["status"] == "PASS":
            self._save_freeze(pred_dict, canonical_hash)
            self._save_final_gate(gate)
            self._append_experiment("prediction_freeze", "PASS", canonical_hash, {
                "prediction_id": pred_dict["prediction_id"],
                "target_issue": pred_dict["target_issue"],
                "freeze_hash": pred_dict["freeze_hash"],
                "context_hash": context_hash,
                "gate_hash": gate["gate_hash"],
            })
        else:
            self._append_experiment("prediction_blocked", "FAIL", canonical_hash, {
                "target_issue": pred_dict["target_issue"],
                "gate": gate,
                "auto_update_error": update_error,
            })

        return {
            "prediction": pred_dict,
            "effect_trace": trace,
            "court": court,
            "final_gate": gate,
            "canonical_context_hash": context_hash,
            "auto_update": update_result,
            "auto_update_error": update_error,
            "immutable_freeze_preserved": False,
        }

    def _integrity_check(self) -> dict[str, Any]:
        try:
            payload = self._history_payload()
            draws = payload.get("draws", [])
            basic = payload.get("game") == "SSQ" and len(draws) > 0
            issue_ordered = all(str(draws[i]["issue"]) < str(draws[i + 1]["issue"]) for i in range(len(draws) - 1))
            date_ordered = all(str(draws[i]["draw_date"]) < str(draws[i + 1]["draw_date"]) for i in range(len(draws) - 1))
            ordered = issue_ordered and date_ordered
            rules = all(
                len(d.get("front", [])) == FRONT_PICK
                and len(set(d.get("front", []))) == FRONT_PICK
                and all(1 <= int(x) <= FRONT_MAX for x in d.get("front", []))
                and len(d.get("back", [])) == BACK_PICK
                and all(1 <= int(x) <= BACK_MAX for x in d.get("back", []))
                for d in draws
            )
            baseline = self.store.integrity_check()
            if not isinstance(baseline, dict):
                baseline_ok = False
            elif "ok" in baseline:
                baseline_ok = bool(baseline.get("ok"))
            else:
                baseline_ok = str(baseline.get("status", "")).upper() == "PASS"
            return {"ok": bool(basic and ordered and rules and baseline_ok), "baseline": baseline, "draw_count": len(draws)}
        except Exception as exc:
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    def _replay_payload(self, pred: dict[str, Any], actual) -> dict[str, Any]:
        fr_obj = pred.get("front_ranking", {})
        br_obj = pred.get("back_ranking", {})
        front_rank = list(fr_obj.get("numbers", [])) if isinstance(fr_obj, dict) else []
        back_rank = list(br_obj.get("numbers", [])) if isinstance(br_obj, dict) else []
        af = set(actual.front); ab = set(actual.back)
        front_hits = len(set(front_rank[:FRONT_PICK]) & af)
        back_hits = len(set(back_rank[:BACK_PICK]) & ab)
        return {
            "schema": "replay-v8",
            "prediction_id": pred.get("prediction_id"),
            "actual_issue": actual.issue,
            "actual_front": list(actual.front),
            "actual_back": list(actual.back),
            "front_hits": front_hits,
            "back_hits": back_hits,
            "winner_rank_front": {str(n): (front_rank.index(n) + 1 if n in front_rank else None) for n in actual.front},
            "winner_rank_back": {str(n): (back_rank.index(n) + 1 if n in back_rank else None) for n in actual.back},
            "research_dan_front_hits": len(set(pred.get("research_dan_front", [])) & af),
            "research_dan_back_hits": len(set(pred.get("research_dan_back", [])) & ab),
            "selector_hash": pred.get("selector_hash"),
            "immutable_freeze_hash": pred.get("freeze_hash"),
            "ranking_lineage_complete": all(pred.get(k) for k in ("model_hash", "selector_hash", "score_hash", "freeze_hash")),
        }

    def replay_all(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        draws = self._load_draws()
        draw_map = {d.issue: d for d in draws}
        db = self._db()
        try:
            rows = db.execute("SELECT prediction_id,target_issue,payload_json FROM freezes ORDER BY target_issue").fetchall()
            replayed = 0
            postmortems = 0
            for row in rows:
                pid, issue, payload_json = row[0], row[1], row[2]
                if issue not in draw_map:
                    continue
                exists = db.execute("SELECT 1 FROM replays WHERE prediction_id=?", (pid,)).fetchone()
                if exists:
                    continue
                pred = json.loads(payload_json)
                actual = draw_map[issue]
                replay = self._replay_payload(pred, actual)
                db.execute(
                    "INSERT INTO replays(prediction_id,replayed_at,actual_issue,payload_json) VALUES(?,?,?,?)",
                    (pid, utc_now(), issue, _json_dumps(replay)),
                )
                post = {
                    "schema": "post-draw-audit-v8",
                    "prediction_id": pid,
                    "actual_issue": issue,
                    "replay": replay,
                    "missed_winner_audit": {
                        "red_missed": sorted(set(actual.front) - set((pred.get("front_ranking") or {}).get("numbers", [])[:FRONT_PICK])),
                        "blue_missed": sorted(set(actual.back) - set((pred.get("back_ranking") or {}).get("numbers", [])[:BACK_PICK])),
                    },
                    "five_why": [
                        "Was the canonical dataset current before freeze?",
                        "Were all features recomputed from past-only data?",
                        "Did any model dominate through duplicate information?",
                        "Did score changes survive strict OOS rather than only in-sample replay?",
                        "Did immutable Freeze/context hashes prevent post-draw contamination?",
                    ],
                    "reverse_validation": ["remove", "shuffle", "random_replace", "reverse_time"],
                    "improvement_candidate": "Challenger only; no production weight change without full revalidation",
                    "production_weight_change": 0,
                }
                db.execute(
                    "INSERT OR IGNORE INTO postmortems(prediction_id,created_at,payload_json) VALUES(?,?,?)",
                    (pid, utc_now(), _json_dumps(post)),
                )
                replayed += 1; postmortems += 1
            db.commit()
            return {"replayed": replayed, "postmortems": postmortems}
        finally:
            db.close()

    def audit(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Advanced analysis is intentionally non-freezing.

        It may refresh canonical data, run heavy falsification and generate a
        research preview, but it never writes a formal prediction/freeze/gate.
        """
        self.ensure_seed()
        update_result = None
        update_error = None
        try:
            update_result = self.update(progress=progress)
        except Exception as exc:
            update_error = f"{type(exc).__name__}: {exc}"
        draws = self._load_draws()
        canonical_hash = self._canonical_hash()
        before = self._freeze_count()
        court = self._court(draws, canonical_hash, progress=progress)
        preview, trace = make_prediction(draws, canonical_hash, evidence=court, formal=False)
        ors = build_ors_record(court, trace)
        after = self._freeze_count()
        isolation_ok = before == after
        self_test = self.self_test(fast=True)
        gates = list(court.get("gates", []))
        gates.append({
            "name": "Audit/Freeze Isolation",
            "status": "PASS" if isolation_ok else "FAIL",
            "decision": "ACCEPT" if isolation_ok else "REJECT",
            "outcome": f"freeze_count {before} -> {after}",
        })
        software_verdict = "PASS" if court.get("software_verdict") == "PASS" and isolation_ok and self_test["status"] == "PASS" else "FAIL"
        result = {
            "schema": "advanced-audit-v8",
            "court": court,
            "ors": ors,
            "gates": gates,
            "software_verdict": software_verdict,
            "research_preview": preview.to_dict(),
            "formal_freeze_written": False,
            "auto_update": update_result,
            "auto_update_error": update_error,
            "self_test": self_test,
            "release_contract": self.release_contract(),
        }
        self._append_experiment("audit", software_verdict, canonical_hash, result)
        return result

    def _freeze_count(self) -> int:
        db = self._db()
        try:
            return int(db.execute("SELECT COUNT(*) FROM freezes").fetchone()[0])
        finally:
            db.close()

    def repair(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        # Repair must remain usable when the local dataset itself is corrupt.
        # Therefore it only materializes missing files first; it does NOT call
        # ensure_seed(), which intentionally rejects corrupted/wrong-game data.
        self._ensure_seed_files()
        before = self._integrity_check()
        if before.get("ok"):
            payload = {"status": "PASS", "repaired": False, "detail": "integrity OK; no repair required", "integrity": before}
            self._append_experiment("repair", "PASS", self._canonical_hash(), payload)
            return payload
        if progress:
            progress("Integrity FAIL：从多官方源重建 Canonical Dataset…")
        try:
            seed_payload = json.loads(resource_path("official_seed.json").read_text(encoding="utf-8"))
            trusted_seed = [Draw.from_dict(x) for x in seed_payload.get("draws", [])]
            dataset, evidences = build_canonical(progress=progress, baseline_draws=trusted_seed)
            if getattr(dataset, "crosscheck_status", None) != "PASS":
                raise RuntimeError("official source crosscheck did not PASS")
            self.store.save_dataset(dataset, evidences)
            replay_result = self.replay_all(progress=progress)
            after = self._integrity_check()
            status = "PASS" if after.get("ok") else "FAIL"
            payload = {
                "status": status, "repaired": bool(after.get("ok")),
                "before": before, "after": after,
                "canonical_hash": getattr(dataset, "canonical_hash", None),
                "crosscheck_status": getattr(dataset, "crosscheck_status", None),
                "replayed": replay_result.get("replayed", 0),
            }
            self._append_experiment("repair", status, self._canonical_hash(), payload)
            return payload
        except Exception as exc:
            payload = {"status": "FAIL", "repaired": False, "before": before, "detail": f"{type(exc).__name__}: {exc}"}
            # A corrupt history may not have a usable canonical hash; keep the
            # failure auditable without pretending the data itself validated.
            try:
                input_hash = self._canonical_hash()
            except Exception:
                input_hash = sha256_json({"repair_failure": payload["detail"]})
            self._append_experiment("repair", "FAIL", input_hash, payload)
            return payload

    def release_contract(self) -> dict[str, Any]:
        return {
            "schema": "three-layer-acceptance-v1",
            "order": ["CODE_COMPLETENESS", "SCIENTIFIC_VALIDATION", "EXACT_EXE_ACCEPTANCE"],
            "release_rule": "no hard FAIL AND final_gate == PASS",
            "non_pass_states": ["FAIL", "UNAVAILABLE", "SKIPPED", "WARNING", "PENDING", "UNKNOWN"],
            "app_version": APP_VERSION,
            "game": GAME,
        }

    def self_test(self, fast: bool = False) -> dict[str, Any]:
        checks: dict[str, bool] = {}
        detail: dict[str, Any] = {}
        try:
            self.ensure_seed()
            checks["ssq_identity"] = GAME == "SSQ" and FRONT_MAX == 33 and FRONT_PICK == 6 and BACK_MAX == 16 and BACK_PICK == 1
            integrity = self._integrity_check()
            checks["seed_integrity"] = bool(integrity.get("ok"))
            draws = self._load_draws()
            canonical_hash = self._canonical_hash()
            fake_court = {
                "edge_state": "NO_EDGE", "dan_state": "NULL_DAN",
                "software_verdict": "PASS", "final_validation": {"status": "PASS"},
            }
            p1, t1 = make_prediction(draws, canonical_hash, fake_court, formal=False)
            p2, t2 = make_prediction(draws, canonical_hash, fake_court, formal=False)
            checks["deterministic_prediction"] = p1.score_hash == p2.score_hash and p1.freeze_hash == p2.freeze_hash
            checks["honest_no_edge"] = t1["production_weights"] == {"uniform_baseline": 1.0, "research_ensemble": 0.0}
            bad_gate = self._release_gate(p1.to_dict(), t1, fake_court, canonical_hash, source_verified=False, integrity_ok=True)
            checks["false_pass_blocked"] = bad_gate["status"] == "FAIL" and bad_gate["hard_fail_count"] >= 1
            checks["immutable_schema"] = self._freeze_triggers_present()
            checks["four_entry_backend"] = all(hasattr(self, n) for n in ("predict", "update", "repair", "audit"))
            detail["integrity"] = integrity
        except Exception as exc:
            checks["self_test_completed"] = False
            detail["exception"] = f"{type(exc).__name__}: {exc}"
        required = {"ssq_identity", "seed_integrity", "deterministic_prediction", "honest_no_edge", "false_pass_blocked", "immutable_schema", "four_entry_backend"}
        status = "PASS" if required.issubset(checks) and all(checks.values()) else "FAIL"
        return {"status": status, "checks": checks, "detail": detail, "fast": bool(fast), "release_contract": self.release_contract()}

    def _freeze_triggers_present(self) -> bool:
        db = self._db()
        try:
            rows = db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
            names = {r[0] for r in rows}
            required = {"freezes_no_update", "freezes_no_delete", "replays_no_update", "contexts_no_update", "final_gate_no_update"}
            return required.issubset(names)
        finally:
            db.close()
