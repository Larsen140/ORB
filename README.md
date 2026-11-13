# ORB
Mein eigener Jarvis – ein persönlicher Sprachassistent für Windows: eine flüssige 3D-Kugel, mit der man spricht.
Das Gehirn ist Claude (Opus) über das eigene Claude-Code-Abo.

## Installieren
**[ORB.exe herunterladen](https://github.com/Larsen140/ORB/releases/download/installer/ORB.exe)** und starten.
ORB installiert sich selbst (Desktop, Startmenü, Autostart), lädt seinen Code von hier und holt sich
**Updates automatisch** von GitHub. Vor jedem Update wird gesichert – klappt ein Update nicht, setzt ORB sich selbst zurück.

Voraussetzung für Antworten: [Claude Code](https://claude.com/claude-code) installiert und angemeldet.

## Was ORB kann
- **Wecken mit Doppelklatschen** – auch direkt nach dem PC-Start (lauscht unsichtbar im Hintergrund, ~70 MB).
- **Gespräch**: hört dauerhaft zu, bis man „Stopp“ sagt; „Jarvis“ unterbricht ihn.
- **Antwortet laut** auf Deutsch (Microsoft-Neural-Stimmen), Satz für Satz, während die Antwort entsteht.
- **Apps & Webseiten öffnen**, Wetter, Termine, Spotify-Steuerung – ohne Token.
- **iCloud-Kalender**: Termine eintragen, lesen und löschen (Einstellungen → iCloud-Kalender, app-spezifisches Passwort).
- **Oberfläche** im Liquid-Glass-Stil mit Uhr, Gesprächsverlauf, System, Wetter, Termine, Spotify und Vorschlägen.
- **Bild-Hologramme**: neue Bilder in `Bilder/ORB Bilder` (oder per `bild_zeigen.ps1`) erscheinen sofort als Holo-Karte.
- **Wissensbasis**: arbeitet im Ordner `Documents\Jarvis` und merkt sich dort alles.

## Aufbau
| Datei | Aufgabe |
|---|---|
| `orb_launcher.py` | wird zur einzigen `ORB.exe`: installiert, lädt Code von GitHub, aktualisiert, setzt bei Fehlern zurück |
| `orb_app.py` | Start, Fenster, Klatsch-Erkennung im Hintergrund, Autostart, Update-Prüfung |
| `server.py` | lokaler Server: Zustand, Stimme, Claude-Anbindung, Wetter, Apps, Termine, Spotify |
| `icloud.py` | iCloud-Kalender über CalDAV (Zugang in der Windows-Anmeldeinformationsverwaltung) |
| `hook.py` | Claude-Code-Hooks → zeigt in ORB an, was Claude gerade tut |
| `index.html` | Oberfläche (WebGL-Kugel, Effekte, Sounds, Einstellungen) |
| `whatsapp.ps1` | WhatsApp-Nachricht (Text/Bild) in Sekunden vorbereiten, Abschicken erst nach Bestätigung |
| `check.py` | prüft Code und Oberfläche vor jedem Update |
| `update.ps1` | prüfen → hochladen → ORB aktualisiert sich → Kontrolle (bei Fehler automatisch zurück) |
| `release.ps1` | stellt die ORB.exe als Download bereit |
| `zuruecksetzen.ps1` | auf die letzte Sicherung zurücksetzen |

## Entwickeln
Im Entwicklungsordner ändern, dann:
```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\larse\Orb\update.ps1
```
Es entsteht **keine neue exe**. Nur wenn `orb_launcher.py` geändert wurde, `-Exe` anhängen.

Private Daten (`config.json`, `state.json`, Schlüssel, Protokolle) bleiben in `%USERPROFILE%\Orb` und werden nie hochgeladen.
