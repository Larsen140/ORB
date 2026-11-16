"""Schnelle Bau-Ideen für Minecraft: ORB entwirft 3 Bauten direkt aus Blöcken, dieses Skript zeichnet sie in ~1 s als
isometrische Vorschau ins Hologramm und baut den gewählten Entwurf GENAU so in Minecraft (keine Bild-KI, keine Grafikkarte).

  py -3 bauvorschau.py zeigen <entwuerfe.json>      → 3 Vorschaubilder als Hologramm (von links 1, 2, 3)
  py -3 bauvorschau.py bauen <Nummer> [--nur-datei] → /fill-Befehle erzeugen und per minecraft.ps1 ins Spiel tippen

entwuerfe.json:
  {"titel": "Burg am See", "entwuerfe": [
     {"name": "Wehrturm", "teile": [
        {"block": "stone_bricks", "von": [0,0,0], "bis": [8,10,8], "hohl": true},
        {"block": "air", "von": [4,1,0], "bis": [4,2,0]},                 # Tür ausschneiden
        {"block": "glass_pane", "von": [0,5,3], "bis": [0,6,5]} ]}, ...]}
  Koordinaten relativ: x nach rechts, y nach oben, z nach hinten; spätere Teile überschreiben frühere (air schneidet aus).
"""
import json
import os
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw

BASIS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "bauideen")
HIER = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = 0x08000000

# Farben nach Stichwort im Blocknamen (erstes Treffer-Wort zählt)
FARBEN = [
    ("glass", (170, 215, 235, 120)), ("water", (50, 110, 210, 170)), ("lava", (230, 110, 20, 255)),
    ("leaves", (60, 130, 45, 255)), ("grass", (95, 160, 65, 255)), ("dirt", (125, 90, 60, 255)), ("sand", (220, 205, 150, 255)),
    ("quartz", (236, 232, 225, 255)), ("white", (232, 234, 236, 255)), ("snow", (245, 248, 250, 255)),
    ("black", (30, 30, 34, 255)), ("blackstone", (45, 40, 48, 255)), ("deepslate", (75, 75, 82, 255)), ("obsidian", (30, 20, 45, 255)),
    ("red", (165, 45, 40, 255)), ("brick", (150, 75, 60, 255)), ("orange", (225, 120, 30, 255)), ("yellow", (235, 200, 50, 255)),
    ("gold", (240, 205, 60, 255)), ("lime", (120, 200, 40, 255)), ("green", (75, 120, 40, 255)), ("cyan", (30, 140, 150, 255)),
    ("light_blue", (90, 170, 220, 255)), ("blue", (50, 60, 160, 255)), ("purple", (115, 45, 165, 255)), ("magenta", (175, 65, 165, 255)),
    ("pink", (230, 140, 170, 255)), ("gray", (110, 110, 115, 255)), ("grey", (110, 110, 115, 255)),
    ("dark_oak", (70, 48, 28, 255)), ("spruce", (110, 80, 50, 255)), ("birch", (200, 180, 125, 255)), ("jungle", (160, 115, 80, 255)),
    ("acacia", (170, 95, 55, 255)), ("mangrove", (120, 55, 50, 255)), ("cherry", (225, 175, 170, 255)), ("crimson", (110, 50, 75, 255)),
    ("warped", (45, 120, 115, 255)), ("bamboo", (195, 175, 85, 255)), ("oak", (165, 130, 80, 255)), ("log", (105, 80, 50, 255)),
    ("prismarine", (90, 160, 145, 255)), ("lantern", (250, 215, 120, 255)), ("glowstone", (245, 210, 120, 255)), ("torch", (250, 200, 90, 255)),
    ("terracotta", (160, 90, 65, 255)), ("andesite", (135, 135, 135, 255)), ("diorite", (200, 200, 200, 255)), ("granite", (150, 105, 85, 255)),
    ("cobble", (120, 120, 120, 255)), ("mossy", (100, 120, 85, 255)), ("stone", (128, 128, 128, 255)), ("iron", (210, 210, 210, 255)),
    ("copper", (190, 105, 75, 255)), ("diamond", (100, 220, 215, 255)), ("emerald", (40, 190, 90, 255)), ("netherrack", (110, 40, 40, 255)),
    ("wool", (225, 225, 225, 255)), ("concrete", (200, 200, 200, 255)), ("plank", (165, 130, 80, 255)), ("wood", (105, 80, 50, 255)),
]


def farbe(block):
    b = block.lower().replace("minecraft:", "")
    for wort, f in FARBEN:
        if wort in b:
            return f
    return (150, 150, 150, 255)


def voxel(entwurf, grenze=120000):
    welt = {}
    for t in entwurf.get("teile", []):
        (x1, y1, z1), (x2, y2, z2) = t["von"], t.get("bis", t["von"])
        x1, x2, y1, y2, z1, z2 = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2), min(z1, z2), max(z1, z2)
        b = t["block"].lower().replace("minecraft:", "")
        hohl = t.get("hohl")
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                for z in range(z1, z2 + 1):
                    if hohl and x1 < x < x2 and y1 < y < y2 and z1 < z < z2:
                        welt.pop((x, y, z), None)   # hohl = innen Luft (wie /fill … hollow)
                        continue
                    if b in ("air", "cave_air", "void_air"):
                        welt.pop((x, y, z), None)
                    else:
                        welt[(x, y, z)] = b
                    if len(welt) > grenze:
                        return welt
    return welt


def zeichnen(entwurf, pfad, groesse=640):
    welt = voxel(entwurf)
    bild = Image.new("RGBA", (groesse, groesse), (14, 18, 30, 255))
    if not welt:
        bild.save(pfad)
        return
    xs, ys, zs = zip(*welt)
    # Bildgröße passend: isometrische Projektion  sx = (x - z),  sy = (x + z)/2 - y
    sx = [x - z for x, y, z in welt]
    sy = [(x + z) / 2 - y for x, y, z in welt]
    breite, hoehe = max(sx) - min(sx) + 2, max(sy) - min(sy) + 2.5
    a = min((groesse * 0.86) / breite, (groesse * 0.86) / hoehe, 28)
    ox = groesse / 2 - (max(sx) + min(sx)) / 2 * a
    oy = groesse / 2 - (max(sy) + min(sy) - 1) / 2 * a
    d = ImageDraw.Draw(bild, "RGBA")

    def p(x, y, z):
        return (ox + (x - z) * a, oy + ((x + z) / 2 - y) * a)

    def schatten(f, k):
        return (int(f[0] * k), int(f[1] * k), int(f[2] * k), f[3])

    linie = max(1, int(a / 14))
    # Boden-Schatten
    for (x, y, z) in welt:
        if y == min(ys):
            d.polygon([p(x, y, z), p(x + 1, y, z), p(x + 1, y, z + 1), p(x, y, z + 1)], fill=(0, 0, 0, 60))
    # Maler-Reihenfolge: Betrachter steht bei +x/+y/+z → hinten-unten zuerst
    for (x, y, z) in sorted(welt, key=lambda v: (v[0] + v[1] + v[2], v[1])):
        b = welt[(x, y, z)]
        f = farbe(b)
        oben = (x, y + 1, z) not in welt or "glass" in welt.get((x, y + 1, z), "")
        links = (x, y, z + 1) not in welt
        rechts = (x + 1, y, z) not in welt
        kante = (0, 0, 0, 70)
        if oben:
            d.polygon([p(x, y + 1, z), p(x + 1, y + 1, z), p(x + 1, y + 1, z + 1), p(x, y + 1, z + 1)], fill=schatten(f, 1.0), outline=kante, width=linie)
        if links:   # Seite zum Betrachter links (z+1)
            d.polygon([p(x, y, z + 1), p(x + 1, y, z + 1), p(x + 1, y + 1, z + 1), p(x, y + 1, z + 1)], fill=schatten(f, .72), outline=kante, width=linie)
        if rechts:  # Seite zum Betrachter rechts (x+1)
            d.polygon([p(x + 1, y, z), p(x + 1, y, z + 1), p(x + 1, y + 1, z + 1), p(x + 1, y + 1, z)], fill=schatten(f, .55), outline=kante, width=linie)
    bild.convert("RGB").save(pfad)


def holo(bilder, titel, namen):
    text = "  ·  ".join("%d: %s" % (i + 1, n) for i, n in enumerate(namen))
    inhalt = [{"typ": "text", "text": text + " – sag „Nummer 2“, dann baue ich ihn genau so (Cheats an)."}]
    inhalt += [{"typ": "bild", "pfad": b, "reihe": True} for b in bilder]
    karte = {"id": "bauideen", "titel": "Bau-Ideen · " + titel[:40], "groesse": "riesig", "farbe": "gruen", "inhalt": inhalt}
    pfad = os.path.join(tempfile.gettempdir(), "orb_bauideen.json")
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(karte, f, ensure_ascii=False)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(HIER, "holo.ps1"), "-Json", pfad],
                   capture_output=True, creationflags=NO_WINDOW, timeout=20)


def befehle(entwurf, vor=3):
    """/fill-Befehle relativ zum Spieler (Bau startet `vor` Blöcke vor ihm, Richtung +x/+z); große Teile werden geteilt."""
    aus = []
    for t in entwurf.get("teile", []):
        (x1, y1, z1), (x2, y2, z2) = t["von"], t.get("bis", t["von"])
        x1, x2, y1, y2, z1, z2 = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2), min(z1, z2), max(z1, z2)
        b = t["block"].replace("minecraft:", "")
        hohl = " hollow" if t.get("hohl") else ""
        schritt = 30   # ≤ 32768 Blöcke pro /fill
        for xa in range(x1, x2 + 1, schritt):
            for za in range(z1, z2 + 1, schritt):
                xb, zb = min(xa + schritt - 1, x2), min(za + schritt - 1, z2)
                h = hohl if (xa, za, xb, zb) == (x1, z1, x2, z2) else ""
                aus.append("fill ~%d ~%d ~%d ~%d ~%d ~%d %s%s" % (xa + vor, y1, za + vor, xb + vor, y2, zb + vor, b, h))
    return aus


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    os.makedirs(BASIS, exist_ok=True)
    if sys.argv[1] == "zeigen":
        with open(sys.argv[2], encoding="utf-8-sig") as f:
            daten = json.load(f)
        ordner = os.path.join(BASIS, time.strftime("%Y-%m-%d_%H%M%S"))
        os.makedirs(ordner, exist_ok=True)
        t0 = time.time()
        bilder = []
        for i, e in enumerate(daten["entwuerfe"], 1):
            pfad = os.path.join(ordner, "entwurf_%d.png" % i)
            zeichnen(e, pfad)
            bilder.append(pfad)
        erg = {"ok": True, "art": "bloecke", "ordner": ordner, "bilder": bilder, "titel": daten.get("titel", ""),
               "entwuerfe": daten["entwuerfe"], "sekunden": round(time.time() - t0, 1)}
        with open(os.path.join(BASIS, "letzte.json"), "w", encoding="utf-8") as f:
            json.dump(erg, f, ensure_ascii=False)
        holo(bilder, erg["titel"], [e.get("name", "Entwurf") for e in daten["entwuerfe"]])
        print(json.dumps({k: v for k, v in erg.items() if k != "entwuerfe"}, ensure_ascii=False))
    elif sys.argv[1] == "bauen":
        with open(os.path.join(BASIS, "letzte.json"), encoding="utf-8") as f:
            erg = json.load(f)
        e = erg["entwuerfe"][int(sys.argv[2]) - 1]
        zeilen = befehle(e)
        datei = os.path.join(tempfile.gettempdir(), "mc_bau.txt")
        with open(datei, "w", encoding="utf-8") as f:
            f.write("\n".join(zeilen))
        print(json.dumps({"ok": True, "entwurf": e.get("name"), "befehle": len(zeilen), "datei": datei}, ensure_ascii=False))
        if "--nur-datei" not in sys.argv:
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(HIER, "minecraft.ps1"),
                            "-Datei", datei], creationflags=NO_WINDOW)


if __name__ == "__main__":
    main()
