# Startet eine Hintergrund-Aufgabe in ORB (eigenes Claude, eigenes Hologramm). ORB sagt das Ergebnis an.
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\aufgabe.ps1 "Kurzer Titel" "Vollständiger Auftrag"
param([Parameter(Mandatory = $true)][string]$Titel, [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Auftrag)
$tok = (Get-Content "$env:LOCALAPPDATA\ORB\token.txt" -ErrorAction SilentlyContinue)
$body = [Text.Encoding]::UTF8.GetBytes((@{ aktion = 'start'; titel = $Titel; auftrag = ($Auftrag -join ' ') } | ConvertTo-Json))
try {
    Invoke-WebRequest http://127.0.0.1:8766/aufgabe -Method Post -Headers @{ 'X-ORB-Token' = $tok } -ContentType 'application/json; charset=utf-8' -Body $body -UseBasicParsing | Out-Null
    Write-Output 'Aufgabe läuft im Hintergrund (eigenes Hologramm). ORB sagt das Ergebnis an – du musst nicht warten.'
} catch { Write-Output "Konnte die Aufgabe nicht starten: $($_.Exception.Message)" }
