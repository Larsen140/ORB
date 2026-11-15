"""Test Echo-Schutz: ORBs eigene Sätze dürfen nicht als Larsens Frage zurückkommen.
Aufruf: py -3 test_echo.py   → „OK“ oder die Fehler. Prüft den Server-Abgleich und den der Oberfläche (Playwright)."""
import ast
import difflib
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
fehler = []

GESAGT_ORB = ["Super, Version 98 läuft. Ich habe die Echo-Sperre eingebaut.",
              "Das war wieder meine eigene Ansage – ich ignoriere sie.",
              "Update installiert. Neu in ORB: Echo-Schutz für das Mikro.",
              "Soll ich dir das Wetter für Berlin zeigen?"]
ECHO = ["Super Version 98 läuft", "super version 98 läuft ich habe die echo sperre eingebaut",
        "Das war wieder meine eigene Ansage", "das war wieder meine eigene ansage ich ignoriere sie",
        "Jarvis update installiert neu in orb echo schutz für das mikro", "Version 98 läuft ich habe die"]
FRAGEN = ["Wie wird das Wetter morgen in Hamburg?", "ja", "Stopp", "Spiel meine Playlist auf Spotify",
          "ja zeig das Wetter für Berlin", "Jarvis welche Version läuft gerade", "Was gibt es Neues bei ORB"]

# --- Server: Funktionen aus server.py holen (ohne ORB zu starten) ---
src = open(os.path.join(HERE, "server.py"), encoding="utf-8-sig").read()
ns = {"re": re, "difflib": difflib, "time": time}
for node in ast.parse(src).body:
    name = getattr(node, "name", None) or (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None))
    if name in ("GESAGT", "ECHO_SPERRE", "_NAMEN", "gesagt_merken", "_stamm", "echo_aehnlichkeit", "ist_echo"):
        exec(compile(ast.Module([node], []), "server.py", "exec"), ns)
for i, t in enumerate(GESAGT_ORB):
    ns["gesagt_merken"]("a%d" % i, t)
for t in ECHO:
    if not ns["ist_echo"](t):
        fehler.append("Server: Echo nicht erkannt: %r (%.2f)" % (t, ns["echo_aehnlichkeit"](t, GESAGT_ORB)))
for t in FRAGEN:
    if ns["ist_echo"](t):
        fehler.append("Server: echte Frage verworfen: %r (%.2f)" % (t, ns["echo_aehnlichkeit"](t, GESAGT_ORB)))
if ns["ECHO_SPERRE"] < 1.5:
    fehler.append("Server: Sperrzeit nach eigener Sprachausgabe unter 1,5 s")

# --- Oberfläche: gleicher Abgleich + Sperrzeit im Browser ---
PORT = 8797
env = dict(os.environ, ORB_PORT=str(PORT))
srv = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py")], cwd=HERE, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
try:
    for _ in range(40):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/version" % PORT, timeout=1)
            break
        except Exception:
            time.sleep(.25)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        b = p.chromium.launch(executable_path=edge if os.path.exists(edge) else None)
        pg = b.new_page()
        pg.goto("http://127.0.0.1:%d/" % PORT)
        time.sleep(2)
        r = pg.evaluate("""([gesagt, echo, fragen]) => {
            gesagt.forEach((t, i) => merkeGesagt('t' + i, t));
            const out = { echo: echo.filter(t => !istEcho(t)), fragen: fragen.filter(t => istEcho(t)) };
            fakeUntil = performance.now() + 300; out.waehrend = nachSprache();
            return new Promise(res => setTimeout(() => { out.nach1s = nachSprache();
              setTimeout(() => { out.nach2s = nachSprache(); res(out); }, 1000); }, 1300));
        }""", [GESAGT_ORB, ECHO, FRAGEN])
        b.close()
    fehler += ["Oberfläche: Echo nicht erkannt: %r" % t for t in r["echo"]]
    fehler += ["Oberfläche: echte Frage verworfen: %r" % t for t in r["fragen"]]
    if not (r["waehrend"] and r["nach1s"] and not r["nach2s"]):
        fehler.append("Oberfläche: Mikro-Sperre falsch (während %s, 1 s danach %s, 2 s danach %s)"
                      % (r["waehrend"], r["nach1s"], r["nach2s"]))
finally:
    srv.kill()

print("\n".join(fehler) if fehler else "OK")
sys.exit(1 if fehler else 0)
