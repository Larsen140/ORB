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


def bring_front():
    """ORB-Fenster nach vorne holen (Windows erlaubt das nur mit kleinem Alt-Tasten-Trick)."""
    try:
        u = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def cb(h, _):
            n = u.GetWindowTextLengthW(h)
            if n and u.IsWindowVisible(h):
                b = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, b, n + 1)
                if b.value == "ORB":
                    found.append(h)
            return True

        u.EnumWindows(cb, 0)
        for h in found:
            u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
            u.ShowWindow(h, 9)
            u.SetForegroundWindow(h)
    except Exception as e:
        print("Fenster nach vorne:", e)


def show(wake=False):
    if window_open():
        bring_front()
        if wake:
            server.write_state(wake_req=time.time())
        return
    _win["opened"] = time.time()
    browser = find_browser()
    url = URL + ("/#wake" if wake else "/")
    if not browser:
        webbrowser.open(url)
        return
    profile = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "fenster")
    extra = ["--start-fullscreen"] if server.load_cfg().get("vollbild", True) else []
    subprocess.Popen([browser, "--app=" + url, "--user-data-dir=" + profile] + LEAN + extra)


def hide_window():
    """ORB-Fenster schließen (spart ~800 MB) – im Hintergrund wird weiter auf Klatschen gelauscht."""
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
        floor, cand, last, claps, cfg_t, thr_base = .002, None, 0.0, [], 0.0, .16
        try:
            with sd.RawInputStream(samplerate=sr, channels=1, dtype="int16", blocksize=block) as st:
                while not window_open():
                    raw, _ = st.read(block)
                    x = array.array("h", bytes(raw))
                    now = time.time()
                    if now - cfg_t > 3:
                        cfg_t = now
                        # Empfindlichkeit 1..10 -> Schwelle 0.31..0.04 (leises Laptop-Mikro)
                        thr_base = .04 + (10 - float(server.load_cfg().get("empfindlichkeit", 6))) * .03
                    pk = max(max(x), -min(x)) / 32768.0
                    rms = math.sqrt(sum(v * v for v in x) / len(x)) / 32768.0
                    if cand:
                        if now - cand[0] >= .075:
                            if rms < cand[1] * .35:
                                last = cand[0]
                                claps = [c for c in claps if last - c < 1.0] + [last]
                                if len(claps) >= 2 and .15 < claps[-1] - claps[-2] < .9:
                                    claps = []
                                    show(wake=True)
                                    break
                            cand = None
                    elif now - last > .14 and pk > max(thr_base, floor * 25) and rms > floor * 6:
                        cand = (now, rms)
                    floor = floor * .995 + min(rms, .2) * .005
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
        urllib.request.urlopen(urllib.request.Request(URL + path, data=json.dumps(data or {}).encode(), method="POST",
                                                      headers={"Content-Type": "application/json"}), timeout=3)
    except Exception:
        pass


def main():
    srv = server.make_server()
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
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = server.load_cfg()
    server.set_autostart(bool(cfg.get("autostart", True)))
    threading.Thread(target=clap_loop, daemon=True).start()
    if not BG:
        show()
    while True:  # bleibt im Hintergrund, bis „ORB beenden“ gewählt wird
        time.sleep(3600)


if __name__ == "__main__":
    main()
