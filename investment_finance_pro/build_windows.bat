@echo off
setlocal
cd /d "%~dp0\.."
python -m pip install --upgrade pip pyinstaller
python investment_finance_pro\app.py --self-test --report source_self_test.json || exit /b 1
python investment_finance_pro\app.py --network-smoke --report source_network_smoke.json || exit /b 1
pyinstaller --noconfirm --clean --onefile --windowed --name InvestmentFinancePro investment_finance_pro\app.py || exit /b 1
dist\InvestmentFinancePro.exe --self-test --report exe_self_test.json || exit /b 1
dist\InvestmentFinancePro.exe --network-smoke --report exe_network_smoke.json || exit /b 1
certutil -hashfile dist\InvestmentFinancePro.exe SHA256 > exe_sha256.txt
echo Build and verification PASS
