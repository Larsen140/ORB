# iCloud-Kontakte über ORB – für Claude (liest den ORB-Token selbst, er wird nie ausgegeben).
# Gibt nie das ganze Adressbuch aus, nur passende Einträge (höchstens 10).
#   ... kontakte.ps1 suche -Text "Anna"                       → Treffer nach Name, Firma, E-Mail oder Telefonnummer
#   ... kontakte.ps1 neu -Name "Anna Muster" [-Telefon "0170 1234567"] [-Email "anna@example.org"]
#        [-Firma ".."] [-Adresse "Straße 1, 12345 Stadt"] [-Geburtstag 1990-05-01] [-Notiz ".."]
#        (mehrere Nummern/Adressen mit Komma trennen)
#   ... kontakte.ps1 aendern -Id "<id aus suche>" [-Name ..] [-Telefon ..] [-Email ..] [-Firma ..] [-Adresse ..]
#        [-Geburtstag ..] [-Notiz ..] [-Dazu]   (angegebene Felder werden ersetzt; -Dazu ergänzt Telefon/E-Mail)
#   ... kontakte.ps1 loeschen -Id "<id>" -Bestaetigt          → NUR nach Larsens ausdrücklicher Zustimmung
param([Parameter(Mandatory = $true)][ValidateSet('suche', 'neu', 'aendern', 'loeschen')][string]$Aktion,
      [string]$Text, [string]$Id, [string]$Name, [string]$Telefon, [string]$Email, [string]$Firma,
      [string]$Adresse, [string]$Geburtstag, [string]$Notiz, [switch]$Dazu, [switch]$Bestaetigt)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$port = if ($env:ORB_PORT) { $env:ORB_PORT } else { 8766 }
$url = "http://127.0.0.1:$port"

$datei = if ([int]$port -eq 8766) { 'token.txt' } else { "token_$port.txt" }
try { $tok = (Get-Content "$env:LOCALAPPDATA\ORB\$datei" -Raw).Trim() }
catch { Write-Output '{"ok":false,"fehler":"ORB-Token nicht gefunden – läuft ORB?"}'; exit 1 }

function Rufe($daten) {
    $p = @{ Uri = "$url/kontakte"; Method = 'POST'; UseBasicParsing = $true; TimeoutSec = 90
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

function Felder($d) {
    foreach ($k in 'Name', 'Telefon', 'Email', 'Firma', 'Adresse', 'Geburtstag', 'Notiz') {
        $v = Get-Variable $k -ValueOnly
        if ($v) { $d[$k.ToLower()] = $v }
    }
    return $d
}

switch ($Aktion) {
    'suche' {
        if (-not $Text) { $out = '{"ok":false,"fehler":"-Text nötig (Name, Firma, E-Mail oder Nummer)"}'; break }
        $out = Rufe @{ aktion = 'suche'; text = $Text }
    }
    'neu' {
        if (-not $Name) { $out = '{"ok":false,"fehler":"-Name nötig"}'; break }
        $out = Rufe (Felder @{ aktion = 'neu' })
    }
    'aendern' {
        if (-not $Id) { $out = '{"ok":false,"fehler":"-Id nötig (erst suche aufrufen)"}'; break }
        $out = Rufe (Felder @{ aktion = 'aendern'; id = $Id; dazu = [bool]$Dazu })
    }
    'loeschen' {
        if (-not $Id) { $out = '{"ok":false,"fehler":"-Id nötig (erst suche aufrufen)"}'; break }
        if (-not $Bestaetigt) { $out = '{"ok":false,"fehler":"Erst Larsen fragen; nach seiner Zustimmung mit -Bestaetigt aufrufen"}'; break }
        $out = Rufe @{ aktion = 'loeschen'; id = $Id; bestaetigt = $true }
    }
}
Write-Output $out
