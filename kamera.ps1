# Holt EIN Standbild aus der Kamera-Ansicht von ORB – nur, wenn Larsen ausdrücklich fragt, was ORB sieht.
#   powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\ORB\app\kamera.ps1"
# Ergebnis: %LOCALAPPDATA%\ORB\screen\kamera.png (wird bei jeder Anfrage überschrieben, nichts wird gesendet).
# Die Kamera wird hiermit NIE eingeschaltet – ist sie aus, kommt eine Fehlermeldung zurück.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$port = if ($env:ORB_PORT) { $env:ORB_PORT } else { 8766 }
$datei = if ([int]$port -eq 8766) { 'token.txt' } else { "token_$port.txt" }
try { $tok = (Get-Content "$env:LOCALAPPDATA\ORB\$datei" -Raw).Trim() }
catch { Write-Output '{"ok":false,"fehler":"ORB-Token nicht gefunden – läuft ORB?"}'; exit 1 }
$pfad = "$env:LOCALAPPDATA\ORB\screen\kamera.png"
$vorher = if (Test-Path $pfad) { (Get-Item $pfad).LastWriteTimeUtc } else { [datetime]::MinValue }
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/kamera/foto" -Method POST -UseBasicParsing -TimeoutSec 10 `
        -Headers @{ 'X-ORB-Token' = $tok } -ContentType 'application/json; charset=utf-8' -Body '{}'
} catch { Write-Output '{"ok":false,"fehler":"ORB nicht erreichbar"}'; exit 1 }
$j = $r.Content | ConvertFrom-Json
if (-not $j.ok) { Write-Output $r.Content; exit 1 }
for ($i = 0; $i -lt 40; $i++) {   # die Oberfläche liefert das Bild beim nächsten Abruf (meist < 1 s)
    Start-Sleep -Milliseconds 250
    if ((Test-Path $pfad) -and (Get-Item $pfad).LastWriteTimeUtc -gt $vorher) {
        Write-Output "Kamerabild: $pfad – mit dem Read-Werkzeug ansehen (echtes, nicht gespiegeltes Kamerabild)."
        exit 0
    }
}
Write-Output '{"ok":false,"fehler":"Kein Kamerabild bekommen – ist das ORB-Fenster offen?"}'; exit 1
