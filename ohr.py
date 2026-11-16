"""ORBs Ohr: lokale Spracherkennung (Whisper auf der Grafikkarte) + Aktivierungswort „Hey Jarvis“ – ohne Internet.

Läuft als eigener Prozess (venv in %LOCALAPPDATA%\\ORB\\ohr\\venv), von ORB gestartet. Fragt ORB, ob gerade mitgeschrieben
werden soll (Fenster wach) – sonst lauscht es nur auf das Aktivierungswort (braucht kaum Leistung) und weckt ORB auch bei
geschlossenem Fenster. Erkanntes geht an  POST /ohr  {typ: "wake"|"text", text}.
"""
import json
import os
import re
import queue
import sys
import threading
import time
import urllib.request

import numpy as np
import sounddevice as sd


def _cuda_pfade():
    """NVIDIA-Bibliotheken aus den pip-Paketen (nvidia-cublas/cudnn) für ctranslate2 auffindbar machen."""
    import glob
    import site
    for sp in site.getsitepackages() + [os.path.join(sys.prefix, "Lib", "site-packages")]:
        for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(d)
            except Exception:
                pass
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


_cuda_pfade()

BASIS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB")
PORT = int(os.environ.get("ORB_PORT", "8766"))
URL = "http://127.0.0.1:%d" % PORT
SR, BLOCK = 16000, 1280                    # 80 ms – Blockgröße von openWakeWord
MODELL = os.environ.get("ORB_WHISPER", "large-v3-turbo")
LOG = os.path.join(BASIS, "ohr.log")
# Wörter, die Larsen oft sagt – Whisper erkennt sie damit zuverlässiger (z. B. „Minecraft“ statt „Microfass“)
PROMPT = ("Jarvis, ORB. Stopp. Minecraft, Skin, Overlay, Meeting, Seminar, Opera, TikTok, Video, Gold, Trading, Chart, "
          "Hologramm, Spotify, Entwickler, Update, Larsens World, Casino, Ultimatrix, Omnitrix, Vantage, ForexFactory.")
HAENGT = re.compile(r"(?i)(\b(und|oder|aber|weil|dass|wenn|ob|also|äh|ähm|ich|du|mir|mich|mein|meine|meinen|der|die|das|den|dem|"
                    r"ein|eine|einen|zu|mit|für|von|im|in|auf|bitte|noch|mal)\W*$)|^\W*jarvis\W*$")


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
        try:
            return self._text(audio)
        except RuntimeError as e:   # Grafikkarte geht nicht (Treiber/Bibliothek) → auf CPU weitermachen statt taub zu sein
            log("GPU-Fehler, wechsle auf CPU:", e)
            from faster_whisper import WhisperModel
            with self.lock:
                self.m = WhisperModel("small", device="cpu", compute_type="int8")
            return self._text(audio)

    def _text(self, audio):
        segs, _ = self.m.transcribe(audio, language="de", beam_size=4, vad_filter=True, condition_on_previous_text=False,
                                    initial_prompt=PROMPT, without_timestamps=True)
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
    offen = {"text": "", "bis": 0.0}

    def senden(txt, dauer=0.0):
        """Angefangene Sätze („Jarvis.“, „… und“, ohne Satzende) kurz halten und mit der Fortsetzung verbinden."""
        if offen["text"]:
            txt = offen["text"].rstrip(" .") + (", " if re.match(r"(?i)^\W*jarvis\W*$", offen["text"]) else " ") + txt[0].lower() + txt[1:]
            offen["text"] = ""
        name_allein = re.match(r"(?i)^\W*jarvis\W*$", txt)
        if name_allein:
            orb("/ohr", {"typ": "wake"})   # sofort „Ich höre …“ zeigen, Frage kommt gleich
        frage = re.search(r"[?!]\s*$", txt)   # „Hörst du mich?“ ist fertig, auch wenn es auf „mich“ endet
        if (HAENGT.search(txt) and not frage) or not re.search(r"[.!?…]\s*$", txt) or name_allein:
            offen.update(text=txt, bis=time.time() + (3.5 if name_allein else 1.8))
            log("halte (unvollständig):", txt)
            return
        log("sende:", txt)
        orb("/ohr", {"typ": "text", "text": txt, "dauer": round(dauer, 1)})

    while True:
        if offen["text"] and time.time() > offen["bis"]:   # keine Fortsetzung gekommen → so abschicken
            t_ = offen["text"]
            offen["text"] = ""
            if not re.match(r"(?i)^\W*jarvis\W*$", t_):
                log("sende (ohne Fortsetzung):", t_)
                orb("/ohr", {"typ": "text", "text": t_})
        try:
            x = q.get(timeout=1)
        except queue.Empty:
            wh.frei()
            continue
        if time.time() - modus["t"] > 1.0:
            m = orb("/ohr/modus") or {}
            modus.update(t=time.time(), mit=bool(m.get("mitschreiben")), an=m.get("an", True))
            if modus["mit"]:
                if wh.m is None:   # ORB ist wach → Whisper SOFORT vorladen, nicht erst beim ersten Satz (sonst 3–7 s Verzögerung)
                    threading.Thread(target=wh.laden, daemon=True).start()
                wh.zuletzt = time.time()   # solange wach: geladen lassen
            else:
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
            if stille >= 8 or dauer > 20:           # 0,64 s Pause = Satzende (ORB fügt Fortsetzungen selbst zusammen)
                sprache = False
                if dauer - stille * BLOCK / SR >= 0.35:
                    audio = np.concatenate(puffer).astype(np.float32) / 32768.0
                    puffer = []
                    try:
                        t0 = time.time()
                        txt = wh.text(audio)
                        anfang = ("untertitel", "vielen dank fürs zuschauen", "sous-titr", "amara", "copyright", "swr ", "zdf",
                                  "bis zum nächsten mal", "danke fürs zuschauen", "thank you", "thanks for watching")
                        ganz = ("musik", "amen", "you", "bye", "hm", "mhm")   # nur wenn das ALLES ist
                        klein = txt.lower().strip(" .!?…,*[]()")
                        if txt and len(txt) > 1 and klein not in ganz and not any(klein.startswith(u) for u in anfang):
                            log("Text (%.1f s):" % (time.time() - t0), txt)
                            senden(txt, dauer)
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
