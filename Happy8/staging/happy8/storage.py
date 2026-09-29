from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(value)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class Store:
    """Generation-based RAW→CANONICAL→EVIDENCE store with atomic CURRENT pointer."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.generations = self.root / "generations"
        self.current = self.root / "CURRENT.json"
        self.generations.mkdir(parents=True, exist_ok=True)

    def commit_official_snapshot(self, report: dict[str, Any], raw_sources: dict[str, bytes]) -> dict[str, Any]:
        if report.get("status") != "PASS":
            raise ValueError("refuse to commit non-PASS official snapshot")
        draws = report.get("draws")
        if not isinstance(draws, list) or not draws:
            raise ValueError("official snapshot has no canonical draws")
        canonical_hash = sha256_json(draws)
        if canonical_hash != report.get("canonical_hash"):
            raise ValueError("canonical hash mismatch before commit")

        receipts = report.get("source_receipts")
        if not isinstance(receipts, list) or len(receipts) < 2:
            raise ValueError("at least two source receipts are required")
        receipt_by_source = {str(x.get("source")): x for x in receipts}

        expected_files = {
            "shanghai_welfare_lottery": "shanghai_welfare_lottery.html",
            "jiangsu_welfare_lottery": "jiangsu_welfare_lottery.html",
        }
        for source, filename in expected_files.items():
            receipt = receipt_by_source.get(source)
            raw = raw_sources.get(filename)
            if not receipt or raw is None:
                raise ValueError(f"missing raw provenance for {source}")
            if sha256_bytes(raw) != receipt.get("raw_sha256"):
                raise ValueError(f"raw SHA mismatch for {source}")

        generation_material = {
            "canonical_hash": canonical_hash,
            "source_raw_hashes": {k: receipt_by_source[k]["raw_sha256"] for k in sorted(expected_files)},
        }
        generation_id = sha256_json(generation_material)
        final_dir = self.generations / generation_id

        if not final_dir.exists():
            stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=str(self.generations)))
            try:
                raw_dir = stage / "RAW"
                raw_dir.mkdir()
                for filename, raw in raw_sources.items():
                    _atomic_bytes(raw_dir / filename, raw)

                canonical = {
                    "schema": "happy8-canonical-v1",
                    "canonical_hash": canonical_hash,
                    "draw_count": len(draws),
                    "draws": draws,
                }
                evidence = {
                    "schema": "happy8-source-evidence-v1",
                    "canonical_hash": canonical_hash,
                    "network_schema": report.get("schema"),
                    "latest": report.get("latest"),
                    "history_count": report.get("history_count"),
                    "crosscheck_count": report.get("crosscheck_count"),
                    "crosscheck_status": report.get("crosscheck_status"),
                    "source_receipts": receipts,
                }
                _atomic_bytes(stage / "CANONICAL.json", (canonical_json(canonical) + "\n").encode("utf-8"))
                _atomic_bytes(stage / "EVIDENCE.json", (canonical_json(evidence) + "\n").encode("utf-8"))
                os.replace(stage, final_dir)
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise

        pointer = {
            "schema": "happy8-current-pointer-v1",
            "generation_id": generation_id,
            "canonical_hash": canonical_hash,
        }
        _atomic_bytes(self.current, (canonical_json(pointer) + "\n").encode("utf-8"))
        integrity = self.integrity_check()
        if integrity["status"] != "PASS":
            raise RuntimeError("post-commit integrity verification failed")
        return {"status": "PASS", "generation_id": generation_id, "canonical_hash": canonical_hash}

    def integrity_check(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        try:
            pointer = json.loads(self.current.read_text(encoding="utf-8"))
            generation_id = str(pointer["generation_id"])
            generation = self.generations / generation_id
            canonical = json.loads((generation / "CANONICAL.json").read_text(encoding="utf-8"))
            evidence = json.loads((generation / "EVIDENCE.json").read_text(encoding="utf-8"))

            computed = sha256_json(canonical["draws"])
            checks.append({"name": "canonical_hash", "status": "PASS" if computed == canonical.get("canonical_hash") == pointer.get("canonical_hash") else "FAIL"})
            checks.append({"name": "evidence_binding", "status": "PASS" if evidence.get("canonical_hash") == computed else "FAIL"})
            checks.append({"name": "crosscheck", "status": "PASS" if evidence.get("crosscheck_status") == "PASS" and int(evidence.get("crosscheck_count") or 0) >= 1 else "FAIL"})

            receipts = {str(x.get("source")): x for x in evidence.get("source_receipts", [])}
            raw_pairs = {
                "shanghai_welfare_lottery": generation / "RAW" / "shanghai_welfare_lottery.html",
                "jiangsu_welfare_lottery": generation / "RAW" / "jiangsu_welfare_lottery.html",
            }
            raw_ok = True
            for source, path in raw_pairs.items():
                receipt = receipts.get(source)
                if not receipt or not path.exists() or sha256_bytes(path.read_bytes()) != receipt.get("raw_sha256"):
                    raw_ok = False
            checks.append({"name": "raw_provenance", "status": "PASS" if raw_ok else "FAIL"})
        except Exception as exc:
            checks.append({"name": "store_read", "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"})

        status = "PASS" if checks and all(x["status"] == "PASS" for x in checks) else "FAIL"
        return {"schema": "happy8-storage-integrity-v1", "status": status, "checks": checks}
