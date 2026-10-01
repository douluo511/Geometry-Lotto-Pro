param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$EvidencePath
)

$ErrorActionPreference = "Stop"

function Get-Sha256([string]$Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Acceptance harness requires administrator rights to create a disposable standard user"
}

$exe = (Resolve-Path -LiteralPath $ExePath).Path
$exeHash = Get-Sha256 $exe
$evidenceFull = [IO.Path]::GetFullPath($EvidencePath)
$evidenceDir = Split-Path -Parent $evidenceFull
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

$user = ("glpssq" + [Guid]::NewGuid().ToString("N").Substring(0,8)).ToLowerInvariant()
$password = "G!p" + [Guid]::NewGuid().ToString("N").Substring(0,16) + "aA9!"
$work = Join-Path $env:RUNNER_TEMP ("glp-standard-user-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $work | Out-Null
$userExe = Join-Path $work (Split-Path -Leaf $exe)
$selfResult = Join-Path $work "self.json"
$whoamiPath = Join-Path $work "whoami.txt"
$groupsPath = Join-Path $work "groups.txt"
$exitPath = Join-Path $work "exit.txt"
$cmdPath = Join-Path $work "run-self.cmd"
$copiedSelf = Join-Path $evidenceDir "standard_user_self.json"
$guiProc = $null
$userCreated = $false

try {
  # Use the supported LocalAccounts API rather than net.exe. The hosted
  # Windows runner can reject net.exe user creation before the product is ever
  # exercised; that is a harness failure, not standard-user product evidence.
  $secure = ConvertTo-SecureString $password -AsPlainText -Force
  try {
    $local = New-LocalUser -Name $user -Password $secure -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword -Description "Disposable SSQ standard-user acceptance account" -ErrorAction Stop
  }
  catch {
    $provisionFailure = [ordered]@{
      schema = "ssq-standard-user-acceptance-v1"
      status = "FAIL"
      stage = "create-standard-user"
      github_sha = $env:GITHUB_SHA
      github_run_id = $env:GITHUB_RUN_ID
      exe = (Split-Path -Leaf $exe)
      exe_sha256 = $exeHash
      provisioning_method = "New-LocalUser"
      error = "$($_.Exception.GetType().FullName): $($_.Exception.Message)"
      tested_at = [DateTime]::UtcNow.ToString("o")
    }
    $provisionFailure | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $evidenceFull -Encoding utf8
    throw "Could not create disposable local standard user via New-LocalUser: $($_.Exception.Message)"
  }
  $userCreated = $true

  $local = Get-LocalUser -Name $user -ErrorAction Stop
  $sid = [string]$local.SID.Value
  $admins = @(Get-LocalGroupMember -Group "Administrators" -ErrorAction Stop | ForEach-Object { [string]$_.SID.Value })
  if($admins -contains $sid) { throw "Disposable user unexpectedly belongs to Administrators" }

  Copy-Item -LiteralPath $exe -Destination $userExe -Force
  if((Get-Sha256 $userExe) -ne $exeHash) { throw "Standard-user EXE copy differs from accepted bytes" }

  & icacls.exe $work /grant:r "$($env:COMPUTERNAME)\$($user):(OI)(CI)M" /T /C | Out-Null
  if($LASTEXITCODE -ne 0) { throw "Could not grant disposable user access to acceptance workspace" }

  $cmd = @"
@echo off
set "GITHUB_SHA=$env:GITHUB_SHA"
set "GITHUB_RUN_ID=$env:GITHUB_RUN_ID"
"$env:SystemRoot\System32\whoami.exe" > "$whoamiPath" 2>&1
"$env:SystemRoot\System32\whoami.exe" /groups > "$groupsPath" 2>&1
"$userExe" --check self --result-file "$selfResult"
echo %ERRORLEVEL% > "$exitPath"
"@
  Set-Content -LiteralPath $cmdPath -Value $cmd -Encoding ascii

  $cred = New-Object Management.Automation.PSCredential("$($env:COMPUTERNAME)\$user", $secure)
  $cmdProc = Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" -ArgumentList @("/d","/c",('"' + $cmdPath + '"')) -Credential $cred -LoadUserProfile -Wait -PassThru -WindowStyle Hidden

  if(-not (Test-Path -LiteralPath $exitPath)) { throw "Standard-user self check did not write exit evidence" }
  $innerExit = [int]((Get-Content -LiteralPath $exitPath -Raw).Trim())
  if($cmdProc.ExitCode -ne 0 -or $innerExit -ne 0) { throw "Standard-user exact-EXE self check failed" }
  if(-not (Test-Path -LiteralPath $selfResult)) { throw "Standard-user self result missing" }

  $self = Get-Content -LiteralPath $selfResult -Raw | ConvertFrom-Json
  if($self.status -ne "PASS" -or $self.exe_sha256 -ne $exeHash -or $self.github_sha -ne $env:GITHUB_SHA -or $self.github_run_id -ne $env:GITHUB_RUN_ID) {
    throw "Standard-user self result is not current-run/hash bound"
  }

  $whoami = (Get-Content -LiteralPath $whoamiPath -Raw).Trim().ToLowerInvariant()
  $groups = Get-Content -LiteralPath $groupsPath -Raw
  $expectedIdentity = ("$($env:COMPUTERNAME)\$user").ToLowerInvariant()
  if($whoami -ne $expectedIdentity) { throw "Exact EXE self check ran under unexpected identity: $whoami" }
  if($groups -match "S-1-5-32-544") { throw "Standard-user token contains local Administrators group" }
  if($groups -notmatch "S-1-16-8192" -or $groups -match "S-1-16-12288") {
    throw "Standard-user token is not Medium integrity"
  }

  Copy-Item -LiteralPath $selfResult -Destination $copiedSelf -Force
  $selfHash = Get-Sha256 $copiedSelf
  $copiedWhoami = Join-Path $evidenceDir "standard_user_whoami.txt"
  $copiedGroups = Join-Path $evidenceDir "standard_user_groups.txt"
  Copy-Item -LiteralPath $whoamiPath -Destination $copiedWhoami -Force
  Copy-Item -LiteralPath $groupsPath -Destination $copiedGroups -Force
  $whoamiHash = Get-Sha256 $copiedWhoami
  $groupsHash = Get-Sha256 $copiedGroups

  $guiProc = Start-Process -FilePath $userExe -Credential $cred -LoadUserProfile -PassThru
  Start-Sleep -Seconds 8
  if($guiProc.HasExited) { throw "Exact EXE did not remain alive as GUI under standard user" }

  $profile = Get-CimInstance Win32_UserProfile | Where-Object { [string]$_.SID -eq $sid } | Select-Object -First 1
  if($null -eq $profile -or [string]::IsNullOrWhiteSpace([string]$profile.LocalPath)) {
    throw "Could not resolve disposable user's profile"
  }
  $appDataRoot = Join-Path ([string]$profile.LocalPath) "AppData\Local\GeometryLottoPro\SSQ"
  $ledger = Join-Path $appDataRoot "ledger.sqlite3"
  if(-not (Test-Path -LiteralPath $ledger)) {
    throw "Standard-user default LOCALAPPDATA store was not created"
  }

  $result = [ordered]@{
    schema = "ssq-standard-user-acceptance-v1"
    status = "PASS"
    github_sha = $env:GITHUB_SHA
    github_run_id = $env:GITHUB_RUN_ID
    exe = (Split-Path -Leaf $exe)
    exe_sha256 = $exeHash
    disposable_user = $user
    user_sid = $sid
    administrators_member = $false
    medium_integrity = $true
    whoami = $whoami
    self_result = (Split-Path -Leaf $copiedSelf)
    self_result_sha256 = $selfHash
    self_status = [string]$self.status
    whoami_evidence = (Split-Path -Leaf $copiedWhoami)
    whoami_evidence_sha256 = $whoamiHash
    groups_evidence = (Split-Path -Leaf $copiedGroups)
    groups_evidence_sha256 = $groupsHash
    gui_default_launch = "PASS"
    default_appdata_root = $appDataRoot
    localappdata_ledger_created = $true
    tested_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss'Z'")
  }
  $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $evidenceFull -Encoding utf8
  Get-Content -LiteralPath $evidenceFull
}
finally {
  if($null -ne $guiProc -and -not $guiProc.HasExited) {
    & taskkill.exe /PID $guiProc.Id /T /F | Out-Null
  }
  if($userCreated) {
    Remove-LocalUser -Name $user -ErrorAction SilentlyContinue
  }
  Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
