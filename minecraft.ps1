# Steuert Minecraft (Java, jede Version, mit oder ohne Mods/LabyMod) über den Chat – wie ein Spieler, der tippt.
#   ... minecraft.ps1 -Info                          → läuft Minecraft? Version, Einzel-/Mehrspieler (aus dem Fenstertitel)
#   ... minecraft.ps1 -Befehl "time set day; weather clear"   → Befehle nacheinander (ohne führenden /)
#   ... minecraft.ps1 -Datei C:\pfad\bau.txt          → eine Befehlszeile pro Zeile (z. B. /fill-Befehle für Bauten)
#   ... minecraft.ps1 -Sagen "Text"                   → Nachricht im Spiel-Chat (tellraw, nur mit Cheats/OP)
# Befehle brauchen Cheats (Welt mit Cheats oder „Im LAN öffnen“ → Cheats an) bzw. OP auf dem Server.
param([switch]$Info, [string]$Befehl, [string]$Datei, [string]$Sagen, [int]$Pause = 140)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
if (-not ('OrbMc' -as [type])) {
Add-Type @'
using System; using System.Text; using System.Runtime.InteropServices;
public class OrbMc {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte s, uint f, IntPtr e);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  public static IntPtr Fenster; public static string Titel = "";
  public static void Suchen() {
    Fenster = IntPtr.Zero; Titel = "";
    EnumWindows((h, l) => {
      if (!IsWindowVisible(h)) return true;
      var sb = new StringBuilder(256); GetWindowText(h, sb, 256); var t = sb.ToString();
      if (t.StartsWith("Minecraft") || t.Contains("LabyMod") || t.StartsWith("Lunar Client") || t.StartsWith("Badlion")) {
        if (!t.Contains("Launcher")) { Fenster = h; Titel = t; return false; }
      }
      return true; }, IntPtr.Zero);
  }
  public static void Taste(byte vk) { keybd_event(vk, 0, 0, IntPtr.Zero); System.Threading.Thread.Sleep(25); keybd_event(vk, 0, 2, IntPtr.Zero); }
}
'@
}
[OrbMc]::Suchen()
if ($Info) {
    if ([OrbMc]::Fenster -eq [IntPtr]::Zero) { '{"laeuft":false}'; exit 0 }
    $t = [OrbMc]::Titel
    $v = if ($t -match '(\d+\.\d+(\.\d+)?(-[\w.]+)?|\d\dw\d\d\w)') { $Matches[1] } else { '' }
    $modus = if ($t -match 'Einzelspieler|Singleplayer') { 'einzelspieler' } elseif ($t -match 'Mehrspieler|Multiplayer|Server|LAN') { 'mehrspieler' } else { 'menue' }
    @{ laeuft = $true; titel = $t; version = $v; modus = $modus } | ConvertTo-Json -Compress
    exit 0
}
if ([OrbMc]::Fenster -eq [IntPtr]::Zero) { Write-Output 'Minecraft läuft nicht (kein Spielfenster gefunden).'; exit 1 }

$liste = @()
if ($Befehl) { $liste += ($Befehl -split ';') }
if ($Datei)  { $liste += Get-Content -LiteralPath $Datei -Encoding UTF8 }
if ($Sagen)  { $liste += 'tellraw @s {"text":"[Jarvis] ' + ($Sagen -replace '"', "'") + '","color":"aqua"}' }
$liste = @($liste | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
if (-not $liste) { Write-Output 'Kein Befehl angegeben.'; exit 1 }

# ORB aus dem Weg, Minecraft nach vorne
$orb = Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq 'ORB' } | Select-Object -First 1
if ($orb) { [OrbMc]::ShowWindow($orb.MainWindowHandle, 6) | Out-Null }
[OrbMc]::ShowWindow([OrbMc]::Fenster, 9) | Out-Null
[OrbMc]::SetForegroundWindow([OrbMc]::Fenster) | Out-Null
Start-Sleep -Milliseconds 350
$altClip = try { [System.Windows.Forms.Clipboard]::GetText() } catch { '' }
$n = 0
foreach ($b in $liste) {
    $cmd = if ($b.StartsWith('/')) { $b } else { '/' + $b }
    if ($cmd.Length -gt 256) { Write-Output "Übersprungen (über 256 Zeichen): $($cmd.Substring(0,40))…"; continue }
    [System.Windows.Forms.Clipboard]::SetText($cmd)
    [OrbMc]::Taste(0x54)                      # T = Chat öffnen (geht in jeder Version)
    Start-Sleep -Milliseconds $Pause
    [OrbMc]::keybd_event(0x11, 0, 0, [IntPtr]::Zero); [OrbMc]::Taste(0x56); [OrbMc]::keybd_event(0x11, 0, 2, [IntPtr]::Zero)   # Strg+V
    Start-Sleep -Milliseconds 60
    [OrbMc]::Taste(0x0D)                      # Enter
    Start-Sleep -Milliseconds $Pause
    $n++
}
if ($altClip) { try { [System.Windows.Forms.Clipboard]::SetText($altClip) } catch {} }
Write-Output "$n Befehl(e) in Minecraft ausgeführt ($([OrbMc]::Titel))."
