@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ENSURE_ENV.bat
if errorlevel 1 (
 echo 环境无法修复，未创建自动任务。
 pause
 exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0SETUP_AUTO_UPDATE.ps1"
pause
