@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto :repair

call ".venv\Scripts\activate.bat"
python doctor.py >nul 2>&1
if errorlevel 1 goto :repair
exit /b 0

:repair
echo 正在准备/修复 Stock AI Pro 运行环境...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BOOTSTRAP.ps1"
if errorlevel 1 exit /b 1
call ".venv\Scripts\activate.bat"
exit /b 0
