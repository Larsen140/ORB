# Zeigt ein freies Hologramm in ORB – beliebig viele gleichzeitig, jedes mit mehreren Inhalten, verschiebbar und in der Größe änderbar.
#   Schnell:  ... holo.ps1 -Titel "Wetter" -Text "Morgen 12°" -Punkte "Regen ab 14 Uhr|Wind 20 km/h" -Groesse klein
#   Voll:     ... holo.ps1 -Json "C:\Pfad\karte.json"   (oder JSON direkt als Text)
#   Ändern:   gleiche -Id erneut senden (-Anhaengen fügt Inhalte hinzu);  Schließen: -Id x -Zu;  alle zu: -AlleZu
# JSON: {"id":"wetter","titel":"…","groesse":"klein|mittel|gross|riesig","breite":500,"hoehe":300,"farbe":"blau|gruen|rot|gelb|lila|pink|orange|#hex",
#        "dauer":0, "inhalt":[ {"typ":"titel","text":"…"}, {"typ":"text","text":"…"}, {"typ":"liste","punkte":["a","b"]},
#        {"typ":"zahl","wert":"21","einheit":"°C","label":"Außen","reihe":true}, {"typ":"fortschritt","prozent":40,"label":"…"},
#        {"typ":"bild","pfad":"C:\…\bild.png"}, {"typ":"web","url":"https://…"}, {"typ":"tabelle","kopf":["A","B"],"zeilen":[["1","2"]]},
#        {"typ":"trenner"} ]}     ("reihe":true stellt Blöcke nebeneinander)
param([string]$Json, [string]$Id, [string]$Titel, [string]$Text, [string]$Punkte, [string]$Bild, [string]$Web,
      [string]$Groesse = 'mittel', [string]$Farbe, [int]$Dauer = 0, [switch]$Anhaengen, [switch]$Zu, [switch]$AlleZu)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$port = if ($env:ORB_PORT) { $env:ORB_PORT } else { 8766 }
$datei = if ([int]$port -eq 8766) { 'token.txt' } else { "token_$port.txt" }
$tok = (Get-Content "$env:LOCALAPPDATA\ORB\$datei" -Raw -ErrorAction SilentlyContinue)
if (-not $tok) { Write-Output '{"ok":false,"fehler":"ORB läuft nicht"}'; exit 1 }
if ($Json) {
    $roh = if (Test-Path -LiteralPath $Json) { [IO.File]::ReadAllText($Json, [Text.Encoding]::UTF8) } else { $Json }
    $daten = $roh | ConvertFrom-Json
} else {
    $inhalt = @()
    if ($Text)   { $inhalt += @{ typ = 'text'; text = $Text } }
    if ($Punkte) { $inhalt += @{ typ = 'liste'; punkte = @($Punkte -split '\|') } }
    if ($Bild)   { $inhalt += @{ typ = 'bild'; pfad = $Bild } }
    if ($Web)    { $inhalt += @{ typ = 'web'; url = $Web } }
    $daten = @{ titel = $Titel; groesse = $Groesse; inhalt = $inhalt; dauer = $Dauer }
    if ($Farbe) { $daten.farbe = $Farbe }
}
if ($Id) { $daten | Add-Member -NotePropertyName id -NotePropertyValue $Id -Force -ErrorAction SilentlyContinue; if ($daten -is [hashtable]) { $daten.id = $Id } }
if ($Anhaengen) { if ($daten -is [hashtable]) { $daten.anhaengen = $true } else { $daten | Add-Member anhaengen $true -Force } }
if ($Zu)     { $daten = @{ id = $Id; zu = $true } }
if ($AlleZu) { $daten = @{ alle_zu = $true } }
$body = [Text.Encoding]::UTF8.GetBytes(($daten | ConvertTo-Json -Depth 8 -Compress))
try { (Invoke-WebRequest "http://127.0.0.1:$port/karte" -Method Post -Headers @{ 'X-ORB-Token' = $tok.Trim() } -ContentType 'application/json; charset=utf-8' -Body $body -UseBasicParsing -TimeoutSec 5).Content }
catch { Write-Output '{"ok":false,"fehler":"ORB nicht erreichbar"}'; exit 1 }
