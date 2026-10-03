
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Find-Python {
    $candidates = @()
    try { $candidates += (& py -3.12 -c "import sys;print(sys.executable)" 2>$null) } catch {}
    try { $candidates += (& py -3 -c "import sys;print(sys.executable)" 2>$null) } catch {}
    try { $candidates += (& python -c "import sys;print(sys.executable)" 2>$null) } catch {}
    $candidates += @(
      "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
      "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
      "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )
    foreach ($p in $candidates) {
      if ($p -and (Test-Path $p)) {
        try {
          $ver = & $p -c "import sys;print(sys.version_info.major*100+sys.version_info.minor)"
          if ([int]$ver -ge 311) { return $p }
        } catch {}
      }
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
      Write-Host "未找到 Python 3.11+，且系统没有 winget。请安装 Python 3.12 后重新运行。" -ForegroundColor Red
      exit 1
    }
    Write-Host "正在安装 Python 3.12..."
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    $Python = Find-Python
    if (-not $Python) {
      Write-Host "Python 安装后仍未找到。请重启电脑后再次运行 ONE_CLICK_START.bat。" -ForegroundColor Red
      exit 1
    }
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "创建独立虚拟环境..."
    & $Python -m venv (Join-Path $Root ".venv")
}
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { throw "虚拟环境创建失败" }

Write-Host "安装/修复依赖..."
& $VenvPython -m pip install --disable-pip-version-check --no-input --retries 1 --timeout 8 -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "官方 PyPI 失败，尝试备用镜像..."
    & $VenvPython -m pip install --disable-pip-version-check --no-input --retries 1 --timeout 8 -r (Join-Path $Root "requirements.txt") -i https://pypi.tuna.tsinghua.edu.cn/simple
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $VenvPython (Join-Path $Root "doctor.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "环境准备完成。" -ForegroundColor Green
exit 0
