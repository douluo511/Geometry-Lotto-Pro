param(
  [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
Set-Location $Root

$dist = Join-Path $Root "dist"
$build = Join-Path $Root "build"
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
if (Test-Path $build) { Remove-Item -Recurse -Force $build }

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onedir `
  --name StockAIPro `
  --paths desktop_native `
  --add-data "staging/Stock_AI_Pro;Stock_AI_Pro" `
  --hidden-import pandas `
  --hidden-import numpy `
  --hidden-import sklearn `
  --hidden-import joblib `
  --hidden-import requests `
  --hidden-import cryptography `
  --hidden-import akshare `
  desktop_native/app.py
if ($LASTEXITCODE -ne 0) { throw "StockAIPro PyInstaller build failed" }

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --console `
  --onefile `
  --name StockAIUpdater `
  --paths desktop_native `
  --hidden-import requests `
  --hidden-import cryptography `
  desktop_native/updater_entry.py
if ($LASTEXITCODE -ne 0) { throw "StockAIUpdater PyInstaller build failed" }

$mainDir = Join-Path $dist "StockAIPro"
$updater = Join-Path $dist "StockAIUpdater.exe"
Copy-Item -Force $updater (Join-Path $mainDir "StockAIUpdater.exe")

$mainExe = Join-Path $mainDir "StockAIPro.exe"
if (!(Test-Path $mainExe)) { throw "main EXE missing" }
if (!(Test-Path (Join-Path $mainDir "StockAIUpdater.exe"))) { throw "updater EXE missing" }

$mainHash = (Get-FileHash -Algorithm SHA256 $mainExe).Hash.ToLowerInvariant()
$updaterHash = (Get-FileHash -Algorithm SHA256 (Join-Path $mainDir "StockAIUpdater.exe")).Hash.ToLowerInvariant()
$evidence = [ordered]@{
  status = "PASS"
  build_kind = "WINDOWS_NATIVE_CANDIDATE"
  main_exe = $mainExe
  main_sha256 = $mainHash
  updater_exe = (Join-Path $mainDir "StockAIUpdater.exe")
  updater_sha256 = $updaterHash
  exact_exe = "CANDIDATE_ONLY"
  physical_gui = "NOT VERIFIED"
  same_hash = "NOT VERIFIED"
  repository_independence = "BLOCKED"
  real_release_update = "BLOCKED"
  final_gate = "FAIL"
}
$evidence | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $Root "desktop_windows_build_evidence.json")
Write-Host ($evidence | ConvertTo-Json -Compress)
