[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$RepositoryPath,
    [Parameter(Mandatory = $true)][string]$ConfigPath,
    [Parameter(Mandatory = $true)][string]$LauncherLogDirectory,
    [Parameter(Mandatory = $true)][string]$ExportXmlPath,
    [ValidatePattern('^GLP-SsqDltV45-[A-Za-z0-9_.-]{1,60}$')][string]$TaskName='GLP-SsqDltV45-Local',
    [string]$RuntimeAcceptancePath,
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
try {
    $pythonResolved = Get-AbsoluteLocalPath $PythonPath 'PythonPath'
    $repositoryResolved = Get-AbsoluteLocalPath $RepositoryPath 'RepositoryPath'
    $configResolved = Get-AbsoluteLocalPath $ConfigPath 'ConfigPath'
    $logResolved = Get-AbsoluteLocalPath $LauncherLogDirectory 'LauncherLogDirectory'
    $exportResolved = Get-AbsoluteLocalPath $ExportXmlPath 'ExportXmlPath'
    Assert-DeploymentPaths $pythonResolved $repositoryResolved $configResolved
    $runner = Join-Path $repositoryResolved 'research\ssq_dlt_v45\windows\Invoke-Runtime.ps1'
    if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw 'Runtime wrapper is missing.' }
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) { throw 'Windows PowerShell is missing.' }
    $arguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File ' + (Quote-NativeArgument $runner) +
        ' -PythonPath ' + (Quote-NativeArgument $pythonResolved) + ' -RepositoryPath ' + (Quote-NativeArgument $repositoryResolved) +
        ' -ConfigPath ' + (Quote-NativeArgument $configResolved) + ' -LauncherLogDirectory ' + (Quote-NativeArgument $logResolved)
    $xmlText = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'task-template.xml'))
    $xmlText = $xmlText.Replace('__CATCHUP_START__', [DateTime]::UtcNow.AddMinutes(1).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"))
    $xmlText = $xmlText.Replace('__POWERSHELL_PATH__', [Security.SecurityElement]::Escape($powershell))
    $xmlText = $xmlText.Replace('__ARGUMENTS__', [Security.SecurityElement]::Escape($arguments))
    $xmlText = $xmlText.Replace('__REPOSITORY_PATH__', [Security.SecurityElement]::Escape($repositoryResolved))
    $document = New-Object Xml.XmlDocument
    $document.LoadXml($xmlText)
    # CreateNew protects both reviewed exports and accidental concurrent export.
    Write-NewUtf8File $exportResolved $xmlText
    if ($Install) {
        if (-not $RuntimeAcceptancePath) { throw 'Install requires a current runtime integration acceptance receipt.' }
        $acceptanceResolved = Get-AbsoluteLocalPath $RuntimeAcceptancePath 'RuntimeAcceptancePath'
        $acceptance = [IO.File]::ReadAllText($acceptanceResolved) | ConvertFrom-Json
        $runtimeHash = Get-Sha256 (Join-Path $repositoryResolved 'research\ssq_dlt_v45\runtime.py')
        if ($acceptance.status -ne 'PASS' -or $acceptance.runtime_integration -ne 'PASS' -or $acceptance.runtime_sha256 -ne $runtimeHash -or $acceptance.config_sha256 -ne (Get-Sha256 $configResolved)) {
            throw 'Runtime integration is not PASS for the current runtime bytes.'
        }
        $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw 'LocalSystem boot registration requires an elevated administrator; XML is exported but no task is installed.'
        }
        Import-Module ScheduledTasks -ErrorAction Stop
        $existing = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -eq $TaskName })
        if ($existing.Count -gt 0) { throw 'Task already exists; refusing replacement. Choose a new V45 name.' }
        # Prove the exact action can execute under the boot principal before
        # registering a durable task. This single check may append one runtime
        # attempt; publication deduplication belongs to the SQLite runtime.
        $smokeName = 'GLP-SsqDltV45-Smoke-' + [Guid]::NewGuid().ToString('N')
        $smokeDocument = New-Object Xml.XmlDocument
        $smokeDocument.LoadXml($xmlText)
        $namespace = New-Object Xml.XmlNamespaceManager($smokeDocument.NameTable)
        $namespace.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
        $smokeDocument.SelectSingleNode('/t:Task/t:Triggers',$namespace).RemoveAll()
        $smokeRegistered=$false
        try {
            Register-ScheduledTask -TaskPath '\' -TaskName $smokeName -Xml $smokeDocument.OuterXml -ErrorAction Stop | Out-Null
            $smokeRegistered=$true
            Start-ScheduledTask -TaskPath '\' -TaskName $smokeName -ErrorAction Stop
            $deadline=[DateTime]::UtcNow.AddSeconds(45)
            do {
                Start-Sleep -Milliseconds 500
                $smokeTask=Get-ScheduledTask -TaskPath '\' -TaskName $smokeName -ErrorAction Stop
                $smokeInfo=Get-ScheduledTaskInfo -TaskPath '\' -TaskName $smokeName -ErrorAction Stop
                $hasRun=$smokeInfo.LastRunTime.Year -gt 2000
            } while ((-not $hasRun -or $smokeTask.State -eq 'Running') -and [DateTime]::UtcNow -lt $deadline)
            if (-not $hasRun -or $smokeTask.State -eq 'Running' -or $smokeInfo.LastTaskResult -ne 0) {
                throw 'LocalSystem access/runtime smoke failed or timed out; durable task not installed.'
            }
        }
        finally {
            if ($smokeRegistered) {
                Stop-ScheduledTask -TaskPath '\' -TaskName $smokeName -ErrorAction SilentlyContinue
                Unregister-ScheduledTask -TaskPath '\' -TaskName $smokeName -Confirm:$false -ErrorAction Stop
            }
        }
        # No -Force: Scheduler rejects a race with a matching task name.
        Register-ScheduledTask -TaskPath '\' -TaskName $TaskName -Xml $xmlText -ErrorAction Stop | Out-Null
    }
    [ordered]@{
        status=$(if ($Install) { 'INSTALLED' } else { 'EXPORTED_ONLY' }); installed=[bool]$Install
        task_name=$TaskName; xml_path=$exportResolved; xml_sha256=(Get-Sha256 $exportResolved)
        schedule_timezone='UTC (fixed JST +09:00)'; weekly_jst='Monday,Wednesday,Saturday 16:00'
        real_boot='NOT_RUN'; thirty_minute_elapsed_trigger='NOT_RUN'; formal_A=0; conclusion='NO_EDGE'
    } | ConvertTo-Json
    exit 0
}
catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
}
