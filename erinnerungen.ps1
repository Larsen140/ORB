# iCloud-Erinnerungen (iPhone-App „Erinnerungen“) über ORB – für Claude (liest den ORB-Token selbst).
#   ... erinnerungen.ps1 liste [-Liste "Einkauf"] [-Alle]     → offene Erinnerungen (-Alle: auch erledigte)
#   ... erinnerungen.ps1 neu -Titel "Milch kaufen" [-Faellig 2026-11-20T18:00] [-Liste ".."] [-Notiz ".."] [-Wichtig]
#        (nur Datum = ganztägig fällig; mit Uhrzeit meldet sich das iPhone zu dieser Zeit; Zeiten sind Ortszeit)
#   ... erinnerungen.ps1 erledigt -Id "<id aus der Liste>" [-Offen]   (-Offen macht das Abhaken rückgängig)
#   ... erinnerungen.ps1 loeschen -Id "<id aus der Liste>"
param([Parameter(Mandatory = $true)][ValidateSet('liste', 'neu', 'erledigt', 'loeschen')][string]$Aktion,
      [string]$Titel, [string]$Faellig, [string]$Liste, [string]$Notiz, [string]$Id,
      [switch]$Wichtig, [switch]$Alle, [switch]$Offen)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$port = if ($env:ORB_PORT) { $env:ORB_PORT } else { 8766 }
$url = "http://127.0.0.1:$port"

$datei = if ([int]$port -eq 8766) { 'token.txt' } else { "token_$port.txt" }
try { $tok = (Get-Content "$env:LOCALAPPDATA\ORB\$datei" -Raw).Trim() }
catch { Write-Output '{"ok":false,"fehler":"ORB-Token nicht gefunden – läuft ORB?"}'; exit 1 }

function Rufe($daten) {
    $p = @{ Uri = "$url/erinnerungen"; Method = 'POST'; UseBasicParsing = $true; TimeoutSec = 60
            Headers = @{ 'X-ORB-Token' = $tok }; ContentType = 'application/json; charset=utf-8'
            Body = [Text.Encoding]::UTF8.GetBytes(($daten | ConvertTo-Json -Compress)) }
    try {
        $r = Invoke-WebRequest @p
        $ms = New-Object IO.MemoryStream; $r.RawContentStream.CopyTo($ms)
        return [Text.Encoding]::UTF8.GetString($ms.ToArray())
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 403) {
            return '{"ok":false,"fehler":"ORB lehnt den Token ab (veraltet) – nach dem nächsten ORB-Neustart klappt es"}'
        }
        return (@{ ok = $false; fehler = "ORB nicht erreichbar: $($_.Exception.Message)" } | ConvertTo-Json -Compress)
    }
}

switch ($Aktion) {
    'liste' { $out = Rufe @{ aktion = 'liste'; liste = $Liste; alle = [bool]$Alle } }
    'neu' {
        if (-not $Titel) { $out = '{"ok":false,"fehler":"-Titel nötig"}'; break }
        $d = @{ aktion = 'neu'; titel = $Titel; wichtig = [bool]$Wichtig }
        if ($Faellig) { $d.faellig = $Faellig }
        if ($Liste) { $d.liste = $Liste }
        if ($Notiz) { $d.notiz = $Notiz }
        $out = Rufe $d
    }
    'erledigt' {
        if (-not $Id) { $out = '{"ok":false,"fehler":"-Id nötig (erst liste aufrufen)"}'; break }
        $out = Rufe @{ aktion = 'erledigt'; id = $Id; offen = [bool]$Offen }
    }
    'loeschen' {
        if (-not $Id) { $out = '{"ok":false,"fehler":"-Id nötig (erst liste aufrufen)"}'; break }
        $out = Rufe @{ aktion = 'loeschen'; id = $Id }
    }
}
Write-Output $out
