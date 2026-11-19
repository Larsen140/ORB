"""Gesichtssperre für ORB: erkennt Larsen per Webcam (OpenCV YuNet + SFace, komplett lokal).

  py -3 gesicht.py lernen      → ~8 s in die Kamera schauen: Profil von Larsens Gesicht anlegen
  py -3 gesicht.py pruefen     → einmal scannen; gibt JSON {"ergebnis": "larsen"|"fremd"|"kein_gesicht", "wert": …} aus
  py -3 gesicht.py waechter    → beim PC-Start: alle ~3 s scannen, bis ein Gesicht zu sehen ist; ist es nicht Larsen, private Apps (WhatsApp, Instagram, Snapchat)
                                  sperren und ORB selbst unsichtbar/stumm/nicht aufrufbar machen, bis Larsen erkannt wird
                                  (neuer Scan bei jedem Öffnungs- oder Weckversuch). Meldet Fremde per Telegram.
Dateien in %LOCALAPPDATA%\\ORB\\gesicht: Modelle, profil.npy, letzter_fremder.jpg, gesicht.log, sperre.json, weckversuch.
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


def ansagen(text):
    """ORB sagt es laut (und zeigt es im Chat) – für das geführte Lernen."""
    import urllib.request
    try:
        tok = open(os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "token.txt")).read().strip()
        req = urllib.request.Request("http://127.0.0.1:8766/announce", data=json.dumps({"text": text}).encode(),
                                     headers={"X-ORB-Token": tok, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    print(text, flush=True)


def lernen():
    """Geführt: vorne, links, rechts – je Richtung mehrere Bilder. Gespeichert werden alle Merkmale (Profil = mehrere Ansichten)."""
    det, rec = modelle()
    alle = []
    for richtung, satz in (("vorne", "Schau bitte gerade in die Kamera."), ("links", "Jetzt den Kopf leicht nach links drehen."),
                           ("rechts", "Und jetzt leicht nach rechts.")):
        ansagen(satz)
        time.sleep(2.2)   # Ansage abwarten
        m, _ = gesichter(4, det, rec, anzahl=12)
        log("Lernen", richtung, len(m), "Bilder")
        alle += m
    if len(alle) < 10:
        ansagen("Das hat nicht geklappt, ich habe dein Gesicht zu selten gesehen. Mehr Licht und etwas näher ran, dann nochmal.")
        print(json.dumps({"ok": False, "bilder": len(alle)}))
        return
    np.save(PROFIL, np.array([x.ravel() for x in alle]))
    ansagen("Fertig, ich kenne dein Gesicht jetzt von vorne, links und rechts.")
    log("Profil gelernt aus", len(alle), "Bildern (vorne/links/rechts)")
    print(json.dumps({"ok": True, "bilder": len(alle)}))


def pruefen(sekunden=6):
    if not os.path.exists(PROFIL):
        return {"ergebnis": "kein_profil"}
    det, rec = modelle()
    profil = np.load(PROFIL)
    m, bild = gesichter(sekunden, det, rec, anzahl=5)
    if not m:
        return {"ergebnis": "kein_gesicht"}
    P = profil.reshape(-1, profil.shape[-1])   # eine oder mehrere gespeicherte Ansichten
    wert = float(max(float(np.max(P @ x.ravel())) for x in m))
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


SPERRE = os.path.join(BASIS, "sperre.json")
WECK = os.path.join(BASIS, "weckversuch")


def sperre_setzen(an):
    """Fremden-Sperre für ORB selbst: solange sperre.json mit der PID dieses Wächters existiert, bleibt ORB unsichtbar,
    stumm und nicht aufrufbar (server.fremd_gesperrt). Stirbt der Wächter, gilt die Sperre automatisch nicht mehr."""
    try:
        if an:
            with open(SPERRE, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "seit": time.time()}, f)
        elif os.path.exists(SPERRE):
            os.remove(SPERRE)
    except Exception as e:
        log("Sperre-Datei:", e)


def weck_zeit():
    try:
        return os.path.getmtime(WECK)
    except OSError:
        return 0.0


def waechter():
    """Beim PC-Start: alles gesperrt lassen und alle paar Sekunden scannen, bis wirklich ein Gesicht zu sehen ist.
    Larsen → Sperre weg, fertig. Fremder → gesperrt lassen, Foto per Telegram, danach Neu-Scan bei Öffnungsversuchen.
    Komplett unsichtbar: nichts auf dem Bildschirm."""
    if not os.path.exists(PROFIL):
        sperre_setzen(False)
        return
    sperre_setzen(True)   # von Anfang an: ORB versteckt und stumm, bis Larsen erkannt ist
    try:
        time.sleep(8)   # Windows und Kamera hochfahren lassen
        fremd_gemeldet = False
        letzter_scan, weck_gesehen = 0.0, weck_zeit()
        while True:
            f = private_fenster()
            if f:
                sperren(f)
            weck = weck_zeit() > weck_gesehen   # jemand wollte ORB holen (Klatschen, „Jarvis“, ORB.exe)
            if not fremd_gemeldet:
                # noch kein Gesicht gesehen → ständig weiterscannen (alle ~3 s)
                faellig = time.time() - letzter_scan > 3
            else:
                # Fremder erkannt → nur bei Öffnungsversuch neu scannen (bei ORB-Weckversuch alle 5 s, sonst alle 20 s)
                faellig = (f or weck) and time.time() - letzter_scan > (5 if weck else 20)
            if not faellig:
                time.sleep(1)
                continue
            weck_gesehen = weck_zeit()
            r = pruefen(4)
            letzter_scan = time.time()
            log("Scan (%s):" % ("Start" if not fremd_gemeldet else "ORB" if weck else "App"), r)
            if r["ergebnis"] in ("larsen", "kein_profil"):
                log("Larsen erkannt – Sperre aufgehoben")
                return
            if r["ergebnis"] == "fremd":
                bild = os.path.join(BASIS, "letzter_fremder.jpg")
                if not fremd_gemeldet:
                    fremd_gemeldet = True
                    telegram("⚠️ ORB: Am PC sitzt jemand, der nicht du bist – ORB und private Apps sind gesperrt.", bild)
                elif f or weck:
                    was = f[0][3][:40] if f else "ORB"
                    telegram("⚠️ ORB: Jemand wollte %s öffnen – gesperrt." % was, bild)
    finally:
        sperre_setzen(False)   # ORB wieder sichtbar und bedienbar

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
