# iCloud-Kalender über ORB – für Claude (liest den ORB-Token selbst, er wird nie ausgegeben).
#   ... kalender.ps1 status                                   → iCloud verbunden? (Apple-ID)
#   ... kalender.ps1 liste [-Von 2026-11-13] [-Bis 2026-11-20] → Termine (ohne Angabe: heute + 7 Tage)
#   ... kalender.ps1 neu -Titel "Zahnarzt" -Start 2026-11-20T15:00 [-Ende 2026-11-20T16:00] [-Ort ".."] [-Notiz ".."] [-Kalender ".."]
#        (nur Datum = ganztägig; ohne Ende +1 Stunde; Zeiten sind Ortszeit)
#   ... kalender.ps1 loeschen -Id "<id aus der Liste>"
param([Parameter(Mandatory = $true)][ValidateSet('status', 'liste', 'neu', 'loeschen')][string]$Aktion,
      [string]$Von, [string]$Bis, [string]$Titel, [string]$Start, [string]$Ende,
      [string]$Ort, [string]$Notiz, [string]$Kalender, [string]$Id)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$port = if ($env:ORB_PORT) { $env:ORB_PORT } else { 8766 }
$url = "http://127.0.0.1:$port"

$datei = if ([int]$port -eq 8766) { 'token.txt' } else { "token_$port.txt" }
try { $tok = (Get-Content "$env:LOCALAPPDATA\ORB\$datei" -Raw).Trim() }
catch { Write-Output '{"ok":false,"fehler":"ORB-Token nicht gefunden – läuft ORB?"}'; exit 1 }

function Rufe($methode, $pfad, $daten) {
    $p = @{ Uri = "$url$pfad"; Method = $methode; UseBasicParsing = $true; TimeoutSec = 60
            Headers = @{ 'X-ORB-Token' = $tok } }
    if ($daten) {
        $p.ContentType = 'application/json; charset=utf-8'
        $p.Body = [Text.Encoding]::UTF8.GetBytes(($daten | ConvertTo-Json -Compress))
    }
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
    'status' { $out = Rufe GET '/icloud' $null }
    'liste' {
        if (-not $Von) { $Von = (Get-Date).ToString('yyyy-MM-dd') }
        if (-not $Bis) { $Bis = ([datetime]$Von).AddDays(7).ToString('yyyy-MM-dd') }
        $out = Rufe POST '/kalender' @{ aktion = 'liste'; von = $Von; bis = $Bis }
    }
    'neu' {
        if (-not $Titel -or -not $Start) { $out = '{"ok":false,"fehler":"-Titel und -Start nötig"}'; break }
        $d = @{ aktion = 'neu'; titel = $Titel; start = $Start }
        foreach ($k in 'Ende', 'Ort', 'Notiz', 'Kalender') {
            $v = Get-Variable $k -ValueOnly
            if ($v) { $d[$k.ToLower()] = $v }
        }
        $out = Rufe POST '/kalender' $d
    }
    'loeschen' {
        if (-not $Id) { $out = '{"ok":false,"fehler":"-Id nötig (erst liste aufrufen)"}'; break }
        $out = Rufe POST '/kalender' @{ aktion = 'loeschen'; id = $Id }
    }
}
Write-Output $out
