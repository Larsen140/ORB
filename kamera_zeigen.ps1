# Schickt Inhalte in die laufende Kamera-Ansicht von ORB (schaltet die Kamera NIE ein – ist sie aus, kommt ein Fehler zurück).
#   Widget:    ... kamera_zeigen.ps1 -Art wetter        (uhr | wetter | termine | spotify | gold | system)
#   Text:      ... kamera_zeigen.ps1 -Art text -Id einkauf -Titel "Einkauf" -Text "Für heute" -Punkte "Milch|Brot"
#   Bild:      ... kamera_zeigen.ps1 -Art bild -Bild "C:\Pfad\bild.png"     (ohne -Bild: das letzte Bild-Hologramm)
#   3D-Objekt: ... kamera_zeigen.ps1 -Art sphaere -Hand   (sphaere | wuerfel | modell; -Hand = schwebt über der offenen Hand)
#   Sonstiges: -Art menue (Gesten-Menü öffnen) | zeichnen (Luft-Zeichnen an/aus) | aufraeumen (alles weg);  -Id x -Zu schließt einen Inhalt
# Alles bleibt lokal; die Inhalte lassen sich per Hand greifen, verschieben, drehen, skalieren, anheften, parken und wegwischen.
param([string]$Art = 'text', [string]$Id, [string]$Titel, [string]$Text, [string]$Punkte, [string]$Bild, [switch]$Hand, [switch]$Zu)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$port = if ($env:ORB_PORT) { $env:ORB_PORT } else { 8766 }
$datei = if ([int]$port -eq 8766) { 'token.txt' } else { "token_$port.txt" }
$tok = (Get-Content "$env:LOCALAPPDATA\ORB\$datei" -Raw -ErrorAction SilentlyContinue)
if (-not $tok) { Write-Output '{"ok":false,"fehler":"ORB läuft nicht"}'; exit 1 }
$daten = @{ art = $Art; id = $Id; titel = $Titel; text = $Text; hand = [bool]$Hand; zu = [bool]$Zu }
if ($Punkte) { $daten.punkte = @($Punkte -split '\|') }
if ($Bild) { $daten.pfad = (Resolve-Path -LiteralPath $Bild -ErrorAction SilentlyContinue).Path; if (-not $daten.pfad) { $daten.pfad = $Bild } }
$body = [Text.Encoding]::UTF8.GetBytes(($daten | ConvertTo-Json -Depth 4 -Compress))
try { $r = (Invoke-WebRequest "http://127.0.0.1:$port/kamera/zeigen" -Method Post -Headers @{ 'X-ORB-Token' = $tok.Trim() } -ContentType 'application/json; charset=utf-8' -Body $body -UseBasicParsing -TimeoutSec 5).Content }
catch { Write-Output '{"ok":false,"fehler":"ORB nicht erreichbar"}'; exit 1 }
Write-Output $r
if (($r | ConvertFrom-Json).ok) { exit 0 } else { exit 1 }
