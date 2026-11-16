"""ORB per Telegram: Larsen schreibt oder spricht dem Bot „Orb“ von unterwegs – ORB zu Hause erledigt es und antwortet
mit Text und Stimme. Nur Larsens eigener Chat wird bedient (chat_id fest in %LOCALAPPDATA%\\ORB\\telegram.json).

  telegram.json: {"token": "<BotFather-Token>", "chat_id": 123456789}
  Fehlt chat_id, wird der ERSTE Chat, der /start schickt, als Larsen gespeichert (danach ist der Bot für alle anderen taub).

Sprachnachrichten schreibt ORBs lokales Ohr mit (Whisper, POST http://127.0.0.1:8768/text). „/bild“ oder „Bildschirm“
schickt das aktuelle Live-Bild des PCs.
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

BASIS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ORB")
CFG = os.path.join(BASIS, "telegram.json")
LOG = os.path.join(BASIS, "telegram.log")
PORT = int(os.environ.get("ORB_PORT", "8766"))
ORB = "http://127.0.0.1:%d" % PORT
LIVE = os.path.join(BASIS, "screen", "live.png")
aktiv = {"t": 0.0}   # letzte Telegram-Nachricht: solange (15 Min.) gehen ORBs Antworten auch aufs Handy


def log(*x):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + " ".join(str(v) for v in x) + "\n")
    except Exception:
        pass


def cfg_laden():
    try:
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def cfg_speichern(c):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(c, f)


def token_orb():
    try:
        with open(os.path.join(BASIS, "token.txt" if PORT == 8766 else "token_%d.txt" % PORT)) as f:
            return f.read().strip()
    except Exception:
        return ""


def orb(pfad, daten=None, timeout=10):
    req = urllib.request.Request(ORB + pfad, data=json.dumps(daten).encode() if daten is not None else None,
                                 method="POST" if daten is not None else "GET",
                                 headers={"X-ORB-Token": token_orb(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def tg(token, methode, felder=None, datei=None, timeout=40):
    url = "https://api.telegram.org/bot%s/%s" % (token, methode)
    if datei:   # multipart (Foto/Sprachnachricht)
        feld, name, inhalt, typ = datei
        grenze = "----orb%d" % int(time.time() * 1000)
        teile = []
        for k, v in (felder or {}).items():
            teile.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (grenze, k, v)).encode())
        teile.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                      % (grenze, feld, name, typ)).encode() + inhalt + b"\r\n")
        teile.append(("--%s--\r\n" % grenze).encode())
        req = urllib.request.Request(url, data=b"".join(teile), headers={"Content-Type": "multipart/form-data; boundary=" + grenze})
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(felder or {}).encode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def antworten_weiterleiten(token, chat):
    """Jede fertige Antwort von ORB (auch spätere Ergebnisse von Hintergrund-Aufgaben) geht aufs Handy,
    solange Larsen in den letzten 15 Min. per Telegram geschrieben hat – als Text und mit ORBs Stimme."""
    zuletzt = None
    stat = {"id": None, "text": "", "t": 0.0}
    while True:
        time.sleep(1)
        try:
            st = json.loads(orb("/state?von=extern"))
        except Exception:
            continue
        if time.time() - aktiv["t"] < 900:
            try:
                status_melden(token, chat, st, stat)
            except Exception as e:
                log("Status:", e)
        kennung = (st.get("aid"), st.get("say"))
        if zuletzt is None:
            zuletzt = kennung
            continue
        if kennung == zuletzt or not st.get("final") or not st.get("say"):
            continue
        zuletzt = kennung
        if time.time() - aktiv["t"] > 900:
            continue
        text = st["say"]
        try:
            if stat["id"] and not laufende(st):   # Statusmeldung abschließen, Antwort kommt darunter
                try:
                    tg(token, "editMessageText", {"chat_id": chat, "message_id": stat["id"], "text": "✅ Erledigt"})
                except Exception:
                    pass
                stat.update(id=None, text="")
            tg(token, "sendMessage", {"chat_id": chat, "text": text})
            stimme = b""
            for i in range(len(st.get("parts") or [])):   # ORBs Sprech-Stücke (MP3) aneinanderhängen
                try:
                    stimme += orb("/tts?aid=%s&i=%d" % (urllib.parse.quote(str(st.get("aid"))), i), timeout=80)
                except Exception:
                    break
            if len(stimme) > 1000:
                tg(token, "sendVoice", {"chat_id": chat}, ("voice", "orb.mp3", stimme, "audio/mpeg"), timeout=60)
        except Exception as e:
            log("Antwort senden:", e)


def laufende(st):
    return [a for a in (st.get("aufgaben") or []) if a.get("status") == "laeuft"]


def status_melden(token, chat, st, stat):
    """Was ORB gerade tut (Gedanke/Werkzeug + Hintergrund-Aufgaben mit aktuellem Schritt) als EINE Nachricht,
    die laufend aktualisiert wird – statt Larsen mit vielen Nachrichten zu fluten."""
    zeilen = []
    if st.get("mode") in ("denkt", "auftrag"):
        was = (st.get("task") or "denkt nach").strip()
        if st.get("detail"):
            was += ": " + str(st["detail"]).strip()
        zeilen.append("⏳ ORB " + was[:200])
    for a in laufende(st):
        p = (" (%d %%)" % a["prozent"]) if a.get("prozent") else ""
        zeilen.append("🔧 %s%s – %s" % (a.get("titel", "Aufgabe"), p, (a.get("schritt") or "läuft")[:160]))
    text = chr(10).join(zeilen)
    if not text or text == stat["text"] or time.time() - stat["t"] < 3:
        return
    stat.update(text=text, t=time.time())
    if stat["id"]:
        try:
            tg(token, "editMessageText", {"chat_id": chat, "message_id": stat["id"], "text": text})
            return
        except Exception:
            pass
    r = tg(token, "sendMessage", {"chat_id": chat, "text": text, "disable_notification": "true"})
    stat["id"] = r.get("result", {}).get("message_id")


def sprache_zu_text(token, file_id):
    info = tg(token, "getFile", {"file_id": file_id})
    pfad = info["result"]["file_path"]
    with urllib.request.urlopen("https://api.telegram.org/file/bot%s/%s" % (token, pfad), timeout=60) as r:
        audio = r.read()
    req = urllib.request.Request("http://127.0.0.1:8768/text", data=audio, headers={"X-ORB-Token": token_orb()})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode()).get("text", "")


def main():
    log("Telegram-Brücke gestartet")
    gestartet = False
    offset = 0
    while True:
        c = cfg_laden()
        token = c.get("token")
        if not token:
            time.sleep(30)
            continue
        chat = c.get("chat_id")
        if chat and not gestartet:
            threading.Thread(target=antworten_weiterleiten, args=(token, chat), daemon=True).start()
            gestartet = True
        try:
            r = tg(token, "getUpdates", {"offset": offset, "timeout": 30}, timeout=45)
        except Exception as e:
            log("getUpdates:", e)
            time.sleep(5)
            continue
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            cid = (m.get("chat") or {}).get("id")
            if not cid:
                continue
            if not chat:   # erster Kontakt: diesen Chat als Larsen festlegen
                if (m.get("text") or "").startswith("/start"):
                    c["chat_id"] = chat = cid
                    cfg_speichern(c)
                    log("Chat festgelegt:", cid)
                    tg(token, "sendMessage", {"chat_id": cid, "text": "Hi Larsen, ich bin ORB. Schreib oder sprich mir einfach – ich erledige es zu Hause am PC."})
                    threading.Thread(target=antworten_weiterleiten, args=(token, chat), daemon=True).start()
                    gestartet = True
                continue
            if cid != chat:
                log("Fremder Chat ignoriert:", cid)
                continue
            try:
                text = (m.get("text") or m.get("caption") or "").strip()
                if m.get("voice") or m.get("audio"):
                    tg(token, "sendChatAction", {"chat_id": chat, "action": "typing"})
                    text = sprache_zu_text(token, (m.get("voice") or m.get("audio"))["file_id"])
                    tg(token, "sendMessage", {"chat_id": chat, "text": "🎙 " + (text or "(nichts verstanden)")})
                if not text or text == "/start":
                    continue
                if text.startswith("/bild") or re.search(r"(?i)\b(screenshot|bildschirm(foto)?)\b", text) and len(text) < 40:
                    with open(LIVE, "rb") as f:
                        tg(token, "sendPhoto", {"chat_id": chat}, ("photo", "bildschirm.png", f.read(), "image/png"), timeout=60)
                    continue
                aktiv["t"] = time.time()
                tg(token, "sendChatAction", {"chat_id": chat, "action": "typing"})
                orb("/ask", {"text": "[Per Telegram vom Handy – Larsen ist nicht am PC; Antwort geht aufs Handy] " + text, "getippt": True})
            except Exception as e:
                log("Nachricht:", e)
                try:
                    tg(token, "sendMessage", {"chat_id": chat, "text": "ORB ist gerade nicht erreichbar (%s)." % type(e).__name__})
                except Exception:
                    pass


def senden(pfad, text=""):
    """Für ORB: Datei/Bild/Video aufs Handy schicken –  py -3 telegram_orb.py senden <pfad> ["Begleittext"]"""
    import mimetypes
    c = cfg_laden()
    typ = mimetypes.guess_type(pfad)[0] or "application/octet-stream"
    methode, feld = ("sendPhoto", "photo") if typ.startswith("image/") and not pfad.lower().endswith(".gif") else         ("sendVideo", "video") if typ.startswith("video/") else ("sendAudio", "audio") if typ.startswith("audio/") else ("sendDocument", "document")
    with open(pfad, "rb") as f:
        r = tg(c["token"], methode, {"chat_id": c["chat_id"], "caption": text[:1000]}, (feld, os.path.basename(pfad), f.read(), typ), timeout=180)
    print("ok" if r.get("ok") else r)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "senden":
        senden(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
        raise SystemExit
    while True:
        try:
            main()
        except Exception as e:
            log("Absturz, Neustart in 10 s:", e)
            time.sleep(10)
