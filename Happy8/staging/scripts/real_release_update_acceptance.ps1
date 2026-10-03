param(
  [Parameter(Mandatory=$true)][string]$ReleaseNExePath,
  [Parameter(Mandatory=$true)][string]$ReleaseN1UpdaterPath,
  [Parameter(Mandatory=$true)][string]$EvidencePath,
  [Parameter(Mandatory=$true)][string]$Repository,
  [Parameter(Mandatory=$true)][string]$SourceSha,
  [Parameter(Mandatory=$true)][string]$ReleaseNSourceSha,
  [Parameter(Mandatory=$true)][string]$ReleaseNId,
  [Parameter(Mandatory=$true)][string]$ReleaseN1Id,
  [Parameter(Mandatory=$true)][string]$ReleaseNUrl,
  [Parameter(Mandatory=$true)][string]$ReleaseN1Url,
  [Parameter(Mandatory=$true)][string]$ExpectedFromVersion,
  [Parameter(Mandatory=$true)][string]$ExpectedToVersion,
  [Parameter(Mandatory=$true)][string]$GithubRunId,
  [Parameter(Mandatory=$true)][string]$GithubRunAttempt,
  [int]$TimeoutSeconds = 180
)

$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class Happy8ReleaseGui {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr hWndParent, EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT point);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder text, int maxCount);

  public static bool FindVisibleWindow(int[] pids, out IntPtr hwnd, out int pid) {
    var wanted=new HashSet<int>(pids ?? new int[0]);
    IntPtr found=IntPtr.Zero; int foundPid=0;
    EnumWindows(delegate(IntPtr h, IntPtr lp) {
      if(!IsWindowVisible(h)) return true;
      uint p=0; GetWindowThreadProcessId(h,out p);
      if(!wanted.Contains((int)p)) return true;
      RECT r; if(!GetWindowRect(h,out r) || r.Right<=r.Left || r.Bottom<=r.Top) return true;
      found=h; foundPid=(int)p; return false;
    },IntPtr.Zero);
    hwnd=found; pid=foundPid; return found!=IntPtr.Zero;
  }

  public static bool FindChildButtonCenter(IntPtr parent,string name,out int x,out int y) {
    int fx=0,fy=0; bool found=false;
    EnumChildWindows(parent,delegate(IntPtr child,IntPtr lp) {
      if(!IsWindowVisible(child)) return true;
      var txt=new StringBuilder(512); GetWindowTextW(child,txt,txt.Capacity);
      if(string.Equals(txt.ToString(),name,StringComparison.Ordinal)) {
        RECT r; if(GetWindowRect(child,out r) && r.Right>r.Left && r.Bottom>r.Top) {
          fx=r.Left+(r.Right-r.Left)/2; fy=r.Top+(r.Bottom-r.Top)/2; found=true; return false;
        }
      }
      return true;
    },IntPtr.Zero);
    x=fx; y=fy; return found;
  }
}
"@

$DOWN=0x0002
$UP=0x0004

function Get-Sha256([string]$path) {
  return (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-NumericVersion([string]$value) {
  $parts=@($value.Split('.'))
  if($parts.Count -eq 0 -or @($parts | Where-Object { $_ -notmatch '^\d+$' }).Count -gt 0) {
    throw "invalid numeric version: $value"
  }
  return @($parts | ForEach-Object { [int]$_ })
}

function Compare-NumericVersion([string]$left,[string]$right) {
  $a=Assert-NumericVersion $left
  $b=Assert-NumericVersion $right
  $n=[Math]::Max($a.Count,$b.Count)
  for($i=0;$i -lt $n;$i++) {
    $av=$(if($i -lt $a.Count){$a[$i]}else{0})
    $bv=$(if($i -lt $b.Count){$b[$i]}else{0})
    if($av -lt $bv){ return -1 }
    if($av -gt $bv){ return 1 }
  }
  return 0
}

function Assert-Https([string]$url) {
  $uri=[Uri]$url
  if($uri.Scheme -ne 'https' -or [string]::IsNullOrWhiteSpace($uri.Host)) {
    throw "URL is not HTTPS: $url"
  }
}

function Assert-HttpsTrusted([string]$url,[string[]]$trustedHosts) {
  Assert-Https $url
  $uri=[Uri]$url
  $host=$uri.Host.ToLowerInvariant()
  if(@($trustedHosts | ForEach-Object {$_.ToLowerInvariant()}) -notcontains $host) {
    throw "URL host is not trusted: $host"
  }
}

function Wait-Window([System.Diagnostics.Process]$p,[string]$processName,[int[]]$baseline) {
  for($i=0;$i -lt 160;$i++) {
    Start-Sleep -Milliseconds 250
    $candidates=@(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object { $baseline -notcontains $_.Id })
    [IntPtr]$hwnd=[IntPtr]::Zero; [int]$pid=0
    [int[]]$ids=@($candidates | ForEach-Object {[int]$_.Id})
    if($ids.Count -gt 0 -and [Happy8ReleaseGui]::FindVisibleWindow($ids,[ref]$hwnd,[ref]$pid)) {
      return @{hwnd=$hwnd;pid=$pid}
    }
    try {
      $p.Refresh()
      if(-not $p.HasExited -and $p.MainWindowHandle -ne 0) {
        return @{hwnd=[IntPtr]$p.MainWindowHandle;pid=$p.Id}
      }
    } catch {}
  }
  throw 'Happy8 Release N main window not found'
}

function Find-UpdatePoint([IntPtr]$hwnd) {
  try {
    $root=[System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
    $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
    foreach($el in $all) {
      try {
        if($el.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and $el.Current.Name -eq '一键更新') {
          $r=$el.Current.BoundingRectangle
          if($r.Width -gt 2 -and $r.Height -gt 2) {
            return @{x=[int]($r.Left+$r.Width/2);y=[int]($r.Top+$r.Height/2);locator='UIAutomation'}
          }
        }
      } catch {}
    }
  } catch {}
  [int]$x=0;[int]$y=0
  if([Happy8ReleaseGui]::FindChildButtonCenter($hwnd,'一键更新',[ref]$x,[ref]$y)) {
    return @{x=$x;y=$y;locator='Win32ChildHWND'}
  }
  $client=New-Object Happy8ReleaseGui+RECT
  if(-not [Happy8ReleaseGui]::GetClientRect($hwnd,[ref]$client)) { throw 'GetClientRect failed' }
  $origin=New-Object Happy8ReleaseGui+POINT;$origin.X=0;$origin.Y=0
  if(-not [Happy8ReleaseGui]::ClientToScreen($hwnd,[ref]$origin)) { throw 'ClientToScreen failed' }
  return @{
    x=[int]($origin.X+($client.Right-$client.Left)*0.38)
    y=[int]($origin.Y+($client.Bottom-$client.Top)*0.155)
    locator='FrozenNormalizedCoordinate'
  }
}

function Click-Point([IntPtr]$hwnd,[int]$x,[int]$y) {
  [void][Happy8ReleaseGui]::SetForegroundWindow($hwnd)
  Start-Sleep -Milliseconds 200
  if(-not [Happy8ReleaseGui]::SetCursorPos($x,$y)) { throw 'SetCursorPos failed' }
  [Happy8ReleaseGui]::mouse_event($DOWN,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 80
  [Happy8ReleaseGui]::mouse_event($UP,0,0,0,[UIntPtr]::Zero)
}

function Screen-Hash() {
  $bounds=[System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp=New-Object System.Drawing.Bitmap $bounds.Width,$bounds.Height
  $g=[System.Drawing.Graphics]::FromImage($bmp)
  try {$g.CopyFromScreen($bounds.Left,$bounds.Top,0,0,$bmp.Size)} finally {$g.Dispose()}
  $tmp=[System.IO.Path]::GetTempFileName()+'.png'
  try {
    $bmp.Save($tmp,[System.Drawing.Imaging.ImageFormat]::Png)
    return Get-Sha256 $tmp
  } finally {
    $bmp.Dispose();Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Wait-Audit([string]$path,[int]$seconds) {
  $deadline=(Get-Date).AddSeconds($seconds)
  while((Get-Date) -lt $deadline) {
    if(Test-Path $path) {
      foreach($line in (@(Get-Content $path -Encoding UTF8 -ErrorAction SilentlyContinue) | Select-Object -Last 20)) {
        try {
          $obj=$line|ConvertFrom-Json
          if($obj.label -eq '一键更新') { return $obj }
        } catch {}
      }
    }
    Start-Sleep -Milliseconds 250
  }
  throw 'GUI audit record not produced for 一键更新'
}

function Wait-Json([string]$path,[int]$seconds) {
  $deadline=(Get-Date).AddSeconds($seconds)
  while((Get-Date) -lt $deadline) {
    if(Test-Path $path) {
      try {
        $obj=Get-Content $path -Raw -Encoding UTF8|ConvertFrom-Json
        if($null -ne $obj -and -not [string]::IsNullOrWhiteSpace([string]$obj.status)){return $obj}
      } catch {}
    }
    Start-Sleep -Milliseconds 250
  }
  throw "timed out waiting for JSON evidence: $path"
}

$evidenceFull=[System.IO.Path]::GetFullPath($EvidencePath)
New-Item -ItemType Directory -Force (Split-Path -Parent $evidenceFull) | Out-Null
$testedAt=(Get-Date).ToUniversalTime().ToString('o')

try {
  if((Compare-NumericVersion $ExpectedToVersion $ExpectedFromVersion) -le 0) {
    throw "ExpectedToVersion must be newer than ExpectedFromVersion"
  }
  if([string]::IsNullOrWhiteSpace($ReleaseNId) -or [string]::IsNullOrWhiteSpace($ReleaseN1Id) -or $ReleaseNId -eq $ReleaseN1Id) {
    throw "Release N and N+1 must have distinct real release identities"
  }
  if($SourceSha -notmatch '^[0-9a-fA-F]{40}$' -or $ReleaseNSourceSha -notmatch '^[0-9a-fA-F]{40}$') {
    throw 'release source SHA must be a 40-hex commit'
  }

  $exe=(Resolve-Path $ReleaseNExePath).Path
  $releaseDir=Split-Path -Parent $exe
  $updaterN=(Resolve-Path (Join-Path $releaseDir 'Geometry_Lotto_Pro_Happy8_Updater.exe')).Path
  $updaterN1=(Resolve-Path $ReleaseN1UpdaterPath).Path
  $configPath=(Resolve-Path (Join-Path $releaseDir 'Happy8_Update_Config.json')).Path
  $config=Get-Content $configPath -Raw -Encoding UTF8|ConvertFrom-Json
  if($config.schema -ne 'happy8-update-config-v1') { throw 'Release N update config schema mismatch' }
  [string[]]$trustedHosts=@($config.trusted_hosts | ForEach-Object {[string]$_})
  if($trustedHosts.Count -eq 0) { throw 'Release N trusted_hosts is empty' }
  Assert-HttpsTrusted ([string]$config.manifest_url) $trustedHosts
  Assert-Https $ReleaseNUrl
  Assert-Https $ReleaseN1Url

  $manifestResponse=Invoke-WebRequest -Uri ([string]$config.manifest_url) -UseBasicParsing -Headers @{Accept='application/json'} -TimeoutSec 60
  if([int]$manifestResponse.StatusCode -ne 200) { throw "manifest HTTP $($manifestResponse.StatusCode)" }
  $manifest=$manifestResponse.Content|ConvertFrom-Json
  if($manifest.schema -ne 'happy8-update-manifest-v1') { throw 'manifest schema mismatch' }
  if([string]$manifest.version -ne $ExpectedToVersion) { throw "manifest version mismatch: $($manifest.version)" }
  Assert-HttpsTrusted ([string]$manifest.artifact_url) $trustedHosts
  $manifestSha=([string]$manifest.artifact_sha256).ToLowerInvariant()
  if($manifestSha -notmatch '^[0-9a-f]{64}$') { throw 'manifest artifact SHA-256 invalid' }
  [long]$manifestBytes=$manifest.artifact_bytes
  if($manifestBytes -le 0 -or $manifestBytes -gt 536870912) { throw 'manifest artifact byte count invalid' }

  $oldMainSha=Get-Sha256 $exe
  $oldUpdaterSha=Get-Sha256 $updaterN
  $newUpdaterSha=Get-Sha256 $updaterN1

  $scratch=Join-Path ([System.IO.Path]::GetTempPath()) ('happy8-real-release-'+[Guid]::NewGuid().ToString('N'))
  $localAppData=Join-Path $scratch 'LocalAppData'
  New-Item -ItemType Directory -Force $localAppData | Out-Null
  $audit=Join-Path $scratch 'update-audit.jsonl'
  $env:LOCALAPPDATA=$localAppData
  $env:HAPPY8_GUI_AUDIT_FILE=$audit

  $processName=[System.IO.Path]::GetFileNameWithoutExtension($exe)
  $baseline=@(Get-Process -Name $processName -ErrorAction SilentlyContinue|ForEach-Object{$_.Id})
  $p=Start-Process -FilePath $exe -PassThru
  $window=Wait-Window $p $processName $baseline
  $beforeScreen=Screen-Hash
  $point=Find-UpdatePoint $window.hwnd
  Click-Point $window.hwnd $point.x $point.y
  $auditRecord=Wait-Audit $audit $TimeoutSeconds
  Start-Sleep -Milliseconds 400
  $afterScreen=Screen-Hash
  if($beforeScreen -eq $afterScreen) { throw 'physical one-click update produced no visible desktop change' }
  if($auditRecord.status -ne 'PASS' -or $auditRecord.result.action -ne 'UPDATER_HANDOFF') {
    throw 'physical one-click update did not hand off to independent Updater'
  }
  if($auditRecord.result.requires_parent_exit -ne $true) { throw 'Updater handoff did not require parent exit' }
  $updaterEvidence=[string]$auditRecord.result.evidence_file
  if([string]::IsNullOrWhiteSpace($updaterEvidence)) { throw 'Updater evidence path missing from GUI handoff' }

  try {$p.WaitForExit(10000)|Out-Null} catch {}
  $updaterResult=Wait-Json $updaterEvidence $TimeoutSeconds
  if($updaterResult.status -ne 'PASS' -or $updaterResult.operation -ne 'software_update' -or $updaterResult.action -ne 'UPDATED') {
    throw "real N→N+1 update did not complete as UPDATED"
  }
  if([string]$updaterResult.from_version -ne $ExpectedFromVersion -or [string]$updaterResult.to_version -ne $ExpectedToVersion) {
    throw 'Updater result version transition mismatch'
  }

  $newMainSha=Get-Sha256 $exe
  if($newMainSha -ne $manifestSha) { throw 'updated main EXE hash does not match manifest' }
  if(([string]$updaterResult.old_exe_sha256).ToLowerInvariant() -ne $oldMainSha) { throw 'Updater old EXE hash mismatch' }
  if(([string]$updaterResult.new_exe_sha256).ToLowerInvariant() -ne $newMainSha) { throw 'Updater new EXE hash mismatch' }
  if([long]$updaterResult.artifact_receipt.bytes -ne $manifestBytes) { throw 'Updater artifact byte receipt mismatch' }
  if(([string]$updaterResult.artifact_receipt.sha256).ToLowerInvariant() -ne $newMainSha) { throw 'Updater artifact receipt hash mismatch' }

  $selfTestPath=Join-Path $scratch 'post-update-self-test.json'
  $self=Start-Process -FilePath $exe -ArgumentList @('--self-test','--result-file',$selfTestPath) -Wait -PassThru
  if($self.ExitCode -ne 0) { throw "updated N+1 self-test exit code $($self.ExitCode)" }
  $selfJson=Get-Content $selfTestPath -Raw -Encoding UTF8|ConvertFrom-Json
  if($selfJson.status -ne 'PASS') { throw 'updated N+1 self-test status is not PASS' }

  $report=[ordered]@{
    schema='happy8-real-release-update-v1'
    status='PASS'
    repository=$Repository
    execution_context=[ordered]@{
      producer='happy8-real-release-acceptance-v1'
      github_run_id=$GithubRunId
      github_run_attempt=$GithubRunAttempt
      head_sha=$SourceSha.ToLowerInvariant()
    }
    release_n=[ordered]@{
      release_id=$ReleaseNId
      version=$ExpectedFromVersion
      source_sha=$ReleaseNSourceSha.ToLowerInvariant()
      release_url=$ReleaseNUrl
      main_exe_sha256=$oldMainSha
      updater_exe_sha256=$oldUpdaterSha
    }
    release_n1=[ordered]@{
      release_id=$ReleaseN1Id
      version=$ExpectedToVersion
      source_sha=$SourceSha.ToLowerInvariant()
      release_url=$ReleaseN1Url
      main_exe_sha256=$newMainSha
      updater_exe_sha256=$newUpdaterSha
    }
    update_config=[ordered]@{
      schema='happy8-update-config-v1'
      manifest_url=[string]$config.manifest_url
      trusted_hosts=@($trustedHosts)
    }
    manifest=[ordered]@{
      schema='happy8-update-manifest-v1'
      version=[string]$manifest.version
      artifact_url=[string]$manifest.artifact_url
      artifact_sha256=$manifestSha
      artifact_bytes=$manifestBytes
    }
    updater_result=$updaterResult
    updater_execution=[ordered]@{
      independent_process=$true
      updater_exe_sha256=$oldUpdaterSha
      main_exe_sha256_before=$oldMainSha
      updater_pid=$auditRecord.result.updater_pid
    }
    physical_update_click=[ordered]@{
      status='PASS'
      label='一键更新'
      locator=$point.locator
      x=$point.x
      y=$point.y
      visual_changed=$true
      before_screen_sha256=$beforeScreen
      after_screen_sha256=$afterScreen
      from_exe_sha256=$oldMainSha
      to_exe_sha256=$newMainSha
    }
    post_update_self_test=[ordered]@{
      status='PASS'
      exe_sha256=$newMainSha
      result=$selfJson
    }
    tested_at=$testedAt
  }
} catch {
  $report=[ordered]@{
    schema='happy8-real-release-update-v1'
    status='FAIL'
    repository=$Repository
    execution_context=[ordered]@{
      producer='happy8-real-release-acceptance-v1'
      github_run_id=$GithubRunId
      github_run_attempt=$GithubRunAttempt
      head_sha=$SourceSha.ToLowerInvariant()
    }
    error=($_.Exception.GetType().Name+': '+$_.Exception.Message)
    tested_at=$testedAt
  }
}

Remove-Item Env:HAPPY8_GUI_AUDIT_FILE -ErrorAction SilentlyContinue
$report|ConvertTo-Json -Depth 12|Set-Content -Path $evidenceFull -Encoding UTF8
Get-Content $evidenceFull -Raw
if($report.status -ne 'PASS'){exit 2}
