"""Fail-closed inventory of only approved mother model families.

The eight SSQ/DLT native feature & ensemble engines are retired from ALL
new unified predictions. No new model can be added without explicit registry
change and a source-identity test. Original application code is not part of
this mother and its historical sealed prediction identities remain unchanged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.harness_v46 import core
from research.harness_v46.d2_challenger_lab import ABLATION_ARMS
from research.supercompute import engine as legacy
from research.mother_v1.source_identity import committed_source_sha256
from research.mother_v1.registry import (
    REGISTERED_V47, EXPLORATORY_V47, LEGACY_SUPERCOMPUTE,
    PHYSICAL, ALL_MODELS,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = (
    "research/harness_v46/core.py",
    "research/harness_v46/d2_challenger_lab.py",
    "research/supercompute/engine.py",
    "research/supercompute/automation/ssq_physical_source.py",
    "research/supercompute/automation/dlt_physical_source.py",
    "research/mother_v1/mother.py",
)
RETIRED_NATIVE = (
    "native_simple_frequency", "native_recency", "native_gap",
    "native_transition", "native_pair_graph", "native_geometry_state",
    "native_geometry_transition", "native_research_ensemble",
)


class InventoryBlocked(ValueError):
    pass


def audit() -> dict:
    if tuple(core.MODELS) != tuple(REGISTERED_V47):
        raise InventoryBlocked("FROZEN_V47_CONTRACT_MISMATCH")
    if {s.removeprefix("supercompute_").upper() for s in LEGACY_SUPERCOMPUTE} != set(legacy.MODELS):
        raise InventoryBlocked("LEGACY_PROVIDER_UNREGISTERED")
    if set(ABLATION_ARMS) != {
        "HOT30", "HOT120", "P-MARGIN", "P-RESIDUAL",
        "HOT60", "EWMA", "P-COMBINED", "NULL",
    }:
        raise InventoryBlocked("ABLATION_ARM_MISSING")
    expected = (
        set(REGISTERED_V47) | set(EXPLORATORY_V47)
        | set(LEGACY_SUPERCOMPUTE) | set(PHYSICAL)
    )
    if len(ALL_MODELS) != len(set(ALL_MODELS)) or len(ALL_MODELS) != 16 or set(ALL_MODELS) != expected:
        raise InventoryBlocked("ACTIVE_MODEL_REGISTRY_CONFLICT")
    if set(ALL_MODELS).intersection(RETIRED_NATIVE):
        raise InventoryBlocked("RETIRED_NATIVE_STILL_REGISTERED")
    for path in ("research/mother_v1/native_provider.py",
                 "research/mother_v1/native_worker.py"):
        if (ROOT / path).exists():
            raise InventoryBlocked("RETIRED_NATIVE_BRIDGE_NOT_REMOVED")
    hashes = {}
    for relative in SOURCE_PATHS:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise InventoryBlocked("ACTIVE_SOURCE_MISSING_OR_SYMLINK")
        hashes[relative] = committed_source_sha256(path)
    return {
        "schema": "SSQDLT_MOTHER_V1_RETIRED_NATIVE_INVENTORY",
        "registered_models_per_game": list(ALL_MODELS),
        "model_rows_per_two_games": 32,
        "registered_v47_count": len(REGISTERED_V47),
        "exploratory_v47_count": len(EXPLORATORY_V47),
        "legacy_supercompute_count": len(LEGACY_SUPERCOMPUTE),
        "physical_count": len(PHYSICAL),
        "removed_native_names": list(RETIRED_NATIVE),
        "retired_native_count_per_game": len(RETIRED_NATIVE),
        "source_file_sha256": hashes,
        "formal_A": 0, "decision": "NO_EDGE",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    result = audit()
    if args.out is not None:
        with args.out.open("x", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, sort_keys=True, indent=2)
            out.write("\n")
    print(json.dumps({
        "model_rows_per_two_games": result["model_rows_per_two_games"],
        "retired_native_count_per_game": result["retired_native_count_per_game"],
        "formal_A": 0, "decision": "NO_EDGE",
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
