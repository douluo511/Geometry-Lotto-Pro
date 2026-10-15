# PowerShell diagnostic only: no durable task, boot, prediction, or network.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$RepositoryPath,
    [Parameter(Mandatory = $true)][string]$WorkDirectory,
    [Parameter(Mandatory = $true)][string]$EvidencePath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$report = [ordered]@{
    checked_at_utc = [DateTime]::UtcNow.ToString('o')
    scope = 'Local Windows diagnostics only; no reboot and no durable task installation'
    powershell_version = $PSVersionTable.PSVersion.ToString()
    syntax = @(); dry_export = 'NOT_RUN'; scheduler_query = 'NOT_RUN'
    temporary_task = 'NOT_RUN'; temporary_execution = 'NOT_RUN'; temporary_cleanup = 'NOT_RUN'
    real_boot = 'NOT_RUN'; thirty_minute_elapsed_trigger = 'NOT_RUN'
    Windows10_reboot = 'NOT_RUN'; Windows11_reboot = 'NOT_RUN'
    durable_task_installed = $false; R2 = 'BLOCKED'; formal_A = 0; decision = 'NO_EDGE'
    P0_09 = 'BLOCKED'
    errors = @()
}
$taskName = 'GLP-V44-Smoke-' + [Guid]::NewGuid().ToString('N')
$registered = $false
try {
    foreach ($value in @($PythonPath, $RepositoryPath, $WorkDirectory, $EvidencePath)) {
        if ($value -notmatch '^[A-Za-z]:[\\/]' -or $value -match '[\x00-\x1f"]') { throw 'Absolute Windows paths required.' }
    }
    if (-not (Test-Path -LiteralPath $WorkDirectory -PathType Container)) { throw 'WorkDirectory must already exist.' }
    if (Test-Path -LiteralPath $EvidencePath) { throw 'EvidencePath already exists; refusing to overwrite.' }
    foreach ($name in @('Install-StatusTask.ps1', 'Invoke-Status.ps1', 'Probe-StatusTask.ps1')) {
        $tokens = $null; $parseErrors = $null
        [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name), [ref]$tokens, [ref]$parseErrors) | Out-Null
        $report.syntax += [ordered]@{ file = $name; status = $(if (@($parseErrors).Count -eq 0) { 'PASS' } else { 'FAIL' }); errors = @($parseErrors).Count }
    }
    $windowsVersion = & $PythonPath -I -c 'import json,sys; v=sys.getwindowsversion(); print(json.dumps(dict(major=v.major,minor=v.minor,build=v.build,platform=v.platform)))'
    if ($LASTEXITCODE -eq 0) { $report.os = $windowsVersion | ConvertFrom-Json }
    $xmlPath = Join-Path $WorkDirectory ('export-' + [Guid]::NewGuid().ToString('N') + '.xml')
    $dbPath = Join-Path $WorkDirectory 'smoke-ledger.sqlite'
    $outputPath = Join-Path $WorkDirectory 'status-output'
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $exportResult = & $powershell -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Install-StatusTask.ps1') -PythonPath $PythonPath -RepositoryPath $RepositoryPath -DatabasePath $dbPath -OutputDirectory $outputPath -ExportXmlPath $xmlPath
    $report.dry_export_exit_code = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) { throw 'Dry XML export failed.' }
    $report.dry_export = 'PASS'
    $report.dry_export_receipt = $exportResult | ConvertFrom-Json
    $report.dry_export_created_no_db = -not (Test-Path -LiteralPath $dbPath)
    $report.dry_export_created_no_status = -not (Test-Path -LiteralPath $outputPath)
    $xml = New-Object Xml.XmlDocument
    $xml.Load($xmlPath)
    Import-Module ScheduledTasks -ErrorAction Stop
    try {
        Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Out-Null
        $report.scheduler_query = 'PASS'
    }
    catch {
        $report.scheduler_query = 'BLOCKED'
        $report.errors += [ordered]@{ step='scheduler_query'; type=$_.Exception.GetType().FullName; hresult=$_.Exception.HResult; message=$_.Exception.Message }
    }
    # Same exported action, current interactive account, no boot or time trigger.
    # A random task name plus no -Force prevents replacing any existing task.
    $ns = New-Object Xml.XmlNamespaceManager($xml.NameTable)
    $ns.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
    $xml.SelectSingleNode('/t:Task/t:Triggers', $ns).RemoveAll()
    $xml.SelectSingleNode('/t:Task/t:Principals/t:Principal/t:UserId', $ns).InnerText = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $xml.SelectSingleNode('/t:Task/t:Principals/t:Principal/t:LogonType', $ns).InnerText = 'InteractiveToken'
    try {
        Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Xml $xml.OuterXml -ErrorAction Stop | Out-Null
        $registered = $true; $report.temporary_task = 'PASS'
        Start-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction Stop
        $deadline = [DateTime]::UtcNow.AddSeconds(45)
        do {
            Start-Sleep -Milliseconds 500
            $task = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction Stop
            $info = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath '\' -ErrorAction Stop
            $hasRun = $info.LastRunTime.Year -gt 2000
        } while ((-not $hasRun -or $task.State -eq 'Running') -and [DateTime]::UtcNow -lt $deadline)
        $report.temporary_exit_code = $info.LastTaskResult
        $report.temporary_execution = $(if ($hasRun -and $task.State -ne 'Running' -and $info.LastTaskResult -eq 0) { 'PASS' } else { 'FAIL' })
    }
    catch {
        $report.temporary_task = $(if ($registered) { 'PASS' } else { 'BLOCKED' })
        $report.temporary_execution = 'BLOCKED'
        $report.errors += [ordered]@{ step='temporary_scheduler_task'; type=$_.Exception.GetType().FullName; hresult=$_.Exception.HResult; message=$_.Exception.Message }
    }
}
catch {
    $report.errors += [ordered]@{ step='diagnostic'; type=$_.Exception.GetType().FullName; hresult=$_.Exception.HResult }
}
finally {
    if ($registered) {
        try {
            Stop-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false -ErrorAction Stop
            $report.temporary_cleanup = 'PASS'
        }
        catch {
            $report.temporary_cleanup = 'FAIL'
            $report.errors += [ordered]@{ step='temporary_cleanup'; type=$_.Exception.GetType().FullName; hresult=$_.Exception.HResult }
        }
    }
    else { $report.temporary_cleanup = 'NOT_RUN' }
    $json = $report | ConvertTo-Json -Depth 8
    $stream = [IO.File]::Open($EvidencePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes($json); $stream.Write($bytes, 0, $bytes.Length) }
    finally { $stream.Dispose() }
    $json
}
