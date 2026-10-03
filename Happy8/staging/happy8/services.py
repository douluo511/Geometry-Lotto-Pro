from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .domain import Draw
from .science import PICK_SIZE, build_prefix_state, rank_prefix, validate_history
from .sources import build_official_snapshot
from .storage import Store, canonical_json, sha256_json


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(canonical_json(value) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class Happy8Service:
    """Application service boundary used by CLI and GUI.

    UI code must call these methods instead of importing Source/Storage/Science
    directly.  Every success response is derived from verified state.
    """

    def __init__(
        self,
        data_root: Path,
        *,
        snapshot_builder: Callable[[], tuple[dict[str, Any], dict[str, bytes]]] = build_official_snapshot,
        science_validator: Callable[..., dict[str, Any]] = validate_history,
        software_update_launcher: Callable[[], dict[str, Any]] | None = None,
    ):
        self.data_root = Path(data_root).resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data_root / "store")
        self.results = self.data_root / "results"
        self.evidence = self.data_root / "evidence"
        self.snapshot_builder = snapshot_builder
        self.science_validator = science_validator
        self.software_update_launcher = software_update_launcher

    @staticmethod
    def _draws(snapshot: dict[str, Any]) -> list[Draw]:
        rows = snapshot["canonical"].get("draws")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("verified canonical snapshot contains no draws")
        return [
            Draw.from_values(row["issue"], row["draw_date"], row["numbers"])
            for row in rows
        ]

    def status(self) -> dict[str, Any]:
        integrity = self.store.integrity_check()
        result: dict[str, Any] = {
            "status": integrity.get("status"),
            "store_integrity": integrity,
        }
        if integrity.get("status") == "PASS":
            snapshot = self.store.read_current_snapshot()
            result.update({
                "generation_id": snapshot["generation_id"],
                "canonical_hash": snapshot["canonical"]["canonical_hash"],
                "draw_count": snapshot["canonical"]["draw_count"],
                "latest_issue": snapshot["canonical"]["draws"][-1]["issue"],
            })
        return result

    def software_update(self) -> dict[str, Any]:
        if self.software_update_launcher is None:
            raise RuntimeError("independent software Updater is not configured")
        result = self.software_update_launcher()
        if result.get("status") != "PASS" or result.get("action") != "UPDATER_HANDOFF":
            raise RuntimeError("independent software Updater handoff failed")
        return result

    def update_data(self) -> dict[str, Any]:
        report, raw_sources = self.snapshot_builder()
        if report.get("status") != "PASS":
            raise RuntimeError("official network snapshot is not PASS")
        commit = self.store.commit_official_snapshot(report, raw_sources)
        result = {
            "status": "PASS",
            "operation": "update",
            "generation_id": commit["generation_id"],
            "canonical_hash": commit["canonical_hash"],
            "history_count": report["history_count"],
            "latest_issue": report["latest"]["issue"],
            "history_source": report["history_source"],
            "verification": report["verification"],
            "completed_at": _utc_now(),
        }
        _atomic_json(self.evidence / "last_update.json", result)
        return result

    def predict_next(self) -> dict[str, Any]:
        snapshot = self.store.read_current_snapshot()
        draws = self._draws(snapshot)
        science = self.science_validator(
            draws,
            canonical_hash=str(snapshot["canonical"]["canonical_hash"]),
        )
        state = build_prefix_state(draws)
        ranking = rank_prefix(draws, state, len(draws))
        candidate10 = sorted(int(row["number"]) for row in ranking[:PICK_SIZE])
        latest_issue = draws[-1].issue
        target_issue = str(int(latest_issue) + 1)

        edge_state = str(science.get("edge_state"))
        dan_state = str(science.get("dan_state"))
        formal_dan = list(science.get("formal_dan") or [])
        if edge_state != "VALIDATED_EDGE":
            if dan_state != "NULL_DAN" or formal_dan:
                raise RuntimeError("NO_EDGE scientific state attempted to emit formal dan")
            production_model = "uniform_baseline"
            label = "STRUCTURED_CANDIDATE_ONLY"
        else:
            production_model = str(science.get("production_model"))
            label = "VALIDATED_EDGE"

        freeze = {
            "schema": "happy8-prediction-freeze-v1",
            "status": "PASS",
            "target_issue": target_issue,
            "source_latest_issue": latest_issue,
            "canonical_hash": snapshot["canonical"]["canonical_hash"],
            "generation_id": snapshot["generation_id"],
            "candidate10_research_only": candidate10,
            "formal_dan": formal_dan,
            "edge_state": edge_state,
            "dan_state": dan_state,
            "production_model": production_model,
            "label": label,
            "created_at": _utc_now(),
        }
        freeze["freeze_hash"] = sha256_json({
            key: value for key, value in freeze.items() if key not in {"created_at", "freeze_hash"}
        })
        path = self.results / f"prediction_{target_issue}.json"
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            comparable_keys = set(freeze) - {"created_at"}
            if any(previous.get(k) != freeze.get(k) for k in comparable_keys):
                raise RuntimeError(
                    f"immutable prediction freeze conflict for target issue {target_issue}"
                )
            return previous
        _atomic_json(path, freeze)
        _atomic_json(self.evidence / "last_prediction.json", freeze)
        return freeze

    def repair(self) -> dict[str, Any]:
        before = self.store.integrity_check()
        if before.get("status") == "PASS":
            snapshot = self.store.read_current_snapshot()
            result = {
                "status": "PASS",
                "operation": "repair",
                "action": "NO_CHANGE_REQUIRED",
                "generation_id": snapshot["generation_id"],
                "completed_at": _utc_now(),
            }
        else:
            repaired = self.store.repair_current_pointer()
            if repaired.get("status") != "PASS":
                result = {
                    "status": "FAIL",
                    "operation": "repair",
                    "action": "NO_VALID_GENERATION",
                    "before": before,
                    "repair": repaired,
                    "completed_at": _utc_now(),
                }
                _atomic_json(self.evidence / "last_repair.json", result)
                return result
            after = self.store.integrity_check()
            if after.get("status") != "PASS":
                raise RuntimeError("repair reported PASS but post-repair integrity failed")
            result = {
                "status": "PASS",
                "operation": "repair",
                "action": "RESTORED_VERIFIED_GENERATION",
                "generation_id": repaired["generation_id"],
                "before": before,
                "after": after,
                "completed_at": _utc_now(),
            }
        _atomic_json(self.evidence / "last_repair.json", result)
        return result

    def advanced_analysis(self) -> dict[str, Any]:
        snapshot = self.store.read_current_snapshot()
        draws = self._draws(snapshot)
        report = self.science_validator(
            draws,
            canonical_hash=str(snapshot["canonical"]["canonical_hash"]),
        )
        if report.get("status") != "PASS" or report.get("software_verdict") != "PASS":
            raise RuntimeError("scientific validation software gate failed")
        result = {
            "status": "PASS",
            "operation": "advanced_analysis",
            "generation_id": snapshot["generation_id"],
            "canonical_hash": snapshot["canonical"]["canonical_hash"],
            "report": report,
            "completed_at": _utc_now(),
        }
        _atomic_json(self.evidence / "last_advanced_analysis.json", result)
        return result
