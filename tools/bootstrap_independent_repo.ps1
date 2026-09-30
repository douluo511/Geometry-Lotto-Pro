param(
  [Parameter(Mandatory = $true)]
  [string]$ExportDir,
  [Parameter(Mandatory = $true)]
  [string]$TargetRepo,
  [Parameter(Mandatory = $true)]
  [ValidateSet("public", "private")]
  [string]$Visibility,
  [string]$ExpectedSourceCommit,
  [switch]$UseExistingEmptyRepository,
  [switch]$PlanOnly,
  [string]$EvidencePath = "independent-repo-bootstrap-evidence.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-JsonEvidence {
  param([hashtable]$Payload, [string]$Path)
  $dir = Split-Path -Parent $Path
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  ($Payload | ConvertTo-Json -Depth 12) + [Environment]::NewLine |
    Set-Content -Path $Path -Encoding utf8
}

function Get-Sha256 {
  param([string]$Path)
  return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Test-FullSha {
  param([string]$Value)
  return $Value -match '^[0-9a-fA-F]{40}$'
}

function Assert-RepoName {
  param([string]$Value)
  if ($Value -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw "TargetRepo must be owner/name"
  }
}

function Invoke-Gh {
  param([string[]]$Args, [switch]$AllowFailure)
  $output = & gh @Args 2>&1
  $code = $LASTEXITCODE
  if (-not $AllowFailure -and $code -ne 0) {
    throw "gh command failed with exit code $code: $($output -join [Environment]::NewLine)"
  }
  return [pscustomobject]@{ ExitCode = $code; Output = @($output) }
}

function Invoke-Git {
  param([string[]]$Args, [string]$WorkingDirectory)
  if ($WorkingDirectory) {
    $output = & git -C $WorkingDirectory @Args 2>&1
  } else {
    $output = & git @Args 2>&1
  }
  $code = $LASTEXITCODE
  if ($code -ne 0) {
    throw "git command failed with exit code $code: $($output -join [Environment]::NewLine)"
  }
  return @($output)
}

function Get-RelativeFileList {
  param([string]$Root)
  $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  $rows = @()
  foreach ($item in Get-ChildItem -LiteralPath $Root -Recurse -Force -File) {
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "symlink/reparse point forbidden: $($item.FullName)"
    }
    $full = [System.IO.Path]::GetFullPath($item.FullName)
    if (-not $full.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "file escaped export root: $full"
    }
    $rel = $full.Substring($rootFull.Length + 1).Replace('\','/')
    if ($rel -notin @("MIGRATION_MANIFEST.json","MIGRATION_SHA256SUMS.txt")) {
      $rows += $rel
    }
  }
  return @($rows | Sort-Object -Unique)
}

function Assert-ExportIntegrity {
  param([string]$Root, [string]$Repo, [string]$ExpectedCommit)

  $manifestPath = Join-Path $Root "MIGRATION_MANIFEST.json"
  if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "MIGRATION_MANIFEST.json missing"
  }
  $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json

  $schema = [string]$manifest.schema
  if ($schema -notin @("ssq-independent-repo-export-v1","portfolio-independent-repo-export-v1")) {
    throw "unsupported manifest schema: $schema"
  }
  if ([string]$manifest.source_repository -ne "douluo511/Geometry-Lotto-Pro") {
    throw "unexpected source_repository"
  }
  if ([string]$manifest.target_repository -ne $Repo) {
    throw "target repository mismatch"
  }

  $sourceCommit = [string]$manifest.source_commit
  if (-not (Test-FullSha -Value $sourceCommit)) {
    throw "manifest source_commit must be full SHA"
  }
  $sourceCommit = $sourceCommit.ToLowerInvariant()
  if ($ExpectedCommit) {
    if (-not (Test-FullSha -Value $ExpectedCommit)) {
      throw "ExpectedSourceCommit must be full SHA"
    }
    if ($sourceCommit -ne $ExpectedCommit.ToLowerInvariant()) {
      throw "source commit mismatch"
    }
  }

  $rows = @($manifest.files)
  if ($rows.Count -eq 0) { throw "manifest file list empty" }

  $expected = @{}
  foreach ($row in $rows) {
    $rel = [string]$row.path
    if (-not $rel -or $expected.ContainsKey($rel)) { throw "invalid/duplicate manifest path: $rel" }
    if ($rel.StartsWith("/") -or $rel.Contains("..")) { throw "unsafe manifest path: $rel" }

    $path = Join-Path $Root ($rel.Replace('/',[System.IO.Path]::DirectorySeparatorChar))
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "missing: $rel" }

    $item = Get-Item -LiteralPath $path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "symlink/reparse point forbidden: $rel"
    }
    if ((Get-Sha256 -Path $path) -ne ([string]$row.sha256).ToLowerInvariant()) {
      throw "SHA256 mismatch: $rel"
    }
    if ([int64]$item.Length -ne [int64]$row.bytes) {
      throw "byte-size mismatch: $rel"
    }
    $expected[$rel] = $true
  }

  $actual = @(Get-RelativeFileList -Root $Root)
  if ($actual.Count -ne $expected.Count) { throw "unmanifested/missing file count mismatch" }
  foreach ($rel in $actual) {
    if (-not $expected.ContainsKey($rel)) { throw "unmanifested file: $rel" }
  }

  $sumsPath = Join-Path $Root "MIGRATION_SHA256SUMS.txt"
  if (-not (Test-Path -LiteralPath $sumsPath -PathType Leaf)) {
    throw "MIGRATION_SHA256SUMS.txt missing"
  }

  $expectedSumLines = @($rows | ForEach-Object {
    "$(([string]$_.sha256).ToLowerInvariant())  $([string]$_.path)"
  })
  $actualSumLines = @(Get-Content -LiteralPath $sumsPath -Encoding utf8 |
    ForEach-Object { $_.TrimEnd() } | Where-Object { $_ -ne "" })

  $newline = [Environment]::NewLine
  if (($expectedSumLines -join $newline) -ne ($actualSumLines -join $newline)) {
    throw "checksum list does not exactly match manifest"
  }

  return [ordered]@{
    schema = $schema
    source_repository = [string]$manifest.source_repository
    target_repository = [string]$manifest.target_repository
    source_commit = $sourceCommit
    file_count = $expected.Count
    manifest_sha256 = Get-Sha256 -Path $manifestPath
    sums_sha256 = Get-Sha256 -Path $sumsPath
  }
}

Assert-RepoName -Value $TargetRepo
$root = (Resolve-Path -LiteralPath $ExportDir).Path

$evidence = [ordered]@{
  schema = "independent-repo-bootstrap-v1"
  status = "PENDING"
  target_repository = $TargetRepo
  visibility = $Visibility
  plan_only = [bool]$PlanOnly
  use_existing_empty_repository = [bool]$UseExistingEmptyRepository
  started_at_utc = [DateTime]::UtcNow.ToString("o")
  source = $null
  gh_authenticated = $false
  repository_created = $false
  repository_preexisted = $false
  pushed_main = $false
  remote_verification = "PENDING"
}

try {
  $sourceProof = Assert-ExportIntegrity -Root $root -Repo $TargetRepo -ExpectedCommit $ExpectedSourceCommit
  $evidence["source"] = $sourceProof

  if ($PlanOnly) {
    $evidence["status"] = "PASS"
    $evidence["remote_verification"] = "NOT_RUN_PLAN_ONLY"
    $evidence["completed_at_utc"] = [DateTime]::UtcNow.ToString("o")
    Write-JsonEvidence -Payload $evidence -Path $EvidencePath
    Write-Host ($evidence | ConvertTo-Json -Compress -Depth 12)
    exit 0
  }

  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "GitHub CLI (gh) required" }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git required" }

  $auth = Invoke-Gh -Args @("auth","status") -AllowFailure
  if ($auth.ExitCode -ne 0) { throw "gh is not authenticated" }
  $evidence["gh_authenticated"] = $true

  $view = Invoke-Gh -Args @("repo","view",$TargetRepo,"--json","nameWithOwner,visibility,defaultBranchRef") -AllowFailure
  $repoExists = ($view.ExitCode -eq 0)

  if ($repoExists) {
    $evidence["repository_preexisted"] = $true
    if (-not $UseExistingEmptyRepository) {
      throw "target exists; use -UseExistingEmptyRepository only after confirming it is the intended empty target"
    }
    $branches = Invoke-Gh -Args @("api","repos/$TargetRepo/branches","--paginate")
    $branchText = ($branches.Output -join [Environment]::NewLine).Trim()
    if ($branchText) {
      $parsedBranches = $branchText | ConvertFrom-Json
      if (@($parsedBranches).Count -ne 0) { throw "existing target repository is not empty" }
    }
  } else {
    Invoke-Gh -Args @("repo","create",$TargetRepo,"--$Visibility","--confirm") | Out-Null
    $evidence["repository_created"] = $true
  }

  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("repo-bootstrap-" + [Guid]::NewGuid().ToString("N"))
  $verifyTmp = Join-Path ([System.IO.Path]::GetTempPath()) ("repo-bootstrap-verify-" + [Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  New-Item -ItemType Directory -Force -Path $verifyTmp | Out-Null

  try {
    Get-ChildItem -LiteralPath $root -Force | ForEach-Object {
      Copy-Item -LiteralPath $_.FullName -Destination $tmp -Recurse -Force
    }

    Invoke-Git -WorkingDirectory $tmp -Args @("init") | Out-Null
    Invoke-Git -WorkingDirectory $tmp -Args @("checkout","-b","main") | Out-Null
    Invoke-Git -WorkingDirectory $tmp -Args @("config","user.name","Independent Repo Bootstrap") | Out-Null
    Invoke-Git -WorkingDirectory $tmp -Args @("config","user.email","bootstrap@users.noreply.github.com") | Out-Null
    Invoke-Git -WorkingDirectory $tmp -Args @("add","--all") | Out-Null
    Invoke-Git -WorkingDirectory $tmp -Args @("commit","-m","Import verified export from $($sourceProof.source_commit)") | Out-Null

    $localCommit = (Invoke-Git -WorkingDirectory $tmp -Args @("rev-parse","HEAD"))[-1].Trim()
    Invoke-Git -WorkingDirectory $tmp -Args @("remote","add","origin","https://github.com/$TargetRepo.git") | Out-Null
    Invoke-Git -WorkingDirectory $tmp -Args @("push","--set-upstream","origin","main") | Out-Null
    $evidence["pushed_main"] = $true
    $evidence["import_commit"] = $localCommit

    $repoInfoRaw = Invoke-Gh -Args @("repo","view",$TargetRepo,"--json","nameWithOwner,visibility,defaultBranchRef")
    $repoInfo = (($repoInfoRaw.Output -join [Environment]::NewLine) | ConvertFrom-Json)
    if ([string]$repoInfo.nameWithOwner -ne $TargetRepo) { throw "remote repository identity mismatch" }
    if (([string]$repoInfo.visibility).ToLowerInvariant() -ne $Visibility.ToLowerInvariant()) {
      throw "remote visibility mismatch"
    }
    if ([string]$repoInfo.defaultBranchRef.name -ne "main") { throw "remote default branch is not main" }

    Invoke-Git -Args @("clone","--depth","1","https://github.com/$TargetRepo.git",$verifyTmp) | Out-Null
    $remoteProof = Assert-ExportIntegrity -Root $verifyTmp -Repo $TargetRepo -ExpectedCommit $sourceProof.source_commit

    if ($remoteProof.manifest_sha256 -ne $sourceProof.manifest_sha256) { throw "remote manifest hash mismatch" }
    if ($remoteProof.sums_sha256 -ne $sourceProof.sums_sha256) { throw "remote checksum hash mismatch" }

    $remoteCommit = (Invoke-Git -WorkingDirectory $verifyTmp -Args @("rev-parse","HEAD"))[-1].Trim()
    if ($remoteCommit -ne $localCommit) { throw "remote main commit mismatch" }

    $evidence["remote_verification"] = "PASS"
    $evidence["remote_manifest_sha256"] = $remoteProof.manifest_sha256
    $evidence["remote_sums_sha256"] = $remoteProof.sums_sha256
    $evidence["remote_main_commit"] = $remoteCommit
    $evidence["status"] = "PASS"
  }
  finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $verifyTmp -Recurse -Force -ErrorAction SilentlyContinue
  }
}
catch {
  $evidence["status"] = "FAIL"
  $evidence["error"] = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
}
finally {
  $evidence["completed_at_utc"] = [DateTime]::UtcNow.ToString("o")
  Write-JsonEvidence -Payload $evidence -Path $EvidencePath
}

Write-Host ($evidence | ConvertTo-Json -Compress -Depth 12)
if ($evidence["status"] -ne "PASS") { exit 2 }
exit 0
