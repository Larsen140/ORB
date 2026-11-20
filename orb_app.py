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

from ctypes import wintypes as _wt
# 64-Bit: ohne Typangaben kommt HWND_TOPMOST (-1) falsch an und Windows lehnt SetWindowPos still ab (Mini-Kugel blieb groß)
ctypes.windll.user32.SetWindowPos.argtypes = [_wt.HWND, _wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
ctypes.windll.user32.SetWindowPos.restype = _wt.BOOL

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


def _ist_vollbild(h):
    u = ctypes.windll.user32
    r = (ctypes.c_long * 4)()
    u.GetWindowRect(h, ctypes.byref(r))
    return r[0] <= 0 and r[1] <= 0 and r[2] >= u.GetSystemMetrics(0) and r[3] >= u.GetSystemMetrics(1) and r[0] > -8


def bring_front():
    """ORB-Fenster nach vorne holen – auch wenn es ausgeblendet war (Windows erlaubt das nur mit kleinem Alt-Tasten-Trick)."""
    try:
        u = ctypes.windll.user32
        for h in orb_windows():
            r = (ctypes.c_long * 4)()
            u.GetWindowRect(h, ctypes.byref(r))
            draussen = r[0] < -10000   # versteckt gestartet (außerhalb des Bildschirms, damit nichts aufblitzt)
            if draussen:
                u.SetWindowPos(h, 0, 0, 0, 1280, 800, 0x0004 | 0x0010)   # zurück auf den Bildschirm (noch unsichtbar)
                u.ShowWindow(h, 3)   # maximiert zeigen
            else:
                u.ShowWindow(h, 9 if u.IsIconic(h) else 5)
            u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
            u.SetForegroundWindow(h)
            if server.load_cfg().get("vollbild", True) and not _ist_vollbild(h):   # z. B. Edge hat den Vollbildmodus verlassen
                time.sleep(.2)
                if u.GetForegroundWindow() == h and not _ist_vollbild(h):
                    u.keybd_event(0x7A, 0, 0, 0); u.keybd_event(0x7A, 0, 2, 0)   # F11 = Vollbild
    except Exception as e:
        print("Fenster nach vorne:", e)


def _voll(h):
    u = ctypes.windll.user32
    r = (ctypes.c_long * 4)()
    u.GetWindowRect(h, ctypes.byref(r))
    return r[0] <= 0 and r[1] <= 0 and r[2] >= u.GetSystemMetrics(0) and r[3] >= u.GetSystemMetrics(1)


def _neu_oeffnen(extra, hash_=""):
    """Fenster schließen und neu öffnen (ein mit --start-fullscreen geöffnetes Fenster lässt sich nicht verkleinern)."""
    if server.fremd_gesperrt():
        return
    hide_window()
    time.sleep(1.2)
    browser = find_browser()
    if not browser:
        return
    profile = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "fenster")
    _win["opened"] = time.time()
    subprocess.Popen([browser, "--app=" + URL + "/" + hash_, "--user-data-dir=" + profile] + LEAN + extra)
    for _ in range(80):
        time.sleep(0.1)
        if orb_windows():
            time.sleep(0.3)
            return


def mini(an=True):
    """Mini-ORB: Fenster als kleine schwebende Kugel unten rechts (immer obenauf, an der Titelleiste verschiebbar,
    hört weiter zu) – bzw. zurück auf groß/Vollbild. Klappt das Umschalten nicht, wird das Fenster passend neu geöffnet."""
    u = ctypes.windll.user32
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    w, hh = 300, 360
    x, y = sw - w - 18, sh - hh - 60
    if server.fremd_gesperrt():
        return
    hs = orb_windows()
    if not hs:
        if an:
            _neu_oeffnen(["--window-size=%d,%d" % (w, hh), "--window-position=%d,%d" % (x, y)], "#wake")
            hs = orb_windows()
        else:
            return show()
    for h in hs:
        u.ShowWindow(h, 9 if u.IsIconic(h) else 5)
        u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
        u.SetForegroundWindow(h)
        if an:
            if _voll(h):
                u.keybd_event(0x7A, 0, 0, 0); u.keybd_event(0x7A, 0, 2, 0)   # F11: Vollbild verlassen
                time.sleep(.45)
            if _voll(h):   # Start-Vollbild lässt sich nicht verlassen → klein neu öffnen
                _neu_oeffnen(["--window-size=%d,%d" % (w, hh), "--window-position=%d,%d" % (x, y)], "#wake")
                hs2 = orb_windows()
                if not hs2:
                    return
                h = hs2[0]
            u.ShowWindow(h, 9)   # wiederherstellen (nicht maximiert)
            u.SetWindowPos(h, -1, x, y, w, hh, 0x40)   # HWND_TOPMOST, SWP_SHOWWINDOW
            return
        u.SetWindowPos(h, -2, 0, 0, 0, 0, 0x3 | 0x40)   # HWND_NOTOPMOST, Größe/Ort behalten
        u.ShowWindow(h, 3)   # maximieren
        if server.load_cfg().get("vollbild", True) and not _voll(h):
            time.sleep(.3)
            u.keybd_event(0x7A, 0, 0, 0); u.keybd_event(0x7A, 0, 2, 0)   # F11: wieder Vollbild
            time.sleep(.6)
            if not _voll(h):
                _neu_oeffnen(["--start-fullscreen"], "#wake")
        return


OHR_PY = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "ohr", "venv", "Scripts", "pythonw.exe")


def ohr_wache():
    """Startet ORBs lokales Ohr (ohr.py im eigenen venv), sobald es installiert ist, und hält es am Laufen."""
    p = None
    try:   # Ohr eines vorherigen ORB (vor Update/Neustart) beenden – sonst laufen zwei
        import psutil
        for q in psutil.process_iter(["name", "cmdline"]):
            if (q.info["name"] or "").lower() in ("pythonw.exe", "python.exe") and any("ohr.py" in c for c in (q.info["cmdline"] or [])):
                q.kill()
    except Exception:
        pass
    while True:
        try:
            an = server.load_cfg().get("ohr", True) and os.path.exists(OHR_PY)
            skript = os.path.join(os.path.dirname(os.path.abspath(server.__file__)), "ohr.py")
            if an and (p is None or p.poll() is not None) and os.path.exists(skript):
                p = subprocess.Popen([OHR_PY, skript], creationflags=0x08000000, env=dict(os.environ, ORB_PORT=str(server.PORT)))
                server.OHR["pid"] = p.pid
            elif not an and p is not None and p.poll() is None:
                p.kill()
                p = None
        except Exception as e:
            print("Ohr:", e)
        time.sleep(10)


STIMME_PY = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "stimme", "venv", "Scripts", "pythonw.exe")


def stimme_wache():
    """Startet die lokale KI-Stimme (stimme.py), wenn eine lokale Stimme gewählt ist, und hält sie am Laufen."""
    p = None
    try:
        import psutil
        for q in psutil.process_iter(["name", "cmdline"]):
            if (q.info["name"] or "").lower() in ("pythonw.exe", "python.exe") and any("stimme.py" in c for c in (q.info["cmdline"] or [])):
                q.kill()   # Rest eines vorherigen ORB
    except Exception:
        pass
    while True:
        try:
            an = str(server.load_cfg().get("stimme", "")).startswith("lokal:") and os.path.exists(STIMME_PY)
            skript = os.path.join(os.path.dirname(os.path.abspath(server.__file__)), "stimme.py")
            if an and (p is None or p.poll() is not None) and os.path.exists(skript):
                p = subprocess.Popen([STIMME_PY, skript], creationflags=0x08000000)
                server.OHR["stimme_pid"] = p.pid
            elif not an and p is not None and p.poll() is None:
                p.kill()
                p = None
        except Exception as e:
            print("Stimme:", e)
        time.sleep(10)


def gesicht_beim_start():
    """Gesichtssperre: nur beim PC-Start (nicht bei jedem ORB-Neustart/Update) unsichtbar per Webcam prüfen, ob Larsen davor sitzt.
    Ist er es nicht, sperrt gesicht.py WhatsApp/Instagram/Snapchat, bis er erkannt wird."""
    try:
        import psutil
        import shutil
        # Windows-Schnellstart: boot_time bleibt beim „Herunterfahren“ alt → Start der Anmeldung (explorer.exe) zählt
        anmeldung = min((p.info["create_time"] for p in psutil.process_iter(["name", "create_time"])
                         if (p.info["name"] or "").lower() == "explorer.exe"), default=psutil.boot_time())
        sitzung = max(psutil.boot_time(), anmeldung)
        if not server.load_cfg().get("gesichtssperre", True) or time.time() - sitzung > 600:
            return
        pyw = shutil.which("pyw") or shutil.which("pythonw")
        skript = os.path.join(os.path.dirname(os.path.abspath(server.__file__)), "gesicht.py")
        if pyw and os.path.exists(skript) and os.path.exists(os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "gesicht", "profil.npy")):
            subprocess.Popen([pyw] + (["-3"] if pyw.lower().endswith("pyw.exe") else []) + [skript, "waechter"], creationflags=0x08000000)
    except Exception as e:
        print("Gesichtssperre:", e)


def fremd_wache():
    """Fremden-Sperre (gesicht.py): solange ein fremdes Gesicht erkannt ist, bleibt das ORB-Fenster ganz zu – keine Kugel,
    kein Taskleisten-Eintrag, keine Stimme. Wächter, Telegram und Server laufen unsichtbar weiter.
    Erkennt der Wächter Larsen wieder, kommt ORB zurück: nach einem Weckversuch sichtbar, sonst wie gewohnt im Hintergrund."""
    vorher = False
    while True:
        time.sleep(1)
        try:
            an = server.fremd_gesperrt()
            if an:
                if not vorher:
                    server.log_close("Fremden-Sperre: ORB versteckt")
                    server.BRAIN.kill() if not server.BRAIN.busy else None
                    server.web_schliessen_fenster()
                if window_open() or window_process_running():
                    hide_window()
            elif vorher:
                server.log_close("Fremden-Sperre aufgehoben – Larsen erkannt")
                try:
                    weck = time.time() - os.path.getmtime(os.path.join(server.GESICHT_DIR, "weckversuch")) < 60
                except OSError:
                    weck = False
                if weck:
                    show(wake=True)
                elif server.load_cfg().get("steuerung", "wort") == "wort":
                    show(hidden=True)   # wieder unsichtbar auf „Jarvis“ lauschen
            vorher = an
        except Exception as e:
            print("Fremden-Sperre:", e)


def telegram_start():
    """Telegram-Brücke (telegram_orb.py neben server.py) im ORB-Prozess laufen lassen – nur Standardbibliothek."""
    try:
        import importlib.util
        pfad = os.path.join(os.path.dirname(os.path.abspath(server.__file__)), "telegram_orb.py")
        spec = importlib.util.spec_from_file_location("telegram_orb", pfad)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        os.environ.setdefault("ORB_PORT", str(server.PORT))
        mod.PORT, mod.ORB = server.PORT, "http://127.0.0.1:%d" % server.PORT
        while True:
            try:
                mod.main()
            except Exception as e:
                mod.log("Absturz, Neustart in 10 s:", e)
                time.sleep(10)
    except Exception as e:
        print("Telegram:", e)


def orb_unsichtbar_fuer_aufnahme():
    """Mit „ORB sieht meinen Bildschirm“: ORBs eigenes Fenster aus Bildschirmaufnahmen ausblenden
    (WDA_EXCLUDEFROMCAPTURE) – so sieht ORB, was UNTER ihm liegt, statt sich selbst."""
    u = ctypes.windll.user32
    while True:
        try:
            an = bool(server.load_cfg().get("bildschirm"))
            for h in orb_windows():
                u.SetWindowDisplayAffinity(h, 0x11 if an else 0)
        except Exception:
            pass
        time.sleep(5)


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
    if server.fremd_gesperrt():
        server.weckversuch()   # Fremder will ORB holen → nichts zeigen, Wächter scannt neu (ist es doch Larsen?)
        return
    if server.tarnmodus.aktiv():
        return   # Tarnmodus: Klatschen & Co. holen das Fenster nicht hervor
    if wake:
        server.CALL_FREI[0] = True   # per Klatschen geholt → auch während eines Meetings zuhören
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
    t0 = time.time()
    proc = subprocess.Popen([browser, "--app=" + url, "--user-data-dir=" + profile] + LEAN + extra)
    threading.Thread(target=verdeckt_starten, args=(t0, proc.pid, hidden), daemon=True).start()


def _fenster_der_profilprozesse():
    """Alle sichtbaren Hauptfenster der ORB-Edge-Prozesse (auch bevor die Seite ihren Titel „ORB“ gesetzt hat)."""
    import psutil
    from ctypes import wintypes
    u = ctypes.windll.user32
    pids = {p.pid for p in psutil.process_iter(["name", "cmdline"])
            if (p.info["name"] or "").lower() == "msedge.exe" and any("ORB\\fenster" in (c or "") for c in p.info["cmdline"] or [])}
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(h) and u.GetParent(h) == 0:
            r = (ctypes.c_long * 4)()
            u.GetWindowRect(h, ctypes.byref(r))
            if r[2] - r[0] > 300:
                out.append(h)
        return True
    u.EnumWindows(cb, 0)
    return out


def _fenster_von_pid(pid):
    """Sichtbare Hauptfenster genau dieses Prozesses – sehr schnell (kein Durchsuchen aller Prozesse)."""
    from ctypes import wintypes
    u = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h) and u.GetParent(h) == 0:
            out.append(h)
        return True
    u.EnumWindows(cb, 0)
    return out


def verdeckt_starten(t0, pid=0, verstecken=False):
    """Startbild ohne Flackern: das neue Fenster sofort DURCHSICHTIG schalten (nicht verstecken – so rendert der Browser ganz
    normal weiter und nichts reißt), bis das Dashboard „bereit“ meldet; dann in 0,3 s weich einblenden. Spätestens nach 7 s."""
    u = ctypes.windll.user32
    u.SetWindowLongW.restype = ctypes.c_long
    fenster = {}
    ende = time.time() + 7
    naechste_vollsuche = 0.0
    while time.time() < ende:
        try:
            gefunden = _fenster_von_pid(pid) if pid else []
            if not gefunden and time.time() > naechste_vollsuche:   # Edge hat den Start evtl. an einen anderen Prozess übergeben
                naechste_vollsuche = time.time() + .25
                gefunden = _fenster_der_profilprozesse()
            for h in gefunden:
                if h not in fenster:
                    ex = u.GetWindowLongW(h, -20)
                    u.SetWindowLongW(h, -20, ex | 0x80000)           # WS_EX_LAYERED
                    u.SetLayeredWindowAttributes(h, 0, 0, 2)          # ganz durchsichtig
                    fenster[h] = ex
        except Exception:
            pass
        if fenster and server.FENSTER_BEREIT[0] > t0:
            break
        time.sleep(.004 if not fenster else .02)
    if verstecken:   # Start im Hintergrund: fertig geladen verstecken, dann wieder undurchsichtig (fürs spätere Zeigen)
        if server.load_cfg().get("vollbild", True):   # erst verstecken, wenn Edge wirklich im Vollbild ist
            bis = time.time() + 3
            while time.time() < bis and not all(_ist_vollbild(h) for h in fenster):
                time.sleep(.05)
        for h, ex in fenster.items():
            try:
                u.ShowWindow(h, 0)
                u.SetLayeredWindowAttributes(h, 0, 255, 2)
                u.SetWindowLongW(h, -20, ex & ~0x80000)
            except Exception:
                pass
        return
    for stufe in range(1, 13):   # weich einblenden (~0,3 s)
        for h in fenster:
            try:
                u.SetLayeredWindowAttributes(h, 0, int(255 * stufe / 12), 2)
            except Exception:
                pass
        time.sleep(.025)
    for h, ex in fenster.items():
        try:
            u.SetLayeredWindowAttributes(h, 0, 255, 2)
            u.SetWindowLongW(h, -20, ex & ~0x80000)                 # wieder normales Fenster (volle Leistung)
        except Exception:
            pass
    bring_front()


def spiel_mini_oeffnen():
    """Im Spiel: ORB als kleine Kugel mit Mini-Hologramm unten rechts, immer obenauf – OHNE dem Spiel den Fokus zu klauen."""
    u = ctypes.windll.user32
    spiel_fenster = u.GetForegroundWindow()
    if window_open() or window_process_running():
        hide_window()                       # großes (Vollbild-)Fenster lässt sich nicht verkleinern → zu und klein neu öffnen
        time.sleep(1.2)
    browser = find_browser()
    if not browser:
        return
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    w, h = 360, 600
    x, y = sw - w - 14, sh - h - 56
    profile = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "fenster")
    _win["opened"] = time.time()
    subprocess.Popen([browser, "--app=" + URL + "/#spiel", "--user-data-dir=" + profile, "--window-size=%d,%d" % (w, h),
                      "--window-position=%d,%d" % (x, y)] + LEAN)
    for _ in range(80):                     # Fenster abwarten
        time.sleep(0.1)
        if orb_windows():
            break
    mini_setzen(8)
    if spiel_fenster and spiel_fenster not in orb_windows():   # Fokus zurück ans Spiel
        u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
        u.SetForegroundWindow(spiel_fenster)


def mini_platz():
    u = ctypes.windll.user32
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    w, h = 360, 600
    return sw - w - 14, sh - h - 56, w, h


def mini_setzen(sekunden=3):
    """ORB-Fenster als Mini-Kugel unten rechts festhalten (immer obenauf, ohne zu aktivieren) – mehrmals, weil Edge
    nach dem Laden seine gespeicherte Größe wiederherstellt."""
    u = ctypes.windll.user32
    x, y, w, h = mini_platz()
    ende = time.time() + sekunden
    while time.time() < ende:
        for hw in orb_windows():
            if u.IsZoomed(hw):
                u.ShowWindow(hw, 4)
            u.SetWindowPos(hw, -1, x, y, w, h, 0x10 | 0x40)
        time.sleep(0.3)


def ist_mini(hw):
    u = ctypes.windll.user32
    r = (ctypes.c_long * 4)()
    u.GetWindowRect(hw, ctypes.byref(r))
    return r[2] - r[0] < 500 and r[3] - r[1] < 700


def spiel_wache():
    """Spiel gestartet → ORB wird zur kleinen Kugel mit Mini-Hologramm (Einstellung „spiel_mini“), sonst wie früher ausblenden.
    Spiel beendet → Mini-Fenster zu, ORB wartet wieder im Hintergrund (Klatschen holt ihn groß)."""
    vorher, mini_an = "", False
    while True:
        time.sleep(8)
        try:
            spiel = server.spiel_laeuft()
            if spiel and not vorher and server.load_cfg().get("spiel_mini", True) and time.time() - server.LAST_ACTIVE[0] > 20:
                server.log_close("Gaming-Modus: %s gestartet – Mini-ORB" % spiel)
                spiel_mini_oeffnen()
                mini_an = True
            elif not spiel and vorher and mini_an:
                mini_an = False
                hide_window()
            elif spiel and mini_an and server.load_cfg().get("spiel_mini", True) and time.time() - server.LAST_ACTIVE[0] > 60:
                # Während des Spiels groß geworden (Klatschen, Neustart, Update) und 1 Min. nicht benutzt → zurück zur Mini-Kugel
                u = ctypes.windll.user32
                for hw in orb_windows():
                    if not u.IsWindowVisible(hw) or ist_mini(hw):
                        continue
                    mini_setzen(2)
                    if not ist_mini(hw) and time.time() - _win.get("spiel_neu", 0) > 120:   # Vollbild lässt sich nicht verkleinern
                        _win["spiel_neu"] = time.time()
                        server.log_close("Gaming-Modus: Vollbild → Mini-Kugel neu geöffnet")
                        spiel_mini_oeffnen()
                    break
            elif spiel and not vorher and window_open() and time.time() - server.LAST_ACTIVE[0] > 20:
                server.log_close("Gaming-Modus: %s gestartet" % spiel)
                if spiel == "Minecraft":
                    hide_window(keep=True)   # nur ausblenden: ORB hört weiter auf „Jarvis“ und steuert das Spiel
                else:
                    server.BRAIN.kill() if not server.BRAIN.busy else None
                    hide_window()
            vorher = spiel
        except Exception as e:
            print("Spiel-Wache:", e)


def hide_window(keep=False):
    """ORB-Fenster schließen (spart ~800 MB) – im Hintergrund wird weiter auf Klatschen gelauscht.
    keep=True: nur ausblenden – die Seite läuft weiter und hört auf „Jarvis“, Klatschen und Schnipsen."""
    server.CALL_FREI[0] = False
    if keep:
        try:
            hs = orb_windows()
            if any(ctypes.windll.user32.IsWindowVisible(h) for h in hs):
                # erst die Seite die Intro-Abdeckung malen lassen, dann verstecken – sonst zeigt Windows beim Holen kurz das alte Bild
                t = time.time()
                server.write_state(abdecken=t)
                ende = t + 1.2
                while time.time() < ende and server.ABGEDECKT[0] < t:
                    time.sleep(.02)
            for h in hs:
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
        self.kalib = None   # Messwerte aus „Mikro kalibrieren“ (nur für das kalibrierte Mikrofon)

    def rausch(self):
        return {"floor": self.floor, "npk": self.npk, "nhf": self.nhf, "nprof": self.nprof}

    def schwellen(self):
        """(Spitze, Pegel) für einen Klatscher – nie unter den alten Werten im stillen Raum, im Rauschen relativ."""
        f, tb = self.floor, self.thr_base
        kp = float((self.kalib or {}).get("klatschPk") or 0)
        if kp > 0:   # kalibriert: ~30 % der gemessenen Klatsch-Spitze (Empfindlichkeit/Musik skalieren), sicher über den Rausch-Spitzen
            return max(self.npk * 3, f * 8, kp * .3 * tb / .003), max(f * 4, min(f * 10, .003))
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
                vor = getattr(self, "cand_pre", 0.0)
                abgeklungen = rms < max(c[1] * .35, f * 1.7, min(vor * 1.3, c[1] * .5)) or pk * 6 < c[2]   # Spitze ist weg, nur noch Sprache
                if abgeklungen and maus_ok:   # abgeklungen (auf Rauschen bzw. Meet-Sprache)
                    self.last = c[0]
                    self.claps = [t for t in self.claps if self.last - t < 1.1] + [self.last]
                    self.pks = (self.pks + [c[2]])[-2:]
                    p = self.pks
                    gleich = len(p) < 2 or (p[0] / p[1] < 3 and p[1] / p[0] < 3)   # zwei ähnlich laute Klatscher
                    if len(self.claps) >= 2 and .22 < self.claps[-1] - self.claps[-2] < 1.0 and gleich:
                        self.claps = []
                        treffer = True
                        try:
                            server.log_close("Doppelklatschen im Hintergrund erkannt", server.HOER_LOG)
                        except Exception:
                            pass
                elif not self.pks or c[2] >= self.pks[-1] * .5:
                    self.claps = []   # lautes Dauergeräusch statt Knall (leise Silben-Anfänge im Meet löschen den ersten Klatscher nicht)
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
                # Vorher-Geräusch (Sprache im Meet, Musik): Knall zählt trotzdem, wenn er klar lauter ist
                laut_genug = ex_pre < ex_rms * .3 or (rms > pre * 3.5 and pk > thr_pk * 1.5)
                sr_ = snap_ratio(x, self.sr, self.nprof)
                if hf < 2.6 and pk / rms < 18 and laut_genug and maus_ok and sr_ < 1.4:
                    self.cand = (now, rms, pk, [])
                    self.cand_pre = pre
                elif now - getattr(self, "_log_t", 0) > 2:
                    self._log_t = now
                    warum = ("Maus/Tastatur" if not maus_ok else "zu hell (Klick/Schnipser)" if hf >= 2.6 or sr_ >= 1.4
                             else "zu spitz" if pk / rms >= 18 else "vorher zu laut (Sprache/Musik)")
                    try:
                        server.log_close("Klatschen im Hintergrund? nein: %s · Spitze %.3f · vorher %.4f · jetzt %.4f"
                                         % (warum, pk, pre, rms), server.HOER_LOG)
                    except Exception:
                        pass
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


def mikro_geraet(sd, wahl):
    """Index des gewählten Mikrofons (z. B. „TONOR“) – None = Windows-Standard."""
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and d["hostapi"] == 0 and server.mikro_passt(wahl, d["name"]):
                return i
    except Exception:
        pass
    return None


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
    mikro = None
    while True:
        if window_open():   # Klatschen ist nie abschaltbar
            time.sleep(1)
            continue
        wahl = str(server.load_cfg().get("mikro") or "")
        if wahl != mikro:
            mikro, _RAUSCH = wahl, None   # anderes Mikro: Grundrauschen neu messen
        k, cfg_t = KlatschErkenner(sr, _RAUSCH), 0.0
        try:
            with sd.RawInputStream(samplerate=sr, channels=1, dtype="int16", blocksize=block, device=mikro_geraet(sd, wahl)) as st:
                while not window_open():
                    raw, _ = st.read(block)
                    if server.spiel_laeuft():
                        continue   # Gaming-Modus: Schüsse/Explosionen sind keine Klatscher
                    x = array.array("h", bytes(raw))
                    now = time.time()
                    if now - cfg_t > 3:
                        cfg_t = now
                        if k.n >= k.KAL:
                            _RAUSCH = k.rausch()
                        c = server.load_cfg()
                        if str(c.get("mikro") or "") != mikro:
                            break   # Mikro gewechselt → mit dem neuen weiterlauschen
                        kal = c.get("kalib") or {}
                        k.kalib = kal if kal.get("klatschPk") and server.mikro_passt(mikro, kal.get("mikro")) else None
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
            try:   # Mikro ab-/angesteckt: Geräteliste neu einlesen
                sd._terminate()
                sd._initialize()
            except Exception:
                pass
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
                neu = ""
                try:   # neu.txt kommt mit dem Update: "<Version>|<was ist neu>"
                    with open(os.path.join(os.path.dirname(os.path.abspath(server.__file__)), "neu.txt"), encoding="utf-8") as f:
                        v, _, txt = f.read().strip().partition("|")
                    if v.strip() == str(server.VERSION) and txt.strip():
                        neu = txt.strip().rstrip(".")
                except Exception:
                    pass
                server.write_answer("Update installiert, Version %s.%s" % (server.VERSION, (" Neu: " + neu + ".") if neu else ""), heard="")


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
    server.tarnmodus.aufraeumen()   # Benachrichtigungen wieder an, falls ORB mitten im Tarnmodus beendet wurde
    server.ON_SHOW[0] = show
    server.ON_HIDE[0] = hide_window
    server.ON_MINI[0] = mini
    server.ON_UPDATE[0] = apply_update
    if hasattr(sys.modules.get("__main__"), "local_sha"):
        server.ON_CHECK[0] = check_update
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = server.load_cfg()
    server.set_autostart(bool(cfg.get("autostart", True)))
    threading.Thread(target=server.mikro_standard, daemon=True).start()   # gewähltes Mikro (TONOR) = Windows-Standard
    threading.Thread(target=clap_loop, daemon=True).start()
    # Gaming-Modus (Mini-Kugel im Spiel) entfernt – spiel_wache läuft nicht mehr
    threading.Thread(target=server.chroma_loop, daemon=True).start()   # Razer-Licht
    threading.Thread(target=server.pc_wache, daemon=True).start()      # warnt bei vollem RAM/Platte, heißer GPU
    threading.Thread(target=server.musik_logger, daemon=True).start()  # Musikgeschmack für den Spotify-DJ
    threading.Thread(target=ohr_wache, daemon=True).start()            # lokales Ohr: „Hey Jarvis“ + Whisper
    threading.Thread(target=stimme_wache, daemon=True).start()         # lokale KI-Stimme (Chatterbox)
    threading.Thread(target=server.live_bildschirm, daemon=True).start()  # Bildschirm in Echtzeit
    threading.Thread(target=telegram_start, daemon=True).start()
    threading.Thread(target=fremd_wache, daemon=True).start()          # fremdes Gesicht → ORB unsichtbar und stumm
    threading.Thread(target=gesicht_beim_start, daemon=True).start()   # Gesichtssperre (nur direkt nach dem PC-Start)          # ORB per Telegram vom Handy
    threading.Thread(target=orb_unsichtbar_fuer_aufnahme, daemon=True).start()
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
