param(
  [Parameter(Mandatory=$true)][string]$UpdaterExe,
  [Parameter(Mandatory=$true)][string]$CurrentMainExe,
  [Parameter(Mandatory=$true)][string]$UpdaterEvidencePath,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [Parameter(Mandatory=$true)][string]$CurrentVersion,
  [Parameter(Mandatory=$true)][string]$PreviousVersion
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Json([object]$Value,[string]$Path){
  $dir=Split-Path -Parent $Path
  if($dir){ New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  ($Value | ConvertTo-Json -Depth 14) + [Environment]::NewLine |
    Set-Content -LiteralPath $Path -Encoding utf8
}
function Sha([string]$Path){
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Is-Semver([string]$Value){
  return $Value -match '^\d+\.\d+\.\d+$'
}

$repo=$env:GITHUB_REPOSITORY
$event=$env:GITHUB_EVENT_NAME
$ref=$env:GITHUB_REF
$runId=$env:GITHUB_RUN_ID
$sha=$env:GITHUB_SHA
$targetRepo='douluo511/Geometry-Lotto-Pro-DLT'
$report=[ordered]@{
  schema='dlt-real-release-update-acceptance-v1'
  status='PENDING'
  github_repository=$repo
  github_event=$event
  github_ref=$ref
  github_sha=$sha
  github_run_id=$runId
  previous_version=$PreviousVersion
  current_version=$CurrentVersion
  updater_real_network='PENDING'
}

try {
  if(-not (Is-Semver $PreviousVersion) -or -not (Is-Semver $CurrentVersion)){
    throw 'PreviousVersion and CurrentVersion must be stable x.y.z values'
  }

  if($repo -ne $targetRepo -or $ref -ne 'refs/heads/main' -or $event -notin @('push','workflow_dispatch')){
    $report.status='SKIPPED'
    $report.reason='real software release acceptance is only valid on independent production repository main'
    Write-Json $report $EvidencePath
    Write-Host ($report | ConvertTo-Json -Compress -Depth 14)
    exit 0
  }

  if(-not (Get-Command gh -ErrorAction SilentlyContinue)){ throw 'GitHub CLI is required' }
  $updater=(Resolve-Path -LiteralPath $UpdaterExe).Path
  $current=(Resolve-Path -LiteralPath $CurrentMainExe).Path
  $updaterEvidence=(Resolve-Path -LiteralPath $UpdaterEvidencePath).Path
  $updaterJson=Get-Content -LiteralPath $updaterEvidence -Raw | ConvertFrom-Json
  if($updaterJson.status -ne 'PASS'){ throw 'base updater acceptance is not PASS' }
  if([string]$updaterJson.github_sha -ne [string]$sha -or [string]$updaterJson.github_run_id -ne [string]$runId){
    throw 'base updater evidence is not bound to this exact run/SHA'
  }

  $previousTag="v$PreviousVersion"
  $currentTag="v$CurrentVersion"
  $assetName='Geometry_Lotto_Pro_DLT.exe'
  $manifestName="dlt-$CurrentVersion-manifest.json"

  $previousRelease=gh release view $previousTag --repo $targetRepo --json tagName,isPrerelease,assets,url 2>$null | ConvertFrom-Json
  if($LASTEXITCODE -ne 0){ throw "previous release $previousTag is unavailable" }
  if([string]$previousRelease.tagName -ne $previousTag){ throw 'previous release tag mismatch' }
  $previousNames=@($previousRelease.assets | ForEach-Object { $_.name })
  if($previousNames -notcontains $assetName){ throw 'previous release exact EXE asset missing' }

  $currentRelease=gh release view $currentTag --repo $targetRepo --json tagName,isPrerelease,assets,url | ConvertFrom-Json
  if($LASTEXITCODE -ne 0){ throw "current prerelease $currentTag is unavailable" }
  if([string]$currentRelease.tagName -ne $currentTag){ throw 'current release tag mismatch' }
  $currentNames=@($currentRelease.assets | ForEach-Object { $_.name })
  foreach($required in @($assetName,$manifestName)){
    if($currentNames -notcontains $required){ throw "current release missing $required" }
  }

  $temp=Join-Path $env:RUNNER_TEMP ("dlt-real-update-"+[Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $temp | Out-Null
  try {
    gh release download $previousTag --repo $targetRepo --pattern $assetName --dir $temp --clobber
    if($LASTEXITCODE -ne 0){ throw 'failed to download previous exact EXE' }
    $baseline=(Resolve-Path -LiteralPath (Join-Path $temp $assetName)).Path
    $beforeHash=Sha $baseline
    $currentHash=Sha $current
    if($beforeHash -eq $currentHash){ throw 'N and N+1 EXE hashes must differ' }

    $resultPath=Join-Path $temp 'software_update_result.json'
    $manifestUrl="https://github.com/$targetRepo/releases/download/$currentTag/$manifestName"
    $env:GLP_UPDATER_PARENT_PID=[string]$PID
    $p=Start-Process -FilePath $updater -ArgumentList @(
      '--software-update',
      '--result-file',$resultPath,
      '--manifest-url',$manifestUrl,
      '--target-exe',$baseline,
      '--current-version',$PreviousVersion
    ) -PassThru -WindowStyle Hidden
    if(-not $p.WaitForExit(1800*1000)){
      try{ Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }catch{}
      throw 'real software update timed out'
    }
    if(-not (Test-Path -LiteralPath $resultPath)){ throw 'real software update result missing' }
    $result=Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if($p.ExitCode -ne 0 -or $result.status -ne 'PASS'){ throw 'Exact Updater real software update failed' }
    if([string]$result.updater_exe_sha256 -ne (Sha $updater)){ throw 'real update evidence does not bind exact Updater EXE' }
    if($result.parent_pid_match -ne $true){ throw 'real update did not prove independent updater process' }

    $installedHash=Sha $baseline
    if($installedHash -ne $currentHash){ throw 'installed N+1 EXE hash differs from current exact build' }
    if([string]$result.service_result.manifest.version -ne $CurrentVersion){ throw 'downloaded manifest version mismatch' }
    if([string]$result.service_result.manifest.artifact_sha256 -ne $currentHash){ throw 'manifest hash does not bind current exact EXE' }
    if([string]$result.service_result.install.status -ne 'PASS'){ throw 'atomic software install did not PASS' }
    if([string]$result.service_result.install.installed_sha256 -ne $currentHash){ throw 'install evidence hash mismatch' }

    $manifestReceipt=$result.service_result.manifest_receipt
    $artifactReceipt=$result.service_result.artifact_receipt
    if([string]$manifestReceipt.status -ne 'PASS' -or [string]$artifactReceipt.status -ne 'PASS'){
      throw 'release HTTPS receipts are not PASS'
    }
    if(-not ([string]$manifestReceipt.final_url).StartsWith('https://') -or -not ([string]$artifactReceipt.final_url).StartsWith('https://')){
      throw 'release update was not HTTPS end-to-end'
    }

    $report.status='PASS'
    $report.updater_real_network='PASS'
    $report.previous_exe_sha256=$beforeHash
    $report.current_exe_sha256=$currentHash
    $report.installed_exe_sha256=$installedHash
    $report.updater_exe_sha256=Sha $updater
    $report.manifest_url=$manifestUrl
    $report.manifest_receipt=$manifestReceipt
    $report.artifact_receipt=$artifactReceipt
    $report.atomic_install=$result.service_result.install
    $report.previous_release_url=[string]$previousRelease.url
    $report.current_release_url=[string]$currentRelease.url

    $base=Get-Content -LiteralPath $updaterEvidence -Raw | ConvertFrom-Json
    $base.updater_real_network='PASS'
    if($base.PSObject.Properties.Name -contains 'software_release_reason'){
      $base.PSObject.Properties.Remove('software_release_reason')
    }
    $base | Add-Member -NotePropertyName software_release_update -NotePropertyValue ([ordered]@{
      schema=$report.schema
      evidence_file=(Split-Path -Leaf $EvidencePath)
      previous_version=$PreviousVersion
      current_version=$CurrentVersion
      previous_exe_sha256=$beforeHash
      installed_exe_sha256=$installedHash
      exact_current_exe_sha256=$currentHash
      manifest_url=$manifestUrl
      status='PASS'
    }) -Force
    Write-Json $base $updaterEvidence
  }
  finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
  }
}
catch {
  $report.status='FAIL'
  $report.error="$($_.Exception.GetType().Name): $($_.Exception.Message)"
}
finally {
  $report.completed_at_utc=[DateTime]::UtcNow.ToString('o')
  Write-Json $report $EvidencePath
}
Write-Host ($report | ConvertTo-Json -Compress -Depth 14)
if($report.status -eq 'FAIL'){ exit 2 }
if($report.status -eq 'PASS'){ exit 0 }
exit 2
