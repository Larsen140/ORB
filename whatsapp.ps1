# WhatsApp-Nachricht schnell vorbereiten (WhatsApp Desktop direkt per Tastatur, feste kurze Wartezeiten, ~5 s).
#   ... whatsapp.ps1 -Kontakt 'Wife' -Text 'Hier guck mal' [-Bild '<Pfad>']   -> nur vorbereiten + Kontroll-Screenshot
#   ... whatsapp.ps1 -Senden                                                -> die vorbereitete Nachricht abschicken
#   ... whatsapp.ps1 -Verwerfen                                             -> vorbereitete Nachricht/Bildvorschau verwerfen
#   ... whatsapp.ps1 -Kontakt ... -Text ... -Senden                         -> vorbereiten und sofort abschicken
# Abschicken NUR nach Larsens Bestätigung. Ergebnis-Screenshot: %LOCALAPPDATA%\ORB\screen\bildschirm.png
param([string]$Kontakt, [string]$Text, [string]$Bild, [switch]$Senden, [switch]$Verwerfen)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System; using System.Text; using System.Runtime.InteropServices;
public class OrbWa {
  public delegate bool CB(IntPtr h, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct R { public int L, T, Ri, B; }
  [DllImport("user32.dll")] public static extern bool EnumWindows(CB cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr p);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr c);
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, int d, IntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte s, uint f, IntPtr e);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int hh, bool r);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int a, out R r, int s);
  public static IntPtr Haupt(uint pid) {
    IntPtr g = IntPtr.Zero;
    EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p); if (p != pid) return true;
      var c = new StringBuilder(100); GetClassName(h, c, 100);
      if (c.ToString() == "WinUIDesktopWin32WindowClass") { g = h; return false; } return true; }, IntPtr.Zero);
    return g;
  }
}
'@
try { [OrbWa]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null } catch {}
$app = "$env:LOCALAPPDATA\ORB\app"
function Ende($t) { Write-Output $t; exit 1 }
function Warte($ms) { Start-Sleep -Milliseconds $ms }
function Tasten($k) { [System.Windows.Forms.SendKeys]::SendWait($k) }
function Fenster {
  $p = Get-Process WhatsApp.Root -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($p) { $h = [OrbWa]::Haupt([uint32]$p.Id); if ($h -ne [IntPtr]::Zero -and [OrbWa]::IsWindowVisible($h)) { return $h } }
  return [IntPtr]::Zero
}
# 1) WhatsApp öffnen bzw. aus dem Infobereich holen
$h = Fenster
$neu = $false
if ($h -eq [IntPtr]::Zero) {
  $pkg = Get-AppxPackage *WhatsAppDesktop* | Select-Object -First 1
  if (-not $pkg) { Ende 'WhatsApp Desktop ist nicht installiert.' }
  $neu = -not (Get-Process WhatsApp.Root -ErrorAction SilentlyContinue)
  Start-Process "shell:AppsFolder\$($pkg.PackageFamilyName)!App"
  $t = [Diagnostics.Stopwatch]::StartNew()
  while (($h = Fenster) -eq [IntPtr]::Zero) { if ($t.Elapsed.TotalSeconds -gt 20) { Ende 'WhatsApp-Fenster erscheint nicht.' }; Warte 150 }
  Warte $(if ($neu) { 6000 } else { 600 })   # frisch gestartet: Chats laden lassen
}
if ([OrbWa]::IsIconic($h)) { [OrbWa]::ShowWindow($h, 9) | Out-Null; Warte 300 }
# ORB aus dem Weg, damit nichts dazwischenfunkt
$orb = Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq 'ORB' } | Select-Object -First 1
if ($orb) { [OrbWa]::ShowWindow($orb.MainWindowHandle, 6) | Out-Null }
# 2) WhatsApp nach vorne holen und sicherstellen, dass die Tastatur wirklich dort ankommt
function Vorne {
  for ($i = 0; $i -lt 5; $i++) {
    if ([OrbWa]::GetForegroundWindow() -eq $h) { return $true }
    [OrbWa]::keybd_event(0x12, 0, 0, [IntPtr]::Zero); [OrbWa]::keybd_event(0x12, 0, 2, [IntPtr]::Zero)   # Alt: erlaubt Fokuswechsel
    $ich = [OrbWa]::GetCurrentThreadId(); $fg = [OrbWa]::GetWindowThreadProcessId([OrbWa]::GetForegroundWindow(), [IntPtr]::Zero)
    $ok = $fg -ne 0 -and $fg -ne $ich -and [OrbWa]::AttachThreadInput($ich, $fg, $true)
    [OrbWa]::BringWindowToTop($h) | Out-Null; [OrbWa]::SetForegroundWindow($h) | Out-Null
    if ($ok) { [OrbWa]::AttachThreadInput($ich, $fg, $false) | Out-Null }
    Warte 200
  }
  return [OrbWa]::GetForegroundWindow() -eq $h
}
if (-not (Vorne)) { Ende 'WhatsApp ließ sich nicht in den Vordergrund holen – nichts getippt.' }
function Screenshot { & powershell -NoProfile -ExecutionPolicy Bypass -File "$app\bildschirm.ps1" | Out-Null; "$env:LOCALAPPDATA\ORB\screen\bildschirm.png" }

# Merker: liegt noch eine unbestätigte Bildvorschau offen? (Fokus steht dann im Bildunterschrift-Feld)
$merker = "$env:LOCALAPPDATA\ORB\screen\whatsapp_vorschau.txt"
function VorschauWeg {
  if (-not (Test-Path $merker)) { return }
  Tasten '{ESC}'; Warte 400; Tasten '+{TAB}'; Warte 150; Tasten '{ENTER}'; Warte 500   # „Auswahl verwerfen?“ -> Verwerfen
  Remove-Item $merker -ErrorAction SilentlyContinue
}
# Nur abschicken (nach Bestätigung) bzw. verwerfen
if (-not $Kontakt) {
  if ($Verwerfen) {
    VorschauWeg; Tasten '^a'; Tasten '{BACKSPACE}'; Warte 300
    Write-Output "Entwurf verworfen. Kontroll-Screenshot: $(Screenshot)"; exit 0
  }
  if (-not $Senden) { Ende 'Bitte -Kontakt angeben (oder -Senden / -Verwerfen für die vorbereitete Nachricht).' }
  Tasten '{ENTER}'; Warte 1200; Remove-Item $merker -ErrorAction SilentlyContinue
  Write-Output "Abgeschickt. Kontroll-Screenshot: $(Screenshot)"; exit 0
}
if (-not $Text -and -not $Bild) { Ende 'Bitte -Text und/oder -Bild angeben.' }
if ($Bild -and -not (Test-Path -LiteralPath $Bild)) { Ende "Bild nicht gefunden: $Bild" }

# 3) Fenstergröße prüfen (zu schmal = andere Anordnung) und Suchfeld anklicken
$r = New-Object OrbWa+R
if ([OrbWa]::DwmGetWindowAttribute($h, 9, [ref]$r, 16) -ne 0) { [OrbWa]::GetWindowRect($h, [ref]$r) | Out-Null }
$s = [OrbWa]::GetDpiForWindow($h) / 96.0; if ($s -le 0) { $s = 1 }
if (($r.Ri - $r.L) / $s -lt 800 -or ($r.B - $r.T) / $s -lt 550) {
  [OrbWa]::MoveWindow($h, $r.L, $r.T, [int](1000 * $s), [int](700 * $s), $true) | Out-Null; Warte 500
  [OrbWa]::DwmGetWindowAttribute($h, 9, [ref]$r, 16) | Out-Null
}
VorschauWeg                                              # alte, nicht abgeschickte Bildvorschau verwerfen
Tasten '{ESC}'; Warte 150; Tasten '{ESC}'; Warte 150      # offene Hinweise/Menüs schließen
[OrbWa]::SetCursorPos($r.L + [int](190 * $s), $r.T + [int](123 * $s)) | Out-Null; Warte 60
[OrbWa]::mouse_event(0x02, 0, 0, 0, [IntPtr]::Zero); Warte 40; [OrbWa]::mouse_event(0x04, 0, 0, 0, [IntPtr]::Zero); Warte 250
if (-not (Vorne)) { Ende 'WhatsApp hat den Fokus verloren – abgebrochen.' }

# 4) Kontakt suchen und ersten Treffer öffnen
Tasten '^a'; Tasten '{BACKSPACE}'; Warte 100
Tasten ($Kontakt -replace '([+^%~(){}\[\]])', '{$1}'); Warte 1200
Tasten '{DOWN}'; Warte 200; Tasten '{ENTER}'; Warte 900
Tasten '^a'; Tasten '{BACKSPACE}'; Warte 100               # alten Entwurf im Eingabefeld leeren

# 5) Bild und/oder Text über die Zwischenablage einfügen (schnell, Umlaute/Emojis sicher)
if ($Bild) {
  $img = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $Bild).Path)
  [System.Windows.Forms.Clipboard]::SetImage($img); $img.Dispose()
  Tasten '^v'; Warte 1800                                 # Bildvorschau mit Bildunterschrift-Feld öffnet sich
}
if ($Text) { [System.Windows.Forms.Clipboard]::SetText($Text); Warte 80; Tasten '^v'; Warte 300 }
if ($Senden) { Tasten '{ENTER}'; Warte 1500 } elseif ($Bild) { Set-Content $merker (Get-Date -Format s) }

# 6) Kontroll-Screenshot
$bildPfad = Screenshot
if ($Senden) { Write-Output "Nachricht an '$Kontakt' abgeschickt. Kontroll-Screenshot: $bildPfad" }
else { Write-Output "Nachricht an '$Kontakt' vorbereitet, NICHT abgeschickt. Screenshot prüfen: $bildPfad – nach Larsens OK: whatsapp.ps1 -Senden" }
