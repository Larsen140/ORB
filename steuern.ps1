# Lässt ORB Maus und Tastatur bedienen – NUR auf ausdrücklichen Wunsch von Larsen.
# Koordinaten sind die aus dem letzten Screenshot (bildschirm.ps1); sie werden automatisch umgerechnet.
#   ... steuern.ps1 klick 640 380          ... steuern.ps1 doppelklick 640 380     ... steuern.ps1 rechtsklick 640 380
#   ... steuern.ps1 tippen "Hallo Welt"     ... steuern.ps1 taste enter              ... steuern.ps1 taste ctrl+s
#   ... steuern.ps1 scrollen -5             ... steuern.ps1 bewegen 640 380
# Tasten: enter, tab, esc, space, backspace, delete, up, down, left, right, home, end, pageup, pagedown, win, f1–f12,
#         Kombinationen mit ctrl+ / alt+ / shift+ (z. B. ctrl+c, alt+tab, ctrl+shift+t)
param([Parameter(Mandatory = $true)][string]$Aktion, [string]$A, [string]$B)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System; using System.Runtime.InteropServices;
public class OrbIn {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, int d, IntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte s, uint f, IntPtr e);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}
'@
[OrbIn]::SetProcessDPIAware() | Out-Null
# ORBs eigenes Fenster aus dem Weg (sonst landen Klicks auf ORB)
$orb = Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq 'ORB' } | Select-Object -First 1
if ($orb) { [OrbIn]::ShowWindow($orb.MainWindowHandle, 6) | Out-Null; Start-Sleep -Milliseconds 300 }
$f = 1.0; try { $f = [double](Get-Content "$env:LOCALAPPDATA\ORB\screen\massstab.txt" -ErrorAction Stop) } catch {}
function Pos($x, $y) { [OrbIn]::SetCursorPos([int]([double]$x * $f), [int]([double]$y * $f)) | Out-Null; Start-Sleep -Milliseconds 60 }
function Klick([uint32]$down, [uint32]$up) { [OrbIn]::mouse_event($down, 0, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 40; [OrbIn]::mouse_event($up, 0, 0, 0, [IntPtr]::Zero) }
$VK = @{ win = 0x5B; ctrl = 0x11; alt = 0x12; shift = 0x10 }
$SK = @{ enter='{ENTER}'; tab='{TAB}'; esc='{ESC}'; space=' '; backspace='{BACKSPACE}'; delete='{DELETE}'; up='{UP}'; down='{DOWN}';
         left='{LEFT}'; right='{RIGHT}'; home='{HOME}'; end='{END}'; pageup='{PGUP}'; pagedown='{PGDN}' }
1..12 | ForEach-Object { $SK["f$_"] = "{F$_}" }
switch ($Aktion.ToLower()) {
  'klick'       { Pos $A $B; Klick 0x02 0x04; "Geklickt bei $A,$B" }
  'doppelklick' { Pos $A $B; Klick 0x02 0x04; Start-Sleep -Milliseconds 80; Klick 0x02 0x04; "Doppelklick bei $A,$B" }
  'rechtsklick' { Pos $A $B; Klick 0x08 0x10; "Rechtsklick bei $A,$B" }
  'bewegen'     { Pos $A $B; "Maus bei $A,$B" }
  'scrollen'    { [OrbIn]::mouse_event(0x0800, 0, 0, [int]$A * 120, [IntPtr]::Zero); "Gescrollt $A" }
  'tippen'      { $t = ($A -replace '([+^%~(){}\[\]])', '{$1}'); [System.Windows.Forms.SendKeys]::SendWait($t); "Getippt: $A" }
  'taste' {
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
  default { "Unbekannte Aktion: $Aktion (klick, doppelklick, rechtsklick, bewegen, scrollen, tippen, taste)"; exit 1 }
}
