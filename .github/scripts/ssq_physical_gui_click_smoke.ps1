param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  # Retained for older workflow callers, but never used as click targets.
  [string]$Points = "",
  [string]$ButtonTexts = "",
  [int]$PreconditionIndex = -1,
  [int]$SettleMs = 900,
  [int]$OperationTimeoutSeconds = 900
)

$ErrorActionPreference = "Stop"
if($PreconditionIndex -ne -1){ throw "Unverified precondition clicks are forbidden" }
if($OperationTimeoutSeconds -lt 1 -or $OperationTimeoutSeconds -gt 1800){ throw "Invalid operation timeout" }
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class PhysicalGuiClick {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr hWnd, int id);
  [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder text, int length);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder text, int length);
  [DllImport("user32.dll", EntryPoint="SendMessageW")] public static extern IntPtr SendMessageRaw(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll", EntryPoint="SendMessageW", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageText(IntPtr hWnd, uint msg, IntPtr wParam, StringBuilder lParam);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT point);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
}
"@

$operations = @(
  @{ name="predict"; id=101; marker1="Final Gate"; marker2="Freeze" },
  @{ name="update"; id=102; marker1="Canonical"; marker2="Source receipts" },
  @{ name="repair"; id=103; marker1='"status": "PASS"'; marker2="integrity" },
  @{ name="audit"; id=104; marker1="Software verdict"; marker2="Court hash" }
)
$buttonNames = @()
if($ButtonTexts){ $buttonNames = @($ButtonTexts.Split(';')) }
if($buttonNames.Count -gt 0 -and $buttonNames.Count -ne 4){ throw "ButtonTexts must contain exactly four names" }
$exeResolved = (Resolve-Path -LiteralPath $ExePath).Path
$exeHash = (Get-FileHash -LiteralPath $exeResolved -Algorithm SHA256).Hash.ToLowerInvariant()
$evidenceResolved = [System.IO.Path]::GetFullPath($EvidencePath)
$evidenceDir = Split-Path -Parent $evidenceResolved
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
$verifier = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\SSQ\tools\verify_gui_effect.py")).Path
$processName = [System.IO.Path]::GetFileNameWithoutExtension($exeResolved)
$savedDataDir = $env:GLP_DATA_DIR
$results = @()
$failure = $null

function Get-TextHash([string]$value){
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($value)
    return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace("-", "").ToLowerInvariant()
  } finally { $sha.Dispose() }
}

function Write-UiText([string]$path,[string]$value){
  [System.IO.File]::WriteAllText($path,$value,[System.Text.UTF8Encoding]::new($false))
}

function Wait-MainWindow([System.Diagnostics.Process]$boot,[int[]]$baselinePids){
  for($attempt=0;$attempt -lt 120;$attempt++){
    Start-Sleep -Milliseconds 250
    $candidates = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object {
      $_.MainWindowHandle -ne 0 -and ($_.Id -eq $boot.Id -or $baselinePids -notcontains $_.Id)
    })
    foreach($candidate in $candidates){
      try {
        if(-not [string]::Equals($candidate.Path, $exeResolved, [StringComparison]::OrdinalIgnoreCase)){ continue }
        if($candidate.Id -ne $boot.Id){
          $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($candidate.Id)"
          if($null -eq $cim -or [int]$cim.ParentProcessId -ne $boot.Id){ continue }
        }
        return @{ hwnd=[IntPtr]$candidate.MainWindowHandle; pid=[int]$candidate.Id }
      } catch { continue }
    }
  }
  throw "Exact EXE's newly spawned main window was not found"
}

function Get-NativeText([IntPtr]$handle){
  $WM_GETTEXT = 0x000D
  $WM_GETTEXTLENGTH = 0x000E
  $length = [PhysicalGuiClick]::SendMessageRaw($handle,$WM_GETTEXTLENGTH,[IntPtr]::Zero,[IntPtr]::Zero).ToInt32()
  if($length -lt 0 -or $length -gt 1048576){ throw "Invalid native control text length: $length" }
  $buffer = New-Object System.Text.StringBuilder ([Math]::Max(2,$length + 2))
  [void][PhysicalGuiClick]::SendMessageText($handle,$WM_GETTEXT,[IntPtr]($buffer.Capacity),$buffer)
  return $buffer.ToString()
}

function Get-Control([IntPtr]$window,[int]$id,[int]$processId,[string]$expectedClass){
  $handle = [PhysicalGuiClick]::GetDlgItem($window,$id)
  if($handle -eq [IntPtr]::Zero){ throw "Control $id missing from exact EXE window" }
  if([PhysicalGuiClick]::GetParent($handle) -ne $window){ throw "Control $id is not a direct child" }
  [uint32]$ownerPid = 0
  if([PhysicalGuiClick]::GetWindowThreadProcessId($handle,[ref]$ownerPid) -eq 0 -or $ownerPid -ne $processId){
    throw "Control $id belongs to a different process"
  }
  $className = New-Object System.Text.StringBuilder 64
  if([PhysicalGuiClick]::GetClassNameW($handle,$className,$className.Capacity) -eq 0 -or
      $className.ToString() -ne $expectedClass){ throw "Control $id has wrong window class" }
  if(-not [PhysicalGuiClick]::IsWindowVisible($handle)){ throw "Control $id is not visible" }
  if($expectedClass -eq "BUTTON" -and -not [PhysicalGuiClick]::IsWindowEnabled($handle)){
    throw "Control $id is disabled"
  }
  $nativeText = Get-NativeText $handle
  return @{ hwnd=$handle; name=$nativeText; class=$className.ToString() }
}

function Get-EditValue($control){
  return [string](Get-NativeText $control.hwnd)
}

function Read-BackendEffect([string]$dataDir,[string]$operation,[int]$afterId,[int]$parentPid){
  $json = & python -B $verifier --data-dir $dataDir --operation $operation --after-id $afterId --parent-pid $parentPid
  if($LASTEXITCODE -ne 0 -or -not $json){ throw "Backend verifier failed" }
  return ($json | ConvertFrom-Json)
}

function Click-Control([IntPtr]$window,[IntPtr]$button){
  $rect = New-Object PhysicalGuiClick+RECT
  $mainRect = New-Object PhysicalGuiClick+RECT
  if(-not [PhysicalGuiClick]::GetWindowRect($button,[ref]$rect) -or
      -not [PhysicalGuiClick]::GetWindowRect($window,[ref]$mainRect)){
    throw "Cannot resolve exact button/window screen rectangles"
  }
  if($rect.Right - $rect.Left -lt 4 -or $rect.Bottom - $rect.Top -lt 4){ throw "Button rectangle is empty" }
  $point = New-Object PhysicalGuiClick+POINT
  $point.X = [int][Math]::Floor(($rect.Left + $rect.Right) / 2)
  $point.Y = [int][Math]::Floor(($rect.Top + $rect.Bottom) / 2)
  if($point.X -lt $mainRect.Left -or $point.X -ge $mainRect.Right -or
      $point.Y -lt $mainRect.Top -or $point.Y -ge $mainRect.Bottom){ throw "Button point is outside exact EXE window" }
  [void][PhysicalGuiClick]::SetForegroundWindow($window)
  Start-Sleep -Milliseconds 250
  if([PhysicalGuiClick]::GetForegroundWindow() -ne $window){ throw "Exact EXE window could not receive foreground focus" }
  if([PhysicalGuiClick]::WindowFromPoint($point) -ne $button){ throw "Button is occluded or hit-test targets another control" }
  if(-not [PhysicalGuiClick]::SetCursorPos($point.X,$point.Y)){ throw "Cannot position physical cursor" }
  [PhysicalGuiClick]::mouse_event(0x0002,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 80
  [PhysicalGuiClick]::mouse_event(0x0004,0,0,0,[UIntPtr]::Zero)
  return @{ x=$point.X; y=$point.Y }
}

function Stop-LaunchedProcess([System.Diagnostics.Process]$boot,[int]$guiPid){
  if($guiPid -gt 0){ Stop-Process -Id $guiPid -Force -ErrorAction SilentlyContinue }
  if($null -ne $boot){ Stop-Process -Id $boot.Id -Force -ErrorAction SilentlyContinue }
}

try {
  for($i=0;$i -lt $operations.Count;$i++){
    $op = $operations[$i]
    $dataDir = Join-Path $evidenceDir ("physical-gui-run-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $dataDir | Out-Null
    $env:GLP_DATA_DIR = $dataDir
    $baselinePids = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
    $boot = $null
    $guiPid = 0
    try {
      $boot = Start-Process -FilePath $exeResolved -PassThru
      $window = Wait-MainWindow $boot $baselinePids
      $guiPid = $window.pid
      $button = Get-Control $window.hwnd $op.id $guiPid "BUTTON"
      if(-not $button.name){ throw "Button $($op.id) has no accessible name" }
      if($buttonNames.Count -eq 4 -and $button.name -ne $buttonNames[$i]){
        throw "Button $($op.id) name does not match expected name"
      }
      $output = Get-Control $window.hwnd 201 $guiPid "EDIT"
      $status = Get-Control $window.hwnd 202 $guiPid "STATIC"
      $beforeText = Get-EditValue $output
      $beforeStatus = [string](Get-NativeText $status.hwnd)
      $beforeOutputPath = Join-Path $dataDir "gui_before.txt"
      Write-UiText $beforeOutputPath $beforeText
      $before = Read-BackendEffect $dataDir $op.name 0 $guiPid
      if($before.latest_id -ne 0){ throw "Backend ledger was not empty before physical click" }
      $click = Click-Control $window.hwnd $button.hwnd
      if($SettleMs -gt 0){ Start-Sleep -Milliseconds $SettleMs }
      $deadline = [DateTime]::UtcNow.AddSeconds($OperationTimeoutSeconds)
      $effect = $null
      $afterText = ""
      $afterStatus = ""
      while([DateTime]::UtcNow -lt $deadline){
        if(-not (Get-Process -Id $guiPid -ErrorAction SilentlyContinue)){
          throw "Exact EXE GUI exited before backend effect was proved"
        }
        $effect = Read-BackendEffect $dataDir $op.name 0 $guiPid
        if($effect.status -eq "FAIL"){
          $effectJson = $effect | ConvertTo-Json -Compress -Depth 12
          throw "Backend $($op.name) FAIL: $($effect.reason); effect=$effectJson"
        }
        if($effect.status -eq "PASS"){
          $afterText = Get-EditValue $output
          $afterStatus = [string](Get-NativeText $status.hwnd)
          if($afterText -ne $beforeText -and
              $afterText.Contains($op.marker1) -and $afterText.Contains($op.marker2) -and
              $afterText.Contains([string]$effect.display_token) -and
              $afterStatus -and $afterStatus -ne $beforeStatus -and
              $afterStatus -notmatch "FAIL"){
            break
          }
        }
        Start-Sleep -Milliseconds 500
      }
      if($null -eq $effect -or $effect.status -ne "PASS" -or
          $afterText -eq $beforeText -or -not $afterText.Contains($op.marker1) -or
          -not $afterText.Contains($op.marker2) -or
          -not $afterText.Contains([string]$effect.display_token) -or
          -not $afterStatus -or $afterStatus -eq $beforeStatus -or
          $afterStatus -match "FAIL"){
        throw "Timed out without operation-specific GUI output and persisted backend PASS"
      }
      $afterOutputPath = Join-Path $dataDir "gui_after.txt"
      Write-UiText $afterOutputPath $afterText
      $dataLeaf = Split-Path -Leaf $dataDir
      $results += [ordered]@{
        button_index=$i+1; status="PASS"; operation=$op.name; control_id=$op.id
        control_name=$button.name; control_class=$button.class; process_id=$guiPid
        x=$click.x; y=$click.y; control_verified=$true; physical_click_verified=$true
        output_verified=$true; backend_effect_verified=$true
        before_output_sha256=(Get-TextHash $beforeText)
        after_output_sha256=(Get-TextHash $afterText)
        before_output_artifact="$dataLeaf/gui_before.txt"
        before_output_artifact_sha256=(Get-FileHash -LiteralPath $beforeOutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        after_output_artifact="$dataLeaf/gui_after.txt"
        after_output_artifact_sha256=(Get-FileHash -LiteralPath $afterOutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        before_status=$beforeStatus; after_status=$afterStatus
        output_markers=@($op.marker1,$op.marker2)
        displayed_backend_token=$effect.display_token
        backend_effect=$effect
        data_dir=$dataLeaf
      }
    } finally {
      Stop-LaunchedProcess $boot $guiPid
    }
  }
} catch {
  $failure = "$(($_ | Out-String).Trim())"
  if($results.Count -lt $operations.Count){
    $op = $operations[$results.Count]
    $results += [ordered]@{ button_index=$results.Count+1; operation=$op.name; control_id=$op.id; status="FAIL"; error=$failure }
  }
} finally {
  $env:GLP_DATA_DIR = $savedDataDir
}

$overallStatus = "FAIL"
if($null -eq $failure -and $results.Count -eq 4){ $overallStatus = "PASS" }
$report = [ordered]@{
  schema="physical-gui-click-smoke-v2"
  status=$overallStatus
  exe=(Split-Path -Leaf $exeResolved)
  exe_sha256=$exeHash
  tested_at=[DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss'Z'")
  github_sha=$env:GITHUB_SHA
  github_run_id=$env:GITHUB_RUN_ID
  activation="exact child BUTTON hit-test + foreground cursor mouse_event LEFTDOWN/LEFTUP"
  coordinate_fallback=$false
  visual_hash_as_proof=$false
  buttons=$results
  error=$failure
}
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $evidenceResolved -Encoding utf8
Get-Content -LiteralPath $evidenceResolved
if($null -ne $failure){ throw "Physical GUI acceptance FAIL: $failure" }
