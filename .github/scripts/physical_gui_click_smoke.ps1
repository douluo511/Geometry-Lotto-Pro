param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$Points,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [string]$ButtonTexts = "",
  [int]$PreconditionIndex = -1,
  [int]$SettleMs = 900
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
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
      $_.MainWindowHandle -ne 0 -and $baselinePids -notcontains $_.Id
    })
    if($candidates.Count -gt 0){
      $gui = $candidates | Sort-Object StartTime -Descending | Select-Object -First 1
      return @{ hwnd=[IntPtr]$gui.MainWindowHandle; pid=$gui.Id }
    }
    if(-not $p.HasExited -and $p.MainWindowHandle -ne 0){
      return @{ hwnd=[IntPtr]$p.MainWindowHandle; pid=$p.Id }
    }
  }
  throw "Main window handle not found in bootloader or spawned GUI process"
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
          return @{x=[int]($r.Left+$r.Width/2);y=[int]($r.Top+$r.Height/2);name=$name}
        }
      }
    } catch {}
  }
  throw "Button not found in UI Automation tree: $name"
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
function Stop-Tree([System.Diagnostics.Process]$p){
  if(-not $p.HasExited){
    & taskkill.exe /PID $p.Id /T /F | Out-Null
    Start-Sleep -Milliseconds 300
  }
}
$buttonNames=@()
if($ButtonTexts){ $buttonNames=@($ButtonTexts.Split(';')) }
if($buttonNames.Count -gt 0 -and $buttonNames.Count -ne 4){ throw "ButtonTexts must contain exactly four names" }
$results=@()
$exeResolved = Resolve-Path $ExePath
$processName = [System.IO.Path]::GetFileNameWithoutExtension($exeResolved)
for($i=0;$i -lt 4;$i++){
  $baselinePids = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
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
      $p.Refresh()
      if($p.HasExited){ throw "EXE exited during precondition click" }
    }
    $before=Get-WindowHash $hwnd
    if($buttonNames.Count -eq 4){
      $point=Find-ButtonPoint $hwnd $buttonNames[$i]
      $click=Click-ScreenPoint $hwnd $point.x $point.y
    } else {
      $pt=$parsed[$i]
      $click=Click-Normalized $hwnd $pt[0] $pt[1]
    }
    Start-Sleep -Milliseconds $SettleMs
    $p.Refresh()
    if($p.HasExited){ throw "EXE exited after core button $($i+1)" }
    $after=Get-WindowHash $hwnd
    $changed=($before -ne $after)
    if(-not $changed){ throw "Core button $($i+1) produced no visible GUI change; click not proven" }
    $results += [pscustomobject]@{button_index=$i+1;status="PASS";x=$click.x;y=$click.y;visual_changed=$true;before_sha256=$before;after_sha256=$after}
  } finally { Stop-Tree $p }
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
