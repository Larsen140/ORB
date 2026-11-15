"""ORBs Ohr: lokale Spracherkennung (Whisper auf der Grafikkarte) + Aktivierungswort „Hey Jarvis“ – ohne Internet.

Läuft als eigener Prozess (venv in %LOCALAPPDATA%\\ORB\\ohr\\venv), von ORB gestartet. Fragt ORB, ob gerade mitgeschrieben
werden soll (Fenster wach) – sonst lauscht es nur auf das Aktivierungswort (braucht kaum Leistung) und weckt ORB auch bei
geschlossenem Fenster. Erkanntes geht an  POST /ohr  {typ: "wake"|"text", text}.
"""
import json
import os
import queue
import sys
import threading
import time
import urllib.request

import numpy as np
import sounddevice as sd

BASIS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB")
PORT = int(os.environ.get("ORB_PORT", "8766"))
URL = "http://127.0.0.1:%d" % PORT
SR, BLOCK = 16000, 1280                    # 80 ms – Blockgröße von openWakeWord
MODELL = os.environ.get("ORB_WHISPER", "large-v3-turbo")
LOG = os.path.join(BASIS, "ohr.log")


def log(*x):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + " ".join(str(v) for v in x) + "\n")
    except Exception:
        pass


def token():
    try:
        with open(os.path.join(BASIS, "token.txt" if PORT == 8766 else "token_%d.txt" % PORT)) as f:
            return f.read().strip()
    except Exception:
        return ""


def orb(pfad, daten=None):
    try:
        req = urllib.request.Request(URL + pfad, data=json.dumps(daten).encode() if daten is not None else None,
                                     method="POST" if daten is not None else "GET",
                                     headers={"X-ORB-Token": token(), "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception:
        return None


class Whisper:
    """Lädt das Modell erst bei Bedarf und gibt die Grafikkarte nach 10 Min. Ruhe wieder frei."""

    def __init__(self):
        self.m, self.zuletzt, self.lock = None, 0.0, threading.Lock()

    def laden(self):
        with self.lock:
            if self.m is None:
                from faster_whisper import WhisperModel
                try:
                    self.m = WhisperModel(MODELL, device="cuda", compute_type="float16")
                except Exception as e:
                    log("CUDA nicht möglich, nutze CPU:", e)
                    self.m = WhisperModel("small", device="cpu", compute_type="int8")
                log("Whisper geladen:", MODELL)
            self.zuletzt = time.time()

    def frei(self):
        with self.lock:
            if self.m is not None and time.time() - self.zuletzt > 600:
                self.m = None
                import gc
                gc.collect()
                log("Whisper entladen (Ruhe)")

    def text(self, audio):
        self.laden()
        segs, _ = self.m.transcribe(audio, language="de", beam_size=1, vad_filter=True, condition_on_previous_text=False,
                                    initial_prompt="Jarvis, ORB, Stopp.", without_timestamps=True)
        self.zuletzt = time.time()
        return " ".join(s.text.strip() for s in segs).strip()


def main():
    from openwakeword.model import Model
    import openwakeword.utils
    try:
        openwakeword.utils.download_models(["hey_jarvis"])
    except Exception as e:
        log("Wake-Modell-Download:", e)
    ww = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    wh = Whisper()
    q = queue.Queue(maxsize=200)
    modus = {"t": 0.0, "mit": False, "an": True}

    def cb(indata, frames, t, status):
        try:
            q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    stream = sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=BLOCK, callback=cb)
    stream.start()
    log("Ohr gestartet")
    rausch, sprache, stille, puffer, vorlauf = 120.0, False, 0, [], []
    letzter_wake = 0.0
    while True:
        try:
            x = q.get(timeout=1)
        except queue.Empty:
            wh.frei()
            continue
        if time.time() - modus["t"] > 1.0:
            m = orb("/ohr/modus") or {}
            modus.update(t=time.time(), mit=bool(m.get("mitschreiben")), an=m.get("an", True))
            if not modus["mit"]:
                wh.frei()
        if not modus["an"]:
            sprache, puffer = False, []
            continue
        # 1) Aktivierungswort (immer, sehr leicht)
        p = ww.predict(x).get("hey_jarvis", 0)
        if p > 0.5 and time.time() - letzter_wake > 2.5:
            letzter_wake = time.time()
            log("Aktivierungswort erkannt (%.2f)" % p)
            orb("/ohr", {"typ": "wake"})
            sprache, puffer = False, []
            continue
        if not modus["mit"]:
            continue
        # 2) Sprachabschnitte finden (Pegel über dem Grundrauschen) und mit Whisper mitschreiben
        pegel = float(np.sqrt(np.mean(x.astype(np.float32) ** 2)))
        if not sprache:
            rausch = rausch * 0.97 + pegel * 0.03 if pegel < rausch * 3 else rausch
            vorlauf = (vorlauf + [x])[-4:]           # 0,3 s vor dem Einsatz mitnehmen
            if pegel > max(rausch * 3.2, 260):
                sprache, stille, puffer = True, 0, list(vorlauf)
        if sprache:
            puffer.append(x)
            stille = stille + 1 if pegel < max(rausch * 2.2, 200) else 0
            dauer = len(puffer) * BLOCK / SR
            if stille >= 10 or dauer > 20:          # 0,8 s Pause = Satzende (ORB fügt Fortsetzungen selbst zusammen)
                sprache = False
                if dauer - stille * BLOCK / SR >= 0.35:
                    audio = np.concatenate(puffer).astype(np.float32) / 32768.0
                    puffer = []
                    try:
                        t0 = time.time()
                        txt = wh.text(audio)
                        if txt and len(txt) > 1 and not txt.lower().startswith(("untertitel", "vielen dank fürs zuschauen")):
                            log("Text (%.1f s):" % (time.time() - t0), txt)
                            orb("/ohr", {"typ": "text", "text": txt, "dauer": round(dauer, 1)})
                    except Exception as e:
                        log("Whisper-Fehler:", e)
                puffer = []


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            log("Ohr abgestürzt, Neustart in 5 s:", e)
            time.sleep(5)
