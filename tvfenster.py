"""Dein TradingView-Konto im ORB-Dashboard: rahmenloses WebView2-Fenster, das exakt über der Chart-Karte liegt.

Läuft als eigener Prozess (von ORB gestartet, `pyw -3 tvfenster.py`). Liest laufend %LOCALAPPDATA%\\ORB\\tv_lage.json
({"an": bool, "x","y","w","h" in Bildschirm-Punkten, "t": Zeit}) und schiebt/zeigt/versteckt das Fenster danach.
Login bleibt gespeichert (%LOCALAPPDATA%\\ORB\\tv_webview). Beendet sich, wenn ORB 2 Min. nichts mehr schreibt.
"""
import ctypes
import json
import os
import threading
import time

import webview

BASIS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB")
LAGE = os.path.join(BASIS, "tv_lage.json")
URL = "https://www.tradingview.com/chart/?symbol=VANTAGE%3AXAUUSD"
u = ctypes.windll.user32


def orb_fenster():
    gef = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        b = ctypes.create_unicode_buffer(16)
        u.GetWindowTextW(h, b, 16)
        if b.value == "ORB" and u.IsWindowVisible(h):
            gef.append(h)
        return True
    u.EnumWindows(cb, 0)
    return gef[0] if gef else None


def steuern(win):
    skala = (u.GetDpiForSystem() or 96) / 96.0
    alt, sichtbar, besitzer = None, False, None
    hwnd = None
    while True:
        time.sleep(0.12)
        try:
            with open(LAGE, encoding="utf-8") as f:
                L = json.load(f)
        except Exception:
            continue
        if time.time() - L.get("t", 0) > 120:   # ORB meldet sich nicht mehr → beenden
            win.destroy()
            return
        if hwnd is None:
            try:
                hwnd = int(win.native.Handle.ToInt64())
            except Exception:
                hwnd = None
        o = orb_fenster()
        an = bool(L.get("an")) and o is not None and not u.IsIconic(o)   # ORB weg/minimiert → TradingView auch weg
        if an:
            k = (L["x"], L["y"], L["w"], L["h"])
            if k != alt:
                alt = k
                # WebView2-Fenster ist DPI-bewusst → echte Pixel
                win.move(int(L["x"] * skala), int(L["y"] * skala))
                win.resize(int(L["w"] * skala), int(L["h"] * skala))
            if hwnd:
                if o and o != besitzer:   # dem ORB-Fenster unterordnen: liegt darüber, minimiert mit ihm
                    u.SetWindowLongPtrW(ctypes.c_void_p(hwnd), -8, ctypes.c_void_p(o))
                    besitzer = o
            if not sichtbar:
                win.show()
                sichtbar = True
        elif sichtbar:
            win.hide()
            sichtbar = False


if __name__ == "__main__":
    os.makedirs(os.path.join(BASIS, "tv_webview"), exist_ok=True)
    w = webview.create_window("ORB TradingView", URL, frameless=True, easy_drag=False, hidden=True,
                              width=900, height=600, background_color="#0f0f12")
    webview.start(lambda: threading.Thread(target=steuern, args=(w,), daemon=True).start(),
                  private_mode=False, storage_path=os.path.join(BASIS, "tv_webview"))
