param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [int]$TimeoutSeconds = 1200
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
public static class Happy8PhysicalGui {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr hWndParent, EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT point);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder text, int maxCount);

  public static bool FindVisibleWindow(int[] pids, out IntPtr hwnd, out int pid) {
    var wanted = new HashSet<int>(pids ?? new int[0]);
    IntPtr found = IntPtr.Zero; int foundPid = 0;
    EnumWindows(delegate(IntPtr h, IntPtr lp) {
      if (!IsWindowVisible(h)) return true;
      uint p=0; GetWindowThreadProcessId(h, out p);
      if (!wanted.Contains((int)p)) return true;
      RECT r; if (!GetWindowRect(h, out r) || r.Right <= r.Left || r.Bottom <= r.Top) return true;
      found=h; foundPid=(int)p; return false;
    }, IntPtr.Zero);
    hwnd=found; pid=foundPid; return found != IntPtr.Zero;
  }

  public static bool FindChildButtonCenter(IntPtr parent, string name, out int x, out int y) {
    int fx=0, fy=0; bool found=false;
    EnumChildWindows(parent, delegate(IntPtr child, IntPtr lp) {
      if (!IsWindowVisible(child)) return true;
      var cls=new StringBuilder(128); var txt=new StringBuilder(512);
      GetClassNameW(child, cls, cls.Capacity); GetWindowTextW(child, txt, txt.Capacity);
      if (string.Equals(txt.ToString(), name, StringComparison.Ordinal)) {
        RECT r; if (GetWindowRect(child, out r) && r.Right>r.Left && r.Bottom>r.Top) {
          fx=r.Left+(r.Right-r.Left)/2; fy=r.Top+(r.Bottom-r.Top)/2; found=true; return false;
        }
      }
      return true;
    }, IntPtr.Zero);
    x=fx; y=fy; return found;
  }
}
"@

$DOWN=0x0002
$UP=0x0004

function Stop-Tree([System.Diagnostics.Process]$p,[int]$guiPid=0) {
  if($guiPid -gt 0 -and $guiPid -ne $p.Id) { Stop-Process -Id $guiPid -Force -ErrorAction SilentlyContinue }
  try { if(-not $p.HasExited) { & taskkill.exe /PID $p.Id /T /F | Out-Null } } catch {}
  Start-Sleep -Milliseconds 300
}

function Wait-Window([System.Diagnostics.Process]$p,[string]$processName,[int[]]$baseline) {
  for($i=0;$i -lt 160;$i++) {
    Start-Sleep -Milliseconds 250
    $candidates=@(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object { $baseline -notcontains $_.Id })
    [IntPtr]$hwnd=[IntPtr]::Zero; [int]$pid=0
    [int[]]$ids=@($candidates | ForEach-Object { [int]$_.Id })
    if($ids.Count -gt 0 -and [Happy8PhysicalGui]::FindVisibleWindow($ids,[ref]$hwnd,[ref]$pid)) {
      return @{ hwnd=$hwnd; pid=$pid }
    }
    try {
      $p.Refresh()
      if(-not $p.HasExited -and $p.MainWindowHandle -ne 0) { return @{ hwnd=[IntPtr]$p.MainWindowHandle; pid=$p.Id } }
    } catch {}
  }
  throw "Happy8 main window not found"
}

function Find-Point([IntPtr]$hwnd,[string]$label,[double]$rx,[double]$ry) {
  try {
    $root=[System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
    $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
    foreach($el in $all) {
      try {
        if($el.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and $el.Current.Name -eq $label) {
          $r=$el.Current.BoundingRectangle
          if($r.Width -gt 2 -and $r.Height -gt 2) { return @{x=[int]($r.Left+$r.Width/2); y=[int]($r.Top+$r.Height/2); locator="UIAutomation"} }
        }
      } catch {}
    }
  } catch {}
  [int]$x=0; [int]$y=0
  if([Happy8PhysicalGui]::FindChildButtonCenter($hwnd,$label,[ref]$x,[ref]$y)) { return @{x=$x;y=$y;locator="Win32ChildHWND"} }
  $client=New-Object Happy8PhysicalGui+RECT
  if(-not [Happy8PhysicalGui]::GetClientRect($hwnd,[ref]$client)) { throw "GetClientRect failed" }
  $origin=New-Object Happy8PhysicalGui+POINT; $origin.X=0; $origin.Y=0
  if(-not [Happy8PhysicalGui]::ClientToScreen($hwnd,[ref]$origin)) { throw "ClientToScreen failed" }
  return @{
    x=[int]($origin.X+($client.Right-$client.Left)*$rx)
    y=[int]($origin.Y+($client.Bottom-$client.Top)*$ry)
    locator="FrozenNormalizedCoordinate"
  }
}

function Click-Point([IntPtr]$hwnd,[int]$x,[int]$y) {
  [void][Happy8PhysicalGui]::SetForegroundWindow($hwnd)
  Start-Sleep -Milliseconds 200
  if(-not [Happy8PhysicalGui]::SetCursorPos($x,$y)) { throw "SetCursorPos failed" }
  [Happy8PhysicalGui]::mouse_event($DOWN,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 80
  [Happy8PhysicalGui]::mouse_event($UP,0,0,0,[UIntPtr]::Zero)
}

function Screen-Hash() {
  $bounds=[System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp=New-Object System.Drawing.Bitmap $bounds.Width,$bounds.Height
  $g=[System.Drawing.Graphics]::FromImage($bmp)
  try { $g.CopyFromScreen($bounds.Left,$bounds.Top,0,0,$bmp.Size) } finally { $g.Dispose() }
  $tmp=[System.IO.Path]::GetTempFileName()+".png"
  try {
    $bmp.Save($tmp,[System.Drawing.Imaging.ImageFormat]::Png)
    return (Get-FileHash $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
  } finally {
    $bmp.Dispose(); Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Wait-Audit([string]$path,[string]$label,[int]$seconds) {
  $deadline=(Get-Date).AddSeconds($seconds)
  while((Get-Date) -lt $deadline) {
    if(Test-Path $path) {
      $lines=@(Get-Content $path -Encoding UTF8 -ErrorAction SilentlyContinue)
      foreach($line in ($lines | Select-Object -Last 20)) {
        try {
          $obj=$line | ConvertFrom-Json
          if($obj.label -eq $label) { return $obj }
        } catch {}
      }
    }
    Start-Sleep -Milliseconds 500
  }
  throw "GUI audit record not produced for $label"
}

$exe=(Resolve-Path $ExePath).Path
$initialHash=(Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
$processName=[System.IO.Path]::GetFileNameWithoutExtension($exe)
$evidenceFull=[System.IO.Path]::GetFullPath($EvidencePath)
$evidenceDir=Split-Path -Parent $evidenceFull
New-Item -ItemType Directory -Force $evidenceDir | Out-Null
$root=Join-Path $evidenceDir ("physical-gui-"+[Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $root | Out-Null
$localAppData=Join-Path $root "LocalAppData"
$dataRoot=Join-Path $localAppData "GeometryLottoPro/Happy8"
New-Item -ItemType Directory -Force $dataRoot | Out-Null

# Seed the isolated GUI store through the exact packaged EXE and the real official
# network path. This is a precondition only; the four acceptance operations below
# are all activated by physical foreground mouse events.
$seedResult=Join-Path $root "seed-live-update.json"
$seed=Start-Process -FilePath $exe -ArgumentList @('--update','--data-root',$dataRoot,'--result-file',$seedResult) -Wait -PassThru
if($seed.ExitCode -ne 0) { throw "exact EXE live-network seed failed: $($seed.ExitCode)" }
$seedJson=Get-Content $seedResult -Raw -Encoding UTF8 | ConvertFrom-Json
if($seedJson.status -ne 'PASS') { throw "exact EXE live-network seed was not PASS" }

$ops=@(
  @{key='predict'; label='预测下一期'; rx=0.14; expected='PASS'},
  @{key='update'; label='一键更新'; rx=0.38; expected='FAIL_CLOSED'},
  @{key='repair'; label='一键修复'; rx=0.62; expected='BLOCKED_EXTERNAL'},
  @{key='advanced'; label='高级分析'; rx=0.86; expected='PASS'}
)
$results=@()

foreach($op in $ops) {
  if($op.key -eq 'repair') {
    $current=Join-Path $dataRoot 'store/CURRENT.json'
    Set-Content -Path $current -Value '{corrupt' -Encoding UTF8
  }

  $audit=Join-Path $root ("audit-"+$op.key+".jsonl")
  Remove-Item $audit -Force -ErrorAction SilentlyContinue
  $env:LOCALAPPDATA=$localAppData
  $env:HAPPY8_GUI_AUDIT_FILE=$audit
  $baseline=@(Get-Process -Name $processName -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
  $p=Start-Process -FilePath $exe -PassThru
  $window=$null
  try {
    $window=Wait-Window $p $processName $baseline
    $before=Screen-Hash
    $point=Find-Point $window.hwnd $op.label $op.rx 0.155
    Click-Point $window.hwnd $point.x $point.y
    $record=Wait-Audit $audit $op.label $TimeoutSeconds
    Start-Sleep -Milliseconds 400
    $after=Screen-Hash
    if($before -eq $after) { throw "physical click produced no visible desktop change for $($op.label)" }

    if($op.expected -eq 'PASS') {
      if($record.status -ne 'PASS') { throw "$($op.label) backend status was $($record.status), expected PASS" }
      if($op.key -eq 'predict' -and [string]::IsNullOrWhiteSpace([string]$record.result.freeze_hash)) { throw "prediction freeze hash missing" }
      if($op.key -eq 'repair' -and $record.result.action -ne 'RESTORED_VERIFIED_GENERATION') { throw "repair did not restore the corrupted CURRENT pointer" }
      if($op.key -eq 'advanced' -and $record.result.report.software_verdict -ne 'PASS') { throw "advanced analysis software verdict not PASS" }
    } elseif($op.expected -eq 'FAIL_CLOSED') {
      if($record.status -ne 'FAIL') { throw "one-click update must fail closed without a real independent release config" }
      $err=[string]$record.result.error
      if($err -notmatch 'release config is unavailable|independent repository/release source remains BLOCKED') {
        throw "one-click update failed for an unexpected reason: $err"
      }
    } else {
      if($record.status -ne 'BLOCKED') { throw "one-click repair must surface the missing trusted release/network configuration as BLOCKED" }
      if($record.result.action -ne 'LOCAL_REPAIR_COMPLETE_EXTERNAL_BLOCKER') { throw "repair blocker action mismatch" }
      if($record.result.components.data_integrity.status -ne 'PASS') { throw "repair local data integrity did not recover" }
      if($record.result.components.index.status -ne 'PASS') { throw "repair CURRENT/index pointer did not recover" }
      if($record.result.components.configuration.status -ne 'BLOCKED') { throw "repair release config blocker was hidden" }
      if($record.result.components.network_configuration.status -ne 'BLOCKED') { throw "repair network config blocker was hidden" }
      if($record.result.post_repair_self_check.status -ne 'PASS') { throw "repair post self-check did not pass" }
    }

    $results += [pscustomobject]@{
      key=$op.key
      label=$op.label
      acceptance=$(if($op.expected -eq 'FAIL_CLOSED'){'PASS_FAIL_CLOSED'}elseif($op.expected -eq 'BLOCKED_EXTERNAL'){'PASS_BLOCKED_EXPLICIT'}else{'PASS'})
      backend_status=$record.status
      locator=$point.locator
      x=$point.x
      y=$point.y
      visual_changed=$true
      before_screen_sha256=$before
      after_screen_sha256=$after
    }
  } finally {
    if($null -ne $p) { Stop-Tree $p $(if($window){[int]$window.pid}else{0}) }
  }
}

Remove-Item Env:HAPPY8_GUI_AUDIT_FILE -ErrorAction SilentlyContinue
$finalHash=(Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
if($initialHash -ne $finalHash) { throw "Exact EXE changed during physical GUI acceptance" }

# Verify Repair left the shared isolated store valid through the same exact EXE.
$statusFile=Join-Path $root "post-gui-status.json"
$statusProc=Start-Process -FilePath $exe -ArgumentList @('--status','--data-root',$dataRoot,'--result-file',$statusFile) -Wait -PassThru
if($statusProc.ExitCode -ne 0) { throw "post-GUI exact EXE status check failed" }
$post=Get-Content $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json
if($post.status -ne 'PASS') { throw "post-GUI store integrity is not PASS" }

$report=[ordered]@{
  schema='happy8-physical-gui-v1'
  status='PASS'
  exact_exe=$exe
  exe_sha256_before=$initialHash
  exe_sha256_after=$finalHash
  same_hash=$true
  activation='foreground SetCursorPos + mouse_event LEFTDOWN/LEFTUP'
  live_network_seed_status='PASS'
  operations=$results
  post_gui_store_status='PASS'
  updater_real_release='BLOCKED'
  final_gate='FAIL'
  tested_at=(Get-Date).ToUniversalTime().ToString('o')
}
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $evidenceFull -Encoding UTF8
Get-Content $evidenceFull -Raw
