@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ENSURE_ENV.bat
if errorlevel 1 (
 echo 无法完成环境安装或修复。
 pause
 exit /b 1
)
python run_daily.py
if errorlevel 1 (
 echo.
 echo 新预测未生成；最后一次有效预测仍然保留。将打开界面显示失败原因。
)
start "" http://localhost:8501
streamlit run app.py --server.port 8501
