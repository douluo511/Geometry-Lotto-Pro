# test10 Windows delivery/recovery prototype — **NOT INSTALLED / NOT RUN ON USER'S HOST**

Branch-only V4.6 SHADOW handler, not formal eight-slot V4.5, not automatic lottery purchase.

## Preconditions

- Windows 10/11 Task Scheduler, CPython 3.11, repository files reviewed at an exact commit SHA.
- A **non-DST** host timezone such as Singapore Standard Time or Tokyo Standard Time. The installer explicitly BLOCKS hosts observing DST instead of silently promising exact 16:00 JST while converting weekly time triggers.
- An independently supplied **single JSON bundle** with exactly `SSQ` and `DLT` as keys. Each is the #426 `validate_snapshot` schema with verified, locked as-of and cutoff fields; this repository **does not** automatically fetch genuine official histories.
- Two accessible local input snapshots cannot by themselves authorize formal A. For a target already past its cutoff, the handler refuses to backfill even if restarted.
- Absolute paths for root, Python interpreter, bundle, SQLite DB and existing log directory; do not store passwords or private keys in this config.

Example `C:\LottoResearch\v46-windows.json` (replace values with actual reviewed local paths):

```json
{
  "repository_root": "C:/Geometry-Lotto-Pro",
  "python_exe": "C:/Python311/python.exe",
  "snapshot_bundle": "C:/LottoResearch/locked-ssq-dlt.json",
  "database": "C:/LottoResearch/shadow-evidence.sqlite3",
  "log_path": "C:/LottoResearch/logs/v46-shadow-handler.log"
}
```

## Preview, installation, inspection (not executed here)

Run from a reviewed local checkout:

```powershell
# PREVIEW ONLY; no Windows Task Scheduler changes:
.\research\harness_v46\windows_shadow_tasks.ps1 -ConfigFile "C:\LottoResearch\v46-windows.json"

# This modifies YOUR local Task Scheduler; use only after reviewing the source and configs:
.\research\harness_v46\windows_shadow_tasks.ps1 -ConfigFile "C:\LottoResearch\v46-windows.json" -Install

Get-ScheduledTask -TaskName "SSQDLT-V46-SHADOW" | Select-Object -ExpandProperty Triggers
Get-ScheduledTaskInfo -TaskName "SSQDLT-V46-SHADOW"
Get-Content "C:\LottoResearch\logs\v46-shadow-handler.log" -Tail 100
```

The installer declares three trigger types: (a) weekly target for Monday/Wednesday/Saturday **16:00 Japan time**, converted to fixed host-local time, (b) startup, and (c) every-30-minute compensation. Any trigger calls a Python gate: reject before target time, off-day or past sales cutoff; reuse original identical predictions; reject a changed snapshot for an already frozen game+issue. Both lotteries commit in **one SQLite transaction** with strict six-model completeness. Each workflow stage through WAIT is recorded as SHADOW/unverified; REPLAY/SCORE/AUDIT/REPORT/NEXT are not fabricated before official results.

The Task Scheduler API and indefinite repetition behavior **require real-host inspection**. PowerShell parser success, synthetic CI, and preview outputs are **not** proof of installed triggers or a successful restart. A real P0 must include exact local timezone, scheduler trigger XML, cold-boot Event Log, TaskScheduler Operational log, raw handler logs, executable/source SHA256, deliberate offline window, transaction row counts and after-cutoff rejection. Recorded chat time, SQLite SHA and GitHub commit time are **not** external trusted pre-draw time proof.

## Cross-platform synthetic acceptance

```sh
python -m unittest discover -s research/harness_v46/tests -v
```

Synthetic tests exercise 16:00 JST conversion, prewindow WAIT, blocked post-cutoff backfill, exact 30-minute retry, cross-game atomicity and injected DB write failure; Windows CI also parses PowerShell files. This remains **NOT_RUN on real hardware**, official original/source conflict P0, trusted TSA validation and forecast advantage remain BLOCKED.

DLT historical 69/2880 negative-control cause remains unresolved. Formal A=0 and NO_EDGE.
