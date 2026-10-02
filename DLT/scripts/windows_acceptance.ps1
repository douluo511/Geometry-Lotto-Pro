$ErrorActionPreference = 'Stop'
$exe = Resolve-Path 'dist\Geometry_Lotto_Pro_DLT.exe'
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
Write-Host "EXE=$exe"
Write-Host "SHA256=$hash"
New-Item -ItemType Directory -Force -Path artifacts | Out-Null
$hash | Set-Content -Encoding ascii artifacts\exe.sha256.txt

function Invoke-BoundedExe([string[]]$ArgumentList, [int]$TimeoutSeconds, [string]$EvidencePath, [string]$Label) {
  Write-Host "START_PHASE=$Label"
  $p = Start-Process -FilePath $exe -ArgumentList $ArgumentList -PassThru -WindowStyle Hidden
  $finished = $p.WaitForExit($TimeoutSeconds * 1000)
  if (-not $finished) {
    try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
    if ($EvidencePath -and (Test-Path $EvidencePath)) {
      Write-Host "LAST_EVIDENCE_BEGIN=$Label"
      Get-Content $EvidencePath
      Write-Host "LAST_EVIDENCE_END=$Label"
    }
    throw "$Label timed out after $TimeoutSeconds seconds"
  }
  if ($p.ExitCode -ne 0) {
    if ($EvidencePath -and (Test-Path $EvidencePath)) { Get-Content $EvidencePath }
    throw "$Label exit code $($p.ExitCode)"
  }
  Write-Host "END_PHASE=$Label"
}

# 1. Core deterministic self-test
Invoke-BoundedExe @('--self-test','--result-file','artifacts\self_test.json') 600 'artifacts\self_test.json' 'self-test'

# 2. Full exact-package acceptance: native Windows runtime + real network +
# all four service entries + scientific audit. Native GUI construction and actual
# button clicks are a separate stronger hard gate in the workflow against the same EXE bytes.
Invoke-BoundedExe @('--acceptance','--result-file','artifacts\acceptance.json') 6300 'artifacts\acceptance.json' 'full-acceptance'

$report = Get-Content artifacts\acceptance.json -Raw | ConvertFrom-Json
if ($report.exact_acceptance_gate -ne 'PASS' -or $report.final_release_gate -ne 'PENDING') { throw 'Exact service acceptance failed or claimed premature Final PASS' }
if ($report.exe_sha256 -ne $hash) { throw "acceptance hash does not match built EXE hash" }

# 3. GUI process smoke: default launch must stay alive long enough to create the real main window.
$proc = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 5
if ($proc.HasExited) { throw "default GUI exited early with code $($proc.ExitCode)" }
Stop-Process -Id $proc.Id -Force
Write-Host 'WINDOWS_EXACT_PACKAGE_ACCEPTANCE=PASS'
