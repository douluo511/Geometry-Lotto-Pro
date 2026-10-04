@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ENSURE_ENV.bat
if errorlevel 1 (
 echo 环境无法修复。
 pause
 exit /b 1
)
python run_daily.py
if errorlevel 1 (
 echo.
 echo 每日流程失败；系统不会伪造新预测，最后有效冻结结果仍保留。
 echo 请查看 logs\stock_ai.log
 pause
 exit /b 1
)
echo.
echo 每日流程完成。
pause
