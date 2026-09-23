$ErrorActionPreference = 'Stop'
$exe = Resolve-Path 'dist\Geometry_Lotto_Pro_DLT.exe'
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
Write-Host "EXE=$exe"
Write-Host "SHA256=$hash"
New-Item -ItemType Directory -Force -Path artifacts | Out-Null
$hash | Set-Content -Encoding ascii artifacts\exe.sha256.txt

function Assert-Result([string]$path, [string]$label) {
  if (-not (Test-Path $path)) { throw "$label result file missing: $path" }
  $r = Get-Content $path -Raw | ConvertFrom-Json
  if ($r.status -ne 'PASS') { throw "$label status=$($r.status)" }
}

# 1. Core deterministic self-test on the exact EXE.
$p = Start-Process -FilePath $exe -ArgumentList '--self-test','--result-file','artifacts\self_test.json' -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "self-test exit code $($p.ExitCode)" }
Assert-Result 'artifacts\self_test.json' 'self-test'

# 2. Real native Win32 window creation / four-entry binding test.
$p = Start-Process -FilePath $exe -ArgumentList '--gui-self-test','--result-file','artifacts\gui_self_test.json' -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "gui-self-test exit code $($p.ExitCode)" }
Assert-Result 'artifacts\gui_self_test.json' 'gui-self-test'

# 3. Full exact-package acceptance: real network + autonomous prediction +
# repair + strict scientific falsification + audit isolation.
$p = Start-Process -FilePath $exe -ArgumentList '--acceptance','--result-file','artifacts\acceptance.json' -Wait -PassThru
if ($p.ExitCode -ne 0) {
  if (Test-Path artifacts\acceptance.json) { Get-Content artifacts\acceptance.json -Raw }
  throw "acceptance exit code $($p.ExitCode)"
}

$report = Get-Content artifacts\acceptance.json -Raw | ConvertFrom-Json
if ($report.final_release_gate -ne 'PASS') { throw "final_release_gate=$($report.final_release_gate)" }
if ([int]$report.hard_fail_count -ne 0) { throw "hard_fail_count=$($report.hard_fail_count)" }
if ([string]$report.exe_sha256 -ne $hash) { throw "acceptance hash does not match built EXE hash" }

# 4. Unicode path + no Python runtime environment. The exact same EXE bytes
# must remain self-contained outside the build directory.
$unicodeDir = Join-Path $env:RUNNER_TEMP '大乐透 最终验收 空格路径'
New-Item -ItemType Directory -Force -Path $unicodeDir | Out-Null
$unicodeExe = Join-Path $unicodeDir 'Geometry Lotto Pro 大乐透.exe'
Copy-Item $exe $unicodeExe -Force
$unicodeHash = (Get-FileHash $unicodeExe -Algorithm SHA256).Hash.ToLower()
if ($unicodeHash -ne $hash) { throw "unicode-path copy hash mismatch" }
$oldPythonPath = $env:PYTHONPATH
$oldPythonHome = $env:PYTHONHOME
try {
  $env:PYTHONPATH = ''
  $env:PYTHONHOME = ''
  $p = Start-Process -FilePath $unicodeExe -ArgumentList '--self-test','--result-file',(Join-Path $unicodeDir 'self.json') -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "unicode/no-python self-test exit=$($p.ExitCode)" }
  $u = Get-Content (Join-Path $unicodeDir 'self.json') -Raw | ConvertFrom-Json
  if ($u.status -ne 'PASS') { throw "unicode/no-python self-test status=$($u.status)" }
} finally {
  $env:PYTHONPATH = $oldPythonPath
  $env:PYTHONHOME = $oldPythonHome
}

# 5. Default user path: exact EXE must stay alive as the native GUI app.
$proc = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 7
if ($proc.HasExited) { throw "default GUI exited early with code $($proc.ExitCode)" }
Stop-Process -Id $proc.Id -Force

@{
  schema = 'dlt-exact-runtime-smoke-v2'
  status = 'PASS'
  exe_sha256 = $hash
  unicode_path_hash = $unicodeHash
  no_python_environment = 'PASS'
  default_gui_alive_7s = $true
} | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 artifacts\runtime_smoke.json

Write-Host 'WINDOWS_EXACT_PACKAGE_ACCEPTANCE=PASS'
