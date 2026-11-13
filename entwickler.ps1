# Gibt einen großen Auftrag an einen eigenen Claude-Code-Entwickler weiter (läuft im Hintergrund).
#   ORB selbst ändern:      powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\entwickler.ps1 "Bau ein Widget für …"
#   Großes Projekt bauen:   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\entwickler.ps1 -Projekt "Bau mir eine Website für …"
# Der Entwickler arbeitet selbstständig, testet, und ORB sagt am Ende Bescheid.
param([switch]$Projekt, [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Auftrag)
$o    = 'C:\Users\larse\Orb'
$art  = if ($Projekt) { 'projekt' } else { 'orb' }
$job  = "$env:LOCALAPPDATA\ORB\entwickler\$art"
New-Item -ItemType Directory -Force $job | Out-Null
$lock = "$job\laeuft.txt"
if ((Test-Path $lock) -and ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalMinutes -lt 60) {
    Write-Output 'Der Entwickler arbeitet gerade noch an einem anderen Auftrag dieser Art. Bitte etwas später nochmal.'
    exit 1
}
$text = ($Auftrag -join ' ').Trim()
[IO.File]::WriteAllText("$job\auftrag.txt", $text, (New-Object Text.UTF8Encoding $false))
Set-Content $lock (Get-Date -Format s)
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$o\entwickler_lauf.ps1`" -Art $art" } | Out-Null
Write-Output 'Auftrag ist beim Entwickler. ORB sagt Bescheid, sobald es fertig ist.'
