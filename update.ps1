# ORB aktualisieren – IMMER so aufrufen, nachdem an ORB etwas geändert wurde:
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\update.ps1
# Ablauf: prüfen -> Version hochzählen -> ORB neu starten -> läuft er? -> Sicherung speichern.
# Startet die neue Version nicht, wird automatisch die letzte funktionierende Sicherung zurückgespielt.
# Es entsteht KEINE neue exe: ORB.exe auf dem Desktop lädt den Code aus diesem Ordner.
# Nur wenn orb_launcher.py selbst geändert wurde: zusätzlich -Exe angeben (ersetzt dieselbe ORB.exe).
# Protokoll: C:\Users\larse\Orb\update.log    Sicherungen: C:\Users\larse\Orb\Sicherungen
param([switch]$Losgeloest, [switch]$Exe)
$ErrorActionPreference = 'Stop'
$o    = 'C:\Users\larse\Orb'
$desk = [Environment]::GetFolderPath('Desktop')
$log  = "$o\update.log"
$bak  = "$o\Sicherungen"
$work = "$env:LOCALAPPDATA\ORB\build"
$CODE = 'server.py','orb_app.py','hook.py','index.html','tts.ps1','check.py','update.ps1','orb_launcher.py','orb.ico'
function Log($t) { $l = (Get-Date -Format 'HH:mm:ss') + '  ' + $t; Add-Content $log $l -Encoding UTF8; Write-Output $l }
function Ver { [regex]::Match((Get-Content "$o\server.py" -Raw -Encoding UTF8), '(?m)^VERSION = "(\d+)"').Groups[1].Value }
function Laeuft($v) { try { return (Invoke-RestMethod http://127.0.0.1:8766/version -TimeoutSec 2).version -eq $v } catch { return $false } }
function Beenden {
    try { Invoke-WebRequest http://127.0.0.1:8766/quit -Method Post -Body '{}' -ContentType 'application/json' -UseBasicParsing -TimeoutSec 3 | Out-Null } catch {}
    for ($i = 0; $i -lt 20; $i++) { Start-Sleep -Milliseconds 500; if (-not (Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue)) { break } }
    Get-Process ORB -ErrorAction SilentlyContinue | ForEach-Object { try { Stop-Process -Id $_.Id -Force } catch {} }
    Start-Sleep 1
}
function Starten($v) {
    Start-Process "$desk\ORB.exe"
    for ($i = 0; $i -lt 30; $i++) { Start-Sleep 1; if (Laeuft $v) { return $true } }
    return $false
}
function Ansage($t) {
    try { $b = [Text.Encoding]::UTF8.GetBytes((@{ text = $t } | ConvertTo-Json))
          Invoke-WebRequest http://127.0.0.1:8766/announce -Method Post -ContentType 'application/json; charset=utf-8' -Body $b -UseBasicParsing | Out-Null } catch {}
}

if (-not $Losgeloest) {
    Set-Content $log '' -Encoding UTF8
    Log 'Prüfe Code und Oberfläche …'
    $out = & py -3 "$o\check.py" 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Log "ABBRUCH – Fehler gefunden, die laufende Version bleibt:`n$out"; exit 1 }
    Log 'Prüfung ok.'
    $v = [int](Ver) + 1
    $s = Get-Content "$o\server.py" -Raw -Encoding UTF8
    [IO.File]::WriteAllText("$o\server.py", [regex]::Replace($s, '(?m)^VERSION = "\d+"', "VERSION = `"$v`""), (New-Object Text.UTF8Encoding $false))
    if ($Exe) {
        Log 'Baue den Starter (ORB.exe) neu …'
        New-Item -ItemType Directory -Force $work | Out-Null
        $ErrorActionPreference = 'Continue'
        $a = "-3 -m PyInstaller --noconfirm --onefile --windowed --name ORB --icon `"$o\orb.ico`" --exclude-module numpy " +
             "--collect-data sounddevice --collect-binaries sounddevice --collect-data certifi " +
             "--distpath `"$work\dist`" --workpath `"$work\tmp`" --specpath `"$work`" `"$o\orb_launcher.py`""
        Start-Process py -ArgumentList $a -Wait -WindowStyle Hidden -RedirectStandardError "$work\build.log" -RedirectStandardOutput "$work\build.out"
        $ErrorActionPreference = 'Stop'
        if (-not (Test-Path "$work\dist\ORB.exe") -or (Get-Item "$work\dist\ORB.exe").LastWriteTime -lt (Get-Date).AddMinutes(-3)) { Log 'ABBRUCH – Bauen fehlgeschlagen.'; exit 1 }
        Log 'Starter gebaut.'
    }
    Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`" -Losgeloest" + $(if ($Exe) { ' -Exe' } else { '' }) } | Out-Null
    Write-Output "Version $v ist geprüft. ORB startet in wenigen Sekunden neu und sagt Bescheid. Protokoll: $log"
    exit 0
}

# ---------- losgelöster Teil (überlebt den Neustart von ORB) ----------
try {
    Start-Sleep 2
    $v = Ver
    New-Item -ItemType Directory -Force $bak | Out-Null
    $kandidat = "$bak\Kandidat.zip"
    Compress-Archive -Path ($CODE | ForEach-Object { "$o\$_" } | Where-Object { Test-Path $_ }) -DestinationPath $kandidat -Force
    Log "Starte Version $v neu …"
    Beenden
    if ($Exe -and (Test-Path "$work\dist\ORB.exe")) { Copy-Item "$work\dist\ORB.exe" "$desk\ORB.exe" -Force; Log 'ORB.exe ersetzt (dieselbe Datei).' }
    if (Starten $v) {
        Move-Item $kandidat "$bak\ORB_v$v`_$(Get-Date -Format yyyy-MM-dd_HHmm).zip" -Force
        Get-ChildItem $bak -Filter 'ORB_v*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 15 | Remove-Item -Force
        Log "Version $v läuft. Sicherung gespeichert."
        Ansage "Update fertig, Version $v läuft."
    } else {
        Log "FEHLER – Version $v startet nicht. Spiele letzte funktionierende Sicherung zurück …"
        $gut = Get-ChildItem $bak -Filter 'ORB_v*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($gut) {
            Expand-Archive $gut.FullName -DestinationPath $o -Force
            Beenden
            Start-Process "$desk\ORB.exe"; Start-Sleep 8
            Log ("Zurückgesetzt auf " + $gut.Name)
            Ansage "Das Update hat nicht geklappt. Ich habe die letzte funktionierende Version wiederhergestellt."
        } else { Log 'Keine Sicherung vorhanden.' }
        Remove-Item $kandidat -Force -ErrorAction SilentlyContinue
    }
    Get-ChildItem $desk -Filter 'ORB_alt*.exe' -Force | ForEach-Object { try { Remove-Item $_.FullName -Force } catch {} }
    Log 'Fertig.'
} catch { Log ("FEHLER: " + $_.Exception.Message) }
