"""Tarnmodus: der PC wirkt ausgeschaltet, alles läuft im Hintergrund weiter (Meetings, Downloads, ORB, Telegram).
Schwarze Fläche über allen Bildschirmen (ohne Mauszeiger), Monitore aus, Windows-Benachrichtigungen stumm,
Ruhezustand gesperrt. Es wird nichts beendet. Taste oder Mausbewegung am PC beendet den Modus (nach 3 s Schonfrist).
Das Razer-Licht und ORBs Stimme/Klänge schaltet server.py dunkel bzw. stumm."""
import ctypes
import ctypes.wintypes as W
import json
import os
import threading
import time

HOME = os.path.join(os.path.expanduser("~"), "Orb")
RESTE = os.path.join(HOME, "tarnmodus.json")   # alte Benachrichtigungs-Werte, falls ORB mitten im Tarnmodus abstürzt
NOTI_KEY = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
NOTI_WERTE = ("NOC_GLOBAL_SETTING_TOASTS_ENABLED", "NOC_GLOBAL_SETTING_ALLOW_NOTIFICATION_SOUND")
SCHONFRIST = 3.0   # so lange nach dem Start zählt keine Eingabe (z. B. Enter nach „Tarnmodus an“)

_z = {"thread": None, "hwnd": None, "ende": None, "grund": "", "stop": False}
_lock = threading.Lock()
_klasse = {"ok": False, "proc": None}

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
u32.DefWindowProcW.argtypes = (W.HWND, W.UINT, W.WPARAM, W.LPARAM)
u32.DefWindowProcW.restype = LRESULT
u32.CreateWindowExW.argtypes = (W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID)
u32.CreateWindowExW.restype = W.HWND
u32.PostMessageW.argtypes = (W.HWND, W.UINT, W.WPARAM, W.LPARAM)
u32.SetWindowPos.argtypes = (W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT)
u32.SetForegroundWindow.argtypes = (W.HWND,)
u32.GetForegroundWindow.restype = W.HWND
u32.SetCursor.argtypes = (W.HANDLE,)
u32.DestroyWindow.argtypes = (W.HWND,)
u32.IsWindow.argtypes = (W.HWND,)
k32.SetThreadExecutionState.argtypes = (W.DWORD,)
k32.SetThreadExecutionState.restype = W.DWORD


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", W.HINSTANCE), ("hIcon", W.HICON), ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH),
                ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.UINT), ("dwTime", W.DWORD)]


WM_DESTROY, WM_CLOSE, WM_SETCURSOR, WM_SYSCOMMAND = 0x0002, 0x0010, 0x0020, 0x0112
SC_MONITORPOWER = 0xF170


def _wndproc(h, msg, wp, lp):
    if msg == WM_SETCURSOR:
        u32.SetCursor(None)   # kein Mauszeiger auf der schwarzen Fläche
        return 1
    if msg == WM_CLOSE:
        u32.DestroyWindow(h)
        return 0
    if msg == WM_DESTROY:
        u32.PostQuitMessage(0)
        return 0
    return u32.DefWindowProcW(h, msg, wp, lp)


def _klasse_anmelden():
    if _klasse["ok"]:
        return
    _klasse["proc"] = WNDPROC(_wndproc)   # Referenz halten, sonst räumt Python den Rückruf weg
    wc = WNDCLASSW()
    wc.lpfnWndProc = _klasse["proc"]
    wc.hInstance = k32.GetModuleHandleW(None)
    wc.hbrBackground = ctypes.windll.gdi32.GetStockObject(4)   # BLACK_BRUSH
    wc.lpszClassName = "ORBTarnmodus"
    u32.RegisterClassW(ctypes.byref(wc))
    _klasse["ok"] = True


def _letzte_eingabe():
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    u32.GetLastInputInfo(ctypes.byref(li))
    return li.dwTime


def _monitor(an):
    h = _z["hwnd"]
    if h:
        u32.PostMessageW(h, WM_SYSCOMMAND, SC_MONITORPOWER, -1 if an else 2)


def _wecken():
    """Monitore nach dem Ende sicher wieder an (winzige Mausbewegung hin und zurück)."""
    u32.mouse_event(1, 0, 1, 0, 0)
    u32.mouse_event(1, 0, -1, 0, 0)


# ---------- Windows-Benachrichtigungen stumm ----------
def _noti_setzen(werte):
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, NOTI_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
        for name, wert in werte.items():
            if wert is None:
                try:
                    winreg.DeleteValue(k, name)
                except OSError:
                    pass
            else:
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(wert))


def _noti_aus():
    import winreg
    alt = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NOTI_KEY) as k:
            for name in NOTI_WERTE:
                try:
                    alt[name] = winreg.QueryValueEx(k, name)[0]
                except OSError:
                    alt[name] = None
    except OSError:
        alt = {n: None for n in NOTI_WERTE}
    try:
        os.makedirs(HOME, exist_ok=True)
        with open(RESTE, "w", encoding="utf-8") as f:
            json.dump(alt, f)
        _noti_setzen({n: 0 for n in NOTI_WERTE})
    except Exception as e:
        print("Tarnmodus Benachrichtigungen:", e)


def aufraeumen():
    """Benachrichtigungen wieder wie vorher (auch nach einem Absturz mitten im Tarnmodus beim nächsten Start)."""
    try:
        with open(RESTE, encoding="utf-8") as f:
            alt = json.load(f)
    except (OSError, ValueError):
        return
    try:
        _noti_setzen(alt)
        os.remove(RESTE)
    except Exception as e:
        print("Tarnmodus aufräumen:", e)


# ---------- Schwarze Fläche ----------
def _lauf():
    try:
        u32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # echte Pixel, damit alle Monitore ganz bedeckt sind
    except Exception:
        pass
    vorher = u32.GetForegroundWindow()
    k32.SetThreadExecutionState(0x80000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: kein Ruhezustand, Downloads laufen weiter
    _klasse_anmelden()
    x, y = u32.GetSystemMetrics(76), u32.GetSystemMetrics(77)   # ganzer virtueller Bildschirm (alle Monitore)
    w, h = u32.GetSystemMetrics(78), u32.GetSystemMetrics(79)
    hwnd = u32.CreateWindowExW(0x00000008 | 0x00000080, "ORBTarnmodus", "ORB Tarnmodus",   # TOPMOST | TOOLWINDOW
                               0x80000000 | 0x10000000, x, y, w, h, None, None, k32.GetModuleHandleW(None), None)
    _z["hwnd"] = hwnd
    u32.keybd_event(0x12, 0, 0, 0)   # Alt-Trick: Windows erlaubt sonst kein Nach-vorne-Holen
    u32.keybd_event(0x12, 0, 2, 0)
    u32.SetForegroundWindow(hwnd)   # Tasten zum Aufwecken landen hier, nicht im Meeting
    start = time.time()
    basis, aus_t, oben_t = None, 0.0, 0.0
    msg = W.MSG()
    try:
        while True:
            while u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == 0x0012:   # WM_QUIT
                    return
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
            jetzt = time.time()
            if _z["stop"]:
                return
            if basis is None:
                if jetzt - start >= SCHONFRIST:
                    basis = _letzte_eingabe()
            elif _letzte_eingabe() != basis:
                _z["grund"] = "pc"   # Larsen ist am PC: Taste oder Maus
                u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            if jetzt - start > 1.0 and jetzt - aus_t > 60:   # Monitore aus (alle 60 s nachlegen, falls etwas sie weckt)
                aus_t = jetzt
                _monitor(False)
            if jetzt - oben_t > 2:   # ganz oben bleiben
                oben_t = jetzt
                u32.SetWindowPos(hwnd, W.HWND(-1), x, y, w, h, 0x0010)   # HWND_TOPMOST, SWP_NOACTIVATE
            time.sleep(0.05)
    finally:
        _z["hwnd"] = None
        if u32.IsWindow(hwnd):
            u32.DestroyWindow(hwnd)
        k32.SetThreadExecutionState(0x80000000)
        _wecken()
        if vorher:
            u32.SetForegroundWindow(vorher)
        aufraeumen()
        ende, grund = _z["ende"], _z["grund"] or "befehl"
        _z.update(thread=None, ende=None, grund="", stop=False)
        if ende:
            try:
                ende(grund)
            except Exception as e:
                print("Tarnmodus Ende:", e)


def aktiv():
    t = _z["thread"]
    return bool(t and t.is_alive())


def starten(bei_ende=None):
    """Tarnmodus einschalten. bei_ende(grund) wird beim Ende aufgerufen („pc“ = Larsen hat Taste/Maus benutzt)."""
    with _lock:
        if aktiv():
            return False
        _noti_aus()
        _z.update(ende=bei_ende, grund="", stop=False)
        _z["thread"] = threading.Thread(target=_lauf, daemon=True, name="Tarnmodus")
        _z["thread"].start()
        return True


def beenden():
    with _lock:
        if not aktiv():
            return False
        _z.update(grund="befehl", stop=True)   # die Schleife räumt selbst auf (Fenster gehört ihrem Thread)
        return True
