# V4.6 SHADOW task registration. Installation is opt-in; no lottery purchase.
# Requires Windows Task Scheduler cmdlets and a reviewed local config JSON.
param(
    [Parameter(Mandatory=$true)][string]$ConfigFile,
    [switch]$Install,
    [string]$TaskName = 'SSQDLT-V46-SHADOW'
)
$ErrorActionPreference = 'Stop'
$ConfigFile = (Resolve-Path -LiteralPath $ConfigFile).Path
$config = Get-Content -LiteralPath $ConfigFile -Raw | ConvertFrom-Json
foreach ($field in @('repository_root','python_exe','snapshot_bundle','database','log_path')) {
    if (-not $config.$field) { throw "MISSING_CONFIG_$field" }
}
$repoRoot = (Resolve-Path -LiteralPath $config.repository_root).Path
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'research\harness_v46\schedule.py'))) {
    throw 'MISSING_REVIEWED_SCHEDULER_CODE'
}
$localTz = [TimeZoneInfo]::Local
$tokyoTz = [TimeZoneInfo]::FindSystemTimeZoneById('Tokyo Standard Time')
# Weekly time-only triggers drift on DST hosts while JST does not.
if ($localTz.SupportsDaylightSavingTime) { throw 'DST_HOST_REQUIRES_TIMEZONE_AWARE_RECURRENCE_IMPLEMENTATION' }
$jstDates = @(
    [datetime]'2026-11-02T16:00:00',
    [datetime]'2026-11-04T16:00:00',
    [datetime]'2026-11-07T16:00:00'
)
$localDates = @($jstDates | ForEach-Object {
    $utc = [TimeZoneInfo]::ConvertTimeToUtc([DateTime]::SpecifyKind($_,[DateTimeKind]::Unspecified),$tokyoTz)
    [TimeZoneInfo]::ConvertTimeFromUtc($utc,$localTz)
})
$times = @($localDates | ForEach-Object { $_.ToString('HH:mm') } | Select-Object -Unique)
if ($times.Count -ne 1) { throw 'INCONSISTENT_JST_TO_LOCAL_WEEKLY_TIME' }
$weekdayNames = @($localDates | ForEach-Object { $_.DayOfWeek.ToString() })
$scheduledLocal = [datetime]::Today.Add($localDates[0].TimeOfDay)
Write-Output "PREVIEW: JST Mon/Wed/Sat 16:00 => local $($weekdayNames -join '/') $($times[0])"
Write-Output 'RECOVERY: at boot and every 30 minutes; handler rechecks JST weekday, time, as-of and cutoff.'
Write-Output 'STATUS: SHADOW_ONLY, no official admission, no verified external TSA, no boot evidence'
if (-not $Install) { Write-Output 'NOT_INSTALLED: pass -Install on reviewed Windows host'; return }

$handler = Join-Path $PSScriptRoot 'invoke_v46_shadow.ps1'
if (-not (Test-Path -LiteralPath $handler)) { throw 'MISSING_HANDLER' }
$arg = '-NoProfile -NonInteractive -File "' + $handler + '" -ConfigFile "' + $ConfigFile + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory $repoRoot
$weekly = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdayNames -At $scheduledLocal
$atBoot = New-ScheduledTaskTrigger -AtStartup
# A real host must verify indefinite repetition and triggers in Task Scheduler.
$recovery = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($weekly,$atBoot,$recovery) -Settings $settings -Description 'V4.6 SHADOW-only as-of guarded runner' -Force | Out-Null
Write-Output "REGISTERED: $TaskName; inspect actual triggers, raw logs and reboot evidence before acceptance"
