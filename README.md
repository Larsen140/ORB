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
- **Antwortet laut** auf Deutsch (Microsoft-Neural-Stimmen), Satz für Satz, während die Antwort entsteht – jede Stimme auf einheitlich −14 LUFS normalisiert, mit Klang-EQ, Limiter und gekürzten Pausen (Lautstärke bis 300 %, ORB im Windows-Mixer immer auf 100 %).
- **Apps & Webseiten öffnen**, Wetter, Termine, Spotify-Steuerung – ohne Token.
- **iCloud-Kalender**: Termine eintragen, lesen und löschen (Einstellungen → iCloud-Kalender, app-spezifisches Passwort).
- **Oberfläche** im Liquid-Glass-Stil mit Uhr, Gesprächsverlauf, System, Wetter, Termine, Spotify und Vorschlägen.
- **Bild-Hologramme**: neue Bilder in `Bilder/ORB Bilder` (oder per `bild_zeigen.ps1`) erscheinen sofort als Holo-Karte.
- **Web-Hologramme**: echte Webseiten zum Klicken, Scrollen und Tippen direkt im Hologramm (`web_zeigen.ps1`).
- **Echte Farben**: Schalter im Bild-/Web-Hologramm (oder `-Rein` an `bild_zeigen.ps1`/`web_zeigen.ps1`) zeigt den Inhalt ohne Hologramm-Effekte; die Bild-Werkstatt (Port 8790) startet immer so.
- **Gold live** („Jarvis, Gold“): XAU/USD jede Sekunde, mit Farbblitz pro Tick und mitlaufender Kurve.
- **Was ist neu?**: nach jedem Update (ORB oder Projekt) erscheint kurz ein kleines Hologramm mit den Neuerungen und wie man sie benutzt.
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
| `neu.ps1` | Entwickler hinterlegt die Einführung „Was ist neu?“ (2–4 Punkte + wie benutzen) – ORB zeigt sie nach dem Update 30 s als kleines Hologramm und liest den ersten Punkt vor |
| `fortschritt.ps1` | Entwickler meldet seinen Fortschritt (Prozent + Schritt) – ORB zeigt ihn als Balken im Entwickler-Hologramm |
| `web_zeigen.ps1` | zeigt eine Webseite als echte, bedienbare Seite im Hologramm (sonst echte Webansicht darüber) |
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
