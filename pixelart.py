"""Pixel-Art-Bauer: Bild → Minecraft-Blöcke (jede Version) → Befehlsliste für minecraft.ps1.

  py -3 pixelart.py <bild> [--breite 48] [--boden] [--version 1.21.11] [--bauen] [--vorschau]

Wand (Standard): steht senkrecht vor dem Spieler, Blickrichtung (ab 1.13 mit ^-Koordinaten, sonst nach Norden).
--boden: liegt flach vor dem Spieler. Transparente Pixel bleiben frei. --bauen führt es direkt im Spiel aus.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile

from PIL import Image

FARBEN = ["white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray", "cyan",
          "purple", "blue", "brown", "green", "red", "black"]
BETON = [(207, 213, 214), (224, 97, 1), (169, 48, 159), (36, 137, 199), (241, 175, 21), (94, 169, 24), (214, 101, 143),
         (55, 58, 62), (125, 125, 115), (21, 119, 136), (100, 32, 156), (45, 47, 143), (96, 60, 32), (73, 91, 36),
         (142, 33, 33), (8, 10, 15)]
TON = [(210, 178, 161), (162, 84, 38), (150, 88, 109), (113, 109, 138), (186, 133, 35), (104, 118, 53), (162, 78, 79),
       (58, 42, 36), (135, 107, 98), (87, 92, 92), (118, 70, 86), (74, 60, 91), (77, 51, 36), (76, 83, 42), (143, 61, 47),
       (37, 23, 16)]
WOLLE = [(234, 236, 237), (241, 118, 20), (189, 68, 179), (58, 175, 217), (248, 198, 40), (112, 185, 26), (237, 141, 172),
         (63, 68, 72), (142, 142, 135), (21, 138, 145), (122, 42, 173), (53, 57, 157), (114, 72, 41), (85, 110, 28),
         (161, 39, 35), (21, 21, 26)]


def version_tupel(v):
    zahlen = [int(x) for x in re.findall(r"\d+", v or "")[:3]] or [99]
    return tuple(zahlen + [0] * (3 - len(zahlen)))


def palette(version):
    v = version_tupel(version)
    p = []
    neu = v >= (1, 13, 0) or v[0] >= 2
    for i, f in enumerate(FARBEN):
        if neu:
            p += [(BETON[i], f"{f}_concrete"), (TON[i], f"{f}_terracotta"), (WOLLE[i], f"{f}_wool")]
        else:
            if v >= (1, 12, 0):
                p.append((BETON[i], f"concrete {i}"))
            p += [(TON[i], f"stained_hardened_clay {i}"), (WOLLE[i], f"wool {i}")]
    return p, neu


def naechster(c, pal):
    r, g, b = c
    return min(pal, key=lambda e: 2 * (e[0][0] - r) ** 2 + 4 * (e[0][1] - g) ** 2 + 3 * (e[0][2] - b) ** 2)[1]


def befehle(bild, breite, boden, version):
    pal, neu = palette(version)
    img = Image.open(bild).convert("RGBA")
    hoehe = max(1, round(img.height * breite / img.width))
    img = img.resize((breite, hoehe), Image.LANCZOS)
    px = img.load()
    out, bloecke = [], {}
    farbe_von = {name: c for c, name in pal}
    vor = Image.new("RGBA", (breite, hoehe), (0, 0, 0, 0))
    for zeile in range(hoehe):
        x = 0
        while x < breite:
            r, g, b, a = px[x, zeile]
            if a < 128:
                x += 1
                continue
            blk = naechster((r, g, b), pal)
            ende = x
            while ende + 1 < breite and px[ende + 1, zeile][3] >= 128 and naechster(px[ende + 1, zeile][:3], pal) == blk:
                ende += 1
            bloecke[blk] = bloecke.get(blk, 0) + ende - x + 1
            for xx in range(x, ende + 1):
                vor.putpixel((xx, zeile), farbe_von[blk] + (255,))
            l1, l2 = breite // 2 - x, breite // 2 - ende          # ^links: positiv = links vom Spieler
            if neu:
                if boden:
                    out.append(f"fill ^{l1} ^-1 ^{3 + zeile} ^{l2} ^-1 ^{3 + zeile} {blk}")
                else:
                    y = hoehe - 1 - zeile
                    out.append(f"fill ^{l1} ^{y} ^6 ^{l2} ^{y} ^6 {blk}")
            else:   # alte Versionen: feste Achsen (Wand nach Norden bzw. Boden nach Norden)
                ax1, ax2 = x - breite // 2, ende - breite // 2
                if boden:
                    out.append(f"fill ~{ax1} ~-1 ~-{3 + zeile} ~{ax2} ~-1 ~-{3 + zeile} {blk}")
                else:
                    y = hoehe - 1 - zeile
                    out.append(f"fill ~{ax1} ~{y} ~-6 ~{ax2} ~{y} ~-6 {blk}")
            x = ende + 1
    vor.resize((breite * 12, hoehe * 12), Image.NEAREST).save(os.path.join(tempfile.gettempdir(), "mc_pixelart_vorschau.png"))
    return out, (breite, hoehe), bloecke


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bild")
    ap.add_argument("--breite", type=int, default=48)
    ap.add_argument("--boden", action="store_true")
    ap.add_argument("--version", default="")
    ap.add_argument("--bauen", action="store_true")
    a = ap.parse_args()
    hier = os.path.dirname(os.path.abspath(__file__))
    version = a.version
    if not version:
        try:
            info = json.loads(subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                              os.path.join(hier, "minecraft.ps1"), "-Info"], capture_output=True, text=True,
                                             creationflags=0x08000000).stdout.strip() or "{}")
            version = info.get("version", "")
        except Exception:
            version = ""
    cmds, groesse, bloecke = befehle(a.bild, a.breite, a.boden, version)
    datei = os.path.join(tempfile.gettempdir(), "mc_pixelart.txt")
    with open(datei, "w", encoding="utf-8") as f:
        f.write("\n".join(cmds))
    erg = {"ok": True, "datei": datei, "vorschau": os.path.join(tempfile.gettempdir(), "mc_pixelart_vorschau.png"), "befehle": len(cmds), "groesse": f"{groesse[0]}×{groesse[1]} Blöcke",
           "version": version or "unbekannt (neue Syntax)", "minuten_ca": round(len(cmds) * 0.3 / 60, 1),
           "haeufigste": sorted(bloecke.items(), key=lambda e: -e[1])[:6]}
    if a.bauen:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(hier, "minecraft.ps1"),
                            "-Datei", datei, "-Pause", "90"], capture_output=True, text=True, creationflags=0x08000000)
        erg["ausgefuehrt"] = (r.stdout or r.stderr).strip()[-200:]
    print(json.dumps(erg, ensure_ascii=False))


if __name__ == "__main__":
    main()
