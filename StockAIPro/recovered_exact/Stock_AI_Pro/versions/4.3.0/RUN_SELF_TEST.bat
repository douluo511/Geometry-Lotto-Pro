@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行 FIRST_TIME_SETUP.bat
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python tests\self_test.py
pause
