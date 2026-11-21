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
PROMPT = ("Jarvis, ORB. Stopp. Meeting, Seminar, Opera, Gold, Trading, Chart, Journal, Notiz, Long, Short, Break-even, Lot, "
          "Hologramm, Spotify, Entwickler, Update, Larsens World, Casino, Vantage, ForexFactory, TradingView.")
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


class Sprecher:
    """Erkennt Larsens Stimme (WeSpeaker ResNet34, ONNX, lokal). Lernt das Profil selbst aus den ersten Sätzen mit „Jarvis“
    und passt es danach langsam an. Fremde Stimmen (Discord, Fernseher, Besuch) werden verworfen."""
    MODELL = os.path.join(BASIS, "ohr", "sprecher.onnx")
    PROFIL = os.path.join(BASIS, "ohr", "stimmprofil.json")
    SCHWELLE = 0.42          # Test: gleicher Sprecher ~0,75, fremde 0,2–0,36 (Werte stehen im ohr.log zum Nachjustieren)
    LERN_SAETZE = 6

    def __init__(self):
        self.s = None
        self.profil, self.n, self.sammel = None, 0, []
        try:
            with open(self.PROFIL, encoding="utf-8") as f:
                d = json.load(f)
            self.profil, self.n = np.array(d["v"], dtype=np.float32), d.get("n", 0)
        except Exception:
            pass

    def bereit(self):
        if self.s is None and os.path.exists(self.MODELL):
            import onnxruntime as ort
            self.s = ort.InferenceSession(self.MODELL, providers=["CPUExecutionProvider"])
            n = np.arange(400)
            self.fenster = (0.5 - 0.5 * np.cos(2 * np.pi * n / 399)) ** 0.85
            mel = lambda f: 1127 * np.log(1 + f / 700.0)
            lo, hi = mel(20), mel(8000)
            punkte = lo + (hi - lo) * np.arange(82) / 81
            fm = mel(np.arange(257) * 16000 / 512)
            self.bank = np.zeros((80, 257), dtype=np.float32)
            for i in range(80):
                l, c, r = punkte[i], punkte[i + 1], punkte[i + 2]
                self.bank[i] = np.clip(np.minimum((fm - l) / (c - l), (r - fm) / (r - c)), 0, None)
        return self.s is not None

    def merkmale(self, audio):
        x = audio.astype(np.float64) * 32768
        if len(x) < 400:
            x = np.pad(x, (0, 400 - len(x)))
        anz = 1 + (len(x) - 400) // 160
        idx = np.arange(400)[None, :] + 160 * np.arange(anz)[:, None]
        fr = x[idx]
        fr = fr - fr.mean(axis=1, keepdims=True)
        fr = np.concatenate([fr[:, :1] - 0.97 * fr[:, :1], fr[:, 1:] - 0.97 * fr[:, :-1]], axis=1) * self.fenster
        spek = np.abs(np.fft.rfft(fr, 512)) ** 2
        f = np.log(np.maximum(spek @ self.bank.T, 1.19e-7)).astype(np.float32)
        return f - f.mean(axis=0, keepdims=True)

    def vektor(self, audio):
        e = self.s.run(None, {"feats": self.merkmale(audio)[None]})[0][0]
        return e / (np.linalg.norm(e) + 1e-9)

    def speichern(self):
        with open(self.PROFIL, "w", encoding="utf-8") as f:
            json.dump({"v": [float(v) for v in self.profil], "n": self.n}, f)

    def pruefen(self, audio, txt):
        """True = durchlassen. Ohne Profil: alles durchlassen und aus Sätzen mit „Jarvis“ lernen."""
        try:
            if len(audio) < 16000 * 0.8 or not self.bereit():
                return True
            v = self.vektor(audio)
            if self.profil is None:
                if re.search(r"(?i)jarvis", txt) and len(audio) >= 16000 * 1.2:
                    self.sammel.append(v)
                    log("Stimmprofil lernen: %d/%d" % (len(self.sammel), self.LERN_SAETZE))
                    if len(self.sammel) >= self.LERN_SAETZE:
                        p = np.mean(self.sammel, axis=0)
                        self.profil, self.n = p / np.linalg.norm(p), len(self.sammel)
                        self.speichern()
                        log("Stimmprofil fertig – ab jetzt nur noch Larsens Stimme")
                return True
            wert = float(v @ self.profil)
            if wert < self.SCHWELLE:
                log("Fremde Stimme verworfen (%.2f): %s" % (wert, txt))
                return False
            log("Stimme ok (%.2f)" % wert)
            if wert > 0.55:   # sicher Larsen → Profil langsam nachführen (Mikro, Erkältung, Tageszeit)
                p = 0.95 * self.profil + 0.05 * v
                self.profil, self.n = p / np.linalg.norm(p), self.n + 1
                if self.n % 10 == 0:
                    self.speichern()
            return True
        except Exception as e:
            log("Stimmprüfung:", e)
            return True


def audio_laden(pfad):
    """Beliebige Audiodatei (OGG/Opus von Telegram, MP3 …) → 16 kHz mono float32 (eigener Decoder: faster_whispers
    decode_audio passt nicht zu PyAV 19)."""
    import av
    teile = []
    with av.open(pfad) as c:
        rs = av.AudioResampler(format="s16", layout="mono", rate=SR)
        for fr in c.decode(audio=0):
            for r in rs.resample(fr):
                teile.append(r.to_ndarray().reshape(-1))
        for r in rs.resample(None):
            teile.append(r.to_ndarray().reshape(-1))
    return (np.concatenate(teile).astype(np.float32) / 32768.0) if teile else np.zeros(0, np.float32)


def text_dienst(wh):
    """Kleiner lokaler Dienst für die Telegram-Brücke: POST http://127.0.0.1:8768/text (Audio-Datei, z. B. OGG) → {"text"}.
    Nutzt dasselbe geladene Whisper – kein zweites Modell auf der Grafikkarte."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import tempfile

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            if self.path != "/text" or self.headers.get("X-ORB-Token") != token():
                self.send_response(403)
                self.end_headers()
                return
            daten = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            fd, pfad = tempfile.mkstemp(suffix=".ogg")
            with os.fdopen(fd, "wb") as f:
                f.write(daten)
            try:
                txt = wh.text(audio_laden(pfad))
                log("Telegram-Sprachnachricht:", txt)
                antwort, code = {"text": txt}, 200
            except Exception as e:
                antwort, code = {"text": "", "fehler": str(e)[:200]}, 500
            finally:
                try:
                    os.remove(pfad)
                except Exception:
                    pass
            roh = json.dumps(antwort, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)

    try:
        ThreadingHTTPServer(("127.0.0.1", 8768), H).serve_forever()
    except Exception as e:
        log("Text-Dienst:", e)


def main():
    from openwakeword.model import Model
    import openwakeword.utils
    try:
        openwakeword.utils.download_models(["hey_jarvis"])
    except Exception as e:
        log("Wake-Modell-Download:", e)
    ww = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    wh = Whisper()
    threading.Thread(target=text_dienst, args=(wh,), daemon=True).start()
    sp = Sprecher()
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
            offen.update(text=txt, bis=time.time() + (4.0 if name_allein else 2.6), dauer=dauer)
            log("halte (unvollständig):", txt)
            return
        # Auch fertige Sätze kurz halten: spricht Larsen gleich weiter, wird es EIN Auftrag (nicht unterbrechen)
        offen.update(text=txt, bis=time.time() + (0.7 if frage else 1.1), dauer=dauer)
        log("halte kurz (vielleicht geht es weiter):", txt)

    while True:
        if offen["text"] and time.time() > offen["bis"]:   # keine Fortsetzung gekommen → so abschicken
            t_ = offen["text"]
            offen["text"] = ""
            if not re.match(r"(?i)^\W*jarvis\W*$", t_):
                log("sende:", t_)
                orb("/ohr", {"typ": "text", "text": t_, "dauer": round(offen.get("dauer", 0.0), 1)})
        try:
            x = q.get(timeout=1)
        except queue.Empty:
            wh.frei()
            continue
        if time.time() - modus["t"] > 1.0:
            m = orb("/ohr/modus") or {}
            modus.update(t=time.time(), mit=bool(m.get("mitschreiben")), an=m.get("an", True), stimm=m.get("stimmcheck", True))
            if modus["mit"]:
                if wh.m is None and not getattr(wh, "vorladen", False):   # ORB ist wach → Whisper vorladen (nicht erst beim ersten Satz)
                    wh.vorladen = True
                    def _vor():
                        time.sleep(3)   # erst das Dashboard flüssig einfliegen lassen, dann die Grafikkarte belasten
                        try:
                            wh.laden()
                        finally:
                            wh.vorladen = False
                    threading.Thread(target=_vor, daemon=True).start()
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
                if offen["text"]:   # Larsen redet weiter → mit dem Abschicken warten, bis auch dieser Teil verstanden ist
                    offen["bis"] = max(offen["bis"], time.time() + 8)
        if sprache:
            puffer.append(x)
            stille = stille + 1 if pegel < max(rausch * 1.9, 180) else 0   # leise Satzenden zählen noch als Sprache
            dauer = len(puffer) * BLOCK / SR
            if stille >= 15 or dauer > 45:          # 1,2 s Pause = Satzende – Larsen ausreden lassen (vorher 0,9 s schnitt ihn ab)
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
                            if not modus.get("stimm", True) or sp.pruefen(audio, txt):
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
