param(
  [Parameter(Mandatory = $true)][string]$CurrentExportDir,
  [Parameter(Mandatory = $true)][string]$TargetRepo,
  [Parameter(Mandatory = $true)][ValidateSet("public", "private")][string]$Visibility,
  [Parameter(Mandatory = $true)][string]$ExpectedCurrentSourceCommit,
  [Parameter(Mandatory = $true)][string]$ExpectedCurrentManifestSha256,
  [Parameter(Mandatory = $true)][string]$ExpectedCurrentSumsSha256,
  [Parameter(Mandatory = $true)][string]$ExpectedBaselineManifestSha256,
  [Parameter(Mandatory = $true)][string]$ExpectedBaselineSumsSha256,
  [Parameter(Mandatory = $true)][string]$ExpectedBaselineReleaseTag,
  [Parameter(Mandatory = $true)][string]$ExpectedBaselineExeSha256,
  [switch]$PlanOnly,
  [string]$EvidencePath = "dlt-baseline-to-current-transition.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedTarget = "douluo511/Geometry-Lotto-Pro-DLT"
$ExpectedBaselineSchema = "dlt-current-main-release-baseline-v2"
$ExpectedCurrentSchema = "dlt-independent-export-v4"
$ExpectedBaselineAssetName = "Geometry_Lotto_Pro_DLT.exe"
$FrozenCurrentSourceCommit = "c2b0db6876d2aae874f8cf4d08f52455c8eaf152"
$FrozenCurrentManifestSha256 = "e53373a56bd8da1948f26aaf7fae6a18a7bbfd65e44a1b1bf9d651ab72a9c87f"
$FrozenCurrentSumsSha256 = "5ea3de9d08962e57f677882441b51de6f7022019979aa5db87888bae7422cc11"
$FrozenBaselineManifestSha256 = "b026ce858f1a6c4d6983cc678beb40ce091837a2bb6e8ecd85808b32da5edf8a"
$FrozenBaselineSumsSha256 = "15e337393f71ce08ef13b22f350cba9491bbe5611de18b931c1c4ee3c88ae30b"
$FrozenBaselineExeSha256 = "f70ad5cf2341545d4630526020cf93ae76cacb405ab84fd3c44419201c62ee04"
$FrozenBaselineReleaseTag = "v2.1.1"

function Write-JsonEvidence {
  param([hashtable]$Payload, [string]$Path)
  $dir = Split-Path -Parent $Path
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  ($Payload | ConvertTo-Json -Depth 16) + [Environment]::NewLine | Set-Content -LiteralPath $Path -Encoding utf8
}

function Test-FullSha {
  param([string]$Value)
  return $Value -match '^[0-9a-fA-F]{40}$'
}

function Test-Sha256 {
  param([string]$Value)
  return $Value -match '^[0-9a-fA-F]{64}$'
}

function Get-Sha256 {
  param([string]$Path)
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-Gh {
  param([string[]]$Arguments, [switch]$AllowFailure)
  if (-not $Arguments -or $Arguments.Count -eq 0) { throw "gh arguments required" }
  $output = & gh @Arguments 2>&1
  $code = $LASTEXITCODE
  if (-not $AllowFailure -and $code -ne 0) {
    throw "gh command failed with exit code $code : $($output -join [Environment]::NewLine)"
  }
  return [pscustomobject]@{ ExitCode = $code; Output = @($output) }
}

function Invoke-Git {
  param([string[]]$Arguments, [string]$WorkingDirectory)
  if (-not $Arguments -or $Arguments.Count -eq 0) { throw "git arguments required" }
  if ($WorkingDirectory) {
    $output = & git -C $WorkingDirectory @Arguments 2>&1
  } else {
    $output = & git @Arguments 2>&1
  }
  $code = $LASTEXITCODE
  if ($code -ne 0) {
    throw "git command failed with exit code $code : $($output -join [Environment]::NewLine)"
  }
  return ,@($output)
}

function Copy-SeedWithoutGitMetadata {
  param([string]$Source, [string]$Destination)
  if (Test-Path -LiteralPath $Destination) {
    Remove-Item -LiteralPath $Destination -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
    if ($item.Name -ieq ".git") { continue }
    Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force
  }
}

function Invoke-BootstrapPlan {
  param(
    [string]$ExportDir,
    [string]$Repo,
    [string]$RepoVisibility,
    [string]$ExpectedCommit,
    [string]$OutputPath
  )
  $bootstrap = Join-Path $PSScriptRoot "bootstrap_independent_repo.ps1"
  if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) {
    throw "bootstrap_independent_repo.ps1 missing"
  }
  & $bootstrap -ExportDir $ExportDir -TargetRepo $Repo -Visibility $RepoVisibility -ExpectedSourceCommit $ExpectedCommit -PlanOnly -EvidencePath $OutputPath
  if ($LASTEXITCODE -ne 0) { throw "bootstrap PlanOnly validation failed" }
  $result = Get-Content -LiteralPath $OutputPath -Raw -Encoding utf8 | ConvertFrom-Json
  if ([string]$result.status -ne "PASS") { throw "bootstrap PlanOnly evidence not PASS" }
  if ([string]$result.remote_verification -ne "NOT_RUN_PLAN_ONLY") {
    throw "bootstrap PlanOnly unexpectedly performed remote verification"
  }
  return $result
}

function Assert-CurrentSeed {
  param([object]$Plan)
  if ([string]$Plan.source.schema -ne $ExpectedCurrentSchema) { throw "current seed schema mismatch" }
  if ([string]$Plan.source.source_commit -ne $ExpectedCurrentSourceCommit.ToLowerInvariant()) { throw "current seed source commit mismatch" }
  if ([string]$Plan.source.manifest_sha256 -ne $ExpectedCurrentManifestSha256.ToLowerInvariant()) { throw "current seed manifest SHA mismatch" }
  if ([string]$Plan.source.sums_sha256 -ne $ExpectedCurrentSumsSha256.ToLowerInvariant()) { throw "current seed checksum-list SHA mismatch" }
  if ([int]$Plan.source.file_count -ne 38) { throw "current seed must contain the post-background 38-file product" }
}

function Assert-BaselineSeed {
  param([object]$Plan)
  if ([string]$Plan.source.schema -ne $ExpectedBaselineSchema) { throw "remote baseline schema mismatch" }
  if ([string]$Plan.source.source_commit -ne $ExpectedCurrentSourceCommit.ToLowerInvariant()) { throw "remote baseline source commit mismatch" }
  if ([string]$Plan.source.manifest_sha256 -ne $ExpectedBaselineManifestSha256.ToLowerInvariant()) { throw "remote baseline manifest SHA mismatch" }
  if ([string]$Plan.source.sums_sha256 -ne $ExpectedBaselineSumsSha256.ToLowerInvariant()) { throw "remote baseline checksum-list SHA mismatch" }
  if ([int]$Plan.source.file_count -ne 38) { throw "remote baseline must contain the post-background 38-file product" }
}

if ($TargetRepo -ne $ExpectedTarget) { throw "transition is restricted to $ExpectedTarget" }
if (-not (Test-FullSha -Value $ExpectedCurrentSourceCommit)) { throw "ExpectedCurrentSourceCommit must be a full Git SHA" }
foreach ($value in @($ExpectedCurrentManifestSha256,$ExpectedCurrentSumsSha256,$ExpectedBaselineManifestSha256,$ExpectedBaselineSumsSha256,$ExpectedBaselineExeSha256)) {
  if (-not (Test-Sha256 -Value $value)) { throw "all expected digest values must be 64-hex SHA256" }
}
if ($ExpectedCurrentSourceCommit.ToLowerInvariant() -ne $FrozenCurrentSourceCommit) { throw "current source commit is not the frozen transition source" }
if ($ExpectedCurrentManifestSha256.ToLowerInvariant() -ne $FrozenCurrentManifestSha256) { throw "current manifest SHA is not the frozen transition manifest" }
if ($ExpectedCurrentSumsSha256.ToLowerInvariant() -ne $FrozenCurrentSumsSha256) { throw "current checksum-list SHA is not the frozen transition checksum list" }
if ($ExpectedBaselineManifestSha256.ToLowerInvariant() -ne $FrozenBaselineManifestSha256) { throw "baseline manifest SHA is not the frozen transition baseline" }
if ($ExpectedBaselineSumsSha256.ToLowerInvariant() -ne $FrozenBaselineSumsSha256) { throw "baseline checksum-list SHA is not the frozen transition baseline" }
if ($ExpectedBaselineExeSha256.ToLowerInvariant() -ne $FrozenBaselineExeSha256) { throw "baseline EXE SHA is not the frozen transition baseline" }
if ($ExpectedBaselineReleaseTag -ne $FrozenBaselineReleaseTag) { throw "baseline release tag is not the frozen transition tag" }

$currentRoot = (Resolve-Path -LiteralPath $CurrentExportDir).Path
$currentPlanPath = Join-Path ([System.IO.Path]::GetTempPath()) ("dlt-current-plan-" + [Guid]::NewGuid().ToString("N") + ".json")
$baselinePlanPath = Join-Path ([System.IO.Path]::GetTempPath()) ("dlt-baseline-plan-" + [Guid]::NewGuid().ToString("N") + ".json")
$verifyPlanPath = Join-Path ([System.IO.Path]::GetTempPath()) ("dlt-verify-plan-" + [Guid]::NewGuid().ToString("N") + ".json")
$cloneRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("dlt-transition-clone-" + [Guid]::NewGuid().ToString("N"))
$baselineCopy = Join-Path ([System.IO.Path]::GetTempPath()) ("dlt-transition-baseline-" + [Guid]::NewGuid().ToString("N"))
$verifyClone = Join-Path ([System.IO.Path]::GetTempPath()) ("dlt-transition-verify-" + [Guid]::NewGuid().ToString("N"))
$verifyCopy = Join-Path ([System.IO.Path]::GetTempPath()) ("dlt-transition-current-" + [Guid]::NewGuid().ToString("N"))
$releaseTemp = Join-Path ([System.IO.Path]::GetTempPath()) ("dlt-transition-release-" + [Guid]::NewGuid().ToString("N"))

$evidence = [ordered]@{
  schema = "dlt-baseline-to-current-transition-v1"
  status = "PENDING"
  target_repository = $TargetRepo
  visibility = $Visibility
  plan_only = [bool]$PlanOnly
  expected_current_source_commit = $ExpectedCurrentSourceCommit.ToLowerInvariant()
  expected_current_manifest_sha256 = $ExpectedCurrentManifestSha256.ToLowerInvariant()
  expected_current_sums_sha256 = $ExpectedCurrentSumsSha256.ToLowerInvariant()
  expected_baseline_manifest_sha256 = $ExpectedBaselineManifestSha256.ToLowerInvariant()
  expected_baseline_sums_sha256 = $ExpectedBaselineSumsSha256.ToLowerInvariant()
  expected_baseline_release_tag = $ExpectedBaselineReleaseTag
  expected_baseline_exe_sha256 = $ExpectedBaselineExeSha256.ToLowerInvariant()
  started_at_utc = [DateTime]::UtcNow.ToString("o")
  current_source = $null
  remote_baseline = $null
  baseline_release = $null
  pushed_current_main = $false
  remote_current_verification = "PENDING"
}

try {
  $currentPlan = Invoke-BootstrapPlan -ExportDir $currentRoot -Repo $TargetRepo -RepoVisibility $Visibility -ExpectedCommit $ExpectedCurrentSourceCommit -OutputPath $currentPlanPath
  Assert-CurrentSeed -Plan $currentPlan
  $evidence["current_source"] = $currentPlan.source

  if ($PlanOnly) {
    $evidence["status"] = "PASS"
    $evidence["remote_current_verification"] = "NOT_RUN_PLAN_ONLY"
    $evidence["completed_at_utc"] = [DateTime]::UtcNow.ToString("o")
    Write-JsonEvidence -Payload $evidence -Path $EvidencePath
    Write-Host ($evidence | ConvertTo-Json -Compress -Depth 16)
    exit 0
  }

  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "GitHub CLI required" }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git required" }

  $auth = Invoke-Gh -Arguments @("auth","status") -AllowFailure
  if ($auth.ExitCode -ne 0) { throw "gh is not authenticated" }
  Invoke-Gh -Arguments @("auth","setup-git") | Out-Null

  $view = Invoke-Gh -Arguments @("repo","view",$TargetRepo,"--json","nameWithOwner,visibility,defaultBranchRef") -AllowFailure
  if ($view.ExitCode -ne 0) { throw "target independent repository does not exist or is not accessible" }
  $repoInfo = (($view.Output -join [Environment]::NewLine) | ConvertFrom-Json)
  if ([string]$repoInfo.nameWithOwner -ne $TargetRepo) { throw "remote repository identity mismatch" }
  if (([string]$repoInfo.visibility).ToLowerInvariant() -ne $Visibility.ToLowerInvariant()) { throw "remote repository visibility mismatch" }
  if ([string]$repoInfo.defaultBranchRef.name -ne "main") { throw "remote default branch must be main" }

  Invoke-Git -Arguments @("-c","core.autocrlf=false","clone","--depth","1","https://github.com/$TargetRepo.git",$cloneRoot) | Out-Null
  Copy-SeedWithoutGitMetadata -Source $cloneRoot -Destination $baselineCopy

  $baselinePlan = Invoke-BootstrapPlan -ExportDir $baselineCopy -Repo $TargetRepo -RepoVisibility $Visibility -ExpectedCommit $ExpectedCurrentSourceCommit -OutputPath $baselinePlanPath
  Assert-BaselineSeed -Plan $baselinePlan
  $evidence["remote_baseline"] = $baselinePlan.source

  $releaseRaw = Invoke-Gh -Arguments @("release","view",$ExpectedBaselineReleaseTag,"--repo",$TargetRepo,"--json","tagName,isPrerelease,assets,url")
  $release = (($releaseRaw.Output -join [Environment]::NewLine) | ConvertFrom-Json)
  if ([string]$release.tagName -ne $ExpectedBaselineReleaseTag) { throw "baseline release tag mismatch" }
  if ($release.isPrerelease -ne $true) { throw "baseline release must remain prerelease before N-to-N+1 acceptance" }
  $assetNames = @($release.assets | ForEach-Object { [string]$_.name })
  if ($assetNames -notcontains $ExpectedBaselineAssetName) { throw "baseline release exact EXE asset missing" }

  New-Item -ItemType Directory -Force -Path $releaseTemp | Out-Null
  Invoke-Gh -Arguments @("release","download",$ExpectedBaselineReleaseTag,"--repo",$TargetRepo,"--pattern",$ExpectedBaselineAssetName,"--dir",$releaseTemp,"--clobber") | Out-Null
  $releaseExe = Join-Path $releaseTemp $ExpectedBaselineAssetName
  if (-not (Test-Path -LiteralPath $releaseExe -PathType Leaf)) { throw "downloaded baseline release EXE missing" }
  $releaseExeSha = Get-Sha256 -Path $releaseExe
  if ($releaseExeSha -ne $ExpectedBaselineExeSha256.ToLowerInvariant()) { throw "baseline release EXE SHA mismatch" }
  $evidence["baseline_release"] = [ordered]@{
    tag = [string]$release.tagName
    prerelease = [bool]$release.isPrerelease
    url = [string]$release.url
    asset_name = $ExpectedBaselineAssetName
    asset_sha256 = $releaseExeSha
    status = "PASS"
  }

  foreach ($item in Get-ChildItem -LiteralPath $cloneRoot -Force) {
    if ($item.Name -ieq ".git") { continue }
    Remove-Item -LiteralPath $item.FullName -Recurse -Force
  }
  foreach ($item in Get-ChildItem -LiteralPath $currentRoot -Force) {
    if ($item.Name -ieq ".git") { continue }
    Copy-Item -LiteralPath $item.FullName -Destination $cloneRoot -Recurse -Force
  }

  Invoke-Git -WorkingDirectory $cloneRoot -Arguments @("config","core.autocrlf","false") | Out-Null
  Invoke-Git -WorkingDirectory $cloneRoot -Arguments @("config","user.name","Verified DLT Release Transition") | Out-Null
  Invoke-Git -WorkingDirectory $cloneRoot -Arguments @("config","user.email","bootstrap@users.noreply.github.com") | Out-Null
  Invoke-Git -WorkingDirectory $cloneRoot -Arguments @("add","--all") | Out-Null
  $pending = (Invoke-Git -WorkingDirectory $cloneRoot -Arguments @("status","--porcelain")) -join [Environment]::NewLine
  if ([string]::IsNullOrWhiteSpace($pending)) { throw "baseline-to-current transition produced no Git changes" }
  Invoke-Git -WorkingDirectory $cloneRoot -Arguments @("commit","-m","Advance verified DLT baseline v2.1.1 to current v2.1.2") | Out-Null
  $transitionCommit = (Invoke-Git -WorkingDirectory $cloneRoot -Arguments @("rev-parse","HEAD"))[-1].Trim()
  Invoke-Git -WorkingDirectory $cloneRoot -Arguments @("push","origin","main") | Out-Null
  $evidence["pushed_current_main"] = $true
  $evidence["transition_commit"] = $transitionCommit

  Invoke-Git -Arguments @("-c","core.autocrlf=false","clone","--depth","1","https://github.com/$TargetRepo.git",$verifyClone) | Out-Null
  Copy-SeedWithoutGitMetadata -Source $verifyClone -Destination $verifyCopy
  $verifyPlan = Invoke-BootstrapPlan -ExportDir $verifyCopy -Repo $TargetRepo -RepoVisibility $Visibility -ExpectedCommit $ExpectedCurrentSourceCommit -OutputPath $verifyPlanPath
  Assert-CurrentSeed -Plan $verifyPlan

  $remoteCommit = (Invoke-Git -WorkingDirectory $verifyClone -Arguments @("rev-parse","HEAD"))[-1].Trim()
  if ($remoteCommit -ne $transitionCommit) { throw "remote main transition commit mismatch" }

  $evidence["remote_current_verification"] = "PASS"
  $evidence["remote_current_source"] = $verifyPlan.source
  $evidence["remote_main_commit"] = $remoteCommit
  $evidence["status"] = "PASS"
}
catch {
  $evidence["status"] = "FAIL"
  $evidence["error"] = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
}
finally {
  foreach ($path in @($currentPlanPath,$baselinePlanPath,$verifyPlanPath,$cloneRoot,$baselineCopy,$verifyClone,$verifyCopy,$releaseTemp)) {
    if (Test-Path -LiteralPath $path) {
      $item = Get-Item -LiteralPath $path -Force
      if ($item.PSIsContainer) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
      } else {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
      }
    }
  }
  $evidence["completed_at_utc"] = [DateTime]::UtcNow.ToString("o")
  Write-JsonEvidence -Payload $evidence -Path $EvidencePath
}

Write-Host ($evidence | ConvertTo-Json -Compress -Depth 16)
if ($evidence["status"] -ne "PASS") { exit 2 }
exit 0
