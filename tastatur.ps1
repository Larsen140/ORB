# Acer Nitro (NitroSense) Tastaturlicht über die Acer-WMI-Schnittstelle (braucht Admin – läuft als geplante Aufgabe „ORB Tastatur“).
#   tastatur.ps1 -Lesen                → aktuelle Werte nach %LOCALAPPDATA%\ORB\tastatur.log
#   tastatur.ps1 -Farbe ff5236         → ganze Tastatur (alle 4 Zonen) statisch in dieser Farbe
#   tastatur.ps1 -Auftrag              → Farbe aus %LOCALAPPDATA%\ORB\tastatur_farbe.txt (so ruft ORB es über die Aufgabe auf)
#   tastatur.ps1 -Einrichten           → geplante Aufgabe anlegen (einmalig, mit Admin-Abfrage)
param([switch]$Lesen, [string]$Farbe, [switch]$Auftrag, [switch]$Einrichten, [int]$Hell = 100)
$ErrorActionPreference = 'Stop'
$basis = Join-Path $env:LOCALAPPDATA 'ORB'
if (-not $basis -or -not (Test-Path $basis)) { $basis = 'C:\Users\larse\AppData\Local\ORB' }
$log = Join-Path $basis 'tastatur.log'
function Log($t) { Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $t) -Encoding UTF8 }

if ($Einrichten) {
    try {
        $skript = $MyInvocation.MyCommand.Path
        $a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$skript`" -Auftrag"
        $p = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
        $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 30)
        Register-ScheduledTask -TaskName 'ORB Tastatur' -Action $a -Principal $p -Settings $s -Force | Out-Null
        Log 'Geplante Aufgabe „ORB Tastatur“ eingerichtet'
        Write-Host "`n  Fertig! ORB kann deine Tastatur jetzt einfärben.`n" -ForegroundColor Green
    } catch {
        Log "Einrichten fehlgeschlagen: $_"
        Write-Host "`n  Fehler: $_`n" -ForegroundColor Red
    }
    Start-Sleep 6
    exit 0
}

$acer = Get-CimInstance -Namespace root/WMI -ClassName AcerGamingFunction
function Ruf($m, $wert) { (Invoke-CimMethod -InputObject $acer -MethodName $m -Arguments @{ gmInput = $wert }) }

if ($Lesen) {
    try { $r = Ruf 'GetGamingKBBacklight' ([uint32]1); Log ('GetGamingKBBacklight: ' + (($r.gmOutput | % { $_ }) -join ',') + ' ret ' + $r.gmReturn) } catch { Log "KBBacklight lesen: $_" }
    foreach ($z in 1, 2, 4, 8) { try { $r = Ruf 'GetGamingLEDColor' ([uint32]$z); Log ("GetGamingLEDColor zone $z" + ': 0x' + ('{0:X16}' -f [uint64]$r.gmOutput)) } catch { Log "LEDColor $z lesen: $_" } }
    try { $r = Ruf 'GetGamingRgbKb' ([uint32]1); Log ('GetGamingRgbKb: 0x' + ('{0:X16}' -f [uint64]$r.gmOutput)) } catch { Log "RgbKb lesen: $_" }
    try { $r = Ruf 'GetGamingLEDBehavior' ([uint32]1); Log ('GetGamingLEDBehavior: 0x' + ('{0:X16}' -f [uint64]$r.gmOutput)) } catch { Log "LEDBehavior lesen: $_" }
    exit 0
}

if ($Auftrag) { $Farbe = (Get-Content -LiteralPath (Join-Path $basis 'tastatur_farbe.txt') -Raw).Trim() }
if ($Farbe -notmatch '^#?[0-9a-fA-F]{6}$') { Log "ungültige Farbe: $Farbe"; exit 1 }
$h = $Farbe.TrimStart('#')
$rot = [Convert]::ToByte($h.Substring(0, 2), 16); $gruen = [Convert]::ToByte($h.Substring(2, 2), 16); $blau = [Convert]::ToByte($h.Substring(4, 2), 16)
try {
    # 1) Effekt „statisch“ mit Farbe – Aufbau wie beim Auslesen: Modus, Tempo, Helligkeit, 0, Richtung, R, G, B, 3, 0 …
    [byte[]]$kb = 0, 0, ([byte]$Hell), 0, 0, $rot, $gruen, $blau, 3, 0, 0, 0, 0, 0, 0, 0
    $r1 = Ruf 'SetGamingKBBacklight' $kb
    # 2) Tastaturfarbe (Zone | R<<8 | G<<16 | B<<24; ausgelesen: 0x65FF0000 = Grün 255, Blau 101)
    $r2 = @()
    foreach ($z in 0, 1, 2, 4, 8) { $wert = [uint64]$z -bor ([uint64]$rot -shl 8) -bor ([uint64]$gruen -shl 16) -bor ([uint64]$blau -shl 24); try { $r2 += (Ruf 'SetGamingRgbKb' $wert).gmOutput } catch { $r2 += 'x' } }
    Log ("Farbe $h gesetzt · KB " + $r1.gmOutput + ' · RgbKb ' + ($r2 -join ','))
} catch { Log "Setzen fehlgeschlagen: $_" ; exit 1 }
