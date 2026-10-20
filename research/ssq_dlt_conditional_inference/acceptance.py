"""Record tests of the two isolated toolkits; never run lottery models."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import platform
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NAMESPACES = ("research/ssq_dlt_conditional_inference", "research/ssq_dlt_time_probe")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out == REPO or REPO in out.parents:
        raise SystemExit("Evidence output must be outside the source checkout")
    out.mkdir(parents=True, exist_ok=False)
    source = sorted(p for namespace in NAMESPACES for p in (REPO / namespace).rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts)
    source.append(REPO / ".github/workflows/ssq-dlt-time-inference.yml")
    manifest = {p.relative_to(REPO).as_posix(): digest(p) for p in source}
    (out / "source-manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    started = datetime.now(timezone.utc).isoformat()
    suite = unittest.TestSuite()
    for namespace in NAMESPACES:
        suite.addTests(unittest.defaultTestLoader.discover(str(REPO / namespace / "tests"),
                       top_level_dir=str(REPO)))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    log = stream.getvalue()
    (out / "tests.log").write_text(log, encoding="utf-8", newline="\n")
    unchanged = manifest == {p.relative_to(REPO).as_posix(): digest(p) for p in source}
    status = "FAIL" if not result.wasSuccessful() or not unchanged or result.testsRun == 0 else ("NOT_RUN" if result.skipped else "PASS")
    receipt = dict(schema="v45-time-inference-acceptance-v1", status=status,
                   started_at_local=started, finished_at_local=datetime.now(timezone.utc).isoformat(),
                   python=sys.version, platform=platform.platform(), tests_run=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), skips=len(result.skipped),
                   sources_unchanged=unchanged, source_manifest_sha256=digest(out / "source-manifest.json"),
                   tests_log_sha256=digest(out / "tests.log"),
                   scope="SYNTHETIC_COMPONENT_TESTS_ONLY", live_timestamp_request="NOT_RUN_BY_THIS_RUNNER",
                   real_p0_system_acceptance="NOT_RUN", registered_trial=False, A=0, verdict="NO_EDGE", prospective=0)
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

