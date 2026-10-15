[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$RepositoryPath,
    [Parameter(Mandatory = $true)][string]$DatabasePath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][string]$ExportXmlPath,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$')][string]$TaskName = 'GLP-SsqDltV44-Status',
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-AbsolutePath([string]$Value, [string]$Label) {
    if ($Value -notmatch '^[A-Za-z]:[\\/]' -or $Value -match '[\x00-\x1f"]') {
        throw "$Label must be an absolute local Windows path without control characters."
    }
    return [IO.Path]::GetFullPath($Value)
}
function Quote-NativeArgument([string]$Value) {
    # Values have already rejected quotes. Double terminal backslashes before
    # the closing quote for the Windows native command-line parser.
    return '"' + [regex]::Replace($Value, '(\\+)$', '$1$1') + '"'
}
function Escape-Xml([string]$Value) { return [Security.SecurityElement]::Escape($Value) }

try {
    $pythonResolved = Get-AbsolutePath $PythonPath 'PythonPath'
    $repositoryResolved = Get-AbsolutePath $RepositoryPath 'RepositoryPath'
    $databaseResolved = Get-AbsolutePath $DatabasePath 'DatabasePath'
    $outputResolved = Get-AbsolutePath $OutputDirectory 'OutputDirectory'
    $exportResolved = Get-AbsolutePath $ExportXmlPath 'ExportXmlPath'
    if (-not (Test-Path -LiteralPath $pythonResolved -PathType Leaf)) { throw 'Python executable is missing.' }
    if ([IO.Path]::GetFileName($pythonResolved) -notmatch '^python(?:[0-9.]*)?\.exe$') { throw 'Expected a Python executable.' }
    if (-not (Test-Path -LiteralPath (Join-Path $repositoryResolved 'research\ssq_dlt_d2_v44\runtime.py') -PathType Leaf)) {
        throw 'RepositoryPath does not contain the approved runtime.'
    }
    $runnerResolved = Join-Path $repositoryResolved 'research\ssq_dlt_d2_v44\windows\Invoke-Status.ps1'
    if (-not (Test-Path -LiteralPath $runnerResolved -PathType Leaf)) { throw 'Status wrapper is missing.' }
    $powershellResolved = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershellResolved -PathType Leaf)) { throw 'Windows PowerShell 5.1 is unavailable.' }
    $pythonProbe = & $pythonResolved -I -c 'import json,sys; print(json.dumps(dict(python=sys.version_info >= (3,10),executable=sys.executable)))'
    if ($LASTEXITCODE -ne 0) { throw 'Python interpreter validation failed.' }
    $pythonIdentity = $pythonProbe | ConvertFrom-Json
    if (-not $pythonIdentity.python -or -not [string]::Equals([IO.Path]::GetFullPath($pythonIdentity.executable), $pythonResolved, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Interpreter identity or Python >= 3.10 validation failed.'
    }
    $arguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File ' + (Quote-NativeArgument $runnerResolved) +
        ' -PythonPath ' + (Quote-NativeArgument $pythonResolved) + ' -RepositoryPath ' + (Quote-NativeArgument $repositoryResolved) +
        ' -DatabasePath ' + (Quote-NativeArgument $databaseResolved) + ' -OutputDirectory ' + (Quote-NativeArgument $outputResolved)
    $templatePath = Join-Path $PSScriptRoot 'task-template.xml'
    $xmlText = [IO.File]::ReadAllText($templatePath)
    $xmlText = $xmlText.Replace('__START_BOUNDARY__', [DateTime]::UtcNow.AddMinutes(1).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"))
    $xmlText = $xmlText.Replace('__POWERSHELL_PATH__', (Escape-Xml $powershellResolved))
    $xmlText = $xmlText.Replace('__ARGUMENTS__', (Escape-Xml $arguments))
    $xmlText = $xmlText.Replace('__REPOSITORY_PATH__', (Escape-Xml $repositoryResolved))
    $xmlDocument = New-Object System.Xml.XmlDocument
    $xmlDocument.LoadXml($xmlText)
    # Export itself is append-only: never silently replace a reviewed XML file.
    $exportStream = [IO.File]::Open($exportResolved, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($xmlText)
        $exportStream.Write($bytes, 0, $bytes.Length)
    }
    finally { $exportStream.Dispose() }

    if ($Install) {
        $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw 'Boot installation uses LocalSystem and requires an elevated administrator. XML was exported; no task was installed.'
        }
        Import-Module ScheduledTasks -ErrorAction Stop
        $existing = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -eq $TaskName })
        if ($existing.Count -gt 0) { throw 'A task with this name already exists; refusing to replace it.' }
        # Verify the exact action under LocalSystem before installing a durable
        # boot task: user-local Python, repository and database ACLs may differ.
        $probeName = 'GLP-V44-AccessProbe-' + [Guid]::NewGuid().ToString('N')
        $probeDocument = New-Object System.Xml.XmlDocument
        $probeDocument.LoadXml($xmlText)
        $ns = New-Object System.Xml.XmlNamespaceManager($probeDocument.NameTable)
        $ns.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
        $triggers = $probeDocument.SelectSingleNode('/t:Task/t:Triggers', $ns)
        $triggers.RemoveAll()
        $probeRegistered = $false
        try {
            Register-ScheduledTask -TaskName $probeName -TaskPath '\' -Xml $probeDocument.OuterXml -ErrorAction Stop | Out-Null
            $probeRegistered = $true
            Start-ScheduledTask -TaskName $probeName -TaskPath '\' -ErrorAction Stop
            $deadline = [DateTime]::UtcNow.AddSeconds(45)
            do {
                Start-Sleep -Milliseconds 500
                $probeTask = Get-ScheduledTask -TaskName $probeName -TaskPath '\' -ErrorAction Stop
                $probeInfo = Get-ScheduledTaskInfo -TaskName $probeName -TaskPath '\' -ErrorAction Stop
                $hasRun = $probeInfo.LastRunTime.Year -gt 2000
            } while ((-not $hasRun -or $probeTask.State -eq 'Running') -and [DateTime]::UtcNow -lt $deadline)
            if (-not $hasRun -or $probeTask.State -eq 'Running' -or $probeInfo.LastTaskResult -ne 0) {
                throw 'LocalSystem execution failed or timed out. No durable task will be installed; inspect ACLs and runtime failures.'
            }
        }
        finally {
            if ($probeRegistered) {
                Stop-ScheduledTask -TaskName $probeName -TaskPath '\' -ErrorAction SilentlyContinue
                Unregister-ScheduledTask -TaskName $probeName -TaskPath '\' -Confirm:$false -ErrorAction Stop
            }
        }
        # No -Force: the Scheduler also rejects a race with an existing name.
        Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Xml $xmlText -ErrorAction Stop | Out-Null
    }
    $hashAlgorithm = [Security.Cryptography.SHA256]::Create()
    try { $xmlHash = [BitConverter]::ToString($hashAlgorithm.ComputeHash([IO.File]::ReadAllBytes($exportResolved))).Replace('-', '').ToLowerInvariant() }
    finally { $hashAlgorithm.Dispose() }
    [ordered]@{
        status = $(if ($Install) { 'INSTALLED' } else { 'EXPORTED_ONLY' })
        task_name = $TaskName
        installed = [bool]$Install
        xml_sha256 = $xmlHash
        R2 = 'BLOCKED'; formal_A = 0; conclusion = 'NO_EDGE'
    } | ConvertTo-Json
    exit 0
}
catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
}
