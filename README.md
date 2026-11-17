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
- **Rausch-fest**: misst das Grundrauschen (z. B. Lüfter am Mikro) laufend, zieht Pegel und Klangprofil ab und setzt alle Klatsch-/Schnips-Schwellen relativ dazu; ORB unterbricht sich nicht selbst (Echo-Abgleich unscharf, höhere Schwelle und Mindestdauer echter Sprache, während ORB spricht). **Echo-Sperre**: während und 1,5 s nach eigener Sprachausgabe nimmt das Mikro keine Fragen an (nur „Jarvis“, „Stopp“ oder klares Dazwischenreden); Erkanntes, das zu über 60 % einem zuletzt gesagten ORB-Satz gleicht (auch Update- und Neu-Ansagen), wird in Oberfläche und Server verworfen (`test_echo.py`).
- **Mikrofon-Wahl** (Einstellungen, Standard: USB-Mikro „TONOR“): Spracherkennung (setzt es als Windows-Standard), Klatsch-/Schnips-Erkennung und Hintergrund-Lauscher nutzen dasselbe Mikro (`mikro.ps1`); **Mikro kalibrieren** misst 5 s Ruhe und je 2× Klatschen und Schnipsen und richtet alle Schwellen danach aus (gilt pro Mikro, Doppel-Schnipsen bleibt).
- **Gespräch**: hört dauerhaft zu, bis man „Stopp“ sagt; „Jarvis“ unterbricht ihn.
- **Antwortet laut** auf Deutsch (Microsoft-Neural-Stimmen), Satz für Satz, während die Antwort entsteht – jedes Stück vorab aufbereitet (Klang-EQ, einheitlich −14 LUFS, Limiter mit Vorschau – kein Übersteuern auch bei 300 %), Sätze nicht an Abkürzungen/Datumsangaben zerstückelt; hängt die Neural-Stimme, startet nach ~2,5 s parallel ein zweiter Versuch (der schnellere gewinnt – keine langen Pausen), Pausen zwischen Stücken passend zum Satzzeichen (Protokoll in `stimme.log`) (Lautstärke bis 300 %, ORB im Windows-Mixer immer auf 100 %).
- **Apps & Webseiten öffnen**, Wetter, Termine, Spotify-Steuerung – ohne Token.
- **iCloud-Kalender**: Termine eintragen, lesen und löschen (Einstellungen → iCloud-Kalender, app-spezifisches Passwort).
- **iCloud-Kontakte & Erinnerungen** (gleiche Anmeldung): Kontakte suchen, anlegen, ändern (`kontakte.ps1`, gibt nur gesuchte Einträge aus, Löschen nur nach Bestätigung); Erinnerungen lesen, anlegen, abhaken, löschen (`erinnerungen.ps1`).
- **Oberfläche** im Liquid-Glass-Stil mit Uhr, Gesprächsverlauf, System, Wetter, Termine, Spotify und Vorschlägen.
- **Grafikstufe „Kino“** (Einstellungen → Grafik): Kugel mit Subsurface-Glühen, weichen Reflexionen, Tiefenschärfe, HDR-Bloom, Lichtstrahlen und filmischer Farbkorrektur; die Stimme formt Rand und Licht, Partikel mit Bewegungsunschärfe, Hologramme kippen mit Perspektive und Lichtkante herein (60 fps, ~2 ms GPU bei 2560×1440). Alle Zustandswechsel laufen über eine weiche Feder. „Flüssig“ bleibt die sparsame Standardstufe.
- **Bild-Hologramme**: neue Bilder in `Bilder/ORB Bilder` (oder per `bild_zeigen.ps1`) erscheinen sofort als Holo-Karte.
- **Web-Hologramme**: echte Webseiten zum Klicken, Scrollen und Tippen direkt im Hologramm (`web_zeigen.ps1`).
- **Echte Farben**: Schalter im Bild-/Web-Hologramm (oder `-Rein` an `bild_zeigen.ps1`/`web_zeigen.ps1`) zeigt den Inhalt ohne Hologramm-Effekte; die Bild-Werkstatt (Port 8790) startet immer so.
- **Stiller Skin-Modus**: Sobald es um einen Minecraft-Skin geht (oder die 3D-Skin-Vorschau offen ist), arbeitet ORB still – Antworten nur als Text, Hologramme und 3D-Vorschau laufen weiter –, bis Larsen „wir sind fertig“ sagt (spätestens nach 30 Min. ohne Skin-Arbeit wieder laut).
- **Tarnmodus** („Jarvis, Tarnmodus an“ / „Tarnmodus aus“, auch per Telegram): der PC wirkt ausgeschaltet – schwarze Fläche über allen Monitoren ohne Mauszeiger, Monitore aus, Razer-Licht schwarz, ORB-Fenster versteckt und stumm (Stimme und Klänge), Windows-Benachrichtigungen still, kein Ruhezustand. Nichts wird beendet: Meetings, Downloads, ORB und Telegram laufen weiter. Taste oder Mausbewegung am PC beendet ihn (ORB meldet das, auch per Telegram, wenn du gerade von dort schreibst), danach ist alles wie vorher (`tarnmodus.py`).
- **Pausemodus** („Jarvis, Pausemodus an“, „hör nicht zu“ oder `/pause` per Telegram): ORB nimmt keine Spracheingaben mehr an (z. B. Meeting-Ton), Telegram und Tippen funktionieren weiter; aufheben mit `/weiter` oder getippt „Pausemodus aus“.
- **Komplett ausschalten** („Jarvis, schalte dich komplett aus“ oder `/aus` per Telegram): fester eingebauter Befehl (das Gesprächs-Gehirn darf ORB nicht beenden) – schickt vorher eine kurze Bestätigung per Telegram und beendet dann ORB samt Ohr, Stimme und Telegram-Brücke. Wieder an: ORB.exe starten oder nächster PC-Start.
- **Gold live** („Jarvis, Gold“): XAU/USD jede Sekunde, mit Farbblitz pro Tick und mitlaufender Kurve.
- **Kamera-Ansicht** („Jarvis, Kamera an“ / „Kamera aus“): Live-Webcam (bis 1080p, Autofokus/-belichtung, Aufhellen bei wenig Licht) als Hologramm-Fenster. Alle Hologramme, Widgets (Uhr, Wetter, Termine, Spotify, Gold, System), Bilder, Text-Karten und 3D-Objekte (Sphäre, Würfel, Modell, WebGL) erscheinen darin und lassen sich per Hand greifen, verschieben, drehen, skalieren, anheften, in eine Ecke parken und wegwischen; Handfläche zeigen = radiales Menü, Zeigefinger = Cursor, Spotify per Geste, Zeichnen in der Luft; „Jarvis, Sphäre in meine Hand“ lässt eine Sphäre über der Handfläche schweben. Positionen werden gemerkt (MediaPipe auf der GPU, beide Hände, geglättet, rechnet lokal). Profil „Flüssig“ (Standard: 1080p, Hände auf jedem Bild bis 60 fps erkannt, stabile Zuordnung beider Hände auch bei schneller Bewegung, kurz verdeckte Hand wird gehalten; regelt bei unter 30 fps selbst runter) oder „Scharf“; beim ersten Start eine geführte Einführung, „Jarvis, Kamera-Hilfe“ zeigt alle Gesten, die erkannte Geste erscheint als kleines Symbol. `kamera_zeigen.ps1` schickt Inhalte hinein. Nur auf Befehl, rotes Kamera-Symbol solange an, nichts wird aufgenommen; `kamera.ps1` holt auf Larsens Frage ein einzelnes Standbild für Claude.
- **Was ist neu?**: nach jedem Update (ORB oder Projekt) erscheint kurz ein kleines Hologramm mit den Neuerungen und wie man sie benutzt.
- **Widget „Was Jarvis kann“**: alle Funktionen nach Bereichen, einklappbar, mit Suchfeld und Beispiel-Befehl (antippen = ins Eingabefeld), per Drag & Drop verschiebbar; speist sich aus `features.json`.
- **Wissensbasis**: arbeitet im Ordner `Documents\Jarvis` und merkt sich dort alles.

## Aufbau
| Datei | Aufgabe |
|---|---|
| `orb_launcher.py` | wird zur einzigen `ORB.exe`: installiert, lädt Code von GitHub, aktualisiert, setzt bei Fehlern zurück |
| `orb_app.py` | Start, Fenster, Klatsch-Erkennung im Hintergrund, Autostart, Update-Prüfung |
| `server.py` | lokaler Server: Zustand, Stimme, Claude-Anbindung, Wetter, Apps, Termine, Spotify |
| `icloud.py` | iCloud-Kalender und -Erinnerungen über CalDAV, Kontakte über CardDAV (Zugang in der Windows-Anmeldeinformationsverwaltung) |
| `tarnmodus.py` | Tarnmodus: schwarze Fläche, Monitore aus, Benachrichtigungen still, Ende bei Taste/Maus |
| `hook.py` | Claude-Code-Hooks → zeigt in ORB an, was Claude gerade tut |
| `index.html` | Oberfläche (WebGL-Kugel, Effekte, Sounds, Einstellungen) |
| `neu.ps1` | Entwickler hinterlegt die Einführung „Was ist neu?“ (2–4 Punkte + wie benutzen) – ORB zeigt sie nach dem Update 30 s als kleines Hologramm und liest den ersten Punkt vor |
| `fortschritt.ps1` | Entwickler meldet seinen Fortschritt (Prozent + Schritt) – ORB zeigt ihn als Balken im Entwickler-Hologramm |
| `web_zeigen.ps1` | zeigt eine Webseite als echte, bedienbare Seite im Hologramm (sonst echte Webansicht darüber) |
| `kamera.ps1` | ein Standbild aus der laufenden Kamera-Ansicht nach `%LOCALAPPDATA%\ORB\screen\kamera.png` (schaltet die Kamera nie ein) |
| `kamera_zeigen.ps1` | schickt Widgets, Bilder, Texte oder 3D-Objekte in die laufende Kamera-Ansicht (schaltet die Kamera nie ein) |
| `whatsapp.ps1` | WhatsApp-Nachricht (Text/Bild) in Sekunden vorbereiten, Abschicken erst nach Bestätigung |
| `features.json` | zentrale Liste aller Funktionen (Bereich → Name, Text, Beispiel-Befehl) für das Widget „Was Jarvis kann“ – bei jeder neuen Funktion ergänzen |
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
