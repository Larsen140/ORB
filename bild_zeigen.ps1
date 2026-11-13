# Blendet ein Bild sofort als Hologramm in ORB ein – für Claude nach dem Erstellen eines Bildes.
#   ... bild_zeigen.ps1 "C:\Pfad\zum\Bild.png"
# Bilder in "Bilder\ORB Bilder" erscheinen auch ohne dieses Skript automatisch.
param([Parameter(Mandatory = $true)][string]$Pfad)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$port = if ($env:ORB_PORT) { $env:ORB_PORT } else { 8766 }
$datei = if ([int]$port -eq 8766) { 'token.txt' } else { "token_$port.txt" }
try { $tok = (Get-Content "$env:LOCALAPPDATA\ORB\$datei" -Raw).Trim() }
catch { Write-Output '{"ok":false,"fehler":"ORB-Token nicht gefunden – läuft ORB?"}'; exit 1 }
try { $voll = (Resolve-Path -LiteralPath $Pfad).ProviderPath }
catch { Write-Output '{"ok":false,"fehler":"Bild nicht gefunden"}'; exit 1 }
$body = [Text.Encoding]::UTF8.GetBytes((@{ pfad = $voll } | ConvertTo-Json -Compress))
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/bild" -Method POST -UseBasicParsing -TimeoutSec 10 `
        -Headers @{ 'X-ORB-Token' = $tok } -ContentType 'application/json; charset=utf-8' -Body $body
    Write-Output $r.Content
} catch { Write-Output '{"ok":false,"fehler":"ORB nicht erreichbar"}'; exit 1 }
