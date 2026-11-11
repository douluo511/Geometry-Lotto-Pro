$ErrorActionPreference='Stop'
$source=$env:SOURCE_SHA
if([string]::IsNullOrWhiteSpace($source)){ $source=(git rev-parse HEAD).Trim() }
if($source -notmatch '^[0-9a-f]{40}$'){ throw 'SOURCE_SHA must be exact commit' }
python -m PyInstaller --noconfirm --clean --windowed --onedir --name AIMusicProduction --paths . main.py
python -m PyInstaller --noconfirm --clean --console --onefile --name AIMusicUpdater --paths . updater_main.py
Copy-Item -Force .\dist\AIMusicUpdater.exe .\dist\AIMusicProduction\AIMusicUpdater.exe
$main=Resolve-Path .\dist\AIMusicProduction\AIMusicProduction.exe
$up=Resolve-Path .\dist\AIMusicProduction\AIMusicUpdater.exe
[ordered]@{
  status='PASS'
  source_sha=$source
  main_sha256=(Get-FileHash -Algorithm SHA256 $main).Hash.ToLowerInvariant()
  updater_sha256=(Get-FileHash -Algorithm SHA256 $up).Hash.ToLowerInvariant()
}|ConvertTo-Json|Set-Content -Encoding utf8 windows_build_evidence.json
Get-Content windows_build_evidence.json
