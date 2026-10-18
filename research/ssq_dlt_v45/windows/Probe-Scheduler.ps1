# Read-only diagnostics. This script never registers, starts or deletes a task.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$EvidencePath)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
$evidenceResolved = Get-AbsoluteLocalPath $EvidencePath 'EvidencePath'
$report = [ordered]@{
    checked_at_utc=[DateTime]::UtcNow.ToString('o'); powershell_version=$PSVersionTable.PSVersion.ToString()
    scope='Read-only Scheduler COM and CIM diagnostics; no task mutation'
    syntax=@(); scheduler_com='NOT_RUN'; scheduler_cim='NOT_RUN'; administrator=$false
    durable_install='NOT_RUN'; real_boot='NOT_RUN'; thirty_minute_elapsed_trigger='NOT_RUN'
    disconnected_network='NOT_RUN'; power_cycle='NOT_RUN'; errors=@(); formal_A=0; conclusion='NO_EDGE'
}
foreach ($name in @('Common.ps1','Install-Tasks.ps1','Invoke-Runtime.ps1','Probe-Scheduler.ps1')) {
    $tokens=$null; $parseErrors=$null
    $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name), [ref]$tokens, [ref]$parseErrors)
    $report.syntax += [ordered]@{file=$name; status=$(if (@($parseErrors).Count -eq 0) { 'PASS' } else { 'FAIL' }); error_count=@($parseErrors).Count}
}
try {
    $principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $report.administrator=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { $report.errors += [ordered]@{step='identity'; message=$_.Exception.Message} }
$service=$null
try {
    $service=New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $null=$service.GetFolder('\').GetTasks(0).Count
    $report.scheduler_com='PASS'
} catch { $report.scheduler_com='BLOCKED'; $report.errors += [ordered]@{step='scheduler_com'; hresult=$_.Exception.HResult; message=$_.Exception.Message} }
finally { if ($null -ne $service -and [Runtime.InteropServices.Marshal]::IsComObject($service)) { $null=[Runtime.InteropServices.Marshal]::ReleaseComObject($service) } }
try {
    Import-Module ScheduledTasks -ErrorAction Stop
    $null = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop).Count
    $report.scheduler_cim='PASS'
} catch { $report.scheduler_cim='BLOCKED'; $report.errors += [ordered]@{step='scheduler_cim'; hresult=$_.Exception.HResult; message=$_.Exception.Message} }
$report.status = $(if ($report.scheduler_com -eq 'PASS' -and $report.scheduler_cim -eq 'PASS') { 'PASS' } else { 'BLOCKED' })
$json=$report | ConvertTo-Json -Depth 8
Write-NewUtf8File $evidenceResolved $json
$json
