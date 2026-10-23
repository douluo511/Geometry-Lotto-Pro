# V4.7 SHADOW Bot host task handler. Never treats localhost clock as TSA.
param(
    [Parameter(Mandatory=$true)][string]$ConfigFile,
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$RepositoryRoot
)
$ErrorActionPreference = 'Stop'
$ConfigFile = (Resolve-Path -LiteralPath $ConfigFile).Path
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
$RepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$modulePath = Join-Path $RepositoryRoot 'research\harness_v46\shadow_bot.py'
if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
    throw 'BOT_EXECUTABLE_CODE_MISSING'
}
$logDir = Split-Path -Parent $ConfigFile
if (-not (Test-Path -LiteralPath $logDir -PathType Container)) {
    throw 'BOT_PERSISTENT_LOG_DIRECTORY_MISSING'
}
$log = Join-Path $logDir 'v47-shadow-bot-task.log'
$stamp = [DateTimeOffset]::UtcNow.ToString('o')
Set-Location -LiteralPath $RepositoryRoot
"[$stamp] SHADOW_BOT_TICK_INVOKED local-clock-untrusted formal_A=0 NO_EDGE" |
    Out-File -LiteralPath $log -Encoding utf8 -Append
# The Bot itself rejects missing preregistered freeze when local cutoff passed.
# Never call shell interpolated dynamic scripts or a different prediction engine.
$output = & $PythonExe -m research.harness_v46.shadow_bot --config $ConfigFile 2>&1
$code = $LASTEXITCODE
$output | Out-String | Out-File -LiteralPath $log -Encoding utf8 -Append
"[$stamp] SHADOW_BOT_TICK_EXIT_CODE=$code" |
    Out-File -LiteralPath $log -Encoding utf8 -Append
if ($code -ne 0) {
    throw "SHADOW_BOT_TICK_FAILED: $code"
}
