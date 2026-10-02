param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$Points,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [string]$ButtonTexts = "",
  [int]$PreconditionIndex = -1,
  [int]$SettleMs = 900,
  [string]$BackendEvidencePath = "",
  [int]$BackendTimeoutSeconds = 1800
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class PhysicalGuiClick {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT point);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr hWndParent, EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hWnd);

  public static bool FindVisibleTopLevelWindow(int[] pids, out IntPtr hwnd, out int pid) {
    var wanted = new HashSet<int>(pids ?? new int[0]);
    IntPtr foundHwnd = IntPtr.Zero;
    int foundPid = 0;
    EnumWindows(delegate(IntPtr candidate, IntPtr lp) {
      if (!IsWindowVisible(candidate)) return true;
      uint ownerPid = 0;
      GetWindowThreadProcessId(candidate, out ownerPid);
      if (!wanted.Contains((int)ownerPid)) return true;
      RECT r;
      if (!GetWindowRect(candidate, out r) || r.Right <= r.Left || r.Bottom <= r.Top) return true;
      foundHwnd = candidate;
      foundPid = (int)ownerPid;
      return false;
    }, IntPtr.Zero);
    hwnd = foundHwnd;
    pid = foundPid;
    return foundHwnd != IntPtr.Zero;
  }

  public static bool FindChildButtonCenter(IntPtr parent, string name, out int x, out int y) {
    int fx = 0, fy = 0;
    bool found = false;
    EnumChildWindows(parent, delegate(IntPtr child, IntPtr lp) {
      var cls = new StringBuilder(128);
      var txt = new StringBuilder(512);
      GetClassNameW(child, cls, cls.Capacity);
      GetWindowTextW(child, txt, txt.Capacity);
      if (IsWindowVisible(child) &&
          string.Equals(cls.ToString(), "Button", StringComparison.OrdinalIgnoreCase) &&
          string.Equals(txt.ToString(), name, StringComparison.Ordinal)) {
        RECT r;
        if (GetWindowRect(child, out r) && r.Right > r.Left && r.Bottom > r.Top) {
          fx = r.Left + (r.Right - r.Left) / 2;
          fy = r.Top + (r.Bottom - r.Top) / 2;
          found = true;
          return false;
        }
      }
      return true;
    }, IntPtr.Zero);
    x = fx; y = fy;
    return found;
  }

  public static bool FindNthVisibleButtonCenter(IntPtr parent, int index, out int x, out int y) {
    var rects = new List<RECT>();
    EnumChildWindows(parent, delegate(IntPtr child, IntPtr lp) {
      var cls = new StringBuilder(128);
      GetClassNameW(child, cls, cls.Capacity);
      if (IsWindowVisible(child) &&
          string.Equals(cls.ToString(), "Button", StringComparison.OrdinalIgnoreCase)) {
        RECT r;
        if (GetWindowRect(child, out r) && r.Right > r.Left && r.Bottom > r.Top) rects.Add(r);
      }
      return true;
    }, IntPtr.Zero);
    rects.Sort(delegate(RECT a, RECT b) {
      int row = a.Top.CompareTo(b.Top);
      return row != 0 ? row : a.Left.CompareTo(b.Left);
    });
    if (index < 0 || index >= rects.Count) { x = 0; y = 0; return false; }
    var target = rects[index];
    x = target.Left + (target.Right - target.Left) / 2;
    y = target.Top + (target.Bottom - target.Top) / 2;
    return true;
  }
}
"@
$MOUSEEVENTF_LEFTDOWN=0x0002
$MOUSEEVENTF_LEFTUP=0x0004
$parsed=@()
foreach($token in $Points.Split(';')){
  $xy=$token.Split(',')
  if($xy.Count -ne 2){ throw "Bad point: $token" }
  $parsed += ,@([double]$xy[0],[double]$xy[1])
}
if($parsed.Count -ne 4){ throw "Exactly four GUI points are required" }

function Wait-MainWindow([System.Diagnostics.Process]$p,[string]$processName,[int[]]$baselinePids){
  for($i=0;$i -lt 120;$i++){
    Start-Sleep -Milliseconds 250
    try { $p.Refresh() } catch {}
    $candidates = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object {
      $baselinePids -notcontains $_.Id
    })
    if($candidates.Count -gt 0){
      # .NET Process.MainWindowHandle can remain zero for a native Win32 window
      # created by a PyInstaller one-file child. Enumerate real top-level HWNDs
      # and bind them to the exact new process IDs from this launch.
      [IntPtr]$nativeHwnd = [IntPtr]::Zero
      [int]$nativePid = 0
      [int[]]$candidatePids = @($candidates | ForEach-Object { [int]$_.Id })
      if([PhysicalGuiClick]::FindVisibleTopLevelWindow($candidatePids,[ref]$nativeHwnd,[ref]$nativePid)){
        return @{ hwnd=$nativeHwnd; pid=$nativePid }
      }

      $gui = $candidates | Where-Object { $_.MainWindowHandle -ne 0 } | Sort-Object StartTime -Descending | Select-Object -First 1
      if($null -ne $gui){
        return @{ hwnd=[IntPtr]$gui.MainWindowHandle; pid=$gui.Id }
      }
    }
    if(-not $p.HasExited -and $p.MainWindowHandle -ne 0){
      return @{ hwnd=[IntPtr]$p.MainWindowHandle; pid=$p.Id }
    }
  }
  $newPids = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object { $baselinePids -notcontains $_.Id } | ForEach-Object { $_.Id })
  throw "Main window handle not found in bootloader or spawned GUI process; new_process_ids=$($newPids -join ',')"
}
function Get-Rect([IntPtr]$hwnd){
  $r=New-Object PhysicalGuiClick+RECT
  if(-not [PhysicalGuiClick]::GetWindowRect($hwnd,[ref]$r)){ throw "GetWindowRect failed" }
  return $r
}
function Get-WindowHash([IntPtr]$hwnd){
  $bounds=[System.Windows.Forms.SystemInformation]::VirtualScreen
  if($bounds.Width -lt 200 -or $bounds.Height -lt 200){ throw "Unexpected desktop size $($bounds.Width) x $($bounds.Height)" }
  $bmp=New-Object System.Drawing.Bitmap $bounds.Width,$bounds.Height
  $g=[System.Drawing.Graphics]::FromImage($bmp)
  try { $g.CopyFromScreen($bounds.Left,$bounds.Top,0,0,$bmp.Size) }
  finally { $g.Dispose() }
  $tmp=[System.IO.Path]::GetTempFileName()+".png"
  try {
    $bmp.Save($tmp,[System.Drawing.Imaging.ImageFormat]::Png)
    return (Get-FileHash $tmp -Algorithm SHA256).Hash.ToLower()
  } finally {
    $bmp.Dispose()
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Find-ButtonPoint([IntPtr]$hwnd,[string]$name){
  $root=[System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  foreach($el in $all){
    try {
      if($el.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and $el.Current.Name -eq $name){
        $r=$el.Current.BoundingRectangle
        if($r.Width -gt 2 -and $r.Height -gt 2){
          return @{x=[int]($r.Left+$r.Width/2);y=[int]($r.Top+$r.Height/2);name=$name;locator="UIAutomation"}
        }
      }
    } catch {}
  }

  # Native Win32 applications do not always expose child BUTTON controls through
  # the runner's UI Automation provider. Enumerate real child HWNDs by exact
  # button text, then still perform a foreground cursor + physical mouse_event click.
  [int]$wx=0
  [int]$wy=0
  if([PhysicalGuiClick]::FindChildButtonCenter($hwnd,$name,[ref]$wx,[ref]$wy)){
    return @{x=$wx;y=$wy;name=$name;locator="Win32ChildHWND"}
  }
  throw "Button not found in UI Automation tree or Win32 child HWNDs: $name"
}
function Click-ScreenPoint([IntPtr]$hwnd,[int]$x,[int]$y){
  [void][PhysicalGuiClick]::SetForegroundWindow($hwnd)
  Start-Sleep -Milliseconds 200
  if(-not [PhysicalGuiClick]::SetCursorPos($x,$y)){ throw "SetCursorPos failed at $x,$y" }
  [PhysicalGuiClick]::mouse_event($MOUSEEVENTF_LEFTDOWN,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 80
  [PhysicalGuiClick]::mouse_event($MOUSEEVENTF_LEFTUP,0,0,0,[UIntPtr]::Zero)
  return @{x=$x;y=$y}
}

function Click-Normalized([IntPtr]$hwnd,[double]$rx,[double]$ry){
  $r=New-Object PhysicalGuiClick+RECT
  if(-not [PhysicalGuiClick]::GetClientRect($hwnd,[ref]$r)){ throw "GetClientRect failed" }
  $origin=New-Object PhysicalGuiClick+POINT
  $origin.X=0; $origin.Y=0
  if(-not [PhysicalGuiClick]::ClientToScreen($hwnd,[ref]$origin)){ throw "ClientToScreen failed" }
  $x=[int]($origin.X+($r.Right-$r.Left)*$rx)
  $y=[int]($origin.Y+($r.Bottom-$r.Top)*$ry)
  [void][PhysicalGuiClick]::SetForegroundWindow($hwnd)
  Start-Sleep -Milliseconds 200
  if(-not [PhysicalGuiClick]::SetCursorPos($x,$y)){ throw "SetCursorPos failed at $x,$y" }
  [PhysicalGuiClick]::mouse_event($MOUSEEVENTF_LEFTDOWN,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 80
  [PhysicalGuiClick]::mouse_event($MOUSEEVENTF_LEFTUP,0,0,0,[UIntPtr]::Zero)
  return @{x=$x;y=$y}
}
function Stop-Tree([System.Diagnostics.Process]$p,[int]$guiPid=0){
  if($guiPid -gt 0 -and $guiPid -ne $p.Id){
    try { Stop-Process -Id $guiPid -Force -ErrorAction SilentlyContinue } catch {}
  }
  try {
    $p.Refresh()
    if(-not $p.HasExited){ & taskkill.exe /PID $p.Id /T /F | Out-Null }
  } catch {}
  Start-Sleep -Milliseconds 300
}
$buttonNames=@()
if($ButtonTexts){ $buttonNames=@($ButtonTexts.Split(';')) }
if($buttonNames.Count -gt 0 -and $buttonNames.Count -ne 4){ throw "ButtonTexts must contain exactly four names" }
$results=@()
$backendResults=@()
$backendRoot=$null
if($BackendEvidencePath){
  $backendParent=Split-Path -Parent $BackendEvidencePath
  if($backendParent){
    New-Item -ItemType Directory -Force $backendParent | Out-Null
    $backendBase=(Resolve-Path $backendParent).Path
  } else {
    $backendBase=(Resolve-Path ".").Path
  }
  $backendRoot=Join-Path $backendBase ("physical-gui-backend-runs-"+[Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Force $backendRoot | Out-Null
}
$exeResolved = Resolve-Path $ExePath
$processName = [System.IO.Path]::GetFileNameWithoutExtension($exeResolved)
for($i=0;$i -lt 4;$i++){
  $baselinePids = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
  $window=$null
  $operationId=1001+$i
  $operationEvidence=$null
  if($backendRoot){
    $runDir=Join-Path $backendRoot ("op-"+$operationId)
    New-Item -ItemType Directory -Force $runDir | Out-Null
    $env:GLP_GUI_ACCEPTANCE_DIR=$runDir
    $env:GLP_DATA_DIR=Join-Path $runDir "data"
    New-Item -ItemType Directory -Force $env:GLP_DATA_DIR | Out-Null
    $operationEvidence=Join-Path $runDir ("operation-"+$operationId+".json")
  } else {
    Remove-Item Env:GLP_GUI_ACCEPTANCE_DIR -ErrorAction SilentlyContinue
  Remove-Item Env:GLP_DATA_DIR -ErrorAction SilentlyContinue
  }
  $p=Start-Process -FilePath $exeResolved -PassThru
  try {
    $window=Wait-MainWindow $p $processName $baselinePids
    $hwnd=$window.hwnd
    if($i -eq 0 -and $PreconditionIndex -ge 0){
      if($buttonNames.Count -eq 4){
        $prePoint=Find-ButtonPoint $hwnd $buttonNames[$PreconditionIndex]
        [void](Click-ScreenPoint $hwnd $prePoint.x $prePoint.y)
      } else {
        $pre=$parsed[$PreconditionIndex]
        [void](Click-Normalized $hwnd $pre[0] $pre[1])
      }
      Start-Sleep -Milliseconds $SettleMs
      if(-not [PhysicalGuiClick]::IsWindow($hwnd)){ throw "GUI window disappeared during precondition click" }
    }
    $before=Get-WindowHash $hwnd
    if($buttonNames.Count -eq 4){
      try {
        $point=Find-ButtonPoint $hwnd $buttonNames[$i]
        $click=Click-ScreenPoint $hwnd $point.x $point.y
        $locator=$point.locator
      } catch {
        # Native Win32 controls may not expose accessible text on hosted runners.
        # Enumerate the real visible BUTTON child HWNDs and use their actual screen
        # rectangles before falling back to the frozen layout coordinates.
        [int]$bx=0
        [int]$by=0
        if([PhysicalGuiClick]::FindNthVisibleButtonCenter($hwnd,$i,[ref]$bx,[ref]$by)){
          $click=Click-ScreenPoint $hwnd $bx $by
          $locator="Win32ButtonIndex"
        } else {
          $pt=$parsed[$i]
          $click=Click-Normalized $hwnd $pt[0] $pt[1]
          $locator="FrozenNormalizedCoordinate"
        }
      }
    } else {
      $pt=$parsed[$i]
      $click=Click-Normalized $hwnd $pt[0] $pt[1]
      $locator="FrozenNormalizedCoordinate"
    }
    if($backendRoot){
      $deadline=(Get-Date).AddSeconds($BackendTimeoutSeconds)
      while((Get-Date) -lt $deadline -and -not (Test-Path $operationEvidence)){
        Start-Sleep -Milliseconds 500
      }
      if(-not (Test-Path $operationEvidence)){
        throw "Physical click did not produce backend evidence for operation $operationId within timeout"
      }
      $backend=Get-Content $operationEvidence -Raw | ConvertFrom-Json
      if($backend.schema -ne 'dlt-physical-gui-backend-v1' -or $backend.status -ne 'PASS' -or [int]$backend.operation_id -ne $operationId){
        throw "Backend evidence is not a bound PASS for operation $operationId"
      }
      switch($operationId){
        1001 {
          if([string]::IsNullOrWhiteSpace([string]$backend.result.prediction.freeze_hash)){ throw 'Predict backend did not persist a formal Freeze' }
          if([string]::IsNullOrWhiteSpace([string]$backend.result.prediction.target_issue)){ throw 'Predict backend target issue missing' }
        }
        1002 {
          if($backend.result.network_gate -ne 'PASS' -or $backend.result.crosscheck_status -ne 'PASS'){ throw 'Update backend did not prove real official network/crosscheck PASS' }
          if($backend.result._updater.parent_pid_match -ne $true -or [string]::IsNullOrWhiteSpace([string]$backend.result._updater.updater_exe_sha256)){
            throw 'Update GUI path did not prove independent exact Updater process'
          }
        }
        1003 {
          if($backend.result.after.status -ne 'PASS'){ throw 'Repair backend integrity is not PASS' }
          if($backend.result._updater.parent_pid_match -ne $true -or [string]::IsNullOrWhiteSpace([string]$backend.result._updater.updater_exe_sha256)){
            throw 'Repair GUI path did not prove independent exact Updater process'
          }
        }
        1004 {
          if($backend.result.court.software_verdict -ne 'PASS' -or $backend.result.formal_freeze_written -ne $false -or [int]$backend.result.freeze_before -ne [int]$backend.result.freeze_after){
            throw 'Audit backend did not prove scientific PASS with zero formal Freeze side effect'
          }
        }
      }
      $backendResults += [pscustomobject]@{
        operation_id=$operationId
        operation=$backend.operation
        status='PASS'
        evidence_path=$operationEvidence
      }
    }
    Start-Sleep -Milliseconds $SettleMs
    if(-not [PhysicalGuiClick]::IsWindow($hwnd)){
      # PyInstaller one-file may hand the visible window from the bootstrap process
      # to the extracted child.  A stale HWND alone is not proof of an application
      # crash. Re-resolve a visible main window belonging to this launch only.
      $rebound = Wait-MainWindow $p $processName $baselinePids
      $hwnd = $rebound.hwnd
      $window = $rebound
      if(-not [PhysicalGuiClick]::IsWindow($hwnd)){
        throw "No live GUI window after core button $($i+1)"
      }
    }
    $after=Get-WindowHash $hwnd
    $changed=($before -ne $after)
    if(-not $changed){ throw "Core button $($i+1) produced no visible GUI change; click not proven" }
    $results += [pscustomobject]@{button_index=$i+1;button_name=$(if($buttonNames.Count -eq 4){$buttonNames[$i]}else{""});status="PASS";locator=$locator;x=$click.x;y=$click.y;visual_changed=$true;before_sha256=$before;after_sha256=$after}
  } finally { Stop-Tree $p $(if($window){[int]$window.pid}else{0}) }
}
$dir=Split-Path -Parent $EvidencePath
if($dir){ New-Item -ItemType Directory -Force $dir | Out-Null }
$report=[ordered]@{
  schema="physical-gui-click-smoke-v1"
  status="PASS"
  exe=(Split-Path -Leaf $ExePath)
  tested_at=(Get-Date).ToUniversalTime().ToString("o")
  activation="foreground cursor + mouse_event LEFTDOWN/LEFTUP"
  buttons=$results
}
$report | ConvertTo-Json -Depth 6 | Set-Content $EvidencePath -Encoding utf8
Get-Content $EvidencePath
if($BackendEvidencePath){
  Remove-Item Env:GLP_GUI_ACCEPTANCE_DIR -ErrorAction SilentlyContinue
  $backendReport=[ordered]@{
    schema='dlt-physical-gui-backend-summary-v1'
    status=$(if($backendResults.Count -eq 4 -and @($backendResults | Where-Object {$_.status -ne 'PASS'}).Count -eq 0){'PASS'}else{'FAIL'})
    exe=(Split-Path -Leaf $ExePath)
    exe_sha256=(Get-FileHash $exeResolved -Algorithm SHA256).Hash.ToLower()
    tested_at=(Get-Date).ToUniversalTime().ToString('o')
    physical_activation='foreground cursor + mouse_event LEFTDOWN/LEFTUP'
    operations=$backendResults
  }
  $backendReport | ConvertTo-Json -Depth 8 | Set-Content $BackendEvidencePath -Encoding utf8
  Get-Content $BackendEvidencePath
  if($backendReport.status -ne 'PASS'){ throw 'Physical GUI backend acceptance is not PASS' }
}
