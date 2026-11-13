# Stellt die ORB.exe als Download auf GitHub bereit (Release „installer“, immer dieselbe Datei wird ersetzt).
# Nutzt die GitHub-Anmeldung, die Git bereits gespeichert hat.
param([string]$Datei)
$ErrorActionPreference = 'Stop'
$repo = 'Larsen140/ORB'
$git = 'C:\Program Files\Git\cmd\git.exe'
$cred = "protocol=https`nhost=github.com`n`n" | & $git credential fill 2>$null
$token = ($cred | Where-Object { $_ -like 'password=*' }) -replace '^password=', ''
if (-not $token) { Write-Output 'Keine GitHub-Anmeldung gefunden – Release übersprungen.'; exit 1 }
$h = @{ Authorization = "Bearer $token"; Accept = 'application/vnd.github+json'; 'User-Agent' = 'ORB' }
try { $rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/tags/installer" -Headers $h }
catch {
    $body = @{ tag_name = 'installer'; name = 'ORB – Installer'; target_commitish = 'main'
               body = "ORB.exe herunterladen und starten. ORB installiert sich selbst und holt sich Updates automatisch von GitHub." } | ConvertTo-Json
    $rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases" -Method Post -Headers $h -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json'
}
foreach ($a in $rel.assets) { if ($a.name -eq 'ORB.exe') { Invoke-RestMethod $a.url -Method Delete -Headers $h | Out-Null } }
$up = ($rel.upload_url -replace '\{.*\}$', '') + '?name=ORB.exe'
Invoke-RestMethod $up -Method Post -Headers $h -InFile $Datei -ContentType 'application/octet-stream' | Out-Null
Write-Output "Installer bereit: https://github.com/$repo/releases/download/installer/ORB.exe"
