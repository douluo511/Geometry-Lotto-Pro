@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto :repair

call ".venv\Scripts\activate.bat"
python doctor.py >nul 2>&1
if errorlevel 1 goto :repair
goto :run

:repair
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BOOTSTRAP.ps1" >> "logs\scheduler_repair.log" 2>&1
if errorlevel 1 exit /b 1
call ".venv\Scripts\activate.bat"

:run
python run_daily.py >> "logs\scheduler.log" 2>&1
exit /b %errorlevel%
