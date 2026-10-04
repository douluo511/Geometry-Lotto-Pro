@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ENSURE_ENV.bat
if errorlevel 1 (
 echo 环境无法修复。
 pause
 exit /b 1
)
python run_backtest.py
pause
