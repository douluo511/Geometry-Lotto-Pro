@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Stock AI Pro 一键启动 ===
call ENSURE_RUNTIME.bat
if errorlevel 1 goto :fail
echo [2/4] 环境检查完成
echo [3/4] 检查软件版本并更新数据/预测...
".runtime_venv\Scripts\python.exe" launcher.py
if errorlevel 1 goto :fail
exit /b 0
:fail
echo.
echo 启动失败。请查看 %%APPDATA%%\StockAIPro\logs\startup.log
pause
exit /b 1
