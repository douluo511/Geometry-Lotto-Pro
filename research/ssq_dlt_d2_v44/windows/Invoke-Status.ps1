[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$RepositoryPath,
    [Parameter(Mandatory = $true)][string]$DatabasePath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$pathsValidated = $false

function Write-LauncherFailure([int]$ExitCode, [string]$FailureType) {
    if (-not $pathsValidated) { return }
    try {
        $failureDirectory = Join-Path $OutputDirectory 'launcher-failures'
        [IO.Directory]::CreateDirectory($failureDirectory) | Out-Null
        $failurePath = Join-Path $failureDirectory ([Guid]::NewGuid().ToString('N') + '.json')
        $failure = [ordered]@{ checked_at_utc=[DateTime]::UtcNow.ToString('o'); status='FAIL'; exit_code=$ExitCode; failure_type=$FailureType; R2='BLOCKED'; formal_A=0; decision='NO_EDGE' } | ConvertTo-Json
        $stream = [IO.File]::Open($failurePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        try { $bytes=(New-Object Text.UTF8Encoding($false)).GetBytes($failure); $stream.Write($bytes, 0, $bytes.Length) }
        finally { $stream.Dispose() }
    }
    catch { Write-Warning 'Could not write a separate launcher failure record; the task still fails.' }
}

try {
    foreach ($value in @($PythonPath, $RepositoryPath, $DatabasePath, $OutputDirectory)) {
        if ($value -notmatch '^[A-Za-z]:[\\/]' -or $value -match '[\x00-\x1f"]') {
            throw 'All runtime paths must be absolute local Windows paths without control characters.'
        }
    }
    $pathsValidated = $true
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Python executable is missing.' }
    if ([IO.Path]::GetFileName($PythonPath) -notmatch '^python(?:[0-9.]*)?\.exe$') { throw 'Expected a Python executable.' }
    if (-not (Test-Path -LiteralPath (Join-Path $RepositoryPath 'research\ssq_dlt_d2_v44\runtime.py') -PathType Leaf)) {
        throw 'The approved status runtime is missing from the repository.'
    }
    Set-Location -LiteralPath $RepositoryPath
    # This is the only Python operation. Runtime checks committed ledger data,
    # emits a new status directory, and appends a separate heartbeat.
    & $PythonPath -m research.ssq_dlt_d2_v44.runtime --db $DatabasePath --output $OutputDirectory
    if ($LASTEXITCODE -ne 0) { Write-LauncherFailure $LASTEXITCODE 'runtime_nonzero'; exit $LASTEXITCODE }
    exit 0
}
catch {
    Write-LauncherFailure 1 $_.Exception.GetType().FullName
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
}
