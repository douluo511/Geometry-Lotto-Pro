@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ENSURE_ENV.bat
if errorlevel 1 goto :fail

python doctor.py
if errorlevel 1 goto :fail
python tests\self_test.py
if errorlevel 1 goto :fail
python tests\integration_pipeline_test.py
if errorlevel 1 goto :fail
python tests\universe_parser_test.py
if errorlevel 1 goto :fail
python tests\provider_normalization_test.py
if errorlevel 1 goto :fail
python tests\legacy_migration_test.py
if errorlevel 1 goto :fail
python tests\storage_test.py
if errorlevel 1 goto :fail
python tests\backtest_test.py
if errorlevel 1 goto :fail
python tests\lock_test.py
if errorlevel 1 goto :fail
python tests\maintenance_test.py
if errorlevel 1 goto :fail
python tests\freshness_gate_test.py
if errorlevel 1 goto :fail
python tests\app_static_test.py
if errorlevel 1 goto :fail
python tests\network_config_test.py
if errorlevel 1 goto :fail
python tests\entrypoints_test.py
if errorlevel 1 goto :fail
python tests\package_manifest_test.py
if errorlevel 1 goto :fail

echo.
echo === Stock AI Pro 3.0 完整自检全部通过 ===
pause
exit /b 0

:fail
echo.
echo === 自检失败；请先运行 REPAIR_ENV.bat，然后再次运行本文件 ===
pause
exit /b 1
