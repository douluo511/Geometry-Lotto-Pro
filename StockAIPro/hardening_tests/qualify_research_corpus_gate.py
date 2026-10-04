from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import hashlib
import json
import os
import sys

import pandas as pd


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    package_root = args.package_root.resolve()
    data_root = args.data_root.resolve()
    os.environ["STOCK_AI_PACKAGE_ROOT"] = str(package_root)
    os.environ["STOCK_AI_DATA_ROOT"] = str(data_root)

    current = json.loads((package_root / "current.json").read_text(encoding="utf-8"))
    version = str(current["active_version"])
    version_root = package_root / "versions" / version
    sys.path.insert(0, str(version_root))

    from stock_ai.config import ROOT, load_config
    from stock_ai.data_source import qualify_research_pool_coverage

    evidence = {
        "schema": "stock-ai-research-corpus-qualification-v1",
        "status": "FAIL",
        "source_sha": os.environ.get("STOCK_SOURCE_SHA"),
        "active_version": version,
        "data_root": str(ROOT),
        "real_network_historical_corpus": "NOT VERIFIED",
        "final_gate": "FAIL",
    }
    try:
        master_path = ROOT / "cache" / "universe_master.csv"
        if not master_path.is_file():
            raise FileNotFoundError("current core run did not produce universe_master.csv")
        master = pd.read_csv(master_path, dtype={"code": str})
        if master.empty or "code" not in master:
            raise ValueError("research master is empty or missing code")

        cfg = load_config()
        qualification = qualify_research_pool_coverage(master, cfg)
        evidence["qualification"] = qualification
        evidence["master_sha256"] = sha256(master_path)

        history_dir = ROOT / "data" / "history"
        rows = []
        for file in sorted(history_dir.glob("*.csv")):
            rows.append(f"{file.name}:{sha256(file)}")
        manifest_bytes = ("\n".join(rows) + ("\n" if rows else "")).encode("utf-8")
        evidence["history_file_count"] = len(rows)
        evidence["history_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()

        target = max(0.90, float(cfg["universe"].get("qualification_coverage_target", 0.90)))
        delisted_target = max(0.90, float(cfg["universe"].get("qualification_delisted_target", 0.90)))
        coverage = float(qualification.get("coverage", 0) or 0)
        delisted = float(qualification.get("delisted_coverage", 0) or 0)
        passed = (
            qualification.get("qualification_status") == "PASS"
            and coverage >= target
            and delisted >= delisted_target
        )
        evidence["required_coverage"] = target
        evidence["required_delisted_coverage"] = delisted_target
        evidence["real_network_historical_corpus"] = "PASS" if passed else "NOT VERIFIED"
        evidence["status"] = "PASS" if passed else "NOT VERIFIED"
    except Exception as exc:
        evidence["status"] = "FAIL"
        evidence["error_type"] = type(exc).__name__
        evidence["error"] = repr(exc)

    args.output.write_text(json.dumps(evidence, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True))
    return 0 if evidence["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
