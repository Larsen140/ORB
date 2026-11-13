# Wird von entwickler.ps1 losgelöst gestartet: lässt Claude Code den Auftrag umsetzen.
param([string]$Art = 'orb')
# Umlaute sauber an Claude übergeben und zurücklesen (Windows PowerShell nutzt sonst ASCII/OEM)
$OutputEncoding = [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false
$o    = 'C:\Users\larse\Orb'
$job  = "$env:LOCALAPPDATA\ORB\entwickler\$Art"
$log  = "$job\protokoll.txt"
$auftrag = [IO.File]::ReadAllText("$job\auftrag.txt", [Text.Encoding]::UTF8)
$tokHdr = @{ 'X-ORB-Token' = (Get-Content "$env:LOCALAPPDATA\ORB\token.txt" -ErrorAction SilentlyContinue) }
function Ansage($t) {
    try { $b = [Text.Encoding]::UTF8.GetBytes((@{ text = $t } | ConvertTo-Json))
          Invoke-WebRequest http://127.0.0.1:8766/announce -Method Post -Headers $tokHdr -ContentType 'application/json; charset=utf-8' -Body $b -UseBasicParsing | Out-Null } catch {}
}
# Eigenes Hologramm in ORB: Fortschritt live melden
$tid = "dev-$Art"
function Melde($status, $schritt, $ergebnis) {
    try { $h = @{ aktion = 'melde'; id = $tid; art = 'entwickler'; status = $status }
          if ($schritt) { $h.schritt = $schritt }; if ($ergebnis) { $h.ergebnis = $ergebnis }
          if ($status -eq 'laeuft' -and -not $schritt) { $h.titel = $(if ($Art -eq 'projekt') { 'Projekt-Entwickler' } else { 'ORB-Entwickler' }) }
          $b = [Text.Encoding]::UTF8.GetBytes(($h | ConvertTo-Json))
          Invoke-WebRequest http://127.0.0.1:8766/aufgabe -Method Post -Headers $tokHdr -ContentType 'application/json; charset=utf-8' -Body $b -UseBasicParsing -TimeoutSec 3 | Out-Null } catch {}
}
Melde 'laeuft' $null $null
Melde 'laeuft' ('Auftrag: ' + $(if ($auftrag.Length -gt 70) { $auftrag.Substring(0, 70) + ' …' } else { $auftrag })) $null
$labels = @{ Read = 'Liest'; Edit = 'Bearbeitet'; Write = 'Schreibt'; MultiEdit = 'Bearbeitet'; Bash = 'Befehl'; PowerShell = 'Befehl'; Grep = 'Sucht'; Glob = 'Sucht Dateien'; WebSearch = 'Recherchiert'; WebFetch = 'Liest Webseite'; Task = 'Helfer'; Agent = 'Helfer' }
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
$env:ORB_RUN = '1'; $env:ORB_BG = '1'   # Antworten des Entwicklers nicht als ORB-Gespräch vorlesen
foreach ($k in 'ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','ANTHROPIC_BASE_URL') { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { $claude = "$env:USERPROFILE\.local\bin\claude.exe" }
Set-Location $ordner
"=== $(Get-Date -Format 'dd.MM.yyyy HH:mm') Auftrag: $auftrag" | Add-Content $log -Encoding UTF8
try {
    $res = $null
    $auftrag | & $claude -p --output-format stream-json --verbose --model claude-opus-5-5 --permission-mode auto --append-system-prompt $regeln 2>>$log | ForEach-Object {
        try { $o = $_ | ConvertFrom-Json } catch { return }
        if ($o.type -eq 'assistant') {
            foreach ($c in $o.message.content) {
                if ($c.type -eq 'tool_use') {
                    $lab = $labels[$c.name]; if (-not $lab) { $lab = $c.name }
                    $det = "$($c.input.description)$($c.input.file_path)$($c.input.pattern)$($c.input.query)"
                    if ($det.Length -gt 60) { $det = '…' + $det.Substring($det.Length - 60) }
                    Melde 'laeuft' ("$lab" + $(if ($det) { ": $det" } else { '' })) $null
                }
            }
        } elseif ($o.type -eq 'result') { $res = $o }
    }
    $satz = ("$($res.result)" -split "`n" | Where-Object { $_.Trim() } | Select-Object -Last 1).Trim()
    "Ergebnis: $($res.result)" | Add-Content $log -Encoding UTF8
    if (-not $res -or $res.is_error -or -not $satz) { Melde 'fehler' $null 'Nicht fertig geworden – siehe Protokoll.'; Ansage 'Der Entwickler ist mit deinem Auftrag nicht fertig geworden. Details stehen im Entwickler-Protokoll.' }
    else { Melde 'fertig' $null $satz; Ansage ("Entwickler fertig: " + $satz) }
} catch {
    "FEHLER: $($_.Exception.Message)" | Add-Content $log -Encoding UTF8
    Melde 'fehler' $null 'Fehler – siehe Protokoll.'
    Ansage 'Beim Entwickler ist etwas schiefgelaufen.'
} finally {
    Remove-Item "$job\laeuft.txt" -ErrorAction SilentlyContinue
}
