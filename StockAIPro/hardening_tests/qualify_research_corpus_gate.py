from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    package_root = args.package_root.resolve()
    data_root = args.data_root.resolve()
    output = args.output.resolve()
    os.environ["STOCK_AI_PACKAGE_ROOT"] = str(package_root)
    os.environ["STOCK_AI_DATA_ROOT"] = str(data_root)

    current = json.loads((package_root / "current.json").read_text(encoding="utf-8"))
    version = str(current["active_version"])
    version_root = package_root / "versions" / version
    sys.path.insert(0, str(version_root))

    from stock_ai.config import load_config
    from stock_ai.data_source import qualify_research_pool_coverage
    import pandas as pd

    master_path = data_root / "cache" / "universe_master.csv"
    if not master_path.is_file():
        raise RuntimeError("completed frozen core universe_master.csv is required")

    master = pd.read_csv(master_path, dtype={"code": str})
    if master.empty or "code" not in master:
        raise RuntimeError("research master is empty or missing code")
    if "status" not in master:
        raise RuntimeError("research master missing current/delisted status denominator")

    cfg = load_config()
    result = qualify_research_pool_coverage(master, cfg)
    coverage = float(result.get("coverage", 0) or 0)
    delisted = float(result.get("delisted_coverage", 0) or 0)
    target = max(0.90, float(result.get("qualification_target", 0.90) or 0.90))
    delisted_target = max(
        0.90, float(result.get("qualification_delisted_target", 0.90) or 0.90)
    )
    status = (
        "PASS"
        if result.get("qualification_status") == "PASS"
        and coverage >= target
        and delisted >= delisted_target
        else "NOT VERIFIED"
    )
    evidence = {
        "schema": "stock-ai-research-corpus-qualification-v1",
        "source_commit": os.environ.get("STOCK_SOURCE_SHA"),
        "active_version": version,
        "status": status,
        "coverage": coverage,
        "coverage_target": target,
        "delisted_coverage": delisted,
        "delisted_coverage_target": delisted_target,
        "covered_symbols": result.get("covered_symbols"),
        "target_symbols": result.get("target_symbols"),
        "current_coverage": result.get("current_coverage"),
        "current_target": result.get("current_target"),
        "delisted_target": result.get("delisted_target"),
        "downloaded": result.get("downloaded"),
        "failed_count": len(result.get("failed") or []),
        "qualification_elapsed_seconds": result.get("qualification_elapsed_seconds"),
        "boundary": (
            "Real-network corpus qualification only. It cannot substitute for "
            "Windows/GUI/Release/Repository Independence gates."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
