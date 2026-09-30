param(
  [Parameter(Mandatory = $true)][string]$BaseExe,
  [Parameter(Mandatory = $true)][string]$CandidateExe,
  [Parameter(Mandatory = $true)][string]$BaseVersion,
  [Parameter(Mandatory = $true)][string]$CandidateVersion,
  [Parameter(Mandatory = $true)][string]$BaseSelfTest,
  [Parameter(Mandatory = $true)][string]$CandidateSelfTest,
  [string]$TargetRepo = "douluo511/Geometry-Lotto-Pro-SSQ",
  [string]$BaseTag,
  [string]$CandidateTag,
  [string]$ManifestTool = "tools/prepare_ssq_release_manifest.py",
  [switch]$PlanOnly,
  [switch]$UseExistingExactReleases,
  [string]$EvidencePath = "ssq-release-pair-evidence.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ExpectedRepo = "douluo511/Geometry-Lotto-Pro-SSQ"
$ExpectedArtifact = "Geometry_Lotto_Pro_SSQ_Windows_Verified.exe"
$ManifestName = "ssq-software-update-manifest.json"

function Sha256([string]$Path) {
  return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-Evidence([hashtable]$Payload) {
  $dir = Split-Path -Parent $EvidencePath
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  ($Payload | ConvertTo-Json -Depth 12) + [Environment]::NewLine |
    Set-Content -LiteralPath $EvidencePath -Encoding utf8
}

function Invoke-Gh([string[]]$Args, [switch]$AllowFailure) {
  $out = & gh @Args 2>&1
  $code = $LASTEXITCODE
  if (-not $AllowFailure -and $code -ne 0) {
    throw "gh failed ($code): $($out -join [Environment]::NewLine)"
  }
  return [pscustomobject]@{ ExitCode = $code; Output = @($out) }
}

function Assert-ExactFile([string]$Path, [string]$Role) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Role EXE missing: $Path" }
  $item = Get-Item -LiteralPath $Path -Force
  if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "$Role EXE may not be a symlink/reparse point"
  }
  if ($item.Name -ne $ExpectedArtifact) {
    throw "$Role EXE filename must be $ExpectedArtifact"
  }
}

function Prepare-Manifest(
  [string]$Exe,
  [string]$Version,
  [string]$SelfTest,
  [string]$Tag,
  [string]$Output,
  [string]$PrepEvidence,
  [switch]$Baseline,
  [string]$Base
) {
  $args = @(
    $ManifestTool,
    "--exe", $Exe,
    "--version", $Version,
    "--tag", $Tag,
    "--self-test", $SelfTest,
    "--output", $Output,
    "--evidence", $PrepEvidence
  )
  if ($Baseline) {
    $args += "--baseline"
  } else {
    $args += @("--base-version", $Base)
  }
  $manifestToolOutput = & python @args
  $manifestToolExit = $LASTEXITCODE
  if ($manifestToolExit -ne 0) {
    throw "release manifest preparation failed for ${Version}: $($manifestToolOutput -join [Environment]::NewLine)"
  }
  $proof = Get-Content -LiteralPath $PrepEvidence -Raw -Encoding utf8 | ConvertFrom-Json
  if ($proof.status -ne "PASS") { throw "manifest preparation evidence is not PASS for $Version" }
  return Get-Content -LiteralPath $Output -Raw -Encoding utf8 | ConvertFrom-Json
}

function Verify-Release(
  [string]$Tag,
  [string]$ExpectedExeSha,
  [int64]$ExpectedExeBytes,
  [string]$ExpectedManifestSha
) {
  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("ssq-release-verify-" + [Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  try {
    Invoke-Gh -Args @("release","download",$Tag,"--repo",$TargetRepo,"--pattern",$ExpectedArtifact,"--pattern",$ManifestName,"--dir",$tmp) | Out-Null
    $downloadExe = Join-Path $tmp $ExpectedArtifact
    $downloadManifest = Join-Path $tmp $ManifestName
    if (-not (Test-Path -LiteralPath $downloadExe -PathType Leaf)) { throw "release EXE missing after download: $Tag" }
    if (-not (Test-Path -LiteralPath $downloadManifest -PathType Leaf)) { throw "release manifest missing after download: $Tag" }
    if ((Sha256 $downloadExe) -ne $ExpectedExeSha) { throw "release EXE SHA256 mismatch after download: $Tag" }
    if ([int64](Get-Item -LiteralPath $downloadExe).Length -ne $ExpectedExeBytes) { throw "release EXE byte-size mismatch after download: $Tag" }
    if ((Sha256 $downloadManifest) -ne $ExpectedManifestSha) { throw "release manifest SHA256 mismatch after download: $Tag" }
  } finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$evidence = [ordered]@{
  schema = "ssq-independent-release-pair-v1"
  status = "PENDING"
  repository = $TargetRepo
  plan_only = [bool]$PlanOnly
  use_existing_exact_releases = [bool]$UseExistingExactReleases
  started_at_utc = [DateTime]::UtcNow.ToString("o")
}

try {
  if ($TargetRepo -ne $ExpectedRepo) { throw "TargetRepo must be exactly $ExpectedRepo" }
  if (-not $BaseTag) { $BaseTag = "v$BaseVersion" }
  if (-not $CandidateTag) { $CandidateTag = "v$CandidateVersion" }
  Assert-ExactFile -Path $BaseExe -Role "base"
  Assert-ExactFile -Path $CandidateExe -Role "candidate"
  if (-not (Test-Path -LiteralPath $BaseSelfTest -PathType Leaf)) { throw "base self-test missing" }
  if (-not (Test-Path -LiteralPath $CandidateSelfTest -PathType Leaf)) { throw "candidate self-test missing" }
  if (-not (Test-Path -LiteralPath $ManifestTool -PathType Leaf)) { throw "manifest tool missing" }

  $work = Join-Path ([System.IO.Path]::GetTempPath()) ("ssq-release-pair-" + [Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Force -Path $work | Out-Null
  try {
    $baseDir = Join-Path $work "base"
    $candidateDir = Join-Path $work "candidate"
    New-Item -ItemType Directory -Force -Path $baseDir,$candidateDir | Out-Null
    $baseManifestPath = Join-Path $baseDir $ManifestName
    $candidateManifestPath = Join-Path $candidateDir $ManifestName

    $baseManifest = Prepare-Manifest -Exe $BaseExe -Version $BaseVersion -SelfTest $BaseSelfTest -Tag $BaseTag -Output $baseManifestPath -PrepEvidence (Join-Path $baseDir "prepare-evidence.json") -Baseline
    $candidateManifest = Prepare-Manifest -Exe $CandidateExe -Version $CandidateVersion -SelfTest $CandidateSelfTest -Tag $CandidateTag -Output $candidateManifestPath -PrepEvidence (Join-Path $candidateDir "prepare-evidence.json") -Base $BaseVersion

    $baseExeSha = Sha256 $BaseExe
    $candidateExeSha = Sha256 $CandidateExe
    $baseManifestSha = Sha256 $baseManifestPath
    $candidateManifestSha = Sha256 $candidateManifestPath

    $evidence["base"] = [ordered]@{
      version = $BaseVersion
      tag = $BaseTag
      exe_sha256 = $baseExeSha
      exe_bytes = [int64](Get-Item -LiteralPath $BaseExe).Length
      manifest_sha256 = $baseManifestSha
      manifest_url = "https://github.com/$TargetRepo/releases/download/$BaseTag/$ManifestName"
      artifact_url = [string]$baseManifest.artifact_url
    }
    $evidence["candidate"] = [ordered]@{
      version = $CandidateVersion
      tag = $CandidateTag
      exe_sha256 = $candidateExeSha
      exe_bytes = [int64](Get-Item -LiteralPath $CandidateExe).Length
      manifest_sha256 = $candidateManifestSha
      manifest_url = "https://github.com/$TargetRepo/releases/download/$CandidateTag/$ManifestName"
      artifact_url = [string]$candidateManifest.artifact_url
    }

    if ($PlanOnly) {
      $evidence["status"] = "PASS"
      $evidence["remote_verification"] = "NOT_RUN_PLAN_ONLY"
      $evidence["completed_at_utc"] = [DateTime]::UtcNow.ToString("o")
      Write-Evidence $evidence
      Write-Host ($evidence | ConvertTo-Json -Compress -Depth 12)
      exit 0
    }

    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "GitHub CLI (gh) required" }
    $auth = Invoke-Gh -Args @("auth","status") -AllowFailure
    if ($auth.ExitCode -ne 0) { throw "gh is not authenticated" }
    $repoView = Invoke-Gh -Args @("repo","view",$TargetRepo,"--json","nameWithOwner,defaultBranchRef")
    $repoInfo = (($repoView.Output -join [Environment]::NewLine) | ConvertFrom-Json)
    if ([string]$repoInfo.nameWithOwner -ne $TargetRepo) { throw "remote repository identity mismatch" }
    if ([string]$repoInfo.defaultBranchRef.name -ne "main") { throw "remote default branch must be main" }

    foreach ($pair in @(
      [ordered]@{ Tag=$BaseTag; Exe=$BaseExe; Manifest=$baseManifestPath; ExeSha=$baseExeSha; ExeBytes=[int64](Get-Item $BaseExe).Length; ManifestSha=$baseManifestSha; Title="SSQ $BaseVersion updater baseline" },
      [ordered]@{ Tag=$CandidateTag; Exe=$CandidateExe; Manifest=$candidateManifestPath; ExeSha=$candidateExeSha; ExeBytes=[int64](Get-Item $CandidateExe).Length; ManifestSha=$candidateManifestSha; Title="SSQ $CandidateVersion candidate" }
    )) {
      $view = Invoke-Gh -Args @("release","view",$pair.Tag,"--repo",$TargetRepo,"--json","tagName,isPrerelease") -AllowFailure
      if ($view.ExitCode -eq 0) {
        if (-not $UseExistingExactReleases) { throw "release already exists: $($pair.Tag)" }
      } else {
        Invoke-Gh -Args @(
          "release","create",$pair.Tag,
          $pair.Exe,
          $pair.Manifest,
          "--repo",$TargetRepo,
          "--prerelease",
          "--title",$pair.Title,
          "--notes","Machine-bound staging release for independent updater acceptance. Not Portfolio FINAL."
        ) | Out-Null
      }
      Verify-Release -Tag $pair.Tag -ExpectedExeSha $pair.ExeSha -ExpectedExeBytes $pair.ExeBytes -ExpectedManifestSha $pair.ManifestSha
    }

    $evidence["status"] = "PASS"
    $evidence["remote_verification"] = "PASS"
    $evidence["completed_at_utc"] = [DateTime]::UtcNow.ToString("o")
    Write-Evidence $evidence
    Write-Host ($evidence | ConvertTo-Json -Compress -Depth 12)
  } finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
  }
} catch {
  $evidence["status"] = "FAIL"
  $evidence["error"] = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
  $evidence["completed_at_utc"] = [DateTime]::UtcNow.ToString("o")
  Write-Evidence $evidence
  Write-Host ($evidence | ConvertTo-Json -Compress -Depth 12)
  exit 2
}
