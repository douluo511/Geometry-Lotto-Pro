# Windows Task Scheduler handler: logs actual invocation, but never self-certifies time.
param([Parameter(Mandatory=$true)][string]$ConfigFile)
$ErrorActionPreference = 'Stop'
$cfg = Get-Content -LiteralPath $ConfigFile -Raw | ConvertFrom-Json
foreach ($key in @('repository_root','python_exe','snapshot_bundle','database','log_path')) {
    if (-not $cfg.$key) { throw "MISSING_CONFIG_$key" }
}
$root = (Resolve-Path -LiteralPath $cfg.repository_root).Path
Set-Location -LiteralPath $root
$stamp = [DateTimeOffset]::UtcNow.ToString('o')
$logdir = Split-Path -Parent $cfg.log_path
if (-not (Test-Path -LiteralPath $logdir)) { throw 'PRECREATED_LOG_DIRECTORY_REQUIRED' }
"[$stamp] V46-SHADOW actual handler invocation (local time is not trusted)" | Out-File -FilePath $cfg.log_path -Encoding utf8 -Append
# The Python module itself prevents off-schedule, changed RUN_ID and post-cutoff writes.
$output = & $cfg.python_exe -m research.harness_v46.schedule --snapshot-bundle $cfg.snapshot_bundle --database $cfg.database 2>&1
$code = $LASTEXITCODE
$output | Out-String | Out-File -FilePath $cfg.log_path -Encoding utf8 -Append
"[exit_code=$code] local receipt only, formal_A=0" | Out-File -FilePath $cfg.log_path -Encoding utf8 -Append
if ($code -ne 0) { throw 'V46_SHADOW_COMPENSATION_RUN_FAILED' }
