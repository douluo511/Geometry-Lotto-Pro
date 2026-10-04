$ErrorActionPreference='Stop'
python -m PyInstaller --noconfirm --clean --windowed --onedir --name EarthOnlineLifeBase --paths . --add-data "content;content" --hidden-import=tkinter main.py
python -m PyInstaller --noconfirm --clean --console --onefile --name EarthOnlineUpdater --paths . updater_main.py
Copy-Item -Force .\dist\EarthOnlineUpdater.exe .\dist\EarthOnlineLifeBase\EarthOnlineUpdater.exe
if (!(Test-Path .\dist\EarthOnlineLifeBase\EarthOnlineLifeBase.exe)) { throw 'main EXE missing' }
if (!(Test-Path .\dist\EarthOnlineLifeBase\EarthOnlineUpdater.exe)) { throw 'updater EXE missing' }
$contentRoot = Join-Path (Resolve-Path .\dist\EarthOnlineLifeBase\_internal) "content"
if (!(Test-Path $contentRoot)) { throw 'bundled content directory missing' }
$chunks = @(Get-ChildItem $contentRoot -Filter 'v2_corpus_pages_*.txt')
if ($chunks.Count -ne 8) { throw "expected 8 corpus chunks in frozen package, got $($chunks.Count)" }
