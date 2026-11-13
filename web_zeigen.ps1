# Zeigt eine Webseite als echtes, bedienbares Hologramm in ORB (klicken, scrollen, tippen) – statt Screenshot.
#   ... web_zeigen.ps1 "https://example.org"  [-Titel "Name"]
# Seiten, die das Einbetten verbieten, öffnet ORB automatisch in einer echten Webansicht über dem Hologramm.
param([Parameter(Mandatory = $true)][string]$Url, [string]$Titel = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$port = if ($env:ORB_PORT) { $env:ORB_PORT } else { 8766 }
$datei = if ([int]$port -eq 8766) { 'token.txt' } else { "token_$port.txt" }
try { $tok = (Get-Content "$env:LOCALAPPDATA\ORB\$datei" -Raw).Trim() }
catch { Write-Output '{"ok":false,"fehler":"ORB-Token nicht gefunden – läuft ORB?"}'; exit 1 }
$body = [Text.Encoding]::UTF8.GetBytes((@{ url = $Url; titel = $Titel } | ConvertTo-Json -Compress))
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/web" -Method POST -UseBasicParsing -TimeoutSec 15 `
        -Headers @{ 'X-ORB-Token' = $tok } -ContentType 'application/json; charset=utf-8' -Body $body
    Write-Output $r.Content
} catch { Write-Output '{"ok":false,"fehler":"ORB nicht erreichbar"}'; exit 1 }
