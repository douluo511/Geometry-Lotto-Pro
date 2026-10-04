
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Config = Get-Content (Join-Path $Root "config.json") -Raw | ConvertFrom-Json
$Time = $Config.automation.run_time
$Bat = Join-Path $Root "RUN_DAILY_SILENT.bat"
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Bat`""
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4)
Register-ScheduledTask -TaskName "Stock_AI_Pro_Daily" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Stock AI Pro 自动更新、预测、回测与审计" -Force
Write-Host "完成：工作日 Windows 本地时间 $Time 自动运行。"
Write-Host "如果电脑在日本，默认 17:30；如果在中国，可把 config.json 改为 16:30 后重新运行本脚本。"
