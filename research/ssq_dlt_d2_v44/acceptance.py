"""Reproducible isolated-component acceptance, including actual Windows wrappers.

Use a new output directory. This runner does not certify official draws, produce
live predictions, configure Windows tasks, contact a TSA, or promote formal A.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import sys
import unittest
from pathlib import Path

from .ledger import digest, utc_now
from .runtime import check


def source_manifest():
    root=Path(__file__).resolve().parents[2]
    package=Path(__file__).resolve().parent
    suffixes={".py",".ps1",".bat",".xml",".txt"}
    return {str(path.relative_to(root)).replace("\\","/"):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.rglob("*")) if path.is_file() and path.suffix in suffixes
            and "evidence" not in path.relative_to(package).parts and "__pycache__" not in path.parts}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv)
    args.output.mkdir(parents=True,exist_ok=False)
    package=Path(__file__).resolve().parent
    manifest_before=source_manifest()
    log=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(package/"tests"))
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    clean_log=log.getvalue().replace(str(package.parents[1]),"<REPOSITORY>")
    (args.output/"tests.log").write_text(clean_log,encoding="utf-8")
    # An empty, explicitly isolated research DB. Never import an R1/V4.0 DB.
    status,folder=check(args.output/"research.sqlite3",args.output/"status")
    manifest_after=source_manifest()
    source_unchanged=manifest_before==manifest_after
    report=dict(recorded_at=utc_now(),scope="ISOLATED_COMPONENT_ACCEPTANCE",
                python=platform.python_version(),os=platform.platform(),
                tests=dict(status="PASS" if result.wasSuccessful() else "FAIL",run=result.testsRun,
                           failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
                           skipped_tests=[dict(test=str(test),reason=reason) for test,reason in result.skipped]),
                source_unchanged=source_unchanged,source_manifest_sha256=digest(manifest_after),
                windows_wrapper_tests="PASS" if os.name=="nt" and result.wasSuccessful() and not result.skipped else "NOT_RUN",
                boot_task_install="BLOCKED",real_reboot="NOT_RUN",elapsed_30_minute_trigger="NOT_RUN",
                empty_runtime_status=status["status"],prediction_calls=status["prediction_calls"],
                R2="BLOCKED",formal_A=0,decision="NO_EDGE",repository_independence="FAIL",final_gate="FAIL")
    (args.output/"source_manifest.json").write_text(json.dumps(manifest_after,indent=2),encoding="utf-8")
    (args.output/"acceptance.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
    return 0 if result.wasSuccessful() and source_unchanged else 1


if __name__=="__main__":
    raise SystemExit(main())
