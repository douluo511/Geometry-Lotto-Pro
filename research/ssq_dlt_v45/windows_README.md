# V4.5 local Windows scheduling and optional Compose

The scheduler invokes one bounded check through `python -m research.ssq_dlt_v45.runtime --config ABSOLUTE_JSON`. The runtime determines the latest due slot in fixed Japan time, writes the SQLite ledger and reports, and performs bounded delivery retries. A launcher success only means the process completed; it does not mean official admission, legal next-issue verification, trustworthy pre-draw sealing, or a predictive edge passed. Formal A remains 0 and the conclusion remains NO_EDGE.

## Schedule

One new task contains three trigger types:

* Boot, with a 30 second delay.
* Monday, Wednesday and Saturday at 07:00 UTC, which is 16:00 JST throughout the year. The UTC boundary avoids dependence on the Windows host's time zone or daylight saving time.
* A repeating 30 minute check, starting one minute after XML export. `StartWhenAvailable` also requests catch-up after an unavailable trigger. This bounds detection after the computer is running and the Scheduler is healthy; it cannot run while power is off.

`IgnoreNew` prevents overlap within this task. The runtime's immutable key/transaction rules handle overlapping manual checks and restarts. The Scheduler retries a nonzero process three times at one minute intervals, runs without requiring a network, and limits a task to ten minutes. Both the action and Python child use hidden windows. A failed process keeps its real exit code, its separate stdout/stderr logs, and a unique JSON receipt with SHA256 hashes.

## Export and read-only probe

Run from the repository root in Windows PowerShell, using absolute paths. The JSON configuration must already exist. Replace these paths with the actual local configuration and interpreter; the export destination's parent must exist.

```powershell
$repo = (Resolve-Path '.').Path
$python = 'C:\Path\To\python.exe'
$config = 'C:\Path\To\runtime.json'
$logs = 'C:\Path\To\v45-launcher-logs'
$xml = 'C:\Path\To\v45-task-review.xml'
& "$repo\research\ssq_dlt_v45\windows\Install-Tasks.ps1" -PythonPath $python -RepositoryPath $repo -ConfigPath $config -LauncherLogDirectory $logs -ExportXmlPath $xml
& "$repo\research\ssq_dlt_v45\windows\Probe-Scheduler.ps1" -EvidencePath 'C:\Path\To\new-scheduler-probe.json'
```

The default export performs no runtime call and no task registration. Existing XML or evidence files are rejected, not overwritten. Paths must be absolute local Windows paths, without quotes or control characters. Python must be an existing executable reporting Python 3.11 or later. The task name is restricted to the new `GLP-SsqDltV45-` prefix. A probe queries both Scheduler COM and the ScheduledTasks CIM interface and never registers, starts or removes a task.

To check the actual runtime manually with the same hidden wrapper:

```powershell
& "$repo\research\ssq_dlt_v45\windows\Invoke-Runtime.ps1" -PythonPath $python -RepositoryPath $repo -ConfigPath $config -LauncherLogDirectory $logs
```

The config may enable delivery only when an intended recipient and delivery credentials are authorized and configured. The launcher itself does not infer an address or contact anyone.

## Durable installation

Installation is explicit through `-Install`. It requires an elevated administrator because the boot principal is LocalSystem, and a local integration receipt bound to the current runtime and config bytes:

```json
{
  "status": "PASS",
  "runtime_integration": "PASS",
  "runtime_sha256": "sha256 of research/ssq_dlt_v45/runtime.py after integration passes",
  "config_sha256": "sha256 of the actual deployed runtime.json"
}
```

This receipt is a local deployment check, not any of the scientific 01/02/03/04 approvals or a trusted timestamp. Produce it from the actual successful integration run. Changing runtime or config invalidates the check. The rest of the source/model/evidence acceptance remains governed by `PORTFOLIO_GOVERNANCE.md`.

```powershell
& "$repo\research\ssq_dlt_v45\windows\Install-Tasks.ps1" -PythonPath $python -RepositoryPath $repo -ConfigPath $config -LauncherLogDirectory $logs -ExportXmlPath 'C:\Path\To\new-install-review.xml' -RuntimeAcceptancePath 'C:\Path\To\integration-receipt.json' -Install
```

The installer refuses a task with an existing name. Before durable registration, it creates a uniquely named temporary task without triggers, runs the exact action once under LocalSystem, checks its exit code with a 45 second bound, and removes the temporary task. A failed access/runtime smoke prevents durable registration. A cleanup error also stops installation. No `-Force` replacement is used. Changes to an already installed task require a new reviewed name/config and a separate deliberate retirement of the old task. Do not run two durable schedulers against the same state directory as a routine deployment.

The runtime can return nonzero when official sources are blocked. For a real deployment the LocalSystem smoke must succeed with the intended configuration, ACLs, source access, and local report path. A user-session test alone cannot prove LocalSystem access to a user-local Python executable or data folder.

## Optional Docker Compose

Docker is an optional local supervisor, not a cloud migration. Do not start it alongside the Windows task as the normal deployment. Use absolute container paths in a separate `runtime.json`: history files under `/config` and writable state under `/data`. Bind-mounted history remains read-only. Prepare `/data` for UID/GID 10001 before starting. No credentials are included in the image.

```powershell
$env:V45_CONFIG_DIRECTORY = 'C:\Path\To\container-config-and-history'
$env:V45_DATA_DIRECTORY = 'C:\Path\To\container-state'
docker compose -f research/ssq_dlt_v45/compose.yaml --profile local-runtime config
docker compose -f research/ssq_dlt_v45/compose.yaml --profile local-runtime up --build -d
```

The container uses the same CLI immediately at start and each UTC half hour; the runtime decides whether publication is due in JST. A failed check retries three times at one minute intervals, and each child has a ten minute timeout. Compose restarts the supervisor after container restart, with a read-only image, no Linux capabilities and a bounded Docker log. Runtime report/state files remain in the mounted directory. Graceful termination signals the child; SQLite recovery and deduplication are still required on abrupt termination.

## What has and has not been tested

`python -m unittest research.ssq_dlt_v45.tests.test_windows -v` runs policy checks and, on Windows, actual PowerShell parser/export/launcher checks. Its launcher fixture is deliberately synthetic; it proves argument handling, SHA receipts, stream capture, unique logs and nonzero propagation. It does not substitute for integration of the real research runtime.

The current restricted Windows session produced all ten test PASS results and PowerShell syntax PASS. Its read-only Scheduler probe returned COM `BLOCKED` (`0x80070003`, path not found), CIM `BLOCKED` (access denied), and administrator false. Therefore durable registration is BLOCKED in this session. Real startup, thirty minutes of elapsed triggering, actual network disconnection and a physical power cycle are NOT_RUN. Docker/Compose execution is NOT_RUN because this session has no Docker executable. Never relabel these as PASS from static XML or synthetic process tests.

Machine-readable probe, commands, test output and SHA evidence are collected separately by the current run. Repository independence remains FAIL in this shared repository, so this work is not a portfolio FINAL release.
