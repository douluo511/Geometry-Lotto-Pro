from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .domain import CanonicalDataset, Draw
from .constants import HEBEI_ANNOUNCE_URL, HEBEI_URL, NATIONAL_URL, SHANGHAI_URL
from .util import app_data_dir, atomic_json, atomic_write, sha256_bytes, sha256_json, utc_now


class Store:
    def __init__(self, root: Path | None = None):
        self.root = (root or app_data_dir()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.history_path = self.root / "canonical_history.json"
        self.evidence_path = self.root / "source_evidence.json"
        self.raw_root = self.root / "raw_responses"
        # Keep this path short enough for Windows onefile acceptance temp roots.
        self.failure_root = self.root / "failed"
        self.update_marker = self.root / "dataset_update_in_progress.json"
        self.db_path = self.root / "ledger.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _check_raw_evidence(
        evidence: dict[str, Any], raw_root: Path, payloads: dict[str, bytes] | None = None,
    ) -> int:
        if evidence.get("schema") != "official-source-evidence-v8.5":
            raise ValueError("current-version raw response evidence is missing")
        if evidence.get("raw_response_status") != ("PENDING_PERSISTENCE" if payloads is not None else "PASS"):
            raise ValueError("raw response persistence has not passed")
        records = evidence.get("raw_responses")
        if not isinstance(records, list) or not records:
            raise ValueError("raw response manifest is empty")
        expected_urls = {
            "official_cwl_L0": {NATIONAL_URL},
            "official_shanghai_L1": {SHANGHAI_URL},
            "official_hebei_L2": {HEBEI_URL, HEBEI_ANNOUNCE_URL},
        }
        by_source: dict[str, list[dict]] = {source: [] for source in expected_urls}
        now = datetime.now(timezone.utc)
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("raw response record is not an object")
            source = record.get("source")
            requested_url = record.get("requested_url")
            if source not in expected_urls or requested_url not in expected_urls[source]:
                raise ValueError("raw response has unknown source provenance")
            actual_url = urlsplit(str(record.get("url", "")))
            expected_host = urlsplit(requested_url).hostname
            if actual_url.scheme.lower() != "https" or actual_url.hostname != expected_host or actual_url.username or actual_url.password:
                raise ValueError("raw response URL left its official HTTPS host")
            fetched_text = str(record.get("fetched_at", ""))
            if not fetched_text.endswith("Z"):
                raise ValueError("raw response timestamp is not UTC Z")
            try:
                fetched = datetime.fromisoformat(fetched_text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("raw response timestamp is invalid") from exc
            if not now - timedelta(hours=24) <= fetched <= now + timedelta(minutes=5):
                raise ValueError("raw response evidence is stale or future dated")
            digest = str(record.get("sha256", ""))
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("raw response SHA-256 is invalid")
            if record.get("artifact") != f"raw_responses/{digest}.bin":
                raise ValueError("raw response artifact path is not content-addressed")
            byte_count = record.get("bytes")
            if isinstance(byte_count, bool) or not isinstance(byte_count, int) or not 0 <= byte_count <= 10_000_000:
                raise ValueError("raw response byte length is invalid")
            status_code = record.get("http_status")
            if isinstance(status_code, bool) or not isinstance(status_code, int):
                raise ValueError("raw response HTTP status is not an integer")
            if not 100 <= status_code <= 599:
                raise ValueError("raw response HTTP status is invalid")
            raw = payloads.get(digest) if payloads is not None else (raw_root / f"{digest}.bin").read_bytes()
            if not isinstance(raw, bytes) or len(raw) != byte_count or sha256_bytes(raw) != digest:
                raise ValueError("raw response artifact is missing or hash-mismatched")
            by_source[source].append(record)

        receipts = evidence.get("source_receipts")
        if not isinstance(receipts, list) or len(receipts) != 3:
            raise ValueError("source receipt set is incomplete")
        receipt_by_source = {r.get("source"): r for r in receipts if isinstance(r, dict)}
        if set(receipt_by_source) != set(expected_urls):
            raise ValueError("source receipt identities are incomplete")
        if sum(receipt.get("status") == "PASS" for receipt in receipts) < 2:
            raise ValueError("official source quorum is not met")
        if any(receipt.get("status") not in {"PASS", "FAIL"} for receipt in receipts):
            raise ValueError("source receipt has an indeterminate status")
        crosschecks = evidence.get("crosscheck_count")
        if isinstance(crosschecks, bool) or not isinstance(crosschecks, int) or crosschecks < 1:
            raise ValueError("official source crosscheck count is invalid")
        latest_issue = str((evidence.get("latest") or {}).get("issue", ""))
        for receipt in receipts:
            if receipt.get("status") == "PASS":
                if (receipt.get("http_status") != 200 or receipt.get("latest_issue") != latest_issue
                        or isinstance(receipt.get("draw_count"), bool)
                        or not isinstance(receipt.get("draw_count"), int)
                        or receipt["draw_count"] <= 0):
                    raise ValueError("PASS receipt contradicts latest draw or HTTP response")

        national = receipt_by_source["official_cwl_L0"]
        if national.get("status") == "PASS":
            if any(record["http_status"] != 200 for record in by_source["official_cwl_L0"]):
                raise ValueError("national PASS receipt includes a failed HTTP response")
            pages = evidence.get("national_raw_manifest")
            if not isinstance(pages, list) or not pages or len(pages) != len(by_source["official_cwl_L0"]):
                raise ValueError("national raw page manifest is incomplete")
            ordered = sorted(pages, key=lambda entry: entry["page"])
            if [entry.get("page") for entry in ordered] != list(range(1, len(ordered) + 1)):
                raise ValueError("national raw page numbers have gaps or duplicates")
            if national.get("raw_sha256") != sha256_json(ordered):
                raise ValueError("national raw manifest does not match receipt")
            for page in ordered:
                matching = [record for record in by_source["official_cwl_L0"]
                            if record.get("request_params", {}).get("pageNo") == str(page["page"])]
                if len(matching) != 1 or matching[0]["sha256"] != page.get("sha256") or matching[0]["bytes"] != page.get("bytes"):
                    raise ValueError("national raw response does not match page manifest")
        shanghai = receipt_by_source["official_shanghai_L1"]
        if shanghai.get("status") == "PASS":
            records_for_source = by_source["official_shanghai_L1"]
            if (len(records_for_source) != 1 or records_for_source[0]["http_status"] != 200
                    or records_for_source[0]["sha256"] != shanghai.get("raw_sha256")):
                raise ValueError("Shanghai raw response does not match receipt")
        hebei = receipt_by_source["official_hebei_L2"]
        if hebei.get("status") == "PASS":
            records_for_source = by_source["official_hebei_L2"]
            digests = {record["requested_url"]: record["sha256"] for record in records_for_source}
            if (len(records_for_source) != 2 or any(record["http_status"] != 200 for record in records_for_source)
                    or set(digests) != {HEBEI_URL, HEBEI_ANNOUNCE_URL}
                    or hebei.get("raw_sha256") != sha256_json({"home": digests[HEBEI_URL], "announce": digests[HEBEI_ANNOUNCE_URL]})):
                raise ValueError("Hebei dual-page raw responses do not match receipt")
        verification = evidence.get("verification")
        if verification == "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS":
            if (national.get("status") != "FAIL" or shanghai.get("status") != "PASS"
                    or hebei.get("status") != "PASS"):
                raise ValueError("provincial fallback receipt statuses contradict its verification")
            baseline = evidence.get("baseline_lineage")
            if (not isinstance(baseline, dict)
                    or not str(baseline.get("verification", "")).startswith("CWL_L0_PLUS_")
                    or baseline.get("baseline_lineage") is not None
                    or baseline.get("canonical_hash") != evidence.get("baseline_canonical_hash")
                    or baseline.get("draw_count") != evidence.get("baseline_draw_count")
                    or not any(r.get("source") == "official_cwl_L0" and r.get("status") == "PASS"
                               for r in baseline.get("source_receipts", []) if isinstance(r, dict))):
                raise ValueError("provincial fallback has no raw-verified CWL baseline lineage")
            Store._check_raw_evidence(baseline, raw_root)
        else:
            validators = int(shanghai.get("status") == "PASS") + int(hebei.get("status") == "PASS")
            if (national.get("status") != "PASS" or validators < 1
                    or verification != f"CWL_L0_PLUS_{validators}_PROVINCIAL_VALIDATOR"):
                raise ValueError("primary-source verification does not match official receipt quorum")
            if evidence.get("baseline_lineage") is not None:
                raise ValueError("unexpected baseline lineage on primary-source update")
        return len(records)

    @staticmethod
    def validate_raw_evidence(evidence: dict[str, Any], artifact_root: Path) -> int:
        """Verify an exported evidence directory without opening the application DB."""
        return Store._check_raw_evidence(evidence, Path(artifact_root) / "raw_responses")

    def save_failure_evidence(self, failure: dict[str, Any]) -> Path:
        """Persist failed live attempts separately, never replacing accepted data."""
        if failure.get("status") != "FAIL" or failure.get("crosscheck_status") != "FAIL":
            raise ValueError("failure evidence cannot claim success")
        records = failure.get("raw_responses")
        payloads = failure.get("_raw_response_payloads")
        if not isinstance(records, list) or not isinstance(payloads, dict):
            raise ValueError("failed raw response capture is malformed")
        if set(payloads) != {record.get("sha256") for record in records if isinstance(record, dict)}:
            raise ValueError("failed response manifest and bytes disagree")
        for _ in range(5):
            attempt_root = self.failure_root / uuid4().hex[:24]
            try:
                attempt_root.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("could not allocate a unique failed-network evidence directory")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("failed response record is not an object")
            digest = str(record.get("sha256", ""))
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("failed response digest is invalid")
            if record.get("artifact") != f"raw_responses/{digest}.bin":
                raise ValueError("failed response artifact path is invalid")
            raw = payloads.get(digest)
            if (not isinstance(raw, bytes) or sha256_bytes(raw) != digest
                    or len(raw) != record.get("bytes")):
                raise ValueError("failed response bytes do not match manifest")
            artifact = attempt_root / "raw_responses" / f"{digest}.bin"
            if not artifact.exists():
                atomic_write(artifact, raw)
            if sha256_bytes(artifact.read_bytes()) != digest:
                raise ValueError("failed response artifact did not survive read-back")
        clean = {key: value for key, value in failure.items() if key != "_raw_response_payloads"}
        clean["status"] = "FAIL"
        clean["crosscheck_status"] = "FAIL"
        clean["raw_response_status"] = "FAIL" if records else "UNAVAILABLE"
        clean["raw_artifacts_verified"] = bool(records)
        clean["recorded_at"] = utc_now()
        manifest = attempt_root / "failure_evidence.json"
        atomic_json(manifest, clean)
        if json.loads(manifest.read_text(encoding="utf-8")) != clean:
            raise ValueError("failed network evidence did not survive read-back")
        return manifest

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
        staged = Path(tmp)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return staged
        except Exception:
            staged.unlink(missing_ok=True)
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
        draws = [draw.to_dict() for draw in dataset.draws]
        if not draws or dataset.canonical_hash != sha256_json(draws):
            raise ValueError("canonical dataset hash is invalid")
        if evidence.get("canonical_hash") != dataset.canonical_hash or evidence.get("draw_count") != len(draws):
            raise ValueError("source evidence does not bind to canonical dataset")
        if evidence.get("latest") != draws[-1] or evidence.get("crosscheck_status") != "PASS":
            raise ValueError("source evidence latest draw or crosscheck is invalid")
        if (isinstance(dataset.crosscheck_count, bool) or dataset.crosscheck_count < 1
                or evidence.get("crosscheck_count") != dataset.crosscheck_count):
            raise ValueError("source evidence crosscheck count differs from canonical dataset")
        self._check_baseline_prefix(evidence, draws)
        if evidence.get("source_receipts") != [r.__dict__ for r in dataset.receipts]:
            raise ValueError("source receipts differ from canonical dataset")
        raw_payloads = evidence.get("_raw_response_payloads")
        if not isinstance(raw_payloads, dict):
            raise ValueError("raw response bytes were not supplied")
        if set(raw_payloads) != {record.get("sha256") for record in evidence.get("raw_responses", [])}:
            raise ValueError("raw response bytes and manifest have different digest sets")
        self._check_raw_evidence(evidence, self.raw_root, raw_payloads)
        clean_evidence = {key: value for key, value in evidence.items() if key != "_raw_response_payloads"}
        clean_evidence["raw_response_status"] = "PASS"
        clean_evidence.pop("commit_id", None)
        commit_id = sha256_json({
            "canonical_hash": dataset.canonical_hash,
            "evidence_hash": sha256_json(clean_evidence),
        })
        clean_evidence["commit_id"] = commit_id
        latest = date.fromisoformat(str(draws[-1]["draw_date"]))
        today = datetime.now(timezone.utc).date()
        if not today - timedelta(days=7) <= latest <= today + timedelta(days=1):
            raise ValueError("canonical latest draw is stale or future dated")
        payload = {
            "schema": 4,
            "game": "SSQ",
            "canonical_hash": dataset.canonical_hash,
            "commit_id": commit_id,
            "draws": draws,
        }
        for digest, raw in raw_payloads.items():
            artifact = self.raw_root / f"{digest}.bin"
            if artifact.exists():
                if sha256_bytes(artifact.read_bytes()) != digest:
                    raise ValueError("existing content-addressed raw artifact is corrupt")
            else:
                atomic_write(artifact, raw)
        self._check_raw_evidence(clean_evidence, self.raw_root)
        old_history = self.history_path.read_bytes() if self.history_path.exists() else None
        old_evidence = self.evidence_path.read_bytes() if self.evidence_path.exists() else None
        staged_history: Path | None = None
        staged_evidence: Path | None = None
        marker_written = False
        try:
            staged_history = self._stage_bytes(self.history_path, self._json_bytes(payload))
            staged_evidence = self._stage_bytes(self.evidence_path, self._json_bytes(clean_evidence))
            atomic_json(self.update_marker, {"status": "PENDING", "commit_id": commit_id})
            marker_written = True
            self._commit_replace(staged_evidence, self.evidence_path)
            staged_evidence = None
            self._commit_replace(staged_history, self.history_path)
            staged_history = None
            if self.load_draws()[1] != dataset.canonical_hash:
                raise ValueError("persisted canonical dataset failed read-back verification")
            if json.loads(self.evidence_path.read_text(encoding="utf-8")) != clean_evidence:
                raise ValueError("persisted source evidence failed read-back verification")
            self.update_marker.unlink()
        except Exception as exc:
            if marker_written:
                try:
                    self._restore_bytes(self.evidence_path, old_evidence)
                    self._restore_bytes(self.history_path, old_history)
                    self.update_marker.unlink(missing_ok=True)
                except Exception as rollback_exc:
                    raise RuntimeError(
                        f"dataset commit failed and rollback was incomplete: {type(rollback_exc).__name__}: {rollback_exc}"
                    ) from exc
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
        if any(draws[i].issue >= draws[i + 1].issue for i in range(len(draws) - 1)):
            raise ValueError("local canonical issue order is not strictly increasing")
        for draw in draws:
            day = date.fromisoformat(draw.draw_date)
            if str(day.year) != draw.issue[:4]:
                raise ValueError("local canonical issue/date year mismatch")
        return draws, expected

    @staticmethod
    def _check_baseline_prefix(evidence: dict[str, Any], draws: list[dict[str, Any]]) -> None:
        if (evidence.get("schema") != "official-source-evidence-v8.5"
                or evidence.get("verification") != "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS"):
            return
        count = evidence.get("baseline_draw_count")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 < count <= len(draws):
            raise ValueError("fallback baseline draw count is invalid")
        if sha256_json(draws[:count]) != evidence.get("baseline_canonical_hash"):
            raise ValueError("fallback canonical history does not preserve its verified baseline")

    def _integrity_check(self, *, require_raw: bool) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        draws: list[Draw] | None = None
        digest = ""

        db: sqlite3.Connection | None = None
        checks.append({
            "name": "Dataset update transaction",
            "status": "FAIL" if self.update_marker.exists() else "PASS",
            "detail": "incomplete update marker present" if self.update_marker.exists() else "no incomplete update",
        })
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
            if history_commit:
                if (not isinstance(history_commit, str) or not re.fullmatch(r"[0-9a-f]{64}", history_commit)
                        or history_commit != evidence_commit):
                    raise ValueError("dataset/evidence commit_id mismatch")
                unhashed_evidence = {key: value for key, value in evidence.items() if key != "commit_id"}
                expected_commit = sha256_json({
                    "canonical_hash": digest,
                    "evidence_hash": sha256_json(unhashed_evidence),
                })
                if history_commit != expected_commit:
                    raise ValueError("dataset/evidence commit_id digest mismatch")
            elif evidence.get("schema") == "official-source-evidence-v8.5":
                raise ValueError("current-version dataset lacks transaction commit_id")
            if str(evidence.get("canonical_hash")) != digest:
                raise ValueError("source evidence canonical_hash mismatch")
            if str(evidence.get("crosscheck_status")) != "PASS":
                raise ValueError("source crosscheck is not PASS")
            if int(evidence.get("draw_count", -1)) != len(draws):
                raise ValueError("source evidence draw_count mismatch")
            latest = evidence.get("latest") or {}
            if latest != draws[-1].to_dict():
                raise ValueError("source evidence latest draw mismatch")
            self._check_baseline_prefix(evidence, [draw.to_dict() for draw in draws])
            if require_raw:
                latest_date = date.fromisoformat(draws[-1].draw_date)
                today = datetime.now(timezone.utc).date()
                if not today - timedelta(days=7) <= latest_date <= today + timedelta(days=1):
                    raise ValueError("canonical latest draw is stale or future dated")
                self._check_raw_evidence(evidence, self.raw_root)
            checks.append({
                "name": "Source evidence and raw responses" if require_raw else "Trusted baseline structure",
                "status": "PASS",
                "detail": f"crosscheck={evidence.get('crosscheck_count', 0)} / latest={draws[-1].issue}",
            })
        except Exception as exc:
            checks.append({"name": "Source evidence and raw responses" if require_raw else "Trusted baseline structure", "status": "FAIL", "detail": str(exc)})

        status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "PASS"
        return {
            "status": status,
            "ok": status == "PASS",
            "checks": checks,
        }

    def integrity_check(self) -> dict[str, Any]:
        """Strict current-version check; historical seed never implies live PASS."""
        return self._integrity_check(require_raw=True)

    def baseline_integrity_check(self) -> dict[str, Any]:
        """Only proves local historical structure for a fresh network rebuild."""
        return self._integrity_check(require_raw=False)
