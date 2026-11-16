"""ORBs lokale KI-Stimme: Chatterbox Multilingual (Resemble AI, MIT-Lizenz) auf der Grafikkarte – kostenlos, ohne Limit.

Läuft im eigenen venv (%LOCALAPPDATA%\\ORB\\stimme\\venv), von ORB gestartet. HTTP nur lokal auf 127.0.0.1:8767:
  POST /tts  {"text": "...", "stimme": "thorsten|standard|<datei>", "emotion": 0.5}  → WAV
  GET  /status
Stimmen-Vorlagen (Klang wird übernommen): %LOCALAPPDATA%\\ORB\\stimme\\stimmen\\<name>.wav (z. B. thorsten = CC0 Thorsten-Voice).
Das Modell wird erst bei Bedarf geladen und nach 10 Min. Ruhe wieder freigegeben (Grafikkarte frei fürs Zocken).
"""
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASIS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "stimme")
STIMMEN = os.path.join(BASIS, "stimmen")
PORT = 8767
LOG = os.path.join(BASIS, "stimme.log")


def log(*x):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + " ".join(str(v) for v in x) + "\n")
    except Exception:
        pass


def token():
    try:
        with open(os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "token.txt")) as f:
            return f.read().strip()
    except Exception:
        return ""


class Modell:
    def __init__(self):
        self.m, self.zuletzt, self.lock = None, 0.0, threading.Lock()
        self.cond = {}   # Klang-Vorlage je Stimme vorbereitet

    def laden(self):
        if self.m is None:
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            t = time.time()
            self.m = ChatterboxMultilingualTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
            self.cond = {}
            log("Modell geladen in %.0f s" % (time.time() - t))
        self.zuletzt = time.time()

    def frei(self):
        with self.lock:
            if self.m is not None and time.time() - self.zuletzt > 600:
                self.m, self.cond = None, {}
                import gc
                import torch
                gc.collect()
                torch.cuda.empty_cache()
                log("Modell entladen (Ruhe)")

    def sprechen(self, text, stimme="thorsten", emotion=0.5):
        import torchaudio
        with self.lock:
            self.laden()
            ref = stimme if os.path.isfile(stimme) else os.path.join(STIMMEN, stimme + ".wav")
            kw = {"language_id": "de", "exaggeration": float(emotion), "cfg_weight": 0.3}   # 0.3: etwas schneller, gleich gut (0.0 erzeugt Artefakte)
            if os.path.isfile(ref):
                kw["audio_prompt_path"] = ref
            t = time.time()
            wav = self.m.generate(text, **kw)
            buf = io.BytesIO()
            torchaudio.save(buf, wav.cpu(), self.m.sr, format="wav")
            log("%.1f s für %d Zeichen (%s)" % (time.time() - t, len(text), stimme))
            self.zuletzt = time.time()
            return buf.getvalue()


M = Modell()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, typ="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/status"):
            return self._send(200, json.dumps({"ok": True, "geladen": M.m is not None,
                                               "stimmen": sorted(f[:-4] for f in os.listdir(STIMMEN) if f.endswith(".wav"))}).encode())
        self._send(404, b"{}")

    def do_POST(self):
        if self.headers.get("X-ORB-Token", "") != token():
            return self._send(403, b"{}")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            b = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            b = {}
        if self.path.startswith("/tts") and str(b.get("text", "")).strip():
            try:
                return self._send(200, M.sprechen(str(b["text"])[:600], str(b.get("stimme") or "thorsten"),
                                                  b.get("emotion", 0.5)), "audio/wav")
            except Exception as e:
                log("Fehler:", e)
                return self._send(500, json.dumps({"ok": False, "fehler": str(e)[:200]}).encode())
        if self.path.startswith("/laden"):   # vorab laden (ORB wird wach)
            threading.Thread(target=lambda: M.sprechen("Ja.", "thorsten"), daemon=True).start()
            return self._send(200, b'{"ok": true}')
        self._send(404, b"{}")


def aufraeumen():
    while True:
        time.sleep(30)
        M.frei()


if __name__ == "__main__":
    os.makedirs(STIMMEN, exist_ok=True)
    threading.Thread(target=aufraeumen, daemon=True).start()
    log("Stimme gestartet")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
