$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
function Find-Python {
  $candidates=@()
  try {$candidates += (& py -3.12 -c "import sys;print(sys.executable)" 2>$null)} catch {}
  try {$candidates += (& py -3 -c "import sys;print(sys.executable)" 2>$null)} catch {}
  try {$candidates += (& python -c "import sys;print(sys.executable)" 2>$null)} catch {}
  $candidates += @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe","$env:LOCALAPPDATA\Programs\Python\Python312\python.exe","$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")
  foreach($p in $candidates){if($p -and (Test-Path $p)){try{$v=& $p -c "import sys;print(sys.version_info.major*100+sys.version_info.minor)";if([int]$v -ge 311){return $p}}catch{}}}
  return $null
}
$Python=Find-Python
if(-not $Python){
  if(-not (Get-Command winget -ErrorAction SilentlyContinue)){Write-Host "未找到 Python 3.11+，且无 winget。请安装 Python 3.12。" -ForegroundColor Red;exit 1}
  Write-Host "正在安装 Python 3.12...";winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  $Python=Find-Python;if(-not $Python){Write-Host "Python 安装后仍未发现。请重启电脑后重试。" -ForegroundColor Red;exit 1}
}
$Venv=Join-Path $Root ".runtime_venv"
$VP=Join-Path $Venv "Scripts\python.exe"
if(-not (Test-Path $VP)){Write-Host "创建启动器环境...";& $Python -m venv $Venv}
$VP=Join-Path $Venv "Scripts\python.exe";if(-not (Test-Path $VP)){throw "启动器环境创建失败"}
Write-Host "安装/修复启动器依赖...";& $VP -m pip install --disable-pip-version-check --no-input --retries 1 --timeout 8 -r (Join-Path $Root "requirements_runtime.txt")
if($LASTEXITCODE -ne 0){Write-Host "官方 PyPI 失败，尝试备用镜像...";& $VP -m pip install --disable-pip-version-check --no-input --retries 1 --timeout 8 -r (Join-Path $Root "requirements_runtime.txt") -i https://pypi.tuna.tsinghua.edu.cn/simple}
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
Write-Host "启动器环境完成。" -ForegroundColor Green
