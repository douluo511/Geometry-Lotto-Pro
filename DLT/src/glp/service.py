from __future__ import annotations

import gc
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from .constants import APP_VERSION
from .domain import CanonicalDataset, Draw, Prediction
from .engine import make_prediction, model_identity, replay_prediction
from .evidence import run_evidence_court, strict_gate_verdict, leakage_guard
from .ors import build_ors_record
from .sources import build_canonical
from .storage import Store
from .util import sha256_bytes, sha256_json, utc_now


def resource_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "resources" / name
    return Path(__file__).resolve().parent.parent / "resources" / name


class LottoService:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def ensure_seed(self) -> None:
        """Install or safely advance the embedded verified seed.

        Upgrading the EXE must not leave an older local canonical dataset silently
        active.  If the embedded seed is newer and all overlapping draws match,
        advance atomically to the embedded seed; never overwrite a newer local
        dataset and never hide a conflict.
        """
        seed_path = resource_path("official_seed.json")
        evidence_path = resource_path("official_seed_evidence.json")
        if not seed_path.exists() or not evidence_path.exists():
            raise FileNotFoundError("安装包缺少官方数据快照/证据，请运行一键修复")

        seed_obj = json.loads(seed_path.read_text(encoding="utf-8"))
        seed_draws = [Draw.from_dict(x) for x in seed_obj.get("draws", [])]
        if not seed_draws:
            raise ValueError("安装包内置 seed 为空")
        seed_payload = [d.to_dict() for d in seed_draws]
        seed_hash = sha256_json(seed_payload)
        if seed_hash != str(seed_obj.get("canonical_hash", "")):
            raise ValueError("安装包内置 seed canonical_hash 不匹配")
        seed_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if str(seed_evidence.get("canonical_hash")) != seed_hash:
            raise ValueError("安装包内置 seed evidence hash 不匹配")
        if str((seed_evidence.get("latest") or {}).get("issue")) != seed_draws[-1].issue:
            raise ValueError("安装包内置 seed evidence 最新期不匹配")

        if not self.store.history_path.exists():
            shutil.copyfile(seed_path, self.store.history_path)
            shutil.copyfile(evidence_path, self.store.evidence_path)
            self._import_legacy_freezes()
            self.replay_all()
            return

        # Existing data must itself be valid before any automatic upgrade.
        local_draws, _ = self.store.load_draws()
        local_by_issue = {d.issue: d.to_dict() for d in local_draws}
        for d in seed_draws:
            if d.issue in local_by_issue and local_by_issue[d.issue] != d.to_dict():
                raise ValueError(f"本地历史与内置官方 seed 冲突: {d.issue}，请运行一键修复")

        if seed_draws[-1].issue > local_draws[-1].issue:
            # Safe monotonic seed upgrade; evidence travels with the exact payload.
            shutil.copyfile(seed_path, self.store.history_path)
            shutil.copyfile(evidence_path, self.store.evidence_path)
            self.store.append_experiment(
                "embedded_seed_upgrade", "PASS", seed_hash, APP_VERSION,
                {"from_issue": local_draws[-1].issue, "to_issue": seed_draws[-1].issue,
                 "draw_count": len(seed_draws), "evidence": seed_evidence.get("seed_patch_evidence", {})},
            )
            self.replay_all()
        self._import_legacy_freezes()

    def _import_legacy_freezes(self) -> None:
        path = resource_path("legacy_freezes.json")
        if not path.exists():
            return
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(values, list):
            return
        imported = 0
        for value in values:
            try:
                pred = Prediction(**value)
                self.store.freeze(pred)
                imported += 1
            except Exception:
                continue
        if imported:
            self.store.append_experiment(
                "legacy_freeze_migration", "PASS", sha256_bytes(path.read_bytes()), "migration-v2",
                {"count": imported, "note": "published combination only; excluded from full-ranking evidence"},
            )

    def update(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        attempt_id = sha256_json({"kind": "official_update", "at": utc_now(), "version": APP_VERSION})
        try:
            dataset, evidence = build_canonical(progress)
            self.store.save_dataset(dataset, evidence)
            integrity = self.store.integrity_check()
            if integrity["status"] != "PASS":
                raise ValueError("官方更新后的本地证据链完整性校验失败")
            replayed = self.replay_all()
            payload = dict(evidence)
            payload["network_gate"] = "PASS"
            payload["replayed"] = replayed
            payload["latest"] = dataset.draws[-1].to_dict()
            payload["source_receipts"] = evidence.get("source_receipts", [])
            self.store.append_experiment("official_update", "PASS", dataset.canonical_hash, APP_VERSION, payload)
            return payload
        except Exception as exc:
            # A failed network/parse/crosscheck attempt is evidence too. Never let a
            # cached dataset make a failed update look successful.
            failure = {
                "network_gate": "FAIL", "attempt_id": attempt_id, "failed_at": utc_now(),
                "error_type": type(exc).__name__, "error": str(exc),
            }
            try:
                self.store.append_experiment("official_update", "FAIL", attempt_id, APP_VERSION, failure)
            except Exception:
                pass
            raise

    def predict(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        self.ensure_seed()
        integrity = self.store.integrity_check()
        if integrity["status"] != "PASS":
            raise ValueError("本地数据/证据链不完整，请先运行“一键修复”")
        draws, canonical_hash = self.store.load_draws()
        if progress:
            progress("完整组合空间评分中：前区 324,632 / 后区 66")
        court = self.latest_court(canonical_hash)
        prediction, trace = make_prediction(draws, canonical_hash, court)
        frozen = self.store.freeze(prediction)
        if frozen.prediction_id != prediction.prediction_id:
            trace = {
                "freeze_hash": frozen.freeze_hash,
                "legacy_freeze_preserved": True,
                "current_score_not_used": True,
                "complete_space": trace.get("complete_space"),
                "production_weights": trace.get("production_weights"),
                "note": "该期已有事前 Freeze；本次重算结果被不可覆盖规则拒绝。",
            }
        payload = {"prediction": frozen.to_dict(), "effect_trace": trace}
        self.store.append_experiment("prediction_freeze", "PASS", canonical_hash, frozen.model_hash, payload)
        return payload

    def replay_all(self) -> int:
        try:
            draws, _ = self.store.load_draws()
        except Exception:
            return 0
        actual_by_issue = {d.issue: d for d in draws}
        count = 0
        for pred in self.store.freezes():
            actual = actual_by_issue.get(pred.target_issue)
            if not actual:
                continue
            self.store.save_replay(pred.prediction_id, actual.issue, replay_prediction(pred, actual))
            count += 1
        return count

    def audit(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        self.ensure_seed()
        integrity = self.store.integrity_check()
        if integrity["status"] != "PASS":
            raise ValueError("Evidence Court 拒绝运行：本地数据/证据链不完整")
        draws, canonical_hash = self.store.load_draws()
        selector_hash = model_identity()["selector_hash"]
        prospective = self.store.prospective_replays(selector_hash)
        court = run_evidence_court(draws, prospective, progress)
        prediction = self.predict(progress)
        trace = prediction.get("effect_trace", {})
        ors = build_ors_record(court, trace)
        payload = {"court": court, "ors": ors}
        self.store.append_experiment("evidence_court", court["software_verdict"], canonical_hash, court["model_hash"], payload)
        return payload

    def latest_court(self, canonical_hash: str | None = None) -> dict[str, Any] | None:
        # Never reuse a PASS from another dataset or model revision. A data update
        # invalidates predictive-edge evidence until Evidence Court is rerun.
        canonical_hash = canonical_hash or self.store.load_draws()[1]
        current_model_hash = model_identity()["model_hash"]
        with self.store._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM experiments "
                "WHERE kind='evidence_court' AND status='PASS' AND input_hash=? AND code_hash=? "
                "ORDER BY id DESC LIMIT 1",
                (canonical_hash, current_model_hash),
            ).fetchone()
        if not row:
            return None
        value = json.loads(row["payload_json"])
        court = value.get("court")
        if not isinstance(court, dict):
            return None
        if court.get("model_hash") != current_model_hash:
            return None
        if court.get("scientific_gate") != "PASS" or court.get("software_verdict") != "PASS":
            return None
        return court

    def repair(self, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        before = self.store.integrity_check()
        actions: list[str] = []
        by_name = {c.get("name"): c.get("status") for c in before.get("checks", [])}

        if by_name.get("SQLite integrity") != "PASS" or by_name.get("Freeze archive") != "PASS":
            if progress:
                progress("实验账本损坏，正在备份并重建 ledger")
            rebuilt = self.store.rebuild_ledger()
            actions.append(f"ledger rebuilt; restored_freezes={rebuilt.get('restored_freezes', 0)}")

        # Recheck local canonical history after ledger recovery. Network is required only
        # when the canonical dataset itself is invalid/missing.
        mid = self.store.integrity_check()
        mid_by_name = {c.get("name"): c.get("status") for c in mid.get("checks", [])}
        if mid_by_name.get("Canonical hash") != "PASS" or mid_by_name.get("Source evidence") != "PASS":
            if progress:
                progress("Canonical/来源证据损坏，正在从双官方源重建")
            self.update(progress)
            actions.append("canonical history/source evidence rebuilt from dual official sources")

        replayed = self.replay_all()
        after = self.store.integrity_check()
        status = "PASS" if after["status"] == "PASS" else "FAIL"
        payload = {"before": before, "action": actions or ["无需修复"], "replayed": replayed, "after": after}
        self.store.append_experiment("repair", status, sha256_json(before), APP_VERSION, payload)
        return payload


def self_test(root: Path | None = None) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    def check(name: str, fn):
        try:
            fn()
            checks.append({"name": name, "status": "PASS"})
        except Exception as exc:
            checks.append({"name": name, "status": "FAIL", "detail": str(exc)})

    d = Draw("26001", "2026-01-03", (1, 7, 13, 25, 35), (3, 12))
    check("DLT rule validation", d.validate)
    check("Model identity", lambda: (_ for _ in ()).throw(AssertionError("bad model hash")) if len(model_identity()["model_hash"]) != 64 else None)
    store = Store(root)
    check("SQLite integrity", lambda: (_ for _ in ()).throw(AssertionError("sqlite")) if store.integrity_check()["checks"][0]["status"] != "PASS" else None)
    # Immutable freeze test without requiring network/data.
    p = Prediction("selftest", "26999", "2026-12-31", utc_now(), [1,2,3,4,5], [1,2], list(range(1,36)), list(range(1,13)), "NULL_DAN", "NO_EDGE", [1,2], [1], "c"*64, "m"*64, "s"*64, "x"*64)
    first = store.freeze(p)
    changed = Prediction(**{**p.to_dict(), "front": [6,7,8,9,10]})
    second = store.freeze(changed)
    check("Immutable Freeze", lambda: (_ for _ in ()).throw(AssertionError("freeze overwritten")) if first.front != second.front else None)

    def freeze_tamper_detection():
        with store._connect() as db:
            row = db.execute("SELECT payload_json FROM freezes WHERE target_issue=?", ("26999",)).fetchone()
            value = json.loads(row["payload_json"])
            value["front"] = [6, 7, 8, 9, 10]
            db.execute("UPDATE freezes SET payload_json=? WHERE target_issue=?", (json.dumps(value, ensure_ascii=False, sort_keys=True), "26999"))
        if store.integrity_check()["status"] != "FAIL":
            raise AssertionError("tampered freeze payload was not detected")
        # Restore the original immutable payload so later self-tests operate on a valid ledger.
        with store._connect() as db:
            db.execute("UPDATE freezes SET payload_json=? WHERE target_issue=?", (json.dumps(first.to_dict(), ensure_ascii=False, sort_keys=True), "26999"))
    check("Freeze tamper detection", freeze_tamper_detection)

    def stale_court_rejection():
        current = model_identity()["model_hash"]
        fake = {"court": {"model_hash": current, "scientific_gate": "PASS", "software_verdict": "PASS", "edge_state": "EDGE_PROVEN"}}
        store.append_experiment("evidence_court", "PASS", "old-canonical", current, fake)
        svc = LottoService(store)
        if svc.latest_court("new-canonical") is not None:
            raise AssertionError("stale Evidence Court was reused across canonical hashes")
    check("Stale court rejection", stale_court_rejection)

    def ledger_rebuild_recovery():
        test_root = store.root / "_ledger_rebuild_selftest"
        if test_root.exists():
            shutil.rmtree(test_root, ignore_errors=True)
        try:
            s2 = Store(test_root)
            pred = Prediction("recovery", "26998", "2026-12-30", utc_now(), [1, 2, 3, 4, 5], [1, 2])
            s2.freeze(pred)

            # Close/checkpoint WAL state before deliberately corrupting the ledger.
            with s2._connect() as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            del s2
            gc.collect()

            (test_root / "ledger.sqlite3").write_bytes(b"not-a-sqlite-database")
            broken = Store(test_root)
            if broken.integrity_check()["status"] != "FAIL":
                raise AssertionError("corrupt ledger not detected")

            recovered = broken.rebuild_ledger()
            if recovered.get("restored_freezes") != 1 or len(broken.freezes()) != 1:
                raise AssertionError("freeze archive recovery failed")
        finally:
            shutil.rmtree(test_root, ignore_errors=True)

    check("Corrupt ledger recovery", ledger_rebuild_recovery)

    def leakage_sentinel_rejection():
        if not leakage_guard(9, 10):
            raise AssertionError("valid chronology rejected")
        if leakage_guard(10, 10) or leakage_guard(11, 10):
            raise AssertionError("future/equality leakage accepted")
    check("Leakage sentinel rejection", leakage_sentinel_rejection)

    def ambiguous_gate_rejection():
        try:
            strict_gate_verdict([{"name": "x", "status": "WARNING"}])
        except ValueError:
            return
        raise AssertionError("ambiguous gate status was accepted")
    check("No ambiguous gate status", ambiguous_gate_rejection)
    status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    return {"status": status, "checks": checks}
