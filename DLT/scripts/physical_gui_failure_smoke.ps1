param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$UpdaterExePath,
  [Parameter(Mandatory=$true)][string]$SuccessBackendPath,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [ValidateSet('update','repair')][string]$Operation = 'update',
  [int]$OperationTimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
if($OperationTimeoutSeconds -lt 30 -or $OperationTimeoutSeconds -gt 1200){ throw 'Invalid operation timeout' }

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class DltFailureGui {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr hWnd, int id);
  [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumWindowsProc cb, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll", EntryPoint="SendMessageW")] public static extern IntPtr SendMessageRaw(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll", EntryPoint="SendMessageW", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageText(IntPtr hWnd, uint msg, IntPtr wParam, StringBuilder lParam);

  public static IntPtr FindVisibleChildByClass(IntPtr parent, string wanted) {
    IntPtr found = IntPtr.Zero;
    EnumChildWindows(parent, delegate(IntPtr child, IntPtr lp) {
      if(!IsWindowVisible(child)) return true;
      var cls = new StringBuilder(128);
      GetClassNameW(child, cls, cls.Capacity);
      if(string.Equals(cls.ToString(), wanted, StringComparison.OrdinalIgnoreCase)) {
        found = child;
        return false;
      }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
"@

function Sha256([string]$Path){
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function NativeText([IntPtr]$Handle){
  $len=[DltFailureGui]::SendMessageRaw($Handle,0x000E,[IntPtr]::Zero,[IntPtr]::Zero).ToInt32()
  if($len -lt 0 -or $len -gt 1048576){ throw 'Invalid native text length' }
  $buffer=New-Object System.Text.StringBuilder ([Math]::Max(2,$len+2))
  [void][DltFailureGui]::SendMessageText($Handle,0x000D,[IntPtr]$buffer.Capacity,$buffer)
  return $buffer.ToString()
}

function Wait-MainWindow([System.Diagnostics.Process]$Boot,[string]$ProcessName,[string]$ExactExe,[int[]]$BaselinePids){
  for($i=0;$i -lt 160;$i++){
    Start-Sleep -Milliseconds 250
    $rows=@(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Where-Object {
      $_.MainWindowHandle -ne 0 -and ($_.Id -eq $Boot.Id -or $BaselinePids -notcontains $_.Id)
    })
    foreach($row in $rows){
      try {
        if(-not [string]::Equals($row.Path,$ExactExe,[StringComparison]::OrdinalIgnoreCase)){ continue }
        if($row.Id -ne $Boot.Id){
          $cim=Get-CimInstance Win32_Process -Filter "ProcessId=$($row.Id)"
          if($null -eq $cim -or [int]$cim.ParentProcessId -ne $Boot.Id){ continue }
        }
        return @{ hwnd=[IntPtr]$row.MainWindowHandle; pid=[int]$row.Id }
      } catch {}
    }
  }
  throw 'Exact DLT EXE main window not found'
}

function Get-Button([IntPtr]$Window,[int]$Id){
  $h=[DltFailureGui]::GetDlgItem($Window,$Id)
  if($h -eq [IntPtr]::Zero -or [DltFailureGui]::GetParent($h) -ne $Window){ throw "Control $Id invalid" }
  return $h
}

function Click-Button([IntPtr]$Window,[IntPtr]$Button){
  $r=New-Object DltFailureGui+RECT
  if(-not [DltFailureGui]::GetWindowRect($Button,[ref]$r)){ throw 'button rectangle unavailable' }
  $p=New-Object DltFailureGui+POINT
  $p.X=[int][Math]::Floor(($r.Left+$r.Right)/2)
  $p.Y=[int][Math]::Floor(($r.Top+$r.Bottom)/2)
  [void][DltFailureGui]::SetForegroundWindow($Window)
  Start-Sleep -Milliseconds 250
  if([DltFailureGui]::GetForegroundWindow() -ne $Window){ throw 'DLT window did not receive foreground' }
  if([DltFailureGui]::WindowFromPoint($p) -ne $Button){ throw 'button hit-test failed' }
  if(-not [DltFailureGui]::SetCursorPos($p.X,$p.Y)){ throw 'SetCursorPos failed' }
  [DltFailureGui]::mouse_event(0x0002,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 80
  [DltFailureGui]::mouse_event(0x0004,0,0,0,[UIntPtr]::Zero)
  return @{x=$p.X;y=$p.Y}
}

function Ledger-Counts([string]$Db){
  if(-not (Test-Path -LiteralPath $Db)){ throw 'ledger.sqlite3 missing' }
  $code=@'
import json, sqlite3, sys
db=sqlite3.connect(sys.argv[1])
try:
    def n(kind,status):
        return db.execute("select count(*) from experiments where kind=? and status=?",(kind,status)).fetchone()[0]
    print(json.dumps({
        "official_update_pass": n("official_update","PASS"),
        "official_update_fail": n("official_update","FAIL"),
        "repair_pass": n("repair","PASS"),
        "repair_fail": n("repair","FAIL"),
    }))
finally:
    db.close()
'@
  $text=& python -c $code $Db
  if($LASTEXITCODE -ne 0){ throw 'ledger query failed' }
  return ($text | ConvertFrom-Json)
}

$exe=(Resolve-Path -LiteralPath $ExePath).Path
$updater=(Resolve-Path -LiteralPath $UpdaterExePath).Path
$success=(Resolve-Path -LiteralPath $SuccessBackendPath).Path
$evidenceFull=[IO.Path]::GetFullPath($EvidencePath)
$evidenceDir=Split-Path -Parent $evidenceFull
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

$summary=Get-Content -LiteralPath $success -Raw | ConvertFrom-Json
$updateRows=@($summary.operations | Where-Object { [int]$_.operation_id -eq 1002 -and $_.status -eq 'PASS' })
if($summary.status -ne 'PASS' -or $updateRows.Count -ne 1){ throw 'Current-run physical GUI Update PASS evidence required' }
$updateEvidence=[string]$updateRows[0].evidence_path
if(-not (Test-Path -LiteralPath $updateEvidence)){ throw 'Physical GUI Update backend evidence path missing' }
$sourceData=Join-Path (Split-Path -Parent $updateEvidence) 'data'
if(-not (Test-Path -LiteralPath $sourceData -PathType Container)){ throw 'Verified source data directory missing' }

$runDir=Join-Path $evidenceDir ("physical-gui-failure-"+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
Get-ChildItem -LiteralPath $sourceData -Force | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $runDir -Recurse -Force }

$history=Join-Path $runDir 'canonical_history.json'
$sourceEvidence=Join-Path $runDir 'source_evidence.json'
if(-not (Test-Path $history) -or -not (Test-Path $sourceEvidence)){ throw 'Canonical/source evidence missing from isolated copy' }
$originalCanonical=Sha256 $history
$controlId=1002
if($Operation -eq 'repair'){
  $controlId=1003
  [IO.File]::WriteAllText($history,("DLT_CONTROLLED_CORRUPT_HISTORY_V1"+[Environment]::NewLine),[Text.UTF8Encoding]::new($false))
}
$beforeCanonical=Sha256 $history
$beforeEvidence=Sha256 $sourceEvidence
$beforeCounts=Ledger-Counts (Join-Path $runDir 'ledger.sqlite3')
$updaterResults=Join-Path $runDir 'updater_results'
New-Item -ItemType Directory -Force -Path $updaterResults | Out-Null
$beforeUpdaterFiles=@(Get-ChildItem -LiteralPath $updaterResults -Filter '*.json' -File -ErrorAction SilentlyContinue | ForEach-Object {$_.FullName})

$acceptanceDir=Join-Path $runDir 'gui_acceptance'
New-Item -ItemType Directory -Force -Path $acceptanceDir | Out-Null
$operationEvidence=Join-Path $acceptanceDir ("operation-"+$controlId+".json")

$savedData=$env:GLP_DATA_DIR
$savedAcceptance=$env:GLP_GUI_ACCEPTANCE_DIR
$env:GLP_DATA_DIR=$runDir
$env:GLP_GUI_ACCEPTANCE_DIR=$acceptanceDir
$ruleMain="GLP-DLT-main-"+[Guid]::NewGuid().ToString('N')
$ruleUpdater="GLP-DLT-updater-"+[Guid]::NewGuid().ToString('N')
$processName=[IO.Path]::GetFileNameWithoutExtension($exe)
$boot=$null
$guiPid=0
$uiText=''
try {
  New-NetFirewallRule -DisplayName $ruleMain -Direction Outbound -Program $exe -Action Block -Profile Any | Out-Null
  New-NetFirewallRule -DisplayName $ruleUpdater -Direction Outbound -Program $updater -Action Block -Profile Any | Out-Null
  $baseline=@(Get-Process -Name $processName -ErrorAction SilentlyContinue | ForEach-Object {$_.Id})
  $boot=Start-Process -FilePath $exe -PassThru
  $window=Wait-MainWindow $boot $processName $exe $baseline
  $guiPid=[int]$window.pid
  $button=Get-Button $window.hwnd $controlId
  $output=[DltFailureGui]::FindVisibleChildByClass($window.hwnd,'EDIT')
  if($output -eq [IntPtr]::Zero){ throw 'Visible output EDIT control not found' }
  $click=Click-Button $window.hwnd $button

  $deadline=[DateTime]::UtcNow.AddSeconds($OperationTimeoutSeconds)
  while([DateTime]::UtcNow -lt $deadline){
    if(-not (Get-Process -Id $guiPid -ErrorAction SilentlyContinue)){ throw 'Exact DLT EXE exited during failure scenario' }
    $uiText=NativeText $output
    if((Test-Path -LiteralPath $operationEvidence) -and $uiText.Contains('Fail-Closed') -and $uiText.Contains('执行失败')){ break }
    Start-Sleep -Milliseconds 500
  }
  if(-not (Test-Path -LiteralPath $operationEvidence)){ throw 'GUI failure backend evidence was not written' }
  if(-not ($uiText.Contains('Fail-Closed') -and $uiText.Contains('执行失败'))){ throw 'GUI did not visibly expose Fail-Closed state' }

  $backend=Get-Content -LiteralPath $operationEvidence -Raw | ConvertFrom-Json
  if($backend.schema -ne 'dlt-physical-gui-backend-v1' -or $backend.status -ne 'FAIL' -or [int]$backend.operation_id -ne $controlId){
    throw 'GUI backend failure evidence is not bound to the clicked operation'
  }
}
finally {
  if($guiPid -gt 0){ Stop-Process -Id $guiPid -Force -ErrorAction SilentlyContinue }
  if($null -ne $boot){ Stop-Process -Id $boot.Id -Force -ErrorAction SilentlyContinue }
  Remove-NetFirewallRule -DisplayName $ruleMain -ErrorAction SilentlyContinue
  Remove-NetFirewallRule -DisplayName $ruleUpdater -ErrorAction SilentlyContinue
  $env:GLP_DATA_DIR=$savedData
  $env:GLP_GUI_ACCEPTANCE_DIR=$savedAcceptance
}

$afterCanonical=Sha256 $history
$afterEvidence=Sha256 $sourceEvidence
$afterCounts=Ledger-Counts (Join-Path $runDir 'ledger.sqlite3')
$afterUpdaterFiles=@(Get-ChildItem -LiteralPath $updaterResults -Filter '*.json' -File -ErrorAction SilentlyContinue | ForEach-Object {$_.FullName})
$newUpdaterFiles=@($afterUpdaterFiles | Where-Object {$beforeUpdaterFiles -notcontains $_})
$expectedMode=$(if($Operation -eq 'repair'){'data-repair'}else{'data-update'})
$failedUpdater=@()
foreach($path in $newUpdaterFiles){
  try {
    $u=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if($u.schema -eq 'dlt-independent-updater-v1' -and $u.mode -eq $expectedMode -and $u.status -eq 'FAIL'){
      $failedUpdater += [ordered]@{path=$path;sha256=(Sha256 $path);error_type=$u.error_type}
    }
  } catch {}
}
if($failedUpdater.Count -lt 1){ throw 'Independent Updater FAIL evidence missing' }

$tmp=Join-Path $runDir 'gui_failure_output.txt'
[IO.File]::WriteAllText($tmp,$uiText,[Text.UTF8Encoding]::new($false))
$report=[ordered]@{
  schema='dlt-physical-gui-failure-v1'
  status='PASS'
  operation=$Operation
  control_id=$controlId
  scenario='controlled corrupt-data/offline physical GUI fail-closed'
  corruption_injected=($Operation -eq 'repair')
  original_canonical_sha256=$originalCanonical
  exe_sha256=(Sha256 $exe)
  updater_sha256=(Sha256 $updater)
  github_sha=$env:GITHUB_SHA
  github_run_id=$env:GITHUB_RUN_ID
  before_canonical_sha256=$beforeCanonical
  after_canonical_sha256=$afterCanonical
  before_evidence_sha256=$beforeEvidence
  after_evidence_sha256=$afterEvidence
  canonical_unchanged=($beforeCanonical -eq $afterCanonical)
  evidence_unchanged=($beforeEvidence -eq $afterEvidence)
  backend_status='FAIL'
  ui_fail_closed=$true
  ui_output_sha256=(Sha256 $tmp)
  official_update_pass_increment=([int]$afterCounts.official_update_pass-[int]$beforeCounts.official_update_pass)
  official_update_fail_increment=([int]$afterCounts.official_update_fail-[int]$beforeCounts.official_update_fail)
  repair_pass_increment=([int]$afterCounts.repair_pass-[int]$beforeCounts.repair_pass)
  repair_fail_increment=([int]$afterCounts.repair_fail-[int]$beforeCounts.repair_fail)
  updater_failure_count=$failedUpdater.Count
  updater_failures=$failedUpdater
  tested_at=[DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss'Z'")
}
if(-not $report.canonical_unchanged -or -not $report.evidence_unchanged -or $report.official_update_pass_increment -ne 0){
  throw 'Failed operation mutated accepted canonical/source evidence or created a false update PASS'
}
if($Operation -eq 'update' -and $report.official_update_fail_increment -lt 1){ throw 'Offline Update did not record its own FAIL ledger' }
if($Operation -eq 'repair' -and ($report.corruption_injected -ne $true -or $report.repair_pass_increment -ne 0 -or $report.repair_fail_increment -lt 1)){
  throw 'Corrupt-data offline Repair did not record FAIL without false PASS'
}
$report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $evidenceFull -Encoding utf8
Get-Content -LiteralPath $evidenceFull
