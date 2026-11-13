# ORB aktualisieren – IMMER so aufrufen, nachdem im Entwicklungsordner C:\Users\larse\Orb etwas geändert wurde:
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\update.ps1
# Ablauf: prüfen -> Version hochzählen -> zu GitHub hochladen -> ORB holt sich das Update und startet neu
#         -> läuft er? sonst automatisch zurück auf die letzte Sicherung.
# Es entsteht KEINE neue exe. Nur wenn orb_launcher.py geändert wurde: -Exe anhängen (baut den Installer neu
# und stellt ihn als GitHub-Release „ORB.exe“ bereit).
# Protokoll: C:\Users\larse\Orb\update.log
param([switch]$Exe)
$ErrorActionPreference = 'Stop'
$o    = 'C:\Users\larse\Orb'
$git  = 'C:\Program Files\Git\cmd\git.exe'
$log  = "$o\update.log"
$work = "$env:LOCALAPPDATA\ORB\build"
$inst = "$env:LOCALAPPDATA\ORB\ORB.exe"
function Log($t) { $l = (Get-Date -Format 'HH:mm:ss') + '  ' + $t; Add-Content $log $l -Encoding UTF8; Write-Output $l }
function Ver { [regex]::Match((Get-Content "$o\server.py" -Raw -Encoding UTF8), '(?m)^VERSION = "(\d+)"').Groups[1].Value }
function LaufendeVer { try { return (Invoke-RestMethod http://127.0.0.1:8766/version -TimeoutSec 2).version } catch { return $null } }
function Git { $ErrorActionPreference = 'Continue'; $r = & $git -C $o @args 2>&1 | Out-String; $code = $LASTEXITCODE; $ErrorActionPreference = 'Stop'; if ($code -ne 0) { throw "git $($args -join ' '): $r" }; $r }
$tokHdr = @{ 'X-ORB-Token' = (Get-Content "$env:LOCALAPPDATA\ORB\token.txt" -ErrorAction SilentlyContinue) }
function Ansage($t) {
    try { $b = [Text.Encoding]::UTF8.GetBytes((@{ text = $t } | ConvertTo-Json))
          Invoke-WebRequest http://127.0.0.1:8766/announce -Method Post -Headers $tokHdr -ContentType 'application/json; charset=utf-8' -Body $b -UseBasicParsing | Out-Null } catch {}
}
Set-Content $log '' -Encoding UTF8
try {
    Log 'Prüfe Code und Oberfläche …'
    $ErrorActionPreference = 'Continue'   # Warnungen auf stderr sind kein Abbruchgrund
    $out = & py -3 "$o\check.py" 2>&1 | Out-String
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { Log "ABBRUCH – Fehler gefunden, nichts wurde geändert:`n$out"; exit 1 }
    Log 'Prüfung ok.'

    $v = [int](Ver) + 1
    $s = Get-Content "$o\server.py" -Raw -Encoding UTF8
    [IO.File]::WriteAllText("$o\server.py", [regex]::Replace($s, '(?m)^VERSION = "\d+"', "VERSION = `"$v`""), (New-Object Text.UTF8Encoding $false))

    Log "Lade Version $v zu GitHub hoch …"
    Git add -A | Out-Null
    Git commit -q -m "ORB Version $v" | Out-Null
    try { Git push -q origin main | Out-Null } catch { Git pull -q --rebase origin main | Out-Null; Git push -q origin main | Out-Null }
    Log 'Hochgeladen.'

    if ($Exe) {
        Log 'Baue den Installer (ORB.exe) neu …'
        New-Item -ItemType Directory -Force $work | Out-Null
        $ErrorActionPreference = 'Continue'
        # ORB-Code (orb_app/server/hook) darf NICHT in die exe – sonst läuft immer der alte Stand statt dem von GitHub
        $a = "-3 -m PyInstaller --noconfirm --onefile --windowed --name ORB --icon `"$o\orb.ico`" --exclude-module numpy " +
             "--exclude-module orb_app --exclude-module server --exclude-module hook --exclude-module check " +
             "--collect-data sounddevice --collect-binaries sounddevice --collect-data certifi --collect-submodules edge_tts " +
             "--distpath `"$work\dist`" --workpath `"$work\tmp`" --specpath `"$work`" `"$o\orb_launcher.py`""
        Start-Process py -ArgumentList $a -Wait -WindowStyle Hidden -RedirectStandardError "$work\build.log" -RedirectStandardOutput "$work\build.out"
        $ErrorActionPreference = 'Stop'
        if (-not (Test-Path "$work\dist\ORB.exe") -or (Get-Item "$work\dist\ORB.exe").LastWriteTime -lt (Get-Date).AddMinutes(-3)) { throw 'Bauen fehlgeschlagen' }
        & powershell -NoProfile -ExecutionPolicy Bypass -File "$o\release.ps1" "$work\dist\ORB.exe" | ForEach-Object { Log $_ }
    }

    if (-not (LaufendeVer)) {
        Log 'ORB läuft nicht – starte ihn mit dem neuen Stand.'
        if (($Exe -or -not (Test-Path $inst)) -and (Test-Path "$work\dist\ORB.exe")) {
            New-Item -ItemType Directory -Force (Split-Path $inst) | Out-Null
            Copy-Item "$work\dist\ORB.exe" $inst -Force
        }
        if (-not (Test-Path $inst)) { throw "ORB ist nicht installiert ($inst fehlt) – update.ps1 -Exe ausführen" }
        Start-Process $inst -ArgumentList '--hintergrund','--update'
    } else {
        Log 'Sage ORB, dass er sich aktualisieren soll …'
        if ($Exe -and (Test-Path "$work\dist\ORB.exe")) {
            # neuer Starter: ORB beenden, Starter ersetzen, neu starten
            try { Invoke-WebRequest http://127.0.0.1:8766/quit -Method Post -Headers $tokHdr -Body '{}' -UseBasicParsing -TimeoutSec 3 | Out-Null } catch {}
            Start-Sleep 3; Get-Process ORB -ErrorAction SilentlyContinue | ForEach-Object { try { Stop-Process -Id $_.Id -Force } catch {} }; Start-Sleep 1
            Copy-Item "$work\dist\ORB.exe" $inst -Force
            Start-Process $inst -ArgumentList '--neustart','--update'
        } else {
            $sha = (Git rev-parse HEAD).Trim()
            Invoke-WebRequest http://127.0.0.1:8766/selfupdate -Method Post -Headers $tokHdr -Body (@{ sha = $sha } | ConvertTo-Json) -ContentType 'application/json' -UseBasicParsing -TimeoutSec 5 | Out-Null
        }
    }
    # Nicht warten: ORB holt sich den Stand selbst (spätestens nach einer Minute), sichert vorher
    # und setzt sich bei einem Fehler beim Start automatisch auf die letzte Sicherung zurück.
    Log "Version $v ist auf GitHub. ORB spielt sie gleich selbst ein und sagt Bescheid."
} catch { Log ("FEHLER: " + $_.Exception.Message); exit 1 }
