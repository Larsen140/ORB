# Der Entwickler meldet hiermit seinen Fortschritt; ORB zeigt ihn als Balken mit Prozent im Entwickler-Hologramm.
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\fortschritt.ps1 40 "Bauen"
param([Parameter(Mandatory = $true)][int]$Prozent, [string]$Schritt = '')
$art = if ($env:ORB_DEV_ART) { $env:ORB_DEV_ART } else { 'orb' }
$job = "$env:LOCALAPPDATA\ORB\entwickler\$art"
New-Item -ItemType Directory -Force $job | Out-Null
$json = @{ prozent = [Math]::Max(0, [Math]::Min(100, $Prozent)); schritt = $Schritt; zeit = (Get-Date -Format s) } | ConvertTo-Json -Compress
[IO.File]::WriteAllText("$job\fortschritt.json", $json, (New-Object Text.UTF8Encoding $false))
Write-Output "Fortschritt: $Prozent % $Schritt"
