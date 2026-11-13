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

from hook import clean, split_sentences  # Markdown -> vorlesbarer Text, Text -> Sprech-Stücke

RES = os.path.dirname(os.path.abspath(__file__))  # Seite & Stimme liegen neben server.py (nicht in der exe)
HOME = os.path.join(os.path.expanduser("~"), "Orb")
STATE = os.path.join(HOME, "state.json")
CONFIG = os.path.join(HOME, "config.json")
PAGE = os.path.join(RES, "index.html")
TTS_PS = os.path.join(RES, "tts.ps1")
PORT = int(os.environ.get("ORB_PORT", "8766"))  # ORB_PORT nur für Tests (update.ps1 prüft auf 8799)
NO_WINDOW = 0x08000000

STIMMEN = [
    ["de-DE-FlorianMultilingualNeural", "Florian (männlich, sehr natürlich)"],
    ["de-DE-SeraphinaMultilingualNeural", "Seraphina (weiblich, sehr natürlich)"],
    ["de-DE-ConradNeural", "Conrad (männlich)"],
    ["de-DE-KillianNeural", "Killian (männlich)"],
    ["de-DE-KatjaNeural", "Katja (weiblich)"],
    ["de-DE-AmalaNeural", "Amala (weiblich)"],
]
DEFAULT_CFG = {
    "stimme": "de-DE-FlorianMultilingualNeural", "tempo": "+12%", "hoehe": "+0Hz", "lautstaerke": 90,
    "farbe": "rot", "effekte": "mittel", "untertitel": True,
    "sfx": True, "sfxlaut": 60, "ambient": False,
    "steuerung": "taste", "wakeword": "Jarvis", "unterbrechen": True,
    "tts_anbieter": "edge", "el_key": "", "el_voice": "", "el_modell": "eleven_flash_v2_5",
    "klatschen": True, "dauerzuhoeren": True, "empfindlichkeit": 6, "begruessung": True, "ort": "", "name": "",
    "schlafen": 5, "vollbild": True, "autostart": True, "schlaf_schliessen": True,
    "modell": "claude-opus-5-5", "laenge": "kurz", "rechte": "auto", "tempo_claude": "low",
    "ordner": os.path.join(os.path.expanduser("~"), "Documents", "Jarvis"), "sitzung": "",
}
# Damit ORB immer dein Claude-Code-Login (Max-Abo) nutzt und nie einen API-Schlüssel
CLAUDE_ENV_DROP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
VERSION = "18"
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


def system_prompt(cfg):
    """Persönlichkeit aus der Wissensbasis + Sprechregeln."""
    persona = ""
    try:
        with open(os.path.join(cfg["ordner"], "persoenlichkeit.md"), encoding="utf-8") as f:
            persona = f.read()[:5000]
    except Exception:
        pass
    return (persona + "\n\n" if persona else "") + ORB_UI + "\n\n" + (KURZ_REGELN if cfg.get("laenge") == "kurz" else LANG_REGELN)


KURZ_PROMPT = ("Du sprichst gerade über ORB, eine Sprachoberfläche; deine Antwort wird laut vorgelesen. "
               "Antworte in 1 bis 3 kurzen, natürlich gesprochenen Sätzen auf Deutsch, ohne Markdown, Listen, "
               "Tabellen, Emojis oder Code. Arbeite Aufträge trotzdem vollständig ab.")

_cache, _lock, _cfg_lock = {}, threading.Lock(), threading.Lock()
LAST_POLL = [0.0]  # wann das Fenster zuletzt nachgefragt hat
ON_SHOW = [None]    # wird von orb_app gesetzt: öffnet/zeigt das Fenster
ON_HIDE = [None]    # schließt das Fenster (Schlaf spart Speicher)
ON_UPDATE = [None]  # neuesten Stand von GitHub holen und neu starten


# ---------- Zustand & Einstellungen ----------
def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seq": 0, "mode": "idle"}


def write_state(**kw):
    st = read_state()
    st.update(kw)
    st["seq"] = int(st.get("seq", 0)) + 1
    st["time"] = time.time()
    os.makedirs(HOME, exist_ok=True)
    tmp = STATE + ".srv.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_cfg(patch):
    with _cfg_lock:
        cfg = load_cfg()
        old = dict(cfg)
        cfg.update({k: v for k, v in patch.items() if k in DEFAULT_CFG
                    and not (k == "el_key" and str(v).startswith("••"))})
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


def write_answer(text, **kw):
    """Fertige Antwort (Begrüßung, lokale Aufträge, Fehler) in Sprech-Stücke zerlegen und ausgeben."""
    write_state(mode="spricht", say=text, parts=split_sentences(text), aid=new_aid(), final=True, **kw)


# ---------- Sprachausgabe ----------
def synth_eleven(text, cfg):
    """ElevenLabs – sehr natürliche Stimme (braucht eigenen API-Schlüssel)."""
    body = json.dumps({"text": text, "model_id": cfg.get("el_modell") or "eleven_flash_v2_5",
                       "voice_settings": {"stability": .42, "similarity_boost": .8, "style": .25, "use_speaker_boost": True,
                                          "speed": max(.7, min(1.2, 1 + int(str(cfg.get("tempo", "+0%")).strip("%+") or 0) / 100))}}).encode()
    req = urllib.request.Request("https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128" % cfg["el_voice"],
                                 data=body, method="POST",
                                 headers={"xi-api-key": cfg["el_key"], "Content-Type": "application/json", "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def el_voices(key):
    req = urllib.request.Request("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        return [[v["voice_id"], v["name"] + (" · " + v.get("labels", {}).get("gender", "") if v.get("labels") else "")]
                for v in json.loads(r.read().decode()).get("voices", [])]


def synth(text, cfg=None):
    """ElevenLabs (falls eingerichtet) → Microsoft-Neural-Stimme (online) → Windows-Stimme (offline)."""
    cfg = cfg or load_cfg()
    if cfg.get("tts_anbieter") == "elevenlabs" and cfg.get("el_key") and cfg.get("el_voice"):
        try:
            return synth_eleven(text, cfg)
        except Exception as e:
            print("ElevenLabs-Fehler, nutze Microsoft-Stimme:", e)
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


def try_local(text):
    """Schnelle Aufträge ohne Claude: Apps/Webseiten öffnen, Wetter. Gibt (Aufgabe, Detail, Antwort) oder None."""
    t = text.strip()
    if WEATHER_RE.search(t) and len(t) < 70 and not re.search(r"\b(morgen|woche|wochenende)\b", t, re.I):
        return "Wetter abrufen", "", weather_text()
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
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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
            self.start()
            self.busy, self.stopped = True, False
            self.buf, self.full, self.spoken, self.aid = "", "", [], new_aid()
            self.last_used = time.time()
            write_state(mode="denkt", heard=text, log=[], task="", detail="", say="", parts=[], aid=self.aid, final=False)
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
            for m in re.finditer(r"[.!?…:;](?=\s)", t):
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
            try:
                o = json.loads(raw.decode("utf-8", "ignore"))
            except Exception:
                continue
            typ = o.get("type")
            if typ == "system" and o.get("subtype") == "init" and o.get("session_id"):
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

    def err_reader(self, proc):
        for raw in proc.stderr:
            line = raw.decode("utf-8", "ignore").strip()
            if line:
                print("[claude]", line[:300])

    def stop(self):
        if self.busy and self.alive():
            self.stopped = True
            self.kill()
            return True
        return False


BRAIN = Brain()


def ask(text):
    try:
        local = try_local(text)
    except Exception as e:
        print("Lokaler Auftrag fehlgeschlagen:", e)
        local = None
    if local:
        task, detail, say = local
        write_state(mode="auftrag", heard=text, task=task, detail=detail, say="", parts=[], aid="",
                    log=[task + (": " + detail if detail else "")])

        def done():
            time.sleep(.6)  # kurz die Hologramm-Animation zeigen
            write_answer(say)

        threading.Thread(target=done, daemon=True).start()
        return True
    return BRAIN.send(text)


def stop():
    return BRAIN.stop()


TERMIN_RE = re.compile(r"^\s*[-*]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})(?:\s+(\d{1,2}[:.]\d{2}))?\s*[-–:]?\s*(.+)$")


def termine():
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


MEDIA_KEYS = {"play": 0xB3, "next": 0xB0, "prev": 0xB1}


def media_key(cmd):
    import ctypes
    vk = MEDIA_KEYS.get(cmd)
    if not vk:
        return False
    ctypes.windll.user32.keybd_event(vk, 0, 1, 0)
    ctypes.windll.user32.keybd_event(vk, 0, 3, 0)
    return True


def idle_reaper():
    """Claude nach 5 Minuten ohne Frage beenden, damit es keinen Speicher belegt (~250 MB)."""
    while True:
        time.sleep(30)
        if BRAIN.alive() and not BRAIN.busy and time.time() - BRAIN.last_used > 300:
            BRAIN.kill()


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
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            with open(PAGE, "rb") as f:
                self.send(200, f.read(), "text/html; charset=utf-8")
        elif u.path == "/state":
            LAST_POLL[0] = time.time()
            st = read_state()
            st["busy"] = BRAIN.busy
            st["version"] = VERSION   # Fenster lädt sich neu, wenn eine neue Version läuft
            for i, p in enumerate(st.get("parts") or []):   # Stimme für alle Stücke vorbereiten
                ensure((st.get("aid"), i), p)
            self.send(200, st)
        elif u.path == "/tts":
            st = read_state()
            aid, i = q.get("aid", ""), int(q.get("i", "-1") or -1)
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
            c["el_key"] = ("••••" + c["el_key"][-4:]) if c.get("el_key") else ""   # Schlüssel nie ganz zurückgeben
            self.send(200, {"config": c, "stimmen": STIMMEN})
        elif u.path == "/el_voices":
            try:
                self.send(200, {"voices": el_voices(load_cfg().get("el_key", ""))})
            except Exception as e:
                self.send(200, {"voices": [], "error": str(e)[:120]})
        elif u.path == "/version":
            self.send(200, {"version": VERSION})
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
        elif u.path == "/termine":
            self.send(200, {"termine": termine()})
        elif u.path == "/spotify":
            try:
                self.send(200, spotify_now())
            except Exception:
                self.send(200, {"laeuft": False})
        else:
            self.send(404, b"", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        b = self.body()
        if u.path == "/ask":
            text = str(b.get("text", "")).strip()
            if not text:
                return self.send(400, {"ok": False})
            self.send(200 if ask(text) else 409, {"ok": True})
        elif u.path == "/stop":
            self.send(200, {"ok": stop()})
        elif u.path == "/media":
            self.send(200, {"ok": media_key(str(b.get("cmd", "")))})
        elif u.path == "/config":
            self.send(200, {"config": save_cfg(b)})
        elif u.path == "/greet":
            threading.Thread(target=lambda: write_answer(greeting(), heard=""), daemon=True).start()
            threading.Thread(target=BRAIN.start, daemon=True).start()  # Gehirn schon mal aufwecken
            self.send(200, {"ok": True})
        elif u.path == "/warm":
            threading.Thread(target=BRAIN.start, daemon=True).start()
            self.send(200, {"ok": True})
        elif u.path == "/sleep":
            if not BRAIN.busy:
                BRAIN.kill()  # im Schlaf keinen Speicher belegen
            self.send(200, {"ok": True})
        elif u.path == "/selfupdate":  # „Nach Updates suchen“ bzw. update.ps1 nach dem Hochladen
            self.send(200, {"ok": bool(ON_UPDATE[0])})
            if ON_UPDATE[0]:
                sha = str(b.get("sha", "")).strip() or None   # update.ps1 schickt den genauen Stand mit
                threading.Thread(target=lambda: (time.sleep(.3), ON_UPDATE[0](sha)), daemon=True).start()
        elif u.path == "/announce":  # z. B. update.ps1: „Update fertig“ laut sagen
            text = str(b.get("text", "")).strip()
            if text:
                write_answer(text, heard="")
            self.send(200, {"ok": bool(text)})
        elif u.path == "/hide":
            self.send(200, {"ok": True})
            if not BRAIN.busy:
                BRAIN.kill()
            if ON_HIDE[0]:
                threading.Thread(target=ON_HIDE[0], daemon=True).start()
        elif u.path == "/show":  # Fenster öffnen bzw. nach vorne holen (z. B. zweiter Doppelklick auf ORB.exe)
            if ON_SHOW[0]:
                threading.Thread(target=ON_SHOW[0], kwargs={"wake": bool(b.get("wake"))}, daemon=True).start()
            self.send(200, {"ok": True})
        elif u.path == "/quit":  # neue ORB-Version übernimmt
            self.send(200, {"ok": True})
            BRAIN.kill()
            threading.Thread(target=lambda: (time.sleep(.3), os._exit(0)), daemon=True).start()
        elif u.path == "/new":
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


def make_server():
    """Gibt den Server zurück, oder None wenn ORB schon läuft."""
    try:
        srv = ExclusiveServer(("127.0.0.1", PORT), Handler)
    except OSError:
        return None
    srv.daemon_threads = True
    threading.Thread(target=load_apps, daemon=True).start()  # App-Liste vorab laden
    threading.Thread(target=idle_reaper, daemon=True).start()
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
