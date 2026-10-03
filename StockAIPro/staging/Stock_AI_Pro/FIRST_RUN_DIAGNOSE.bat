@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ENSURE_RUNTIME.bat
if errorlevel 1 goto :fail
".runtime_venv\Scripts\python.exe" diagnose.py
echo 报告：%%APPDATA%%\StockAIPro\reports\diagnose_report.txt
pause
exit /b %errorlevel%
:fail
pause
exit /b 1
