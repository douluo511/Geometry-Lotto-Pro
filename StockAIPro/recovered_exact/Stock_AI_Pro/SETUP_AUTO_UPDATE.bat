@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ENSURE_RUNTIME.bat
if errorlevel 1 goto :fail
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0SETUP_AUTO_UPDATE.ps1"
pause
exit /b %errorlevel%
:fail
pause
exit /b 1
