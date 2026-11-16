"""Minecraft-Skin-Designer für ORB: Rezept (JSON) → 64×64-Skin, 3D-Vorschau als Hologramm, ab in die Launcher-Bibliothek.

  py -3 skin.py bauen  <rezept.json>        ein Rezept oder eine Liste (z. B. 3 Varianten) → Skins + 3D-Hologramm
  py -3 skin.py launcher <name>             Skin in die Skin-Bibliothek des Minecraft-Launchers legen
  py -3 skin.py launcher alle               alle PNGs aus Bilder/Minecraft-Skins (auch selbst abgelegte) in den Launcher
  py -3 skin.py zeigen [name …]             vorhandene Skins (auch eigene PNGs) als drehbares 3D-Hologramm
  py -3 skin.py liste                       vorhandene Skins

Rezept (alles optional außer name):
{"name":"ritter", "modell":"classic|slim", "haut":"#c68e6a", "augen":"#2a6bd6", "mund":true,
 "haare":{"farbe":"#3b2516","stil":"kurz|lang|glatze|irokese|zopf"}, "bart":"#3b2516",
 "oberteil":{"farbe":"#a31c2b","stil":"tshirt|pullover|hoodie|jacke|ruestung|anzug","aermel":"lang|kurz","akzent":"#d4af37","muster":"keins|streifen|karo|verlauf"},
 "hose":{"farbe":"#2c3e66","stil":"normal|ruestung"}, "schuhe":"#2a2a2a", "guertel":"#5a3a1a", "handschuhe":"#222222",
 "helm":{"stil":"ritter|kappe|krone|kapuze","farbe":"#d4af37","visier":"#151515"},
 "details":[{"teil":"kopf|koerper|arm_r|arm_l|bein_r|bein_l","seite":"front|back|left|right|top|bottom","ebene":"basis|overlay",
             "x":0,"y":0,"w":1,"h":1,"farbe":"#ff0000"}]}
Freies Pixel-Malen (jede Figur, jedes Logo, jedes Gesicht): "pixel":[{"teil":"kopf","seite":"front","ebene":"basis",
  "x":0,"y":0,"zeilen":["HHHHHHHH","HSSSSSSH","SWESSEWS",...],"farben":{"H":"#3b2516","S":"#e8b48f","W":"#ffffff","E":"#2e9e3e"}}]
  – je Zeichen ein Pixel, "." = unverändert lassen, "_" = durchsichtig (nur Overlay). Seitengrößen: Kopf 8×8; Körper front/back 8×12,
  left/right 4×12, top/bottom 8×4; Arme/Beine front/back/left/right 4×12 (slim-Arme 3×12), top/bottom 4×4.
Vorhandenen Skin bearbeiten: "basis":"<Dateiname im Skin-Ordner ohne .png oder voller Pfad>" – dann wird nur gemalt, was im Rezept
  steht (details/pixel und angegebene Teile), der Rest bleibt wie im Original. "schatten": false = exakte Farben ohne Schattierung.
Umfärben (beide Schichten, Schattierung bleibt): "umfaerben":[{"von":"#ffffff"|"weiss"|"schwarz"|"grau","nach":"#7a1f2b",
  "toleranz":60, "teile":["koerper","arm_r","arm_l"] (optional, sonst alle)}].
Beim Bearbeiten mit "basis" werden details/pixel AUTOMATISCH auch auf die Overlay-Schicht übertragen, wo dort etwas liegt
  (sonst würde die alte Overlay-Farbe darüber sichtbar bleiben). "nur_basis": true schaltet das ab.
Koordinaten in "details" sind lokal je Seite (x nach rechts, y nach unten; Kopf 8×8, Körper-Front 8×12, Arme/Beine-Front 4×12).
"""
import base64
import datetime as dt
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import uuid

from PIL import Image

ORDNER = os.path.join(os.path.expanduser("~"), "Pictures", "Minecraft-Skins")   # Larsens Skin-Ordner
LAUNCHER = os.path.join(os.environ.get("APPDATA", ""), ".minecraft", "launcher_custom_skins.json")
NO_WINDOW = 0x08000000

# Teil: (u, v, breite, höhe, tiefe) Basis-Ebene, (u, v) Overlay-Ebene
TEILE = {"kopf": ((0, 0, 8, 8, 8), (32, 0)), "koerper": ((16, 16, 8, 12, 4), (16, 32)),
         "arm_r": ((40, 16, 4, 12, 4), (40, 32)), "arm_l": ((32, 48, 4, 12, 4), (48, 48)),
         "bein_r": ((0, 16, 4, 12, 4), (0, 32)), "bein_l": ((16, 48, 4, 12, 4), (0, 48))}
LICHT = {"top": 1.10, "front": 1.0, "left": 0.9, "right": 0.9, "back": 0.84, "bottom": 0.75}


def rgb(h):
    h = str(h).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mischen(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


class Skin:
    def __init__(self, slim=False):
        self.img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        self.px = self.img.load()
        self.slim = slim
        self.seite = {}   # (x, y) -> Seite (für Schattierung)

    def box(self, teil, ebene="basis"):
        (u, v, w, h, d), (ou, ov) = TEILE[teil]
        if self.slim and teil.startswith("arm"):
            w = 3
        if ebene == "overlay":
            u, v = ou, ov
        return u, v, w, h, d

    def flaechen(self, teil, ebene="basis"):
        u, v, w, h, d = self.box(teil, ebene)
        return {"top": (u + d, v, w, d), "bottom": (u + d + w, v, w, d), "right": (u, v + d, d, h),
                "front": (u + d, v + d, w, h), "left": (u + d + w, v + d, d, h), "back": (u + 2 * d + w, v + d, w, h)}

    def setzen(self, x, y, farbe, seite):
        if 0 <= x < 64 and 0 <= y < 64:
            self.px[x, y] = tuple(farbe) + (255,) if len(farbe) == 3 else tuple(farbe)
            self.seite[(x, y)] = seite

    def rechteck(self, teil, seite, x, y, w, h, farbe, ebene="basis"):
        fx, fy, fw, fh = self.flaechen(teil, ebene)[seite]
        for yy in range(max(0, y), min(fh, y + h)):
            for xx in range(max(0, x), min(fw, x + w)):
                self.setzen(fx + xx, fy + yy, farbe, seite)

    def zeilen(self, teil, y0, y1, farbe, ebene="basis", seiten=("front", "back", "left", "right"), oben=False, unten=False):
        """Zeilen y0..y1 (inklusive) aller Seiten färben; top/bottom optional."""
        for s in seiten:
            fx, fy, fw, fh = self.flaechen(teil, ebene)[s]
            self.rechteck(teil, s, 0, y0, fw, y1 - y0 + 1, farbe, ebene)
        if oben:
            self.rechteck(teil, "top", 0, 0, 99, 99, farbe, ebene)
        if unten:
            self.rechteck(teil, "bottom", 0, 0, 99, 99, farbe, ebene)

    def ganz(self, teil, farbe, ebene="basis"):
        self.zeilen(teil, 0, 99, farbe, ebene, oben=True, unten=True)

    def schattieren(self, seed):
        rnd = random.Random(seed)
        for (x, y), s in self.seite.items():
            r, g, b, a = self.px[x, y]
            if a == 0:
                continue
            f = LICHT.get(s, 1.0) * (1 + rnd.uniform(-0.05, 0.05))
            self.px[x, y] = mischen((r, g, b), f) + (a,)


def basis_laden(name):
    pfad = name if os.path.isfile(name) else os.path.join(ORDNER, os.path.splitext(name)[0] + ".png")
    img = Image.open(pfad).convert("RGBA")
    if img.size == (64, 32):   # altes Format: linke Gliedmaßen aus den rechten spiegeln
        neu = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        neu.paste(img, (0, 0))
        neu.paste(img.crop((0, 16, 16, 32)).transpose(Image.FLIP_LEFT_RIGHT), (16, 48))
        neu.paste(img.crop((40, 16, 56, 32)).transpose(Image.FLIP_LEFT_RIGHT), (32, 48))
        img = neu
    return img.resize((64, 64), Image.NEAREST) if img.size != (64, 64) else img


def overlay_mitziehen(sk, vorher):
    """Was auf der Basis-Schicht geändert wurde, auch auf der Overlay-Schicht ändern – aber nur dort, wo das Overlay
    sichtbare Pixel hat (sonst bliebe die alte Overlay-Farbe über der neuen Basis sichtbar)."""
    for teil in TEILE:
        for seite in ("top", "bottom", "right", "front", "left", "back"):
            bx, by, bw, bh = sk.flaechen(teil, "basis")[seite]
            ox, oy, ow, oh = sk.flaechen(teil, "overlay")[seite]
            for y in range(min(bh, oh)):
                for x in range(min(bw, ow)):
                    neu, alt = sk.px[bx + x, by + y], vorher[bx + x, by + y]
                    if neu != alt and sk.px[ox + x, oy + y][3] > 0:
                        sk.px[ox + x, oy + y] = neu


def _hell(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def umfaerben(sk, ops):
    """Farbe ersetzen auf BEIDEN Schichten; Helligkeitsverlauf (Schattierung) bleibt erhalten."""
    import colorsys
    for o in ops or []:
        von, nach, tol = str(o.get("von", "#ffffff")).lower(), rgb(o.get("nach", "#7a1f2b")), float(o.get("toleranz", 60))
        teile = o.get("teile") or list(TEILE)

        def passt(c):
            r, g, b = c[:3]
            h, l, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if von in ("weiss", "weiß", "white"):
                return l > 0.62 and sat < 0.28
            if von in ("schwarz", "black"):
                return l < 0.22
            if von in ("grau", "grey", "gray"):
                return 0.2 <= l <= 0.75 and sat < 0.15
            z = rgb(von)
            return ((r - z[0]) ** 2 + (g - z[1]) ** 2 + (b - z[2]) ** 2) ** 0.5 <= tol

        ziel_l = _hell(nach) or 1
        for teil in teile:
            for ebene in ("basis", "overlay"):
                for seite, (fx, fy, fw, fh) in sk.flaechen(teil, ebene).items():
                    hell = [_hell(sk.px[fx + x, fy + y]) for y in range(fh) for x in range(fw)
                            if sk.px[fx + x, fy + y][3] > 0 and passt(sk.px[fx + x, fy + y])]
                    if not hell:
                        continue
                    mittel = sum(hell) / len(hell)
                    for y in range(fh):
                        for x in range(fw):
                            c = sk.px[fx + x, fy + y]
                            if c[3] > 0 and passt(c):
                                f = (_hell(c) / mittel) if mittel else 1   # Schattierung relativ beibehalten
                                sk.px[fx + x, fy + y] = mischen(nach, f) + (c[3],)


def tiefe(sk, staerke=1.0):
    """Keine flachen Skins: Kleidung, Haare und Schuhe zusätzlich auf die Overlay-Schicht legen (abstehend in 3D),
    Haut und Gesicht bleiben frei. Vorhandenes Overlay bleibt unangetastet."""
    import colorsys
    fx, fy, fw, fh = sk.flaechen("kopf", "basis")["front"]
    proben = [sk.px[fx + x, fy + y] for y in (5, 6) for x in (1, 2, 5, 6) if sk.px[fx + x, fy + y][3] > 0]
    haut = tuple(sum(c[i] for c in proben) // len(proben) for i in range(3)) if proben else (200, 150, 120)

    def ist_haut(c):
        return ((c[0] - haut[0]) ** 2 + (c[1] - haut[1]) ** 2 + (c[2] - haut[2]) ** 2) ** 0.5 < 48

    rnd = random.Random(7)
    for teil in TEILE:
        for seite in ("top", "bottom", "right", "front", "left", "back"):
            bx, by, bw, bh = sk.flaechen(teil, "basis")[seite]
            ox, oy, ow, oh = sk.flaechen(teil, "overlay")[seite]
            for y in range(min(bh, oh)):
                for x in range(min(bw, ow)):
                    if sk.px[ox + x, oy + y][3] > 0:
                        continue   # Overlay schon da
                    c = sk.px[bx + x, by + y]
                    if c[3] == 0 or ist_haut(c):
                        continue
                    if teil == "kopf":
                        # am Kopf nur Haare/Kopfbedeckung: oben, hinten, Seiten oben, vorne nur die obersten 2 Reihen
                        if seite == "front" and y > 1:
                            continue
                        if seite in ("left", "right") and y > 4:
                            continue
                        if seite == "bottom":
                            continue
                    f = (1.06 if seite == "top" else 0.94) * (1 + rnd.uniform(-0.04, 0.04) * staerke)
                    sk.px[ox + x, oy + y] = mischen(c[:3], f) + (255,)


def pixel_malen(sk, ops):
    for o in ops or []:
        try:
            farben = {k: (rgb(v) if v not in ("_", "transparent") else None) for k, v in (o.get("farben") or {}).items()}
            ebene, teil, seite = o.get("ebene", "basis"), o["teil"], o.get("seite", "front")
            fx, fy, fw, fh = sk.flaechen(teil, ebene)[seite]
            for dy, zeile in enumerate(o.get("zeilen") or []):
                for dx, ch in enumerate(zeile):
                    x, y = int(o.get("x", 0)) + dx, int(o.get("y", 0)) + dy
                    if ch == "." or not (0 <= x < fw and 0 <= y < fh):
                        continue
                    if ch == "_" or farben.get(ch, 0) is None:
                        sk.px[fx + x, fy + y] = (0, 0, 0, 0)
                        sk.seite.pop((fx + x, fy + y), None)
                    elif ch in farben:
                        sk.setzen(fx + x, fy + y, farben[ch], seite)
        except Exception as e:
            print("Pixel-Fehler:", e, file=sys.stderr)


def bauen(r):
    sk = Skin(r.get("modell") == "slim")
    if r.get("basis"):   # vorhandenen Skin bearbeiten: nur das Angegebene ändern
        sk.img = basis_laden(r["basis"])
        sk.px = sk.img.load()
        vorher = sk.img.copy().load()
        umfaerben(sk, r.get("umfaerben"))
        for d in r.get("details") or []:
            try:
                sk.rechteck(d["teil"], d.get("seite", "front"), int(d.get("x", 0)), int(d.get("y", 0)), int(d.get("w", 1)),
                            int(d.get("h", 1)), rgb(d["farbe"]), d.get("ebene", "basis"))
            except Exception:
                pass
        pixel_malen(sk, r.get("pixel"))
        if not r.get("nur_basis"):
            overlay_mitziehen(sk, vorher)
        if not r.get("flach"):
            tiefe(sk)
        if r.get("schatten", False):
            sk.schattieren(r.get("name", "skin"))
        return sk.img
    haut = rgb(r.get("haut", "#c68e6a"))
    for t in TEILE:
        sk.ganz(t, haut)
    # Gesicht
    weiss, auge = (240, 240, 240), rgb(r.get("augen", "#2a5bd7"))
    for x, c in ((1, weiss), (2, auge), (5, auge), (6, weiss)):
        sk.rechteck("kopf", "front", x, 4, 1, 1, c)
    if r.get("mund", True):
        sk.rechteck("kopf", "front", 3, 6, 2, 1, mischen(haut, 0.72))
    sk.rechteck("kopf", "front", 3, 5, 2, 1, mischen(haut, 0.9))   # Nase angedeutet
    # Haare
    ha = r.get("haare") or {}
    stil = ha.get("stil", "kurz")
    if ha and stil != "glatze":
        hf = rgb(ha.get("farbe", "#3b2516"))
        if stil == "irokese":
            sk.rechteck("kopf", "top", 3, 0, 2, 8, hf)
            sk.rechteck("kopf", "back", 3, 0, 2, 4, hf)
            sk.rechteck("kopf", "front", 3, 0, 2, 1, hf)
        else:
            sk.rechteck("kopf", "top", 0, 0, 8, 8, hf)
            sk.rechteck("kopf", "front", 0, 0, 8, 2, hf)
            sk.rechteck("kopf", "front", 0, 2, 1, 1, hf)
            sk.rechteck("kopf", "front", 7, 2, 1, 1, hf)
            lang = stil in ("lang", "zopf")
            sk.rechteck("kopf", "back", 0, 0, 8, 8 if lang else 4, hf)
            for s in ("left", "right"):
                sk.rechteck("kopf", s, 0, 0, 8, 8 if lang else 3, hf)
            if lang:
                for s in ("left", "right"):
                    sk.rechteck("kopf", s, 6 if s == "right" else 0, 3, 2, 5, haut)   # Gesichtsseite frei
            if stil == "zopf":
                sk.rechteck("koerper", "back", 3, 0, 2, 5, hf)
        sk.rechteck("kopf", "front", 1, 3, 2, 1, mischen(hf, 0.85))   # Augenbrauen
        sk.rechteck("kopf", "front", 5, 3, 2, 1, mischen(hf, 0.85))
    if r.get("bart"):
        bf = rgb(r["bart"])
        sk.rechteck("kopf", "front", 0, 5, 8, 3, bf)
        sk.rechteck("kopf", "front", 3, 6, 2, 1, mischen(bf, 0.7))
        for s in ("left", "right"):
            sk.rechteck("kopf", s, 0 if s == "right" else 4, 5, 4, 3, bf)
    # Oberteil
    ob = r.get("oberteil") or {"farbe": "#3a7bd5"}
    of, ak = rgb(ob.get("farbe", "#3a7bd5")), rgb(ob.get("akzent", "#ffffff"))
    sk.zeilen("koerper", 0, 11, of, oben=True, unten=True)
    aermel = 11 if ob.get("aermel", "lang") == "lang" else 3
    for a in ("arm_r", "arm_l"):
        sk.zeilen(a, 0, aermel, of, oben=True)
    st, mu = ob.get("stil", "tshirt"), ob.get("muster", "keins")
    if mu == "streifen":
        for y in range(1, 12, 3):
            sk.zeilen("koerper", y, y, ak)
            for a in ("arm_r", "arm_l"):
                if y <= aermel:
                    sk.zeilen(a, y, y, ak)
    elif mu == "karo":
        for t, h in (("koerper", 12), ("arm_r", aermel + 1), ("arm_l", aermel + 1)):
            for s in ("front", "back"):
                fx, fy, fw, fh = sk.flaechen(t)[s]
                for y in range(h):
                    for x in range(fw):
                        if (x // 2 + y // 2) % 2 == 0:
                            sk.rechteck(t, s, x, y, 1, 1, mischen(of, 0.8))
    elif mu == "verlauf":
        for y in range(12):
            sk.zeilen("koerper", y, y, mischen(of, 1.15 - y * 0.03))
    if st == "jacke":
        sk.rechteck("koerper", "front", 3, 0, 2, 12, mischen(of, 0.75))
        sk.rechteck("koerper", "front", 3, 0, 2, 12, ak, "overlay") if ob.get("akzent") else None
    elif st == "hoodie":
        sk.zeilen("kopf", 0, 99, of, "overlay", seiten=("back", "left", "right"), oben=True)
        sk.rechteck("kopf", "front", 0, 0, 8, 1, of, "overlay")
        sk.rechteck("koerper", "front", 2, 6, 4, 3, mischen(of, 0.85))   # Bauchtasche
        sk.rechteck("koerper", "front", 2, 0, 1, 4, ak)
        sk.rechteck("koerper", "front", 5, 0, 1, 4, ak)
    elif st == "anzug":
        sk.rechteck("koerper", "front", 2, 0, 4, 5, (235, 235, 235))
        sk.rechteck("koerper", "front", 3, 0, 2, 7, ak if ob.get("akzent") else (150, 20, 30))
    elif st == "ruestung":
        sk.zeilen("koerper", 0, 11, mischen(of, 1.05), "overlay", oben=True)
        sk.zeilen("koerper", 0, 0, ak, "overlay")
        sk.zeilen("koerper", 11, 11, ak, "overlay")
        sk.rechteck("koerper", "front", 3, 2, 2, 6, ak, "overlay")
        for a in ("arm_r", "arm_l"):
            sk.zeilen(a, 0, 3, mischen(of, 1.1), "overlay", oben=True)
            sk.zeilen(a, 3, 3, ak, "overlay")
    elif st == "pullover":
        sk.zeilen("koerper", 0, 0, mischen(of, 0.8))
    # Hose, Gürtel, Schuhe, Handschuhe
    ho = r.get("hose") or {"farbe": "#2c3e66"}
    hf2 = rgb(ho.get("farbe", "#2c3e66"))
    for b in ("bein_r", "bein_l"):
        sk.zeilen(b, 0, 8, hf2, oben=True)
        if ho.get("stil") == "ruestung":
            sk.zeilen(b, 0, 8, mischen(hf2, 1.08), "overlay")
            sk.zeilen(b, 4, 4, rgb(ob.get("akzent", "#cccccc")), "overlay")
    sf = rgb(r.get("schuhe", "#2a2a2a"))
    for b in ("bein_r", "bein_l"):
        sk.zeilen(b, 9, 11, sf, unten=True)
    if r.get("guertel"):
        gf = rgb(r["guertel"])
        sk.zeilen("koerper", 10, 10, gf)
        sk.rechteck("koerper", "front", 3, 10, 2, 1, rgb(ob.get("akzent", "#d4af37")))
    if r.get("handschuhe"):
        for a in ("arm_r", "arm_l"):
            sk.zeilen(a, 9, 11, rgb(r["handschuhe"]), unten=True)
    # Helm / Kopfbedeckung (Overlay)
    he = r.get("helm")
    if he:
        hc, hv = rgb(he.get("farbe", "#9aa3ad")), rgb(he.get("visier", "#151515"))
        s = he.get("stil", "ritter")
        if s == "ritter":
            sk.ganz("kopf", hc, "overlay")
            sk.rechteck("kopf", "front", 0, 0, 8, 8, hc, "overlay")
            sk.rechteck("kopf", "front", 1, 4, 6, 1, hv, "overlay")
            sk.rechteck("kopf", "front", 3, 5, 2, 3, mischen(hc, 0.8), "overlay")
            sk.rechteck("kopf", "top", 3, 0, 2, 8, mischen(hc, 1.15), "overlay")
        elif s == "kappe":
            sk.zeilen("kopf", 0, 1, hc, "overlay", oben=True)
            sk.rechteck("kopf", "front", 0, 2, 8, 1, mischen(hc, 0.8), "overlay")
        elif s == "krone":
            sk.zeilen("kopf", 0, 1, hc, "overlay")
            for x in (0, 2, 5, 7):
                sk.rechteck("kopf", "front", x, 0, 1, 1, (0, 0, 0, 0), "overlay")
            sk.rechteck("kopf", "front", 3, 1, 2, 1, hv if he.get("visier") else (200, 30, 40), "overlay")
        elif s == "kapuze":
            sk.zeilen("kopf", 0, 99, hc, "overlay", seiten=("back", "left", "right"), oben=True)
            sk.rechteck("kopf", "front", 0, 0, 8, 2, hc, "overlay")
            sk.rechteck("kopf", "front", 0, 0, 1, 8, hc, "overlay")
            sk.rechteck("kopf", "front", 7, 0, 1, 8, hc, "overlay")
    for d in r.get("details") or []:
        try:
            sk.rechteck(d["teil"], d.get("seite", "front"), int(d.get("x", 0)), int(d.get("y", 0)), int(d.get("w", 1)),
                        int(d.get("h", 1)), rgb(d["farbe"]), d.get("ebene", "basis"))
        except Exception:
            pass
    pixel_malen(sk, r.get("pixel"))
    umfaerben(sk, r.get("umfaerben"))
    if not r.get("flach"):
        tiefe(sk)
    if r.get("schatten", True):
        sk.schattieren(r.get("name", "skin"))
    return sk.img


def vorschau(img, slim=False):
    """Flache Vorder- und Rückansicht (für Launcher-Bild und Liste)."""
    sk = Skin(slim)
    out = Image.new("RGBA", (40, 34), (0, 0, 0, 0))

    def teil(t, s, x, y):
        for eb in ("basis", "overlay"):
            fx, fy, fw, fh = sk.flaechen(t, eb)[s]
            out.alpha_composite(img.crop((fx, fy, fx + fw, fy + fh)), (x, y))

    aw = 3 if slim else 4
    for ox, s, links, rechts in ((0, "front", "arm_r", "arm_l"), (20, "back", "arm_l", "arm_r")):
        teil("kopf", s, ox + aw, 1)
        teil("koerper", s, ox + aw, 9)
        teil(links, s, ox, 9)
        teil(rechts, s, ox + aw + 8, 9)
        teil("bein_r" if s == "front" else "bein_l", s, ox + aw, 21)
        teil("bein_l" if s == "front" else "bein_r", s, ox + aw + 4, 21)
    return out.resize((400, 340), Image.NEAREST)


def name_ok(n):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(n).replace(" ", "_"))[:60] or "skin"


def holo(namen):
    inhalt = [{"typ": "text", "text": ("Von links: " + ", ".join(str(i + 1) for i in range(len(namen))) + ". Sag „Nummer …“ – "
                                       "dann lege ich ihn in deinen Launcher.") if len(namen) > 1 else "Dein neuer Skin – sag „in den Launcher“."}]
    port = os.environ.get("ORB_PORT", "8766")
    inhalt += [{"typ": "web", "url": f"http://127.0.0.1:{port}/skin3d?n={n}", "reihe": len(namen) > 1} for n in namen]
    karte = {"id": "skins", "titel": "Skin-Designer", "groesse": "gross" if len(namen) > 1 else "mittel", "farbe": "lila", "inhalt": inhalt}
    pfad = os.path.join(tempfile.gettempdir(), "orb_skins.json")
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(karte, f, ensure_ascii=False)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "holo.ps1"), "-Json", pfad],
                   capture_output=True, creationflags=NO_WINDOW)


def launcher(n):
    pfad = os.path.join(ORDNER, n + ".png")
    if not os.path.exists(pfad):
        n = name_ok(n)
        pfad = os.path.join(ORDNER, n + ".png")
    meta = json.load(open(os.path.join(ORDNER, n + ".json"), encoding="utf-8")) if os.path.exists(os.path.join(ORDNER, n + ".json")) else {}
    img = Image.open(pfad)
    b64 = lambda im: "data:image/png;base64," + base64.b64encode((lambda b: (im.save(b, "PNG"), b.getvalue())[1])(io.BytesIO())).decode()
    try:
        d = json.load(open(LAUNCHER, encoding="utf-8"))
    except Exception:
        d = {"customSkins": {}, "version": 1}
    jetzt = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sid = "skin_" + str(uuid.uuid4())
    anzeige = meta.get("anzeige", n)
    d["customSkins"] = {k: v for k, v in d.get("customSkins", {}).items() if v.get("name") != anzeige}   # gleichnamige ersetzen statt doppeln
    d["customSkins"][sid] = {"created": jetzt, "id": sid, "modelImage": b64(vorschau(img, meta.get("modell") == "slim")),
                                            "name": anzeige, "skinImage": b64(img), "slim": meta.get("modell") == "slim",
                                            "textureId": "", "updated": jetzt}
    with open(LAUNCHER, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    laeuft = (subprocess.run(["tasklist", "/FI", "IMAGENAME eq MinecraftLauncher.exe"], capture_output=True, text=True,
                            encoding="oem", errors="ignore", creationflags=NO_WINDOW).stdout or "").count("MinecraftLauncher.exe") > 0
    return {"ok": True, "id": sid, "launcher_offen": laeuft,
            "hinweis": "Launcher läuft – bitte einmal schließen und neu öffnen, dann steht der Skin unter „Skins“." if laeuft
            else "Beim nächsten Öffnen des Launchers steht der Skin unter „Skins“ – anklicken und „Verwenden“."}


def main():
    os.makedirs(ORDNER, exist_ok=True)
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd = sys.argv[1]
    if cmd == "bauen":
        roh = sys.argv[2]
        daten = json.load(open(roh, encoding="utf-8")) if os.path.exists(roh) else json.loads(roh)
        rezepte = daten if isinstance(daten, list) else [daten]
        namen = []
        for i, r in enumerate(rezepte):
            n = name_ok(r.get("name", f"skin_{i + 1}"))
            img = bauen(r)
            img.save(os.path.join(ORDNER, n + ".png"))
            vorschau(img, r.get("modell") == "slim").save(os.path.join(ORDNER, n + "_vorschau.png"))
            with open(os.path.join(ORDNER, n + ".json"), "w", encoding="utf-8") as f:
                json.dump(dict(r, anzeige=r.get("anzeige") or r.get("name", n)), f, ensure_ascii=False)
            namen.append(n)
        with open(os.path.join(ORDNER, "letzte.json"), "w", encoding="utf-8") as f:
            json.dump(namen, f)
        holo(namen)
        print(json.dumps({"ok": True, "skins": namen, "ordner": ORDNER}, ensure_ascii=False))
    elif cmd == "launcher":
        if sys.argv[2] == "alle":   # alle Skins aus Bilder\Minecraft-Skins in den Launcher (auch selbst abgelegte PNGs)
            vorhanden = json.load(open(LAUNCHER, encoding="utf-8")).get("customSkins", {}) if os.path.exists(LAUNCHER) else {}
            namen_da = {v.get("name") for v in vorhanden.values()}
            neu = [f[:-4] for f in os.listdir(ORDNER) if f.lower().endswith(".png") and "_vorschau" not in f and f[:-4] not in namen_da]
            erg = [launcher(n) for n in neu]
            print(json.dumps({"ok": True, "hinzugefuegt": neu, "hinweis": erg[-1]["hinweis"] if erg else "nichts Neues"}, ensure_ascii=False))
        else:
            print(json.dumps(launcher(sys.argv[2]), ensure_ascii=False))
    elif cmd == "zeigen":   # vorhandene Skins (auch selbst abgelegte) als 3D-Hologramm
        namen = [os.path.splitext(n)[0] for n in sys.argv[2:]] or sorted(f[:-4] for f in os.listdir(ORDNER) if f.lower().endswith(".png") and "_vorschau" not in f)[:3]
        holo(namen)
        print(json.dumps({"ok": True, "skins": namen}, ensure_ascii=False))
    elif cmd == "vergleich":   # Vorschau mehrerer Skins nebeneinander (für ORBs Selbstkontrolle mit Read)
        namen = sys.argv[2:]
        bilder = [vorschau(basis_laden(n)) for n in namen]
        bild = Image.new("RGBA", (400 * len(bilder), 380), (28, 30, 40, 255))
        for i, b in enumerate(bilder):
            bild.alpha_composite(b, (i * 400, 30))
        ziel = os.path.join(tempfile.gettempdir(), "orb_skin_vergleich.png")
        bild.save(ziel)
        print(json.dumps({"ok": True, "bild": ziel, "reihenfolge": namen}, ensure_ascii=False))
    elif cmd == "tiefe":   # vorhandenen (z. B. KI-)Skins die 3D-Schicht geben – überschreibt die Datei
        for n in sys.argv[2:]:
            sk = Skin()
            sk.img = basis_laden(n)
            sk.px = sk.img.load()
            tiefe(sk)
            sk.img.save(os.path.join(ORDNER, os.path.splitext(os.path.basename(n))[0] + ".png"))
        print(json.dumps({"ok": True, "skins": sys.argv[2:]}, ensure_ascii=False))
    elif cmd == "liste":
        print(json.dumps(sorted(f[:-4] for f in os.listdir(ORDNER) if f.endswith(".png") and "_vorschau" not in f), ensure_ascii=False))


if __name__ == "__main__":
    main()
