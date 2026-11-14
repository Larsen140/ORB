"""ORB.exe – startet den Server, lauscht im Hintergrund auf Doppelklatschen und öffnet dann das Fenster im Vollbild.
Aufruf mit --hintergrund (Windows-Autostart): kein Fenster, nur lauschen."""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

import server

URL = "http://127.0.0.1:%d" % server.PORT
BG = "--hintergrund" in sys.argv

LEAN = [
    "--autoplay-policy=no-user-gesture-required",
    "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-sync", "--disable-background-networking",
    "--disable-component-update", "--disable-default-apps", "--disable-breakpad",
    "--disable-features=Translate,msEdgeShopping,EdgeCollections,msEdgeSidebarV2,"
    "AutofillServerCommunication,OptimizationHints,MediaRouter,BackForwardCache,Prerender2,"
    "SpareRendererForSitePerProcess,msEdgeEnableNurturingFramework,EdgeShoppingAssistant",
    "--disk-cache-size=1048576",
    # Speicher sparen: Grafikspeicher und JS-Heap begrenzen (gemessen ~50 MB weniger, Bild bleibt gleich)
    "--force-gpu-mem-available-mb=192", "--force-gpu-mem-discardable-limit-mb=64", "--disable-gpu-program-cache",
    "--js-flags=--max-old-space-size=128",
    # damit Zuhören/Klatschen auch weiterläuft, wenn das Fenster nicht im Vordergrund ist
    "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
    "--window-size=1200,820",
]
_win = {"opened": 0.0}


def find_browser():
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    local = os.environ.get("LOCALAPPDATA", "")
    for p in (os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
              os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
              os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
              os.path.join(local, r"Google\Chrome\Application\chrome.exe")):
        if os.path.exists(p):
            return p
    return None


def window_open():
    return time.time() - server.LAST_POLL[0] < 4 or time.time() - _win["opened"] < 15


def orb_windows():
    """Alle ORB-Fenster (auch ausgeblendete) – Edge-App-Fenster mit dem Titel „ORB“."""
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        if u.GetWindowTextLengthW(h) == 3:
            b = ctypes.create_unicode_buffer(4)
            u.GetWindowTextW(h, b, 4)
            c = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(h, c, 64)
            if b.value == "ORB" and c.value.startswith("Chrome_WidgetWin"):
                found.append(h)
        return True

    u.EnumWindows(cb, 0)
    return found


def bring_front():
    """ORB-Fenster nach vorne holen – auch wenn es ausgeblendet war (Windows erlaubt das nur mit kleinem Alt-Tasten-Trick)."""
    try:
        u = ctypes.windll.user32
        for h in orb_windows():
            u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
            u.ShowWindow(h, 9 if u.IsIconic(h) else 5)
            u.SetForegroundWindow(h)
    except Exception as e:
        print("Fenster nach vorne:", e)


def hide_hidden_soon():
    """Gerade gestartetes Fenster sofort ausblenden (Start im Hintergrund, damit „Jarvis“ trotzdem zuhört)."""
    end = time.time() + 20
    while time.time() < end:
        try:
            hs = orb_windows()
            if hs:
                for h in hs:
                    ctypes.windll.user32.ShowWindow(h, 0)
                return
        except Exception:
            pass
        time.sleep(.05)


def window_process_running():
    """Läuft schon ein ORB-Fenster (egal ob die Seite gerade lädt)? Verhindert, dass mehrere Fenster aufgehen."""
    try:
        import psutil
        for p in psutil.process_iter(["name", "cmdline"]):
            if (p.info["name"] or "").lower() == "msedge.exe":
                cl = " ".join(p.info["cmdline"] or [])
                if "ORB\\fenster" in cl and "--app=" in cl:
                    return True
    except Exception:
        pass
    return False


def show(wake=False, hidden=False):
    if window_open() or window_process_running():
        if hidden:
            return
        bring_front()
        if wake:
            server.write_state(wake_req=time.time())
        return
    _win["opened"] = time.time()
    browser = find_browser()
    url = URL + ("/#schlaf" if hidden else "/#wake" if wake else "/")
    if not browser:
        webbrowser.open(url)
        return
    profile = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "fenster")
    extra = ["--start-fullscreen"] if server.load_cfg().get("vollbild", True) else []
    subprocess.Popen([browser, "--app=" + url, "--user-data-dir=" + profile] + LEAN + extra)
    if hidden:
        threading.Thread(target=hide_hidden_soon, daemon=True).start()


def hide_window(keep=False):
    """ORB-Fenster schließen (spart ~800 MB) – im Hintergrund wird weiter auf Klatschen gelauscht.
    keep=True: nur ausblenden – die Seite läuft weiter und hört auf „Jarvis“, Klatschen und Schnipsen."""
    if keep:
        try:
            for h in orb_windows():
                ctypes.windll.user32.ShowWindow(h, 0)
            return
        except Exception as e:
            print("Fenster ausblenden:", e)
    try:
        import psutil
        for p in psutil.process_iter(["name", "cmdline"]):
            if (p.info["name"] or "").lower() == "msedge.exe" and any("ORB\\fenster" in (c or "") for c in p.info["cmdline"] or []):
                try:
                    p.kill()
                except Exception:
                    pass
    except Exception as e:
        print("Fenster schließen:", e)
    server.LAST_POLL[0] = 0
    _win["opened"] = 0
    _win["closed"] = time.time()


def window_watch():
    """Fragt das Fenster plötzlich nicht mehr nach (ohne dass ORB es geschlossen hat), Grund protokollieren."""
    gemeldet, geheilt = False, 0.0
    while True:
        time.sleep(3)
        lp = server.LAST_POLL[0]
        if lp and time.time() - lp > 12 and lp > _win.get("closed", 0) + 3:
            if not gemeldet:
                server.log_close("Fenster meldet sich nicht mehr (abgestürzt oder von Hand geschlossen)")
                gemeldet = True
            # Fenster läuft noch, meldet sich aber 30 s nicht (z. B. Fehlerseite nach Update-Neustart):
            # neu öffnen, sonst sind Schnipsen und Klatschen im Fenster tot (höchstens alle 2 Min.)
            if time.time() - lp > 30 and time.time() - geheilt > 120 and window_process_running():
                geheilt = time.time()
                try:
                    sichtbar = any(ctypes.windll.user32.IsWindowVisible(h) for h in orb_windows())
                except Exception:
                    sichtbar = True
                server.log_close("Fenster hing → neu geöffnet")
                hide_window()
                for _ in range(20):   # warten, bis Edge wirklich weg ist – sonst öffnet show() nichts
                    time.sleep(.5)
                    if not window_process_running():
                        break
                show(hidden=not sichtbar)
        else:
            gemeldet = False


def snap_ratio(x, sr, rausch=None):
    """Helle (2–5,5 kHz) zu volle Energie (150–1500 Hz) – Schnipsen > 1,4, Klatschen darunter.
    Goertzel auf wenigen Frequenzen, nur für Knall-Kandidaten berechnet. rausch=(tief, hell) wird vorher abgezogen
    (Lüfter-Rauschprofil), damit ein Knall im Rauschen nicht dumpfer oder heller wirkt, als er ist."""
    lo, hi = baender(x, sr)
    if rausch:
        lo, hi = max(lo - rausch[0], lo * .05), max(hi - rausch[1], 0.0)
    return (hi * 3500) / ((lo * 1350) or 1e-9)


def baender(x, sr):
    """Mittlere Goertzel-Leistung tief (200–1400 Hz) und hell (2–5,2 kHz)."""
    import math

    def power(f):
        w = 2 * math.cos(2 * math.pi * f / sr)
        s1 = s2 = 0.0
        for v in x:
            s1, s2 = v + w * s1 - s2, s1
        return s1 * s1 + s2 * s2 - w * s1 * s2

    return (sum(power(f) for f in range(200, 1500, 200)) / 7, sum(power(f) for f in range(2000, 5500, 400)) / 9)


class KlatschErkenner:
    """Doppelklatschen im Dauerrauschen (z. B. zwei Lüfter direkt am Mikro).
    Misst laufend das Grundrauschen (Pegel, Spitzen, Helligkeit, Klangprofil), zieht es ab und setzt alle Schwellen
    RELATIV dazu – in einem stillen Raum bleibt alles wie bisher, bei lautem Rauschen sinken die festen Faktoren
    auf einen sicheren Abstand über den Rausch-Spitzen. Eingabe: 16-Bit-Blöcke (array 'h'), Ausgabe True = Doppelklatscher."""
    KAL = 40   # erste ~1 s nur messen (Kalibrierung), dann erkennen

    def __init__(self, sr=16000, rausch=None):
        self.sr = sr
        r = rausch or {}
        self.floor, self.npk = r.get("floor", .0003), r.get("npk", .001)
        self.nhf, self.nprof = r.get("nhf", 1.0), r.get("nprof")
        self.n = 0 if not rausch else self.KAL
        self.kal = []
        self.cand, self.last, self.claps, self.pks, self.hist = None, 0.0, [], [], []
        self.thr_base, self.prof_n = .0024, 0

    def rausch(self):
        return {"floor": self.floor, "npk": self.npk, "nhf": self.nhf, "nprof": self.nprof}

    def schwellen(self):
        """(Spitze, Pegel) für einen Klatscher – nie unter den alten Werten im stillen Raum, im Rauschen relativ."""
        f, tb = self.floor, self.thr_base
        pk = max(tb, min(f * 40, max(self.npk * 6, .012)))
        rms = max(tb * .2, f * 4, min(f * 10, .003))
        return pk, rms

    def feed(self, x, now, maus_ok=True):
        import math
        n = len(x)
        e = float(sum(v * v for v in x)) or 1.0
        pk = max(max(x), -min(x)) / 32768.0
        rms = math.sqrt(e / n) / 32768.0
        self.n += 1
        if self.n <= self.KAL:   # Kalibrierung: Rauschpegel aus der ruhigsten Hälfte der ersten Sekunde
            self.kal.append((rms, pk, sum((x[i] - x[i - 1]) ** 2 for i in range(1, n)) / e))
            if self.n == self.KAL:
                k = sorted(self.kal)[:self.KAL // 2]
                self.floor = max(1e-5, k[len(k) // 2][0])
                self.npk = max(self.floor * 2, sorted(p for _, p, _ in k)[len(k) // 2])
                self.nhf = sorted(h for _, _, h in k)[len(k) // 2]
                self.kal = []
            self.hist = (self.hist + [rms])[-8:]
            return False
        f = self.floor
        pre = sum(self.hist[-6:-1]) / 5 if len(self.hist) >= 6 else 1.0   # Lautstärke 25–150 ms vorher
        self.hist = (self.hist + [rms])[-8:]
        treffer = False
        if self.cand:
            c = self.cand
            if now - c[0] < .075:   # lautesten Block merken und den ZWEITEN Block danach (Klatschen ist nach 25–50 ms fast weg)
                if rms > c[1]:
                    self.cand = c = (c[0], rms, max(c[2], pk), [])
                elif len(c[3]) < 2:
                    c[3].append(rms)
            else:
                if len(c[3]) >= 2 and c[3][1] - f > (c[1] - f) * .5:
                    rms = max(rms, c[1])   # klang nicht sofort ab (Silbe/Ton) -> kein Knall
                # Klatschen klingt kurz nach (auf Rauschniveau zurück); Mausklick im selben Moment -> verwerfen
                if rms < max(c[1] * .35, f * 1.7) and maus_ok:
                    self.last = c[0]
                    self.claps = [t for t in self.claps if self.last - t < 1.1] + [self.last]
                    self.pks = (self.pks + [c[2]])[-2:]
                    p = self.pks
                    gleich = len(p) < 2 or (p[0] / p[1] < 3 and p[1] / p[0] < 3)   # zwei ähnlich laute Klatscher
                    if len(self.claps) >= 2 and .22 < self.claps[-1] - self.claps[-2] < 1.0 and gleich:
                        self.claps = []
                        treffer = True
                elif rms >= max(c[1] * .35, f * 1.7):
                    self.claps = []   # Dauergeräusch statt Knall
                self.cand = None
        else:
            thr_pk, thr_rms = self.schwellen()
            if now - self.last > .14 and pk > thr_pk and rms > thr_rms:
                # Klatschen ist breitbandig; ein Mausklick ist fast nur hohes Klicken – Helligkeit OHNE Rauschanteil
                d = sum((x[i] - x[i - 1]) ** 2 for i in range(1, n))
                rn = (f * 32768.0) ** 2 * n                       # Energie des Grundrauschens in diesem Block
                hf = max(d - rn * self.nhf, 0.0) / max(e - rn, e * .05)
                ex_pre = max(pre - f * 1.1, 0.0)                   # was vorher ÜBER dem Rauschen lag (Sprache/Musik)
                ex_rms = rms - f
                if (hf < 2.6 and pk / rms < 18 and ex_pre < ex_rms * .3 and maus_ok
                        and snap_ratio(x, self.sr, self.nprof) < 1.4):
                    self.cand = (now, rms, pk, [])
        # Grundrauschen nachführen: Stille schnell übernehmen, nach oben langsam und ohne Knall-Ausreißer
        if rms < f:
            self.floor = f * .7 + rms * .3
        else:
            self.floor = f * .995 + min(rms, f * 2.5, .2) * .005
        if rms < self.floor * 1.6 and not self.cand:   # reiner Rauschblock: Spitzen, Helligkeit und Klangprofil lernen
            self.npk = self.npk * .97 + pk * .03
            self.nhf = self.nhf * .97 + (sum((x[i] - x[i - 1]) ** 2 for i in range(1, n)) / e) * .03 if self.n % 4 == 0 else self.nhf
            self.prof_n += 1
            if self.prof_n % 20 == 1:   # Rauschprofil (Goertzel tief/hell) ~2× pro Sekunde
                lo, hi = baender(x, self.sr)
                self.nprof = (lo, hi) if not self.nprof else (self.nprof[0] * .8 + lo * .2, self.nprof[1] * .8 + hi * .2)
        return treffer


_RAUSCH = None   # gemessenes Grundrauschen (bleibt beim erneuten Lauschen erhalten – keine neue Kalibrierung nötig)


def clap_loop():
    """Lauscht nur, solange das Fenster zu ist – erkennt zwei kurze, laute Knalle kurz hintereinander.
    Ohne numpy (spart Speicher): rohe 16-Bit-Werte. Schwellen relativ zum gemessenen Grundrauschen (Lüfter)."""
    global _RAUSCH
    try:
        import array
        import sounddevice as sd
    except Exception as e:
        print("Klatsch-Erkennung im Hintergrund nicht verfügbar:", e)
        return
    sr, block = 16000, 400  # 25 ms
    while True:
        if window_open():   # Klatschen ist nie abschaltbar
            time.sleep(1)
            continue
        k, cfg_t = KlatschErkenner(sr, _RAUSCH), 0.0
        try:
            with sd.RawInputStream(samplerate=sr, channels=1, dtype="int16", blocksize=block) as st:
                while not window_open():
                    raw, _ = st.read(block)
                    x = array.array("h", bytes(raw))
                    now = time.time()
                    if now - cfg_t > 3:
                        cfg_t = now
                        if k.n >= k.KAL:
                            _RAUSCH = k.rausch()
                        # Empfindlichkeit 1..10 -> Grundschwelle (leise Laptop-Mikros: Klatscher kommen nur mit ~0,003–0,01 an)
                        k.thr_base = .0006 * (11 - float(server.load_cfg().get("empfindlichkeit", 6)))
                        try:   # läuft Musik, zählen nur deutliche Knalle (Beats sind kein Klatschen)
                            if server.load_cfg().get("musik_schutz", True) and server.musik_status().get("an"):
                                k.thr_base *= 2.5
                        except Exception:
                            pass
                    maus_ok = server.mouse_ago() > .4 and server.input_ago() > .4
                    if k.feed(x, now, maus_ok):
                        _RAUSCH = k.rausch()
                        show(wake=True)
                        break
        except Exception as e:
            print("Mikrofon:", e)
            time.sleep(5)


def other_instance():
    try:
        with urllib.request.urlopen(URL + "/version", timeout=2) as r:
            return json.loads(r.read().decode()).get("version")
    except Exception:
        return None


def post(path, data=None):
    try:
        try:
            with open(server.TOKEN_FILE) as f:
                tok = f.read().strip()   # Token der laufenden ORB-Instanz
        except Exception:
            tok = ""
        urllib.request.urlopen(urllib.request.Request(URL + path, data=json.dumps(data or {}).encode(), method="POST",
                                                      headers={"Content-Type": "application/json", "X-ORB-Token": tok}), timeout=3)
    except Exception:
        pass


RESTART = "--neustart" in sys.argv


def restart(update=False):
    """ORB neu starten (z. B. nach einem Update von GitHub). Das offene Fenster bleibt und lädt sich selbst neu."""
    exe = os.environ.get("ORB_EXE") or sys.executable
    args = [exe, "--neustart"] + (["--update"] if update else [])
    if getattr(sys, "frozen", False) or exe.lower().endswith(".exe") and "python" not in exe.lower():
        # Wichtig: frische Umgebung für die neue exe – sonst übernimmt sie den Temp-Ordner dieser Instanz,
        # der beim Beenden gelöscht wird, und stürzt sofort ab (ORB war nach Updates „weg“).
        env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k not in ("_MEIPASS2", "_MEIPASS")}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen(args, env=env, creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--neustart"], creationflags=0x00000008 | 0x00000200)
    server.BRAIN.kill()
    server.clean_exit("Neustart" + (" für Update" if update else " (Update eingespielt)"))


def github_head():
    """Neuester Stand von main – über die Git-Schnittstelle (sparsam, ohne API-Abfragegrenze)."""
    req = urllib.request.Request("https://github.com/Larsen140/ORB.git/info/refs?service=git-upload-pack",
                                 headers={"User-Agent": "git/2.45 ORB"})
    with urllib.request.urlopen(req, timeout=8) as r:
        for line in r.read().decode("utf-8", "ignore").split("\n"):
            if line.endswith("refs/heads/main") or " refs/heads/main" in line:
                sha = line[4:44] if len(line) > 44 else ""
                if len(sha) == 40:
                    return sha
    return None


def apply_update(sha=None):
    """Genau diesen GitHub-Stand laden (vorher sichern) und neu starten – ohne auf GitHubs verzögerte API zu warten."""
    launcher = sys.modules.get("__main__")
    if not hasattr(launcher, "install_code"):
        return restart(update=True)
    sha = sha or github_head()
    if sha and sha != launcher.local_sha():
        for _ in range(10):   # direkt nach dem Hochladen kann GitHub den Stand ein paar Sekunden noch nicht ausliefern
            try:
                launcher.install_code(sha)
                break
            except Exception as e:
                print("Update-Download:", e)
                time.sleep(2)
        else:
            return
    restart(update=False)


def check_update():
    """Neueren GitHub-Stand liefern (sha) oder None, wenn ORB aktuell ist."""
    launcher = sys.modules.get("__main__")
    sha = github_head()
    if not sha:
        raise OSError("kein Stand")
    if sha == launcher.local_sha() or sha in getattr(launcher, "bad_shas", lambda: [])():
        return None
    return sha


def update_loop():
    """Jede Minute auf GitHub nachsehen und ein Update SOFORT einspielen – nur nicht mitten im Sprechen oder Arbeiten."""
    launcher = sys.modules.get("__main__")
    if not hasattr(launcher, "local_sha"):
        return  # läuft ohne Starter (Entwicklung)
    while True:
        time.sleep(60)
        try:
            sha = github_head()
            if not sha or sha == launcher.local_sha() or sha in getattr(launcher, "bad_shas", lambda: [])():
                continue
            st = server.read_state()
            ruhig = (not server.BRAIN.busy and not any(t.get("status") == "laeuft" for t in server.TASKS.values()) and st.get("mode") not in ("denkt", "auftrag", "wartet")
                     and time.time() - float(st.get("time", 0)) > 12
                     and time.time() - server.LAST_ACTIVE[0] > 60)   # nicht mitten im Sprechen/Zuhören   # gerade nichts gesagt/getan
            if ruhig:
                apply_update(sha)
        except Exception as e:
            print("Update-Prüfung:", e)


def announce_update():
    """Nach einem Update einmal kurz Bescheid sagen."""
    launcher = sys.modules.get("__main__")
    if not hasattr(launcher, "local_sha"):
        return
    sha, marker = launcher.local_sha(), os.path.join(server.HOME, "letzter_stand.txt")
    try:
        with open(marker) as f:
            alt = f.read().strip()
    except Exception:
        alt = ""
    if sha and sha != alt:
        with open(marker, "w") as f:
            f.write(sha)
        if alt:
            time.sleep(4)   # Fenster hat sich inzwischen neu geladen
            n = server.neu_laden("orb")   # Einführung vom Entwickler (neu.ps1)?
            if n:
                server.neu_zeigen("orb", n["punkte"], n["nutzen"])
                server.write_answer("Update installiert. Neu: %s" % n["punkte"][0], heard="")
            else:
                server.write_answer("Update installiert, Version %s." % server.VERSION, heard="")


def backup_jarvis():
    """Wissensbasis (Documents/Jarvis) täglich sichern – die letzten 30 Tage bleiben erhalten."""
    import zipfile
    src = os.path.join(os.path.expanduser("~"), "Documents", "Jarvis")
    dst = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "Sicherungen")
    while True:
        try:
            if os.path.isdir(src) and os.listdir(src):
                os.makedirs(dst, exist_ok=True)
                ziel = os.path.join(dst, "Jarvis_%s.zip" % time.strftime("%Y-%m-%d"))
                if not os.path.exists(ziel):
                    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as z:
                        for root, _dirs, files in os.walk(src):
                            for f in files:
                                full = os.path.join(root, f)
                                z.write(full, os.path.relpath(full, src))
                    import glob
                    for alt in sorted(glob.glob(os.path.join(dst, "Jarvis_*.zip")))[:-30]:
                        os.remove(alt)
        except Exception as e:
            print("Jarvis-Sicherung:", e)
        time.sleep(6 * 3600)


def main():
    srv = server.make_server()
    if not srv and RESTART:
        for _ in range(60):  # alte Instanz beendet sich gerade – Port wird gleich frei
            time.sleep(.25)
            srv = server.make_server()
            if srv:
                break
        if not srv:
            return
    if not srv:
        v = other_instance()
        if v == server.VERSION:
            if not BG:
                post("/show")      # läuft schon – nur Fenster zeigen
            return
        post("/quit")              # alte Version ablösen
        for _ in range(20):
            time.sleep(.25)
            srv = server.make_server()
            if srv:
                break
        if not srv:
            return
    # alte Kopien vom letzten Update wegräumen (gesperrte bleiben bis zum nächsten Start liegen)
    try:
        import glob
        here = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.join(os.path.expanduser("~"), "Desktop")
        for f in glob.glob(os.path.join(here, "ORB_alt*.exe")):
            try:
                os.remove(f)
            except OSError:
                pass
    except Exception:
        pass
    server.ON_SHOW[0] = show
    server.ON_HIDE[0] = hide_window
    server.ON_UPDATE[0] = apply_update
    if hasattr(sys.modules.get("__main__"), "local_sha"):
        server.ON_CHECK[0] = check_update
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = server.load_cfg()
    server.set_autostart(bool(cfg.get("autostart", True)))
    threading.Thread(target=clap_loop, daemon=True).start()
    threading.Thread(target=update_loop, daemon=True).start()
    threading.Thread(target=announce_update, daemon=True).start()
    threading.Thread(target=backup_jarvis, daemon=True).start()
    threading.Thread(target=window_watch, daemon=True).start()
    if not BG and not RESTART:
        show()
    elif BG and cfg.get("steuerung", "wort") == "wort":
        show(hidden=True)   # unsichtbar starten, damit „Jarvis“ auch direkt nach dem PC-Start zuhört
    while True:  # bleibt im Hintergrund, bis „ORB beenden“ gewählt wird
        time.sleep(3600)


if __name__ == "__main__":
    main()
