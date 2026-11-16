"""„Mach mich ins Meeting“: KATI-Online-Seminar in Larsens EIGENEM Opera GX betreten – stumm, ohne Kamera, Teilnahme erbitten.

  py -3 meeting.py            (ORB ruft das auf)          py -3 meeting.py --probe   (alles bis vor „Teilnahme erbitten“)

Steuert Opera über die Windows-Barrierefreiheit (UI Automation) – wie ein Screenreader: Knöpfe werden per Name gefunden
und ausgelöst, Larsens normales Opera-Profil bleibt, kein Fernsteuer-Port.
Ablauf: kati-bst.de → Einloggen (Zugang lokal in %LOCALAPPDATA%\\ORB\\meeting_login.json) → Kurs K2609-34a-O-AK →
„Zum Online-Seminar“ (Google Meet) → Mikrofon aus, Kamera aus → „Teilnahme erbitten“.
"""
import json
import os
import re
import subprocess
import sys
import time

URL = "https://kati-bst.de"
KURS = "K2609-34a-O-AK"
PROBE = "--probe" in sys.argv
OPERA = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Opera GX", "opera.exe")
LOG = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "meeting.log")
SHOT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "screen", "meeting.png")


def log(*x):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + " ".join(str(v) for v in x) + "\n")


def ende(ok, **kw):
    try:
        from PIL import ImageGrab
        os.makedirs(os.path.dirname(SHOT), exist_ok=True)
        ImageGrab.grab().save(SHOT)   # Screenshot für ORB (bei Problemen ansehen)
        kw.setdefault("screenshot", SHOT)
    except Exception:
        pass
    print(json.dumps(dict(ok=ok, **kw), ensure_ascii=False))
    sys.exit(0)


def zugang():
    try:
        with open(os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB", "meeting_login.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def opera_fenster(auto, titel, timeout=25):
    """Opera-Fenster finden, dessen aktiver Tab `titel` im Namen hat."""
    t = time.time()
    while time.time() - t < timeout:
        for w in auto.GetRootControl().GetChildren():
            if w.ClassName.startswith("Chrome_WidgetWin") and "Opera" in (w.Name or "") and re.search(titel, w.Name or "", re.I):
                return w
        time.sleep(0.5)
    return None


def dokument(auto, w, titel, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        d = w.DocumentControl(searchDepth=30, RegexName=titel)
        if d.Exists(1):
            return d
    return None


def finde(doc, muster, typen=("ButtonControl", "HyperlinkControl"), timeout=15):
    t = time.time()
    while time.time() - t < timeout:
        for ty in typen:
            c = getattr(doc, ty)(searchDepth=45, RegexName=muster)
            if c.Exists(0.5):
                return c
    return None


def ausloesen(c):
    """Element auslösen: erst Barrierefreiheits-Aktion (ohne Maus), sonst echter Klick."""
    try:
        c.GetInvokePattern().Invoke()
        return
    except Exception:
        pass
    try:
        c.GetLegacyIAccessiblePattern().DoDefaultAction()
        return
    except Exception:
        pass
    c.Click(simulateMove=False)


def main():
    import uiautomation as auto
    auto.SetGlobalSearchTimeout(2)
    subprocess.Popen([OPERA, URL])   # KATI in Larsens Opera öffnen (neuer Tab bzw. Opera startet)
    w = opera_fenster(auto, r"KATI")
    if not w:
        ende(False, schritt="Opera", grund="KATI-Tab in Opera GX nicht gefunden")
    w.SetActive()
    doc = dokument(auto, w, r"KATI")
    if not doc:
        ende(False, schritt="Seite", grund="KATI-Seite lädt nicht")
    # 1) Einloggen (falls nötig)
    knopf = finde(doc, r"(?i)^\s*einloggen\s*$", timeout=4)
    if knopf:
        ausloesen(knopf)
        time.sleep(2.5)
        doc = dokument(auto, w, r"KATI") or doc
        z = zugang()
        mail_feld = doc.EditControl(searchDepth=45, RegexName=r"(?i)mail|benutzer|login")
        pw_feld = doc.EditControl(searchDepth=45, RegexName=r"(?i)passwort|password")
        vorausgefuellt = False
        try:
            vorausgefuellt = bool(mail_feld.Exists(8) and (mail_feld.GetValuePattern().Value or "").strip())
        except Exception:
            pass
        if vorausgefuellt:   # Opera hat die Anmeldedaten schon eingetragen → nur abschicken
            time.sleep(0.8)
            w.SetActive()
            pw_feld.SetFocus()
            time.sleep(0.3)
            auto.SendKeys("{Enter}")
            time.sleep(3.5)
            doc = dokument(auto, w, r"KATI") or doc
            if not doc.EditControl(searchDepth=45, RegexName=r"(?i)passwort|password").Exists(1.5):
                log("Eingeloggt mit Operas gespeicherten Daten")
                z = {}   # Ersatz-Zugang nicht mehr nötig
        if z and mail_feld.Exists(2) and pw_feld.Exists(3) and z.get("passwort"):
            for mail in [z.get("email_alt"), z.get("email")]:
                if not mail:
                    continue
                mail_feld.GetValuePattern().SetValue(mail)
                pw_feld.GetValuePattern().SetValue(z["passwort"])
                w.SetActive()
                pw_feld.SetFocus()   # Absenden per echter Enter-Taste (der Knopf reagiert nicht auf Barrierefreiheits-Klick)
                time.sleep(0.3)
                auto.SendKeys("{Enter}")
                time.sleep(3.5)
                doc = dokument(auto, w, r"KATI") or doc
                if not doc.EditControl(searchDepth=45, RegexName=r"(?i)passwort|password").Exists(1.5):
                    log("Eingeloggt mit", mail)
                    break
        else:
            log("Login-Felder nicht gefunden")
    # 2) Kurs
    kurs = finde(doc, ".*" + re.escape(KURS) + ".*", ("HyperlinkControl", "ButtonControl", "TextControl", "ListItemControl", "DataItemControl"), 15)
    if not kurs:
        ende(False, schritt="Kurs", grund="Kurs K2609-34a-O-AK nicht gefunden (Login prüfen)")
    ausloesen(kurs)
    time.sleep(3)
    doc = dokument(auto, w, r"KATI") or doc
    # 3) Zum Online-Seminar → Google Meet öffnet sich als neuer Tab
    seminar = finde(doc, r"(?i)zum\s+online[- ]?seminar", timeout=15)
    if not seminar:
        ende(False, schritt="Online-Seminar", grund="Knopf „Zum Online-Seminar“ nicht gefunden")
    ausloesen(seminar)
    mw = opera_fenster(auto, r"Meet", 30)
    if not mw:
        ende(False, schritt="Google Meet", grund="Meet-Tab hat sich nicht geöffnet")
    mw.SetActive()
    meet = dokument(auto, mw, r"Meet", 30)
    if not meet:
        ende(False, schritt="Google Meet", grund="Meet-Seite lädt nicht")
    # 4) Mikrofon und Kamera aus – nur wenn an; danach prüfen
    for teil in ("Mikrofon", "Kamera"):
        an = finde(meet, rf"(?i)^{teil} deaktivieren", ("ButtonControl",), 12)
        if an:
            ausloesen(an)
            time.sleep(1)
    noch_an = [t for t in ("Mikrofon", "Kamera") if finde(meet, rf"(?i)^{t} deaktivieren", ("ButtonControl",), 1.5)]
    if noch_an:
        ende(False, schritt="Mikro/Kamera", grund=" und ".join(noch_an) + " ließ sich nicht ausschalten – NICHT beigetreten")
    log("Mikrofon und Kamera aus")
    # Name (nur als Gast nötig), Hinweis „Mit Google-Konto anmelden“ wegklicken
    try:
        ok = meet.ButtonControl(searchDepth=45, Name="Ok")
        if ok.Exists(1):
            ausloesen(ok)
        name = meet.EditControl(searchDepth=45)
        if name.Exists(1) and not (name.GetValuePattern().Value or "").strip():
            name.GetValuePattern().SetValue("Larsen Hanna")
    except Exception:
        pass
    if PROBE:
        ende(True, probe=True, hinweis="Probelauf: stumm und ohne Kamera, Teilnahme NICHT erbeten")
    # 5) Teilnahme erbitten (bzw. „Jetzt teilnehmen“, wenn bei Google angemeldet)
    join = finde(meet, r"(?i)^(teilnahme erbitten|jetzt teilnehmen|ask to join|join now)", ("ButtonControl",), 15)
    if not join:
        ende(False, schritt="Teilnahme erbitten", grund="Knopf nicht gefunden")
    ausloesen(join)
    time.sleep(3)
    ende(True, mikro="aus", kamera="aus")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log("Fehler:", e)
        ende(False, schritt="unbekannt", grund=str(e)[:200])
