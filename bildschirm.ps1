# Macht einen Screenshot des Hauptbildschirms für ORB (ORBs eigenes Fenster wird dafür kurz ausgeblendet).
#   powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\ORB\app\bildschirm.ps1"
# Ergebnis: %LOCALAPPDATA%\ORB\screen\bildschirm.png (max. 1600 px breit). Die Koordinaten in diesem Bild
# nimmt steuern.ps1 direkt entgegen (Umrechnung auf echte Pixel passiert automatisch).
param([switch]$OrbAusgeblendetLassen)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class OrbScr {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
}
'@
[OrbScr]::SetProcessDPIAware() | Out-Null
$dir = "$env:LOCALAPPDATA\ORB\screen"; New-Item -ItemType Directory -Force $dir | Out-Null
$orb = Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq 'ORB' } | Select-Object -First 1
$warSichtbar = $orb -and -not [OrbScr]::IsIconic($orb.MainWindowHandle)
if ($warSichtbar) { [OrbScr]::ShowWindow($orb.MainWindowHandle, 6) | Out-Null; Start-Sleep -Milliseconds 350 }   # minimieren
$w = [OrbScr]::GetSystemMetrics(0); $h = [OrbScr]::GetSystemMetrics(1)
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen(0, 0, 0, 0, $bmp.Size); $g.Dispose()
if ($warSichtbar -and -not $OrbAusgeblendetLassen) { [OrbScr]::ShowWindow($orb.MainWindowHandle, 9) | Out-Null }
$bw = [Math]::Min(1600, $w); $bh = [int]($h * $bw / $w)
$klein = New-Object System.Drawing.Bitmap $bmp, $bw, $bh
$pfad = "$dir\bildschirm.png"
$klein.Save($pfad, [System.Drawing.Imaging.ImageFormat]::Png); $klein.Dispose(); $bmp.Dispose()
Set-Content "$dir\massstab.txt" ("{0}" -f ($w / $bw)) -Encoding ASCII
Write-Output "Screenshot: $pfad ($bw x $bh Pixel). Mit dem Read-Werkzeug ansehen. Für Klicks diese Bild-Koordinaten an steuern.ps1 geben."
