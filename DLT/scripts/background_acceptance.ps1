param(
  [Parameter(Mandatory=$true)][string]$MainExe,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [int]$TimeoutSeconds = 3600
)

$ErrorActionPreference = 'Stop'
$evidence=[System.IO.Path]::GetFullPath($EvidencePath)
$requestPath=$evidence + '.request.json'
# Fixed output paths are single-use. In particular, a retry in the same workflow
# attempt must not validate a previous launch's report against its own nonce.
if((Test-Path -LiteralPath $evidence) -or (Test-Path -LiteralPath $requestPath)){
  throw 'background evidence or expected request already exists'
}
$main=(Resolve-Path -LiteralPath $MainExe).Path
$exeHash=(Get-FileHash -LiteralPath $main -Algorithm SHA256).Hash.ToLowerInvariant()
if($TimeoutSeconds -lt 1800){ throw 'native continuity timeout cannot be below 1800 seconds' }
foreach($value in @($env:GITHUB_SHA,$env:GITHUB_RUN_ID,$env:GITHUB_RUN_ATTEMPT)){
  if([string]::IsNullOrWhiteSpace($value)){ throw 'exact SHA, run and run-attempt are required' }
}
$parent=[System.IO.Path]::GetDirectoryName($evidence)
New-Item -ItemType Directory -Force $parent | Out-Null
$work=Join-Path $parent ('background-' + [Guid]::NewGuid().ToString('N'))
$data=Join-Path $work 'data'
$launch=Join-Path $work 'launch.json'
New-Item -ItemType Directory -Force $data | Out-Null

function Write-CreateOnlyJson([string]$Path, $Value){
  $bytes=[System.Text.UTF8Encoding]::new($false).GetBytes(($Value | ConvertTo-Json -Depth 30))
  $stream=[System.IO.File]::Open($Path,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::Read)
  try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) }
  finally { $stream.Dispose() }
}

$request=[ordered]@{
  schema='dlt-background-acceptance-request-v2'
  launch_session=[Guid]::NewGuid().ToString('N')
  acceptance_nonce=[Guid]::NewGuid().ToString('N')
  github_sha=$env:GITHUB_SHA
  github_run_id=$env:GITHUB_RUN_ID
  github_run_attempt=$env:GITHUB_RUN_ATTEMPT
  exe_sha256=$exeHash
  exe_path=$main
}
Write-CreateOnlyJson $requestPath $request
$errors=[System.Collections.Generic.List[string]]::new()
$samples=[System.Collections.Generic.List[object]]::new()
$owned=@{}
$launchObj=$null
$statusObj=$null
$p=$null
$launcherExit=$null
$finalStatusOffset=$null
$launchStarted=[DateTime]::UtcNow
$watch=[System.Diagnostics.Stopwatch]::StartNew()
$previousData=$env:GLP_DATA_DIR
$report=[ordered]@{
  schema='dlt-background-acceptance-v2'; status='FAIL'
  launch_session=$request.launch_session; acceptance_nonce=$request.acceptance_nonce
  github_sha=$request.github_sha; github_run_id=$request.github_run_id; github_run_attempt=$request.github_run_attempt
  exe_sha256=$exeHash; exe_path=$main; exe_sha256_before=$exeHash; exe_sha256_after=$null
  launch=$null; worker_status=$null; observer=$null; errors=@()
}

function Read-OwnedProcesses {
  # Creation identity and executable bytes are observed outside the worker. Only
  # descendants of this invocation's Start-Process identity enter the owned set.
  # Known PIDs must be queried independently of executable name/path. Otherwise
  # a reused ancestor that becomes a foreign executable vanishes in the discovery
  # filter, and may be gone again by cleanup without retaining the reuse event.
  foreach($knownKey in @($owned.Keys)){
    $known=Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$knownKey"
    if($null -ne $known -and (
      $known.CreationDate.ToUniversalTime().ToString('o') -ne $owned[$knownKey].creation_time -or
      -not [string]::Equals($known.ExecutablePath,$owned[$knownKey].exe_path,[StringComparison]::OrdinalIgnoreCase)
    )){ throw "owned PID identity changed: $knownKey" }
  }
  $name=[System.IO.Path]::GetFileName($main).Replace("'","''")
  $discovered=@(Get-CimInstance -ClassName Win32_Process -Filter "Name='$name'")
  foreach($candidate in $discovered){
    $key=[int]$candidate.ProcessId
    if($owned.ContainsKey($key)){
      if($owned[$key].creation_time -ne $candidate.CreationDate.ToUniversalTime().ToString('o') -or
         -not [string]::Equals($candidate.ExecutablePath,$owned[$key].exe_path,[StringComparison]::OrdinalIgnoreCase)){
        throw "owned PID identity changed: $key"
      }
    }
  }
  $candidates=@($discovered | Where-Object {
    $_.ExecutablePath -and [string]::Equals($_.ExecutablePath,$main,[StringComparison]::OrdinalIgnoreCase) -and
    $_.CreationDate.ToUniversalTime() -ge $launchStarted
  })
  # A single snapshot can contain multiple bootloader/payload generations.
  for($round=0;$round -lt $candidates.Count;$round++){
    foreach($candidate in $candidates){
      $key=[int]$candidate.ProcessId
      $parentKey=[int]$candidate.ParentProcessId
      if(-not $owned.ContainsKey($key) -and $owned.ContainsKey($parentKey)){
        if($candidate.CreationDate.ToUniversalTime() -lt [DateTime]::Parse($owned[$parentKey].creation_time).ToUniversalTime()){
          throw 'descendant creation precedes owned parent'
        }
        $identityHash=(Get-FileHash -LiteralPath $candidate.ExecutablePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if($identityHash -ne $exeHash){ throw 'live executable bytes changed' }
        $owned[$key]=[ordered]@{
          pid=$key; parent_pid=$parentKey; creation_time=$candidate.CreationDate.ToUniversalTime().ToString('o')
          exe_path=$candidate.ExecutablePath; exe_sha256=$exeHash
        }
      }
    }
  }
  $live=[System.Collections.Generic.List[object]]::new()
  foreach($candidate in $candidates){
    $key=[int]$candidate.ProcessId
    if($owned.ContainsKey($key)){
      # This identity's path and hash were observed at registration; the same
      # file is hashed again after observation and before any owned cleanup.
      $live.Add($owned[$key])
    }
  }
  return ,$live.ToArray()
}

try {
  $env:GLP_DATA_DIR=$data
  $p=Start-Process -FilePath $main -ArgumentList @(
    '--background-launch',
    '--background-interval-seconds','1800',
    '--background-max-cycles','2',
    '--background-launch-session',$request.launch_session,
    '--background-acceptance-nonce',$request.acceptance_nonce,
    '--result-file',('"' + $launch + '"')
  ) -PassThru -WindowStyle Hidden
  $p.Refresh()
  $rootProcess=Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$($p.Id)"
  if($null -eq $rootProcess -or -not [string]::Equals($rootProcess.ExecutablePath,$main,[StringComparison]::OrdinalIgnoreCase)){
    throw 'cannot observe fresh launcher creation identity'
  }
  # CIM formats creation times with lower precision than Process.StartTime.
  # The initial comparison allows 1ms formatting loss; subsequent PID identity
  # checks compare the stable exact CIM creation token without tolerance.
  if($rootProcess.CreationDate.ToUniversalTime() -lt $launchStarted -or [Math]::Abs(($rootProcess.CreationDate.ToUniversalTime() - $p.StartTime.ToUniversalTime()).TotalMilliseconds) -gt 1){
    throw 'launcher PID creation identity mismatch'
  }
  $owned[[int]$p.Id]=[ordered]@{
    pid=[int]$p.Id; parent_pid=[int]$rootProcess.ParentProcessId
    creation_time=$rootProcess.CreationDate.ToUniversalTime().ToString('o')
    exe_path=$rootProcess.ExecutablePath; exe_sha256=$exeHash
  }
  $sawWorker=$false
  while($watch.Elapsed.TotalSeconds -lt $TimeoutSeconds){
    $live=Read-OwnedProcesses
    $offset=$watch.Elapsed.TotalSeconds
    $samples.Add([ordered]@{offset_seconds=$offset; processes=@($live)})
    $p.Refresh()
    if($p.HasExited -and $null -eq $launcherExit){
      $launcherExit=$watch.Elapsed.TotalSeconds
      if($p.ExitCode -ne 0){ throw "background launcher failed: exit=$($p.ExitCode)" }
    }
    if($null -eq $launcherExit -and $watch.Elapsed.TotalSeconds -gt 90){ throw 'launcher startup exceeded 90 seconds' }
    if($null -eq $launchObj -and (Test-Path -LiteralPath $launch)){
      $launchObj=Get-Content -LiteralPath $launch -Raw | ConvertFrom-Json
      if($launchObj.launch_session -ne $request.launch_session -or $launchObj.acceptance_nonce -ne $request.acceptance_nonce){
        throw 'launcher session/nonce mismatch'
      }
    }
    if(Test-Path -LiteralPath (Join-Path $data 'background_status.json')){
      # Worker status replacement is atomic; malformed evidence must fail closed.
      $statusObj=Get-Content -LiteralPath (Join-Path $data 'background_status.json') -Raw | ConvertFrom-Json
      if($statusObj.launch_session -ne $request.launch_session -or $statusObj.acceptance_nonce -ne $request.acceptance_nonce){
        throw 'worker session/nonce mismatch'
      }
      $workerLive=@($live | Where-Object { $_.pid -eq [int]$statusObj.pid }).Count -eq 1
      if($workerLive){ $sawWorker=$true }
      if($statusObj.worker_exit -eq 'MAX_CYCLES_REACHED'){
        $finalStatusOffset=$watch.Elapsed.TotalSeconds
        if($null -eq $launcherExit){ throw 'worker completed before launcher exit observed' }
        break
      }
      if($sawWorker -and -not $workerLive){ throw 'worker exited before completing two cycles' }
    }
    Start-Sleep -Milliseconds 250
  }
  if($null -eq $finalStatusOffset){ throw 'background worker did not complete two live cycles before timeout' }
}
catch { $errors.Add($_.Exception.Message) }
finally {
  # Cleanup is limited to observed descendants with the same creation identity.
  # A reused PID, different executable or any pre-existing user process is untouched.
  # Open and validate one native handle, then terminate that handle. A PID-only
  # Stop-Process after a CIM lookup has a reuse race between lookup and termination.
  if($owned.Count -gt 0 -and -not ('DLTBackgroundNative' -as [type])){
    try { Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class DLTBackgroundNative {
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool GetProcessTimes(IntPtr handle, out long creation, out long exit, out long kernel, out long user);
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern bool QueryFullProcessImageName(IntPtr handle, uint flags, StringBuilder path, ref int length);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool TerminateProcess(IntPtr handle, uint code);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool CloseHandle(IntPtr handle);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern uint WaitForSingleObject(IntPtr handle, uint timeout);
}
'@
    } catch { $errors.Add('owned cleanup initialization: ' + $_.Exception.Message) }
  }
  foreach($entry in @($owned.Values | Sort-Object creation_time -Descending)){
    $handle=[IntPtr]::Zero
    try {
      $current=Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$($entry.pid)"
      if($null -ne $current){
        if($current.CreationDate.ToUniversalTime().ToString('o') -ne $entry.creation_time -or
           -not [string]::Equals($current.ExecutablePath,$entry.exe_path,[StringComparison]::OrdinalIgnoreCase)){
          $errors.Add("cleanup refused changed process identity: $($entry.pid)")
          continue
        }
        if((Get-FileHash -LiteralPath $current.ExecutablePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $exeHash){
          $errors.Add("cleanup refused changed executable bytes: $($entry.pid)")
          continue
        }
        $handle=[DLTBackgroundNative]::OpenProcess(0x101001,$false,$entry.pid)
        if($handle -eq [IntPtr]::Zero){ throw 'cannot open verified owned process handle' }
        [long]$created=0; [long]$exited=0; [long]$kernel=0; [long]$user=0
        if(-not [DLTBackgroundNative]::GetProcessTimes($handle,[ref]$created,[ref]$exited,[ref]$kernel,[ref]$user)){
          throw 'cannot query owned process handle creation identity'
        }
        $nativeCreated=[DateTime]::FromFileTimeUtc($created)
        $expectedCreated=[DateTime]::Parse($entry.creation_time).ToUniversalTime()
        # Normalize only the documented microsecond precision of the CIM token.
        if($nativeCreated.AddTicks(-($nativeCreated.Ticks % 10)) -ne $expectedCreated.AddTicks(-($expectedCreated.Ticks % 10))){
          throw 'cleanup refused changed handle creation identity'
        }
        $nativePath=[System.Text.StringBuilder]::new(32768)
        [int]$nativeLength=$nativePath.Capacity
        if(-not [DLTBackgroundNative]::QueryFullProcessImageName($handle,0,$nativePath,[ref]$nativeLength) -or
           -not [string]::Equals($nativePath.ToString(),$entry.exe_path,[StringComparison]::OrdinalIgnoreCase)){
          throw 'cleanup refused changed handle executable path'
        }
        if([DLTBackgroundNative]::WaitForSingleObject($handle,0) -ne 0 -and
           -not [DLTBackgroundNative]::TerminateProcess($handle,2)){
          throw 'cannot terminate verified owned process handle'
        }
      }
    } catch { $errors.Add('owned process cleanup: ' + $_.Exception.Message) }
    finally { if($handle -ne [IntPtr]::Zero){ $null=[DLTBackgroundNative]::CloseHandle($handle) } }
  }
  $watch.Stop()
  if($null -eq $previousData){ Remove-Item Env:GLP_DATA_DIR -ErrorAction SilentlyContinue }
  else { $env:GLP_DATA_DIR=$previousData }
  try { $report.exe_sha256_after=(Get-FileHash -LiteralPath $main -Algorithm SHA256).Hash.ToLowerInvariant() }
  catch { $errors.Add('cannot hash executable after observation: ' + $_.Exception.Message) }
  $report.launch=$launchObj
  $report.worker_status=$statusObj
  $report.observer=[ordered]@{
    clock_origin='observer_stopwatch_start'; launcher_pid=$(if($null -ne $p){[int]$p.Id}else{$null})
    launcher_exit_code=$(if($null -ne $launcherExit){[int]$p.ExitCode}else{$null})
    launcher_exit_offset_seconds=$launcherExit; launch_started_at=$launchStarted.ToString('o')
    elapsed_seconds=$watch.Elapsed.TotalSeconds; max_sample_gap_seconds=5
    samples=$samples.ToArray(); final_status_observed_offset_seconds=$finalStatusOffset
  }
  $report.errors=$errors.ToArray()
  $report.status=$(if($errors.Count -eq 0){'PASS'}else{'FAIL'})
  try {
    $candidate=Join-Path $work 'candidate-report.json'
    Write-CreateOnlyJson $candidate $report
    $verification=& python (Join-Path $PSScriptRoot 'verify_background_acceptance.py') `
      --report $candidate --request $requestPath --sha $env:GITHUB_SHA `
      --run-id $env:GITHUB_RUN_ID --run-attempt $env:GITHUB_RUN_ATTEMPT `
      --exe-sha256 $exeHash --exe-path $main
    $verificationCode=$LASTEXITCODE
    $verificationObj=($verification -join "`n") | ConvertFrom-Json
    Write-CreateOnlyJson (Join-Path $work 'verification.json') $verificationObj
    if($verificationCode -ne 0 -or $verificationObj.status -ne 'PASS'){
      foreach($message in $verificationObj.errors){ $errors.Add([string]$message) }
      if($verificationCode -ne 0 -and @($verificationObj.errors).Count -eq 0){ $errors.Add("verifier exit=$verificationCode") }
    }
  } catch { $errors.Add('pure verifier failed: ' + $_.Exception.Message) }
  $report.errors=$errors.ToArray()
  $report.status=$(if($errors.Count -eq 0){'PASS'}else{'FAIL'})
  Write-CreateOnlyJson $evidence $report
}
Get-Content -LiteralPath $evidence
if($report.status -ne 'PASS'){ throw 'background exact-EXE continuity acceptance failed; failure evidence retained' }
