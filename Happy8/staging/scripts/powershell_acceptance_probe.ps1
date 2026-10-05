param([Parameter(Mandatory=$true)][string]$PayloadPath)

$ErrorActionPreference = 'Stop'
$payload = Get-Content -LiteralPath $PayloadPath -Raw -Encoding UTF8 | ConvertFrom-Json
$readOnlyNames = @{}
foreach ($variable in (Get-Variable)) {
  if (($variable.Options -band [System.Management.Automation.ScopedItemOptions]::ReadOnly) -or
      ($variable.Options -band [System.Management.Automation.ScopedItemOptions]::Constant)) {
    $readOnlyNames[$variable.Name.ToLowerInvariant()] = $true
  }
}

function Test-PowerShellContract([string]$code) {
  $tokens = $null
  $parseErrors = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseInput($code, [ref]$tokens, [ref]$parseErrors)
  $conflicts = @()
  foreach ($node in $ast.FindAll({ param($entry)
      $entry -is [System.Management.Automation.Language.AssignmentStatementAst] -or
      $entry -is [System.Management.Automation.Language.ParameterAst] -or
      $entry -is [System.Management.Automation.Language.ForEachStatementAst] -or
      $entry -is [System.Management.Automation.Language.UnaryExpressionAst]
    }, $true)) {
    $target = $null
    if ($node -is [System.Management.Automation.Language.AssignmentStatementAst]) { $target = $node.Left }
    elseif ($node -is [System.Management.Automation.Language.ParameterAst]) { $target = $node.Name }
    elseif ($node -is [System.Management.Automation.Language.ForEachStatementAst]) { $target = $node.Variable }
    elseif ([string]$node.TokenKind -match 'PlusPlus|MinusMinus') { $target = $node.Child }
    while ($target -is [System.Management.Automation.Language.ConvertExpressionAst] -or
           $target -is [System.Management.Automation.Language.AttributedExpressionAst]) { $target = $target.Child }
    if ($target -is [System.Management.Automation.Language.VariableExpressionAst]) {
      $name = ($target.VariablePath.UserPath -split ':')[-1].ToLowerInvariant()
      if ($readOnlyNames.ContainsKey($name)) { $conflicts += $target.Extent.Text }
    }
  }
  return [ordered]@{
    status = $(if (@($parseErrors).Count -eq 0 -and $conflicts.Count -eq 0) { 'PASS' } else { 'FAIL' })
    parse_errors = @($parseErrors | ForEach-Object { $_.Message })
    readonly_variable_targets = @($conflicts)
  }
}

$checks = [ordered]@{}
foreach ($block in $payload.blocks) { $checks[[string]$block.label] = Test-PowerShellContract ([string]$block.code) }

# Counterexamples prove that the native parser and automatic-variable audit reject
# the original defects. No production workflow or GUI operation is executed here.
$badInterpolation = Test-PowerShellContract 'throw "PowerShell parse failed for $script: $messages"'
$checks.original_interpolation_rejected = @{
  status = $(if (@($badInterpolation.parse_errors).Count -gt 0) { 'PASS' } else { 'FAIL' })
  detected = $badInterpolation
}
$badVariables = Test-PowerShellContract '$Host = "bad"; [int]$PID = 0'
$checks.original_automatic_variables_rejected = @{
  status = $(if (@($badVariables.readonly_variable_targets).Count -eq 2) { 'PASS' } else { 'FAIL' })
  detected = $badVariables
}

# Execute the actual release helper definitions with deterministic process/window
# substitutes, so Host/PID conflicts are caught as runtime errors as well.
try {
  $releaseTokens = $null
  $releaseErrors = $null
  $releaseAst = [System.Management.Automation.Language.Parser]::ParseInput(
    [string]$payload.release_script, [ref]$releaseTokens, [ref]$releaseErrors)
  if (@($releaseErrors).Count -gt 0) { throw 'Release acceptance script did not parse' }
  foreach ($functionName in @('Assert-Https', 'Assert-HttpsTrusted', 'Wait-Window', 'Get-Sha256', 'Capture-OfficialJson', 'Capture-OfficialRelease')) {
    $definition = @($releaseAst.FindAll({ param($entry)
      $entry -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true) | Where-Object { $_.Name -eq $functionName })
    if ($definition.Count -ne 1) { throw "Release helper definition missing or duplicated: $functionName" }
    . ([scriptblock]::Create($definition[0].Extent.Text))
  }
  Assert-HttpsTrusted 'https://updates.example/manifest.json' @('updates.example')
  $checks.release_https_helper_executes = @{ status = 'PASS' }
  $untrustedRejected = $false
  try { Assert-HttpsTrusted 'https://untrusted.example/manifest.json' @('updates.example') }
  catch { $untrustedRejected = $_.Exception.Message -like 'URL host is not trusted:*' }
  $checks.release_https_helper_rejects_untrusted = @{
    status = $(if ($untrustedRejected) { 'PASS' } else { 'FAIL' })
  }
  $releaseFixture = $payload.official_release_fixture
  $Repository = [string]$releaseFixture.repository
  $fixtureResponses = @{}
  foreach ($fixtureResponse in $releaseFixture.responses) { $fixtureResponses[[string]$fixtureResponse.url] = [string]$fixtureResponse.body }
  function Invoke-WebRequest {
    param([string]$Uri, [hashtable]$Headers, [int]$TimeoutSec, [string]$OutFile, [switch]$PassThru)
    if (-not $fixtureResponses.ContainsKey($Uri)) { throw 'No deterministic offline HTTP fixture for requested URL' }
    [System.IO.File]::WriteAllBytes($OutFile, [System.Text.Encoding]::UTF8.GetBytes($fixtureResponses[$Uri]))
    return [pscustomobject]@{StatusCode = 200}
  }
  New-Item -ItemType Directory -Force $releaseFixture.capture_dir | Out-Null
  $capture = Capture-OfficialRelease '101' '0.2.1' ([string]$releaseFixture.source_sha) ([string]$releaseFixture.main_sha256) ([string]$releaseFixture.updater_sha256) ([string]$releaseFixture.release_url) ([string]$releaseFixture.capture_dir) 'contract'
  $checks.official_release_producer_contract = @{
    status = $(if ($capture.main_asset_receipt.sha256 -eq $releaseFixture.main_sha256 -and
                   $capture.updater_asset_receipt.sha256 -eq $releaseFixture.updater_sha256 -and
                   $capture.release_response.http_status -eq 200 -and
                   $capture.tag_commit_response.http_status -eq 200) { 'PASS' } else { 'FAIL' })
    network_scope = 'deterministic offline HTTP substitute; no real release verification'
  }
  $wrongSourceRejected = $false
  try { Capture-OfficialRelease '101' '0.2.1' ('c' * 40) ([string]$releaseFixture.main_sha256) ([string]$releaseFixture.updater_sha256) ([string]$releaseFixture.release_url) ([string]$releaseFixture.capture_dir) 'wrong-source' | Out-Null }
  catch { $wrongSourceRejected = $_.Exception.Message -eq 'official release tag resolves to a different source head' }
  $checks.official_release_producer_wrong_source_rejected = @{ status = $(if ($wrongSourceRejected) { 'PASS' } else { 'FAIL' }) }
  $missingReleaseRejected = $false
  try { Capture-OfficialRelease '999' '0.2.1' ([string]$releaseFixture.source_sha) ([string]$releaseFixture.main_sha256) ([string]$releaseFixture.updater_sha256) ([string]$releaseFixture.release_url) ([string]$releaseFixture.capture_dir) 'missing-release' | Out-Null }
  catch { $missingReleaseRejected = $_.Exception.Message -eq 'No deterministic offline HTTP fixture for requested URL' }
  $checks.official_release_producer_missing_release_rejected = @{ status = $(if ($missingReleaseRejected) { 'PASS' } else { 'FAIL' }) }
  Add-Type @"
using System;
public static class Happy8ReleaseGui {
  public static bool FindVisibleWindow(int[] pids, out IntPtr hwnd, out int pid) {
    hwnd = new IntPtr(1); pid = 42; return true;
  }
}
"@
  function Get-Process { [CmdletBinding()]param([string]$Name) [pscustomobject]@{Id = 42} }
  function Start-Sleep { param([int]$Milliseconds) }
  $window = Wait-Window ([System.Diagnostics.Process]::GetCurrentProcess()) 'AcceptanceRegression' @()
  $checks.release_window_helper_executes = @{
    status = $(if ($window.hwnd -eq [IntPtr]1 -and $window.pid -eq 42) { 'PASS' } else { 'FAIL' })
    window_pid = $window.pid
  }
} catch {
  $checks.release_helper_execution = @{ status = 'FAIL'; error = $_.Exception.Message }
}

$allPass = @($checks.Values | Where-Object { $_.status -ne 'PASS' }).Count -eq 0
[ordered]@{
  schema = 'happy8-powershell-acceptance-probe-v1'
  status = $(if ($allPass) { 'PASS' } else { 'FAIL' })
  checks = $checks
} | ConvertTo-Json -Depth 10
if (-not $allPass) { exit 2 }
