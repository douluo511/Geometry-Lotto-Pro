Set-StrictMode -Version Latest

function Get-AbsoluteLocalPath([string]$Value, [string]$Label) {
    if ($Value -notmatch '^[A-Za-z]:[\\/]' -or $Value -match '[\x00-\x1f"]') {
        throw "$Label must be an absolute local Windows path without control characters or quotes."
    }
    return [IO.Path]::GetFullPath($Value)
}

function Quote-NativeArgument([string]$Value) {
    # Reject quotes before this function; escape terminal slashes for CommandLineToArgvW.
    return '"' + [regex]::Replace($Value, '(\\+)$', '$1$1') + '"'
}

function Write-NewUtf8File([string]$Path, [string]$Content) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes($Content)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally { $stream.Dispose() }
}

function Get-Sha256([string]$Path) {
    # .NET works even when the optional Utility module containing Get-FileHash
    # is unavailable in a reduced Windows PowerShell installation.
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}

function Assert-DeploymentPaths([string]$PythonPath, [string]$RepositoryPath, [string]$ConfigPath) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf) -or
        [IO.Path]::GetFileName($PythonPath) -notmatch '^python(?:[0-9.]*)?\.exe$') {
        throw 'Expected an existing Python executable.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RepositoryPath 'research\ssq_dlt_v45\runtime.py') -PathType Leaf)) {
        throw 'RepositoryPath does not contain the V4.5 runtime.'
    }
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw 'ConfigPath is missing.' }
    if ([IO.Path]::GetExtension($ConfigPath) -ne '.json') { throw 'ConfigPath must name a JSON file.' }
    $null = [IO.File]::ReadAllText($ConfigPath) | ConvertFrom-Json -ErrorAction Stop
    $pythonProbe = & $PythonPath -I -c 'import json,sys; print(json.dumps(dict(supported=sys.version_info >= (3,11), executable=sys.executable)))'
    if ($LASTEXITCODE -ne 0) { throw 'Python identity validation failed.' }
    $identity = $pythonProbe | ConvertFrom-Json
    if (-not $identity.supported -or -not [string]::Equals([IO.Path]::GetFullPath($identity.executable), $PythonPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Python >= 3.11 or executable identity validation failed.'
    }
}
