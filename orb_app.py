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


def snap_ratio(x, sr):
    """Helle (2–5,5 kHz) zu volle Energie (150–1500 Hz) – Schnipsen > 1,4, Klatschen darunter.
    Goertzel auf wenigen Frequenzen, nur für Knall-Kandidaten berechnet."""
    import math

    def power(f):
        w = 2 * math.cos(2 * math.pi * f / sr)
        s1 = s2 = 0.0
        for v in x:
            s1, s2 = v + w * s1 - s2, s1
        return s1 * s1 + s2 * s2 - w * s1 * s2

    lo = sum(power(f) for f in range(200, 1500, 200)) / 7
    hi = sum(power(f) for f in range(2000, 5500, 400)) / 9
    return (hi * 3500) / ((lo * 1350) or 1e-9)


def clap_loop():
    """Lauscht nur, solange das Fenster zu ist – erkennt zwei kurze, laute Knalle kurz hintereinander.
    Ohne numpy (spart Speicher): rohe 16-Bit-Werte."""
    try:
        import array
        import math
        import sounddevice as sd
    except Exception as e:
        print("Klatsch-Erkennung im Hintergrund nicht verfügbar:", e)
        return
    sr, block = 16000, 400  # 25 ms
    while True:
        if window_open() or not server.load_cfg().get("klatschen", True):
            time.sleep(1)
            continue
        floor, cand, last, claps, cfg_t, thr_base = .0003, None, 0.0, [], 0.0, .0024
        hist, pks = [], []
        try:
            with sd.RawInputStream(samplerate=sr, channels=1, dtype="int16", blocksize=block) as st:
                while not window_open():
                    raw, _ = st.read(block)
                    if server.in_call():
                        cand, claps = None, []
                        continue   # während eines Meetings nicht auf Klatschen reagieren
                    x = array.array("h", bytes(raw))
                    now = time.time()
                    if now - cfg_t > 3:
                        cfg_t = now
                        # Empfindlichkeit 1..10 -> Schwelle 0.31..0.04 (leises Laptop-Mikro)
                        thr_base = .0006 * (11 - float(server.load_cfg().get("empfindlichkeit", 6)))   # leise Laptop-Mikros: Klatscher kommen nur mit ~0,003–0,01 an
                    pk = max(max(x), -min(x)) / 32768.0
                    rms = math.sqrt(sum(v * v for v in x) / len(x)) / 32768.0
                    pre = sum(hist[-6:-1]) / 5 if len(hist) >= 6 else 1.0   # Lautstärke 25–150 ms vorher
                    hist = (hist + [rms])[-8:]
                    if cand:
                        if now - cand[0] >= .075:
                            # Klatschen klingt kurz nach; Mausklick im selben Moment -> verwerfen
                            if rms < cand[1] * .35 and server.mouse_ago() > .4:
                                last = cand[0]
                                claps = [c for c in claps if last - c < 1.1] + [last]
                                pks = (pks + [cand[2]])[-2:]
                                gleich = len(pks) < 2 or (pks[0] / pks[1] < 3 and pks[1] / pks[0] < 3)   # zwei ähnlich laute Klatscher
                                if len(claps) >= 2 and .22 < claps[-1] - claps[-2] < 1.0 and gleich:
                                    claps = []
                                    show(wake=True)
                                    break
                            elif rms >= cand[1] * .35:
                                claps = []   # Dauergeräusch statt Knall
                            cand = None
                    elif now - last > .14 and pk > max(thr_base, floor * 40) and rms > max(floor * 10, thr_base * .2):
                        # Klatschen ist breitbandig; ein Mausklick ist fast nur hohes Klicken
                        e = sum(v * v for v in x) or 1
                        hf = sum((x[i] - x[i - 1]) ** 2 for i in range(1, len(x))) / e
                        # Schnipser (hell, Energie bei 2–5 kHz) zählen nicht als Klatschen
                        # Knall aus der Stille (Sprache/Musik hat davor schon Energie) und keine Tastatur/Maus gerade
                        if (hf < 2.6 and pk / rms < 18 and pre < rms * .3 and server.mouse_ago() > .4
                                and server.input_ago() > .4 and snap_ratio(x, sr) < 1.4):
                            cand = (now, rms, pk)
                    floor = rms if rms < floor else floor * .995 + min(rms, .2) * .005   # Stille sofort übernehmen
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
    os._exit(0)


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
            ruhig = (not server.BRAIN.busy and st.get("mode") not in ("denkt", "auftrag", "wartet")
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
    if not BG and not RESTART:
        show()
    elif BG and cfg.get("steuerung", "wort") == "wort":
        show(hidden=True)   # unsichtbar starten, damit „Jarvis“ auch direkt nach dem PC-Start zuhört
    while True:  # bleibt im Hintergrund, bis „ORB beenden“ gewählt wird
        time.sleep(3600)


if __name__ == "__main__":
    main()
