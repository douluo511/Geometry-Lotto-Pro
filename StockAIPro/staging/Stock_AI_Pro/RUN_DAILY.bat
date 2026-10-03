@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ENSURE_RUNTIME.bat
if errorlevel 1 goto :fail
".runtime_venv\Scripts\python.exe" launcher.py --daily-only
if errorlevel 1 goto :fail
pause
exit /b 0
:fail
echo 运行失败，请看 %%APPDATA%%\StockAIPro\logs\startup.log
pause
exit /b 1
