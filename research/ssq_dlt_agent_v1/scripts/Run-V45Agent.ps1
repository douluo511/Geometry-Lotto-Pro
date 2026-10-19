[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$RepositoryPath,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [Parameter(Mandatory=$true)][string]$LauncherLogDirectory,
    [Parameter(Mandatory=$true)][string]$DeploymentManifestPath,
    [ValidateSet('live','sdk-fixture','tools-smoke')][string]$Mode='live',
    [ValidatePattern('^[A-Za-z0-9_.:+-]{1,200}$')][string]$RunKey
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$logResolved=$null
try {
    if ($RepositoryPath -notmatch '^[A-Za-z]:[\\/]' -or $RepositoryPath -match '[\x00-\x1f"]') { throw 'INVALID_REPOSITORY_PATH' }
    . (Join-Path $RepositoryPath 'research\ssq_dlt_v45\windows\Common.ps1')
    $pythonResolved=Get-AbsoluteLocalPath $PythonPath 'PythonPath'
    $repositoryResolved=Get-AbsoluteLocalPath $RepositoryPath 'RepositoryPath'
    $configResolved=Get-AbsoluteLocalPath $ConfigPath 'ConfigPath'
    $logResolved=Get-AbsoluteLocalPath $LauncherLogDirectory 'LauncherLogDirectory'
    $manifestResolved=Get-AbsoluteLocalPath $DeploymentManifestPath 'DeploymentManifestPath'
    $manifest=[IO.File]::ReadAllText($manifestResolved) | ConvertFrom-Json -ErrorAction Stop
    if ($manifest.schema -cne 'ssq-dlt-agent-windows-deployment-1' -or
        -not [string]::Equals($manifest.python_path,$pythonResolved,[StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($manifest.repository_path,$repositoryResolved,[StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($manifest.config_path,$configResolved,[StringComparison]::OrdinalIgnoreCase) -or
        $manifest.python_sha256 -cne (Get-Sha256 $pythonResolved) -or
        $manifest.config_sha256 -cne (Get-Sha256 $configResolved) -or
        $manifest.base_python_sha256 -cne (Get-Sha256 $manifest.base_python_path)) { throw 'DEPLOYMENT_IDENTITY_CHANGED' }
    $expectedManifest=@{}
    foreach ($name in @('ssq_dlt_agent_v1','ssq_dlt_v45','ssq_dlt_d2_v44')) {
        $moduleRoot=Join-Path $repositoryResolved ('research\'+$name)
        if (-not (Test-Path -LiteralPath $moduleRoot -PathType Container)) { throw 'DEPENDENCY_DIRECTORY_MISSING' }
        foreach ($file in Get-ChildItem -LiteralPath $moduleRoot -File -Recurse) {
            $relative=$file.FullName.Substring($moduleRoot.Length+1).Replace('\','/')
            if ($file.Extension -in @('.py','.ps1','.xml','.txt') -and $relative -notmatch '(^|/)(tests|__pycache__|evidence)(/|$)') {
                $expectedManifest[$name+'/'+$relative]=Get-Sha256 $file.FullName
            }
        }
    }
    $savedProperties=@($manifest.code_manifest.PSObject.Properties)
    if ($savedProperties.Count -ne $expectedManifest.Count) { throw 'DEPLOYMENT_CODE_SET_CHANGED' }
    foreach ($property in $savedProperties) {
        if (-not $expectedManifest.ContainsKey($property.Name) -or $expectedManifest[$property.Name] -cne $property.Value) { throw 'DEPLOYMENT_CODE_CHANGED' }
    }
    Assert-DeploymentPaths $pythonResolved $repositoryResolved $configResolved
    if (-not (Test-Path -LiteralPath (Join-Path $repositoryResolved 'research\ssq_dlt_agent_v1\__main__.py') -PathType Leaf)) { throw 'AGENT_ENTRY_POINT_MISSING' }
    [IO.Directory]::CreateDirectory($logResolved) | Out-Null
    $runId=[Guid]::NewGuid().ToString('N')
    $startedAt=[DateTime]::UtcNow.ToString('o')
    $stdoutPath=Join-Path $logResolved ($runId+'.stdout.log')
    $stderrPath=Join-Path $logResolved ($runId+'.stderr.log')
    $arguments='-m research.ssq_dlt_agent_v1 --config '+(Quote-NativeArgument $configResolved)+' --mode '+$Mode
    # No generated UUID is passed as a run key. Omission deliberately uses the
    # CLI's JST Monday/Wednesday/Saturday due_slot key for catch-up deduplication.
    if ($RunKey) { $arguments+=' --run-key '+(Quote-NativeArgument $RunKey) }
    # Failure stays in the requested mode: there is no fixture/tools fallback.
    $process=Start-Process -FilePath $pythonResolved -ArgumentList $arguments -WorkingDirectory $repositoryResolved -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $runtimeExit=$process.ExitCode
    if ($manifest.config_sha256 -cne (Get-Sha256 $configResolved) -or
        $manifest.python_sha256 -cne (Get-Sha256 $pythonResolved) -or
        $manifest.base_python_sha256 -cne (Get-Sha256 $manifest.base_python_path)) { throw 'DEPLOYMENT_CHANGED_DURING_RUN' }
    $finishedManifest=@{}
    foreach ($name in @('ssq_dlt_agent_v1','ssq_dlt_v45','ssq_dlt_d2_v44')) {
        $moduleRoot=Join-Path $repositoryResolved ('research\'+$name)
        foreach ($file in Get-ChildItem -LiteralPath $moduleRoot -File -Recurse) {
            $relative=$file.FullName.Substring($moduleRoot.Length+1).Replace('\','/')
            if ($file.Extension -in @('.py','.ps1','.xml','.txt') -and $relative -notmatch '(^|/)(tests|__pycache__|evidence)(/|$)') {
                $finishedManifest[$name+'/'+$relative]=Get-Sha256 $file.FullName
            }
        }
    }
    if ($finishedManifest.Count -ne $expectedManifest.Count) { throw 'DEPLOYMENT_CHANGED_DURING_RUN' }
    foreach ($property in $savedProperties) {
        if (-not $finishedManifest.ContainsKey($property.Name) -or $property.Value -cne $finishedManifest[$property.Name]) { throw 'DEPLOYMENT_CHANGED_DURING_RUN' }
    }
    $receipt=[ordered]@{
        schema='ssq-dlt-agent-windows-launch-1'; run_id=$runId; mode=$Mode
        entry_point='research.ssq_dlt_agent_v1'; started_at_utc=$startedAt; finished_at_utc=[DateTime]::UtcNow.ToString('o')
        status=$(if ($runtimeExit -eq 0) { 'PASS' } elseif ($runtimeExit -eq 2) { 'BLOCKED' } else { 'FAIL' }); exit_code=$runtimeExit
        validation_scope='HIDDEN_LAUNCHER_PROCESS_ONLY'; fallback_used=$false
        run_key_policy=$(if ($RunKey) { 'EXPLICIT_OPERATOR_KEY' } else { 'CLI_JST_MON_WED_SAT_DUE_SLOT' })
        deployment_manifest_sha256=(Get-Sha256 $manifestResolved); config_sha256=$manifest.config_sha256
        python_sha256=$manifest.python_sha256; base_python_sha256=$manifest.base_python_sha256
        stdout_sha256=(Get-Sha256 $stdoutPath); stderr_sha256=(Get-Sha256 $stderrPath)
        deadline_enforcement='NOT_PROVEN'; daily_schedule_execution='NOT_RUN'; formal_A=0; decision='NO_EDGE'
    }
    Write-NewUtf8File (Join-Path $logResolved ($runId+'.json')) ($receipt | ConvertTo-Json -Depth 8)
    $receipt | ConvertTo-Json -Depth 8
    exit $runtimeExit
}
catch {
    # Do not serialize exception messages, configuration, environment or SMTP
    # values. A JSON parser/provider exception could otherwise echo a secret.
    if ($null -ne $logResolved) {
        try {
            [IO.Directory]::CreateDirectory($logResolved) | Out-Null
            $failure=[ordered]@{ schema='ssq-dlt-agent-windows-launch-1'; status='FAIL'; exit_code=1; mode=$Mode; error_code='AGENT_LAUNCHER_FAILED'; error_type=$_.Exception.GetType().Name; checked_at_utc=[DateTime]::UtcNow.ToString('o'); fallback_used=$false; formal_A=0; decision='NO_EDGE' }
            Write-NewUtf8File (Join-Path $logResolved ([Guid]::NewGuid().ToString('N')+'.failure.json')) ($failure | ConvertTo-Json)
        } catch { [Console]::Error.WriteLine('AGENT_FAILURE_RECEIPT_UNAVAILABLE') }
    }
    [Console]::Error.WriteLine('AGENT_LAUNCHER_FAILED')
    exit 1
}
