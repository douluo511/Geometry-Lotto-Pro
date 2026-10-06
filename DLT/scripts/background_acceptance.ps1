param(
  [Parameter(Mandatory=$true)][string]$MainExe,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [int]$TimeoutSeconds = 1800
)

$ErrorActionPreference = 'Stop'
$main=(Resolve-Path $MainExe).Path
$exeHash=(Get-FileHash $main -Algorithm SHA256).Hash.ToLowerInvariant()
$evidence=[System.IO.Path]::GetFullPath($EvidencePath)
$work=Join-Path ([System.IO.Path]::GetDirectoryName($evidence)) ("background-" + [Guid]::NewGuid().ToString("N"))
$data=Join-Path $work "data"
$launch=Join-Path $work "launch.json"
New-Item -ItemType Directory -Force $data | Out-Null

$previousData=$env:GLP_DATA_DIR
try {
  $env:GLP_DATA_DIR=$data
  $p=Start-Process -FilePath $main -ArgumentList @(
    "--background-launch",
    "--background-interval-seconds","2",
    "--background-max-cycles","1",
    "--result-file",$launch
  ) -PassThru -Wait -WindowStyle Hidden
  if($p.ExitCode -ne 0){ throw "background launcher failed: exit=$($p.ExitCode)" }
  if(-not (Test-Path $launch)){ throw "background launch evidence missing" }

  $launchObj=Get-Content $launch -Raw | ConvertFrom-Json
  $statusPath=Join-Path $data "background_status.json"
  $deadline=(Get-Date).AddSeconds($TimeoutSeconds)
  $statusObj=$null
  while((Get-Date) -lt $deadline){
    if(Test-Path $statusPath){
      try {
        $statusObj=Get-Content $statusPath -Raw | ConvertFrom-Json
        if($statusObj.worker_exit -eq "MAX_CYCLES_REACHED"){ break }
      } catch {}
    }
    Start-Sleep -Milliseconds 500
  }
  if($null -eq $statusObj -or $statusObj.worker_exit -ne "MAX_CYCLES_REACHED"){
    throw "background worker did not complete one detached live cycle"
  }

  $last=$statusObj.last_cycle
  $checks=[ordered]@{
    launch_status=($launchObj.status -eq "PASS")
    launch_shell_false=($launchObj.shell -eq $false)
    child_is_separate=([int]$launchObj.child_pid -gt 0 -and [int]$launchObj.child_pid -ne [int]$launchObj.parent_pid)
    exact_exe_hash_bound=($launchObj.exe_sha256 -eq $exeHash -and $statusObj.exe_sha256 -eq $exeHash)
    parent_exit_observed=($statusObj.parent_exit_observed -eq $true)
    production_poll_1800=([int]$launchObj.production_poll_seconds -eq 1800 -and [int]$statusObj.production_poll_seconds -eq 1800)
    startup_requires_manual_open=($statusObj.startup_mode -eq "manual_app_launch_required_after_login" -and $statusObj.autostart_registered -eq $false)
    worker_completed_cycle=([int]$statusObj.cycle_count -eq 1 -and $statusObj.worker_exit -eq "MAX_CYCLES_REACHED")
    live_network_pass=($last.status -eq "PASS" -and $last.network_gate -eq "PASS" -and $last.crosscheck_status -eq "PASS")
    next_prediction_frozen=($last.prediction_id -and $last.freeze_hash -and $last.target_issue)
    default_two_front_dan=(@($last.research_dan_front).Count -eq 2)
    production_not_promoted=($last.production_edge_state -eq "NO_EDGE" -and $last.production_dan_state -eq "NULL_DAN")
  }
  $ok=($checks.Values -notcontains $false)
  $report=[ordered]@{
    schema="dlt-background-acceptance-v1"
    status=$(if($ok){"PASS"}else{"FAIL"})
    github_sha=$env:GITHUB_SHA
    github_run_id=$env:GITHUB_RUN_ID
    exe_sha256=$exeHash
    production_poll_seconds=1800
    startup_mode="manual_app_launch_required_after_login"
    autostart_registered=$false
    launch=$launchObj
    worker_status=$statusObj
    checks=$checks
  }
  $parent=Split-Path -Parent $evidence
  New-Item -ItemType Directory -Force $parent | Out-Null
  $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $evidence -Encoding utf8
  Get-Content -LiteralPath $evidence
  if(-not $ok){ throw "background exact-EXE acceptance failed" }
}
finally {
  if($null -eq $previousData){ Remove-Item Env:GLP_DATA_DIR -ErrorAction SilentlyContinue }
  else { $env:GLP_DATA_DIR=$previousData }
}
