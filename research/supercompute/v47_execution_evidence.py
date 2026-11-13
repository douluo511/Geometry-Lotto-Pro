"""Produce strict machine-checkable evidence for a dual-game 11-model run.

This validation does NOT claim input is current or independently official.
It verifies actual execution traces and create-only SHA256 frozen research receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from research.supercompute.v47_models import validate_ticket, canonical
from research.supercompute.v47_registry import REGISTRY

EXPECTED = tuple(model.label for model in REGISTRY)


def inspect_run(report_path, frozen_dir, expected_targets, latest_verified):
    raw = Path(report_path).read_bytes()
    payload = json.loads(raw)
    if (payload.get("schema") != "SSQDLT_V47_UNIFIED_RUN_V1"
            or set(payload.get("games", {})) != {"ssq", "dlt"}
            or payload.get("edge") != "NO_EDGE"
            or payload.get("formal_prediction") is not False
            or len(EXPECTED) != 11):
        raise ValueError("incomplete dual-game research report")
    evidence = {"schema": "SSQDLT_V47_11_MODEL_EXECUTION_EVIDENCE_V1",
                "report_sha256": hashlib.sha256(raw).hexdigest(),
                "verified_from": "GITHUB_ACTIONS_EXECUTION",
                "input_source": "CHECKED_IN_HISTORICAL_SNAPSHOT",
                "source_current_verification": False,
                "games": {}}
    for game, outcome in payload["games"].items():
        target = str(expected_targets[game])
        if outcome.get("target_issue") != target:
            raise ValueError(f"target mismatch: {game}")
        independent = outcome["independent_11"]
        if (independent.get("model_count") != 11
                or independent.get("independent_modules") is not True
                or set(independent.get("models", {})) != set(EXPECTED)
                or independent.get("formal_prediction") is not False
                or independent.get("edge") != "NO_EDGE"
                or outcome.get("primary_candidate_source") != "M1_M2_M3_Validation"):
            raise ValueError("not all eleven models executed: " + game)
        actual_names = sorted(
            (item["number"], key) for key, item in independent["models"].items()
        )
        if actual_names != [(i, name) for i, name in enumerate(EXPECTED, 1)]:
            raise ValueError("incorrect independent model registry/order")
        for name, record in independent["models"].items():
            if (record.get("status") != "EXECUTED"
                    or not record.get("fit")
                    or not record.get("prediction")
                    or not record["prediction"].get("ticket")):
                raise ValueError("empty model computation: " + name)
            validate_ticket(record["prediction"]["ticket"], game)
        first = outcome["proposed_tickets"][0]
        if (first["front"], first["back"]) != (
            independent["final_candidate"]["front"],
            independent["final_candidate"]["back"]
        ):
            raise ValueError("model-11 primary candidate was not emitted")
        if not all(v["status"] == "PASS" for v in outcome["validation"]["M1"]):
            raise ValueError("M1 failed")
        if len(outcome["validation"]["M2"]) != 5 or len(outcome["validation"]["M3"]) != 5:
            raise ValueError("M2/M3 absent")
        if (independent["models"]["Physics"]["fit"]
                ["calibrated_to_draw_machine"] is not False):
            raise ValueError("calibration status missing")
        src_issue = str(outcome["history_last_issue"])
        if int(src_issue) >= int(target):
            raise ValueError("target is not after input history")
        basename = f"{game}-{target}-v47-unified.json"
        fpath = Path(frozen_dir) / basename
        frozen = fpath.read_bytes()
        doc = json.loads(frozen)
        if (doc.get("schema") != "SSQDLT_V47_UNIFIED_FROZEN_V1"
                or doc["source"]["target_issue"] != target
                or doc["source"]["proposed_tickets"][0] != first
                or doc.get("formal_prediction") is not False):
            raise ValueError("frozen research receipt differs: " + game)
        entry = {"target_issue": target,
                 "history_last_issue": src_issue,
                 "history_last_date": outcome["history_last_date"],
                 "latest_public_issue_checked": str(latest_verified[game]),
                 "source_is_fresh": src_issue == str(latest_verified[game]),
                 "model_count": 11,
                 "model_names": list(EXPECTED),
                 "primary": {"front": first["front"], "back": first["back"],
                             "dan2": first["dan2"]},
                 "alternate_candidates": [
                     {"front": t["front"], "back": t["back"], "dan2": t["dan2"]}
                     for t in outcome["proposed_tickets"][1:]
                 ],
                 "genome_id": independent["models"]["Challenger"]
                                      ["fit"]["champion_id"],
                 "generations": len(outcome["evolution"]["lineage"]) - 1,
                 "M1": "PASS", "M2": "EXECUTED", "M3": "EXECUTED",
                 "physics_calibrated": False,
                 "frozen_filename": basename,
                 "frozen_sha256": hashlib.sha256(frozen).hexdigest(),
                 "predictive_edge": "NO_EDGE"}
        evidence["games"][game] = entry
    evidence["source_current_verification"] = all(
        g["source_is_fresh"] for g in evidence["games"].values())
    return evidence


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--frozen-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ssq-target", required=True)
    p.add_argument("--dlt-target", required=True)
    p.add_argument("--ssq-public-latest", required=True)
    p.add_argument("--dlt-public-latest", required=True)
    args = p.parse_args(argv)
    evidence = inspect_run(
        args.report, args.frozen_dir,
        {"ssq": args.ssq_target, "dlt": args.dlt_target},
        {"ssq": args.ssq_public_latest, "dlt": args.dlt_public_latest},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as f:
        f.write(canonical(evidence))
    print("V47_EXECUTED_11_EVIDENCE=" + json.dumps(evidence,
          ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
