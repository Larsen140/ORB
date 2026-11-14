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
- **Antwortet laut** auf Deutsch (Microsoft-Neural-Stimmen), Satz für Satz, während die Antwort entsteht – jedes Stück vorab aufbereitet (Klang-EQ, einheitlich −14 LUFS, Limiter mit Vorschau – kein Übersteuern auch bei 300 %), Sätze nicht an Abkürzungen/Datumsangaben zerstückelt; hängt die Neural-Stimme, gibt es Wiederholversuche statt Ersatzstimme (Protokoll in `stimme.log`) (Lautstärke bis 300 %, ORB im Windows-Mixer immer auf 100 %).
- **Apps & Webseiten öffnen**, Wetter, Termine, Spotify-Steuerung – ohne Token.
- **iCloud-Kalender**: Termine eintragen, lesen und löschen (Einstellungen → iCloud-Kalender, app-spezifisches Passwort).
- **iCloud-Kontakte & Erinnerungen** (gleiche Anmeldung): Kontakte suchen, anlegen, ändern (`kontakte.ps1`, gibt nur gesuchte Einträge aus, Löschen nur nach Bestätigung); Erinnerungen lesen, anlegen, abhaken, löschen (`erinnerungen.ps1`).
- **Oberfläche** im Liquid-Glass-Stil mit Uhr, Gesprächsverlauf, System, Wetter, Termine, Spotify und Vorschlägen.
- **Bild-Hologramme**: neue Bilder in `Bilder/ORB Bilder` (oder per `bild_zeigen.ps1`) erscheinen sofort als Holo-Karte.
- **Web-Hologramme**: echte Webseiten zum Klicken, Scrollen und Tippen direkt im Hologramm (`web_zeigen.ps1`).
- **Echte Farben**: Schalter im Bild-/Web-Hologramm (oder `-Rein` an `bild_zeigen.ps1`/`web_zeigen.ps1`) zeigt den Inhalt ohne Hologramm-Effekte; die Bild-Werkstatt (Port 8790) startet immer so.
- **Gold live** („Jarvis, Gold“): XAU/USD jede Sekunde, mit Farbblitz pro Tick und mitlaufender Kurve.
- **Kamera-Ansicht** („Jarvis, Kamera an“ / „Kamera aus“): Live-Webcam (bis 1080p, Autofokus/-belichtung, Aufhellen bei wenig Licht) als Hologramm-Fenster. Alle Hologramme, Widgets (Uhr, Wetter, Termine, Spotify, Gold, System), Bilder, Text-Karten und 3D-Objekte (Sphäre, Würfel, Modell, WebGL) erscheinen darin und lassen sich per Hand greifen, verschieben, drehen, skalieren, anheften, in eine Ecke parken und wegwischen; Handfläche zeigen = radiales Menü, Zeigefinger = Cursor, Spotify per Geste, Zeichnen in der Luft; „Jarvis, Sphäre in meine Hand“ lässt eine Sphäre über der Handfläche schweben. Positionen werden gemerkt (MediaPipe auf der GPU, beide Hände, geglättet, rechnet lokal). Profil „Flüssig“ (Standard: 720p, Erkennung auf kleinerem Bild, regelt bei unter 30 fps selbst runter) oder „Scharf“; beim ersten Start eine geführte Einführung, „Jarvis, Kamera-Hilfe“ zeigt alle Gesten, die erkannte Geste erscheint als kleines Symbol. `kamera_zeigen.ps1` schickt Inhalte hinein. Nur auf Befehl, rotes Kamera-Symbol solange an, nichts wird aufgenommen; `kamera.ps1` holt auf Larsens Frage ein einzelnes Standbild für Claude.
- **Was ist neu?**: nach jedem Update (ORB oder Projekt) erscheint kurz ein kleines Hologramm mit den Neuerungen und wie man sie benutzt.
- **Wissensbasis**: arbeitet im Ordner `Documents\Jarvis` und merkt sich dort alles.

## Aufbau
| Datei | Aufgabe |
|---|---|
| `orb_launcher.py` | wird zur einzigen `ORB.exe`: installiert, lädt Code von GitHub, aktualisiert, setzt bei Fehlern zurück |
| `orb_app.py` | Start, Fenster, Klatsch-Erkennung im Hintergrund, Autostart, Update-Prüfung |
| `server.py` | lokaler Server: Zustand, Stimme, Claude-Anbindung, Wetter, Apps, Termine, Spotify |
| `icloud.py` | iCloud-Kalender und -Erinnerungen über CalDAV, Kontakte über CardDAV (Zugang in der Windows-Anmeldeinformationsverwaltung) |
| `hook.py` | Claude-Code-Hooks → zeigt in ORB an, was Claude gerade tut |
| `index.html` | Oberfläche (WebGL-Kugel, Effekte, Sounds, Einstellungen) |
| `neu.ps1` | Entwickler hinterlegt die Einführung „Was ist neu?“ (2–4 Punkte + wie benutzen) – ORB zeigt sie nach dem Update 30 s als kleines Hologramm und liest den ersten Punkt vor |
| `fortschritt.ps1` | Entwickler meldet seinen Fortschritt (Prozent + Schritt) – ORB zeigt ihn als Balken im Entwickler-Hologramm |
| `web_zeigen.ps1` | zeigt eine Webseite als echte, bedienbare Seite im Hologramm (sonst echte Webansicht darüber) |
| `kamera.ps1` | ein Standbild aus der laufenden Kamera-Ansicht nach `%LOCALAPPDATA%\ORB\screen\kamera.png` (schaltet die Kamera nie ein) |
| `kamera_zeigen.ps1` | schickt Widgets, Bilder, Texte oder 3D-Objekte in die laufende Kamera-Ansicht (schaltet die Kamera nie ein) |
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
