"""PC-Doktor: warum ist der PC langsam? Was frisst Speicher/CPU/GPU, wie voll ist die Platte, wie warm die Grafikkarte?

  py -3 pcdoktor.py              Diagnose als JSON (+ --holo: Hologramm in ORB)
  py -3 pcdoktor.py --aufraeumen Temp-Dateien älter als 1 Tag löschen (nur %TEMP% und Windows-Temp des Nutzers)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import psutil

NO_WINDOW = 0x08000000


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=8,
                             creationflags=NO_WINDOW).stdout.strip().split(", ")
        return dict(name=out[0], last=int(out[1]), vram_mb=int(out[2]), vram_gesamt_mb=int(out[3]), temp=int(out[4]))
    except Exception:
        return None


def ordner_groesse(pfad, alter_tage=0):
    gesamt, grenze = 0, time.time() - alter_tage * 86400
    for wurzel, _, dateien in os.walk(pfad):
        for d in dateien:
            try:
                st = os.stat(os.path.join(wurzel, d))
                if st.st_mtime < grenze:
                    gesamt += st.st_size
            except OSError:
                pass
    return gesamt


def diagnose():
    for p in psutil.process_iter(["name"]):
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(1.5)
    procs = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            n = p.info["name"] or "?"
            e = procs.setdefault(n, {"name": n, "ram_mb": 0, "cpu": 0.0, "anzahl": 0})
            e["ram_mb"] += (p.info["memory_info"].rss if p.info["memory_info"] else 0) / 2**20
            e["cpu"] += p.cpu_percent(None) / psutil.cpu_count()
            e["anzahl"] += 1
        except Exception:
            pass
    liste = list(procs.values())
    vm, platte = psutil.virtual_memory(), shutil.disk_usage("C:\\")
    temp = tempfile.gettempdir()
    erg = {
        "cpu_prozent": psutil.cpu_percent(1),
        "ram": {"belegt_prozent": vm.percent, "frei_gb": round(vm.available / 2**30, 1), "gesamt_gb": round(vm.total / 2**30, 1)},
        "platte_c": {"frei_gb": round(platte.free / 2**30, 1), "belegt_prozent": round(platte.used / platte.total * 100, 1)},
        "gpu": gpu(),
        "top_ram": [dict(e, ram_mb=round(e["ram_mb"])) for e in sorted(liste, key=lambda e: -e["ram_mb"])[:6]],
        "top_cpu": [dict(e, cpu=round(e["cpu"], 1), ram_mb=round(e["ram_mb"])) for e in sorted(liste, key=lambda e: -e["cpu"])[:5]],
        "temp_gb_aufraeumbar": round(ordner_groesse(temp, 1) / 2**30, 2),
        "laufzeit_h": round((time.time() - psutil.boot_time()) / 3600, 1),
    }
    warn = []
    if erg["ram"]["belegt_prozent"] > 85:
        warn.append(f"Arbeitsspeicher zu {erg['ram']['belegt_prozent']:.0f} % voll – größter Fresser: {erg['top_ram'][0]['name']}")
    if erg["cpu_prozent"] > 80:
        warn.append(f"Prozessor zu {erg['cpu_prozent']:.0f} % ausgelastet – vor allem {erg['top_cpu'][0]['name']}")
    if erg["platte_c"]["frei_gb"] < 25:
        warn.append(f"Festplatte C: fast voll – nur noch {erg['platte_c']['frei_gb']} GB frei")
    g = erg["gpu"]
    if g and g["temp"] >= 83:
        warn.append(f"Grafikkarte heiß: {g['temp']} °C")
    if g and g["vram_mb"] > 0.9 * g["vram_gesamt_mb"]:
        warn.append(f"Grafikspeicher fast voll ({g['vram_mb']} von {g['vram_gesamt_mb']} MB)")
    if erg["laufzeit_h"] > 72:
        warn.append(f"PC läuft seit {erg['laufzeit_h']:.0f} Stunden – ein Neustart hilft oft")
    if erg["temp_gb_aufraeumbar"] > 2:
        warn.append(f"{erg['temp_gb_aufraeumbar']} GB alte Temp-Dateien – aufräumen möglich")
    erg["warnungen"] = warn
    return erg


def aufraeumen():
    grenze, frei, n = time.time() - 86400, 0, 0
    for pfad in {tempfile.gettempdir(), os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp")}:
        for wurzel, ordner, dateien in os.walk(pfad, topdown=False):
            if "claude" in wurzel.lower():   # laufende Claude-Sitzungen nicht stören
                continue
            for d in dateien:
                p = os.path.join(wurzel, d)
                try:
                    st = os.stat(p)
                    if st.st_mtime < grenze:
                        os.remove(p)
                        frei += st.st_size
                        n += 1
                except OSError:
                    pass
            for o in ordner:
                try:
                    os.rmdir(os.path.join(wurzel, o))   # nur leere Ordner
                except OSError:
                    pass
    return {"geloescht": n, "frei_gb": round(frei / 2**30, 2)}


def holo(erg):
    g = erg["gpu"] or {}
    inhalt = [{"typ": "zahl", "wert": f"{erg['cpu_prozent']:.0f}", "einheit": "%", "label": "CPU", "reihe": True},
              {"typ": "zahl", "wert": f"{erg['ram']['belegt_prozent']:.0f}", "einheit": "%", "label": "RAM", "reihe": True},
              {"typ": "zahl", "wert": f"{g.get('temp', '–')}", "einheit": "°C", "label": "GPU", "reihe": True},
              {"typ": "fortschritt", "prozent": erg["platte_c"]["belegt_prozent"], "label": f"Platte C: ({erg['platte_c']['frei_gb']} GB frei)"},
              {"typ": "tabelle", "kopf": ["Größte Speicherfresser", "RAM"],
               "zeilen": [[e["name"] + (f" ×{e['anzahl']}" if e["anzahl"] > 1 else ""), f"{e['ram_mb']} MB"] for e in erg["top_ram"]]}]
    inhalt.append({"typ": "liste", "punkte": erg["warnungen"]} if erg["warnungen"] else {"typ": "text", "text": "Alles im grünen Bereich."})
    karte = {"id": "pcdoktor", "titel": "PC-Doktor", "groesse": "mittel", "farbe": "rot" if erg["warnungen"] else "gruen", "inhalt": inhalt}
    pfad = os.path.join(tempfile.gettempdir(), "orb_pcdoktor.json")
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(karte, f, ensure_ascii=False)
    skript = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holo.ps1")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", skript, "-Json", pfad],
                   capture_output=True, creationflags=NO_WINDOW)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--aufraeumen", action="store_true")
    ap.add_argument("--holo", action="store_true")
    a = ap.parse_args()
    if a.aufraeumen:
        print(json.dumps(aufraeumen(), ensure_ascii=False))
        sys.exit(0)
    e = diagnose()
    print(json.dumps(e, ensure_ascii=False, indent=1))
    if a.holo:
        holo(e)
