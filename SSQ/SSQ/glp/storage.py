from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .domain import CanonicalDataset, Draw
from .util import app_data_dir, atomic_write, sha256_json


class Store:
    def __init__(self, root: Path | None = None):
        self.root = (root or app_data_dir()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.history_path = self.root / "canonical_history.json"
        self.evidence_path = self.root / "source_evidence.json"
        self.db_path = self.root / "ledger.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init_db(self) -> None:
        # sqlite3.Connection's context manager commits/rolls back but does NOT
        # close the connection. Explicit close is mandatory for exact-EXE
        # acceptance on Windows, otherwise TemporaryDirectory cleanup can hit
        # WinError 32 on ledger.sqlite3 / WAL sidecars.
        db = self._connect()
        try:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS freezes(
                    prediction_id TEXT PRIMARY KEY,
                    target_issue TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    model_hash TEXT NOT NULL,
                    selector_hash TEXT NOT NULL,
                    freeze_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replays(
                    prediction_id TEXT PRIMARY KEY,
                    replayed_at TEXT NOT NULL,
                    actual_issue TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(prediction_id) REFERENCES freezes(prediction_id)
                );
                CREATE TABLE IF NOT EXISTS canonical_contexts(
                    context_hash TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS final_gate_decisions(
                    gate_hash TEXT PRIMARY KEY,
                    target_issue TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS postmortems(
                    prediction_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(prediction_id) REFERENCES freezes(prediction_id)
                );
                CREATE TRIGGER IF NOT EXISTS freezes_no_update
                    BEFORE UPDATE ON freezes BEGIN SELECT RAISE(ABORT,'immutable freezes'); END;
                CREATE TRIGGER IF NOT EXISTS freezes_no_delete
                    BEFORE DELETE ON freezes BEGIN SELECT RAISE(ABORT,'immutable freezes'); END;
                CREATE TRIGGER IF NOT EXISTS replays_no_update
                    BEFORE UPDATE ON replays BEGIN SELECT RAISE(ABORT,'immutable replays'); END;
                CREATE TRIGGER IF NOT EXISTS contexts_no_update
                    BEFORE UPDATE ON canonical_contexts BEGIN SELECT RAISE(ABORT,'immutable contexts'); END;
                CREATE TRIGGER IF NOT EXISTS final_gate_no_update
                    BEFORE UPDATE ON final_gate_decisions BEGIN SELECT RAISE(ABORT,'immutable final gate'); END;
                """
            )
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _json_bytes(value: Any) -> bytes:
        return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    @staticmethod
    def _stage_bytes(path: Path, data: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".stage", dir=path.parent)
        tmp_path = Path(tmp)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            return tmp_path
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            finally:
                raise

    @staticmethod
    def _commit_replace(staged: Path, target: Path) -> None:
        os.replace(staged, target)

    @staticmethod
    def _restore_bytes(path: Path, previous: bytes | None) -> None:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, previous)

    def save_dataset(self, dataset: CanonicalDataset, evidence: dict[str, Any]) -> None:
        # Stage both payloads before mutating either production file.  Evidence
        # is committed first and canonical history last; therefore an evidence
        # staging/write failure can never mutate canonical history.  If the
        # history commit fails, evidence is rolled back to the previous bytes.
        # Matching commit_id values make any crash-partial state fail closed.
        evidence_payload = dict(evidence)
        commit_id = sha256_json({
            "canonical_hash": dataset.canonical_hash,
            "evidence_hash": sha256_json(evidence_payload),
        })
        payload = {
            "schema": 4,
            "game": "SSQ",
            "canonical_hash": dataset.canonical_hash,
            "commit_id": commit_id,
            "draws": [d.to_dict() for d in dataset.draws],
        }
        evidence_payload["commit_id"] = commit_id

        history_bytes = self._json_bytes(payload)
        evidence_bytes = self._json_bytes(evidence_payload)
        old_history = self.history_path.read_bytes() if self.history_path.exists() else None
        old_evidence = self.evidence_path.read_bytes() if self.evidence_path.exists() else None

        staged_history: Path | None = None
        staged_evidence: Path | None = None
        evidence_committed = False
        try:
            staged_history = self._stage_bytes(self.history_path, history_bytes)
            staged_evidence = self._stage_bytes(self.evidence_path, evidence_bytes)
            self._commit_replace(staged_evidence, self.evidence_path)
            staged_evidence = None
            evidence_committed = True
            self._commit_replace(staged_history, self.history_path)
            staged_history = None
        except Exception:
            if evidence_committed:
                self._restore_bytes(self.evidence_path, old_evidence)
            # Canonical history is committed last, so unless its replace
            # succeeded there is nothing to roll back. If an exotic filesystem
            # raised after replacement, restore defensively when bytes differ.
            current_history = self.history_path.read_bytes() if self.history_path.exists() else None
            if current_history != old_history:
                self._restore_bytes(self.history_path, old_history)
            raise
        finally:
            if staged_history is not None:
                staged_history.unlink(missing_ok=True)
            if staged_evidence is not None:
                staged_evidence.unlink(missing_ok=True)

    def load_draws(self) -> tuple[list[Draw], str]:
        if not self.history_path.exists():
            raise FileNotFoundError("尚无已验证的官方历史数据")
        value = json.loads(self.history_path.read_text(encoding="utf-8"))
        if value.get("game") != "SSQ":
            raise ValueError("dataset game mismatch")
        draws = [Draw.from_dict(x) for x in value.get("draws", [])]
        if not draws:
            raise ValueError("empty canonical history")
        expected = str(value.get("canonical_hash") or "")
        actual = sha256_json([d.to_dict() for d in draws])
        if actual != expected:
            raise ValueError("本地历史数据哈希校验失败，请运行“一键修复”")
        if len({d.issue for d in draws}) != len(draws):
            raise ValueError("本地历史数据存在重复期号")
        if any(draws[i].draw_date >= draws[i + 1].draw_date for i in range(len(draws) - 1)):
            raise ValueError("本地历史开奖日期非严格递增")
        return draws, expected

    def integrity_check(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        draws: list[Draw] | None = None
        digest = ""

        db: sqlite3.Connection | None = None
        try:
            db = self._connect()
            row = db.execute("PRAGMA integrity_check").fetchone()
            ok = bool(row and str(row[0]).lower() == "ok")
            checks.append({
                "name": "SQLite integrity",
                "status": "PASS" if ok else "FAIL",
                "detail": str(row[0]) if row else "no result",
            })
        except Exception as exc:
            checks.append({"name": "SQLite integrity", "status": "FAIL", "detail": str(exc)})
        finally:
            if db is not None:
                db.close()

        try:
            draws, digest = self.load_draws()
            checks.append({"name": "Canonical hash", "status": "PASS", "detail": f"{len(draws)} 期 / {digest}"})
        except Exception as exc:
            checks.append({"name": "Canonical hash", "status": "FAIL", "detail": str(exc)})

        try:
            if draws is None:
                raise ValueError("canonical history unavailable")
            if not self.evidence_path.exists():
                raise FileNotFoundError("source_evidence.json missing")
            evidence = json.loads(self.evidence_path.read_text(encoding="utf-8"))
            history_payload = json.loads(self.history_path.read_text(encoding="utf-8"))
            history_commit = history_payload.get("commit_id")
            evidence_commit = evidence.get("commit_id")
            if bool(history_commit) != bool(evidence_commit):
                raise ValueError("dataset/evidence commit_id presence mismatch")
            if history_commit and str(history_commit) != str(evidence_commit):
                raise ValueError("dataset/evidence commit_id mismatch")
            if str(evidence.get("canonical_hash")) != digest:
                raise ValueError("source evidence canonical_hash mismatch")
            if str(evidence.get("crosscheck_status")) != "PASS":
                raise ValueError("source crosscheck is not PASS")
            if int(evidence.get("draw_count", -1)) != len(draws):
                raise ValueError("source evidence draw_count mismatch")
            latest = evidence.get("latest") or {}
            if str(latest.get("issue")) != draws[-1].issue:
                raise ValueError("source evidence latest issue mismatch")
            checks.append({
                "name": "Source evidence",
                "status": "PASS",
                "detail": f"crosscheck={evidence.get('crosscheck_count', 0)} / latest={draws[-1].issue}",
            })
        except Exception as exc:
            checks.append({"name": "Source evidence", "status": "FAIL", "detail": str(exc)})

        return {
            "status": "FAIL" if any(c["status"] == "FAIL" for c in checks) else "PASS",
            "checks": checks,
        }
