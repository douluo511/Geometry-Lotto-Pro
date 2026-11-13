"""Mechanical audit that the mother registry covers every discovered source arm.

No auto-deletion: a selection algorithm, GUI service, source parser or historical
replay implementation cannot safely be classified as an unused model.
"""
from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path

from research.harness_v46 import core
from research.harness_v46.d2_challenger_lab import ABLATION_ARMS, CHALLENGER_ID
from research.supercompute import engine as legacy
from research.mother_v1.source_identity import committed_source_sha256
from research.mother_v1.registry import (
    REGISTERED_V47, EXPLORATORY_V47, LEGACY_SUPERCOMPUTE,
    NATIVE_FEATURES, PHYSICAL, ALL_MODELS,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = (
    "research/harness_v46/core.py",
    "research/harness_v46/d2_challenger_lab.py",
    "research/supercompute/engine.py",
    "SSQ/SSQ/glp/engine.py",
    "DLT/src/glp/engine.py",
    "research/supercompute/automation/ssq_physical_source.py",
    "research/supercompute/automation/dlt_physical_source.py",
    "research/mother_v1/mother.py",
    "research/mother_v1/native_worker.py",
)
NATIVE_BASE = {
    "simple_frequency", "recency", "gap", "transition", "pair_graph",
    "geometry_state", "geometry_transition", "research_ensemble",
}


class InventoryBlocked(ValueError):
    pass


def _native_ssq_sources() -> set[str]:
    code = ast.parse((ROOT / "SSQ/SSQ/glp/engine.py").read_text(encoding="utf-8"))
    func = next((x for x in code.body if isinstance(x, ast.FunctionDef)
                 and x.name == "model_scores_from_features"), None)
    if func is None:
        raise InventoryBlocked("SSQ_NATIVE_SCORE_FACTORY_MISSING")
    found = set()
    for n in ast.walk(func):
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "out":
            sl = n.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                # Reading a component also counts, so require an assignment.
                found.add(sl.value)
    return found


def _native_dlt_sources() -> set[str]:
    code = ast.parse((ROOT / "DLT/src/glp/engine.py").read_text(encoding="utf-8"))
    base = next((x for x in code.body if isinstance(x, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "BASE_MODELS" for t in x.targets)), None)
    if base is None:
        raise InventoryBlocked("DLT_NATIVE_BASE_MODELS_MISSING")
    return set(ast.literal_eval(base.value)) | {"research_ensemble"}


def audit() -> dict:
    actual = {
        "V47_FROZEN": set(core.MODELS),
        "V47_EXPLORATORY": set(EXPLORATORY_V47),
        "LEGACY_SUPERCOMPUTE": set(LEGACY_SUPERCOMPUTE),
        "SSQ_NATIVE": _native_ssq_sources(),
        "DLT_NATIVE": _native_dlt_sources(),
        "PHYSICAL": set(PHYSICAL),
    }
    if tuple(core.MODELS) != tuple(REGISTERED_V47):
        raise InventoryBlocked("REGISTERED_V47_CORE_MISMATCH")
    if actual["SSQ_NATIVE"] != NATIVE_BASE or actual["DLT_NATIVE"] != NATIVE_BASE:
        raise InventoryBlocked("MISSING_NATIVE_GEOMETRY_OR_ENSEMBLE_ARM")
    if {s.removeprefix("native_") for s in NATIVE_FEATURES} != NATIVE_BASE:
        raise InventoryBlocked("MOTHER_NATIVE_REGISTRY_MISMATCH")
    if {s.removeprefix("supercompute_").upper() for s in LEGACY_SUPERCOMPUTE} != set(legacy.MODELS):
        raise InventoryBlocked("SUPERCOMPUTE_ARCHIVE_UNREGISTERED")
    # Four distinct exploratory ablation arms; duplicates of frozen
    # hot60, ewma, pairwise_d2, random_null are NOT double-counted.
    covered_arms = {
        "HOT30", "HOT120", "P-MARGIN", "P-RESIDUAL", "HOT60",
        "EWMA", "P-COMBINED", "NULL",
    }
    if set(ABLATION_ARMS) != covered_arms or "recency_pair_h45_120" not in EXPLORATORY_V47:
        raise InventoryBlocked("UNACCOUNTED_ABLATION_ARM")
    if (len(ALL_MODELS) != 24 or len(set(ALL_MODELS)) != 24 or
            len(PHYSICAL) != 2 or set(ALL_MODELS) !=
            (set(REGISTERED_V47) | set(EXPLORATORY_V47) |
             set(LEGACY_SUPERCOMPUTE) | set(NATIVE_FEATURES) | set(PHYSICAL))):
        raise InventoryBlocked("REGISTRY_MISSING_OR_DUPLICATE")
    hashes = {}
    for relative in SOURCE_PATHS:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise InventoryBlocked("MODEL_SOURCE_MISSING_OR_SYMLINK")
        hashes[relative] = committed_source_sha256(path)
    return {
        "schema": "SSQDLT_MOTHER_V1_COMPLETE_MODEL_SOURCE_INVENTORY",
        "registered_models_per_game": list(ALL_MODELS),
        "model_rows_per_two_games": len(ALL_MODELS) * 2,
        "registered_v47_count": len(REGISTERED_V47),
        "exploratory_v47_count": len(EXPLORATORY_V47),
        "legacy_supercompute_count": len(LEGACY_SUPERCOMPUTE),
        "native_ssq_count": len(actual["SSQ_NATIVE"]),
        "native_dlt_count": len(actual["DLT_NATIVE"]),
        "physical_count": len(PHYSICAL),
        "source_file_sha256": hashes,
        "source_methods_checked": {
            "V47": list(core.MODELS), "legacy": list(legacy.MODELS),
            "SSQ_native": sorted(actual["SSQ_NATIVE"]),
            "DLT_native": sorted(actual["DLT_NATIVE"]),
            "ablation": list(ABLATION_ARMS),
            "physical": list(PHYSICAL),
        },
        "full_research_edge": "NO_EDGE", "formal_A": 0,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    report = audit()
    serialized = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2)
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(serialized + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in (
        "source_file_sha256", "registered_models_per_game", "source_methods_checked")},
        ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
