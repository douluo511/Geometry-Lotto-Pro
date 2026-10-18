[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$RepositoryPath,
    [Parameter(Mandatory = $true)][string]$ConfigPath,
    [Parameter(Mandatory = $true)][string]$LauncherLogDirectory
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Common.ps1')
$logResolved = $null
try {
    $pythonResolved = Get-AbsoluteLocalPath $PythonPath 'PythonPath'
    $repositoryResolved = Get-AbsoluteLocalPath $RepositoryPath 'RepositoryPath'
    $configResolved = Get-AbsoluteLocalPath $ConfigPath 'ConfigPath'
    $logResolved = Get-AbsoluteLocalPath $LauncherLogDirectory 'LauncherLogDirectory'
    Assert-DeploymentPaths $pythonResolved $repositoryResolved $configResolved
    [IO.Directory]::CreateDirectory($logResolved) | Out-Null
    $runId = [Guid]::NewGuid().ToString('N')
    $startedAt = [DateTime]::UtcNow.ToString('o')
    $stdoutPath = Join-Path $logResolved ($runId + '.stdout.log')
    $stderrPath = Join-Path $logResolved ($runId + '.stderr.log')
    # Redirect both streams without PowerShell treating native stderr as a
    # terminating PowerShell error. No visible helper window is opened.
    $runtimeArguments = '-m research.ssq_dlt_v45.runtime --config ' + (Quote-NativeArgument $configResolved)
    $process = Start-Process -FilePath $pythonResolved -ArgumentList $runtimeArguments -WorkingDirectory $repositoryResolved -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $runtimeExit = $process.ExitCode
    $receipt = [ordered]@{
        run_id=$runId; started_at_utc=$startedAt; finished_at_utc=[DateTime]::UtcNow.ToString('o')
        status=$(if ($runtimeExit -eq 0) { 'PASS' } else { 'FAIL' }); exit_code=$runtimeExit
        config_sha256=(Get-Sha256 $configResolved)
        runtime_sha256=(Get-Sha256 (Join-Path $repositoryResolved 'research\ssq_dlt_v45\runtime.py'))
        stdout_sha256=(Get-Sha256 $stdoutPath); stderr_sha256=(Get-Sha256 $stderrPath)
        formal_A=0; conclusion='NO_EDGE'
    }
    Write-NewUtf8File (Join-Path $logResolved ($runId + '.json')) ($receipt | ConvertTo-Json -Depth 8)
    $receipt | ConvertTo-Json -Depth 8
    exit $runtimeExit
}
catch {
    if ($null -ne $logResolved) {
        try {
            [IO.Directory]::CreateDirectory($logResolved) | Out-Null
            $failure = [ordered]@{ status='FAIL'; exit_code=1; checked_at_utc=[DateTime]::UtcNow.ToString('o'); error=$_.Exception.Message; formal_A=0; conclusion='NO_EDGE' }
            Write-NewUtf8File (Join-Path $logResolved ([Guid]::NewGuid().ToString('N') + '.failure.json')) ($failure | ConvertTo-Json)
        }
        catch { Write-Warning 'Could not persist launcher failure; exit remains nonzero.' }
    }
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
}
