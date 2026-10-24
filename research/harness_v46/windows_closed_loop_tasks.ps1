# V4.7 SHADOW-only Windows Bot scheduler; preview is the default.
# Install ONLY on a durable and reviewed Windows machine, not GitHub-hosted CI.
param(
    [Parameter(Mandatory=$true)][string]$ConfigFile,
    [switch]$Install,
    [string]$TaskName = 'SSQDLT-V47-CLOSED-LOOP-SHADOW'
)
$ErrorActionPreference = 'Stop'
$ConfigFile = (Resolve-Path -LiteralPath $ConfigFile).Path
$cfg = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($field in @('repository_root', 'python_exe', 'workspace', 'log_path')) {
    if (-not $cfg.$field) { throw "CLOSED_LOOP_CONFIG_FIELD_MISSING:$field" }
}
$repo = (Resolve-Path -LiteralPath $cfg.repository_root).Path
$handler = Join-Path $PSScriptRoot 'invoke_closed_loop.ps1'
if (-not (Test-Path -LiteralPath $handler)) { throw 'CLOSED_LOOP_HANDLER_MISSING' }
Write-Output 'PREVIEW: run SHADOW closed_loop every 30 minutes and at startup'
Write-Output 'BLOCKED IF: no snapshots; caller-unverified outcomes; invalid time or evidence'
Write-Output 'NOT A PRODUCTION FORECAST: no official source/cutoff/TSA approval or persistent-host proof'
if (-not $Install) {
    Write-Output 'NOT_INSTALLED: explicit -Install required on a reviewed durable Windows host'
    return
}
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) { throw "TASK_ALREADY_EXISTS_REFUSING_OVERWRITE:$TaskName" }
$arguments = '-NoProfile -NonInteractive -File "' + $handler + '" -ConfigFile "' + $ConfigFile + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $repo
$startup = New-ScheduledTaskTrigger -AtStartup
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
# Deliberately no -Force: never overwrite V4.6 or other V4.7 tasks.
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($startup, $repeat) -Settings $settings -Description 'V4.7 local SHADOW-only unified prediction/feedback bot' | Out-Null
Write-Output "REGISTERED: $TaskName; physical cold-start and recovery remain NOT_VERIFIED"
