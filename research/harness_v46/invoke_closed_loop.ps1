# V4.7 SHADOW local Bot invocation; DOES NOT authenticate sources or TSA.
# This script has no auto-install / ticket purchase / model-promotion side effects.
param([Parameter(Mandatory=$true)][string]$ConfigFile)
$ErrorActionPreference = 'Stop'
$cfg = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($field in @('repository_root', 'python_exe', 'workspace', 'log_path')) {
    if (-not $cfg.$field) { throw "CLOSED_LOOP_CONFIG_FIELD_MISSING:$field" }
}
$repo = (Resolve-Path -LiteralPath $cfg.repository_root).Path
if (-not (Test-Path -LiteralPath (Join-Path $repo 'research\harness_v46\closed_loop.py'))) {
    throw 'CLOSED_LOOP_MODULE_MISSING'
}
$logDir = Split-Path -Parent $cfg.log_path
if (-not (Test-Path -LiteralPath $logDir -PathType Container)) {
    throw 'CLOSED_LOOP_LOG_DIR_NOT_PRECREATED'
}
Set-Location -LiteralPath $repo
$argv = @('-m', 'research.harness_v46.closed_loop', '--workspace', [string]$cfg.workspace)
if ($cfg.snapshot_bundle) {
    $argv += @('--snapshot-bundle', [string]$cfg.snapshot_bundle)
}
if ($cfg.research_history_bundle) {
    $argv += @('--research-history-bundle', [string]$cfg.research_history_bundle)
}
$stamp = [DateTimeOffset]::UtcNow.ToString('o')
"[$stamp] V47 SHADOW closed_loop tick, local clock NOT independently trusted" |
    Out-File -LiteralPath $cfg.log_path -Encoding utf8 -Append
$output = & $cfg.python_exe @argv 2>&1
$code = $LASTEXITCODE
$output | Out-String | Out-File -LiteralPath $cfg.log_path -Encoding utf8 -Append
"[exit_code=$code] A=0 NO_EDGE; research evidence only" |
    Out-File -LiteralPath $cfg.log_path -Encoding utf8 -Append
if ($code -ne 0) { throw "CLOSED_LOOP_TICK_BLOCKED:$code" }
