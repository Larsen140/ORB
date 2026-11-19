"""Gesichtssperre für ORB: erkennt Larsen per Webcam (OpenCV YuNet + SFace, komplett lokal).

  py -3 gesicht.py lernen      → ~8 s in die Kamera schauen: Profil von Larsens Gesicht anlegen
  py -3 gesicht.py pruefen     → einmal scannen; gibt JSON {"ergebnis": "larsen"|"fremd"|"kein_gesicht", "wert": …} aus
  py -3 gesicht.py waechter    → beim PC-Start: scannen; ist es nicht Larsen, private Apps (WhatsApp, Instagram, Snapchat)
                                  sperren, bis Larsen erkannt wird (neuer Scan bei jedem Öffnungsversuch). Meldet Fremde per Telegram.
Dateien in %LOCALAPPDATA%\\ORB\\gesicht: Modelle, profil.npy, letzter_fremder.jpg, gesicht.log.
"""
import ctypes
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

BASIS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "gesicht")
PROFIL = os.path.join(BASIS, "profil.npy")
LOG = os.path.join(BASIS, "gesicht.log")
SCHWELLE = 0.42          # Kosinus-Ähnlichkeit (SFace empfiehlt 0,363) – etwas strenger, damit Fremde sicher nicht durchkommen
PRIVAT_APPS = ("whatsapp.exe", "whatsapp.root.exe", "instagram.exe", "snapchat.exe")
PRIVAT_TITEL = ("whatsapp", "instagram", "snapchat")
BROWSER = ("opera.exe", "msedge.exe", "chrome.exe", "firefox.exe", "brave.exe")
u = ctypes.windll.user32


def log(*x):
    os.makedirs(BASIS, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + " ".join(str(v) for v in x) + "\n")


def modelle():
    det = cv2.FaceDetectorYN.create(os.path.join(BASIS, "yunet.onnx"), "", (320, 240), 0.8, 0.3, 5000)
    rec = cv2.FaceRecognizerSF.create(os.path.join(BASIS, "sface.onnx"), "")
    return det, rec


def kamera():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return cap


def gesichter(sekunden, det, rec, anzahl=12):
    """Bis zu `anzahl` Gesichts-Merkmale sammeln (größtes Gesicht je Bild). Gibt (Liste, letztes Bild) zurück."""
    cap = kamera()
    merkmale, bild, ende = [], None, time.time() + sekunden
    try:
        while time.time() < ende and len(merkmale) < anzahl:
            ok, fr = cap.read()
            if not ok:
                time.sleep(.1)
                continue
            bild = fr
            h, w = fr.shape[:2]
            det.setInputSize((w, h))
            _, faces = det.detect(fr)
            if faces is None or not len(faces):
                continue
            f = max(faces, key=lambda z: z[2] * z[3])
            if f[2] < 60:   # zu klein/weit weg
                continue
            m = rec.feature(rec.alignCrop(fr, f))
            merkmale.append(m / np.linalg.norm(m))
    finally:
        cap.release()
    return merkmale, bild


def lernen():
    det, rec = modelle()
    print("Bitte ca. 8 Sekunden in die Kamera schauen, Kopf leicht bewegen …", flush=True)
    m, _ = gesichter(10, det, rec, anzahl=30)
    if len(m) < 8:
        print(json.dumps({"ok": False, "fehler": "zu wenig Gesichtsbilder (%d) – mehr Licht, näher ran" % len(m)}))
        return
    p = np.mean(m, axis=0)
    np.save(PROFIL, p / np.linalg.norm(p))
    log("Profil gelernt aus", len(m), "Bildern")
    print(json.dumps({"ok": True, "bilder": len(m)}))


def pruefen(sekunden=6):
    if not os.path.exists(PROFIL):
        return {"ergebnis": "kein_profil"}
    det, rec = modelle()
    profil = np.load(PROFIL)
    m, bild = gesichter(sekunden, det, rec, anzahl=5)
    if not m:
        return {"ergebnis": "kein_gesicht"}
    wert = float(max(float(np.dot(x.ravel(), profil.ravel())) for x in m))
    if wert >= SCHWELLE:
        return {"ergebnis": "larsen", "wert": round(wert, 3)}
    if bild is not None:
        cv2.imwrite(os.path.join(BASIS, "letzter_fremder.jpg"), bild)
    return {"ergebnis": "fremd", "wert": round(wert, 3)}


def telegram(text, bild=None):
    """Larsen per Telegram Bescheid geben (falls die ORB-Telegram-Brücke eingerichtet ist)."""
    skript = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_orb.py")
    try:
        if bild and os.path.exists(bild):
            subprocess.run([sys.executable, skript, "senden", bild, text], timeout=60, capture_output=True)
    except Exception as e:
        log("Telegram:", e)


def private_fenster():
    """(hwnd, pid, exe, titel) aller sichtbaren Fenster mit WhatsApp/Instagram/Snapchat."""
    import psutil
    from ctypes import wintypes
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if not u.IsWindowVisible(h):
            return True
        n = u.GetWindowTextLengthW(h)
        if not n:
            return True
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        t = b.value.lower()
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        try:
            exe = psutil.Process(pid.value).name().lower()
        except Exception:
            exe = ""
        if exe in PRIVAT_APPS or (exe in BROWSER and any(k in t for k in PRIVAT_TITEL)) or \
                (exe == "applicationframehost.exe" and any(k in t for k in PRIVAT_TITEL)):
            out.append((h, pid.value, exe, b.value))
        return True
    u.EnumWindows(cb, 0)
    return out


def sperren(fenster):
    """App-Fenster: Programm beenden. Browser-Tab: Tab nach vorne holen und mit Strg+W schließen."""
    import psutil
    for h, pid, exe, titel in fenster:
        try:
            if exe in BROWSER:
                u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
                u.SetForegroundWindow(h)
                time.sleep(.25)
                if u.GetForegroundWindow() == h:
                    u.keybd_event(0x11, 0, 0, 0); u.keybd_event(0x57, 0, 0, 0)   # Strg+W
                    u.keybd_event(0x57, 0, 2, 0); u.keybd_event(0x11, 0, 2, 0)
            elif exe == "applicationframehost.exe":
                u.PostMessageW(h, 0x0010, 0, 0)   # WM_CLOSE (Store-App)
            else:
                psutil.Process(pid).kill()
            log("gesperrt:", exe, titel[:60])
        except Exception as e:
            log("sperren fehlgeschlagen:", exe, e)
    # bewusst KEIN Hinweis auf dem Bildschirm: der Wächter bleibt unsichtbar (Larsen erfährt es per Telegram)


def waechter():
    time.sleep(8)   # Windows und Kamera hochfahren lassen
    r = pruefen(8)
    log("Start-Scan:", r)
    if r["ergebnis"] in ("larsen", "kein_profil"):
        return
    if r["ergebnis"] == "fremd":
        telegram("⚠️ ORB: Am PC sitzt jemand, der nicht du bist – private Apps sind gesperrt.", os.path.join(BASIS, "letzter_fremder.jpg"))
    gesperrt, letzter_scan = True, 0.0
    while gesperrt:
        time.sleep(1)
        f = private_fenster()
        if not f:
            continue
        if time.time() - letzter_scan > 20:   # jemand öffnet eine private App → nochmal scannen: ist es jetzt Larsen?
            letzter_scan = time.time()
            r = pruefen(4)
            log("Scan bei Öffnungsversuch:", r)
            if r["ergebnis"] == "larsen":
                log("Larsen erkannt – Sperre aufgehoben")
                return
            if r["ergebnis"] == "fremd":
                telegram("⚠️ ORB: Jemand wollte %s öffnen – gesperrt." % f[0][3][:40], os.path.join(BASIS, "letzter_fremder.jpg"))
        sperren(f)


if __name__ == "__main__":
    was = sys.argv[1] if len(sys.argv) > 1 else "pruefen"
    if was == "lernen":
        lernen()
    elif was == "waechter":
        try:
            waechter()
        except Exception as e:
            log("Wächter-Fehler:", e)
    else:
        print(json.dumps(pruefen()))
