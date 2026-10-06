$ErrorActionPreference='Stop'
$source=$env:SOURCE_SHA
if([string]::IsNullOrWhiteSpace($source)){ $source=(git rev-parse HEAD).Trim() }
if($source -notmatch '^[0-9a-f]{40}$'){ throw "SOURCE_SHA must be exact 40-char commit" }
$chunks=@(Get-ChildItem -LiteralPath content -Filter 'v10_corpus_lines_*.txt')
if($chunks.Count -ne 28){ throw "expected 28 V10 corpus chunks, got $($chunks.Count)" }
Set-Content -LiteralPath app/_generated_build.py -Value "SOURCE_SHA = `"$source`"" -Encoding utf8
try {
  python -m PyInstaller --noconfirm --clean --windowed --onefile --name BeYourOwnMaster --add-data "content;content" main.py
  python -m PyInstaller --noconfirm --clean --console --onefile --name BeYourOwnMasterUpdater updater_main.py
} finally {
  Remove-Item app/_generated_build.py -Force -ErrorAction SilentlyContinue
}
$main=Resolve-Path dist/BeYourOwnMaster.exe
$up=Resolve-Path dist/BeYourOwnMasterUpdater.exe
git diff --exit-code -- app main.py updater_main.py
if($LASTEXITCODE -ne 0){ throw "tracked source changed during build" }
[ordered]@{
  status='PASS'
  source_sha=$source
  tracked_source_clean='PASS'
  frozen_1500_content_source_chunks=28
  main_path=$main.Path
  main_sha256=(Get-FileHash -Algorithm SHA256 $main).Hash.ToLowerInvariant()
  updater_path=$up.Path
  updater_sha256=(Get-FileHash -Algorithm SHA256 $up).Hash.ToLowerInvariant()
}|ConvertTo-Json|Set-Content -Encoding utf8 windows_build_evidence.json
Get-Content windows_build_evidence.json
