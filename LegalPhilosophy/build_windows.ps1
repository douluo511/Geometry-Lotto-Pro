$ErrorActionPreference='Stop'
$source=$env:SOURCE_SHA
if([string]::IsNullOrWhiteSpace($source)){ $source=(git rev-parse HEAD).Trim() }
if($source -notmatch '^[0-9a-f]{40}$'){ throw "SOURCE_SHA must be exact 40-char commit" }
Set-Content -LiteralPath app/_generated_build.py -Value "SOURCE_SHA = `"$source`"" -Encoding utf8
try {
  python -m PyInstaller --noconfirm --clean --windowed --onefile --name LegalPhilosophy main.py
  python -m PyInstaller --noconfirm --clean --console --onefile --name LegalPhilosophyUpdater updater_main.py
} finally {
  Remove-Item app/_generated_build.py -Force -ErrorAction SilentlyContinue
}
$main=Resolve-Path dist/LegalPhilosophy.exe
$up=Resolve-Path dist/LegalPhilosophyUpdater.exe
git diff --exit-code -- app main.py updater_main.py
if($LASTEXITCODE -ne 0){ throw "tracked source changed during build" }
$evidence=[ordered]@{
  status='PASS'
  source_sha=$source
  tracked_source_clean='PASS'
  main_path=$main.Path
  main_sha256=(Get-FileHash -Algorithm SHA256 $main).Hash.ToLowerInvariant()
  updater_path=$up.Path
  updater_sha256=(Get-FileHash -Algorithm SHA256 $up).Hash.ToLowerInvariant()
}
$evidence|ConvertTo-Json|Set-Content -Encoding utf8 windows_build_evidence.json
Get-Content windows_build_evidence.json
