"""Separate component tests, real process scenarios and their scope limits."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

from .harness import sources_manifest, write, file_sha, REPO, execute
from .verify import verify

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();out=args.output
    if not out.is_absolute(): raise ValueError('ABSOLUTE_OUTPUT_REQUIRED')
    out=out.resolve()
    if out.is_relative_to(REPO) or REPO.is_relative_to(out): raise ValueError('SEPARATE_SOURCE_AND_OUTPUT_REQUIRED')
    out.mkdir(parents=True,exist_ok=False)
    before=sources_manifest();write(out/'source-manifest.json',before)
    command=[sys.executable,'-m','unittest','discover','-s','research/ssq_dlt_process_faults/tests','-v']
    started=datetime.now(timezone.utc).isoformat()
    try:
        result=subprocess.run(command,cwd=REPO,capture_output=True,timeout=120)
        stdout,stderr,code,timed_out=result.stdout,result.stderr,result.returncode,False
    except subprocess.TimeoutExpired as error:
        stdout,stderr,code,timed_out=error.stdout or b'',error.stderr or b'',None,True
    (out/'tests.stdout').write_bytes(stdout);(out/'tests.stderr').write_bytes(stderr)
    count=re.search(rb'Ran (\d+) tests? in',stdout+stderr)
    tests_run=int(count[1]) if count else 0
    skips=len(re.findall(rb'\.\.\. skipped ',stdout+stderr))
    write(out/'tests-command.json',dict(argv=command,exit_code=code,timed_out=timed_out,started_at_local=started,
          finished_at_local=datetime.now(timezone.utc).isoformat(),stdout_sha256=file_sha(out/'tests.stdout'),stderr_sha256=file_sha(out/'tests.stderr')))
    scenarios=execute(out/'process-scenarios') if code==0 and tests_run>0 and skips==0 else None
    verification=verify(out/'process-scenarios') if scenarios else None
    unchanged=before==sources_manifest()
    complete=(code==0 and tests_run>0 and skips==0 and scenarios and scenarios['status']=='DIAGNOSTIC_COMPLETE_WITH_BASELINE_FAIL'
              and scenarios['all_registered_cases_run'] and unchanged)
    receipt=dict(status='PASS_REPAIR_AND_DIAGNOSTIC_EXECUTION_ONLY' if complete else 'FAIL_OR_INCOMPLETE',
          unit_test_exit_code=code,unit_tests_run=tests_run,unit_skips=skips,unit_timed_out=timed_out,
          process_case_count=len(scenarios['cases']) if scenarios else 0,
          original_workflow_status='FAIL_BASELINE_MAPPING' if scenarios and scenarios['baseline_failure_preserved'] else 'NOT_ESTABLISHED',
          repaired_workflow_status=next((x['status'] for x in scenarios['cases'] if x['case']=='R04'),'NOT_RUN') if scenarios else 'NOT_RUN',
          source_unchanged=unchanged,source_manifest_sha256=file_sha(out/'source-manifest.json'),verification=verification,
          real_scheduler='NOT_RUN',physical_power_test='NOT_RUN',real_inbox_delivery='NOT_RUN',formal_A=0,decision='NO_EDGE',qualified_prospective_samples=0)
    write(out/'receipt.json',receipt);print(json.dumps(receipt))
    return 0 if complete else 1

if __name__=='__main__': raise SystemExit(main())
