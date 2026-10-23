# V4.7 separate research Bot task installer. Dry-run by default.
# DOES NOT deploy, enable, or claim an unattended service without -Install.
param(
    [Parameter(Mandatory=$true)][string]$ConfigFile,
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [switch]$Install,
    [string]$TaskName = 'SSQDLT-V47-SHADOW-BOT'
)
$ErrorActionPreference = 'Stop'
$ConfigFile = (Resolve-Path -LiteralPath $ConfigFile).Path
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
$RepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw 'BOT_REQUIRES_REVIEWED_PYTHON_EXE'
}
$modulePath = Join-Path $RepositoryRoot 'research\harness_v46\shadow_bot.py'
if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
    throw 'BOT_EXECUTABLE_CODE_MISSING'
}
$config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($config.schema -ne 'V47-SHADOW-BOT-CONFIG-1') {
    throw 'BOT_CONFIG_SCHEMA_INVALID'
}
$configFolder = Split-Path -Parent $ConfigFile
foreach ($field in @('snapshot_bundle','database','receipts_dir')) {
    if (-not $config.$field) { throw "BOT_CONFIG_REQUIRED_FIELD_MISSING:$field" }
}
$receiptsDir = if ([IO.Path]::IsPathRooted($config.receipts_dir)) {
    $config.receipts_dir
} else {
    Join-Path $configFolder $config.receipts_dir
}
if (-not (Test-Path -LiteralPath $receiptsDir -PathType Container)) {
    throw 'BOT_RECEIPTS_DIRECTORY_MUST_PREEXIST'
}
$snapshotPath = if ([IO.Path]::IsPathRooted($config.snapshot_bundle)) {
    $config.snapshot_bundle
} else {
    Join-Path $configFolder $config.snapshot_bundle
}
if (-not (Test-Path -LiteralPath $snapshotPath -PathType Leaf)) {
    throw 'BOT_SNAPSHOT_BUNDLE_MUST_PREEXIST'
}
$handler = Join-Path $PSScriptRoot 'invoke_v47_shadow_bot.ps1'
if (-not (Test-Path -LiteralPath $handler -PathType Leaf)) {
    throw 'BOT_TASK_HANDLER_MISSING'
}
if ($TaskName -ne 'SSQDLT-V47-SHADOW-BOT') {
    throw 'BOT_TASK_NAME_MUST_USE_ISOLATED_V47_ID'
}
Write-Output 'PREVIEW: research Bot invokes one local SHADOW tick every 30 minutes and at host startup.'
Write-Output 'PREVIEW: model forecasts before local cutoff; waits for caller-supplied result; scores original frozen rows only.'
Write-Output 'PREVIEW: user must independently supply valid official-source inputs and audit persistent local data.'
Write-Output 'PREVIEW: no proof of trusted pre-draw timestamps, official results, D2 advantage or unattended host recovery.'
Write-Output 'PREVIEW: formal_A=0, NO_EDGE, no lottery purchase.'
if (-not $Install) {
    Write-Output 'NOT_INSTALLED: review config and pass -Install explicitly on the intended Windows host'
    return
}
# Do not overwrite the legacy V4.7 schedule task or any unrelated task.
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    throw "TASK_ALREADY_EXISTS_REFUSING_OVERWRITE:$TaskName"
}
# All paths are quoted; no powershell.exe -Command interpolation of user inputs.
$arg = '-NoProfile -NonInteractive -File "' + $handler +
       '" -ConfigFile "' + $ConfigFile +
       '" -PythonExe "' + $PythonExe +
       '" -RepositoryRoot "' + $RepositoryRoot + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory $RepositoryRoot
$atStartup = New-ScheduledTaskTrigger -AtStartup
$recurring = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
# No -Force. Scheduling is explicitly opt-in and requires adequate host rights.
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($atStartup,$recurring) -Settings $settings -Description 'V4.7 SSQ/DLT SHADOW Bot: research-only, formal A=0, NO_EDGE' | Out-Null
Write-Output "REGISTERED: $TaskName; VERIFY with Task Scheduler and real boot/30-minute recovery tests"
