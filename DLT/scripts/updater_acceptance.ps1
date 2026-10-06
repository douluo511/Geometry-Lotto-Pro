param(
  [Parameter(Mandatory=$true)][string]$UpdaterExe,
  [Parameter(Mandatory=$true)][string]$MainExe,
  [Parameter(Mandatory=$true)][string]$RebuiltUpdaterExe,
  [Parameter(Mandatory=$true)][string]$EvidencePath
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force (Split-Path -Parent $EvidencePath) | Out-Null

$updater=(Resolve-Path $UpdaterExe).Path
$main=(Resolve-Path $MainExe).Path
$rebuilt=(Resolve-Path $RebuiltUpdaterExe).Path
$updaterHash=(Get-FileHash $updater -Algorithm SHA256).Hash.ToLower()
$rebuiltHash=(Get-FileHash $rebuilt -Algorithm SHA256).Hash.ToLower()
$sameHash=($updaterHash -eq $rebuiltHash)

function Invoke-Updater([string[]]$Arguments,[string]$ResultPath,[int]$TimeoutSeconds=900) {
  $env:GLP_UPDATER_PARENT_PID=[string]$PID
  $p=Start-Process -FilePath $updater -ArgumentList $Arguments -PassThru -WindowStyle Hidden
  if(-not $p.WaitForExit($TimeoutSeconds*1000)){
    try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
    throw "Updater timed out: $($Arguments -join ' ')"
  }
  if(-not (Test-Path $ResultPath)){ throw "Updater evidence missing: $ResultPath" }
  $r=Get-Content $ResultPath -Raw | ConvertFrom-Json
  if($p.ExitCode -ne 0 -or $r.status -ne 'PASS'){ throw "Updater exact execution failed: $($Arguments -join ' ')" }
  if($r.updater_exe_sha256 -ne $updaterHash){ throw "Updater evidence hash differs from exact EXE" }
  if(-not $r.parent_pid_match){ throw "Updater did not prove separate parent/child process boundary" }
  return $r
}

$selfPath=(Join-Path (Split-Path -Parent $EvidencePath) "updater_self_test.json")
$softwarePath=(Join-Path (Split-Path -Parent $EvidencePath) "updater_software_self_test.json")
$dataPath=(Join-Path (Split-Path -Parent $EvidencePath) "updater_data_real_network.json")
$repairPath=(Join-Path (Split-Path -Parent $EvidencePath) "updater_data_repair.json")

$self=Invoke-Updater @("--self-test","--result-file",$selfPath) $selfPath 300
$software=Invoke-Updater @("--software-self-test","--result-file",$softwarePath) $softwarePath 300

$dataRoot=Join-Path $env:RUNNER_TEMP ("dlt-updater-data-"+[Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $dataRoot | Out-Null
$env:GLP_DATA_DIR=$dataRoot
$data=Invoke-Updater @("--data-update","--result-file",$dataPath) $dataPath 1800
$repair=Invoke-Updater @("--data-repair","--result-file",$repairPath) $repairPath 900

$processPass=($self.parent_pid_match -and $software.parent_pid_match -and $data.parent_pid_match -and $repair.parent_pid_match)
$rollbackPass=(
  $software.service_result.checks.atomic_replace_success -eq $true -and
  $software.service_result.checks.forced_validation_failure_rolls_back -eq $true -and
  $software.service_result.checks.rollback_hash_restored -eq $true
)
$dataNetworkPass=(
  $data.service_result.network_gate -eq 'PASS' -and
  $data.service_result.crosscheck_status -eq 'PASS'
)
$report=[ordered]@{
  schema='dlt-updater-exact-acceptance-v1'
  status=$(if($processPass -and $rollbackPass -and $sameHash -and $dataNetworkPass){'PASS'}else{'FAIL'})
  github_sha=$env:GITHUB_SHA
  github_run_id=$env:GITHUB_RUN_ID
  main_exe_sha256=(Get-FileHash $main -Algorithm SHA256).Hash.ToLower()
  updater_sha256=$updaterHash
  rebuilt_updater_sha256=$rebuiltHash
  updater_process=$(if($processPass){'PASS'}else{'FAIL'})
  updater_exact_exe=$(if($self.status -eq 'PASS' -and $software.status -eq 'PASS'){'PASS'}else{'FAIL'})
  updater_atomic_rollback=$(if($rollbackPass){'PASS'}else{'FAIL'})
  updater_real_network='PENDING'
  updater_data_real_network=$(if($dataNetworkPass){'PASS'}else{'FAIL'})
  updater_same_hash=$(if($sameHash){'PASS'}else{'FAIL'})
  software_release_reason='independent Geometry-Lotto-Pro-DLT release N->N+1 is not available in this shared repository'
  evidence=[ordered]@{
    self_test=(Split-Path -Leaf $selfPath)
    software_self_test=(Split-Path -Leaf $softwarePath)
    data_real_network=(Split-Path -Leaf $dataPath)
    data_repair=(Split-Path -Leaf $repairPath)
  }
}
$report | ConvertTo-Json -Depth 10 | Set-Content $EvidencePath -Encoding utf8
Get-Content $EvidencePath
if($report.status -ne 'PASS'){ throw 'DLT updater exact acceptance failed' }
