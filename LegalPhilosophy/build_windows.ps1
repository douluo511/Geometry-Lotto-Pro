$ErrorActionPreference='Stop'
$source=$env:SOURCE_SHA
if([string]::IsNullOrWhiteSpace($source)){ $source=(git rev-parse HEAD).Trim() }
$info=@"
VERSION = "0.1.0"
SOURCE_SHA = "$source"
PRODUCT = "LegalPhilosophy"
"@
Set-Content -LiteralPath app/build_info.py -Value $info -Encoding utf8
python -m PyInstaller --noconfirm --clean --windowed --onefile --name LegalPhilosophy main.py
python -m PyInstaller --noconfirm --clean --console --onefile --name LegalPhilosophyUpdater updater_main.py
$main=Resolve-Path dist/LegalPhilosophy.exe
$up=Resolve-Path dist/LegalPhilosophyUpdater.exe
$evidence=[ordered]@{
  status='PASS'
  source_sha=$source
  main_path=$main.Path
  main_sha256=(Get-FileHash -Algorithm SHA256 $main).Hash.ToLowerInvariant()
  updater_path=$up.Path
  updater_sha256=(Get-FileHash -Algorithm SHA256 $up).Hash.ToLowerInvariant()
}
$evidence|ConvertTo-Json|Set-Content -Encoding utf8 windows_build_evidence.json
Get-Content windows_build_evidence.json
