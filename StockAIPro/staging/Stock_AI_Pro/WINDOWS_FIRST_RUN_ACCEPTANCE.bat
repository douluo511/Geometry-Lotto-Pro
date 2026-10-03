@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Windows 首次发行验收（包含真实数据/预测）===
call ENSURE_RUNTIME.bat
if errorlevel 1 goto :fail
".runtime_venv\Scripts\python.exe" acceptance_windows.py --live
if errorlevel 1 goto :fail
echo 验收 PASS。报告位于 %%APPDATA%%\StockAIPro\reports\windows_acceptance.json
pause
exit /b 0
:fail
echo 验收 FAIL。请查看 %%APPDATA%%\StockAIPro\reports\windows_acceptance.json 和 logs\startup.log
pause
exit /b 1
