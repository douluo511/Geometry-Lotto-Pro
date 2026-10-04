@echo off
cd /d "%~dp0"
call ENSURE_RUNTIME.bat >nul 2>&1
if errorlevel 1 exit /b 1
".runtime_venv\Scripts\python.exe" launcher.py --daily-only
exit /b %errorlevel%
