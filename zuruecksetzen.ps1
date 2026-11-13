# ORB auf eine Sicherung zurücksetzen (Standard: die neueste).
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\zuruecksetzen.ps1            -> neueste Sicherung
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\zuruecksetzen.ps1 -Liste     -> Sicherungen anzeigen
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\zuruecksetzen.ps1 -Name ORB_v12_2026-11-13_0230.zip
param([switch]$Liste, [string]$Name)
$o = 'C:\Users\larse\Orb'; $bak = "$o\Sicherungen"; $desk = [Environment]::GetFolderPath('Desktop')
$alle = Get-ChildItem $bak -Filter 'ORB_v*.zip' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
if ($Liste) { $alle | ForEach-Object { $_.Name }; exit 0 }
$z = if ($Name) { $alle | Where-Object Name -eq $Name } else { $alle | Select-Object -First 1 }
if (-not $z) { Write-Output 'Keine passende Sicherung gefunden.'; exit 1 }
# Neustart losgelöst, damit er das Beenden von ORB überlebt
$cmd = "Expand-Archive '$($z.FullName)' -DestinationPath '$o' -Force; " +
       "try { Invoke-WebRequest http://127.0.0.1:8766/quit -Method Post -Body '{}' -UseBasicParsing -TimeoutSec 3 | Out-Null } catch {}; " +
       "Start-Sleep 3; Get-Process ORB -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 1; Start-Process '$desk\ORB.exe'"
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = "powershell -NoProfile -WindowStyle Hidden -Command `"$cmd`"" } | Out-Null
Write-Output "Setze ORB auf $($z.Name) zurück und starte neu."
