@echo off
chcp 65001 >nul
schtasks /Delete /TN "Stock_AI_Pro_Daily" /F
pause
