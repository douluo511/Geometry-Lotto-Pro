from __future__ import annotations

import hashlib
import json
import os
import re
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


def _validate_raw_bundle(report: dict[str, Any], raw_sources: dict[str, bytes]) -> dict[str, str]:
    receipts = report.get("source_receipts")
    if not isinstance(receipts, list) or len(receipts) < 2:
        raise ValueError("at least two source receipts are required")
    receipt_by_source = {str(x.get("source")): x for x in receipts}

    history_source = str(report.get("history_source") or "shanghai_welfare_lottery")
    history = receipt_by_source.get(history_source)
    jiangsu = receipt_by_source.get("jiangsu_welfare_lottery")
    if not history or history.get("status") != "PASS" or not jiangsu or jiangsu.get("status") != "PASS":
        raise ValueError("required official PASS source receipts are missing")

    manifest = report.get("history_raw_manifest")
    if manifest is None and history_source == "shanghai_welfare_lottery":
        manifest = report.get("shanghai_raw_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("full-history raw manifest is missing")
    manifest_hash = sha256_json(manifest)
    if manifest_hash != history.get("raw_sha256"):
        raise ValueError("history raw manifest SHA mismatch")
    if sum(int(x.get("bytes") or 0) for x in manifest) != int(history.get("bytes") or 0):
        raise ValueError("history raw manifest byte count mismatch")

    seen_files: set[str] = set()
    for item in manifest:
        filename = str(item.get("filename") or "")
        if history_source == "national_welfare_lottery":
            safe = re.fullmatch(r"national_page_\d{4}\.json", filename)
        elif history_source == "shanghai_welfare_lottery":
            safe = re.fullmatch(r"shanghai_20\d{5}_20\d{5}\.html", filename)
        else:
            safe = None
        if not safe:
            raise ValueError(f"unsafe history raw filename/source: {history_source} {filename!r}")
        if filename in seen_files:
            raise ValueError(f"duplicate history raw filename: {filename}")
        seen_files.add(filename)
        raw = raw_sources.get(filename)
        if raw is None:
            raise ValueError(f"missing history raw response: {filename}")
        if sha256_bytes(raw) != item.get("sha256"):
            raise ValueError(f"history raw SHA mismatch: {filename}")
        if len(raw) != int(item.get("bytes") or -1):
            raise ValueError(f"history raw byte count mismatch: {filename}")

    jiangsu_name = "jiangsu_welfare_lottery.html"
    jiangsu_raw = raw_sources.get(jiangsu_name)
    if jiangsu_raw is None:
        raise ValueError("missing Jiangsu raw response")
    if sha256_bytes(jiangsu_raw) != jiangsu.get("raw_sha256"):
        raise ValueError("Jiangsu raw SHA mismatch")
    if len(jiangsu_raw) != int(jiangsu.get("bytes") or -1):
        raise ValueError("Jiangsu raw byte count mismatch")

    extra = set(raw_sources) - seen_files - {jiangsu_name}
    if extra:
        raise ValueError(f"unexpected raw source files: {sorted(extra)!r}")

    return {
        history_source: str(history["raw_sha256"]),
        "jiangsu_welfare_lottery": str(jiangsu["raw_sha256"]),
    }


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

        source_raw_hashes = _validate_raw_bundle(report, raw_sources)
        generation_material = {
            "canonical_hash": canonical_hash,
            "source_raw_hashes": source_raw_hashes,
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
                    "schema": "happy8-canonical-v2",
                    "canonical_hash": canonical_hash,
                    "draw_count": len(draws),
                    "draws": draws,
                }
                evidence = {
                    "schema": "happy8-source-evidence-v2",
                    "canonical_hash": canonical_hash,
                    "network_schema": report.get("schema"),
                    "latest": report.get("latest"),
                    "history_count": report.get("history_count"),
                    "crosscheck_count": report.get("crosscheck_count"),
                    "crosscheck_status": report.get("crosscheck_status"),
                    "verification": report.get("verification"),
                    "source_receipts": report.get("source_receipts"),
                    "history_source": report.get("history_source"),
                    "history_raw_manifest": report.get("history_raw_manifest"),
                    "shanghai_raw_manifest": report.get("shanghai_raw_manifest"),
                }
                _atomic_bytes(stage / "CANONICAL.json", (canonical_json(canonical) + "\n").encode("utf-8"))
                _atomic_bytes(stage / "EVIDENCE.json", (canonical_json(evidence) + "\n").encode("utf-8"))
                os.replace(stage, final_dir)
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise

        pointer = {
            "schema": "happy8-current-pointer-v2",
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
            checks.append({
                "name": "canonical_hash",
                "status": "PASS" if computed == canonical.get("canonical_hash") == pointer.get("canonical_hash") else "FAIL",
            })
            checks.append({
                "name": "evidence_binding",
                "status": "PASS" if evidence.get("canonical_hash") == computed else "FAIL",
            })
            checks.append({
                "name": "crosscheck",
                "status": "PASS"
                if evidence.get("crosscheck_status") == "PASS" and int(evidence.get("crosscheck_count") or 0) >= 1
                else "FAIL",
            })

            raw_sources = {
                path.name: path.read_bytes()
                for path in (generation / "RAW").iterdir()
                if path.is_file()
            }
            integrity_report = {
                "source_receipts": evidence.get("source_receipts"),
                "history_source": evidence.get("history_source"),
                "history_raw_manifest": evidence.get("history_raw_manifest"),
                "shanghai_raw_manifest": evidence.get("shanghai_raw_manifest"),
            }
            _validate_raw_bundle(integrity_report, raw_sources)
            checks.append({"name": "raw_provenance", "status": "PASS"})
        except Exception as exc:
            checks.append({"name": "store_read", "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"})

        status = "PASS" if checks and all(x["status"] == "PASS" for x in checks) else "FAIL"
        return {"schema": "happy8-storage-integrity-v2", "status": status, "checks": checks}
