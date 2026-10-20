"""Current-byte scoped regression, without old real-data scoring or model search."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SPECS = (
    ("new_audit", ["discover", "-s", "research/ssq_dlt_v45_audit/tests", "-v"]),
    ("native_agent_core", ["research.ssq_dlt_agent_v1.tests.test_core", "-v"]),
    ("graph_host", ["research.ssq_dlt_agent_graph.tests.test_host", "-v"]),
    ("negative_replay_component", ["discover", "-s", "research/ssq_dlt_d2_negative_audit/tests", "-v"]),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest():
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted((ROOT/"research").rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
            and p.suffix in {".py", ".md", ".txt", ".ps1", ".xml", ".json", ".lock"}}


def frozen_science():
    binding = json.loads((Path(__file__).parent/"FROZEN_SCIENCE_SHA256.json").read_bytes())
    if (binding["science_plan_sha256"] != "704a2962d68d73624757943ea9f1d9308a08bad49239110b408f5edef6563922"
            or len(binding["files"]) != 49):
        raise ValueError("ORIGINAL_49_SCIENCE_BINDING_REQUIRED")
    mismatches = []
    for name, expected in binding["files"].items():
        path = (ROOT/name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != expected:
            mismatches.append(name)
    return dict(status="PASS" if not mismatches else "FAIL", files=49, mismatches=mismatches)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    before = source_manifest()
    science_before = frozen_science()
    runs = []
    for name, arguments in SPECS:
        command = [sys.executable, "-B", "-m", "unittest", *arguments]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
        log = result.stdout + result.stderr
        (args.output/(name+".log")).write_text(log, encoding="utf-8", newline="\n")
        count_match = re.search(r"Ran (\d+) tests? in", log)
        count = int(count_match[1]) if count_match else 0
        skipped = len(re.findall(r"\.\.\. skipped ", log))
        runs.append(dict(name=name, command=command, exit_code=result.returncode,
                         tests=count, skipped=skipped, status="PASS" if
                         result.returncode == 0 and count > 0 and skipped == 0 else "FAIL"))
    after = source_manifest()
    science_after = frozen_science()
    passed = all(r["status"] == "PASS" for r in runs) and before == after and science_before == science_after
    passed = passed and science_after["status"] == "PASS"
    report = dict(schema="V45_QUARANTINE_ACCEPTANCE_1", status="PASS" if passed else "FAIL",
        recorded_at_local_clock_untrusted=datetime.now(timezone.utc).isoformat(),
        python=sys.version, platform=platform.platform(), suites=runs, tests_run=sum(r["tests"] for r in runs),
        skipped=sum(r["skipped"] for r in runs), source_unchanged=before == after,
        source_manifest_sha256=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(",", ":")).encode()).hexdigest(),
        original_frozen_science=science_after,
        scope="AUDIT_AGENT_CORE_GRAPH_HOST_AND_NEGATIVE_COMPONENT_TESTS_ONLY",
        full_2880_generation_replay="SEPARATE_EXECUTION_NOT_RUN_BY_THIS_SUITE",
        old_real_lottery_holdouts="NOT_READ_OR_REEVALUATED", model_search="NOT_RUN",
        new_challengers_activated=0, scheduled_delivery_trigger="NOT_RUN", full_P0="BLOCKED",
        R2="BLOCKED", formal_A=0, decision="NO_EDGE", repository_independence="FAIL", final_gate="FAIL")
    (args.output/"source_manifest.json").write_text(json.dumps(before,indent=2)+"\n",encoding="utf-8",newline="\n")
    (args.output/"acceptance.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(report))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
