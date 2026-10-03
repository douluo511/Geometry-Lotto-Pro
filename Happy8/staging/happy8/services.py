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
        repair_environment_probe: Callable[[], dict[str, Any]] | None = None,
    ):
        self.data_root = Path(data_root).resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data_root / "store")
        self.results = self.data_root / "results"
        self.evidence = self.data_root / "evidence"
        self.snapshot_builder = snapshot_builder
        self.science_validator = science_validator
        self.software_update_launcher = software_update_launcher
        self.repair_environment_probe = repair_environment_probe
        self.cache = self.data_root / "cache"

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
        ranking80 = [
            {
                "rank": int(row["rank"]),
                "number": int(row["number"]),
                "score": float(row["score"]),
                "consensus": float(row["consensus"]),
                "stability": float(row["stability"]),
                "seed_support": float(row["seed_support"]),
                "frequency_signal": float(row["frequency_signal"]),
                "transition_signal": float(row["transition_signal"]),
                "geometry_signal": float(row["geometry_signal"]),
            }
            for row in ranking
        ]
        candidate10 = sorted(int(row["number"]) for row in ranking[:PICK_SIZE])
        candidate20 = sorted(int(row["number"]) for row in ranking[:20])
        observed_core = sorted(int(row["number"]) for row in ranking[:4])
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
            "ranking80_research_only": ranking80,
            "candidate10_research_only": candidate10,
            "candidate20_research_only": candidate20,
            "observed_core_research_only": observed_core,
            "baseline": {
                "single_number_probability": 0.25,
                "pick10_expected_hits": 2.5,
            },
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
        """Repair only recoverable local state and diagnose externally bound state.

        The application uses a generation-based file store rather than SQLite.
        That store is the persistence/database-equivalent layer; CURRENT.json is
        its index pointer. Release/network configuration is never synthesized.
        """
        components: dict[str, dict[str, Any]] = {}
        before = self.store.integrity_check()

        # Database/storage + index + missing-file + data-integrity recovery:
        # switch only to an already verified immutable generation.
        repaired = None
        if before.get("status") == "PASS":
            snapshot = self.store.read_current_snapshot()
            components["database"] = {
                "status": "PASS",
                "action": "GENERATION_STORE_VERIFIED",
                "implementation": "generation_file_store",
                "generation_id": snapshot["generation_id"],
            }
            components["index"] = {
                "status": "PASS",
                "action": "CURRENT_POINTER_VERIFIED",
                "implementation": "CURRENT.json",
            }
            components["missing_files"] = {
                "status": "PASS",
                "action": "CURRENT_GENERATION_REQUIRED_FILES_VERIFIED",
            }
        else:
            repaired = self.store.repair_current_pointer()
            if repaired.get("status") == "PASS":
                components["database"] = {
                    "status": "PASS",
                    "action": "RESTORED_VERIFIED_GENERATION",
                    "implementation": "generation_file_store",
                    "generation_id": repaired["generation_id"],
                }
                components["index"] = {
                    "status": "PASS",
                    "action": "REBUILT_FROM_VERIFIED_GENERATION",
                    "implementation": "CURRENT.json",
                }
                components["missing_files"] = {
                    "status": "PASS",
                    "action": "RECOVERED_BY_VERIFIED_GENERATION_SWITCH",
                }
            else:
                components["database"] = {
                    "status": "FAIL",
                    "action": "NO_VALID_GENERATION",
                    "implementation": "generation_file_store",
                    "detail": repaired,
                }
                components["index"] = {
                    "status": "FAIL",
                    "action": "NO_SAFE_POINTER_TARGET",
                    "implementation": "CURRENT.json",
                }
                components["missing_files"] = {
                    "status": "FAIL",
                    "action": "NO_SAFE_LOCAL_SOURCE",
                }

        # Cache is explicitly ephemeral. Never delete generations/results/evidence.
        cache_removed = 0
        cache_error = None
        try:
            if self.cache.exists():
                for path in sorted(self.cache.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                        cache_removed += 1
                    elif path.is_dir():
                        path.rmdir()
                self.cache.rmdir()
            self.cache.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            cache_error = f"{type(exc).__name__}: {exc}"
        components["cache"] = {
            "status": "PASS" if cache_error is None else "FAIL",
            "action": "CLEARED_EPHEMERAL_CACHE" if cache_error is None else "CACHE_REPAIR_FAILED",
            "removed_entries": cache_removed,
            "detail": cache_error,
        }

        # Configuration/network/version are externally anchored. Diagnose them;
        # never generate a fake trusted endpoint or version.
        if self.repair_environment_probe is None:
            environment = {
                "status": "BLOCKED",
                "checks": {
                    "release_config": {
                        "status": "BLOCKED",
                        "detail": "trusted software-update environment probe is not configured",
                    },
                    "network_config": {
                        "status": "BLOCKED",
                        "detail": "trusted network release configuration cannot be inferred",
                    },
                    "version_contract": {
                        "status": "BLOCKED",
                        "detail": "packaged software version contract is unavailable",
                    },
                },
            }
        else:
            try:
                environment = self.repair_environment_probe()
            except Exception as exc:
                environment = {
                    "status": "FAIL",
                    "checks": {
                        "environment_probe": {
                            "status": "FAIL",
                            "detail": f"{type(exc).__name__}: {exc}",
                        }
                    },
                }

        env_checks = dict(environment.get("checks") or {})
        components["configuration"] = dict(
            env_checks.get("release_config")
            or {"status": environment.get("status", "FAIL"), "detail": "release config check missing"}
        )
        components["network_configuration"] = dict(
            env_checks.get("network_config")
            or {"status": environment.get("status", "FAIL"), "detail": "network config check missing"}
        )
        components["version"] = dict(
            env_checks.get("version_contract")
            or {"status": environment.get("status", "FAIL"), "detail": "version contract check missing"}
        )
        if "updater_exe" in env_checks:
            components["updater_file"] = dict(env_checks["updater_exe"])
        if "main_exe" in env_checks:
            components["main_exe_file"] = dict(env_checks["main_exe"])

        after = self.store.integrity_check()
        components["data_integrity"] = {
            "status": "PASS" if after.get("status") == "PASS" else "FAIL",
            "before": before,
            "after": after,
        }

        states = [str(item.get("status") or "FAIL") for item in components.values()]
        if "FAIL" in states:
            status = "FAIL"
        elif "BLOCKED" in states:
            status = "BLOCKED"
        else:
            status = "PASS"

        action = (
            "REPAIR_COMPLETE"
            if status == "PASS"
            else "LOCAL_REPAIR_COMPLETE_EXTERNAL_BLOCKER"
            if status == "BLOCKED" and after.get("status") == "PASS"
            else "REPAIR_FAILED"
        )
        result = {
            "schema": "happy8-repair-v2",
            "status": status,
            "operation": "repair",
            "action": action,
            "components": components,
            "store_repaired": bool(repaired and repaired.get("status") == "PASS"),
            "user_data_deleted": False,
            "post_repair_self_check": after,
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
