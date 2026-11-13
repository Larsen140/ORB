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

from hook import clean, split_sentences  # Markdown -> vorlesbarer Text, Text -> Sprech-Stücke

RES = os.path.dirname(os.path.abspath(__file__))  # Seite & Stimme liegen neben server.py (nicht in der exe)
HOME = os.path.join(os.path.expanduser("~"), "Orb")
STATE = os.path.join(HOME, "state.json")
CONFIG = os.path.join(HOME, "config.json")
PAGE = os.path.join(RES, "index.html")


def _lade_icloud():
    """icloud.py liegt neben server.py – ausdrücklich von dort laden (der App-Ordner steht nicht im Suchpfad)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("icloud", os.path.join(RES, "icloud.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


icloud = _lade_icloud()  # iCloud-Kalender (CalDAV)
TTS_PS = os.path.join(RES, "tts.ps1")
PORT = int(os.environ.get("ORB_PORT", "8766"))  # ORB_PORT nur für Tests (update.ps1 prüft auf 8799)
NO_WINDOW = 0x08000000
# Schutz gegen fremde Webseiten: nur Anfragen mit diesem Token (steht nur in ORBs eigener Seite und in einer
# Datei im Benutzerordner) dürfen etwas tun.
TOKEN = secrets.token_hex(16)
# Test-Server (andere Ports) dürfen den Token des echten ORB nicht überschreiben
TOKEN_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB",
                          "token.txt" if PORT == 8766 else "token_%d.txt" % PORT)
ERLAUBTE_HOSTS = ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)

STIMMEN = [
    ["de-DE-FlorianMultilingualNeural", "Florian (männlich, sehr natürlich)"],
    ["de-DE-SeraphinaMultilingualNeural", "Seraphina (weiblich, sehr natürlich)"],
    ["de-DE-ConradNeural", "Conrad (männlich)"],
    ["de-DE-KillianNeural", "Killian (männlich)"],
    ["de-DE-KatjaNeural", "Katja (weiblich)"],
    ["de-DE-AmalaNeural", "Amala (weiblich)"],
]
DEFAULT_CFG = {
    "stimme": "de-DE-FlorianMultilingualNeural", "tempo": "+12%", "hoehe": "+0Hz", "lautstaerke": 160, "laut_v": 2,
    "farbe": "rot", "effekte": "mittel", "untertitel": True,
    "sfx": True, "sfxlaut": 60, "ambient": False,
    "steuerung": "wort", "wakeword": "Jarvis", "schnipsen": True, "unterbrechen": True, "sprechen_unterbrechen": True, "nur_jarvis": True, "musik_schutz": True, "ducking": True,
    "tts_anbieter": "edge",
    "klatschen": True, "dauerzuhoeren": True, "empfindlichkeit": 6, "schnips_empf": 6, "satzpause": 2.0, "begruessung": True, "ort": "", "name": "",
    "schlafen": 5, "vollbild": True, "autostart": True, "schlaf_schliessen": True, "bildschirm": False,
    "modell": "claude-opus-5-5", "laenge": "kurz", "rechte": "auto", "tempo_claude": "low",
    "ordner": os.path.join(os.path.expanduser("~"), "Documents", "Jarvis"), "sitzung": "",
}
# Damit ORB immer dein Claude-Code-Login (Max-Abo) nutzt und nie einen API-Schlüssel
CLAUDE_ENV_DROP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
VERSION = "70"
ORB_UI = ("Deine Oberfläche (die Larsen gerade sieht): in der Mitte du als flüssige leuchtende Kugel mit Tropfen, "
          "Orbit-Ringen und Sternenhimmel; links eine Uhr und darunter der Gesprächsverlauf mit Eingabefeld; rechts "
          "Karten für System (CPU, RAM, Akku), Wetter mit Stundenvorschau, Aktivität (was du gerade tust) und Vorschläge; "
          "unten ein Dock mit Tastatur, Mikrofon und Einstellungen. Lies dafür keinen Code – du kennst dich.")
KURZ_REGELN = ("Antworte immer auf Deutsch. Du sprichst über ORB, eine Sprachoberfläche; alles wird laut vorgelesen. Antworte wie ein Mensch "
               "im Gespräch: meist EIN kurzer Satz, höchstens zwei, unter 25 Wörtern – auch wenn die Frage groß wirkt; "
               "Larsen fragt nach, wenn er mehr will. Kein Markdown, keine Listen, "
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
    "Ende sonst +1 Stunde); löschen = erst liste, dann loeschen -Id \"<id aus der Liste>\". Zeiten sind Ortszeit.")


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
            + MAIL_REGELN + "\n\n" + BILD_REGELN + "\n\n" + WEB_REGELN + kal)


KURZ_PROMPT = ("Du sprichst gerade über ORB, eine Sprachoberfläche; deine Antwort wird laut vorgelesen. "
               "Antworte in 1 bis 3 kurzen, natürlich gesprochenen Sätzen auf Deutsch, ohne Markdown, Listen, "
               "Tabellen, Emojis oder Code. Arbeite Aufträge trotzdem vollständig ab.")

_cache, _lock, _cfg_lock = {}, threading.Lock(), threading.Lock()
LAST_POLL = [0.0]
LAST_ACTIVE = [0.0]   # wann das Fenster zuletzt gesprochen/zugehört hat  # wann das Fenster zuletzt nachgefragt hat
ON_SHOW = [None]    # wird von orb_app gesetzt: öffnet/zeigt das Fenster
ON_HIDE = [None]    # schließt das Fenster (Schlaf spart Speicher)
ON_UPDATE = [None]  # neuesten Stand von GitHub holen und neu starten
ON_CHECK = [None]   # liefert den neueren GitHub-Stand (sha) oder None, wenn ORB aktuell ist

_mouse = {"t": 0.0, "on": False}
CLOSE_LOG = os.path.join(HOME, "schliessen.log")   # warum ORB sich geschlossen/ausgeblendet hat (Grund + Uhrzeit)
RUN_MARK = os.path.join(HOME, "laeuft.txt")        # fehlt beim sauberen Beenden – liegt er beim Start noch da, war es ein Absturz


HOER_LOG = os.path.join(HOME, "hoeren.log")       # Spracherkennung: welcher Erkenner wann startet/endet (Fehlersuche „hört nicht“)


def log_close(grund, path=CLOSE_LOG):
    """Grund fürs Schließen/Ausblenden mit Uhrzeit protokollieren (Datei bleibt klein)."""
    if os.environ.get("ORB_PORT"):
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


def write_state(**kw):
    """Zustand schreiben – mit Lock (mehrere Threads) und Wiederholung, falls Windows die Datei kurz sperrt."""
    with _state_lock:
        st = read_state()
        st.update(kw)
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
    return cfg


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
def synth(text, cfg=None):
    """Microsoft-Neural-Stimme (online) → Windows-Stimme (offline)."""
    cfg = cfg or load_cfg()
    try:
        import asyncio
        import edge_tts

        async def run():
            buf = bytearray()
            com = edge_tts.Communicate(text, cfg["stimme"], rate=cfg["tempo"], pitch=cfg["hoehe"])
            async for chunk in com.stream():
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
            return bytes(buf)

        data = asyncio.run(asyncio.wait_for(run(), 30))
        if data:
            return data
    except Exception as e:
        print("Neural-Stimme nicht verfügbar, nutze Windows-Stimme:", e)
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
    return shutil.which("claude") or os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")


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
                try:   # aktueller Bildschirm für ORB (nur ansehen, wenn die Frage ihn betrifft)
                    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                    os.path.join(RES, "bildschirm.ps1")], capture_output=True, timeout=8, creationflags=NO_WINDOW)
                    text = ("[Bildschirm-Modus: aktueller Screenshot liegt unter %s – nur ansehen, wenn die Frage den "
                            "Bildschirm betrifft.]\n" % os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "screen", "bildschirm.png")) + text
                except Exception as e:
                    print("Screenshot:", e)
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
            m = None
            ende = r"[.!?…:;,](?=\s)" if not self.spoken and len(t) >= 25 else r"[.!?…:;](?=\s)"   # erstes Stück früher
            for m in re.finditer(ende, t):
                pass
            if not m:
                return
            ready, rest = t[: m.end()], t[m.end():]
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


def ask(text):
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

    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd):
            return True
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
    if not titles:
        return {"laeuft": False}
    t = next((x for x in titles if " - " in x), titles[0])
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
                if (p.info["name"] or "").lower() == "msedge.exe" and any("ORB\fenster" in (c or "") for c in p.info["cmdline"] or []):
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
             "Deine letzte Antwort wird laut vorgelesen: 1-2 kurze deutsche Sätze mit dem Ergebnis (bei Dateien: wo es liegt). "
             "Kein Markdown.")


def task_set(tid, **kw):
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
            "--permission-mode", "auto", "--append-system-prompt", BG_REGELN]
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
BLOCK_TYPEN = ("text", "titel", "liste", "zahl", "fortschritt", "bild", "web", "tabelle", "trenner")


def karte_setzen(b):
    """Neues/aktualisiertes Hologramm. b: {id?, titel, groesse: klein|mittel|gross, breite?, hoehe?, farbe?,
    inhalt: [{typ:text|titel|liste|zahl|fortschritt|bild|web|tabelle|trenner, ...}], dauer: Sekunden (0 = bleibt),
    anhaengen: true (Inhalte anfügen statt ersetzen)} – oder {id, zu: true} / {alle_zu: true}."""
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
                if blk["typ"] == "bild":
                    pfad = os.path.abspath(os.path.expandvars(str(blk.get("pfad", ""))))
                    if not (pfad.lower().endswith(BILD_ENDUNGEN) and os.path.isfile(pfad)):
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
                           "dauer": float(b.get("dauer") or 0), "zeit": time.time(), "v": alt.get("v", 0) + 1}
            KARTEN_V[0] += 1
            return {"ok": True, "id": kid}
        KARTEN_V[0] += 1
        return {"ok": True}


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
        if not self.erlaubt(braucht_token=u.path not in ("/", "/index.html", "/version")):
            return
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            with open(PAGE, "rb") as f:
                page = f.read()
            # Token in die eigene Seite einbetten; alle fetch()-Aufrufe der Seite senden es automatisch mit
            inject = ("<script>(()=>{const T='%s',f=window.fetch;window.fetch=(u,o={})=>{o.headers=Object.assign({},"
                      "o.headers||{},{'X-ORB-Token':T});return f(u,o)}})()</script>" % TOKEN).encode()
            self.send(200, page.replace(b"<head>", b"<head>" + inject, 1), "text/html; charset=utf-8")
        elif u.path == "/state":
            LAST_POLL[0] = time.time()
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
            karten_liste()   # abgelaufene Hologramme wegräumen
            st["karten_v"] = KARTEN_V[0]   # Hintergrund-Aufgaben + Entwickler (je ein Hologramm)
            st["bild"] = {"n": BILD["n"], "name": BILD["name"], "rein": BILD["rein"]}   # Bild-Hologramm
            st["gold"] = GOLD["n"]   # Gold-Hologramm auf Zuruf
            st["web"] = {"n": WEB["n"], "url": WEB["url"], "titel": WEB["titel"], "modus": WEB["modus"],
                         "lebt": web_lebt(), "rein": WEB["rein"]}   # Web-Hologramm
            st["anruf"] = in_call()   # während Meet/Teams/Zoom nicht zuhören
            st["version"] = VERSION   # Fenster lädt sich neu, wenn eine neue Version läuft
            for i, p in enumerate(st.get("parts") or []):   # Stimme für alle Stücke vorbereiten
                ensure((st.get("aid"), i), p)
            self.send(200, st)
        elif u.path == "/karten":
            self.send(200, {"karten": [dict(c, inhalt=[{k: v for k, v in blk.items() if k != "pfad"} for blk in c["inhalt"]])
                                       for c in karten_liste()]})
        elif u.path == "/karte/datei":   # Bild aus einem Hologramm (nur Bilddateien, die beim Anlegen geprüft wurden)
            c = KARTEN.get(q.get("id", ""))
            try:
                pfad = c["inhalt"][int(q.get("i", -1))]["pfad"]
                with open(pfad, "rb") as f:
                    data = f.read()
            except Exception:
                return self.send(404, b"", "text/plain")
            ext = os.path.splitext(pfad)[1].lower().lstrip(".")
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
            ent["ev"].wait(60)
            self.audio(ent["data"])
        elif u.path == "/preview":
            cfg = load_cfg()
            cfg.update({k: q[k] for k in ("stimme", "tempo", "hoehe") if k in q})
            self.audio(synth(q.get("text") or "Hallo! So klinge ich mit diesen Einstellungen.", cfg))
        elif u.path == "/config":
            c = load_cfg()
            self.send(200, {"config": c, "stimmen": STIMMEN})
        elif u.path == "/version":
            self.send(200, {"version": VERSION})
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
        elif u.path == "/gold":
            try:
                self.send(200, {"preis": gold_preis(), "zeit": GOLD["zeit"]})
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
        elif u.path == "/greet":
            threading.Thread(target=lambda: write_answer(greeting(), heard="", holo=holo_for("Wetter abrufen", "")), daemon=True).start()
            threading.Thread(target=BRAIN.start, daemon=True).start()  # Gehirn schon mal aufwecken
            self.send(200, {"ok": True})
        elif u.path == "/warm":
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
        elif u.path == "/karte":   # holo.ps1: freies Hologramm anlegen/ändern/schließen
            self.send(200, karte_setzen(b if isinstance(b, dict) else {}))
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
            self.send(200, {"ok": True})
            keep = bool(b.get("keep"))   # nur ausblenden: Seite hört weiter auf „Jarvis“
            log_close("Fenster %s: %s" % ("ausgeblendet" if keep else "geschlossen", b.get("grund") or "unbekannt"))
            if not BRAIN.busy and not keep:
                BRAIN.kill()
            web_schliessen_fenster()   # Webansicht verschwindet mit ORB
            if ON_HIDE[0]:
                threading.Thread(target=ON_HIDE[0], kwargs={"keep": keep}, daemon=True).start()
        elif u.path == "/show":  # Fenster öffnen bzw. nach vorne holen (z. B. zweiter Doppelklick auf ORB.exe)
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
    if os.environ.get("ORB_PORT"):
        pass   # Test-Server (check.py) – echtes Protokoll nicht anfassen
    elif os.path.exists(RUN_MARK):
        log_close("Gestartet – vorher unerwartet beendet (Absturz, Abmelden oder PC aus)")
    else:
        log_close("Gestartet")
    if not os.environ.get("ORB_PORT"):
        mark_running(True)
    write_token()
    threading.Thread(target=load_apps, daemon=True).start()  # App-Liste vorab laden
    threading.Thread(target=idle_reaper, daemon=True).start()
    if not os.environ.get("ORB_PORT"):
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
