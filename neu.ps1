# Der Entwickler hinterlegt hiermit die kleine Einführung „Was ist neu?“ – VOR dem Veröffentlichen aufrufen.
# ORB zeigt sie nach dem Laden des Updates (bzw. wenn das Projekt fertig ist) 30 s als kleines Hologramm und liest den ersten Punkt vor.
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\neu.ps1 -Punkte "Goldkurs live|Kurve läuft mit" -Nutzen "Sag: Jarvis, Gold"
param([Parameter(Mandatory = $true)][string]$Punkte, [string]$Nutzen = '')
$art = if ($env:ORB_DEV_ART -eq 'projekt') { 'projekt' } else { 'orb' }
$job = "$env:LOCALAPPDATA\ORB\entwickler\$art"
New-Item -ItemType Directory -Force $job | Out-Null
$liste = @($Punkte -split '\|' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -First 4)
if (-not $liste) { Write-Output 'Keine Punkte angegeben.'; exit 1 }
$json = @{ punkte = $liste; nutzen = $Nutzen.Trim(); zeit = (Get-Date -Format s) } | ConvertTo-Json -Compress
[IO.File]::WriteAllText("$job\neu.json", $json, (New-Object Text.UTF8Encoding $false))
Write-Output "Einführung hinterlegt ($($liste.Count) Punkte)."
