@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ENSURE_RUNTIME.bat
if errorlevel 1 goto :fail
".runtime_venv\Scripts\python.exe" run_full_check.py
if errorlevel 1 goto :fail
echo === ALL ENGINEERING ACCEPTANCE PASS ===
pause
exit /b 0
:fail
echo === ACCEPTANCE FAIL ===
pause
exit /b 1
