@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BOOTSTRAP.ps1"
if errorlevel 1 (
 echo.
 echo 环境安装/修复失败。
 pause
 exit /b 1
)
echo.
echo 安装完成。以后可直接双击 ONE_CLICK_START.bat
pause
