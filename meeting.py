"""„Mach mich ins Meeting“: KATI-Online-Seminar betreten – stumm und ohne Kamera, Teilnahme erbitten.

  py -3 meeting.py            (ORB ruft das auf; Opera-GX-Fenster bleibt danach offen)

Ablauf: kati-bst.de → Einloggen → Kurs „K2609-34a-O-AK 28.09.2026 - 18.12.2026“ → Online-Seminar → im Vorschau-Feld
Mikrofon und Kamera aus → „Teilnahme erbitten“. Eigenes Edge-Profil (%LOCALAPPDATA%\\ORB\\meeting-profil): beim ersten Mal
loggt Larsen sich dort selbst ein (ORB tippt nie Passwörter) – danach bleibt er angemeldet.
Ergebnis als JSON-Zeile; bei einem Problem mit Schritt, Grund und Screenshot (für ORBs Bildschirm-Hilfe).
"""
import json
import os
import re
import subprocess
import sys
import time

URL = "https://kati-bst.de"
KURS = "K2609-34a-O-AK"
PORT = 9334
PROFIL = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "meeting-opera")   # eigenes Opera-GX-Profil (bleibt eingeloggt)
LOG = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "meeting.log")
# Larsens Browser: immer Opera GX
OPERA = next((p for p in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Opera GX", "opera.exe"),
                          os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Opera GX", "launcher.exe")) if os.path.exists(p)), "opera")


def log(*x):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + " ".join(str(v) for v in x) + "\n")


def ende(ok, **kw):
    print(json.dumps(dict(ok=ok, **kw), ensure_ascii=False))
    sys.exit(0)


def opera_starten():
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
        return False   # läuft schon
    except Exception:
        pass
    os.makedirs(PROFIL, exist_ok=True)
    subprocess.Popen([OPERA, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFIL}", "--start-maximized",
                      "--no-first-run", "--no-default-browser-check", URL])
    for _ in range(40):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
            return True
        except Exception:
            pass
    ende(False, schritt="Opera GX starten", grund="Opera-GX-Fenster ließ sich nicht öffnen")


def klick_text(seite, muster, timeout=15):
    """Sichtbares Element (Link/Knopf/Zeile) mit passendem Text klicken. Gibt den Klick-Ort zurück oder None."""
    rx = re.compile(muster, re.I)
    ende_t = time.time() + timeout
    while time.time() < ende_t:
        for frame in seite.frames:
            for sel in ("button", "a", "[role=button]", "input[type=submit]", "input[type=button]", "td", "li", "div", "span"):
                try:
                    loc = frame.locator(sel).filter(has_text=rx) if not sel.startswith("input") else frame.locator(sel)
                    n = min(loc.count(), 30)
                    for i in range(n):
                        el = loc.nth(i)
                        if sel.startswith("input"):
                            if not rx.search(el.get_attribute("value") or ""):
                                continue
                        if el.is_visible():
                            el.click(timeout=3000)
                            return True
                except Exception:
                    continue
        time.sleep(0.6)
    return False


def schalter_aus(seite, art):
    """Mikrofon bzw. Kamera im Vorschau-Feld ausschalten – nur klicken, wenn es gerade AN ist."""
    an = {"mikro": r"mikro|microphone|audio|stumm|mute", "kamera": r"kamera|camera|video|webcam"}[art]
    schon_aus = r"aufheben|einschalten|aktivieren|starten|unmute|turn on|start|enable|ist aus|off\b"
    for frame in seite.frames:
        try:
            knoepfe = frame.locator("button, [role=button], [role=switch], input[type=checkbox]")
            for i in range(min(knoepfe.count(), 80)):
                k = knoepfe.nth(i)
                if not k.is_visible():
                    continue
                text = " ".join(filter(None, [k.get_attribute("aria-label"), k.get_attribute("title"),
                                              k.get_attribute("data-tooltip"), (k.inner_text(timeout=500) or "")[:60]]))
                if not re.search(an, text, re.I):
                    continue
                gedrueckt = k.get_attribute("aria-pressed") or k.get_attribute("aria-checked")
                if gedrueckt == "false" and re.search(r"stumm|mute", text, re.I):
                    k.click(timeout=3000); return "geklickt (" + text[:40] + ")"
                if re.search(schon_aus, text, re.I) or gedrueckt == "false":
                    return "war schon aus (" + text[:40] + ")"
                k.click(timeout=3000)
                return "ausgeschaltet (" + text[:40] + ")"
        except Exception:
            continue
    return None


def knoepfe_protokollieren(seite):
    for frame in seite.frames:
        try:
            k = frame.locator("button, [role=button], a")
            for i in range(min(k.count(), 60)):
                e = k.nth(i)
                if e.is_visible():
                    log("  Knopf:", (e.get_attribute("aria-label") or "") + " | " + (e.inner_text(timeout=300) or "")[:50].replace("\n", " "))
        except Exception:
            pass


def main():
    from playwright.sync_api import sync_playwright
    neu = opera_starten()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        ctx = browser.contexts[0]
        try:
            ctx.grant_permissions(["microphone", "camera"], origin=URL)
        except Exception:
            pass
        seite = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not neu:
            seite.goto(URL)
        seite.bring_to_front()
        seite.wait_for_load_state("domcontentloaded")
        shot = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "screen", "meeting.png")
        os.makedirs(os.path.dirname(shot), exist_ok=True)

        # 1) Einloggen (falls nicht schon angemeldet)
        if seite.get_by_text(KURS).count() == 0:   # noch nicht im Kursbereich
            klick_text(seite, r"^\s*(einloggen|login|anmelden)\s*$", 8)
            seite.wait_for_load_state("domcontentloaded")
        # angemeldet? Sonst auf Larsens Login warten (Passwort tippt er selbst)
        t0 = time.time()
        while seite.get_by_text(KURS).count() == 0 and time.time() - t0 < 150:
            if time.time() - t0 < 2:
                log("Warte auf Login …")
            time.sleep(1)
            if seite.get_by_text(re.compile(r"einloggen|login", re.I)).count() == 0 and seite.get_by_text(KURS).count() == 0:
                klick_text(seite, r"kurse|meine kurse|dashboard|übersicht", 2)
        if seite.get_by_text(KURS).count() == 0:
            seite.screenshot(path=shot)
            ende(False, schritt="Login", grund="Kurs nicht gefunden – bitte im Opera-GX-Fenster einmal einloggen (angemeldet bleiben), dann nochmal",
                 screenshot=shot, erster_login=True)
        # 2) Kurs öffnen
        if not klick_text(seite, re.escape(KURS), 15):
            seite.screenshot(path=shot)
            ende(False, schritt="Kurs", grund="Kurs K2609-34a-O-AK nicht anklickbar", screenshot=shot)
        seite.wait_for_load_state("domcontentloaded")
        # 3) Online-Seminar (öffnet evtl. einen neuen Tab)
        vorher = len(ctx.pages)
        if not klick_text(seite, r"online[- ]?seminar", 20):
            seite.screenshot(path=shot)
            ende(False, schritt="Online-Seminar", grund="Knopf „Online-Seminar“ nicht gefunden", screenshot=shot)
        time.sleep(3)
        if len(ctx.pages) > vorher:
            seite = ctx.pages[-1]
            seite.bring_to_front()
        seite.wait_for_load_state("domcontentloaded")
        time.sleep(4)   # Vorschau mit Kamera/Mikro baut sich auf
        knoepfe_protokollieren(seite)
        # 4) stumm + Kamera aus im großen Vorschau-Feld
        mikro = schalter_aus(seite, "mikro")
        kamera = schalter_aus(seite, "kamera")
        log("Mikro:", mikro, "| Kamera:", kamera)
        time.sleep(1)
        # 5) Teilnahme erbitten
        if not klick_text(seite, r"teilnahme\s+erbitten|teilnahme\s+anfragen|beitritt\s+(erbitten|anfragen)|ask to join", 20):
            seite.screenshot(path=shot)
            ende(False, schritt="Teilnahme erbitten", grund="Knopf nicht gefunden", mikro=mikro, kamera=kamera, screenshot=shot)
        time.sleep(2)
        seite.screenshot(path=shot)
        ende(True, mikro=mikro or "Knopf nicht gefunden – bitte prüfen", kamera=kamera or "Knopf nicht gefunden – bitte prüfen",
             screenshot=shot)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log("Fehler:", e)
        ende(False, schritt="unbekannt", grund=str(e)[:200])
