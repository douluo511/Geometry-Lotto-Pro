# Windows local status runner — research only

`Invoke-Status.ps1` makes exactly one Python call:

```text
python -m research.ssq_dlt_d2_v44.runtime --db ABSOLUTE_DATABASE --output ABSOLUTE_DIRECTORY
```

This replays committed ledger data, creates an exclusive per-run JSON/CSV/HTML
directory and appends a separate heartbeat. It does not create predictions,
fetch sources, change registrations or admit a model. A successful process exit
means the bounded status check ran; admission remains **R2 BLOCKED, formal A=0,
NO_EDGE**. On failure the wrapper returns a nonzero code and attempts to write
an exclusive `launcher-failures/<uuid>.json`; inability to write that diagnostic
does not turn failure into success.

## Export and review before installation

Use a local, trusted Python >=3.10 executable and an unchanged, approved
checkout. These example paths must be replaced with the actual local paths;
the XML parent directory must already exist.

```powershell
.\research\ssq_dlt_d2_v44\windows\Install-StatusTask.ps1 `
  -PythonPath 'C:\Python311\python.exe' `
  -RepositoryPath 'C:\GLP\Geometry-Lotto-Pro' `
  -DatabasePath 'C:\GLP\state\ledger.sqlite' `
  -OutputDirectory 'C:\GLP\state\status' `
  -ExportXmlPath 'C:\GLP\review\status-task.xml'
```

The default only exports XML. It validates absolute local paths, the approved
runtime file, Python identity/version and Windows PowerShell availability. It
does not initialize the database, run a status check or register a task. Both
XML export and task registration refuse to overwrite an existing item.
`status-task.bat` forwards the same explicit arguments to Windows PowerShell.

The XML defines a boot trigger with a 30-second delay and an indefinite PT30M
time trigger. `IgnoreNew` prevents overlapping scheduled instances. Failed
actions retry at most three times at one-minute intervals; each action has a
five-minute time limit. The action runs Windows PowerShell with `-NoProfile`,
`-NonInteractive`, `-WindowStyle Hidden` and an absolute working directory.
Its status check does not depend on network availability.

## Installation requirements and limits

Adding `-Install` requests a durable boot task as **LocalSystem**, which requires
an elevated administrator. The installer first rejects an existing task name,
then registers and runs a temporary LocalSystem task with the exact same
action and removes it. Only a zero result within 45 seconds permits the
durable registration. A user-local Python installation, checkout or database
may be inaccessible to LocalSystem: a failed access probe blocks installation
and must be diagnosed; do not assume another account has the same access.

The access probe performs an ordinary local status check and therefore may
append one heartbeat and one output directory. It does not prove a boot or a
30-minute timer fired. Scheduler errors and nonzero runtime results propagate.
Scheduled task history and `launcher-failures` are diagnostics, never evidence
of predictive edge or formal admission. No durable task was installed during
this implementation session.

## Reproduce the safe local diagnostic

Create an empty local work directory, then run:

```powershell
.\research\ssq_dlt_d2_v44\windows\Probe-StatusTask.ps1 `
  -PythonPath 'C:\Python311\python.exe' `
  -RepositoryPath 'C:\GLP\Geometry-Lotto-Pro' `
  -WorkDirectory 'C:\GLP\probe-work' `
  -EvidencePath 'C:\GLP\review\scheduler-probe.json'
```

This exports XML and, when access permits, registers a random temporary task
under the current interactive account with no time or boot trigger, runs it
once and removes it. The JSON records each actual result and leaves real
reboot and elapsed-30-minute tests NOT_RUN. It does not install the durable
boot task. Its process exit only indicates that a diagnostic report was
written; inspect the report's individual PASS/FAIL/BLOCKED/NOT_RUN fields.

`evidence/scheduler-probe-final.json` records the actual implementation host:
Windows kernel 10.0 build 19045 and Windows PowerShell 5.1.19041.6456. Syntax
and dry export passed. Scheduler querying and temporary registration were
BLOCKED by CIM access denial, so no scheduled execution occurred. Real
Windows 10/11 reboot, a genuine 30-minute trigger, scheduled retry behavior,
power interruption and offline startup remain **NOT_RUN**. **P0-09 remains
BLOCKED**. A task XML parser test cannot replace these machine tests.

The wrapper tests run with:

```text
python -m unittest research.ssq_dlt_d2_v44.tests.test_windows -v
```

On non-Windows hosts only the portable XML policy check runs; actual wrapper
checks are explicitly skipped. Those skips cannot count as Windows PASS.
