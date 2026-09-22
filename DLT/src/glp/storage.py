from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .domain import CanonicalDataset, Draw, Prediction
from .util import app_data_dir, atomic_json, sha256_json, utc_now


class Store:
    def __init__(self, root: Path | None = None):
        self.root = (root or app_data_dir()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.history_path = self.root / "canonical_history.json"
        self.evidence_path = self.root / "source_evidence.json"
        self.db_path = self.root / "ledger.sqlite3"
        self.freeze_archive_path = self.root / "freeze_archive.json"
        self._db_init_error = ""
        self._archive_init_error = ""
        try:
            self._init_db()
        except sqlite3.DatabaseError as exc:
            # Keep the service constructible so the Repair entry can rebuild a corrupt ledger.
            self._db_init_error = str(exc)
        if not self._db_init_error and not self.freeze_archive_path.exists():
            try:
                self._archive_freezes()
            except Exception as exc:
                self._archive_init_error = str(exc)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS freezes (
                    prediction_id TEXT PRIMARY KEY,
                    target_issue TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    model_hash TEXT NOT NULL,
                    selector_hash TEXT NOT NULL,
                    freeze_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replays (
                    prediction_id TEXT PRIMARY KEY,
                    replayed_at TEXT NOT NULL,
                    actual_issue TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(prediction_id) REFERENCES freezes(prediction_id)
                );
                """
            )

    def _archive_freezes(self) -> None:
        with self._connect() as db:
            rows = db.execute("SELECT payload_json FROM freezes ORDER BY target_issue").fetchall()
        values = [json.loads(r["payload_json"]) for r in rows]
        atomic_json(self.freeze_archive_path, {"schema": 1, "freezes": values})

    def rebuild_ledger(self) -> dict[str, Any]:
        # Recover a corrupt ledger without requiring Windows to rename
        # SQLite WAL/SHM files while they may still be transiently locked.
        stamp = utc_now().replace(":", "").replace("-", "")
        backups: list[str] = []

        # Best-effort checkpoint. A corrupt DB may reject this.
        try:
            db = self._connect()
            try:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

        # Back up the main database first. This is the forensic evidence
        # required for recovery. WAL/SHM are best-effort on Windows.
        if self.db_path.exists():
            dst = self.root / f"{self.db_path.name}.corrupt.{stamp}.bak"
            shutil.copy2(self.db_path, dst)
            backups.append(str(dst))

        # Remove the main corrupt database. A new database will be created.
        if self.db_path.exists():
            os.remove(self.db_path)

        # WAL/SHM cleanup is best-effort because Windows can temporarily
        # retain handles even after the SQLite connection is closed.
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.db_path) + suffix)
            if sidecar.exists():
                try:
                    sidecar.unlink()
                except PermissionError:
                    pass
                except OSError:
                    pass

        self._db_init_error = ""
        self._archive_init_error = ""
        self._init_db()

        restored = 0
        if self.freeze_archive_path.exists():
            value = json.loads(
                self.freeze_archive_path.read_text(encoding="utf-8")
            )
            for item in value.get("freezes", []):
                pred = Prediction(**item)
                self.freeze(pred)
                restored += 1

        return {
            "backups": backups,
            "restored_freezes": restored,
        }

    def save_dataset(self, dataset: CanonicalDataset, evidence: dict[str, Any]) -> None:
        payload = {
            "schema": 2,
            "game": "DLT",
            "canonical_hash": dataset.canonical_hash,
            "draws": [d.to_dict() for d in dataset.draws],
        }
        atomic_json(self.history_path, payload)
        atomic_json(self.evidence_path, evidence)

    def load_draws(self) -> tuple[list[Draw], str]:
        if not self.history_path.exists():
            raise FileNotFoundError("尚无已验证的官方历史数据，请先运行“一键更新”")
        value = json.loads(self.history_path.read_text(encoding="utf-8"))
        draws = [Draw.from_dict(x) for x in value["draws"]]
        expected = str(value["canonical_hash"])
        actual = sha256_json([d.to_dict() for d in draws])
        if actual != expected:
            raise ValueError("本地历史数据哈希校验失败，请运行“一键修复”")
        if len({d.issue for d in draws}) != len(draws):
            raise ValueError("本地历史数据存在重复期号")
        return draws, expected

    def append_experiment(self, kind: str, status: str, input_hash: str, code_hash: str, payload: dict[str, Any]) -> int:
        if status not in {"PASS", "FAIL"}:
            raise ValueError(f"实验状态必须明确为 PASS/FAIL，收到: {status}")
        with self._connect() as db:
            cur = db.execute(
                "INSERT INTO experiments(created_at,kind,status,input_hash,code_hash,payload_json) VALUES(?,?,?,?,?,?)",
                (utc_now(), kind, status, input_hash, code_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
            return int(cur.lastrowid)

    @staticmethod
    def _verify_freeze(prediction: Prediction) -> None:
        core = prediction.to_dict()
        supplied = str(core.get("freeze_hash") or "")
        core["freeze_hash"] = ""
        expected = sha256_json(core)
        if not supplied or supplied != expected:
            raise ValueError(f"Freeze hash mismatch for issue {prediction.target_issue}")

    def freeze(self, prediction: Prediction) -> Prediction:
        with self._connect() as db:
            row = db.execute("SELECT payload_json FROM freezes WHERE target_issue=?", (prediction.target_issue,)).fetchone()
            if row:
                existing = Prediction(**json.loads(row["payload_json"]))
                self._verify_freeze(existing)
                return existing
            core = prediction.to_dict()
            core["freeze_hash"] = ""
            freeze_hash = sha256_json(core)
            payload = prediction.to_dict()
            payload["freeze_hash"] = freeze_hash
            frozen = Prediction(**payload)
            db.execute(
                "INSERT INTO freezes(prediction_id,target_issue,created_at,canonical_hash,model_hash,selector_hash,freeze_hash,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                (
                    frozen.prediction_id,
                    frozen.target_issue,
                    frozen.created_at,
                    frozen.canonical_hash,
                    frozen.model_hash,
                    frozen.selector_hash,
                    frozen.freeze_hash,
                    json.dumps(frozen.to_dict(), ensure_ascii=False, sort_keys=True),
                ),
            )
        self._archive_freezes()
        return frozen

    def freezes(self) -> list[Prediction]:
        with self._connect() as db:
            rows = db.execute("SELECT payload_json FROM freezes ORDER BY target_issue").fetchall()
        values = [Prediction(**json.loads(r["payload_json"])) for r in rows]
        for pred in values:
            self._verify_freeze(pred)
        return values

    def save_replay(self, prediction_id: str, issue: str, payload: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO replays(prediction_id,replayed_at,actual_issue,payload_json) VALUES(?,?,?,?)",
                (prediction_id, utc_now(), issue, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )

    def prospective_replays(self, selector_hash: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT r.payload_json FROM replays r JOIN freezes f ON f.prediction_id=r.prediction_id "
        params: tuple[Any, ...] = ()
        if selector_hash:
            query += "WHERE f.selector_hash=? "
            params = (selector_hash,)
        query += "ORDER BY f.target_issue"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    def integrity_check(self) -> dict[str, Any]:
        checks: list[dict[str, str]] = []
        try:
            if self._db_init_error:
                raise sqlite3.DatabaseError(self._db_init_error)
            with self._connect() as db:
                row = db.execute("PRAGMA integrity_check").fetchone()
                ok = bool(row and str(row[0]).lower() == "ok")
                freeze_rows = db.execute("SELECT payload_json FROM freezes ORDER BY target_issue").fetchall()
                freeze_count = len(freeze_rows)
                for fr in freeze_rows:
                    self._verify_freeze(Prediction(**json.loads(fr["payload_json"])))
            checks.append({"name": "SQLite integrity", "status": "PASS" if ok else "FAIL", "detail": str(row[0]) if row else "no result"})
            try:
                if self._archive_init_error:
                    raise ValueError(self._archive_init_error)
                if not self.freeze_archive_path.exists():
                    raise FileNotFoundError("freeze archive missing")
                archive = json.loads(self.freeze_archive_path.read_text(encoding="utf-8"))
                archive_values = [Prediction(**item) for item in archive.get("freezes", [])]
                for pred in archive_values:
                    self._verify_freeze(pred)
                archive_count = len(archive_values)
                if archive_count != freeze_count:
                    raise ValueError(f"freeze archive count={archive_count}, sqlite count={freeze_count}")
                archive_hashes = {p.freeze_hash for p in archive_values}
                db_hashes = {Prediction(**json.loads(fr["payload_json"])).freeze_hash for fr in freeze_rows}
                if archive_hashes != db_hashes:
                    raise ValueError("freeze archive/hash set differs from sqlite")
                checks.append({"name": "Freeze archive", "status": "PASS", "detail": f"{freeze_count} verified freezes"})
            except Exception as exc:
                checks.append({"name": "Freeze archive", "status": "FAIL", "detail": str(exc)})
        except Exception as exc:
            checks.append({"name": "SQLite integrity", "status": "FAIL", "detail": str(exc)})
            checks.append({"name": "Freeze archive", "status": "FAIL", "detail": "ledger unavailable"})
        draws = None
        digest = ""
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
            if str(evidence.get("canonical_hash")) != digest:
                raise ValueError("source evidence canonical_hash mismatch")
            if str(evidence.get("crosscheck_status")) != "PASS":
                raise ValueError("source crosscheck is not PASS")
            if int(evidence.get("draw_count", -1)) != len(draws):
                raise ValueError("source evidence draw_count mismatch")
            latest = evidence.get("latest") or {}
            if str(latest.get("issue")) != draws[-1].issue:
                raise ValueError("source evidence latest issue mismatch")
            checks.append({"name": "Source evidence", "status": "PASS", "detail": f"crosscheck={evidence.get('crosscheck_count', 0)} / latest={draws[-1].issue}"})
        except Exception as exc:
            checks.append({"name": "Source evidence", "status": "FAIL", "detail": str(exc)})
        return {"status": "FAIL" if any(c["status"] == "FAIL" for c in checks) else "PASS", "checks": checks}
