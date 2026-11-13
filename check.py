"""Prüft ORB vor einem Update: Python-Syntax, dann echte Seite mit Test-Server laden (JavaScript- und 3D-Fehler).
Aufruf: py -3 check.py   → Ausgabe „OK“ oder die Fehler, Rückgabewert 0/1."""
import ast
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8799
fehler = []

for f in ("server.py", "orb_app.py", "hook.py"):
    try:
        with open(os.path.join(HERE, f), encoding="utf-8-sig") as fh:
            ast.parse(fh.read(), f)
    except SyntaxError as e:
        fehler.append("Python-Fehler in %s Zeile %s: %s" % (f, e.lineno, e.msg))
if fehler:
    print("\n".join(fehler))
    sys.exit(1)

env = dict(os.environ, ORB_PORT=str(PORT))
srv = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py")], cwd=HERE, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=0x08000000)
try:
    for _ in range(40):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/version" % PORT, timeout=1)
            break
        except Exception:
            time.sleep(.25)
    else:
        out = srv.stdout.read1(4000).decode("utf-8", "ignore") if srv.poll() is not None else ""
        print("Server startet nicht. " + out)
        sys.exit(1)
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("OK (nur Python geprüft – Playwright fehlt)")
        sys.exit(0)
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=edge if os.path.exists(edge) else None, args=[
            "--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        pg = b.new_page(viewport={"width": 1600, "height": 900})
        pg.on("console", lambda m: fehler.append("Konsole: " + m.text) if m.type == "error" and "404" not in m.text
              and "Failed to load resource" not in m.text else None)
        pg.on("pageerror", lambda e: fehler.append("JavaScript: " + str(e)))
        pg.goto("http://127.0.0.1:%d/" % PORT)
        time.sleep(4)
        try:
            if not pg.evaluate("typeof glOk === 'undefined' || glOk"):
                fehler.append("3D-Grafik (Shader) lässt sich nicht übersetzen")
        except Exception as e:
            fehler.append("Seite reagiert nicht: %s" % e)
        b.close()
finally:
    srv.kill()

if fehler:
    print("\n".join(dict.fromkeys(fehler)))
    sys.exit(1)
print("OK")
