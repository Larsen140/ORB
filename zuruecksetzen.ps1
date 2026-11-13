# ORB auf die letzte funktionierende Sicherung zurücksetzen und neu starten.
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\zuruecksetzen.ps1
# Sicherungen liegen in %LOCALAPPDATA%\ORB\Sicherungen (vor jedem Update automatisch angelegt).
$inst = "$env:LOCALAPPDATA\ORB\ORB.exe"
$cmd = "try { Invoke-WebRequest http://127.0.0.1:8766/quit -Method Post -Body '{}' -UseBasicParsing -TimeoutSec 3 | Out-Null } catch {}; " +
       "Start-Sleep 3; Get-Process ORB -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 1; " +
       "Start-Process '$inst' -ArgumentList '--neustart','--zurueck'"
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = "powershell -NoProfile -WindowStyle Hidden -Command `"$cmd`"" } | Out-Null
Write-Output 'ORB wird auf die letzte Sicherung zurückgesetzt und startet neu.'
