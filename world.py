"""ORBs Zugriff auf Larsens World (Daten-Repo Larsen140/Larsens-World-Daten).

  py -3 world.py stand                       Guthaben + Casino-Statistik anzeigen
  py -3 world.py geld +10000                 Guthaben erhöhen (auch -500)
  py -3 world.py geld 50000                  Guthaben auf genau 50000 setzen
  py -3 world.py setze settings.wheel.x 5    beliebigen Wert setzen (Punkt-Pfad, JSON-Wert)
  py -3 world.py zeige settings.bj           Teil der Daten anzeigen

Die World-App (PC, iPhone) holt sich Änderungen nach ~5 Sekunden selbst ab. Ändert die App gleichzeitig etwas,
gewinnt der neuere Stand – dann einfach nochmal ausführen.
"""
import json
import os
import subprocess
import sys
import time

REPO_URL = "https://github.com/Larsen140/Larsens-World-Daten.git"
ORDNER = os.path.join(os.path.expanduser("~"), "Projekte", "Larsens-World-Daten")
DATEI = os.path.join(ORDNER, "larsens-world-daten.json")
NO_WINDOW = 0x08000000


def git(*a, pruefen=True):
    r = subprocess.run(["git", "-C", ORDNER, *a], capture_output=True, text=True, encoding="utf-8", creationflags=NO_WINDOW)
    if pruefen and r.returncode:
        raise SystemExit("git %s: %s" % (a[0], (r.stderr or r.stdout).strip()[:300]))
    return r


def holen():
    if not os.path.isdir(os.path.join(ORDNER, ".git")):
        os.makedirs(os.path.dirname(ORDNER), exist_ok=True)
        subprocess.run(["git", "clone", "-q", REPO_URL, ORDNER], check=True, creationflags=NO_WINDOW)
    git("fetch", "-q", "origin")
    git("reset", "-q", "--hard", "origin/main")   # immer den aktuellen Stand der App nehmen
    with open(DATEI, encoding="utf-8") as f:
        return json.load(f)


def speichern(d, nachricht):
    d["at"] = int(time.time() * 1000)   # neuer Zeitstempel: die App übernimmt den Stand
    d["dev"], d["name"] = "orb", "ORB"
    with open(DATEI, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    git("add", "larsens-world-daten.json")
    git("commit", "-q", "-m", nachricht)
    if git("push", "-q", "origin", "HEAD:main", pruefen=False).returncode:
        return False
    return True


def pfad_setzen(d, pfad, wert):
    teile = pfad.split(".")
    x = d
    for t in teile[:-1]:
        x = x.setdefault(t, {})
    x[teile[-1]] = wert


def pfad_holen(d, pfad):
    x = d
    for t in pfad.split("."):
        x = x[t]
    return x


def aendern(funk, nachricht):
    for versuch in range(4):          # schreibt die App gerade, nochmal mit frischem Stand
        d = holen()
        ergebnis = funk(d)
        if speichern(d, nachricht):
            return ergebnis
        time.sleep(2)
    raise SystemExit("Konnte nicht speichern (App schreibt gerade dauernd?) – gleich nochmal versuchen.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "stand":
        d = holen()
        bj = d.get("settings", {}).get("bj", {})
        print(json.dumps({"guthaben": bj.get("bal"), "rekord": bj.get("best"), "gespielt": bj.get("played"),
                          "gewonnen": bj.get("won"), "verloren": bj.get("lost"), "stand_vom": d.get("at"),
                          "geraet": d.get("name")}, ensure_ascii=False))
    elif cmd == "geld":
        arg = sys.argv[2]

        def f(d):
            bj = d.setdefault("settings", {}).setdefault("bj", {})
            alt = int(bj.get("bal") or 0)
            neu = alt + int(arg) if arg[0] in "+-" else int(arg)
            bj["bal"] = max(0, neu)
            if bj["bal"] > int(bj.get("best") or 0):
                bj["best"], bj["bestAt"] = bj["bal"], int(time.time() * 1000)
            return {"vorher": alt, "jetzt": bj["bal"]}
        print(json.dumps(dict(aendern(f, "ORB: Guthaben " + arg), ok=True), ensure_ascii=False))
    elif cmd == "setze":
        pfad, roh = sys.argv[2], sys.argv[3]
        try:
            wert = json.loads(roh)
        except Exception:
            wert = roh
        aendern(lambda d: pfad_setzen(d, pfad, wert), "ORB: %s = %s" % (pfad, roh))
        print(json.dumps({"ok": True, pfad: wert}, ensure_ascii=False))
    elif cmd == "zeige":
        print(json.dumps(pfad_holen(holen(), sys.argv[2]), ensure_ascii=False, indent=1)[:4000])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
