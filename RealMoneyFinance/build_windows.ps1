param([string]$Python="python")
$ErrorActionPreference="Stop"
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
if($env:SOURCE_SHA -notmatch '^[0-9a-f]{40}$'){throw "exact source SHA required before build"}
$buildInfo=Join-Path $Root "app/build_info.py"
$lines=Get-Content -LiteralPath $buildInfo | ForEach-Object {if($_ -match '^SOURCE_SHA = '){'SOURCE_SHA = "'+$env:SOURCE_SHA+'"'}else{$_}}
[IO.File]::WriteAllLines($buildInfo,$lines,[Text.UTF8Encoding]::new($false))
if(Test-Path dist){Remove-Item -Recurse -Force dist}
if(Test-Path build){Remove-Item -Recurse -Force build}

& $Python -m PyInstaller --noconfirm --clean --windowed --onefile --name RealMoneyFinance main.py
if($LASTEXITCODE -ne 0){throw "main build failed"}
& $Python -m PyInstaller --noconfirm --clean --console --onefile --name RealMoneyFinanceUpdater updater_main.py
if($LASTEXITCODE -ne 0){throw "updater build failed"}

$main=Resolve-Path ./dist/RealMoneyFinance.exe
$updater=Resolve-Path ./dist/RealMoneyFinanceUpdater.exe
[ordered]@{
  status="PASS"
  source_sha=$env:SOURCE_SHA
  build_kind="WINDOWS_CANDIDATE"
  main_sha256=(Get-FileHash -Algorithm SHA256 $main).Hash.ToLowerInvariant()
  updater_sha256=(Get-FileHash -Algorithm SHA256 $updater).Hash.ToLowerInvariant()
  physical_gui="NOT VERIFIED"
  real_release_update="BLOCKED"
  repository_independence="BLOCKED"
  final_gate="FAIL"
}|ConvertTo-Json -Depth 5|Set-Content -Encoding UTF8 ./windows_build_evidence.json

