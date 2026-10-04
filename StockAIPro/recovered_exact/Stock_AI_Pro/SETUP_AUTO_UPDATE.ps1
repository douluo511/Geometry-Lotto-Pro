$ErrorActionPreference="Stop"
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$Current=Get-Content (Join-Path $Root "current.json") -Raw | ConvertFrom-Json
$ConfigPath=Join-Path $Root ("versions\"+$Current.active_version+"\config.json")
$Config=Get-Content $ConfigPath -Raw | ConvertFrom-Json
$Time=$Config.automation.run_time
$Bat=Join-Path $Root "RUN_DAILY_SILENT.bat"
$Action=New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Bat`""
$Trigger=New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time
$Settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4)
Register-ScheduledTask -TaskName "Stock_AI_Pro_Daily" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Stock AI Pro 数据更新、预测、回测、审计与软件更新检查" -Force
Write-Host "完成：工作日 Windows 本地时间 $Time 自动运行。" -ForegroundColor Green
