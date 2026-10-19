[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$RepositoryPath,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [Parameter(Mandatory=$true)][string]$LauncherLogDirectory,
    [Parameter(Mandatory=$true)][string]$ExportXmlPath,
    [string]$DeploymentManifestPath,
    [ValidatePattern('^GLP-SsqDltAgentV1-[A-Za-z0-9_.-]{1,60}$')][string]$TaskName='GLP-SsqDltAgentV1-Local',
    [string]$LiveAcceptancePath,
    [switch]$ExportOnly,
    [switch]$Install
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
try {
    if ($ExportOnly -and $Install) { throw 'EXPORT_AND_INSTALL_ARE_EXCLUSIVE' }
    if ($RepositoryPath -notmatch '^[A-Za-z]:[\\/]' -or $RepositoryPath -match '[\x00-\x1f"]') { throw 'INVALID_REPOSITORY_PATH' }
    . (Join-Path $RepositoryPath 'research\ssq_dlt_v45\windows\Common.ps1')
    $pythonResolved=Get-AbsoluteLocalPath $PythonPath 'PythonPath'
    $repositoryResolved=Get-AbsoluteLocalPath $RepositoryPath 'RepositoryPath'
    $configResolved=Get-AbsoluteLocalPath $ConfigPath 'ConfigPath'
    $logResolved=Get-AbsoluteLocalPath $LauncherLogDirectory 'LauncherLogDirectory'
    $exportResolved=Get-AbsoluteLocalPath $ExportXmlPath 'ExportXmlPath'
    if (-not $DeploymentManifestPath) { $DeploymentManifestPath=$exportResolved+'.deployment.json' }
    $manifestResolved=Get-AbsoluteLocalPath $DeploymentManifestPath 'DeploymentManifestPath'
    Assert-DeploymentPaths $pythonResolved $repositoryResolved $configResolved
    $runner=Join-Path $repositoryResolved 'research\ssq_dlt_agent_v1\scripts\Run-V45Agent.ps1'
    if (-not (Test-Path -LiteralPath $runner -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $repositoryResolved 'research\ssq_dlt_agent_v1\__main__.py') -PathType Leaf)) { throw 'AGENT_ENTRY_POINT_MISSING' }
    $powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) { throw 'WINDOWS_POWERSHELL_MISSING' }
    $xmlExists=Test-Path -LiteralPath $exportResolved
    $manifestExists=Test-Path -LiteralPath $manifestResolved
    $reuseReviewed=$Install -and $xmlExists -and $manifestExists
    if (($xmlExists -or $manifestExists) -and -not $reuseReviewed) { throw 'EXPORT_ALREADY_EXISTS' }
    $baseProbe=& $pythonResolved -I -c 'import json,sys; print(json.dumps(dict(base_executable=sys._base_executable)))'
    if ($LASTEXITCODE -ne 0) { throw 'PYTHON_IDENTITY_FAILED' }
    $basePython=Get-AbsoluteLocalPath (($baseProbe | ConvertFrom-Json).base_executable) 'BasePythonPath'
    $codeManifest=[ordered]@{}
    foreach ($name in @('ssq_dlt_agent_v1','ssq_dlt_v45','ssq_dlt_d2_v44')) {
        $moduleRoot=Join-Path $repositoryResolved ('research\'+$name)
        if (-not (Test-Path -LiteralPath $moduleRoot -PathType Container)) { throw 'DEPENDENCY_DIRECTORY_MISSING' }
        foreach ($file in (Get-ChildItem -LiteralPath $moduleRoot -File -Recurse | Sort-Object FullName)) {
            $relative=$file.FullName.Substring($moduleRoot.Length+1).Replace('\','/')
            if ($file.Extension -in @('.py','.ps1','.xml','.txt') -and $relative -notmatch '(^|/)(tests|__pycache__|evidence)(/|$)') {
                $codeManifest[$name+'/'+$relative]=Get-Sha256 $file.FullName
            }
        }
    }
    $manifest=[ordered]@{ schema='ssq-dlt-agent-windows-deployment-1'; repository_path=$repositoryResolved; config_path=$configResolved; config_sha256=(Get-Sha256 $configResolved); python_path=$pythonResolved; python_sha256=(Get-Sha256 $pythonResolved); base_python_path=$basePython; base_python_sha256=(Get-Sha256 $basePython); code_manifest=$codeManifest }
    $manifestText=$manifest | ConvertTo-Json -Depth 8
    if ($reuseReviewed -and [IO.File]::ReadAllText($manifestResolved) -cne $manifestText) { throw 'REVIEWED_DEPLOYMENT_CHANGED' }
    # Scheduled actions are always live and never receive an explicit run key.
    # The CLI derives the JST due_slot key on both normal and catch-up triggers.
    $arguments='-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File '+(Quote-NativeArgument $runner)+
        ' -PythonPath '+(Quote-NativeArgument $pythonResolved)+' -RepositoryPath '+(Quote-NativeArgument $repositoryResolved)+
        ' -ConfigPath '+(Quote-NativeArgument $configResolved)+' -LauncherLogDirectory '+(Quote-NativeArgument $logResolved)+
        ' -DeploymentManifestPath '+(Quote-NativeArgument $manifestResolved)+' -Mode live'
    $commandXml=[Security.SecurityElement]::Escape($powershell)
    $argumentsXml=[Security.SecurityElement]::Escape($arguments)
    $workingXml=[Security.SecurityElement]::Escape($repositoryResolved)
    $catchup=[DateTime]::UtcNow.AddMinutes(1).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
    if ($reuseReviewed) {
        $reviewedDocument=New-Object Xml.XmlDocument
        $reviewedDocument.LoadXml([IO.File]::ReadAllText($exportResolved))
        $namespace=New-Object Xml.XmlNamespaceManager($reviewedDocument.NameTable)
        $namespace.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
        $catchup=$reviewedDocument.SelectSingleNode('/t:Task/t:Triggers/t:TimeTrigger/t:StartBoundary',$namespace).InnerText
        # Reject malformed boundaries before embedding the reviewed value.
        if ($catchup -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$') { throw 'REVIEWED_CATCHUP_BOUNDARY_INVALID' }
    }
    $xmlText=@"
<?xml version="1.0" encoding="UTF-8"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Opt-in SSQ/DLT Agent V1 live model only. Monday,Wednesday,Saturday 16:00 JST (07:00 UTC), boot and 30 minute catch-up. Export does not prove a deadline, boot or elapsed schedule. Formal A=0; NO_EDGE.</Description></RegistrationInfo>
  <Triggers>
    <BootTrigger><Enabled>true</Enabled><Delay>PT30S</Delay></BootTrigger>
    <CalendarTrigger><StartBoundary>2020-01-06T07:00:00Z</StartBoundary><Enabled>true</Enabled><ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Monday/><Wednesday/><Saturday/></DaysOfWeek></ScheduleByWeek></CalendarTrigger>
    <TimeTrigger><Repetition><Interval>PT30M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>$catchup</StartBoundary><Enabled>true</Enabled></TimeTrigger>
  </Triggers>
  <Principals><Principal id="AgentV1Runner"><UserId>S-1-5-18</UserId><LogonType>ServiceAccount</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>true</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT10M</ExecutionTimeLimit><Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="AgentV1Runner"><Exec><Command>$commandXml</Command><Arguments>$argumentsXml</Arguments><WorkingDirectory>$workingXml</WorkingDirectory></Exec></Actions>
</Task>
"@
    $document=New-Object Xml.XmlDocument
    $document.LoadXml($xmlText)
    if ($reuseReviewed) {
        if ([IO.File]::ReadAllText($exportResolved) -cne $xmlText) { throw 'REVIEWED_TASK_CHANGED' }
    } else {
        Write-NewUtf8File $manifestResolved $manifestText
        Write-NewUtf8File $exportResolved $xmlText
    }
    if ($Install) {
        $principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'ADMINISTRATOR_REQUIRED_EXPORTED_NOT_INSTALLED' }
        if (-not $LiveAcceptancePath) { throw 'CURRENT_LIVE_LAUNCH_ACCEPTANCE_REQUIRED' }
        $acceptancePath=Get-AbsoluteLocalPath $LiveAcceptancePath 'LiveAcceptancePath'
        $acceptance=[IO.File]::ReadAllText($acceptancePath) | ConvertFrom-Json -ErrorAction Stop
        if ($acceptance.schema -cne 'ssq-dlt-agent-windows-launch-1' -or $acceptance.status -cne 'PASS' -or
            $acceptance.mode -cne 'live' -or $acceptance.exit_code -ne 0 -or $acceptance.fallback_used -ne $false -or
            $acceptance.deployment_manifest_sha256 -cne (Get-Sha256 $manifestResolved)) { throw 'CURRENT_LIVE_LAUNCH_ACCEPTANCE_REQUIRED' }
        Import-Module ScheduledTasks -ErrorAction Stop
        $existing=@(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -eq $TaskName })
        if ($existing.Count -gt 0) { throw 'TASK_EXISTS_REFUSING_REPLACEMENT' }
        # No -Force: a race or an existing task fails closed. Export/test paths
        # never import Scheduler or register a transient smoke task.
        Register-ScheduledTask -TaskPath '\' -TaskName $TaskName -Xml $xmlText -ErrorAction Stop | Out-Null
    }
    [ordered]@{
        status=$(if ($Install) { 'INSTALLED' } else { 'EXPORTED_ONLY' }); installed=[bool]$Install
        task_name=$TaskName; xml_path=$exportResolved; xml_sha256=(Get-Sha256 $exportResolved)
        deployment_manifest_path=$manifestResolved; deployment_manifest_sha256=(Get-Sha256 $manifestResolved)
        scheduled_mode='live'; fallback_allowed=$false; run_key_policy='CLI_JST_MON_WED_SAT_DUE_SLOT'
        schedule_timezone='UTC (fixed JST +09:00)'; weekly_jst='Monday,Wednesday,Saturday 16:00'
        real_boot='NOT_RUN'; thirty_minute_elapsed_trigger='NOT_RUN'; daily_schedule_execution='NOT_RUN'
        deadline_enforcement='NOT_PROVEN'; local_system_execution='NOT_RUN'; formal_A=0; decision='NO_EDGE'
    } | ConvertTo-Json -Depth 8
    exit 0
}
catch {
    # Never echo parsed config or environment values in an exception message.
    [Console]::Error.WriteLine('AGENT_TASK_EXPORT_OR_INSTALL_FAILED')
    exit 1
}
