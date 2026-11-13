# Gibt einen Änderungswunsch für ORB an einen eigenen Claude-Code-Entwickler weiter (läuft im Hintergrund).
# Aufruf (z. B. durch ORBs Gehirn):
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\entwickler.ps1 "Bau ein Widget für …"
# Der Entwickler arbeitet im Entwicklungsordner, prüft, veröffentlicht über update.ps1 und ORB sagt am Ende Bescheid.
param([Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Auftrag)
$o    = 'C:\Users\larse\Orb'
$job  = "$env:LOCALAPPDATA\ORB\entwickler"
New-Item -ItemType Directory -Force $job | Out-Null
$lock = "$job\laeuft.txt"
if ((Test-Path $lock) -and ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalMinutes -lt 30) {
    Write-Output 'Der Entwickler arbeitet gerade noch an einem anderen Auftrag. Bitte gleich nochmal.'
    exit 1
}
$text = ($Auftrag -join ' ').Trim()
[IO.File]::WriteAllText("$job\auftrag.txt", $text, (New-Object Text.UTF8Encoding $false))
Set-Content $lock (Get-Date -Format s)
# losgelöst starten, damit es weiterläuft, auch wenn ORBs Gehirn fertig ist
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$o\entwickler_lauf.ps1`"" } | Out-Null
Write-Output 'Auftrag ist beim Entwickler. ORB sagt Bescheid, sobald es fertig und eingespielt ist.'
