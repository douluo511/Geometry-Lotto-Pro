# V4.7 REA+Harness SHADOW Bot installer. Read-only preview by default.
# Must not install on shared hosts without separate operator approval.
param(
    [Parameter(Mandatory=$true)][string]$ConfigFile,
    [string]$PythonExe = 'python.exe',
    [string]$TaskName = 'SSQDLT-V47-SHADOW-BOT',
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
$configPath = (Resolve-Path -LiteralPath $ConfigFile).Path
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$source = Join-Path $root 'research\harness_v46\shadow_bot.py'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'BOT_RUNNER_NOT_FOUND' }
$payload = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if ($payload.schema -ne 'V47-SHADOW-BOT-CONFIG-1') { throw 'BOT_CONFIG_SCHEMA_INVALID' }
foreach ($key in @('snapshot_bundle','database','receipts_dir')) {
    if (-not $payload.$key) { throw "BOT_CONFIG_MISSING_$key" }
}
if ($TaskName -notmatch '^SSQDLT-V47-SHADOW-BOT(?:-[a-zA-Z0-9_-]+)?$') {
    throw 'BOT_TASK_NAME_NOT_ALLOWED'
}
$resolvedPython = Get-Command $PythonExe -ErrorAction Stop
$pythonPath = $resolvedPython.Source
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'BOT_PYTHON_EXECUTABLE_NOT_FOUND'
}
Write-Output "BOT_PREVIEW: $TaskName"
Write-Output 'CADENCE: once every 30 minutes and at startup (local host clock; untrusted)'
Write-Output "SOURCE: $source"
Write-Output "CONFIG: $configPath"
Write-Output 'AUTHORITY: SHADOW_ONLY, formal A=0, NO_EDGE; no externally trusted preregistration'
Write-Output 'WARNING: operator must independently verify persistent storage, source input, cutoff, PowerShell task exit logs and reboot recovery'
if (-not $Install) {
    Write-Output 'NOT_INSTALLED: requires explicit -Install on a reviewed Windows host'
    return
}
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask) { throw 'BOT_TASK_ALREADY_EXISTS_REFUSING_OVERWRITE' }
# Only user-supplied Python and repository source are invoked. No remote script.
$args = '-m research.harness_v46.shadow_bot --config "' + $configPath + '"'
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $args -WorkingDirectory $root
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 365)
$boot = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
# Deliberately no -Force. The task owner must explicitly renew before day 365.
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($repeat,$boot) -Settings $settings -Description 'Unverified research-only SSQ DLT V4.7 SHADOW bot' | Out-Null
Write-Output "BOT_REGISTERED: $TaskName. Must verify real cold boot/30-minute retries; this printout is not evidence."
