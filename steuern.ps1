# Lässt ORB Maus und Tastatur bedienen – NUR auf ausdrücklichen Wunsch von Larsen.
# Koordinaten sind die aus dem letzten Screenshot (bildschirm.ps1); sie werden automatisch umgerechnet.
#   ... steuern.ps1 klick 640 380          ... steuern.ps1 doppelklick 640 380     ... steuern.ps1 rechtsklick 640 380
#   ... steuern.ps1 tippen "Hallo Welt"     ... steuern.ps1 taste enter              ... steuern.ps1 taste ctrl+s
#   ... steuern.ps1 scrollen -5             ... steuern.ps1 bewegen 640 380
# SCHNELL – mehrere Schritte in EINEM Aufruf (spart je Schritt ~1–2 s Startzeit), am Ende optional neuer Screenshot:
#   ... steuern.ps1 folge "klick 640 380; tippen Hallo Welt; taste enter; warten 800; scrollen -3" -Bild
#   ... steuern.ps1 klick 640 380 -Bild      (-Bild: danach sofort bildschirm.ps1 – spart einen zweiten Aufruf)
# Tasten: enter, tab, esc, space, backspace, delete, up, down, left, right, home, end, pageup, pagedown, win, f1–f12,
#         Kombinationen mit ctrl+ / alt+ / shift+ (z. B. ctrl+c, alt+tab, ctrl+shift+t)
param([Parameter(Mandatory = $true)][string]$Aktion, [string]$A, [string]$B, [switch]$Bild)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$dll = "$env:LOCALAPPDATA\ORB\orbin_v1.dll"
$code = @'
using System; using System.Runtime.InteropServices;
public class OrbIn {
  [StructLayout(LayoutKind.Sequential)] public struct PT { public int X; public int Y; }
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr c);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out PT p);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(PT p);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint f);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, int d, IntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte s, uint f, IntPtr e);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}
'@
if (-not ('OrbIn' -as [type])) {
  try { if (Test-Path $dll) { Add-Type -Path $dll } else { Add-Type -TypeDefinition $code -OutputAssembly $dll; Add-Type -Path $dll } }
  catch { Add-Type -TypeDefinition $code }
}
# Echte Pixel verwenden (Bildschirm 150 % usw.) – zuerst Per-Monitor-V2, sonst klassisch
try { if (-not [OrbIn]::SetProcessDpiAwarenessContext([IntPtr](-4))) { [OrbIn]::SetProcessDPIAware() | Out-Null } } catch { [OrbIn]::SetProcessDPIAware() | Out-Null }
$sw = [OrbIn]::GetSystemMetrics(0); $sh = [OrbIn]::GetSystemMetrics(1)
# ORBs eigenes Fenster aus dem Weg (sonst landen Klicks auf ORB)
$orb = Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq 'ORB' } | Select-Object -First 1
if ($orb -and $Aktion -notin 'scrollen', 'warten') { [OrbIn]::ShowWindow($orb.MainWindowHandle, 6) | Out-Null; Start-Sleep -Milliseconds 150 }
# Maßstab Screenshot -> echte Pixel (Komma oder Punkt; unplausible Werte verwerfen)
$f = $sw / [Math]::Min(1600, $sw)
try {
  $roh = ((Get-Content "$env:LOCALAPPDATA\ORB\screen\massstab.txt" -ErrorAction Stop | Select-Object -First 1) -replace ',', '.').Trim()
  $g = [double]::Parse($roh, [System.Globalization.CultureInfo]::InvariantCulture)
  if ($g -ge 0.5 -and $g -le 4) { $f = $g }
} catch {}
# Fenster unter der Maus nach vorne holen, damit Klick und Tastatur dort ankommen
function Fokus {
  $p = New-Object OrbIn+PT; [OrbIn]::GetCursorPos([ref]$p) | Out-Null
  $w = [OrbIn]::GetAncestor([OrbIn]::WindowFromPoint($p), 2)
  if ($w -ne [IntPtr]::Zero -and $w -ne [OrbIn]::GetForegroundWindow()) {
    # Eingabe-Threads kurz koppeln, damit Windows den Fokuswechsel erlaubt (ohne Tastendruck)
    $ich = [OrbIn]::GetCurrentThreadId(); $vorne = [OrbIn]::GetWindowThreadProcessId([OrbIn]::GetForegroundWindow(), [IntPtr]::Zero)
    $ok = $vorne -ne 0 -and $vorne -ne $ich -and [OrbIn]::AttachThreadInput($ich, $vorne, $true)
    [OrbIn]::BringWindowToTop($w) | Out-Null; [OrbIn]::SetForegroundWindow($w) | Out-Null
    if ($ok) { [OrbIn]::AttachThreadInput($ich, $vorne, $false) | Out-Null }
    Start-Sleep -Milliseconds 120
  }
}
function Pos($x, $y) {
  $rx = [Math]::Max(0, [Math]::Min($sw - 1, [int][Math]::Round([double]$x * $f)))
  $ry = [Math]::Max(0, [Math]::Min($sh - 1, [int][Math]::Round([double]$y * $f)))
  [OrbIn]::SetCursorPos($rx, $ry) | Out-Null; Start-Sleep -Milliseconds 80; Fokus
}
function Klick([uint32]$down, [uint32]$up) { [OrbIn]::mouse_event($down, 0, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 40; [OrbIn]::mouse_event($up, 0, 0, 0, [IntPtr]::Zero) }
$VK = @{ win = 0x5B; ctrl = 0x11; alt = 0x12; shift = 0x10 }
$SK = @{ enter='{ENTER}'; tab='{TAB}'; esc='{ESC}'; space=' '; backspace='{BACKSPACE}'; delete='{DELETE}'; up='{UP}'; down='{DOWN}';
         left='{LEFT}'; right='{RIGHT}'; home='{HOME}'; end='{END}'; pageup='{PGUP}'; pagedown='{PGDN}' }
1..12 | ForEach-Object { $SK["f$_"] = "{F$_}" }
function Tu([string]$Aktion, [string]$A, [string]$B) {
switch ($Aktion.ToLower()) {
  'klick'       { Pos $A $B; Klick 0x02 0x04; "Geklickt bei $A,$B" }
  'doppelklick' { Pos $A $B; Klick 0x02 0x04; Start-Sleep -Milliseconds 80; Klick 0x02 0x04; "Doppelklick bei $A,$B" }
  'rechtsklick' { Pos $A $B; Klick 0x08 0x10; "Rechtsklick bei $A,$B" }
  'bewegen'     { Pos $A $B; "Maus bei $A,$B" }
  'scrollen'    { [OrbIn]::mouse_event(0x0800, 0, 0, [int]$A * 120, [IntPtr]::Zero); "Gescrollt $A" }
  'tippen'      { Fokus; $t = ($A -replace '([+^%~(){}\[\]])', '{$1}'); [System.Windows.Forms.SendKeys]::SendWait($t); "Getippt: $A" }
  'taste' { Fokus
    $teile = $A.ToLower() -split '\+'
    $haupt = $teile[-1]; $mods = @($teile | Select-Object -SkipLast 1)
    if ($haupt -eq 'win' -or $mods -contains 'win') {
      $alle = @($mods + $haupt | ForEach-Object { if ($VK.ContainsKey($_)) { $VK[$_] } elseif ($_.Length -eq 1) { [byte][char]$_.ToUpper() } })
      foreach ($k in $alle) { [OrbIn]::keybd_event([byte]$k, 0, 0, [IntPtr]::Zero) }
      [array]::Reverse($alle); foreach ($k in $alle) { [OrbIn]::keybd_event([byte]$k, 0, 2, [IntPtr]::Zero) }
    } else {
      $p = ($mods | ForEach-Object { @{ ctrl = '^'; alt = '%'; shift = '+' }[$_] }) -join ''
      $k = if ($SK.ContainsKey($haupt)) { $SK[$haupt] } else { $haupt }
      [System.Windows.Forms.SendKeys]::SendWait($p + $k)
    }
    "Taste: $A"
  }
  'warten'      { Start-Sleep -Milliseconds ([int]$A); "Gewartet $A ms" }
  default { "Unbekannte Aktion: $Aktion (klick, doppelklick, rechtsklick, bewegen, scrollen, tippen, taste, warten)" }
}}
if ($Aktion.ToLower() -eq 'folge') {
  foreach ($schritt in ($A -split ';')) {
    $w = $schritt.Trim(); if (-not $w) { continue }
    $teil = $w -split '\s+', 2; $akt = $teil[0]; $rest = if ($teil.Count -gt 1) { $teil[1] } else { '' }
    if ($akt -in 'tippen', 'taste', 'warten', 'scrollen') { Tu $akt $rest '' }
    else { $xy = $rest -split '[\s,]+'; Tu $akt $xy[0] $xy[1] }
    Start-Sleep -Milliseconds 60
  }
} else { Tu $Aktion $A $B }
if ($Bild) { Start-Sleep -Milliseconds 250; & "$PSScriptRoot\bildschirm.ps1" }

