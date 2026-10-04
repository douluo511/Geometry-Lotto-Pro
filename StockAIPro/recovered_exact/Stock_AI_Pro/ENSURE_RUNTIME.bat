@echo off
cd /d "%~dp0"
if exist ".runtime_venv\Scripts\python.exe" exit /b 0
echo [1/4] 正在准备 Stock AI Pro 启动环境...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BOOTSTRAP.ps1"
exit /b %errorlevel%
