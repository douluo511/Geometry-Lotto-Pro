param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$UpdaterExePath,
  [Parameter(Mandatory=$true)][string]$SuccessEvidencePath,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [ValidateSet('update','repair')][string]$Operation = 'update',
  [int]$OperationTimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"
if($OperationTimeoutSeconds -lt 30 -or $OperationTimeoutSeconds -gt 900){ throw "Invalid operation timeout" }

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class PhysicalGuiFailureClick {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr hWnd, int id);
  [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT point);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
  [DllImport("user32.dll", EntryPoint="SendMessageW")] public static extern IntPtr SendMessageRaw(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll", EntryPoint="SendMessageW", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageText(IntPtr hWnd, uint msg, IntPtr wParam, StringBuilder lParam);
}
"@

function Get-Sha256([string]$path){
  return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-NativeText([IntPtr]$handle){
  $len = [PhysicalGuiFailureClick]::SendMessageRaw($handle,0x000E,[IntPtr]::Zero,[IntPtr]::Zero).ToInt32()
  if($len -lt 0 -or $len -gt 1048576){ throw "Invalid native text length" }
  $buffer = New-Object System.Text.StringBuilder ([Math]::Max(2,$len + 2))
  [void][PhysicalGuiFailureClick]::SendMessageText($handle,0x000D,[IntPtr]($buffer.Capacity),$buffer)
  return $buffer.ToString()
}

function Wait-MainWindow([System.Diagnostics.Process]$boot,[string]$processName,[string]$exe,[int[]]$baselinePids){
  for($attempt=0;$attempt -lt 120;$attempt++){
    Start-Sleep -Milliseconds 250
    $rows = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object {
      $_.MainWindowHandle -ne 0 -and ($_.Id -eq $boot.Id -or $baselinePids -notcontains $_.Id)
    })
    foreach($row in $rows){
      try {
        if(-not [string]::Equals($row.Path,$exe,[StringComparison]::OrdinalIgnoreCase)){ continue }
        if($row.Id -ne $boot.Id){
          $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($row.Id)"
          if($null -eq $cim -or [int]$cim.ParentProcessId -ne $boot.Id){ continue }
        }
        return @{ hwnd=[IntPtr]$row.MainWindowHandle; pid=[int]$row.Id }
      } catch { continue }
    }
  }
  throw "Exact EXE main window not found"
}

function Get-Control([IntPtr]$window,[int]$id,[int]$processId){
  $handle = [PhysicalGuiFailureClick]::GetDlgItem($window,$id)
  if($handle -eq [IntPtr]::Zero -or [PhysicalGuiFailureClick]::GetParent($handle) -ne $window){ throw "Control $id invalid" }
  [uint32]$owner = 0
  if([PhysicalGuiFailureClick]::GetWindowThreadProcessId($handle,[ref]$owner) -eq 0 -or $owner -ne $processId){ throw "Control $id wrong process" }
  if(-not [PhysicalGuiFailureClick]::IsWindowVisible($handle)){ throw "Control $id hidden" }
  return $handle
}

function Click-Control([IntPtr]$window,[IntPtr]$button){
  $r = New-Object PhysicalGuiFailureClick+RECT
  if(-not [PhysicalGuiFailureClick]::GetWindowRect($button,[ref]$r)){ throw "Cannot resolve button rectangle" }
  $p = New-Object PhysicalGuiFailureClick+POINT
  $p.X = [int][Math]::Floor(($r.Left+$r.Right)/2)
  $p.Y = [int][Math]::Floor(($r.Top+$r.Bottom)/2)
  [void][PhysicalGuiFailureClick]::SetForegroundWindow($window)
  Start-Sleep -Milliseconds 250
  if([PhysicalGuiFailureClick]::GetForegroundWindow() -ne $window){ throw "Exact EXE did not receive foreground" }
  if([PhysicalGuiFailureClick]::WindowFromPoint($p) -ne $button){ throw "Operation button hit-test failed" }
  if(-not [PhysicalGuiFailureClick]::SetCursorPos($p.X,$p.Y)){ throw "Cannot position cursor" }
  [PhysicalGuiFailureClick]::mouse_event(0x0002,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 80
  [PhysicalGuiFailureClick]::mouse_event(0x0004,0,0,0,[UIntPtr]::Zero)
  return @{x=$p.X;y=$p.Y}
}

$exe = (Resolve-Path -LiteralPath $ExePath).Path
$acceptedUpdater = (Resolve-Path -LiteralPath $UpdaterExePath).Path
$successEvidence = (Resolve-Path -LiteralPath $SuccessEvidencePath).Path
$evidenceFull = [System.IO.Path]::GetFullPath($EvidencePath)
$evidenceDir = Split-Path -Parent $evidenceFull
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

$success = Get-Content -LiteralPath $successEvidence -Raw | ConvertFrom-Json
$verifiedUpdate = @($success.buttons | Where-Object { $_.operation -eq "update" -and $_.status -eq "PASS" })
if($success.status -ne "PASS" -or $verifiedUpdate.Count -ne 1){ throw "Verified GUI success update evidence required" }
$sourceDir = Join-Path (Split-Path -Parent $successEvidence) ([string]$verifiedUpdate[0].data_dir)
foreach($required in @("canonical_history.json","source_evidence.json","raw_responses")){
  if(-not (Test-Path -LiteralPath (Join-Path $sourceDir $required))){ throw "Success update evidence missing $required" }
}


$runDir = Join-Path $evidenceDir ("physical-gui-failure-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceDir "canonical_history.json") -Destination $runDir
Copy-Item -LiteralPath (Join-Path $sourceDir "source_evidence.json") -Destination $runDir
Copy-Item -LiteralPath (Join-Path $sourceDir "raw_responses") -Destination $runDir -Recurse

$history = Join-Path $runDir "canonical_history.json"
$sourceEvidenceFile = Join-Path $runDir "source_evidence.json"
$originalHistoryHash = Get-Sha256 $history
$controlId = 102
$operationLabel = '一键更新'
if($Operation -eq 'repair'){
  $controlId = 103
  $operationLabel = '一键修复'
  # Controlled fault in the isolated acceptance copy, never the user's data.
  [IO.File]::WriteAllText($history, "SSQ_CONTROLLED_CORRUPT_HISTORY_V1`n", [Text.UTF8Encoding]::new($false))
}
$beforeHistory = Get-Sha256 $history
$beforeEvidence = Get-Sha256 $sourceEvidenceFile
$exeHash = Get-Sha256 $exe
$updaterHash = Get-Sha256 $acceptedUpdater
$verifiedUpdaterHash = [string]$verifiedUpdate[0].backend_effect.updater_process.updater_exe_sha256
if($verifiedUpdaterHash -ne $updaterHash){ throw "Verified GUI update used a different updater hash" }
$materializedUpdaterDir = Join-Path (Join-Path $runDir "updater") $updaterHash
New-Item -ItemType Directory -Force -Path $materializedUpdaterDir | Out-Null
$materializedUpdater = Join-Path $materializedUpdaterDir (Split-Path -Leaf $acceptedUpdater)
Copy-Item -LiteralPath $acceptedUpdater -Destination $materializedUpdater -Force
if((Get-Sha256 $materializedUpdater) -ne $updaterHash){ throw "Materialized updater precondition hash mismatch" }
$processName = [System.IO.Path]::GetFileNameWithoutExtension($exe)
$savedDataDir = $env:GLP_DATA_DIR
$env:GLP_DATA_DIR = $runDir
$ruleMain = "GLP-SSQ-main-" + [Guid]::NewGuid().ToString("N")
$ruleUpdaterDist = "GLP-SSQ-updater-dist-" + [Guid]::NewGuid().ToString("N")
$ruleUpdaterMaterialized = "GLP-SSQ-updater-materialized-" + [Guid]::NewGuid().ToString("N")
$boot = $null
$guiPid = 0
$result = [ordered]@{
  schema="physical-gui-failure-smoke-v2"
  status="FAIL"
  scenario="controlled Windows outbound block"
  operation=$Operation
  control_id=$controlId
  original_canonical_sha256=$originalHistoryHash
  corruption_injected=($Operation -eq 'repair')
  exe=(Split-Path -Leaf $exe)
  exe_sha256=$exeHash
  updater_exe=(Split-Path -Leaf $acceptedUpdater)
  updater_sha256=$updaterHash
  materialized_updater=$materializedUpdater
  materialized_updater_sha256=(Get-Sha256 $materializedUpdater)
  github_sha=$env:GITHUB_SHA
  github_run_id=$env:GITHUB_RUN_ID
  data_dir=(Split-Path -Leaf $runDir)
  source_success_data_dir=(Split-Path -Leaf $sourceDir)
  before_canonical_sha256=$beforeHistory
  before_evidence_sha256=$beforeEvidence
}

try {
  New-NetFirewallRule -DisplayName $ruleMain -Direction Outbound -Program $exe -Action Block -Profile Any | Out-Null
  New-NetFirewallRule -DisplayName $ruleUpdaterDist -Direction Outbound -Program $acceptedUpdater -Action Block -Profile Any | Out-Null
  New-NetFirewallRule -DisplayName $ruleUpdaterMaterialized -Direction Outbound -Program $materializedUpdater -Action Block -Profile Any | Out-Null
  $result.firewall_rules_created = $true
  $result.firewall_programs = @($exe, $acceptedUpdater, $materializedUpdater)

  $baselinePids = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
  $boot = Start-Process -FilePath $exe -PassThru
  $window = Wait-MainWindow $boot $processName $exe $baselinePids
  $guiPid = $window.pid
  $operationButton = Get-Control $window.hwnd $controlId $guiPid
  $output = Get-Control $window.hwnd 201 $guiPid
  $status = Get-Control $window.hwnd 202 $guiPid
  $click = Click-Control $window.hwnd $operationButton
  $result.process_id = $guiPid
  $result.click_x = $click.x
  $result.click_y = $click.y

  $deadline = [DateTime]::UtcNow.AddSeconds($OperationTimeoutSeconds)
  $uiText = ""
  $statusText = ""
  while([DateTime]::UtcNow -lt $deadline){
    if(-not (Get-Process -Id $guiPid -ErrorAction SilentlyContinue)){ throw "Exact EXE exited during failure scenario" }
    $uiText = Get-NativeText $output
    $statusText = Get-NativeText $status
    if($statusText -match "FAIL" -and $uiText -match "Fail-Closed" -and $uiText.Contains("$operationLabel FAIL")){ break }
    Start-Sleep -Milliseconds 500
  }
  if($statusText -notmatch "FAIL" -or $uiText -notmatch "Fail-Closed" -or -not $uiText.Contains("$operationLabel FAIL")){
    throw "GUI did not expose the controlled network failure as Fail-Closed"
  }
  $result.ui_status = $statusText
  $uiOutputPath = Join-Path $runDir 'gui_failure_output.txt'
  [IO.File]::WriteAllText($uiOutputPath, $uiText, [Text.UTF8Encoding]::new($false))
  $result.ui_output_sha256 = Get-Sha256 $uiOutputPath
  $result.ui_fail_closed = $true
}
finally {
  if($guiPid -gt 0){ Stop-Process -Id $guiPid -Force -ErrorAction SilentlyContinue }
  if($null -ne $boot){ Stop-Process -Id $boot.Id -Force -ErrorAction SilentlyContinue }
  Remove-NetFirewallRule -DisplayName $ruleMain -ErrorAction SilentlyContinue
  Remove-NetFirewallRule -DisplayName $ruleUpdaterDist -ErrorAction SilentlyContinue
  Remove-NetFirewallRule -DisplayName $ruleUpdaterMaterialized -ErrorAction SilentlyContinue
  $env:GLP_DATA_DIR = $savedDataDir
}

$afterHistory = Get-Sha256 $history
$afterEvidence = Get-Sha256 $sourceEvidenceFile
$result.after_canonical_sha256 = $afterHistory
$result.after_evidence_sha256 = $afterEvidence
$result.canonical_unchanged = ($afterHistory -eq $beforeHistory)
$result.evidence_unchanged = ($afterEvidence -eq $beforeEvidence)

$failureManifests = @(Get-ChildItem -LiteralPath (Join-Path $runDir "failed") -Recurse -Filter "failure_evidence.json" -File -ErrorAction SilentlyContinue)
$result.failure_manifest_count = $failureManifests.Count
$result.failure_manifests = @($failureManifests | ForEach-Object {
  [ordered]@{ path=$_.FullName; sha256=(Get-Sha256 $_.FullName) }
})

$db = Join-Path $runDir "ledger.sqlite3"
if(-not (Test-Path -LiteralPath $db)){ throw "Failure scenario ledger missing" }
$pythonLedgerQuery = @'
import sqlite3
import sys
import json

db = sqlite3.connect(sys.argv[1])
try:
    print(json.dumps({
        "official_update_pass_count": db.execute("select count(*) from experiments where kind='official_update' and status='PASS'").fetchone()[0],
        "repair_pass_count": db.execute("select count(*) from experiments where kind='repair' and status='PASS'").fetchone()[0],
        "repair_fail_count": db.execute("select count(*) from experiments where kind='repair' and status='FAIL'").fetchone()[0],
    }))
finally:
    db.close()
'@
$ledgerText = & python -c $pythonLedgerQuery $db
if($LASTEXITCODE -ne 0){ throw "Could not inspect failure scenario ledger" }
$ledgerCounts = $ledgerText | ConvertFrom-Json
$result.official_update_pass_count = [int]$ledgerCounts.official_update_pass_count
$result.repair_pass_count = [int]$ledgerCounts.repair_pass_count
$result.repair_fail_count = [int]$ledgerCounts.repair_fail_count
if($Operation -eq 'repair' -and ($result.repair_pass_count -ne 0 -or $result.repair_fail_count -lt 1)){
  throw 'Corrupt-data offline repair did not produce its own FAIL ledger'
}

if(-not $result.canonical_unchanged -or -not $result.evidence_unchanged -or
   $result.failure_manifest_count -lt 1 -or $result.official_update_pass_count -ne 0 -or
   -not $result.ui_fail_closed){
  throw "Physical GUI failure acceptance contract did not hold"
}

$result.status = "PASS"
$result.tested_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss'Z'")
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $evidenceFull -Encoding utf8
Get-Content -LiteralPath $evidenceFull
