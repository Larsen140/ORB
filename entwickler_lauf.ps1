# Wird von entwickler.ps1 losgelöst gestartet: lässt Claude Code den Auftrag umsetzen.
param([string]$Art = 'orb')
$o    = 'C:\Users\larse\Orb'
$job  = "$env:LOCALAPPDATA\ORB\entwickler\$Art"
$log  = "$job\protokoll.txt"
$auftrag = [IO.File]::ReadAllText("$job\auftrag.txt", [Text.Encoding]::UTF8)
function Ansage($t) {
    try { $b = [Text.Encoding]::UTF8.GetBytes((@{ text = $t } | ConvertTo-Json))
          Invoke-WebRequest http://127.0.0.1:8766/announce -Method Post -ContentType 'application/json; charset=utf-8' -Body $b -UseBasicParsing | Out-Null } catch {}
}
if ($Art -eq 'projekt') {
    $ordner = 'C:\Users\larse\Projekte'
    $regeln = @"
Du bist Larsens Entwickler für große Aufgaben: Apps, Websites, Spiele, Programme, Skripte.
Arbeite in einem passenden Unterordner von C:\Users\larse\Projekte (kurzer, sprechender Ordnername; anlegen, falls neu –
gibt es schon ein passendes Projekt, arbeite dort weiter).
Regeln:
- Baue das Projekt vollständig und lauffähig, mit modernem, schönem Design. Teste es selbst (z. B. Seite laden, Skript ausführen).
- Larsens Vorlieben: alles auf Deutsch; keine Figuren/Namen/Grafiken aus bekannten Serien oder Spielen – nur eigene Designs.
- Lege eine kurze Projektnotiz an: C:\Users\larse\Documents\Jarvis\projekte\<name>.md (Ziel, Ordner, Stand, wie starten, nächste Ideen).
- Ist das Ergebnis im Browser anzusehen (Website, Web-App, Spiel), öffne es am Ende mit Start-Process.
- Veröffentliche nur, wenn der Auftrag es ausdrücklich verlangt. Keine privaten Daten (Schlüssel, Mailadressen) in öffentliche Dateien.
- Nichts an ORB selbst (C:\Users\larse\Orb, ORB.exe) ändern.
- Deine letzte Antwort wird Larsen laut vorgelesen: EIN kurzer deutscher Satz, was fertig ist und wo er es findet.
"@
} else {
    $ordner = $o
    $regeln = @"
Du bist der Entwickler von ORB, Larsens persönlichem Sprachassistenten (Windows, Python-Server + HTML/WebGL-Oberfläche).
Arbeitsordner: C:\Users\larse\Orb (Git-Repo Larsen140/ORB, öffentlich). Lies zuerst README.md, um den Aufbau zu verstehen.
Regeln:
- Setze den Auftrag vollständig und sauber um, passend zum bestehenden Design (Liquid-Glass, Palette mit --c/--c2/--c3/--c4).
- Ändere nur, was für den Auftrag nötig ist. Keine privaten Daten (Schlüssel, Mailadressen) in den Code – das Repo ist öffentlich.
- Prüfe mit:  py -3 check.py   (muss „OK“ ausgeben; Fehler beheben).
- Veröffentliche danach mit:  powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\update.ps1
  (nur wenn orb_launcher.py geändert wurde, zusätzlich -Exe). ORB spielt das Update dann selbst ein.
- NIEMALS selbst PyInstaller ausführen, exe-Dateien bauen/kopieren oder ORB beenden/starten. Nicht auf ORB warten.
- Ist der Auftrag unklar oder würde er ORB beschädigen, setze die sinnvollste kleine Version um.
- Deine letzte Antwort wird Larsen laut vorgelesen: EIN kurzer deutscher Satz, was jetzt neu ist (ohne Dateinamen/Technik).
"@
}
New-Item -ItemType Directory -Force $ordner | Out-Null
$env:ORB_RUN = '1'   # Antworten des Entwicklers nicht als ORB-Gespräch vorlesen
foreach ($k in 'ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','ANTHROPIC_BASE_URL') { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { $claude = "$env:USERPROFILE\.local\bin\claude.exe" }
Set-Location $ordner
"=== $(Get-Date -Format 'dd.MM.yyyy HH:mm') Auftrag: $auftrag" | Add-Content $log -Encoding UTF8
try {
    $out = $auftrag | & $claude -p --output-format json --model claude-opus-5-5 --permission-mode auto --append-system-prompt $regeln 2>>$log
    $res = ($out | Out-String | ConvertFrom-Json)
    $satz = ("$($res.result)" -split "`n" | Where-Object { $_.Trim() } | Select-Object -Last 1).Trim()
    "Ergebnis: $($res.result)" | Add-Content $log -Encoding UTF8
    if ($res.is_error -or -not $satz) { Ansage 'Der Entwickler ist mit deinem Auftrag nicht fertig geworden. Details stehen im Entwickler-Protokoll.' }
    else { Ansage ("Entwickler fertig: " + $satz) }
} catch {
    "FEHLER: $($_.Exception.Message)" | Add-Content $log -Encoding UTF8
    Ansage 'Beim Entwickler ist etwas schiefgelaufen.'
} finally {
    Remove-Item "$job\laeuft.txt" -ErrorAction SilentlyContinue
}
