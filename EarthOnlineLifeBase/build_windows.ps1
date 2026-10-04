$ErrorActionPreference='Stop'
python -m PyInstaller --noconfirm --clean --windowed --onedir --name EarthOnlineLifeBase --paths . --hidden-import=tkinter main.py
python -m PyInstaller --noconfirm --clean --console --onefile --name EarthOnlineUpdater --paths . updater_main.py
Copy-Item -Force .\dist\EarthOnlineUpdater.exe .\dist\EarthOnlineLifeBase\EarthOnlineUpdater.exe
if (!(Test-Path .\dist\EarthOnlineLifeBase\EarthOnlineLifeBase.exe)) { throw 'main EXE missing' }
if (!(Test-Path .\dist\EarthOnlineLifeBase\EarthOnlineUpdater.exe)) { throw 'updater EXE missing' }
