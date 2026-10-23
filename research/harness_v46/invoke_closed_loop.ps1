# V4.7 SHADOW local Bot invocation; DOES NOT authenticate sources or TSA.
# This script has no auto-install / ticket purchase / model-promotion side effects.
param([Parameter(Mandatory=$true)][string]$ConfigFile)
$ErrorActionPreference = 'Stop'
$cfg = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($field in @('repository_root', 'python_exe', 'workspace', 'log_path')) {
    if (-not $cfg.$field) { throw "CLOSED_LOOP_CONFIG_FIELD_MISSING:$field" }
}
$repo = (Resolve-Path -LiteralPath $cfg.repository_root).Path
if (-not (Test-Path -LiteralPath (Join-Path $repo 'research\harness_v46\closed_loop.py'))) {
    throw 'CLOSED_LOOP_MODULE_MISSING'
}
$logDir = Split-Path -Parent $cfg.log_path
if (-not (Test-Path -LiteralPath $logDir -PathType Container)) {
    throw 'CLOSED_LOOP_LOG_DIR_NOT_PRECREATED'
}
Set-Location -LiteralPath $repo

# The SAME closed_loop runner supports either legacy combined SHADOW or
# independent per-game issue ticks. Never share a single required draw result.
$hasSingleGame = [bool]($cfg.ssq_snapshot_bundle -or $cfg.dlt_snapshot_bundle)
if ($hasSingleGame -and ($cfg.snapshot_bundle -or $cfg.research_history_bundle)) {
    throw 'CLOSED_LOOP_MIXED_LEGACY_AND_PER_GAME_CONFIG_FORBIDDEN'
}
$commands = @()
if ($hasSingleGame) {
    foreach ($game in @('SSQ', 'DLT')) {
        $field = $game.ToLowerInvariant() + '_snapshot_bundle'
        $argv = @('-m', 'research.harness_v46.closed_loop',
                  '--workspace', [string]$cfg.workspace)
        if ($cfg.$field) {
            $argv += @('--game-snapshot', [string]$cfg.$field)
        } else {
            # A missing source must not invent a forecast. Poll only
            # existing issues; log BLOCKED if the game was never registered.
            $argv += @('--game', $game)
        }
        $commands += ,@{ Game = $game; Arguments = $argv }
    }
} else {
    $argv = @('-m', 'research.harness_v46.closed_loop',
              '--workspace', [string]$cfg.workspace)
    if ($cfg.snapshot_bundle) {
        $argv += @('--snapshot-bundle', [string]$cfg.snapshot_bundle)
    }
    if ($cfg.research_history_bundle) {
        $argv += @('--research-history-bundle', [string]$cfg.research_history_bundle)
    }
    $commands += ,@{ Game = 'LEGACY-DUAL'; Arguments = $argv }
}

$failed = 0
foreach ($command in $commands) {
    $stamp = [DateTimeOffset]::UtcNow.ToString('o')
    "[$stamp][$($command.Game)] V47 SHADOW tick, local clock NOT independently trusted" |
        Out-File -LiteralPath $cfg.log_path -Encoding utf8 -Append
    $argv = $command.Arguments
    $output = & $cfg.python_exe @argv 2>&1
    $code = $LASTEXITCODE
    $output | Out-String | Out-File -LiteralPath $cfg.log_path -Encoding utf8 -Append
    "[$($command.Game)][exit_code=$code] A=0 NO_EDGE; research evidence only" |
        Out-File -LiteralPath $cfg.log_path -Encoding utf8 -Append
    if ($code -ne 0) {
        $failed++
        # Continue BOTH independent games; failure of one official source
        # must not delay the other game's valid frozen SHADOW run.
    }
}
if ($failed -gt 0) {
    throw "CLOSED_LOOP_TICK_BLOCKED:$failed"
}
