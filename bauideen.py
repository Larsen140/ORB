"""Bau-Ideen für Minecraft: 3 KI-Entwürfe (lokal auf der RTX 4060) als Hologramm – Larsen wählt, ORB baut.

  py -3 bauideen.py "english prompt describing the build"  [--anzahl 3]

Dauert ~2–4 Min. (am besten als Hintergrund-Aufgabe). Ergebnis-JSON: {"ok", "ordner", "bilder": [...]}.
Die Bilder liegen in %LOCALAPPDATA%\\ORB\\bauideen\\<zeit>\\ – ORB merkt sich die letzte Runde in letzte.json.
"""
import argparse
import json
import os
import subprocess
import tempfile
import time

KI = r"C:\Users\larse\Projekte\bildwerkzeug\ki_bild.cmd"
BASIS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "bauideen")
NO_WINDOW = 0x08000000
STIL = ("isometric view of a voxel building made of cubic blocks, blocky game build, every block clearly visible, "
        "full building in frame, simple grass ground, clean sky background, bright daylight, sharp, no people, no text")


def holo(bilder, titel):
    inhalt = [{"typ": "text", "text": "Von links nach rechts: 1, 2, 3. Sag „Nummer 2“ – dann baue ich ihn dir in Minecraft (Cheats an)."}]
    inhalt += [{"typ": "bild", "pfad": p, "reihe": True} for p in bilder]
    karte = {"id": "bauideen", "titel": "Bau-Ideen · " + titel[:40], "groesse": "riesig", "farbe": "gruen", "inhalt": inhalt}
    pfad = os.path.join(tempfile.gettempdir(), "orb_bauideen.json")
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(karte, f, ensure_ascii=False)
    skript = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holo.ps1")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", skript, "-Json", pfad],
                   capture_output=True, creationflags=NO_WINDOW)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--anzahl", type=int, default=3)
    ap.add_argument("--titel", default="")
    a = ap.parse_args()
    ordner = os.path.join(BASIS, time.strftime("%Y-%m-%d_%H%M%S"))
    os.makedirs(ordner, exist_ok=True)
    r = subprocess.run(["cmd", "/c", KI, f"{a.prompt}, {STIL}", "--format", "quadrat", "--stil", "3d",
                        "--anzahl", str(a.anzahl), "--ordner", ordner, "--name", "entwurf"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    zeile = next((z for z in reversed(r.stdout.splitlines()) if z.startswith('{"ok"')), None)
    bilder = json.loads(zeile).get("pfade", []) if zeile else []
    if not bilder:
        print(json.dumps({"ok": False, "fehler": (r.stderr or r.stdout)[-400:]}, ensure_ascii=False))
        return
    erg = {"ok": True, "ordner": ordner, "bilder": bilder, "prompt": a.prompt, "titel": a.titel or a.prompt}
    with open(os.path.join(BASIS, "letzte.json"), "w", encoding="utf-8") as f:
        json.dump(erg, f, ensure_ascii=False)
    holo(bilder, erg["titel"])
    print(json.dumps(erg, ensure_ascii=False))


if __name__ == "__main__":
    main()
