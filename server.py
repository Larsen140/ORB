"""ORB-Server: Kugel-Seite, Zustand, Sprachausgabe, Einstellungen und Gespräch mit Claude (nur lokal)."""
import datetime
import difflib
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import secrets

from hook import clean, satz_grenzen, split_sentences  # Markdown -> vorlesbarer Text, Text -> Sprech-Stücke

RES = os.path.dirname(os.path.abspath(__file__))  # Seite & Stimme liegen neben server.py (nicht in der exe)
HOME = os.path.join(os.path.expanduser("~"), "Orb")
STATE = os.path.join(HOME, "state.json")
CONFIG = os.path.join(HOME, "config.json")
PAGE = os.path.join(RES, "index.html")


def _lade_icloud(name="icloud"):
    """icloud.py & Co. liegen neben server.py – ausdrücklich von dort laden (der App-Ordner steht nicht im Suchpfad)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(RES, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


icloud = _lade_icloud()  # iCloud-Kalender (CalDAV)
tarnmodus = _lade_icloud("tarnmodus")  # PC wirkt aus, alles läuft weiter
TTS_PS = os.path.join(RES, "tts.ps1")
MIKRO_PS = os.path.join(RES, "mikro.ps1")
PORT = int(os.environ.get("ORB_PORT", "8766"))  # ORB_PORT nur für Tests (update.ps1 prüft auf 8799)
TESTSERVER = PORT != 8766   # nicht nach ORB_PORT fragen: der echte ORB setzt es selbst (für Telegram & Ohr)
NO_WINDOW = 0x08000000
# Schutz gegen fremde Webseiten: nur Anfragen mit diesem Token (steht nur in ORBs eigener Seite und in einer
# Datei im Benutzerordner) dürfen etwas tun.
TOKEN = secrets.token_hex(16)
# Test-Server (andere Ports) dürfen den Token des echten ORB nicht überschreiben
TOKEN_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB",
                          "token.txt" if PORT == 8766 else "token_%d.txt" % PORT)
ERLAUBTE_HOSTS = ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)

STIMMEN = [
    ["de-DE-ChristophNeural", "Christoph (männlich, deutsch – Jarvis-Standard)"],
    ["en-US-BrianMultilingualNeural", "Brian (männlich, sehr natürlich, leichter Akzent)"],
    ["en-AU-WilliamMultilingualNeural", "William (männlich, ruhig, leichter Akzent)"],
    ["de-AT-JonasNeural", "Jonas (männlich, österreichisch)"],
    ["de-CH-JanNeural", "Jan (männlich, Schweizer Hochdeutsch)"],
    ["lokal:thorsten", "KI-Stimme Thorsten (lokal, männlich)"],
    ["de-DE-SeraphinaMultilingualNeural", "Seraphina (weiblich)"],
    ["de-DE-KatjaNeural", "Katja (weiblich)"],
    ["lokal:standard", "KI-Stimme Lina (lokal, weiblich)"],
]
# Microsoft hat diese Stimmen abgeschaltet – alte Einstellungen landen sonst still bei der Notfall-Frauenstimme
STIMMEN_ERSATZ = {"de-DE-FlorianMultilingualNeural": "de-DE-ChristophNeural", "de-DE-ConradNeural": "de-DE-ChristophNeural",
                  "de-DE-KillianNeural": "de-DE-ChristophNeural", "de-DE-AmalaNeural": "de-DE-KatjaNeural"}
DEFAULT_CFG = {
    "stimme": "de-DE-ChristophNeural", "tempo": "+6%", "hoehe": "-2Hz", "jarvis_effekt": True, "lautstaerke": 160, "laut_v": 2,
    "farbe": "rot", "effekte": "mittel", "untertitel": True,
    "sfx": True, "sfxlaut": 60, "ambient": False,
    "steuerung": "wort", "wakeword": "Jarvis", "schnipsen": True, "trading_start": True, "gaming_modus": False, "stimmung": True, "razer": True, "gesten": False, "ohr": True, "unterbrechen": True, "sprechen_unterbrechen": True, "nur_jarvis": True, "musik_schutz": True, "ducking": True,
    "tts_anbieter": "edge",
    "klatschen": True, "dauerzuhoeren": True, "empfindlichkeit": 6, "schnips_empf": 6, "mikro": "TONOR", "kalib": {}, "satzpause": 2.0, "begruessung": True, "ort": "", "name": "",
    "schlafen": 5, "vollbild": True, "spiel_mini": False, "nur_meine_stimme": True, "streng_jarvis": True, "tastatur_farbe": True, "gesichtssperre": True, "autostart": True, "schlaf_schliessen": True, "bildschirm": False,
    "modell": "claude-opus-5-5", "laenge": "kurz", "rechte": "auto", "tempo_claude": "low",
    "ordner": os.path.join(os.path.expanduser("~"), "Documents", "Jarvis"), "sitzung": "",
}
# Damit ORB immer dein Claude-Code-Login (Max-Abo) nutzt und nie einen API-Schlüssel
CLAUDE_ENV_DROP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
VERSION = "170"
ORB_UI = ("Deine Oberfläche (die Larsen gerade sieht): in der Mitte du als flüssige leuchtende Kugel mit Tropfen, "
          "Orbit-Ringen und Sternenhimmel; links eine Uhr und darunter der Gesprächsverlauf mit Eingabefeld; rechts "
          "Karten für System (CPU, RAM, Akku), Wetter mit Stundenvorschau, Aktivität (was du gerade tust) und Vorschläge; "
          "unten ein Dock mit Tastatur, Mikrofon und Einstellungen. Lies dafür keinen Code – du kennst dich.")
KURZ_REGELN = ("Antworte immer auf Deutsch. Du sprichst über ORB, eine Sprachoberfläche; alles wird laut vorgelesen. Antworte wie ein Mensch "
               "im Gespräch: GENAU EIN kurzer Satz, höchstens 12 Wörter – auch wenn die Frage groß wirkt. Keine Einleitung, "
               "keine Begründung, keine Zusatzinfos, keine Rückfrage am Ende, nichts wiederholen; nur die Antwort selbst "
               "(z. B. „14:30 Uhr.“, „Läuft.“, „Morgen 8 Grad und Regen.“). Details zeigst du lieber als Hologramm statt sie zu "
               "sagen. Larsen fragt nach, wenn er mehr will. Kein Markdown, keine Listen, "
               "keine Emojis, kein Code, keine Floskeln. Aufträge trotzdem vollständig erledigen und dann nur kurz "
               "bestätigen. Bei Erledigtem reicht z. B. „Erledigt.“ oder „Läuft.“.")
LANG_REGELN = ("Antworte immer auf Deutsch. Du sprichst über ORB, eine Sprachoberfläche; alles wird laut vorgelesen. Antworte natürlich "
               "gesprochen ohne Markdown oder Listen; ausführlicher ist erlaubt, wenn es nötig ist.")

AUFGABEN_REGELN = (
    "MULTITASKING: Alles, was länger als etwa 15 Sekunden dauern würde (Recherche im Netz, mehrere Schritte, Dateien "
    "durchsuchen/zusammenfassen/erstellen, Mails auswerten, Vergleiche, Pläne), machst du NICHT selbst, sondern startest es "
    "als Hintergrund-Aufgabe – dann kann Larsen sofort weiterreden, und für jede Aufgabe erscheint ein eigenes Hologramm:\n"
    "  powershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\larse\\Orb\\aufgabe.ps1 \"<kurzer Titel, 2-4 Wörter>\" "
    "\"<vollständiger Auftrag mit allem Kontext>\"\n"
    "Danach nur kurz sagen, z. B. „Läuft im Hintergrund.“ Das Ergebnis sagt ORB selbst an, sobald es fertig ist. "
    "Mehrere Aufgaben gleichzeitig sind erlaubt. Kurze Sachen (Fragen beantworten, App öffnen, Musik, Termin eintragen) "
    "machst du direkt. Programmwünsche an ORB und große Projekte gehen wie bisher an den Entwickler (entwickler.ps1) – "
    "der bekommt automatisch auch ein eigenes Hologramm.")

MAIL_REGELN = (
    "Larsens Gmail erreichst du über die claude.ai-Connector-Werkzeuge (mcp__claude_ai_Gmail__…; bei Bedarf mit "
    "ToolSearch nach \"gmail\" laden). Mails lesen, suchen und zusammenfassen darfst du jederzeit. Eine Mail abschicken "
    "oder einen Entwurf versenden NUR, nachdem du Larsen Empfänger und Inhalt kurz genannt hast und er ausdrücklich "
    "zugestimmt hat. Findest du keine Gmail-Werkzeuge, sag ehrlich, dass die Gmail-Verbindung gerade nicht erreichbar "
    "ist und er es gleich noch einmal versuchen soll – erfinde keine Mails.")
MAIL_WORT = re.compile(r"\b(e-?mails?|mails?|gmail|postfach|posteingang|inbox|nachrichten von google)\b", re.I)
KALENDER_REGELN = (
    "Larsens Kalender ist sein iCloud-Kalender (iPhone); das Termine-Widget links zeigt ihn. Termine trägst du NICHT in "
    "termine.md ein, sondern über ORBs Kalender-Skript (es kümmert sich selbst um die Anmeldung): "
    "powershell -NoProfile -ExecutionPolicy Bypass -File \"$env:LOCALAPPDATA\\ORB\\app\\kalender.ps1\" <aktion>. "
    "Aktionen: status; liste -Von 2026-11-13 -Bis 2026-11-20 (ohne Angabe heute + 7 Tage); "
    "neu -Titel \"Zahnarzt\" -Start 2026-11-20T15:00 (optional -Ende, -Ort, -Notiz, -Kalender; nur Datum = ganztägig, "
    "Ende sonst +1 Stunde); löschen = erst liste, dann loeschen -Id \"<id aus der Liste>\". Zeiten sind Ortszeit. "
    "iCloud-Erinnerungen (iPhone-App Erinnerungen) über erinnerungen.ps1 im selben Ordner: liste [-Liste \"..\"] [-Alle]; "
    "neu -Titel \"Milch kaufen\" [-Faellig 2026-11-20T18:00] [-Liste \"..\"] [-Notiz \"..\"] [-Wichtig]; "
    "erledigt -Id \"<id>\" [-Offen]; loeschen -Id \"<id>\" (ids aus liste). "
    "iCloud-Kontakte über kontakte.ps1 im selben Ordner: suche -Text \"Anna\" (Name, Firma, Mail oder Nummer – gib nie "
    "das ganze Adressbuch aus, nur gesuchte Einträge); neu -Name \"Anna Muster\" [-Telefon \"..\"] [-Email \"..\"] "
    "[-Firma] [-Adresse] [-Geburtstag 1990-05-01] [-Notiz]; aendern -Id \"<id aus suche>\" mit den zu ersetzenden Feldern "
    "(-Dazu ergänzt Telefon/E-Mail statt sie zu ersetzen). Einen Kontakt löschen NUR, nachdem du Larsen den Kontakt "
    "genannt und er ausdrücklich zugestimmt hat: loeschen -Id \"<id>\" -Bestaetigt. Alle Antworten sind JSON mit ok.")


# ---------- Bild-Hologramme: neue Bilder (z. B. von Claude erstellt) sofort in ORB einblenden ----------
BILD_ORDNER = os.path.join(os.path.expanduser("~"), "Pictures", "ORB Bilder")
BILD_ENDUNGEN = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
BILD = {"n": 0, "pfad": "", "name": "", "zeit": 0.0, "rein": False}
BILD_LOCK = threading.Lock()


def bild_zeigen(pfad, rein=False):
    """Bild als Hologramm anzeigen lassen (die Seite holt es über /bild). Gibt True zurück, wenn es gültig ist."""
    pfad = os.path.abspath(str(pfad or "").strip().strip('"'))
    if not pfad.lower().endswith(BILD_ENDUNGEN) or not os.path.isfile(pfad):
        return False
    try:
        if os.path.getsize(pfad) > 40 * 1024 * 1024:
            return False
    except OSError:
        return False
    with BILD_LOCK:
        if pfad == BILD["pfad"] and time.time() - BILD["zeit"] < 8:
            BILD["rein"] = BILD["rein"] or bool(rein)
            return True   # Skript und Ordner-Beobachtung melden dasselbe Bild nur einmal
        BILD.update(n=BILD["n"] + 1, pfad=pfad, name=os.path.splitext(os.path.basename(pfad))[0], zeit=time.time(),
                    rein=bool(rein))
    return True


def bild_wache():
    """Beobachtet „Bilder/ORB Bilder“: jedes neue oder geänderte Bild erscheint als Hologramm."""
    bekannt = {}
    erster = True
    while True:
        try:
            if os.path.isdir(BILD_ORDNER):
                for e in os.scandir(BILD_ORDNER):
                    if not e.is_file() or not e.name.lower().endswith(BILD_ENDUNGEN):
                        continue
                    st = e.stat()
                    sig = (st.st_mtime, st.st_size)
                    if not erster and bekannt.get(e.path) != sig and st.st_size > 0:
                        time.sleep(.6)   # fertig schreiben lassen
                        try:
                            if os.path.getsize(e.path) == st.st_size:
                                bild_zeigen(e.path)
                            else:
                                continue   # wird noch geschrieben – beim nächsten Durchlauf
                        except OSError:
                            continue
                    bekannt[e.path] = sig
            erster = False
        except Exception:
            pass
        time.sleep(1.5)


BILD_REGELN = (
    "Bilder, die du für Larsen erstellst, speicherst du als PNG in \"%USERPROFILE%\\Pictures\\ORB Bilder\" – ORB blendet "
    "sie dann automatisch als Hologramm ein. Liegt ein Bild woanders, zeigst du es mit: powershell -NoProfile "
    "-ExecutionPolicy Bypass -File \"$env:LOCALAPPDATA\\ORB\\app\\bild_zeigen.ps1\" \"<Pfad zum Bild>\". Soll Larsen die echten Farben "
    "ohne Hologramm-Effekte sehen (z. B. Designs, Fotos), hänge -Rein an.")


# ---------- Web-Hologramme: echte, bedienbare Webseite im Hologramm-Fenster ----------
# Erlaubt die Seite das Einbetten, läuft sie direkt im Hologramm (iframe). Verbietet sie es (X-Frame-Options /
# frame-ancestors), öffnet ORB eine echte Webansicht (Edge-App-Fenster) genau über dem Hologramm.
WEB = {"n": 0, "url": "", "titel": "", "modus": "", "proc": None, "hwnd": 0, "rein": False}
WEB_LOCK = threading.Lock()
WEB_PROFIL = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "webansicht")


def web_pruefen(url):
    """Lädt die Seite kurz an: (einbettbar, Ziel-URL nach Weiterleitungen, Seitentitel)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
                                               "Accept-Language": "de-DE,de;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            ziel, h = r.geturl(), r.headers
            html = r.read(200000).decode("utf-8", "ignore")
    except Exception as e:
        print("Webansicht prüfen:", e)
        return False, url, ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    titel = re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""
    try:
        import html as html_mod
        titel = html_mod.unescape(titel)
    except Exception:
        pass
    if (h.get("X-Frame-Options") or "").strip().lower() in ("deny", "sameorigin"):
        return False, ziel, titel
    for csp in h.get_all("Content-Security-Policy") or []:
        fa = re.search(r"frame-ancestors([^;]*)", csp, re.I)
        if fa and "*" not in fa.group(1).split():
            return False, ziel, titel
    # Seiten, die sich per Skript gegen Einbetten wehren (z. B. Wix: bleiben im iframe schwarz) → echte Webansicht
    if re.search(r"(?:window\.)?(?:self|top)\s*[!=]==?\s*(?:window\.)?(?:top|self)\b|top\.location|parent\.location"
                 r"|static\.wixstatic\.com|wix-thunderbolt", html, re.I):
        return False, ziel, titel
    return True, ziel, titel


def web_zeigen(url, titel="", rein=False):
    """Webseite als bedienbares Hologramm anzeigen. Gibt (ok, Antwort-Daten) zurück."""
    url = str(url or "").strip().strip('"')
    if url and not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    if not re.match(r"^https?://[^\s/]+\.[^\s]+", url, re.I):
        return False, {"fehler": "Keine gültige Adresse"}
    einbettbar, ziel, t = web_pruefen(url)
    web_schliessen_fenster()
    # lokale Bild-Werkstatt (Port 8790) immer ohne Hologramm-Effekte – dort zählen die echten Farben
    try:
        ort = urlparse(ziel or url)
        rein = bool(rein) or (ort.hostname in ("127.0.0.1", "localhost") and ort.port == 8790)
    except ValueError:
        rein = bool(rein)
    with WEB_LOCK:
        WEB.update(n=WEB["n"] + 1, url=ziel or url, titel=str(titel or t or urlparse(url).hostname or url)[:80],
                   modus="iframe" if einbettbar else "fenster", hwnd=0, rein=rein)
    return True, {"modus": WEB["modus"], "url": WEB["url"], "titel": WEB["titel"]}


def web_lebt():
    p = WEB["proc"]
    return bool(p and p.poll() is None)


def web_schliessen_fenster():
    """Webansicht-Fenster beenden (alle Browser-Prozesse des eigenen Profils)."""
    p, WEB["proc"], WEB["hwnd"] = WEB["proc"], None, 0
    try:
        import psutil
        for q in psutil.process_iter(["name", "cmdline"]):
            if (q.info["name"] or "").lower() in ("msedge.exe", "chrome.exe") and \
                    any("ORB\\webansicht" in (c or "") for c in q.info["cmdline"] or []):
                try:
                    q.kill()
                except Exception:
                    pass
    except Exception:
        if p and p.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=0x08000000)


def _fenster_von(pids, titel=None):
    """Sichtbare Browser-Fenster der gegebenen Prozesse (bzw. mit genau diesem Titel)."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        c = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, c, 64)
        if c.value.startswith("Chrome_WidgetWin"):
            if titel is not None:
                n = u.GetWindowTextLengthW(h)
                b = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, b, n + 1)
                if b.value == titel:
                    found.append(h)
            elif u.IsWindowVisible(h) and u.GetWindowTextLengthW(h) > 0:
                pid = wintypes.DWORD()
                u.GetWindowThreadProcessId(h, ctypes.byref(pid))
                if pid.value in pids:
                    found.append(h)
        return True

    u.EnumWindows(cb, 0)
    return found


def _web_platzieren(x, y, w, h):
    """Webansicht-Fenster über das Hologramm legen und an ORB hängen (bleibt über ORB, verschwindet mit ORB)."""
    import ctypes
    u = ctypes.windll.user32
    u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    try:
        u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # echte Bildschirmpixel
    except Exception:
        pass
    if not WEB["hwnd"] or not u.IsWindow(ctypes.c_void_p(WEB["hwnd"])):
        try:
            import psutil
            pids = {q.pid for q in psutil.process_iter(["name", "cmdline"])
                    if any("ORB\\webansicht" in (c or "") for c in q.info["cmdline"] or [])}
        except Exception:
            pids = {WEB["proc"].pid} if WEB["proc"] else set()
        hs = _fenster_von(pids)
        if not hs:
            return False
        WEB["hwnd"] = hs[0]
        orb = _fenster_von(set(), "ORB")
        if orb:
            u.SetWindowLongPtrW(hs[0], -8, orb[0])   # Besitzer = ORB-Fenster: bleibt darüber, verschwindet mit ihm
    hw = ctypes.c_void_p(WEB["hwnd"])
    u.ShowWindow(hw, 9 if u.IsIconic(hw) else 5)
    u.SetWindowPos(hw, None, int(x), int(y), int(w), int(h), 0x0040)   # SWP_SHOWWINDOW
    u.SetForegroundWindow(hw)
    return True


def web_fenster(n, rect):
    """Webansicht starten bzw. neu ausrichten. rect = [x, y, b, h] in Bildschirmpixeln (von der Oberfläche)."""
    if n != WEB["n"] or WEB["modus"] != "fenster":
        return False
    x, y, w, h = (int(float(v)) for v in rect)
    if not web_lebt():
        browser = next((p for p in (
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"Google\Chrome\Application\chrome.exe"))
            if os.path.exists(p)), None)
        if not browser:
            return False
        WEB["proc"] = subprocess.Popen([browser, "--app=" + WEB["url"], "--user-data-dir=" + WEB_PROFIL,
                                        "--no-first-run", "--no-default-browser-check", "--disable-features=Translate",
                                        "--window-position=%d,%d" % (x, y), "--window-size=%d,%d" % (w, h)])
        WEB["hwnd"] = 0
    for _ in range(60):   # warten, bis das Fenster da ist
        try:
            if _web_platzieren(x, y, w, h):
                return True
        except Exception as e:
            print("Webansicht platzieren:", e)
            return False
        time.sleep(.15)
    return web_lebt()


def web_schliessen():
    with WEB_LOCK:
        WEB["modus"] = ""
    web_schliessen_fenster()


WEB_REGELN = (
    "Webseiten zeigst du Larsen nicht als Screenshot, sondern als echte, bedienbare Webseite im Hologramm: "
    "powershell -NoProfile -ExecutionPolicy Bypass -File \"$env:LOCALAPPDATA\\ORB\\app\\web_zeigen.ps1\" \"<URL>\" "
    "(optional -Titel \"…\"). -Rein zeigt sie ohne Hologramm-Effekte in echten Farben. "
    "Larsen kann darin klicken, scrollen und tippen.")


# ---------- Kamera-Ansicht (Webcam + AR-Hologramme) ----------
# Die Kamera läuft nur in der Oberfläche und nur auf Larsens ausdrücklichen Befehl („Kamera an“). Es wird nichts
# aufgenommen oder gesendet. Einzige Ausnahme: kamera.ps1 bittet die Oberfläche um EIN Standbild (nur, wenn Larsen fragt).
KAMERA = {"aktiv": False, "zeit": 0.0, "foto": 0, "foto_zeit": 0.0}
KAMERA_BILD = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "screen", "kamera.png")
KAMERA_REGELN = (
    "Kamera: Larsen schaltet sie selbst mit „Kamera an“/„Kamera aus“ ein und aus – du schaltest sie nie ein. Nur wenn die "
    "Kamera an ist UND Larsen ausdrücklich fragt, was du siehst (z. B. „Was hab ich in der Hand?“), holst du EIN Standbild: "
    "powershell -NoProfile -ExecutionPolicy Bypass -File \"$env:LOCALAPPDATA\\ORB\\app\\kamera.ps1\" und siehst dir "
    "%LOCALAPPDATA%\\ORB\\screen\\kamera.png mit dem Read-Werkzeug an. Ist die Kamera aus, sag ihm, dass er „Kamera an“ sagen kann. "
    "Solange die Kamera an ist, erscheinen holo.ps1-Hologramme und bild_zeigen.ps1-Bilder automatisch darin. Widgets, 3D-Objekte "
    "oder kurze Texte schickst du mit powershell -NoProfile -ExecutionPolicy Bypass -File \"$env:LOCALAPPDATA\\ORB\\app\\kamera_zeigen.ps1\" "
    "-Art uhr|wetter|termine|spotify|gold|system|bild|text|sphaere|wuerfel|modell [-Titel …] [-Text …] [-Punkte \"a|b\"] [-Bild Pfad] [-Hand].")


KAM_INHALT = {"n": 0, "liste": []}   # Inhalte, die kamera_zeigen.ps1 in die Kamera-Ansicht schickt (nur im Speicher)
KAM_ARTEN = {"uhr", "wetter", "termine", "spotify", "gold", "system", "bild", "text", "sphaere", "wuerfel", "modell",
             "menue", "zeichnen", "aufraeumen"}


def kamera_zeigen(b):
    """kamera_zeigen.ps1: Hologramm/Widget/3D-Objekt in die laufende Kamera-Ansicht schicken (schaltet sie nie ein)."""
    if not kamera_aktiv():
        return {"ok": False, "fehler": "Die Kamera ist aus. Larsen kann „Kamera an“ sagen."}
    art = str(b.get("art") or "text").lower().replace("ä", "ae").replace("ü", "ue").replace("ö", "oe")
    if art not in KAM_ARTEN:
        return {"ok": False, "fehler": "Unbekannte Art. Erlaubt: " + ", ".join(sorted(KAM_ARTEN))}
    e = {"art": art, "id": str(b.get("id") or "")[:40], "titel": str(b.get("titel") or "")[:80],
         "text": str(b.get("text") or "")[:2000], "punkte": [str(x)[:200] for x in (b.get("punkte") or [])][:30],
         "hand": bool(b.get("hand")), "zu": bool(b.get("zu")), "pfad": ""}
    if art == "bild" and b.get("pfad"):
        pfad = os.path.abspath(str(b["pfad"]))
        if not (pfad.lower().endswith(BILD_ENDUNGEN) and os.path.isfile(pfad)):
            return {"ok": False, "fehler": "Bild nicht gefunden (png/jpg/webp/gif/bmp)"}
        e["pfad"] = pfad
    KAM_INHALT["n"] += 1
    e["n"] = KAM_INHALT["n"]
    KAM_INHALT["liste"] = (KAM_INHALT["liste"] + [e])[-20:]
    return {"ok": True, "n": e["n"]}


def kamera_aktiv():
    """Kamera gilt nur als an, solange die Oberfläche das regelmäßig bestätigt (Fenster zu → aus)."""
    return KAMERA["aktiv"] and time.time() - KAMERA["zeit"] < 6


def kamera_bild_speichern(b64):
    """Standbild der Oberfläche (data-URL/Base64-PNG) nach screen/kamera.png – nur nach einer Anfrage über kamera.ps1."""
    import base64
    if not KAMERA["foto"] or time.time() - KAMERA["foto_zeit"] > 15 or not kamera_aktiv():
        return False
    try:
        data = base64.b64decode(str(b64 or "").split(",", 1)[-1])
    except Exception:
        return False
    if not data.startswith(b"\x89PNG") or len(data) > 12 * 1024 * 1024:
        return False
    os.makedirs(os.path.dirname(KAMERA_BILD), exist_ok=True)
    tmp = KAMERA_BILD + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, KAMERA_BILD)
    KAMERA["foto_zeit"] = 0.0   # Anfrage erledigt
    return True


def system_prompt(cfg):
    """Persönlichkeit aus der Wissensbasis + Sprechregeln."""
    persona = ""
    try:
        with open(os.path.join(cfg["ordner"], "persoenlichkeit.md"), encoding="utf-8") as f:
            persona = f.read()[:5000]
    except Exception:
        pass
    try:
        kal = "\n\n" + KALENDER_REGELN if icloud.verbunden() else ""
    except Exception:
        kal = ""
    return ((persona + "\n\n" if persona else "") + ORB_UI + "\n\n"
            + (KURZ_REGELN if cfg.get("laenge") == "kurz" else LANG_REGELN) + "\n\n" + AUFGABEN_REGELN + "\n\n"
            + MAIL_REGELN + "\n\n" + BILD_REGELN + "\n\n" + WEB_REGELN + "\n\n" + KAMERA_REGELN + kal)


KURZ_PROMPT = ("Du sprichst gerade über ORB, eine Sprachoberfläche; deine Antwort wird laut vorgelesen. "
               "Antworte in 1 bis 3 kurzen, natürlich gesprochenen Sätzen auf Deutsch, ohne Markdown, Listen, "
               "Tabellen, Emojis oder Code. Arbeite Aufträge trotzdem vollständig ab.")

_cache, _lock, _cfg_lock = {}, threading.Lock(), threading.Lock()
LAST_POLL = [0.0]
LAST_WACH = [0.0]
LAST_SPRICHT = [0.0]   # wann ORB zuletzt hörbar gesprochen hat (Echo-Schutz fürs lokale Ohr)
GESAGT = {}   # aid → [Zeit, Text]: was ORB zuletzt gesagt hat (Antworten, Ansagen, Update-/Neu-Hinweise) – gegen Echo-Schleifen
ECHO_SPERRE = 1.5   # so lange nach eigener Sprachausgabe zählt nur „Jarvis“/„Stopp“
_NAMEN = re.compile(r"(?i)\b(jarvis|orb)\b")


def gesagt_merken(aid, text):
    text = str(text or "").strip()
    if not text:
        return
    now = time.time()
    GESAGT[aid or "x%d" % int(now * 1000)] = [now, text]
    for k in [k for k, v in list(GESAGT.items()) if now - v[0] > 180]:
        GESAGT.pop(k, None)


def _stamm(t):
    return [w[:5] for w in re.findall(r"[a-zäöüß0-9]+", _NAMEN.sub(" ", str(t).lower()))]


def echo_aehnlichkeit(text, gesagt):
    """0..1: wie sehr der gehörte Text einem von ORB gesagten Satz (oder zwei aufeinanderfolgenden) gleicht."""
    h = _stamm(text)
    if len(h) < 3:
        return 0.0   # „Ja“, „Stopp“ … nie als Echo verwerfen
    best = 0.0
    for g in gesagt:
        saetze = [x for x in re.split(r"(?<=[.!?…])\s+", g) if x.strip()] or [g]
        for st in saetze + [a + " " + b for a, b in zip(saetze, saetze[1:])] + [g]:
            w = _stamm(st)
            if not w:
                continue
            treffer = sum(x.size for x in difflib.SequenceMatcher(None, h, w, autojunk=False).get_matching_blocks())
            # Dice-Wert; bei längeren Stücken auch: steckt das Gehörte fast ganz in ORBs Satz (nur ein Teil wurde erkannt)?
            best = max(best, 2 * treffer / (len(h) + len(w)), treffer / len(h) - .25 if len(h) >= 4 else 0)
    return best


def ist_echo(text, frist=180):
    now = time.time()
    return echo_aehnlichkeit(text, [v[1] for v in list(GESAGT.values()) if now - v[0] < frist]) > .6
OHR = {"t": 0.0, "n": 0, "ev": []}   # lokales Ohr (ohr.py): letzter Kontakt, Ereignisse für die Oberfläche   # wann die Oberfläche zuletzt sichtbar und wach war (Razer-Licht)
LAST_ACTIVE = [0.0]   # wann das Fenster zuletzt gesprochen/zugehört hat  # wann das Fenster zuletzt nachgefragt hat
ON_SHOW = [None]    # wird von orb_app gesetzt: öffnet/zeigt das Fenster
ON_HIDE = [None]
ON_MINI = [None]    # Mini-ORB an/aus (orb_app.mini)    # schließt das Fenster (Schlaf spart Speicher)
ON_UPDATE = [None]  # neuesten Stand von GitHub holen und neu starten
ON_CHECK = [None]   # liefert den neueren GitHub-Stand (sha) oder None, wenn ORB aktuell ist

_mouse = {"t": 0.0, "on": False}
CLOSE_LOG = os.path.join(HOME, "schliessen.log")   # warum ORB sich geschlossen/ausgeblendet hat (Grund + Uhrzeit)
RUN_MARK = os.path.join(HOME, "laeuft.txt")        # fehlt beim sauberen Beenden – liegt er beim Start noch da, war es ein Absturz


HOER_LOG = os.path.join(HOME, "hoeren.log")       # Spracherkennung: welcher Erkenner wann startet/endet (Fehlersuche „hört nicht“)


def log_close(grund, path=CLOSE_LOG):
    """Grund fürs Schließen/Ausblenden mit Uhrzeit protokollieren (Datei bleibt klein)."""
    if TESTSERVER:
        return   # Test-Server
    try:
        os.makedirs(HOME, exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 200000:
            with open(path, encoding="utf-8", errors="ignore") as f:
                rest = f.readlines()[-500:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(rest)
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), str(grund)[:300]))
    except Exception:
        pass


def mark_running(on=True):
    try:
        if on:
            with open(RUN_MARK, "w") as f:
                f.write(str(os.getpid()))
        elif os.path.exists(RUN_MARK):
            os.remove(RUN_MARK)
    except Exception:
        pass


def clean_exit(grund):
    """Gewolltes Beenden: protokollieren, Markierung entfernen, Prozess sofort beenden."""
    log_close(grund)
    mark_running(False)
    for k in ("pid", "stimme_pid"):   # lokales Ohr und KI-Stimme mitbeenden
        if OHR.get(k):
            subprocess.run(["taskkill", "/F", "/PID", str(OHR[k])], capture_output=True, creationflags=NO_WINDOW)
    for t in list(TASKS.values()):
        if t.get("status") == "laeuft" and t.get("pid"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(t["pid"])], capture_output=True, creationflags=NO_WINDOW)
    os._exit(0)


def _install_crash_log():
    """Unbehandelte Fehler (auch in Threads) ins Protokoll schreiben."""
    alt = sys.excepthook

    def hook(t, v, tb):
        log_close("Absturz: %s: %s" % (t.__name__, v))
        alt(t, v, tb)
    sys.excepthook = hook
    if hasattr(threading, "excepthook"):
        def thook(a):
            if a.exc_type is not SystemExit:
                log_close("Fehler im Hintergrund (%s): %s: %s" % (getattr(a.thread, "name", "?"), a.exc_type.__name__, a.exc_value))
        threading.excepthook = thook


_call = {"t": 0.0, "v": False}
CALL_TITLES = ("google meet", "meet – ", "meet - ", "zoom meeting", "zoom-meeting", "microsoft teams", "webex", "discord")
CALL_APPS = ("opera.exe", "chrome.exe", "firefox.exe", "brave.exe", "discord.exe", "teams.exe", "ms-teams.exe",
             "zoom.exe", "ciscocollabhost.exe", "webex.exe", "skype.exe")


CALL_FREI = [False]   # im Meet: Larsen hat ORB selbst geholt (Klatschen) → ORB hört zu, bis er wieder weg ist


def call_aktiv():
    """Meeting läuft UND Larsen hat ORB nicht selbst dazugeholt → nicht zuhören."""
    if not in_call():
        CALL_FREI[0] = False
        return False
    return not CALL_FREI[0]


def in_call():
    """Läuft gerade ein Anruf/Meeting (Google Meet, Teams, Zoom, Discord …)? Dann hört ORB nicht hin.
    Erkennung über Fenstertitel und darüber, ob eine Anruf-App gerade das Mikrofon benutzt. 2 s zwischengespeichert."""
    now = time.time()
    if now - _call["t"] < 2:
        return _call["v"]
    found = False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        titles = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(h, _):
            if u.IsWindowVisible(h):
                n = u.GetWindowTextLengthW(h)
                if n:
                    b = ctypes.create_unicode_buffer(n + 1)
                    u.GetWindowTextW(h, b, n + 1)
                    titles.append(b.value.replace("\xa0", " ").lower())
            return True
        u.EnumWindows(cb, 0)
        found = any(k in t for t in titles for k in CALL_TITLES if not t.startswith("orb"))
    except Exception:
        pass
    if not found:
        try:
            import winreg
            base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    if name.lower().rsplit("#", 1)[-1] in CALL_APPS:
                        with winreg.OpenKey(k, name) as sk:
                            try:
                                if winreg.QueryValueEx(sk, "LastUsedTimeStop")[0] == 0:   # 0 = Mikrofon gerade in Benutzung
                                    found = True
                                    break
                            except OSError:
                                pass
        except Exception:
            pass
    _call.update(t=now, v=found)
    return found


def input_ago():
    """Sekunden seit der letzten Tastatur- oder Mauseingabe (systemweit) – Tippen klickt ähnlich hell wie Schnipsen."""
    try:
        import ctypes

        class LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        li = LII(); li.cbSize = ctypes.sizeof(LII)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
        return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return 99.0


def mouse_ago():
    """Sekunden seit dem letzten Mausklick (systemweit). Klickgeräusche sollen nicht als Klatschen zählen.
    Startet beim ersten Aufruf einen kleinen Beobachter (nur Windows)."""
    if not _mouse["on"]:
        _mouse["on"] = True

        def watch():
            try:
                import ctypes
                gks = ctypes.windll.user32.GetAsyncKeyState
            except Exception:
                return
            down = set()
            while True:
                for vk in (1, 2, 4, 5, 6):   # links, rechts, Mitte, Seitentasten
                    if gks(vk) & 0x8000:
                        if vk not in down:
                            down.add(vk)
                            _mouse["t"] = time.time()
                    else:
                        down.discard(vk)
                time.sleep(.01)
        threading.Thread(target=watch, daemon=True).start()
    return time.time() - _mouse["t"]


# ---------- Zustand & Einstellungen ----------
def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seq": 0, "mode": "idle"}


_state_lock = threading.Lock()


# ---------- Stiller Skin-Modus: beim gemeinsamen Skin-Bauen nicht sprechen, bis Larsen „wir sind fertig“ sagt ----------
SKIN_STILL = {"an": False, "zeit": 0.0}
SKIN_WORT = re.compile(r"\bskin", re.I)
SKIN_FERTIG = re.compile(r"\b(wir\s+sind|ich\s+bin|sind\s+wir)\s+fertig\b", re.I)


def skin_still(an=None):
    """Abfragen (an=None), einschalten (True, frischt auch die Zeit auf) oder ausschalten (False). Nach 30 Min. ohne
    Skin-Tätigkeit schaltet er sich von selbst ab, damit ORB nie dauerhaft stumm bleibt."""
    SKIN_STILL["an"] = False   # Minecraft/Skins sind entfernt (18.11.): „Skin“ im Satz darf ORB nicht mehr stummschalten
    return False
    if an is True:
        if not SKIN_STILL["an"]:
            print("Skin-Modus: still")
        SKIN_STILL.update(an=True, zeit=time.time())
    elif an is False:
        SKIN_STILL["an"] = False
    elif SKIN_STILL["an"] and time.time() - SKIN_STILL["zeit"] > 1800:
        SKIN_STILL["an"] = False
    return SKIN_STILL["an"]


def write_state(**kw):
    """Zustand schreiben – mit Lock (mehrere Threads) und Wiederholung, falls Windows die Datei kurz sperrt."""
    if kw.get("parts") and fremd_gesperrt():
        kw["parts"] = []   # Fremden-Sperre: nie etwas laut sagen, auch nicht „laut“-Ansagen
    if not kw.pop("laut", False) and kw.get("parts") and (skin_still() or tarnmodus.aktiv()):
        kw["parts"] = []   # Skin- oder Tarnmodus: Text nur anzeigen (und per Telegram), nicht vorlesen
    with _state_lock:
        st = read_state()
        st.update(kw)
        if kw.get("say"):
            gesagt_merken(st.get("aid"), kw["say"])
        st["seq"] = int(st.get("seq", 0)) + 1
        st["time"] = time.time()
        os.makedirs(HOME, exist_ok=True)
        tmp = "%s.%d.%d.tmp" % (STATE, os.getpid(), threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        for i in range(20):
            try:
                os.replace(tmp, STATE)
                return
            except PermissionError:
                time.sleep(.02 * (i + 1))
        try:
            os.remove(tmp)
        except OSError:
            pass


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("laut_v", 1) < 2:   # einmalig: Stimme deutlich lauter (Regler geht jetzt bis 200 %)
            data["lautstaerke"] = max(160, int(data.get("lautstaerke", 90) or 0))
            data["laut_v"] = 2
        cfg.update(data)
    except Exception:
        pass
    cfg["lautstaerke"] = max(0, min(300, int(cfg.get("lautstaerke", 160) or 0)))
    return cfg


def save_cfg(patch):
    with _cfg_lock:
        cfg = load_cfg()
        old = dict(cfg)
        cfg.update({k: v for k, v in patch.items() if k in DEFAULT_CFG})
        for k in [k for k in cfg if k not in DEFAULT_CFG]:
            del cfg[k]   # alte Einträge (z. B. ElevenLabs) aufräumen
        os.makedirs(HOME, exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    if "autostart" in patch:
        set_autostart(bool(cfg["autostart"]))
    # Claude mit neuen Einstellungen neu starten (passiert beim nächsten Auftrag)
    if any(old.get(k) != cfg.get(k) for k in ("modell", "rechte", "laenge", "ordner", "tempo_claude")):
        BRAIN.kill()
    if "mikro" in patch and old.get("mikro") != cfg.get("mikro"):
        threading.Thread(target=mikro_standard, daemon=True).start()
    return cfg


def mikro_passt(wahl, name):
    """Passt ein Gerätename zur Mikrofon-Wahl? („TONOR“ passt zu „Mikrofon (TONOR TD510 …)“; MME kürzt Namen auf 31 Zeichen)."""
    w, n = str(wahl or "").strip().lower(), str(name or "").strip().lower()
    return bool(w and n) and (w in n or (len(n) >= 20 and n in w))


def mikro_standard():
    """Gewähltes Mikrofon zum Windows-Standard machen – die Spracherkennung im Fenster hört immer auf den Standard."""
    wahl = str(load_cfg().get("mikro") or "").strip()
    if not wahl:
        return
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", MIKRO_PS, "-Name", wahl],
                       capture_output=True, timeout=20, creationflags=NO_WINDOW)
    except Exception as e:
        print("Mikrofon-Wahl:", e)


STARTUP_LNK = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup\ORB.lnk")


def set_autostart(on):
    """Verknüpfung im Windows-Autostart anlegen/entfernen (startet ORB unsichtbar im Hintergrund)."""
    try:
        if not on:
            if os.path.exists(STARTUP_LNK):
                os.remove(STARTUP_LNK)
            return
        exe = sys.executable if getattr(sys, "frozen", False) else os.path.join(os.path.expanduser("~"), "Desktop", "ORB.exe")
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s'); $s.TargetPath='%s'; $s.Arguments='--hintergrund'; "
              "$s.WorkingDirectory='%s'; $s.Save()" % (STARTUP_LNK, exe, os.path.dirname(exe)))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=20, creationflags=NO_WINDOW)
    except Exception as e:
        print("Autostart:", e)


def new_aid():
    return "a%d" % int(time.time() * 1000)


def holo_for(task, detail):
    """Daten für die Holo-Projektion über der Kugel (Wetter, geöffnete Apps)."""
    try:
        if task == "Wetter abrufen":
            w = weather_data()
            if w:
                return {"typ": "wetter", "titel": "%d°" % round(w["temp"]), "code": w["code"],
                        "sub": "%s · %s" % (w["desc"], w["city"])}
        if task == "Öffne" and detail:
            return {"typ": "app", "titel": detail, "sub": "wird geöffnet"}
    except Exception:
        pass
    return None


def write_answer(text, **kw):
    """Fertige Antwort (Begrüßung, lokale Aufträge, Fehler) in Sprech-Stücke zerlegen und ausgeben."""
    kw.setdefault("holo", None)   # alte Holo-Projektion nicht mitschleppen
    write_state(mode="spricht", say=text, parts=split_sentences(text), aid=new_aid(), final=True, **kw)


# ---------- Sprachausgabe ----------
STIMM_LOG = os.path.join(HOME, "stimme.log")   # Neural-Stimme: Fehler, Wiederholversuche, Ersatzstimme (Fehlersuche „klingt komisch“)
_edge_sem = threading.BoundedSemaphore(5)       # nicht zu viele gleichzeitige Verbindungen (sonst drosselt der Dienst)


def _edge_einmal(text, cfg, frist):
    """Ein Versuch bei der Neural-Stimme. Hängt der Dienst, merkt man es am ersten Audio-Stück: kommt es nicht
    binnen 5 s, ist dieser Versuch tot (vorher wartete ORB bis zu 12 s → lange Pausen zwischen Sätzen)."""
    import asyncio
    import edge_tts

    async def run():
        buf = bytearray()
        stimme = cfg["stimme"] if "Neural" in str(cfg.get("stimme", "")) else "de-DE-ChristophNeural"   # lokal:… → Netz-Ersatz
        stimme = STIMMEN_ERSATZ.get(stimme, stimme)
        com = edge_tts.Communicate(text, stimme, rate=cfg["tempo"], pitch=cfg["hoehe"])
        it = com.stream().__aiter__()
        while True:
            try:
                chunk = await asyncio.wait_for(it.__anext__(), 5 if not buf else 6)
            except StopAsyncIteration:
                break
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    with _edge_sem:
        return asyncio.run(asyncio.wait_for(run(), frist))


def stimme_vorladen():
    """Lokale KI-Stimme schon mal in die Grafikkarte laden (beim Aufwachen), damit die erste Antwort nicht wartet."""
    try:
        if str(load_cfg().get("stimme", "")).startswith("lokal:"):
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8767/laden", data=b"{}", method="POST",
                                                          headers={"X-ORB-Token": TOKEN}), timeout=2)
    except Exception:
        pass


def synth_lokal(text, cfg):
    """Lokale KI-Stimme (Chatterbox, stimme.py auf Port 8767). None, wenn sie (noch) nicht läuft."""
    try:
        st = json.loads(urllib.request.urlopen("http://127.0.0.1:8767/status", timeout=1.5).read())
        if not st.get("geladen"):   # Modell lädt noch: diesmal Microsoft-Stimme, im Hintergrund vorladen
            stimme_vorladen()
            return None
        stimme = str(cfg.get("stimme", "")).split(":", 1)[1] or "thorsten"
        req = urllib.request.Request("http://127.0.0.1:8767/tts", data=json.dumps(
            {"text": text, "stimme": stimme, "emotion": float(cfg.get("emotion", 0.55))}).encode(),
            headers={"Content-Type": "application/json", "X-ORB-Token": TOKEN}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        return data if len(data) > 1000 else None
    except Exception as e:
        print("Lokale Stimme:", e)
        return None


def synth(text, cfg=None):
    cfg = cfg or load_cfg()
    if str(cfg.get("stimme", "")).startswith("lokal:"):
        data = synth_lokal(text, cfg)
        if data:
            return data
        cfg = dict(cfg, stimme="de-DE-FlorianMultilingualNeural")   # Ersatz, bis die KI-Stimme bereit ist
    return synth_edge(text, cfg)


def synth_edge(text, cfg=None):
    """Microsoft-Neural-Stimme mit „gestaffelten“ Versuchen: Ist nach ~2,5 s noch nichts da (oder scheitert ein Versuch),
    startet sofort ein zweiter parallel – der schnellere gewinnt. So entstehen keine Lücken zwischen den Sätzen,
    wenn der Dienst kurz hängt. Windows-Stimme nur, wenn alle Versuche scheitern."""
    import queue
    cfg = cfg or load_cfg()
    fehler, q, t0 = [], queue.Queue(), time.time()
    gestaffelt = (0, 2.5 + len(text) * .012, 7, 13)   # Startzeit je Versuch (s nach Beginn)

    def versuch(nr):
        try:
            c = cfg
            if nr >= 2 and any("NoAudio" in (f or "") for f in fehler):   # Stimme/Parameter abgelehnt → Standardstimme, normale Einstellungen
                c = dict(cfg, stimme="de-DE-ChristophNeural", tempo="+0%", hoehe="+0Hz")
            data = _edge_einmal(text, c, 18)
            q.put((nr, data if len(data) > 400 else None, None if len(data) > 400 else "leere Antwort"))   # leer = Fehler
        except Exception as e:
            q.put((nr, None, "%s: %s" % (type(e).__name__, str(e)[:120] or "Zeitüberschreitung")))

    gestartet, offen = 0, 0
    while True:
        if gestartet < len(gestaffelt) and (offen == 0 or time.time() - t0 >= gestaffelt[gestartet]):
            threading.Thread(target=versuch, args=(gestartet,), daemon=True).start()
            gestartet, offen = gestartet + 1, offen + 1
        if offen == 0:
            break
        warte = (t0 + gestaffelt[gestartet] - time.time()) if gestartet < len(gestaffelt) else 25
        try:
            nr, data, f = q.get(timeout=max(.05, warte))
        except queue.Empty:
            if gestartet >= len(gestaffelt):
                break
            continue
        offen -= 1
        if data:
            if fehler or nr:
                log_close("Neural-Stimme ok mit Versuch %d nach %.1f s%s | %s" % (nr + 1, time.time() - t0,
                          (": " + "; ".join(fehler)) if fehler else " (erster hing)", text[:60]), STIMM_LOG)
            return data
        fehler.append(f)
    log_close("ERSATZSTIMME (Windows) nach %d Fehlversuchen: %s | %s" % (gestartet, "; ".join(fehler) or "keine Antwort", text[:60]), STIMM_LOG)
    print("Neural-Stimme nicht verfügbar, nutze Windows-Stimme:", fehler)
    return synth_windows(text)


def synth_windows(text):
    fd, txt = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    wav = txt[:-4] + ".wav"
    try:
        with open(txt, "w", encoding="utf-8") as f:
            f.write(text)
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", TTS_PS, txt, wav],
                       capture_output=True, timeout=120, creationflags=NO_WINDOW)
        with open(wav, "rb") as f:
            return f.read()
    except Exception as e:
        print("Sprachausgabe-Fehler:", e)
        return None
    finally:
        for p in (txt, wav):
            try:
                os.remove(p)
            except OSError:
                pass


def ensure(key, text):
    """Erzeugt die Sprachausgabe für ein Antwort-Stück im Hintergrund (einmal pro Stück)."""
    with _lock:
        ent = _cache.get(key)
        if ent is None:
            ent = {"ev": threading.Event(), "data": None}
            _cache[key] = ent
            while len(_cache) > 40:
                _cache.pop(next(iter(_cache)))

            def run():
                ent["data"] = synth(text)
                ent["ev"].set()

            threading.Thread(target=run, daemon=True).start()
        return ent


# ---------- Wetter & Begrüßung (ohne Token) ----------
WMO = {0: "klarer Himmel", 1: "überwiegend klar", 2: "teilweise bewölkt", 3: "bedeckt", 45: "neblig",
       48: "Nebel mit Reif", 51: "leichter Nieselregen", 53: "Nieselregen", 55: "starker Nieselregen",
       56: "gefrierender Nieselregen", 57: "gefrierender Nieselregen", 61: "leichter Regen", 63: "Regen",
       65: "starker Regen", 66: "gefrierender Regen", 67: "gefrierender Regen", 71: "leichter Schneefall",
       73: "Schneefall", 75: "starker Schneefall", 77: "Schneegriesel", 80: "leichte Regenschauer",
       81: "Regenschauer", 82: "heftige Regenschauer", 85: "Schneeschauer", 86: "starke Schneeschauer",
       95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Gewitter mit Hagel"}
_loc = {}


def http_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "ORB/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def location(cfg):
    key = (cfg.get("ort") or "").strip()
    if key in _loc:
        return _loc[key]
    loc = None
    if key:
        d = http_json("https://geocoding-api.open-meteo.com/v1/search?count=1&language=de&name=" + urllib.parse.quote(key))
        r = (d.get("results") or [None])[0]
        if r:
            loc = (r["latitude"], r["longitude"], r["name"])
    else:  # Standort grob über die Internetverbindung
        d = http_json("http://ip-api.com/json/?lang=de&fields=status,city,lat,lon")
        if d.get("status") == "success":
            loc = (d["lat"], d["lon"], d.get("city", ""))
    if loc:
        _loc[key] = loc
    return loc


def zahl(x):
    n = round(x)
    return "minus %d" % -n if n < 0 else str(n)


_wcache = {"t": 0.0, "d": None}


def weather_data():
    """Wetter als Zahlen (5 Min. zwischengespeichert)."""
    if _wcache["d"] and time.time() - _wcache["t"] < 300:
        return _wcache["d"]
    loc = location(load_cfg())
    if not loc:
        return None
    lat, lon, city = loc
    w = http_json("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&current=temperature_2m,"
                  "weather_code,is_day&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                  "&hourly=temperature_2m,weather_code&forecast_hours=7&timezone=auto&forecast_days=1" % (lat, lon))
    c, d = w["current"], w["daily"]
    hr = w.get("hourly") or {}
    hourly = [{"h": tm[11:13], "t": tt, "c": int(cc)} for tm, tt, cc in
              zip(hr.get("time", []), hr.get("temperature_2m", []), hr.get("weather_code", []))][1:7]
    data = {"city": city, "temp": c["temperature_2m"], "code": int(c["weather_code"]), "day": c.get("is_day", 1),
            "desc": WMO.get(int(c["weather_code"]), ""), "min": d["temperature_2m_min"][0], "hourly": hourly,
            "max": d["temperature_2m_max"][0], "rain": (d.get("precipitation_probability_max") or [None])[0]}
    _wcache.update(t=time.time(), d=data)
    return data


import random


def rain_note(p):
    if p is None or p < 30:
        return ""
    return random.choice([" Schirm einpacken.", " Regen ist so gut wie sicher."]) if p >= 70 else " Kann regnen."


def weather_text():
    try:
        w = weather_data()
        if not w:
            return "Ich weiß nicht, wo du bist – trag deinen Ort in den Einstellungen ein."
        t = "%s Grad%s in %s, heute bis %s." % (zahl(w["temp"]), " und " + w["desc"] if w["desc"] else "", w["city"], zahl(w["max"]))
        return t + rain_note(w["rain"])
    except Exception as e:
        print("Wetter-Fehler:", e)
        return "Das Wetter krieg ich gerade nicht rein."


def greeting():
    cfg, h = load_cfg(), datetime.datetime.now().hour
    name = (cfg.get("name") or "").strip()
    n = ", " + name if name else ""
    gruss = random.choice(
        ["Na, du Nachteule%s." % n, "Noch wach%s?" % n] if h < 5 else
        ["Morgen%s!" % n, "Guten Morgen%s." % n, "Moin%s!" % n] if h < 11 else
        ["Hey%s!" % n, "Da bist du ja%s." % n, "Hi%s!" % n] if h < 18 else
        ["Guten Abend%s." % n, "Hey%s, schönen Abend." % n] if h < 23 else
        ["Spät dran heute%s." % n, "Na%s, noch fit?" % n])
    try:
        w = weather_data()
        wx = " Draußen %s Grad%s." % (zahl(w["temp"]), ", " + w["desc"] if w["desc"] else "") if w else ""
        wx += rain_note(w["rain"]) if w else ""
    except Exception:
        wx = ""
    return gruss + wx + " " + random.choice(["Was steht an?", "Was brauchst du?", "Womit legen wir los?", "Was kann ich tun?"])


# ---------- Apps öffnen (ohne Token) ----------
_apps = {"list": [], "time": 0.0}
_apps_lock = threading.Lock()
ALIASES = {"rechner": "rechner", "taschenrechner": "rechner", "explorer": "datei-explorer",
           "dateien": "datei-explorer", "datei explorer": "datei-explorer", "einstellungen": "einstellungen",
           "notepad": "editor", "browser": "opera gx", "opera": "opera gx", "taskmanager": "task-manager",
           "task manager": "task-manager", "word": "word", "excel": "excel", "powerpoint": "powerpoint"}
SITES = {"youtube": "https://www.youtube.com", "google": "https://www.google.de", "netflix": "https://www.netflix.com",
         "twitch": "https://www.twitch.tv", "gmail": "https://mail.google.com", "tiktok": "https://www.tiktok.com",
         "instagram": "https://www.instagram.com", "amazon": "https://www.amazon.de", "github": "https://github.com",
         "claude": "https://claude.ai", "whatsapp web": "https://web.whatsapp.com", "chatgpt": "https://chatgpt.com",
         "google maps": "https://maps.google.de", "maps": "https://maps.google.de"}


def load_apps(force=False):
    with _apps_lock:
        if not force and _apps["list"] and time.time() - _apps["time"] < 600:
            return _apps["list"]
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                                "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
                               capture_output=True, timeout=30, creationflags=NO_WINDOW)
            data = json.loads(r.stdout.decode("utf-8", "ignore") or "[]")
            if isinstance(data, dict):
                data = [data]
            _apps.update(list=[(a["Name"], a["AppID"]) for a in data if a.get("Name") and a.get("AppID")],
                         time=time.time())
        except Exception as e:
            print("App-Liste:", e)
        return _apps["list"]


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9äöüß\- ]", "", s.lower())).strip()


def find_app(q):
    qn = norm(q)
    qn = ALIASES.get(qn, qn)
    best, score = None, 0.0
    for name, aid in load_apps():
        n = norm(name)
        if n == qn:
            s = 1.0
        elif n.startswith(qn + " ") or (qn.startswith(n) and len(n) > 3):
            s = .9
        elif qn in n.split() or (len(qn) > 3 and qn in n):
            s = .8
        else:
            s = difflib.SequenceMatcher(None, qn, n).ratio()
        if any(w in n for w in ("uninstall", "deinstall", "hilfe", "help", "readme")):
            s -= .5
        if s > score:
            best, score = (name, aid), s
    return best if score >= .72 else None


def launch(target):
    if re.match(r"https?://", target) or os.path.exists(target):
        os.startfile(target)
    else:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + target], creationflags=NO_WINDOW)


OPEN_RE = [
    re.compile(r"^(?:hey\s+|orb,?\s+)?(?:bitte\s+)?(?:öffne|öffnen|starte|starten|mach|mache)\s+(?:mir\s+)?(?:bitte\s+)?"
               r"(?:mal\s+)?(.+?)(?:\s+(?:auf|an|bitte))?[\s.!?]*$", re.I),
    re.compile(r"^(?:kannst|könntest|würdest)\s+du\s+(?:mir\s+)?(?:bitte\s+)?(?:mal\s+)?(.+?)\s+"
               r"(?:öffnen|starten|aufmachen)(?:\s+bitte)?[\s.!?]*$", re.I),
]
ARTICLE = re.compile(r"^(?:die\s+app\s+|das\s+programm\s+|den\s+|die\s+|das\s+|der\s+|meinen\s+|meine\s+|mein\s+)", re.I)
WEATHER_RE = re.compile(r"\b(wetter|wie (warm|kalt) ist es|regnet es|wird es regnen)\b", re.I)
GOLD_RE = re.compile(r"\b(gold|goldpreis|goldkurs|xau(?:\s*/?\s*usd)?)\b", re.I)
GOLD = {"n": 0, "preis": None, "zeit": 0.0, "lock": threading.Lock()}   # Gold-Hologramm auf Zuruf


def gold_quelle():
    """XAU/USD live: Swissquote-Kursfeed (Geld/Brief, ändert sich jede Sekunde), sonst gold-api.com."""
    try:
        req = urllib.request.Request("https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD",
                                     headers={"User-Agent": "Mozilla/5.0 (ORB)"})
        with urllib.request.urlopen(req, timeout=3) as r:
            feeds = json.loads(r.read().decode("utf-8"))
        # immer dieselbe Plattform nehmen, sonst springt der Kurs zwischen den Anbietern hin und her
        f = next((x for x in feeds if (x.get("topo") or {}).get("platform") == "SwissquoteLtd"), feeds[0])
        q = f["spreadProfilePrices"][0]
        return round((float(q["bid"]) + float(q["ask"])) / 2, 2)
    except Exception as e:
        print("Goldkurs (Swissquote):", e)
    req = urllib.request.Request("https://api.gold-api.com/price/XAU", headers={"User-Agent": "ORB"})
    with urllib.request.urlopen(req, timeout=6) as r:
        return float(json.loads(r.read().decode("utf-8"))["price"])


def gold_preis():
    """XAU/USD-Spotpreis, höchstens etwa einmal pro Sekunde neu abgefragt (Hologramm tickt sekündlich)."""
    with GOLD["lock"]:
        if GOLD["preis"] is not None and time.time() - GOLD["zeit"] < .8:
            return GOLD["preis"]
        GOLD["preis"] = gold_quelle()
        GOLD["zeit"] = time.time()
        return GOLD["preis"]


def gold_text():
    GOLD["n"] += 1   # Oberfläche öffnet das Live-Hologramm
    try:
        p = gold_preis()
    except Exception as e:
        print("Goldkurs:", e)
        return "Den Goldkurs bekomme ich gerade nicht."
    d, c = divmod(int(round(p * 100)), 100)
    zahl = "{:,}".format(d).replace(",", ".")
    return ("Gold steht bei %s Dollar %d." % (zahl, c)) if c else ("Gold steht bei %s Dollar." % zahl)


def try_local(text):
    """Schnelle Aufträge ohne Claude: Apps/Webseiten öffnen, Wetter. Gibt (Aufgabe, Detail, Antwort) oder None."""
    t = text.strip()
    if WEATHER_RE.search(t) and len(t) < 70 and not re.search(r"\b(morgen|woche|wochenende)\b", t, re.I):
        return "Wetter abrufen", "", weather_text()
    if GOLD_RE.search(t) and len(t) < 50 and not re.search(r"\b(öffne|starte|kaufen|verkaufen|ring|kette|schmuck|warum|wieso|wird|prognose|analyse|meinst|news|nachrichten)\b", t, re.I):
        return "Goldkurs", "XAU/USD", gold_text()
    for rx in OPEN_RE:
        m = rx.match(t)
        if m:
            break
    else:
        return None
    opened, missing = [], []
    for part in re.split(r"\s+und\s+|,\s*", m.group(1)):
        p = ARTICLE.sub("", part.strip())
        key = norm(p)
        if not key:
            continue
        if key in SITES:
            launch(SITES[key]); opened.append(p); continue
        if re.fullmatch(r"[\w.-]+\.(de|com|net|org|io|tv|ai|eu)", key.replace(" ", "")):
            launch("https://" + key.replace(" ", "")); opened.append(p); continue
        app = find_app(p)
        if app:
            launch(app[1]); opened.append(app[0])
        else:
            missing.append(p)
    if not opened:
        return None  # nichts erkannt -> Claude soll es versuchen
    a = " und ".join(opened)
    say = random.choice(["%s kommt." % a, "Mach ich.", "%s ist offen." % a, "Klar, %s." % a, "Läuft."])
    if missing:
        say += " " + " und ".join(missing) + " find ich hier nicht."
    return "Öffne", ", ".join(opened), say


# ---------- Gespräch mit Claude ----------
def find_claude():
    """Immer Larsens Claude Code unter %USERPROFILE%/.local/bin – nicht eine andere installierte Version (z. B. WinGet)."""
    eigen = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    return eigen if os.path.isfile(eigen) else (shutil.which("claude") or eigen)


class Brain:
    """Ein dauerhaft laufendes Claude (Opus 5.5 über Larsens Claude-Code-Login).
    Spart den Kaltstart bei jeder Frage und liefert die Antwort Wort für Wort, damit ORB sofort sprechen kann."""

    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.busy = False
        self.stopped = False
        self.buf = ""          # Text der aktuellen Antwort, der noch nicht gesprochen wurde
        self.spoken = []       # schon ausgegebene Sprech-Stücke
        self.full = ""
        self.aid = ""
        self.last_used = 0.0
        self.last_out = 0.0     # letzte Ausgabe des Gehirns (für den Hänger-Wächter)
        self.gmail = False      # claude.ai-Gmail-Connector in dieser Sitzung verbunden?
        self.gmail_retry = 0.0  # letzter Neustart, um Gmail neu zu verbinden

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.alive():
            return
        cfg = load_cfg()
        args = [find_claude(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                "--include-partial-messages", "--verbose", "--model", cfg["modell"],
                "--permission-mode", cfg["rechte"], "--effort", cfg.get("tempo_claude") or "low"]
        if cfg.get("sitzung"):
            args += ["--resume", cfg["sitzung"]]
        args += ["--append-system-prompt", system_prompt(cfg)]
        ordner = cfg["ordner"] if os.path.isdir(cfg["ordner"]) else os.path.expanduser("~")
        env = {k: v for k, v in os.environ.items() if k not in CLAUDE_ENV_DROP}
        env["ORB_RUN"] = "1"
        # claude.ai-Connectoren (Gmail, Drive) beim Start abwarten statt nur im Hintergrund zu verbinden
        env.setdefault("MCP_CONNECTION_NONBLOCKING", "false")
        self.gmail = False
        self.proc =subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     cwd=ordner, env=env, creationflags=NO_WINDOW)
        self.started_with_session = bool(cfg.get("sitzung"))
        threading.Thread(target=self.reader, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self.err_reader, args=(self.proc,), daemon=True).start()

    def kill(self):
        p = self.proc
        self.proc = None
        if p and p.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, creationflags=NO_WINDOW)

    def send(self, text):
        with self.lock:
            if self.busy:
                return False
            # Mail-Frage, aber Gmail-Connector nicht verbunden (Abruf bei claude.ai schlägt manchmal fehl und
            # wird in einer laufenden Sitzung nie wiederholt) -> Gehirn neu starten, die Unterhaltung bleibt erhalten.
            if MAIL_WORT.search(text) and self.alive() and not self.gmail and time.time() - self.gmail_retry > 60:
                self.gmail_retry = time.time()
                self.kill()
            self.start()
            self.busy, self.stopped = True, False
            self.buf, self.full, self.spoken, self.aid = "", "", [], new_aid()
            self.last_used = self.last_out = time.time()
            write_state(mode="denkt", heard=text, log=[], task="", detail="", say="", parts=[], aid=self.aid, final=False, holo=None)
            if load_cfg().get("bildschirm"):
                try:   # Live-Bild (alle 1,5 s frisch) – keine Wartezeit mehr vor der Antwort
                    alter = time.time() - LIVE["t"]
                    text = ("[Bildschirm live: %s (%.0f s alt, Klick-Maßstab %.2f) – nur ansehen, wenn die Frage den Bildschirm "
                            "betrifft; für Klicks diese Bild-Koordinaten an steuern.ps1 geben.]\n" % (LIVE_BILD, alter, LIVE["massstab"])) + text
                except Exception as e:
                    print("Screenshot:", e)
            if skin_still():
                text = ("[Stiller Skin-Modus: Larsen will beim Skin-Bauen keine gesprochenen Antworten, bis er „wir sind "
                        "fertig“ sagt. Arbeite normal weiter (Skin bauen/ändern, 3D-Hologramm aktualisieren) und antworte "
                        "nur mit einem Wort wie „Okay.“ – nichts erklären.]\n" + text)
            if kamera_aktiv():
                text = ("[Kamera ist an – Standbild nur auf ausdrückliche Frage über kamera.ps1. Gezeigtes erscheint in der "
                        "Kamera-Ansicht, Widgets/3D-Objekte über kamera_zeigen.ps1.]\n" + text)
            msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
            try:
                self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
                self.proc.stdin.flush()
            except Exception as e:
                print("Senden an Claude fehlgeschlagen:", e)
                self.busy = False
                self.kill()
                write_answer("Ich konnte mein Gehirn gerade nicht erreichen. Versuch es bitte noch einmal.")
            return True

    def flush(self, final=False):
        """Fertige Sätze aus dem Puffer als Sprech-Stücke ausgeben."""
        t = self.buf
        if t.count("```") % 2 == 1 and not final:
            return  # mitten in einem Codeblock – warten
        if final:
            ready, rest = t, ""
        else:
            # Satzgrenzen ohne Abkürzungen/Datumsangaben; Komma nur bei einem sehr langen ersten Satz (sonst klingt es zerhackt)
            g = satz_grenzen(t) or (satz_grenzen(t, komma=True) if not self.spoken and len(t) >= 90 else [])
            if not g:
                return
            ready, rest = t[: g[-1]], t[g[-1]:]
            # erstes Stück so früh wie möglich, danach größere Stücke für flüssigen Klang
            if len(ready.strip()) < (12 if not self.spoken else 260):
                return
        said = clean(ready)
        self.buf = rest
        if said:
            self.spoken.append(said)
            self.full = (self.full + " " + said).strip()
            write_state(say=self.full, parts=list(self.spoken), aid=self.aid, final=final,
                        **({} if read_state().get("mode") == "auftrag" else {"mode": "spricht"}))
            if not skin_still():
                ensure((self.aid, len(self.spoken) - 1), said)  # Stimme sofort vorbereiten
        elif final:
            write_state(final=True)

    def finish_turn(self, text_if_empty):
        self.flush(final=True)
        if not self.spoken:
            write_answer(text_if_empty)
        else:
            write_state(mode="spricht", final=True)
        self.busy = False

    def reader(self, proc):
        for raw in proc.stdout:
            if proc is not self.proc:
                break   # alter Prozess (nach Neustart/„Neue Unterhaltung“) – nichts mehr anfassen
            try:
                o = json.loads(raw.decode("utf-8", "ignore"))
            except Exception:
                continue
            try:
                self.handle(o)
            except Exception as e:
                print("Gehirn-Ausgabe:", e)
        if proc is not self.proc:
            return
        # Prozess beendet
        if self.busy:
            self.busy = False
            if self.stopped:
                write_answer("Okay, abgebrochen.")
            elif self.started_with_session and not self.spoken:
                save_cfg({"sitzung": ""})  # alte Unterhaltung unbrauchbar -> nächstes Mal frisch
                write_answer("Ich musste neu starten. Sag es bitte noch einmal.")
            else:
                write_answer("Da ist leider etwas schiefgelaufen.")

    def handle(self, o):
        self.last_out = time.time()
        if True:
            typ = o.get("type")
            if typ == "system" and o.get("subtype") == "init" and o.get("session_id"):
                self.gmail = any("gmail" in str(s.get("name", "")).lower() and s.get("status") == "connected"
                                 for s in (o.get("mcp_servers") or []) if isinstance(s, dict))
                save_cfg({"sitzung": o["session_id"]})
            elif typ == "stream_event" and self.busy:
                ev = o.get("event") or {}
                if ev.get("type") == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
                    self.buf += ev["delta"].get("text", "")
                    self.flush()
                elif ev.get("type") == "message_stop":
                    self.buf += "\n"
                    self.flush()
            elif typ == "result":
                if o.get("session_id"):
                    save_cfg({"sitzung": o["session_id"]})
                if o.get("is_error") and not self.spoken:
                    print("Claude-Fehler:", str(o.get("result"))[:300])
                    self.finish_turn("Da ist leider etwas schiefgelaufen.")
                else:
                    self.finish_turn("Erledigt.")

    def err_reader(self, proc):
        for raw in proc.stderr:
            line = raw.decode("utf-8", "ignore").strip()
            if line:
                print("[claude]", line[:300])

    def stop(self):
        if self.busy and self.alive():
            self.stopped = True
            self.kill()
            self.busy = False
            write_answer("Okay, abgebrochen.")
            return True
        return False


BRAIN = Brain()


# ---------- Fremden-Sperre (gesicht.py): fremdes Gesicht → ORB unsichtbar, stumm, nicht aufrufbar ----------
GESICHT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "gesicht")
FREMD = {"t": 0.0, "an": False}


def fremd_gesperrt():
    """Sperrt der Gesichts-Wächter ORB gerade (sperre.json mit seiner PID)? Läuft der Wächter nicht mehr,
    gilt die Sperre nicht – so kann ein abgestürzter Wächter Larsen nie aussperren. 1 s zwischengespeichert."""
    if time.time() - FREMD["t"] < 1:
        return FREMD["an"]
    an = False
    try:
        with open(os.path.join(GESICHT_DIR, "sperre.json"), encoding="utf-8") as f:
            pid = int(json.load(f).get("pid", 0))
        import psutil
        an = bool(pid) and "gesicht.py" in " ".join(psutil.Process(pid).cmdline())
    except Exception:
        an = False
    FREMD.update(t=time.time(), an=an)
    return an


def weckversuch():
    """Jemand will ORB holen (Klatschen, „Jarvis“, ORB.exe) → der Wächter scannt sofort neu: ist es Larsen, geht die Sperre auf."""
    try:
        with open(os.path.join(GESICHT_DIR, "weckversuch"), "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass


# ---------- Tarnmodus: PC wirkt aus, Meetings/Downloads/ORB/Telegram laufen weiter (tarnmodus.py) ----------
TARN_RE = re.compile(r"\btarn[\s-]*modus\b", re.I)
TARN_AUS = re.compile(r"\b(aus\w*|beend\w*|stopp?\w*|deaktiv\w*|ende|verlass\w*)\b", re.I)
TARN_AN = re.compile(r"\b(an|ein\w*|aktiv\w*|start\w*|geh\w*|mach\w*|schalt\w*|wechsel\w*)\b", re.I)
TARN_VORHER = {"sichtbar": False}


def tarn_befehl(text):
    """„Tarnmodus an/aus“ (Sprache oder Telegram) → True/False, sonst None. Fragen über den Tarnmodus gehen an Claude."""
    t = re.sub(r"^\[[^\]]*\]\s*", "", text.strip())   # Telegram-Hinweis vorne weg
    t = re.sub(r"^(hey\s+)?(jarvis|orb)[,\s]+", "", t, flags=re.I)
    if not TARN_RE.search(t) or len(t) > 60 or "?" in t or re.search(r"\b(was|wie|warum|wieso|erklär)", t, re.I):
        return None
    rest = TARN_RE.sub(" ", t)
    if TARN_AUS.search(rest):
        return False
    if TARN_AN.search(rest) or not rest.strip(" ,.!"):
        return True
    return None


def tarn_ende(grund):
    """Läuft im Tarnmodus-Thread, wenn er endet (Befehl oder Larsen am PC)."""
    print("Tarnmodus aus:", grund)
    if TARN_VORHER["sichtbar"] and ON_SHOW[0]:
        try:
            ON_SHOW[0]()
        except Exception as e:
            print("Tarnmodus Fenster:", e)
    text = ("Tarnmodus beendet – jemand hat am PC Maus oder Tastatur benutzt." if grund == "pc"
            else "Tarnmodus ist aus, alles wieder wie vorher.")
    write_state(mode="idle", tarn=False, say=text, parts=[], aid=new_aid(), final=True, holo=None)


def tarn_schalten(an, heard=""):
    if an:
        if tarnmodus.aktiv():
            write_answer("Der Tarnmodus läuft schon.", heard=heard)
            return
        TARN_VORHER["sichtbar"] = time.time() - LAST_WACH[0] < 3   # Fenster war sichtbar → danach wieder zeigen
        write_state(mode="idle", tarn=True, heard=heard, say="Tarnmodus an. Der PC wirkt aus, alles läuft weiter.",
                    parts=[], aid=new_aid(), final=True, holo=None)
        if ON_HIDE[0]:
            try:
                ON_HIDE[0](keep=True)   # nur ausblenden: die Seite hört weiter auf „Tarnmodus aus“
            except Exception as e:
                print("Tarnmodus Fenster:", e)
        tarnmodus.starten(tarn_ende)
        print("Tarnmodus an")
    elif not tarnmodus.beenden():
        write_answer("Der Tarnmodus ist gar nicht an.", heard=heard)


# ---------- Komplett ausschalten & Pausemodus (feste Befehle – das Gesprächs-Gehirn darf ORB nicht beenden) ----------
AUS_RE = re.compile(r"^/(aus|beenden)\b|\b(schalt\w*|mach\w*|fahr\w*)\s+(dich|orb|jarvis)\s+(jetzt\s+)?(komplett|ganz|vollständig)\s+(aus|runter|ab)\b"
                    r"|\b(beende|schließe?)\s+dich\s+(jetzt\s+)?(komplett|ganz|vollständig)\b"
                    r"|^(orb|jarvis)?\s*(komplett|ganz|vollständig)\s+(ausschalten|beenden|aus)\W*$", re.I)
PAUSE_RE = re.compile(r"\b(pause[n-]?modus|stumm[\s-]*modus|zuhör[\s-]*pause)\b", re.I)
PAUSE = {"an": False}
HANDY = {"t": 0.0}   # letzte Nachricht per Telegram: dann am PC weder Stimme noch Klänge (Antwort geht nur aufs Handy)


def handy_still():
    """True, solange das Gespräch übers Handy läuft (15 Min. wie die Telegram-Weiterleitung, bis Larsen am PC spricht/tippt)."""
    return time.time() - HANDY["t"] < 900


def befehl_text(text):
    t = re.sub(r"^\[[^\]]*\]\s*", "", text.strip())   # Telegram-Hinweis vorne weg
    return re.sub(r"^(hey\s+)?(jarvis|orb)[,\s]+", "", t, flags=re.I).strip()


def aus_befehl(text):
    t = befehl_text(text)
    return len(t) <= 60 and "?" not in t and bool(AUS_RE.search(t))


def pause_befehl(text):
    """„/pause“, „/weiter“, „Pausemodus an/aus“, „hör nicht zu“ / „hör wieder zu“ → True/False, sonst None."""
    t = befehl_text(text)
    if len(t) > 60 or "?" in t:
        return None
    if re.match(r"^/pause\b", t, re.I) or re.search(r"\bhör\w*\s+(mir\s+)?(jetzt\s+)?nicht\s+(mehr\s+)?zu\b", t, re.I):
        return True
    if re.match(r"^/weiter\b", t, re.I) or re.search(r"\bhör\w*\s+(mir\s+)?(jetzt\s+)?wieder\s+zu\b", t, re.I):
        return False
    if not PAUSE_RE.search(t) or re.search(r"\b(was|wie|warum|wieso|erklär)", t, re.I):
        return None
    rest = PAUSE_RE.sub(" ", t)
    if TARN_AUS.search(rest):
        return False
    if TARN_AN.search(rest) or not rest.strip(" ,.!"):
        return True
    return None


def telegram_nachricht(text):
    """Kurze Nachricht direkt aufs Handy (unabhängig davon, ob Larsen gerade per Telegram schreibt)."""
    try:
        with open(os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "telegram.json"), encoding="utf-8") as f:
            c = json.load(f)
        if c.get("token") and c.get("chat_id"):
            daten = urllib.parse.urlencode({"chat_id": c["chat_id"], "text": text}).encode()
            urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % c["token"], data=daten, timeout=8).read()
            return True
    except Exception as e:
        print("Telegram-Nachricht:", e)
    return False


def orb_aus(heard=""):
    """ORB komplett beenden (inkl. Ohr, Stimme, Telegram) – vorher Bestätigung per Telegram."""
    per_telegram = heard.startswith("[Per Telegram")
    print("Komplett aus auf Befehl:", heard[:80])
    BRAIN.kill()
    telegram_nachricht("ORB schaltet sich jetzt komplett aus. Wieder an: ORB.exe am PC starten (oder beim nächsten PC-Start).")
    if per_telegram:   # nicht über die Weiterleitung schicken – die Bestätigung ist schon da
        write_state(mode="idle", heard=heard, say="ORB schaltet sich aus.", parts=[], aid="", final=False)
    else:
        write_answer("Okay, ich schalte mich komplett aus. Bis später.", heard=heard, laut=True)

    def ende():
        time.sleep(1.5 if per_telegram else 6)   # Ansage noch ausreden lassen
        try:
            tarnmodus.aufraeumen()
        except Exception:
            pass
        clean_exit("Beendet: Befehl „komplett aus“" + (" (Telegram)" if per_telegram else ""))
    threading.Thread(target=ende, daemon=True).start()


def pause_schalten(an, heard=""):
    if an == PAUSE["an"]:
        write_answer("Der Pausemodus ist schon " + ("an." if an else "aus."), heard=heard)
        return
    PAUSE["an"] = an
    print("Pausemodus", "an" if an else "aus")
    write_answer("Pausemodus an. Ich reagiere nicht mehr auf Stimmen, per Telegram oder Tippen bin ich weiter da. "
                 "Beenden mit /weiter." if an else "Pausemodus aus, ich höre wieder zu.", heard=heard)


def ask(text):
    HANDY["t"] = time.time() if text.startswith("[Per Telegram") else 0.0
    if aus_befehl(text):
        orb_aus(text)
        return True
    pb = pause_befehl(text)
    if pb is not None:
        pause_schalten(pb, text)
        return True
    tb = tarn_befehl(text)
    if tb is not None:
        tarn_schalten(tb, text)
        return True
    if skin_still() and SKIN_FERTIG.search(text):   # Skin-Arbeit beendet: wieder normal sprechen
        skin_still(False)
        write_answer("Alles klar, ich rede wieder.", heard=text, laut=True)
        return True
    if SKIN_WORT.search(text):
        skin_still(True)
    try:
        local = try_local(text)
    except Exception as e:
        print("Lokaler Auftrag fehlgeschlagen:", e)
        local = None
    if local and BRAIN.busy:
        return "lokal"   # schon ausgeführt – die laufende Antwort nicht unterbrechen
    if local:
        task, detail, say = local
        write_state(mode="auftrag", heard=text, task=task, detail=detail, say="", parts=[], aid="",
                    log=[task + (": " + detail if detail else "")])

        def done():
            time.sleep(.6)  # kurz die Hologramm-Animation zeigen
            write_answer(say, holo=holo_for(task, detail))

        threading.Thread(target=done, daemon=True).start()
        return True
    if BRAIN.busy:
        worte = re.sub(r"^(jarvis|orb)[,\s]+", "", text, flags=re.I).split()
        titel = " ".join(worte[:4]).strip(" ,.!?") or "Aufgabe"
        task_start(titel[:1].upper() + titel[1:], text)
        return "parallel"
    return BRAIN.send(text)


def stop():
    return BRAIN.stop()


TERMIN_RE = re.compile(r"^\s*[-*]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})(?:\s+(\d{1,2}[:.]\d{2}))?\s*[-–:]?\s*(.+)$")


def termine():
    if icloud.verbunden():
        return icloud.termine_widget()
    return termine_md()


def termine_md():
    """Liest <ordner>/termine.md – Zeilen wie '- 14.11.2026 15:00 Zahnarzt'. Liefert die nächsten Termine."""
    path = os.path.join(load_cfg()["ordner"], "termine.md")
    out, heute = [], datetime.date.today()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = TERMIN_RE.match(line)
                if not m:
                    continue
                d = m.group(1)
                try:
                    day = (datetime.date.fromisoformat(d) if "-" in d
                           else datetime.datetime.strptime(d, "%d.%m.%Y").date())
                except ValueError:
                    continue
                if day < heute:
                    continue
                zeit = (m.group(2) or "").replace(".", ":")
                out.append({"datum": day.isoformat(), "zeit": zeit, "text": m.group(3).strip()})
    except OSError:
        pass
    out.sort(key=lambda x: (x["datum"], x["zeit"] or "99"))
    return out[:6]


def _icloud_fehler(e):
    if isinstance(e, urllib.error.HTTPError):
        return {"ok": False, "fehler": "iCloud antwortet mit Fehler %d" % e.code}
    return {"ok": False, "fehler": str(e)}


def erinnerungen_aktion(b):
    if not icloud.verbunden():
        return {"ok": False, "fehler": "iCloud ist nicht verbunden (ORB-Einstellungen > iCloud-Kalender)"}
    try:
        a = str(b.get("aktion", "")).lower()
        if a == "liste":
            return {"ok": True, "erinnerungen": icloud.erinnerungen(b.get("liste", ""), bool(b.get("alle")))}
        if a == "neu":
            if not b.get("titel"):
                return {"ok": False, "fehler": "titel nötig"}
            return {"ok": True, "erinnerung": icloud.erinnerung_neu(b["titel"], b.get("faellig"), b.get("liste", ""),
                                                                    b.get("notiz", ""), bool(b.get("wichtig")))}
        if a == "erledigt":
            return {"ok": icloud.erinnerung_erledigt(str(b.get("id", "")), not b.get("offen"))}
        if a == "loeschen":
            return {"ok": icloud.erinnerung_loeschen(str(b.get("id", "")))}
        return {"ok": False, "fehler": "aktion muss liste, neu, erledigt oder loeschen sein"}
    except Exception as e:
        return _icloud_fehler(e)


def kontakte_aktion(b):
    if not icloud.verbunden():
        return {"ok": False, "fehler": "iCloud ist nicht verbunden (ORB-Einstellungen > iCloud-Kalender)"}
    try:
        a = str(b.get("aktion", "")).lower()
        felder = {k: b.get(k) for k in ("telefon", "email", "firma", "adresse", "geburtstag", "notiz")}
        if a == "suche":
            treffer, n = icloud.kontakte_suche(b.get("text", ""))
            res = {"ok": True, "kontakte": treffer, "anzahl": n}
            if n > len(treffer):
                res["hinweis"] = "Nur die ersten %d von %d Treffern – genauer suchen" % (len(treffer), n)
            return res
        if a == "neu":
            if not b.get("name"):
                return {"ok": False, "fehler": "name nötig"}
            return {"ok": True, "kontakt": icloud.kontakt_neu(b["name"], **felder)}
        if a == "aendern":
            return {"ok": True, "kontakt": icloud.kontakt_aendern(str(b.get("id", "")), name=b.get("name"),
                                                                 dazu=bool(b.get("dazu")), **felder)}
        if a == "loeschen":
            if b.get("bestaetigt") is not True:
                return {"ok": False, "fehler": "Löschen nur nach Larsens ausdrücklicher Bestätigung (-Bestaetigt)"}
            return {"ok": icloud.kontakt_loeschen(str(b.get("id", "")))}
        return {"ok": False, "fehler": "aktion muss suche, neu, aendern oder loeschen sein"}
    except Exception as e:
        return _icloud_fehler(e)


def kalender_aktion(b):
    if not icloud.verbunden():
        return {"ok": False, "fehler": "iCloud ist nicht verbunden (ORB-Einstellungen > iCloud-Kalender)"}
    try:
        a = str(b.get("aktion", "")).lower()
        if a == "neu":
            if not b.get("titel") or not b.get("start"):
                return {"ok": False, "fehler": "titel und start nötig"}
            return {"ok": True, "termin": icloud.neu(b["titel"], b["start"], b.get("ende"), b.get("ort", ""),
                                                    b.get("notiz", ""), b.get("kalender", ""))}
        if a == "liste":
            von = icloud._parse(b["von"])[0] if b.get("von") else None
            bis = icloud._parse(b["bis"])[0] + datetime.timedelta(days=1) if b.get("bis") else None
            if von and not bis:
                bis = von + datetime.timedelta(days=30)
            return {"ok": True, "termine": icloud.liste(von, bis)}
        if a == "loeschen":
            return {"ok": icloud.loeschen(str(b.get("id", "")))}
        return {"ok": False, "fehler": "aktion muss neu, liste oder loeschen sein"}
    except Exception as e:
        return {"ok": False, "fehler": str(e)}


def spotify_now():
    """Aktueller Spotify-Titel aus dem Fenstertitel ('Künstler - Titel'); pausiert = 'Spotify …'."""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    titles = []

    def cb(hwnd, _):   # auch versteckte Fenster: Spotify minimiert/im Infobereich behält seinen Titel „Künstler - Titel“
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = k32.OpenProcess(0x1000, False, pid.value)
        if h:
            buf = ctypes.create_unicode_buffer(260)
            n = wintypes.DWORD(260)
            ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
            k32.CloseHandle(h)
            if ok and buf.value.lower().endswith("spotify.exe"):
                ln = u32.GetWindowTextLengthW(hwnd)
                if ln:
                    t = ctypes.create_unicode_buffer(ln + 1)
                    u32.GetWindowTextW(hwnd, t, ln + 1)
                    titles.append(t.value)
        return True

    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    titles = [x for x in titles if x not in ("Default IME", "MSCTFIME UI", "GDI+ Window", "G", "Chrome Legacy Window")
              and not x.startswith(("GDI+", "Spotify Widevine", "CicMarshalWnd"))]
    if not titles:
        return {"laeuft": False}
    t = next((x for x in titles if " - " in x), next((x for x in titles if x.startswith("Spotify")), titles[0]))
    if " - " not in t:
        return {"laeuft": True, "spielt": False}
    kuenstler, titel = t.split(" - ", 1)
    return {"laeuft": True, "spielt": True, "kuenstler": kuenstler, "titel": titel}


# ---------- Musik erkennen und leiser stellen (Windows-Core-Audio über ctypes, ohne Zusatzpakete) ----------
_AUDIO_LOCK = threading.Lock()
_MUSIK = {"t": 0.0, "an": False, "laut_t": 0.0, "quelle": ""}
_DUCK = {"vol": {}, "t": 0.0}
_EIGENE = {"t": 0.0, "pids": set()}
_PNAMEN = {}


def _guid(s):
    import ctypes
    import uuid
    g = (ctypes.c_ubyte * 16)()
    ctypes.memmove(g, uuid.UUID(s).bytes_le, 16)
    return g


def _vcall(p, idx, argtypes, *args):
    import ctypes
    vt = ctypes.cast(p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vt[idx])(p, *args)


def _audio_sessions(fn):
    """Ruft fn(pid, aktiv, pegel, volume) für jede Audio-Sitzung am Standard-Ausgang auf (Systemklänge ausgenommen)."""
    import ctypes
    from ctypes import POINTER, byref, c_float, c_int, c_ulong, c_void_p
    ole = ctypes.windll.ole32
    ole.CoInitializeEx(None, 0)
    ole.CoCreateInstance.argtypes = [c_void_p, c_void_p, c_ulong, c_void_p, POINTER(c_void_p)]
    g = {k: _guid(v) for k, v in {
        "clsid": "BCDE0395-E52F-467C-8E3D-C4579291692E", "enum": "A95664D2-9614-4F35-A746-DE8DB63617E6",
        "mgr": "77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F", "ctl2": "BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D",
        "vol": "87CE5498-68D6-44E5-9215-6DA47EF883D8", "met": "C02216F6-8C67-4B5B-9D00-D008E73E0064"}.items()}
    A = lambda k: ctypes.addressof(g[k])  # noqa: E731
    PP = [c_void_p, POINTER(c_void_p)]
    frei = []
    try:
        en, dev, mgr, sen = c_void_p(), c_void_p(), c_void_p(), c_void_p()
        if ole.CoCreateInstance(A("clsid"), None, 23, A("enum"), byref(en)):
            return
        frei.append(en)
        if _vcall(en, 4, [c_int, c_int, POINTER(c_void_p)], 0, 1, byref(dev)):   # Lautsprecher, Multimedia
            return
        frei.append(dev)
        if _vcall(dev, 3, [c_void_p, c_ulong, c_void_p, POINTER(c_void_p)], A("mgr"), 23, None, byref(mgr)):
            return
        frei.append(mgr)
        if _vcall(mgr, 5, [POINTER(c_void_p)], byref(sen)):
            return
        frei.append(sen)
        n = c_int()
        _vcall(sen, 3, [POINTER(c_int)], byref(n))
        for i in range(n.value):
            ctl, c2, vol, met = c_void_p(), c_void_p(), c_void_p(), c_void_p()
            try:
                if _vcall(sen, 4, [c_int, POINTER(c_void_p)], i, byref(ctl)) or not ctl.value:
                    continue
                if _vcall(ctl, 0, PP, A("ctl2"), byref(c2)) or not c2.value:
                    continue
                if _vcall(c2, 15, []) == 0:   # Systemklänge
                    continue
                pid, st, pk = c_ulong(), c_int(), c_float()
                _vcall(c2, 14, [POINTER(c_ulong)], byref(pid))
                _vcall(ctl, 3, [POINTER(c_int)], byref(st))
                if not _vcall(ctl, 0, PP, A("met"), byref(met)) and met.value:
                    _vcall(met, 3, [POINTER(c_float)], byref(pk))
                _vcall(ctl, 0, PP, A("vol"), byref(vol))
                fn(pid.value, st.value == 1, pk.value, vol if vol.value else None)
            finally:
                for p in (met, vol, c2, ctl):
                    if p.value:
                        _vcall(p, 2, [])
    finally:
        for p in reversed(frei):
            if p.value:
                _vcall(p, 2, [])


def _eigene_pids():
    """ORB selbst und sein Fenster (Edge mit ORB-Profil) – deren Ton ist keine Musik."""
    now = time.time()
    if now - _EIGENE["t"] > 30:
        pids = {os.getpid()}
        try:
            import psutil
            for p in psutil.process_iter(["pid", "name", "cmdline"]):
                if (p.info["name"] or "").lower() == "msedge.exe" and any(r"ORB\fenster" in (c or "") for c in p.info["cmdline"] or []):
                    pids.add(p.info["pid"])
        except Exception:
            pass
        _EIGENE.update(t=now, pids=pids)
    return _EIGENE["pids"]


def _pname(pid):
    if pid not in _PNAMEN:
        try:
            import psutil
            _PNAMEN[pid] = psutil.Process(pid).name().lower()
        except Exception:
            _PNAMEN[pid] = ""
    return _PNAMEN[pid]


def musik_status():
    """Spielt gerade Musik/Ton (Spotify oder ein anderes Programm)? Kurz zwischengespeichert."""
    now = time.time()
    with _AUDIO_LOCK:
        if now - _MUSIK["t"] < 1.5:
            return {"an": _MUSIK["an"], "quelle": _MUSIK["quelle"], "leiser": bool(_DUCK["vol"])}
        _MUSIK["t"] = now
        quelle = ""
        try:
            if spotify_now().get("spielt"):
                quelle = "spotify.exe"
        except Exception:
            pass
        eigene, laut = _eigene_pids(), []

        def f(pid, aktiv, pk, vol):
            if aktiv and pid and pid not in eigene and pk > (.004 if pid in _DUCK["vol"] else .015):
                laut.append(_pname(pid))
        try:
            _audio_sessions(f)
        except Exception:
            pass
        if laut:
            _MUSIK["laut_t"], quelle = now, quelle or laut[0]
        an = bool(quelle) or now - _MUSIK["laut_t"] < 4   # kurze Pausen zwischen Songs überbrücken
        _MUSIK.update(an=an, quelle=quelle or _MUSIK["quelle"] if an else "")
        return {"an": an, "quelle": _MUSIK["quelle"], "leiser": bool(_DUCK["vol"])}


DUCK_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "absenkung.json")


def _duck_saved():
    try:
        with open(DUCK_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _duck_save(d):
    try:
        if d:
            with open(DUCK_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f)
        elif os.path.exists(DUCK_FILE):
            os.remove(DUCK_FILE)
    except Exception:
        pass


def duck_reparieren():
    """Beim Start: war ORB mitten im Absenken beendet worden, die gemerkten Lautstärken zurückholen."""
    import ctypes
    saved = _duck_saved()
    if not saved:
        return

    def g(pid, aktiv, pk, vol):
        n = _pname(pid)
        if vol and n in saved:
            _vcall(vol, 3, [ctypes.c_float, ctypes.c_void_p], float(saved[n]), None)
    with _AUDIO_LOCK:
        try:
            _audio_sessions(g)
        except Exception:
            pass
    _duck_save({})


def duck(an):
    """Musik leiser stellen, während ORB zuhört/antwortet (an=True), danach wieder auf die alte Lautstärke."""
    import ctypes
    with _AUDIO_LOCK:
        if an:
            _DUCK["t"] = time.time()
            if _DUCK["vol"]:
                return True
            eigene, alt, saved = _eigene_pids(), {}, _duck_saved()

            def f(pid, aktiv, pk, vol):
                if vol and pid and pid not in eigene and (aktiv or _pname(pid) == "spotify.exe"):
                    v = ctypes.c_float()
                    if not _vcall(vol, 4, [ctypes.POINTER(ctypes.c_float)], ctypes.byref(v)):
                        orig = float(saved.get(_pname(pid), v.value))   # gemerkte Original-Lautstärke hat Vorrang
                        alt[pid] = orig
                        _vcall(vol, 3, [ctypes.c_float, ctypes.c_void_p], orig * .3, None)
            try:
                _audio_sessions(f)
            except Exception:
                pass
            _DUCK["vol"] = alt
            _duck_save({_pname(p): v for p, v in alt.items()})
            if alt:
                threading.Thread(target=_duck_wache, daemon=True).start()
            return bool(alt)
        alt, _DUCK["vol"] = _DUCK["vol"], {}

        def g(pid, aktiv, pk, vol):
            if vol and pid in alt:
                _vcall(vol, 3, [ctypes.c_float, ctypes.c_void_p], alt[pid], None)
        try:
            if alt:
                _audio_sessions(g)
        except Exception:
            pass
        _duck_save({})
        return True


def eigene_lautstaerke_voll():
    """ORBs eigene Lautstärke im Windows-Mixer auf 100 % halten – sonst wird die Stimme dort heimlich gedrosselt."""
    import ctypes
    eigene = _eigene_pids()

    def f(pid, aktiv, pk, vol):
        if vol and pid in eigene:
            v = ctypes.c_float()
            if not _vcall(vol, 4, [ctypes.POINTER(ctypes.c_float)], ctypes.byref(v)) and v.value < .99:
                _vcall(vol, 3, [ctypes.c_float, ctypes.c_void_p], 1.0, None)
    with _AUDIO_LOCK:
        try:
            _audio_sessions(f)
        except Exception:
            pass


def _mixer_wache():
    try:
        duck_reparieren()
    except Exception:
        pass
    while True:
        time.sleep(20)   # Fenster und Tonsitzung brauchen kurz, bis es sie gibt
        eigene_lautstaerke_voll()
        time.sleep(100)


def _duck_wache():
    """Sicherheitsnetz: meldet sich die Oberfläche nicht mehr, wird die Musik nach 30 s wieder laut."""
    while _DUCK["vol"]:
        time.sleep(2)
        if _DUCK["vol"] and time.time() - _DUCK["t"] > 30:
            duck(False)


MEDIA_KEYS = {"play": 0xB3, "next": 0xB0, "prev": 0xB1}


def media_key(cmd):
    import ctypes
    vk = MEDIA_KEYS.get(cmd)
    if not vk:
        return False
    ctypes.windll.user32.keybd_event(vk, 0, 1, 0)
    ctypes.windll.user32.keybd_event(vk, 0, 3, 0)
    return True


# ---------- Hintergrund-Aufgaben (Multitasking, je Aufgabe ein Hologramm) ----------
TASKS, _tasks_lock = {}, threading.Lock()
BG_REGELN = ("Du erledigst für ORB, Larsens Sprachassistenten, eine Aufgabe im Hintergrund, während Larsen weiter mit ORB redet. "
             "Arbeite selbstständig und vollständig, ohne Rückfragen. Lege längere Ergebnisse (Recherchen, Listen, Texte) als "
             "Markdown-Datei in C:\\Users\\larse\\Documents\\Jarvis\\ergebnisse an. Ändere nichts am ORB-Programm. "
             "Deine letzte Antwort wird laut vorgelesen: EIN kurzer deutscher Satz (höchstens 15 Wörter) mit dem Ergebnis. "
             "Kein Markdown. TEMPO: Sofort loslegen statt lange planen oder alte Dateien/Logs studieren – höchstens 2–3 kurze Blicke "
             "zum Orientieren, dann handeln. Melde Fortschritt nach jedem Teilschritt per aufgabe.ps1 (Larsen sieht dein Hologramm). "
             "Unabhängige Schritte (mehrere Suchen, Downloads, Dateien) parallel erledigen. QUALITÄT: Ergebnis am Ende selbst prüfen "
             "(Bildschirm: %LOCALAPPDATA%\\ORB\\screen\\live.png ansehen, Dateien öffnen, Befehle testen) und Fehler sofort beheben, "
             "bevor du fertig meldest.")


def umlaute(v):
    """Falsch kodierte Umlaute reparieren (UTF-8 als Windows-1252 gelesen: „Ã¤“ → „ä“) – auch in Listen/Objekten."""
    if isinstance(v, str):
        if re.search("[ÂÃâ][-¿ŒœŠšŸŽžƒˆ˜–-›€™]", v):
            try:
                return v.encode("cp1252").decode("utf-8")
            except UnicodeError:
                pass
        return v
    if isinstance(v, list):
        return [umlaute(x) for x in v]
    if isinstance(v, dict):
        return {k: umlaute(x) for k, x in v.items()}
    return v


def task_set(tid, **kw):
    kw = {k: umlaute(v) for k, v in kw.items()}
    with _tasks_lock:
        t = TASKS.setdefault(tid, {"id": tid, "titel": "Aufgabe", "art": "hintergrund", "status": "laeuft",
                                   "schritt": "", "schritte": 0, "start": time.time(), "ende": 0, "ergebnis": ""})
        if kw.get("status") == "laeuft" and t.get("status") != "laeuft":
            t.update(start=time.time(), ende=0, ergebnis="", schritte=0, prozent=None, phase="", auftrag="")   # neue Runde (z. B. nächster Entwickler-Auftrag)
        if kw.get("schritt") and kw["schritt"] != t.get("schritt"):
            t["schritte"] = t.get("schritte", 0) + 1
        t.update({k: v for k, v in kw.items() if v is not None})
        if t["status"] in ("fertig", "fehler", "abgebrochen") and not t["ende"]:
            t["ende"] = time.time()
        return dict(t)


DEV_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "entwickler")


def dev_fortschritt(t):
    """Entwickler schreibt seinen Fortschritt (fortschritt.ps1) in eine Statusdatei – hier ins Hologramm übernehmen."""
    if t.get("art") != "entwickler" or not str(t["id"]).startswith("dev-"):
        return
    if t["status"] == "fertig":
        t["prozent"], t["phase"] = 100, "Fertig"
        return
    if t["status"] != "laeuft":
        return
    f = os.path.join(DEV_DIR, str(t["id"])[4:], "fortschritt.json")
    try:
        if os.path.getmtime(f) < t["start"] - 5:
            return   # Datei vom vorigen Auftrag
        with open(f, encoding="utf-8-sig") as fh:
            d = json.load(fh)
        t["prozent"] = max(0, min(99, int(d.get("prozent", 0))))   # 100 % erst, wenn wirklich fertig
        t["phase"] = str(d.get("schritt") or "")[:40]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    t["fertig_ca"] = dev_schaetzung(t)


_DAUER = {}


def dev_durchschnitt(art):
    """Durchschnittliche Dauer früherer Entwickler-Aufträge (Sekunden) aus dem Protokoll, None ohne Daten."""
    f = os.path.join(DEV_DIR, art, "protokoll.txt")
    try:
        mt = os.path.getmtime(f)
    except OSError:
        return None
    if _DAUER.get(art, (0, None))[0] == mt:
        return _DAUER[art][1]
    import re
    try:
        with open(f, encoding="utf-8-sig", errors="ignore") as fh:
            txt = fh.read()
    except OSError:
        return None
    werte = [int(x) for x in re.findall(r"^Dauer: (\d+) s", txt, re.M)]
    if len(werte) < 3:   # ältere Protokolle ohne Dauer: Abstand zwischen aufeinanderfolgenden Aufträgen (plausible nur)
        st = []
        for m in re.findall(r"^=== (\d\d\.\d\d\.\d{4} \d\d:\d\d) ", txt, re.M):
            try:
                st.append(time.mktime(time.strptime(m, "%d.%m.%Y %H:%M")))
            except ValueError:
                pass
        werte += [b - a for a, b in zip(st, st[1:]) if 120 <= b - a <= 2700]
    werte = werte[-12:]
    ds = sum(werte) / len(werte) if werte else None
    _DAUER[art] = (mt, ds)
    return ds


def dev_schaetzung(t):
    """Voraussichtliche Fertig-Zeit (Epoche): bisheriges Tempo je Prozent, gemischt mit dem Durchschnitt früherer Aufträge."""
    if t["status"] != "laeuft":
        return 0
    seit, pz = time.time() - t["start"], t.get("prozent") or 0
    ds = dev_durchschnitt(str(t["id"])[4:])
    if pz >= 10 and seit >= 45:
        tempo = seit * 100 / pz
        w = pz / 100   # je weiter, desto mehr zählt das eigene Tempo
        gesamt = tempo * w + ds * (1 - w) if ds else tempo
    elif ds:
        gesamt = ds
    else:
        return 0
    return t["start"] + max(gesamt, seit + 30)


def tasks_list():
    now = time.time()
    with _tasks_lock:
        for tid in [k for k, t in TASKS.items() if t["ende"] and now - t["ende"] > 600]:
            del TASKS[tid]   # fertige Aufgaben nach 10 Minuten wegräumen
        for t in TASKS.values():
            dev_fortschritt(t)
        return [dict(t, laeuft_seit=round(now - t["start"]), jetzt=now) for t in sorted(TASKS.values(), key=lambda t: t["start"])]


# ---------- Trading-Tagesstart: beim ersten Öffnen am Tag 3 Hologramme (News, Gold, Chart) ----------
TAGESSTART_DATEI = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "tagesstart.txt")
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def _json_holen(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


FF_CACHE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "ff_kalender.json")


def ff_kalender():
    try:
        if time.time() - os.path.getmtime(FF_CACHE) < 7200:
            with open(FF_CACHE, encoding="utf-8") as f:
                return json.load(f)
    except OSError:
        pass
    try:
        daten = _json_holen(FF_URL)
        with open(FF_CACHE, "w", encoding="utf-8") as f:
            json.dump(daten, f)
        return daten
    except Exception:
        with open(FF_CACHE, encoding="utf-8") as f:   # gesperrt/offline: letzter Stand (gleiche Woche)
            return json.load(f)


def ff_news_heute():
    """ForexFactory-Kalender: heutige Termine (Ortszeit), High + Medium, sortiert."""
    heute, out = datetime.date.today(), []
    for e in ff_kalender():
        try:
            t = datetime.datetime.fromisoformat(e["date"]).astimezone()   # in Ortszeit (MEZ/MESZ)
        except Exception:
            continue
        if t.date() == heute and e.get("impact") in ("High", "Medium"):
            out.append(dict(zeit=t, land=e.get("country", ""), titel=e.get("title", ""), impact=e["impact"],
                            prognose=e.get("forecast", ""), vorher=e.get("previous", "")))
    return sorted(out, key=lambda x: x["zeit"])


_GOLD_TAG = {"t": 0.0, "d": {}}


def gold_tag():
    """Tageswerte fürs Dashboard (10 Min. zwischengespeichert): Hoch/Tief/Vortag vom Gold-Future, auf den Spot-Preis
    verschoben (Future liegt meist ~20 $ höher), plus Tagesveränderung in % und die laufende Session."""
    if time.time() - _GOLD_TAG["t"] < 600:
        return _GOLD_TAG["d"]
    d = {}
    try:
        r = _json_holen("https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=5d")["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        tage = [(h, l, c) for h, l, c in zip(q["high"], q["low"], q["close"]) if h and l and c]
        if len(tage) >= 2:
            versatz = gold_preis() - tage[-1][2]
            d["heute_hoch"], d["heute_tief"] = round(tage[-1][0] + versatz, 2), round(tage[-1][1] + versatz, 2)
            d["vortag_hoch"], d["vortag_tief"] = round(tage[-2][0] + versatz, 2), round(tage[-2][1] + versatz, 2)
            d["vortag_schluss"] = round(tage[-2][2] + versatz, 2)
            d["veraenderung"] = round((tage[-1][2] - tage[-2][2]) / tage[-2][2] * 100, 3)
    except Exception:
        pass
    try:
        d["session"] = session_jetzt()
    except Exception:
        pass
    _GOLD_TAG.update(t=time.time(), d=d)
    return d


def gold_daten():
    d = {}
    try:
        d["preis"] = float(_json_holen("https://api.gold-api.com/price/XAU")["price"])
    except Exception:
        pass
    try:
        r = _json_holen("https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=5d")["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        tage = [(h, l, c) for h, l, c in zip(q["high"], q["low"], q["close"]) if h and l and c]
        if len(tage) >= 2:
            d["vortag_hoch"], d["vortag_tief"], d["vortag_schluss"] = tage[-2]
            d["heute_hoch"], d["heute_tief"] = tage[-1][0], tage[-1][1]
    except Exception:
        pass
    return d


def session_jetzt():
    h = datetime.datetime.now().hour + datetime.datetime.now().minute / 60
    if datetime.date.today().weekday() >= 5:
        return "Wochenende – Markt geschlossen"
    if 8 <= h < 12:
        return "London-Session läuft (08–12 Uhr)"
    if 14 <= h < 18:
        return "New-York-Session läuft (14–18 Uhr)"
    if h < 8:
        return "Vor London – Start 08:00"
    if h < 14:
        return "Pause bis New York – Start 14:00"
    return "Sessions vorbei – heute keine Setups mehr"


def _news_nachladen():
    """ForexFactory hat abgelehnt (zu viele Abrufe): später erneut versuchen und dann ansagen."""
    for warte in (300, 600, 1200):
        time.sleep(warte)
        try:
            ff_kalender()
        except Exception:
            continue
        try:
            os.remove(TAGESSTART_DATEI)
        except OSError:
            pass
        tagesstart(zwingen="nachladen")
        return


def tagesstart(zwingen=False):
    """Beim ersten Öffnen am Tag: News, Gold und Live-Chart als Hologramme; News kurz ansagen."""
    heute = datetime.date.today().isoformat()
    try:
        with open(TAGESSTART_DATEI, encoding="utf-8") as f:
            if f.read().strip() == heute and not zwingen:
                return False
    except OSError:
        pass
    if not load_cfg().get("trading_start", True) and not zwingen:
        return False
    with open(TAGESSTART_DATEI, "w", encoding="utf-8") as f:
        f.write(heute)

    # 1) News
    satz = ""
    try:
        news = ff_news_heute()
        rote = [n for n in news if n["impact"] == "High"]
        zeilen = [[n["zeit"].strftime("%H:%M"), ("🔴 " if n["impact"] == "High" else "🟠 ") + n["land"], n["titel"],
                   n["prognose"] or "–"] for n in news]
        inhalt = [{"typ": "zahl", "wert": str(len(rote)), "label": "rote News heute", "reihe": True},
                  {"typ": "zahl", "wert": str(len(news) - len(rote)), "label": "mittlere", "reihe": True}]
        if zeilen:
            inhalt.append({"typ": "tabelle", "kopf": ["Zeit", "Land", "Termin", "Prognose"], "zeilen": zeilen})
        sperren = [f"{(n['zeit'] - datetime.timedelta(minutes=30)):%H:%M}–{(n['zeit'] + datetime.timedelta(minutes=30)):%H:%M} "
                   f"({n['land']} {n['titel']})" for n in rote if n["land"] in ("USD", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF", "NZD")]
        if sperren:
            inhalt.append({"typ": "liste", "punkte": ["Kein Trade: " + s for s in sperren]})
        else:
            inhalt.append({"typ": "text", "text": "Keine roten News – freie Bahn (trotzdem vor jedem Entry kurz prüfen)."})
        karte_setzen({"id": "ts_news", "titel": "ForexFactory · News heute", "groesse": "mittel", "pos": "oben-links", "farbe": "rot" if rote else "gruen",
                      "inhalt": inhalt})
        usd = [n for n in rote if n["land"] == "USD"]
        if not rote:
            satz = "Heute gibt es keine roten News bei ForexFactory."
        else:
            erste = ", ".join(f"{n['zeit']:%H:%M} {n['titel']}" for n in (usd or rote)[:3])
            satz = (f"Heute {len(rote)} rote News" + (f", für Gold wichtig: {erste}." if usd else f": {erste}.")
                    + " Eine halbe Stunde davor und danach nicht traden.")
    except Exception:
        karte_setzen({"id": "ts_news", "titel": "ForexFactory · News heute", "groesse": "klein", "pos": "oben-links",
                      "inhalt": [{"typ": "text", "text": "ForexFactory lässt gerade keine Abfrage zu – ich versuche es in "
                                                         "ein paar Minuten automatisch noch einmal."}]})
        satz = "Den ForexFactory-Kalender lade ich gleich nach."
        if zwingen != "nachladen":
            threading.Thread(target=_news_nachladen, daemon=True).start()

    # 2) Gold
    g = gold_daten()
    inhalt = []
    if "preis" in g:
        ch = "Spot (ca.)"
        inhalt.append({"typ": "zahl", "wert": f"{g['preis']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                       "einheit": "$", "label": "XAUUSD " + ch})
    inhalt.append({"typ": "text", "text": session_jetzt()})
    inhalt.append({"typ": "liste", "punkte": ["Setup-TF M1 · M5 · M15, Kontext M15/H1", "Entry 83,6 % · SL X ± 2 Pip · BE 1R · TP 2R",
                                             "Alle 6 Confirmations – sonst kein Trade"]})
    inhalt.append({"typ": "text", "text": "Broker: Vantage (XAUUSD, 1 Lot = 100 oz). Spot-Preis oben ca. – maßgeblich ist der Vantage-Kurs im Chart."})
    karte_setzen({"id": "ts_gold", "titel": "Jarvis · Gold", "groesse": "klein", "farbe": "gelb", "pos": "oben-rechts", "inhalt": inhalt})

    # 3) Live-Chart (TradingView)
    karte_setzen({"id": "ts_chart", "titel": "XAUUSD · Vantage · M5", "groesse": "gross", "farbe": "gelb", "pos": "unten", "inhalt": [
        {"typ": "web", "url": "https://s.tradingview.com/widgetembed/?symbol=VANTAGE%3AXAUUSD&interval=5&theme=dark"
                              "&style=1&locale=de_DE&timezone=Europe%2FBerlin&hide_side_toolbar=0&withdateranges=1"}]})
    if satz:
        say_when_free(satz)
    return True


# ---------- Gaming-Modus: läuft ein Spiel, gibt ORB Grafikkarte/Speicher frei und reagiert nicht auf Knalle ----------
SPIEL_ORDNER = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\roblox\\versions\\", "\\ea games\\",
                "\\ubisoft game launcher\\games\\", "\\battle.net\\", "\\xboxgames\\", "\\gog galaxy\\games\\")
KEIN_SPIEL = ("steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "robloxplayerlauncher.exe", "riotclientservices.exe",
              "riotclientux.exe", "battle.net.exe", "eadesktop.exe", "crashreport", "unitycrashhandler", "easyanticheat")
_spiel = {"t": 0.0, "name": ""}


def spiel_laeuft():
    """Name des laufenden Spiels (Steam, Epic, Riot, Roblox, EA, Ubisoft, Battle.net, Xbox) oder ''. 5 s zwischengespeichert."""
    return ""   # Gaming-Modus entfernt (19.11.): Spiele werden nicht mehr erkannt, ORB verhält sich immer gleich
    if time.time() - _spiel["t"] < 5:
        return _spiel["name"]
    name = ""
    if load_cfg().get("gaming_modus", True):
        try:
            import psutil
            for p in psutil.process_iter(["exe", "name"]):
                exe = (p.info.get("exe") or "").lower()
                n = (p.info.get("name") or "").lower()
                if n in ("javaw.exe", "java.exe"):   # Minecraft Java (jede Version, Fabric/Forge/LabyMod/Lunar …)
                    try:
                        cl = " ".join(p.cmdline()).lower()
                    except Exception:
                        cl = ""
                    if ("net.minecraft" in cl or ".minecraft" in cl or "labymod" in cl or "lunarclient" in cl) and "nogui" not in cl:
                        name = "Minecraft"
                        break
                if exe and any(o in exe for o in SPIEL_ORDNER) and not any(k in n for k in KEIN_SPIEL):
                    name = p.info.get("name") or "Spiel"
                    break
        except Exception:
            pass
    _spiel.update(t=time.time(), name=name)
    return name


def stimmung():
    """Farbe für ORB nach Lage: Spiel/Nacht/Trading-Ergebnis des Tages – sonst die eingestellte Farbe."""
    cfg = load_cfg()
    if not cfg.get("stimmung", True):
        return {"farbe": cfg.get("farbe", "rot"), "grund": "aus"}
    h = datetime.datetime.now().hour
    r = 0.0
    try:
        heute = datetime.date.today()
        varianten = (heute.isoformat(), heute.strftime("%d.%m.%Y"), heute.strftime("%d.%m."))
        with open(os.path.join(cfg["ordner"], "trading", "journal.md"), encoding="utf-8") as f:
            for zeile in f:
                teile = [t.strip() for t in zeile.strip().strip("|").split("|")]
                if len(teile) >= 10 and any(teile[0].startswith(v) for v in varianten):
                    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", teile[9])
                    if m:
                        r += float(m.group().replace(",", "."))
    except Exception:
        pass
    if r > 0:
        return {"farbe": "gruen", "grund": "Trading heute im Plus (%+.1f R)" % r}
    if r < 0:
        return {"farbe": "gold", "grund": "Trading heute im Minus (%+.1f R) – ruhig bleiben" % r}
    if h >= 22 or h < 6:
        return {"farbe": "blau", "grund": "Nacht"}
    return {"farbe": cfg.get("farbe", "rot"), "grund": "normal"}


# ---------- Razer Chroma: Tastatur/Maus leuchten in ORBs Farbe, pulsieren beim Sprechen, blinken rot vor roten News ----------
FARBEN = {"rot": (255, 50, 40), "blau": (50, 140, 255), "cyan": (30, 215, 255), "gruen": (30, 235, 130),
          "lila": (170, 80, 255), "gold": (255, 180, 40), "weiss": (210, 225, 255)}
FARBEN2 = {"rot": (255, 100, 180), "blau": (150, 90, 255), "cyan": (120, 110, 255), "gruen": (30, 190, 255),
           "lila": (255, 80, 190), "gold": (255, 90, 60), "weiss": (150, 190, 255)}
CHROMA_GERAETE = ("keyboard", "mouse", "mousepad", "headset", "keypad", "chromalink")


class Chroma:
    def __init__(self):
        self.uri, self.zuletzt, self.farbe = None, 0.0, None

    def _req(self, methode, url, daten=None):
        req = urllib.request.Request(url, data=json.dumps(daten).encode() if daten is not None else None, method=methode,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read().decode() or "{}")

    def an(self):
        if self.uri:
            return True
        try:
            r = self._req("POST", "http://localhost:54235/razer/chromasdk", {
                "title": "ORB Licht", "description": "ORB Sprachassistent – Licht",   # eigener Name: Razer startet dafür einen Hilfsprozess mit diesem Namen "author": {"name": "ORB", "contact": "lokal"},
                "device_supported": list(CHROMA_GERAETE), "category": "application"})
            self.uri = r.get("uri")
            time.sleep(0.6)   # Chroma braucht kurz, bis die Sitzung bereit ist
        except Exception:
            self.uri = None
        return bool(self.uri)

    def aus(self):
        if self.uri:
            try:
                self._req("DELETE", self.uri)
            except Exception:
                pass
        self.uri, self.farbe = None, None

    def setzen(self, rgb):
        if not self.an():
            return
        bgr = rgb[2] << 16 | rgb[1] << 8 | rgb[0]   # Chroma erwartet BGR
        if bgr == self.farbe and time.time() - self.zuletzt < 5:
            self._req("PUT", self.uri + "/heartbeat")
            return
        try:
            for g in CHROMA_GERAETE:
                self._req("PUT", f"{self.uri}/{g}", {"effect": "CHROMA_STATIC", "param": {"color": bgr}})
            self.farbe, self.zuletzt = bgr, time.time()
        except Exception:
            self.uri = None


def _dimmen(rgb, f):
    return tuple(max(0, min(255, int(c * f))) for c in rgb)


def chroma_loop():
    """Leuchtet nur, solange ORB wach/sichtbar ist; im Schlaf, im Spiel oder ausgeschaltet gehört das Licht wieder Synapse."""
    ch, gewarnt, t = Chroma(), set(), 0
    cache = {"t": 0.0, "farbe": "rot", "news": [], "cfg": {}}
    while True:
        time.sleep(0.25)
        t += 1
        try:
            if time.time() - cache["t"] > 20:   # Farbe/News/Einstellungen nur alle 20 s neu
                cache["cfg"] = load_cfg()
                cache["farbe"] = stimmung().get("farbe", cache["cfg"].get("farbe", "rot"))
                try:
                    cache["news"] = ff_news_heute()
                except Exception:
                    cache["news"] = []
                cache["t"] = time.time()
            cfg = cache["cfg"]
            if tarnmodus.aktiv():   # Tarnmodus: alle Razer-Geräte schwarz (statt Synapse-Licht) – PC wirkt aus
                ch.setzen((0, 0, 0))
                time.sleep(1)
                continue
            wach = time.time() - LAST_WACH[0] < 3
            if not cfg.get("razer", True) or not wach or spiel_laeuft():
                if ch.uri:
                    ch.aus()
                time.sleep(1.5)
                continue
            farbe = cache["farbe"]
            basis, zweit = FARBEN.get(farbe, FARBEN["rot"]), FARBEN2.get(farbe, FARBEN2["rot"])
            # rote News in 5 Minuten: 8 s rot blinken (einmal pro Termin)
            warnung = False
            try:
                for n in cache["news"]:
                    rest = (n["zeit"] - datetime.datetime.now().astimezone()).total_seconds()
                    if n["impact"] == "High" and 0 < rest <= 300:
                        key = n["zeit"].isoformat() + n["titel"]
                        if key not in gewarnt:
                            gewarnt.add(key)
                            for i in range(16):
                                ch.setzen((255, 0, 0) if i % 2 == 0 else (40, 0, 0))
                                time.sleep(0.5)
                            warnung = True
            except Exception:
                pass
            if warnung:
                continue
            mode = read_state().get("mode", "idle")
            if mode == "spricht":
                ch.setzen(_dimmen(basis, 1.0 if t % 3 else 0.45))          # pulsiert beim Sprechen
            elif mode in ("denkt", "auftrag"):
                ch.setzen(_dimmen(zweit, 0.55 + 0.45 * abs(((t / 8) % 2) - 1)))   # atmet beim Arbeiten
            else:
                ch.setzen(_dimmen(basis, 0.7))
        except Exception as e:
            print("Razer:", e)
            time.sleep(5)


# ---------- PC-Wache: warnt von selbst bei vollem Speicher, voller Platte oder heißer Grafikkarte ----------
def pc_wache():
    zuletzt = {}
    while True:
        time.sleep(600)
        try:
            import psutil
            warn = []
            vm = psutil.virtual_memory()
            if vm.percent >= 92:
                warn.append(("ram", "Dein Arbeitsspeicher ist zu %d Prozent voll. Sag „PC-Doktor“, dann schaue ich, was ihn frisst." % vm.percent))
            frei = shutil.disk_usage("C:\\").free / 2**30
            if frei < 15:
                warn.append(("platte", "Auf C: sind nur noch %d Gigabyte frei." % frei))
            try:
                t = int(subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                                       capture_output=True, text=True, timeout=8, creationflags=NO_WINDOW).stdout.strip())
                if t >= 87:
                    warn.append(("gpu", "Deine Grafikkarte ist mit %d Grad sehr heiß." % t))
            except Exception:
                pass
            for art, text in warn:
                if time.time() - zuletzt.get(art, 0) > 6 * 3600 and time.time() - LAST_WACH[0] < 60 and not spiel_laeuft():
                    zuletzt[art] = time.time()
                    say_when_free(text)
        except Exception as e:
            print("PC-Wache:", e)


# ---------- Musik-Geschmack: merkt sich gehörte und übersprungene Spotify-Songs (für den DJ) ----------
def musik_logger():
    pfad = os.path.join(load_cfg()["ordner"], "musik", "geschmack.json")
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    try:
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
    except Exception:
        daten = {"songs": {}, "kuenstler": {}}
    jetzt, start = None, 0.0
    while True:
        time.sleep(4)
        try:
            sp = spotify_now()
            song = f"{sp['kuenstler']} - {sp['titel']}" if sp.get("spielt") else None
            if song == jetzt or (song is None and jetzt):   # gleicher Song oder pausiert: nichts zählen
                continue
            if jetzt:   # vorheriger Song zu Ende oder übersprungen
                dauer = time.time() - start
                k = jetzt.split(" - ", 1)[0]
                e = daten["songs"].setdefault(jetzt, {"gehoert": 0, "geskippt": 0})
                ke = daten["kuenstler"].setdefault(k, {"gehoert": 0, "geskippt": 0})
                art = "geskippt" if dauer < 30 else "gehoert"
                e[art] += 1
                ke[art] += 1
                e["zuletzt"] = datetime.date.today().isoformat()
                if len(daten["songs"]) > 3000:   # nicht endlos wachsen
                    for alt in sorted(daten["songs"], key=lambda s: daten["songs"][s].get("zuletzt", ""))[:500]:
                        del daten["songs"][alt]
                tmp = pfad + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(daten, f, ensure_ascii=False, indent=0)
                os.replace(tmp, pfad)
            jetzt, start = song, time.time()
        except Exception:
            time.sleep(20)


# ---------- Bildschirm in Echtzeit: alle 1,5 s ein frisches Bild (ORB selbst ist aus der Aufnahme ausgeblendet) ----------
LIVE_BILD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "screen", "live.png")
LIVE = {"t": 0.0, "groesse": (0, 0), "massstab": 1.0}


def _bildschirm_png(breite_max=1600):
    """Bildschirm per GDI aufnehmen, auf ≤1600 px verkleinern, als PNG speichern – ohne Zusatzpakete (ctypes + zlib)."""
    import ctypes
    import struct
    import zlib
    from ctypes import wintypes
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    # Nur dieser Thread DPI-bewusst: sonst liefert Windows bei 150 % Skalierung nur einen Ausschnitt (oben links)
    alt = None
    try:
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        alt = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # PER_MONITOR_AWARE_V2
    except Exception:
        pass
    try:
        return _bildschirm_png_roh(u, g, breite_max)
    finally:
        if alt:
            u.SetThreadDpiAwarenessContext(ctypes.c_void_p(alt))


def _bildschirm_png_roh(u, g, breite_max):
    import ctypes
    import struct
    import zlib
    from ctypes import wintypes
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)   # echte Pixel (Thread ist DPI-bewusst)
    f = min(1.0, breite_max / sw)
    w, h = int(sw * f), int(sh * f)
    hdc = u.GetDC(0)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    g.SelectObject(mdc, bmp)
    g.SetStretchBltMode(mdc, 4)   # HALFTONE: sauber verkleinern
    g.StretchBlt(mdc, 0, 0, w, h, hdc, 0, 0, sw, sh, 0x00CC0020 | 0x40000000)   # SRCCOPY | CAPTUREBLT

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
    bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 24, 0, 0, 0, 0, 0, 0)
    stride = (w * 3 + 3) & ~3
    buf = ctypes.create_string_buffer(stride * h)
    g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u.ReleaseDC(0, hdc)
    raw = buf.raw
    zeilen = bytearray()
    for y in range(h):
        z = raw[y * stride:y * stride + w * 3]
        rgb = bytearray(z)
        rgb[0::3], rgb[2::3] = z[2::3], z[0::3]   # BGR -> RGB
        zeilen += b"\x00" + rgb
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(bytes(zeilen), 3)) + chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(LIVE_BILD), exist_ok=True)
    tmp = LIVE_BILD + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(png)
    os.replace(tmp, LIVE_BILD)
    echt_w = sw
    LIVE.update(t=time.time(), groesse=(w, h), massstab=echt_w / w)
    with open(os.path.join(os.path.dirname(LIVE_BILD), "massstab.txt"), "w") as fh:
        fh.write("%.4f" % (echt_w / w))   # für steuern.ps1 (Klick-Koordinaten in echten Pixeln)


def live_bildschirm():
    """Solange „ORB sieht meinen Bildschirm“ an ist: alle 1,5 s neu aufnehmen (im Spiel und im Schlaf Pause)."""
    while True:
        time.sleep(1.5)
        try:
            if not load_cfg().get("bildschirm") or spiel_laeuft():
                time.sleep(3)
                continue
            _bildschirm_png()
        except Exception as e:
            print("Live-Bildschirm:", e)
            time.sleep(5)


_TASTATUR = {"farbe": "", "t": 0.0}


def tastatur_farbe(farbe):
    """Acer-Nitro-Tastatur einfärben: Farbe in eine Datei schreiben und die geplante Aufgabe „ORB Tastatur“ starten
    (läuft mit Admin-Rechten, die Acer-Schnittstelle verlangt das). Ohne eingerichtete Aufgabe passiert nichts."""
    farbe = farbe.strip().lstrip("#").lower()
    if not re.fullmatch(r"[0-9a-f]{6}", farbe) or not load_cfg().get("tastatur_farbe", True):
        return False
    if farbe == _TASTATUR["farbe"] and time.time() - _TASTATUR["t"] < 600:
        return True
    try:
        with open(os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "tastatur_farbe.txt"), "w") as f:
            f.write(farbe)
        r = subprocess.run(["schtasks", "/run", "/tn", "ORB Tastatur"], capture_output=True, timeout=10, creationflags=NO_WINDOW)
        if r.returncode == 0:
            _TASTATUR.update(farbe=farbe, t=time.time())
            return True
    except Exception as e:
        print("Tastatur:", e)
    return False


# ---------- Trading-Journal (schnell: Währung, Emotion, +/-, Lotgröße) ----------
JOURNAL = os.path.join(os.path.expanduser("~"), "Documents", "Jarvis", "trading", "journal.json")


def journal_laden():
    try:
        with open(JOURNAL, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def journal_speichern(liste):
    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    tmp = JOURNAL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(liste, f, ensure_ascii=False, indent=1)
    os.replace(tmp, JOURNAL)


def journal_eintrag(b):
    """Neuer Trade: {waehrung, emotion, ergebnis (Zahl, + oder -), lot}. Alles optional außer Ergebnis."""
    try:
        ergebnis = float(str(b.get("ergebnis", "")).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
    try:
        lot = float(str(b.get("lot") or 0).replace(",", "."))
    except ValueError:
        lot = 0.0
    e = {"id": "%x" % int(time.time() * 1000), "zeit": time.strftime("%Y-%m-%d %H:%M"),
         "waehrung": re.sub(r"[^A-Z0-9/.]", "", str(b.get("waehrung") or "XAUUSD").upper())[:12] or "XAUUSD",
         "emotion": str(b.get("emotion") or "")[:16], "ergebnis": round(ergebnis, 2), "lot": round(lot, 2),
         "richtung": "short" if str(b.get("richtung", "")).lower().startswith("s") else "long",
         "be": bool(b.get("be")) or ergebnis == 0}
    liste = journal_laden()
    liste.append(e)
    journal_speichern(liste)
    return e


def journal_statistik(liste):
    erg = [x.get("ergebnis", 0) for x in liste]
    heute = time.strftime("%Y-%m-%d")
    return {"anzahl": len(erg), "summe": round(sum(erg), 2), "trefferquote": round(sum(1 for x in erg if x > 0) / len(erg) * 100) if erg else 0,
            "heute": round(sum(x.get("ergebnis", 0) for x in liste if str(x.get("zeit", "")).startswith(heute)), 2)}


# ---------- TradingView-Konto im Dashboard: eigenes Fenster, randlos in die Chart-Karte gelegt ----------
TV = {"hwnd": 0, "an": False, "rect": None, "proc": None, "t": 0.0}
TV_PROFIL = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "tradingview")


def _tv_fenster():
    """HWND des TradingView-Fensters (Edge-App mit eigenem Profil)."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    if TV["hwnd"] and u.IsWindow(TV["hwnd"]):
        return TV["hwnd"]
    try:
        import psutil
        pids = {p.pid for p in psutil.process_iter(["name", "cmdline"])
                if (p.info["name"] or "").lower() == "msedge.exe" and any("ORB\\tradingview" in (c or "") for c in p.info["cmdline"] or [])}
    except Exception:
        return 0
    gefunden = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u.GetWindowTextLengthW(h) and u.GetParent(h) == 0:
            r = (ctypes.c_long * 4)()
            u.GetWindowRect(h, ctypes.byref(r))
            if r[2] - r[0] > 200:
                gefunden.append(h)
        return True
    u.EnumWindows(cb, 0)
    TV["hwnd"] = gefunden[0] if gefunden else 0
    return TV["hwnd"]


def tv_dock(an, rect=None, symbol="VANTAGE:XAUUSD"):
    """Dein TradingView-Konto: rahmenloses WebView2-Fenster (tvfenster.py) über der Chart-Karte.
    Schreibt die gewünschte Lage nach tv_lage.json – das Fenster folgt ihr – und startet es bei Bedarf."""
    lage = {"an": bool(an), "t": time.time()}
    if rect:
        lage.update({k: int(rect[k]) for k in ("x", "y", "w", "h")})
    elif TV.get("rect"):
        lage.update(TV["rect"])
    if rect:
        TV["rect"] = {k: int(rect[k]) for k in ("x", "y", "w", "h")}
    pfad = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "tv_lage.json")
    with open(pfad + ".tmp", "w", encoding="utf-8") as f:
        json.dump(lage, f)
    os.replace(pfad + ".tmp", pfad)
    if not an:
        return True
    p = TV.get("proc")
    if p is None or p.poll() is not None:
        try:
            import psutil
            laeuft = any("tvfenster.py" in " ".join(q.info["cmdline"] or []) for q in psutil.process_iter(["cmdline"]))
        except Exception:
            laeuft = False
        if not laeuft and time.time() - TV["t"] > 6:
            TV["t"] = time.time()
            import shutil
            pyw = shutil.which("pyw") or shutil.which("pythonw")
            skript = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tvfenster.py")
            if pyw and os.path.exists(skript):
                TV["proc"] = subprocess.Popen([pyw] + (["-3"] if pyw.lower().endswith("pyw.exe") else []) + [skript], creationflags=NO_WINDOW)
    return True


def tv_lebenszeichen():
    """Solange das Dashboard läuft, Lage-Datei frisch halten (sonst beendet sich das TradingView-Fenster nach 2 Min.)."""
    while True:
        time.sleep(30)
        try:
            pfad = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "tv_lage.json")
            with open(pfad, encoding="utf-8") as f:
                lage = json.load(f)
            if time.time() - LAST_POLL[0] < 60:
                lage["t"] = time.time()
                with open(pfad + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(lage, f)
                os.replace(pfad + ".tmp", pfad)
        except Exception:
            pass


threading.Thread(target=tv_lebenszeichen, daemon=True).start()


def _orb_hwnds():
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        b = ctypes.create_unicode_buffer(16)
        u.GetWindowTextW(h, b, 16)
        if b.value == "ORB" and u.IsWindowVisible(h):
            out.append(h)
        return True
    u.EnumWindows(cb, 0)
    return out


# ---------- Notizen (Dashboard-Tab; liegen in der Wissensbasis, damit ORB sie kennt) ----------
NOTIZEN = os.path.join(os.path.expanduser("~"), "Documents", "Jarvis", "notizen.json")


def notizen_laden():
    try:
        with open(NOTIZEN, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def notizen_aendern(b):
    """{text, titel?, farbe?, id?} speichern (neu oder ändern) · {loeschen: id} · {anheften: id}."""
    liste = notizen_laden()
    if b.get("loeschen"):
        liste = [n for n in liste if n.get("id") != str(b["loeschen"])]
    elif b.get("anheften"):
        for n in liste:
            if n.get("id") == str(b["anheften"]):
                n["angeheftet"] = not n.get("angeheftet")
    else:
        text = str(b.get("text") or "")[:20000]
        titel = str(b.get("titel") or "").strip()[:120] or (text.strip().split("\n")[0][:60] if text.strip() else "Neue Notiz")
        nid = str(b.get("id") or "")
        n = next((x for x in liste if x.get("id") == nid), None) if nid else None
        if n is None:
            n = {"id": "%x" % int(time.time() * 1000), "erstellt": time.strftime("%Y-%m-%d %H:%M")}
            liste.append(n)
        n.update(titel=titel, text=text, farbe=str(b.get("farbe") or n.get("farbe") or "")[:12], geaendert=time.strftime("%Y-%m-%d %H:%M"))
        nid = n["id"]
    os.makedirs(os.path.dirname(NOTIZEN), exist_ok=True)
    tmp = NOTIZEN + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(liste, f, ensure_ascii=False, indent=1)
    os.replace(tmp, NOTIZEN)
    return {"ok": True, "id": nid if not b.get("loeschen") else None}


def say_when_free(text):
    """Ansage, sobald ORB nicht gerade selbst antwortet (max. 2 Min. warten)."""
    def run():
        for _ in range(240):
            if not BRAIN.busy and read_state().get("mode") not in ("denkt", "auftrag"):
                break
            time.sleep(.5)
        write_answer(text, heard="")
    threading.Thread(target=run, daemon=True).start()


def run_task(tid, auftrag):
    cfg = load_cfg()
    args = [find_claude(), "-p", "--output-format", "stream-json", "--verbose", "--model", cfg["modell"],
            "--permission-mode", "auto", "--effort", "medium", "--append-system-prompt", BG_REGELN]   # medium: zügig statt ewig grübeln
    ordner = cfg["ordner"] if os.path.isdir(cfg["ordner"]) else os.path.expanduser("~")
    env = {k: v for k, v in os.environ.items() if k not in CLAUDE_ENV_DROP}
    env["ORB_RUN"] = "1"
    env["ORB_BG"] = "1"
    try:
        import hook as _hook
    except Exception:
        _hook = None
    ergebnis, fehler = "", False
    try:
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             cwd=ordner, env=env, creationflags=NO_WINDOW)
        task_set(tid, pid=p.pid)
        p.stdin.write(auftrag.encode("utf-8"))
        p.stdin.close()
        for raw in p.stdout:
            TASKS.get(tid, {})["aus"] = time.time()
            try:
                o = json.loads(raw.decode("utf-8", "ignore"))
            except Exception:
                continue
            if o.get("type") == "assistant":
                for c in (o.get("message") or {}).get("content") or []:
                    if c.get("type") == "tool_use":
                        name = c.get("name", "")
                        lab = _hook.label_for(name) if _hook else name
                        det = _hook.detail_for(c.get("input")) if _hook else ""
                        task_set(tid, schritt=(lab + (": " + det if det else ""))[:90])
                    elif c.get("type") == "text" and c.get("text", "").strip():
                        task_set(tid, schritt="Denkt nach …")
            elif o.get("type") == "result":
                ergebnis, fehler = str(o.get("result") or ""), bool(o.get("is_error"))
        p.wait()
    except Exception as e:
        ergebnis, fehler = str(e), True
    if TASKS.get(tid, {}).get("status") == "abgebrochen":
        return
    satz = clean(ergebnis).strip() or ("Fertig." if not fehler else "")
    if fehler or not satz:
        task_set(tid, status="fehler", schritt="", ergebnis="Hat nicht geklappt.")
        say_when_free("Die Aufgabe „%s“ hat leider nicht geklappt." % TASKS[tid]["titel"])
    else:
        task_set(tid, status="fertig", schritt="", ergebnis=satz[:600])
        say_when_free(satz[:600])


def task_start(titel, auftrag):
    tid = "t%d" % int(time.time() * 1000)
    task_set(tid, titel=(titel or "Aufgabe")[:40], art="hintergrund", status="laeuft", schritt="Startet …")
    threading.Thread(target=run_task, args=(tid, auftrag), daemon=True).start()
    return tid


def task_cancel(tid):
    t = TASKS.get(tid)
    if t and t.get("status") == "laeuft" and t.get("pid"):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(t["pid"])], capture_output=True, creationflags=NO_WINDOW)
        task_set(tid, status="abgebrochen", schritt="", ergebnis="Abgebrochen.")
        return True
    return False


# ---------- Freie Hologramme („Karten“): beliebig viele, je mit mehreren Inhalten ----------
KARTEN, KARTEN_V, _karten_lock = {}, [0], threading.Lock()
BILD_ENDUNGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
BLOCK_TYPEN = ("text", "titel", "liste", "zahl", "fortschritt", "bild", "video", "web", "tabelle", "trenner")
VIDEO_ENDUNGEN = (".mp4", ".webm", ".mov", ".m4v")


def karte_setzen(b):
    """Neues/aktualisiertes Hologramm. b: {id?, titel, groesse: klein|mittel|gross, breite?, hoehe?, farbe?,
    inhalt: [{typ:text|titel|liste|zahl|fortschritt|bild|web|tabelle|trenner, ...}], dauer: Sekunden (0 = bleibt),
    anhaengen: true (Inhalte anfügen statt ersetzen)} – oder {id, zu: true} / {alle_zu: true}."""
    b = umlaute(b)
    with _karten_lock:
        if b.get("alle_zu"):
            KARTEN.clear()
        elif b.get("zu"):
            KARTEN.pop(str(b.get("id", "")), None)
        else:
            kid = re.sub(r"[^\w-]", "", str(b.get("id") or "")) or "k%d" % int(time.time() * 1000)
            inhalt = []
            for blk in (b.get("inhalt") or [])[:60]:
                if not isinstance(blk, dict) or blk.get("typ") not in BLOCK_TYPEN:
                    continue
                if blk["typ"] in ("bild", "video"):
                    pfad = os.path.abspath(os.path.expandvars(str(blk.get("pfad", ""))))
                    endungen = BILD_ENDUNGEN if blk["typ"] == "bild" else VIDEO_ENDUNGEN
                    if not (pfad.lower().endswith(endungen) and os.path.isfile(pfad)):
                        continue
                    blk = dict(blk, pfad=pfad)
                inhalt.append(blk)
            alt = KARTEN.get(kid, {})
            if b.get("anhaengen") and alt:
                inhalt = (alt.get("inhalt") or []) + inhalt
            KARTEN[kid] = {"id": kid, "titel": str(b.get("titel") or alt.get("titel") or "")[:80],
                           "groesse": str(b.get("groesse") or alt.get("groesse") or "mittel"),
                           "breite": b.get("breite") or alt.get("breite"), "hoehe": b.get("hoehe") or alt.get("hoehe"),
                           "farbe": str(b.get("farbe") or alt.get("farbe") or ""), "inhalt": inhalt[-60:],
                           "pos": str(b.get("pos") or alt.get("pos") or ""),
                           "dauer": float(b.get("dauer") or 0), "zeit": time.time(), "v": alt.get("v", 0) + 1}
            KARTEN_V[0] += 1
            return {"ok": True, "id": kid}
        KARTEN_V[0] += 1
        return {"ok": True}


# ---------- „Was ist neu?“ – kleine Einführung nach jedem Update (ORB) bzw. fertigen Projekt ----------
NEU_ZULETZT = [0.0]


def neu_datei(art):
    return os.path.join(DEV_DIR, "projekt" if art == "projekt" else "orb", "neu.json")


def neu_laden(art):
    """Vom Entwickler (neu.ps1) hinterlegte Einführung holen und verbrauchen – nur, wenn sie frisch ist (< 3 Std.)."""
    f = neu_datei(art)
    try:
        frisch = time.time() - os.path.getmtime(f) < 3 * 3600
        with open(f, encoding="utf-8-sig") as fh:
            d = json.load(fh)
        os.remove(f)
    except Exception:
        return None
    punkte = d.get("punkte") or []
    punkte = [str(p).strip()[:120] for p in ([punkte] if isinstance(punkte, str) else punkte) if str(p).strip()][:4]
    return {"punkte": punkte, "nutzen": str(d.get("nutzen") or "").strip()[:120]} if frisch and punkte else None


def neu_zeigen(art, punkte, nutzen="", sagen=""):
    """Kleines Hologramm „Neu …“: 2–4 Punkte + wie man es benutzt, 30 s sichtbar (oder bis X)."""
    inhalt = [{"typ": "liste", "punkte": punkte[:4]}]
    if nutzen:
        inhalt.append({"typ": "text", "text": "So geht’s: " + nutzen})
    karte_setzen({"id": "neu", "titel": "Neu im Projekt" if art == "projekt" else "Neu in ORB · Version %s" % VERSION,
                  "groesse": "klein", "inhalt": inhalt, "dauer": 30})
    NEU_ZULETZT[0] = time.time()
    if sagen:
        say_when_free(sagen)


def neu_nach_entwickler(art, satz):
    """entwickler_lauf.ps1 ist fertig: Projekt → Einführung sofort; ORB → nur falls das Update sie nicht schon gezeigt hat."""
    satz = clean(str(satz or "")).strip()[:160]
    if art != "projekt" and (os.path.exists(neu_datei(art)) or time.time() - NEU_ZULETZT[0] < 900):
        return False   # Update wird noch eingespielt (zeigt sie dann selbst) bzw. wurde schon gezeigt
    n = neu_laden(art)
    if n:
        neu_zeigen(art, n["punkte"], n["nutzen"], sagen="Neu: " + n["punkte"][0])
    elif satz:
        neu_zeigen(art, [satz])   # Ergebnis wurde schon angesagt – nur anzeigen
    return bool(n or satz)


def karten_liste():
    now = time.time()
    with _karten_lock:
        weg = [k for k, c in KARTEN.items() if c["dauer"] and now - c["zeit"] > c["dauer"]]
        for k in weg:
            del KARTEN[k]
        if weg:
            KARTEN_V[0] += 1
        return list(KARTEN.values())


def idle_reaper():
    """Claude nach 15 Minuten ohne Frage beenden, damit es keinen Speicher belegt (~250 MB)."""
    while True:
        time.sleep(30)
        if BRAIN.alive() and not BRAIN.busy and time.time() - BRAIN.last_used > 600:
            BRAIN.kill()
        for t in list(TASKS.values()):
            if t.get("status") == "laeuft" and t.get("pid") and time.time() - t.get("aus", t["start"]) > 600:
                task_cancel(t["id"])
                task_set(t["id"], status="fehler", ergebnis="Hing 10 Minuten ohne Fortschritt – abgebrochen.")
        if BRAIN.busy and time.time() - BRAIN.last_out > 180:
            # Gehirn hängt (3 Min. ohne jede Ausgabe) → abbrechen statt ewig „denkt“
            BRAIN.stopped = True
            BRAIN.kill()
            BRAIN.busy = False
            write_answer("Das hat zu lange gedauert, ich habe abgebrochen. Frag mich bitte noch einmal.")


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def audio(self, data):
        if not data:
            return self.send(500, b"", "text/plain")
        self.send(200, data, "audio/wav" if data[:4] == b"RIFF" else "audio/mpeg")

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            raw = self.rfile.read(n) if n else b""
            try:
                txt = raw.decode("utf-8")
            except UnicodeDecodeError:
                txt = raw.decode("cp1252", "replace")  # z. B. Windows-PowerShell
            return json.loads(txt) if txt else {}
        except Exception:
            return {}

    def erlaubt(self, braucht_token=True):
        """Host prüfen (gegen DNS-Rebinding) und Token prüfen (gegen Anfragen fremder Webseiten)."""
        if self.headers.get("Host", "") not in ERLAUBTE_HOSTS:
            self.send(403, b"", "text/plain")
            return False
        if braucht_token and self.headers.get("X-ORB-Token", "") != TOKEN:
            self.send(403, b"", "text/plain")
            return False
        return True

    def do_GET(self):
        u = urlparse(self.path)
        if not self.erlaubt(braucht_token=u.path not in ("/", "/index.html", "/version", "/skin3d")
                            and not u.path.startswith("/skinbild/") and not u.path.startswith("/dash/")):
            return
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            with open(PAGE, "rb") as f:
                page = f.read()
            # Token in die eigene Seite einbetten; fetch()-Aufrufe an ORB selbst senden es automatisch mit (nie an fremde Server)
            inject = ("<script>(()=>{const T='%s',f=window.fetch;window.fetch=(u,o={})=>{const s=String(u&&u.url||u);"
                      "if(/^[a-z][a-z0-9+.-]*:/i.test(s)&&!s.startsWith(location.origin+'/'))return f(u,o);"
                      "o.headers=Object.assign({},o.headers||{},{'X-ORB-Token':T});return f(u,o)}})()</script>" % TOKEN).encode()
            self.send(200, page.replace(b"<head>", b"<head>" + inject, 1), "text/html; charset=utf-8")
        elif u.path == "/state":
            if q.get("von") != "extern":   # nur das ORB-Fenster zählt als „Fenster offen“ (Telegram & Co. fragen mit von=extern)
                LAST_POLL[0] = time.time()
            if q.get("wach") == "1":
                LAST_WACH[0] = time.time()
            if q.get("spricht") == "1":
                LAST_SPRICHT[0] = time.time()
            if q.get("aktiv") == "1":
                LAST_ACTIVE[0] = time.time()
            st = read_state()
            if (st.get("mode") in ("denkt", "auftrag", "wartet") and not BRAIN.busy
                    and time.time() - float(st.get("time") or 0) > 90):
                # Rest eines abgebrochenen Auftrags (z. B. Claude-Code-Sitzung ohne Abschluss) → wieder bereit
                write_state(mode="idle", task="", detail="", log=[])
                st = read_state()
            st["busy"] = BRAIN.busy
            st["aufgaben"] = tasks_list()
            OHR["ev"] = [e for e in OHR["ev"] if time.time() - e["t"] < 20]
            st["ohr"] = {"an": time.time() - OHR["t"] < 5 and load_cfg().get("ohr", True), "ev": OHR["ev"]}
            karten_liste()   # abgelaufene Hologramme wegräumen
            st["karten_v"] = KARTEN_V[0]   # Hintergrund-Aufgaben + Entwickler (je ein Hologramm)
            st["bild"] = {"n": BILD["n"], "name": BILD["name"], "rein": BILD["rein"]}   # Bild-Hologramm
            st["gold"] = GOLD["n"]   # Gold-Hologramm auf Zuruf
            st["kam_n"] = KAM_INHALT["n"]   # neue Inhalte für die Kamera-Ansicht (kamera_zeigen.ps1)
            st["kamera_foto"] = KAMERA["foto"] if time.time() - KAMERA["foto_zeit"] < 15 else 0   # kamera.ps1 wartet auf ein Standbild
            st["web"] = {"n": WEB["n"], "url": WEB["url"], "titel": WEB["titel"], "modus": WEB["modus"],
                         "lebt": web_lebt(), "rein": WEB["rein"]}   # Web-Hologramm
            st["spiel"] = spiel_laeuft()
            # Meeting oder Spiel: nicht zuhören – außer Minecraft: da hört ORB weiter auf „Jarvis“ (Befehle im Spiel)
            st["anruf"] = call_aktiv() or bool(st["spiel"] and st["spiel"] != "Minecraft")   # während Meet/Teams/Zoom nicht zuhören
            st["tarn"] = tarnmodus.aktiv()   # Tarnmodus: Oberfläche ganz stumm
            st["handy"] = handy_still()   # Gespräch per Telegram: Oberfläche stumm, Sprachnachricht trotzdem fürs Handy
            st["pause"] = PAUSE["an"]   # Pausemodus: Oberfläche hört nicht zu, Telegram/Tippen gehen weiter
            st["anruf"] = st["anruf"] or PAUSE["an"]
            st["version"] = VERSION   # Fenster lädt sich neu, wenn eine neue Version läuft
            for i, p in enumerate(st.get("parts") or []):   # Stimme für alle Stücke vorbereiten
                ensure((st.get("aid"), i), p)
            self.send(200, st)
        elif u.path == "/karten":
            self.send(200, {"karten": [dict(c, inhalt=[{k: v for k, v in blk.items() if k != "pfad"} for blk in c["inhalt"]])
                                       for c in karten_liste()]})
        elif u.path == "/ohr/modus":   # ohr.py fragt: lauschen? mitschreiben?
            OHR["t"] = time.time()
            spiel = spiel_laeuft()
            an = load_cfg().get("ohr", True) and not call_aktiv() and not (spiel and spiel != "Minecraft")
            self.send(200, {"an": an, "mitschreiben": an and time.time() - LAST_WACH[0] < 3,
                            "stimmcheck": load_cfg().get("nur_meine_stimme", True)})
        elif u.path == "/stimmung":
            self.send(200, stimmung())
        elif u.path == "/karte/datei":   # Bild aus einem Hologramm (nur Bilddateien, die beim Anlegen geprüft wurden)
            c = KARTEN.get(q.get("id", ""))
            try:
                pfad = c["inhalt"][int(q.get("i", -1))]["pfad"]
                with open(pfad, "rb") as f:
                    data = f.read()
            except Exception:
                return self.send(404, b"", "text/plain")
            ext = os.path.splitext(pfad)[1].lower().lstrip(".")
            typ = ({"mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}.get(ext)
                   or "image/" + {"jpg": "jpeg"}.get(ext, ext))
            self.send(200, data, typ)
        elif u.path == "/kamera/inhalt":   # Oberfläche holt neue Kamera-Inhalte (ohne Dateipfade)
            try:
                seit = int(q.get("seit", "0") or 0)
            except ValueError:
                seit = 0
            self.send(200, {"liste": [dict({k: v for k, v in e.items() if k != "pfad"}, datei=bool(e["pfad"]))
                                      for e in KAM_INHALT["liste"] if e["n"] > seit]})
        elif u.path == "/kamera/datei":   # Bild eines Kamera-Inhalts (beim Senden geprüft)
            e = next((e for e in KAM_INHALT["liste"] if str(e["n"]) == q.get("n") and e["pfad"]), None)
            try:
                with open(e["pfad"], "rb") as f:
                    data = f.read()
            except Exception:
                return self.send(404, b"", "text/plain")
            ext = os.path.splitext(e["pfad"])[1].lower().lstrip(".")
            self.send(200, data, "image/" + {"jpg": "jpeg"}.get(ext, ext))
        elif u.path == "/bild":   # aktuelles Bild-Hologramm ausliefern
            pfad = BILD["pfad"]
            try:
                with open(pfad, "rb") as f:
                    data = f.read()
            except OSError:
                return self.send(404, b"", "text/plain")
            ext = os.path.splitext(pfad)[1].lower().lstrip(".")
            self.send(200, data, "image/" + {"jpg": "jpeg"}.get(ext, ext))
        elif u.path == "/tts":
            st = read_state()
            aid = q.get("aid", "")
            try:
                i = int(q.get("i", "-1") or -1)
            except ValueError:
                i = -1
            parts = st.get("parts") or []
            if aid != st.get("aid") or not (0 <= i < len(parts)):
                return self.send(404, b"", "text/plain")
            ent = ensure((aid, i), parts[i])
            ent["ev"].wait(75)   # Wiederholversuche der Neural-Stimme abwarten
            self.audio(ent["data"])
        elif u.path == "/preview":
            cfg = load_cfg()
            cfg.update({k: q[k] for k in ("stimme", "tempo", "hoehe") if k in q})
            self.audio(synth(q.get("text") or "Hallo! So klinge ich mit diesen Einstellungen.", cfg))
        elif u.path == "/config":
            c = load_cfg()
            self.send(200, {"config": c, "stimmen": STIMMEN})
        elif u.path == "/skin3d":   # drehbare 3D-Vorschau eines Minecraft-Skins (skinview3d)
            skin_still(True)   # Skin-Vorschau offen: gemeinsames Skin-Bauen läuft
            n = re.sub(r"[^A-Za-z0-9_-]", "", q.get("n", ""))[:60]   # Großbuchstaben erlaubt (z. B. „Larscraft17-aktuell“)
            seite = ("<!doctype html><meta charset=utf-8><style>html,body{margin:0;height:100%;background:#0b0f1c;overflow:hidden}"
                     "canvas{display:block}</style><canvas id=c></canvas>"
                     "<script src='https://cdn.jsdelivr.net/npm/skinview3d@3.1.0/bundles/skinview3d.bundle.js'></script><script>"
                     "const v=new skinview3d.SkinViewer({canvas:document.getElementById('c'),width:innerWidth,height:innerHeight,"
                     "skin:'/skinbild/{N}.png?t='+Date.now()});v.autoRotate=true;v.autoRotateSpeed=.8;"
                     "v.animation=new skinview3d.WalkingAnimation();v.animation.speed=.6;v.zoom=.85;"
                     "v.background=0x0b0f1c;onresize=()=>v.setSize(innerWidth,innerHeight)</script>").replace("{N}", n)   # kein %-Format: CSS enthält „100%“
            self.send(200, seite.encode(), "text/html; charset=utf-8")
        elif u.path.startswith("/dash/"):   # Glas-Dashboard: Stil, Skript, Hintergrund (nur Dateien aus dem dash-Ordner)
            n = os.path.basename(urllib.parse.unquote(u.path[len("/dash/"):]))
            typ = {"css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8", "jpg": "image/jpeg", "png": "image/png",
                   "webp": "image/webp"}.get(n.rsplit(".", 1)[-1].lower())
            pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), n)   # liegen im Hauptordner (Updater kopiert keine Unterordner)
            if not typ or not re.fullmatch(r"dash[A-Za-z0-9_.-]*", n) or not os.path.isfile(pfad):
                return self.send(404, b"", "text/plain")
            with open(pfad, "rb") as f:
                self.send(200, f.read(), typ)
        elif u.path.startswith("/skinbild/"):   # nur PNGs aus dem Skin-Ordner
            n = re.sub(r"[^A-Za-z0-9_-]", "", urllib.parse.unquote(u.path[len("/skinbild/"):]).rsplit(".", 1)[0])[:60]
            pfad = os.path.join(os.path.expanduser("~"), "Pictures", "Minecraft-Skins", n + ".png")
            try:
                with open(pfad, "rb") as f:
                    self.send(200, f.read(), "image/png")
            except OSError:
                self.send(404, b"", "text/plain")
        elif u.path == "/version":
            self.send(200, {"version": VERSION})
        elif u.path == "/features":   # Widget „Was Jarvis kann“: zentrale Liste features.json neben server.py
            try:
                with open(os.path.join(RES, "features.json"), encoding="utf-8-sig") as f:
                    self.send(200, {"bereiche": json.load(f).get("bereiche", [])})
            except Exception:
                self.send(200, {"bereiche": []})
        elif u.path == "/mouse":
            self.send(200, {"ago": round(mouse_ago(), 3), "eingabe": round(input_ago(), 3)})
        elif u.path == "/sys":
            try:
                import psutil
                b = psutil.sensors_battery()
                self.send(200, {"cpu": psutil.cpu_percent(None), "ram": psutil.virtual_memory().percent,
                                "akku": b.percent if b else None, "laden": bool(b and b.power_plugged)})
            except Exception:
                self.send(200, {})
        elif u.path == "/weather":
            try:
                self.send(200, weather_data() or {})
            except Exception:
                self.send(200, {})
        elif u.path == "/notizen":
            self.send(200, {"notizen": notizen_laden()})
        elif u.path == "/journal":
            liste = journal_laden()
            self.send(200, {"eintraege": liste[-200:], "statistik": journal_statistik(liste)})
        elif u.path == "/gold":
            try:
                self.send(200, dict(gold_tag(), preis=gold_preis(), zeit=GOLD["zeit"]))
            except Exception:
                self.send(200, {})
        elif u.path == "/termine":
            self.send(200, {"termine": termine()})
        elif u.path == "/icloud":
            z = icloud.zugang()
            self.send(200, {"verbunden": bool(z), "apple_id": z[0] if z else ""})
        elif u.path == "/spotify":
            try:
                self.send(200, spotify_now())
            except Exception:
                self.send(200, {"laeuft": False})
        elif u.path == "/musik":
            try:
                self.send(200, musik_status())
            except Exception:
                self.send(200, {"an": False})
        else:
            self.send(404, b"", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        if not self.erlaubt():
            return
        b = self.body()
        if u.path == "/ask":
            text = str(b.get("text", "")).strip()
            if not text:
                return self.send(400, {"ok": False})
            if not b.get("getippt") and ist_echo(text):   # ORBs eigene Stimme über das Mikro – nie als Frage weitergeben
                print("Echo verworfen:", text[:80])
                return self.send(200, {"ok": False, "echo": True})
            if PAUSE["an"] and not b.get("getippt"):   # Pausemodus: Stimmen (z. B. Meeting-Ton) nie annehmen
                print("Pausemodus, Sprache ignoriert:", text[:80])
                return self.send(200, {"ok": False, "pause": True})
            r = ask(text)
            self.send(200 if r else 409, {"ok": True, "parallel": r == "parallel", "lokal": r == "lokal"})
        elif u.path == "/stop":
            self.send(200, {"ok": stop()})
        elif u.path == "/media":
            self.send(200, {"ok": media_key(str(b.get("cmd", "")))})
        elif u.path == "/duck":
            self.send(200, {"ok": duck(bool(b.get("an")))})
        elif u.path == "/config":
            self.send(200, {"config": save_cfg(b)})
        elif u.path == "/icloud":  # Einstellungen: verbinden / trennen
            try:
                if b.get("trennen"):
                    icloud.trennen()
                    res = {"ok": True}
                else:
                    res = {"ok": True, "kalender": icloud.verbinden(b.get("apple_id", ""), b.get("passwort", ""))}
                if not BRAIN.busy:
                    BRAIN.kill()  # Claude kennt beim nächsten Auftrag den Kalender
            except Exception as e:
                res = {"ok": False, "fehler": str(e)}
            self.send(200, res)
        elif u.path == "/kalender":  # für Claude: Termine anlegen, lesen, löschen
            self.send(200, kalender_aktion(b))
        elif u.path == "/erinnerungen":  # für Claude: iCloud-Erinnerungen
            self.send(200, erinnerungen_aktion(b))
        elif u.path == "/kontakte":  # für Claude: iCloud-Kontakte (nur gesuchte Einträge)
            self.send(200, kontakte_aktion(b))
        elif u.path == "/greet":
            threading.Thread(target=stimme_vorladen, daemon=True).start()
            threading.Thread(target=lambda: write_answer(greeting(), heard="", holo=holo_for("Wetter abrufen", "")), daemon=True).start()
            threading.Thread(target=BRAIN.start, daemon=True).start()  # Gehirn schon mal aufwecken
            self.send(200, {"ok": True})
        elif u.path == "/warm":
            threading.Thread(target=stimme_vorladen, daemon=True).start()
            threading.Thread(target=BRAIN.start, daemon=True).start()
            self.send(200, {"ok": True})
        elif u.path == "/hoerlog":
            log_close(str(b.get("t") or ""), HOER_LOG)
            self.send(200, {"ok": True})
        elif u.path == "/sleep":
            log_close("Schlaf: " + str(b.get("grund") or "unbekannt"))
            if not BRAIN.busy:
                BRAIN.kill()  # im Schlaf keinen Speicher belegen
            self.send(200, {"ok": True})
        elif u.path == "/selfupdate":  # „Nach Updates suchen“ bzw. update.ps1 nach dem Hochladen
            self.send(200, {"ok": bool(ON_UPDATE[0])})
            if ON_UPDATE[0]:
                sha = str(b.get("sha", "")).strip().lower() or None
                if sha and not re.fullmatch(r"[0-9a-f]{40}", sha):
                    sha = None   # nur echte Commit-Kennungen   # update.ps1 schickt den genauen Stand mit
                threading.Thread(target=lambda: (time.sleep(.3), ON_UPDATE[0](sha)), daemon=True).start()
        elif u.path == "/updatecheck":  # Knopf „Nach Updates suchen“
            if not ON_CHECK[0] or not ON_UPDATE[0]:
                self.send(200, {"ok": False, "version": VERSION, "fehler": "Nur in der installierten Version möglich"})
            else:
                try:
                    neu = ON_CHECK[0]()
                except Exception:
                    self.send(200, {"ok": False, "version": VERSION, "fehler": "GitHub nicht erreichbar"})
                    write_answer("Ich konnte GitHub gerade nicht erreichen.", heard="")
                else:
                    self.send(200, {"ok": True, "version": VERSION, "update": bool(neu)})
                    if neu:
                        write_answer("Update gefunden. Ich lade es und starte neu.", heard="")
                        threading.Thread(target=lambda: (time.sleep(3.5), ON_UPDATE[0](neu)), daemon=True).start()
                    else:
                        write_answer("Du bist auf dem neuesten Stand, Version %s." % VERSION, heard="")
        elif u.path == "/aufgabe":   # Hintergrund-Aufgabe starten / Fortschritt melden (Entwickler) / abbrechen
            a = str(b.get("aktion", "start"))
            if a == "start" and str(b.get("auftrag", "")).strip():
                self.send(200, {"id": task_start(str(b.get("titel", "")).strip(), str(b["auftrag"]).strip())})
            elif a == "melde" and re.fullmatch(r"[\w-]{1,40}", str(b.get("id", ""))):
                self.send(200, task_set(str(b["id"]), **{k: b.get(k) for k in ("titel", "art", "status", "schritt", "ergebnis", "auftrag")
                                                         if b.get(k) is not None}))
            elif a == "abbrechen":
                self.send(200, {"ok": task_cancel(str(b.get("id", "")))})
            else:
                self.send(400, {"ok": False})
        elif u.path == "/neu":   # entwickler_lauf.ps1 am Ende: Einführung „Was ist neu?“
            self.send(200, {"ok": neu_nach_entwickler(str(b.get("art", "orb")), b.get("satz"))})
        elif u.path == "/tagesstart":   # Fenster geöffnet: einmal am Tag News/Gold/Chart einblenden
            self.send(200, {"ok": True})
            threading.Thread(target=lambda: tagesstart(bool(b.get("zwingen"))), daemon=True).start()
        elif u.path == "/karte":   # holo.ps1: freies Hologramm anlegen/ändern/schließen
            self.send(200, karte_setzen(b if isinstance(b, dict) else {}))
        elif u.path == "/kamera":   # Oberfläche: Kamera an/aus (wird alle paar Sekunden bestätigt)
            KAMERA["aktiv"], KAMERA["zeit"] = bool(b.get("aktiv")), time.time()
            if not KAMERA["aktiv"]:
                KAMERA["foto_zeit"] = 0.0
            self.send(200, {"ok": True})
        elif u.path == "/kamera/foto":   # kamera.ps1: um EIN Standbild bitten (nur wenn die Kamera schon an ist)
            if not kamera_aktiv():
                return self.send(200, {"ok": False, "fehler": "Die Kamera ist aus. Larsen kann „Kamera an“ sagen."})
            KAMERA["foto"] += 1
            KAMERA["foto_zeit"] = time.time()
            self.send(200, {"ok": True, "n": KAMERA["foto"]})
        elif u.path == "/kamera/zeigen":   # kamera_zeigen.ps1: Inhalt in die Kamera-Ansicht schicken
            self.send(200, kamera_zeigen(b if isinstance(b, dict) else {}))
        elif u.path == "/kamera/bild":   # Oberfläche liefert das angefragte Standbild
            self.send(200, {"ok": kamera_bild_speichern(b.get("bild"))})
        elif u.path == "/bild":   # bild_zeigen.ps1: Bild sofort als Hologramm einblenden
            self.send(200, {"ok": bild_zeigen(b.get("pfad"), b.get("rein"))})
        elif u.path == "/web":   # web_zeigen.ps1: Webseite als bedienbares Hologramm
            ok, d = web_zeigen(b.get("url"), b.get("titel"), b.get("rein"))
            self.send(200, dict(d, ok=ok))
        elif u.path == "/web/fenster":   # Oberfläche: echte Webansicht über dem Hologramm öffnen/ausrichten
            try:
                ok = web_fenster(int(b.get("n", -1)), b.get("rect") or [])
            except Exception as e:
                print("Webansicht:", e)
                ok = False
            self.send(200, {"ok": ok})
        elif u.path == "/web/zu":
            if int(b.get("n", -1)) == WEB["n"]:
                web_schliessen()
            self.send(200, {"ok": True})
        elif u.path == "/web/browser":   # im normalen Browser öffnen
            url = WEB["url"]
            if url:
                launch(url)
            web_schliessen()
            self.send(200, {"ok": bool(url)})
        elif u.path == "/announce":  # z. B. update.ps1: „Update fertig“ laut sagen
            text = str(b.get("text", "")).strip()
            if text:
                write_answer(text, heard="")
            self.send(200, {"ok": bool(text)})
        elif u.path == "/hide":
            CALL_FREI[0] = False   # weggeschickt → im Meet wieder taub
            self.send(200, {"ok": True})
            keep = bool(b.get("keep"))   # nur ausblenden: Seite hört weiter auf „Jarvis“
            log_close("Fenster %s: %s" % ("ausgeblendet" if keep else "geschlossen", b.get("grund") or "unbekannt"))
            if not BRAIN.busy and not keep:
                BRAIN.kill()
            web_schliessen_fenster()   # Webansicht verschwindet mit ORB
            if ON_HIDE[0]:
                threading.Thread(target=ON_HIDE[0], kwargs={"keep": keep}, daemon=True).start()
        elif u.path == "/ohr":   # ohr.py: „Hey Jarvis“ erkannt oder Satz mitgeschrieben
            OHR["t"] = time.time()
            typ, text = str(b.get("typ", "")), str(b.get("text", "")).strip()
            eigen = typ == "text" and ist_echo(text)   # Whisper liefert ORBs eigenen Satz oft erst nach der Ansage
            echo = time.time() - LAST_SPRICHT[0] < ECHO_SPERRE or eigen
            name_stopp = re.search(r"(?i)\b(jarvis|orb|stopp?|hör auf|aufhören|sei still|ruhe)\b", text) and not eigen
            if typ == "text" and echo and not name_stopp:
                return self.send(200, {"ok": False, "grund": "Echo – ORB sprach gerade"})
            if fremd_gesperrt():   # Fremder am PC: „Jarvis“ & Fragen ignorieren, nur neu scannen lassen
                if typ == "wake":
                    weckversuch()
                return self.send(200, {"ok": False, "grund": "gesperrt"})
            if typ == "wake" and time.time() - LAST_WACH[0] > 3 and ON_SHOW[0]:
                threading.Thread(target=ON_SHOW[0], kwargs={"wake": True}, daemon=True).start()   # Fenster zu/versteckt: aufwecken
            OHR["n"] += 1
            OHR["ev"].append({"id": OHR["n"], "typ": typ, "text": text, "t": time.time()})
            self.send(200, {"ok": True})
        elif u.path == "/journal":   # Trading-Journal: neuer Eintrag {waehrung, emotion, ergebnis, lot} oder {loeschen: id}
            if b.get("loeschen"):
                journal_speichern([x for x in journal_laden() if x.get("id") != str(b["loeschen"])])
                self.send(200, {"ok": True})
            else:
                e = journal_eintrag(b)
                self.send(200 if e else 400, {"ok": bool(e), "eintrag": e})
        elif u.path == "/notizen":   # Notizen-Tab: speichern / löschen / anheften
            self.send(200, notizen_aendern(b))
        elif u.path == "/tv_dock":   # Dashboard: TradingView-Konto in der Chart-Karte zeigen/ausblenden
            self.send(200, {"ok": tv_dock(bool(b.get("an")), b.get("rect"), str(b.get("symbol") or "VANTAGE:XAUUSD"))})
        elif u.path == "/tastatur":   # Dashboard-Farbthema → Acer-Nitro-Tastatur (über die Admin-Aufgabe „ORB Tastatur“)
            self.send(200, {"ok": tastatur_farbe(str(b.get("farbe", "")))})
        elif u.path == "/tradingview":   # Dashboard: „Mein TradingView“ – Chart in Larsens Opera GX (sein Konto, seine Layouts)
            sym = re.sub(r"[^A-Z0-9:._!-]", "", str(b.get("symbol") or "VANTAGE:XAUUSD").upper())[:40]
            opera = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Opera GX", "opera.exe")
            url = "https://www.tradingview.com/chart/?symbol=" + urllib.parse.quote(sym)
            try:
                subprocess.Popen([opera, url] if os.path.exists(opera) else ["cmd", "/c", "start", "", url], creationflags=NO_WINDOW)
                self.send(200, {"ok": True})
            except Exception as e:
                self.send(500, {"ok": False, "fehler": str(e)[:120]})
        elif u.path == "/mini":   # Mini-ORB: kleine Kugel in der Ecke, immer obenauf
            self.send(200, {"ok": bool(ON_MINI[0])})
            if ON_MINI[0]:
                threading.Thread(target=ON_MINI[0], args=(bool(b.get("an", True)),), daemon=True).start()
        elif u.path == "/show":  # Fenster öffnen bzw. nach vorne holen (z. B. zweiter Doppelklick auf ORB.exe)
            CALL_FREI[0] = True   # Larsen hat ORB selbst geholt (Klatschen) → auch im Meet zuhören
            if ON_SHOW[0]:
                threading.Thread(target=ON_SHOW[0], kwargs={"wake": bool(b.get("wake"))}, daemon=True).start()
            self.send(200, {"ok": True})
        elif u.path == "/quit":  # neue ORB-Version übernimmt bzw. „ORB ganz beenden“
            self.send(200, {"ok": True})
            BRAIN.kill()
            grund = "Beendet: " + str(b.get("grund") or "neue ORB-Instanz übernimmt")
            threading.Thread(target=lambda: (time.sleep(.3), clean_exit(grund)), daemon=True).start()
        elif u.path == "/new":
            BRAIN.stopped, BRAIN.busy = True, False
            BRAIN.kill()
            save_cfg({"sitzung": ""})
            write_state(mode="idle", heard="", say="", parts=[], aid="", log=[])
            self.send(200, {"ok": True})
        else:
            self.send(404, b"", "text/plain")


class ExclusiveServer(ThreadingHTTPServer):
    """Windows erlaubt sonst, dass zwei ORBs denselben Port belegen – dann antwortet die falsche Version."""
    allow_reuse_address = False

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def write_token():
    try:
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            f.write(TOKEN)
    except Exception as e:
        print("Token-Datei:", e)


def make_server():
    """Gibt den Server zurück, oder None wenn ORB schon läuft."""
    try:
        srv = ExclusiveServer(("127.0.0.1", PORT), Handler)
    except OSError:
        return None
    srv.daemon_threads = True
    _install_crash_log()
    if TESTSERVER:
        pass   # Test-Server (check.py) – echtes Protokoll nicht anfassen
    elif os.path.exists(RUN_MARK):
        log_close("Gestartet – vorher unerwartet beendet (Absturz, Abmelden oder PC aus)")
    else:
        log_close("Gestartet")
    if not TESTSERVER:
        mark_running(True)
    write_token()
    threading.Thread(target=load_apps, daemon=True).start()  # App-Liste vorab laden
    threading.Thread(target=idle_reaper, daemon=True).start()
    if not TESTSERVER:
        threading.Thread(target=bild_wache, daemon=True).start()   # neue Bilder als Hologramm
        threading.Thread(target=_mixer_wache, daemon=True).start()   # ORB im Windows-Mixer auf 100 %
    return srv


if __name__ == "__main__":
    srv = make_server()
    if not srv:
        print("ORB läuft bereits auf http://127.0.0.1:%d" % PORT)
        sys.exit(0)
    print("ORB läuft auf http://127.0.0.1:%d  (Fenster offen lassen)" % PORT)
    try:
        srv.serve_forever()
    finally:
        BRAIN.kill()
