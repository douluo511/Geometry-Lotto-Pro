$ErrorActionPreference = 'Stop'
$exe = Resolve-Path 'dist\Geometry_Lotto_Pro_DLT.exe'
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
Write-Host "EXE=$exe"
Write-Host "SHA256=$hash"
New-Item -ItemType Directory -Force -Path artifacts | Out-Null
$hash | Set-Content -Encoding ascii artifacts\exe.sha256.txt

# 1. Core deterministic self-test
$p = Start-Process -FilePath $exe -ArgumentList '--self-test','--result-file','artifacts\self_test.json' -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "self-test exit code $($p.ExitCode)" }

# 2. Real native Win32 window creation / four-entry binding test
$p = Start-Process -FilePath $exe -ArgumentList '--gui-self-test','--result-file','artifacts\gui_self_test.json' -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "gui-self-test exit code $($p.ExitCode)" }

# 3. Full exact-package acceptance: real network + all four service entries + scientific audit.
$p = Start-Process -FilePath $exe -ArgumentList '--acceptance','--result-file','artifacts\acceptance.json' -Wait -PassThru
if ($p.ExitCode -ne 0) {
  if (Test-Path artifacts\acceptance.json) { Get-Content artifacts\acceptance.json }
  throw "acceptance exit code $($p.ExitCode)"
}

$report = Get-Content artifacts\acceptance.json -Raw | ConvertFrom-Json
if ($report.final_release_gate -ne 'PASS') { throw "final_release_gate=$($report.final_release_gate)" }
if ($report.exe_sha256 -ne $hash) { throw "acceptance hash does not match built EXE hash" }

# 4. GUI process smoke: default launch must stay alive long enough to create the real main window.
$proc = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 5
if ($proc.HasExited) { throw "default GUI exited early with code $($proc.ExitCode)" }
Stop-Process -Id $proc.Id -Force
Write-Host 'WINDOWS_EXACT_PACKAGE_ACCEPTANCE=PASS'
