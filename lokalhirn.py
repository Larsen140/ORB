"""ORB – lokales Gehirn (inspiriert von OpenJarvis: local-first, Cloud nur wenn nötig).

- Antwortet mit einem Sprachmodell auf Larsens Grafikkarte (Ollama, qwen3:8b) – gratis, schnell, offline.
- Kennt Larsens Second Brain: durchsucht den Jarvis-Ordner (inkl. gehirn/ mit allen Chats, Projekten, ORB-Daten)
  per Vektor-Suche (nomic-embed-text) und antwortet mit diesem Wissen.
- Ist eine Aufgabe zu schwer (PC-Aktionen, Internet, Code, Nachrichten senden …), gibt es an Claude weiter.
- Dauer-Beobachter: behält Webseiten, Gold, Krypto oder Wetter im Blick und meldet sich, wenn die Bedingung eintritt.
Nur Standardbibliothek (ORB.exe enthält kein numpy).
"""
import array, datetime, hashlib, json, math, os, re, threading, time, urllib.request

OLLAMA = "http://127.0.0.1:11434"
MODELL = "qwen3:4b-instruct"                          # passt neben Design + Whisper in die 8 GB der RTX 4060
EMBED = "nomic-embed-text"
DIM = 256                                    # Matryoshka-Kürzung: schnell genug für reines Python
BASIS = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB")
INDEX_META = os.path.join(BASIS, "hirn_index.json")
INDEX_VEC = os.path.join(BASIS, "hirn_index.bin")
BEOB_DATEI = os.path.join(BASIS, "beobachter.json")
VAULT = os.path.join(os.path.expanduser("~"), "Documents", "Jarvis")
_lock = threading.Lock()
_index = {"chunks": [], "vec": array.array("f"), "dateien": {}}
VERLAUF = []                                 # letzte lokale Wortwechsel (kurzes Gedächtnis)


# ---------------- Ollama ----------------
def _post(pfad, daten, frist=60):
    req = urllib.request.Request(OLLAMA + pfad, data=json.dumps(daten).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=frist) as r:
        return json.loads(r.read().decode("utf-8"))


def auf_gpu():
    """Läuft das Modell (falls geladen) wirklich auf der Grafikkarte? Auf der CPU wäre es viel zu langsam."""
    try:
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=2) as r:
            for m in json.loads(r.read().decode("utf-8")).get("models", []):
                if m.get("name", "").startswith(MODELL):
                    return m.get("size_vram", 0) >= .85 * max(1, m.get("size", 1))
        return True   # noch nicht geladen → lädt gleich auf die Grafikkarte
    except Exception:
        return False


def vorwaermen():
    """Modell auf die Grafikkarte laden, damit die erste Frage nicht wartet. Hängt es auf der CPU fest: entladen, neu laden."""
    try:
        if not auf_gpu():
            _post("/api/generate", {"model": MODELL, "prompt": "", "keep_alive": 0}, frist=30)
            time.sleep(2)
        _post("/api/generate", {"model": MODELL, "prompt": "", "keep_alive": "30m", "options": {"num_ctx": 4096}}, frist=60)
    except Exception:
        pass


def verfuegbar():
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=2) as r:
            namen = [m.get("name", "") for m in json.loads(r.read().decode("utf-8")).get("models", [])]
        return any(n.startswith(MODELL) for n in namen), any(n.startswith(EMBED) for n in namen)
    except Exception:
        return False, False


def _embed(texte, praefix):
    out = _post("/api/embed", {"model": EMBED, "input": [praefix + t for t in texte], "keep_alive": "30m"}, frist=180)
    res = []
    for v in out.get("embeddings", []):
        v = v[:DIM]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        res.append([x / n for x in v])
    return res


# ---------------- Second Brain: Index ----------------
def _stuecke(pfad, text):
    rel = os.path.relpath(pfad, VAULT).replace("\\", "/")
    titel = rel[:-3]
    teile = re.split(r"(?m)^(#{1,3} .+)$", text)
    kopf, out, cur = titel, [], ""
    for t in teile:
        if re.match(r"#{1,3} ", t):
            if cur.strip():
                out.append((kopf, cur.strip()))
            kopf, cur = titel + " › " + t.lstrip("# ").strip(), ""
        else:
            cur += t
    if cur.strip():
        out.append((kopf, cur.strip()))
    fertig = []
    koepfe = [k.strip() for k in re.findall(r"(?m)^## (.+)$", text)]
    if len(koepfe) > 2:   # Übersicht je Datei – beantwortet „Welche … habe ich?“-Fragen vollständig
        name = rel.split("/")[-1][:-3]
        liste = "; ".join(koepfe)
        for i in range(0, len(liste), 1500):
            fertig.append({"q": rel, "t": "Liste aller %s-Einträge (%d Stück)" % (name, len(koepfe)), "x": "Alle %s: %s" % (name, liste[i:i + 1500])})
    for k, c in out:
        for i in range(0, len(c), 900):
            fertig.append({"q": rel, "t": k[:160], "x": c[i:i + 900]})
    return fertig


def index_aktualisieren(log=print):
    """Neue/geänderte Dateien im Jarvis-Ordner einbetten (inkrementell). Läuft im Hintergrund."""
    _, hat_embed = verfuegbar()
    if not hat_embed:
        return False
    os.makedirs(BASIS, exist_ok=True)
    with _lock:
        if not _index["chunks"] and os.path.exists(INDEX_META):
            try:
                m = json.load(open(INDEX_META, encoding="utf-8"))
                v = array.array("f")
                with open(INDEX_VEC, "rb") as f:
                    v.frombytes(f.read())
                if len(v) == len(m["chunks"]) * DIM:
                    _index.update(chunks=m["chunks"], vec=v, dateien=m["dateien"])
            except Exception:
                pass
        dateien, aktuell = {}, set()
        for wurzel, ordner, namen in os.walk(VAULT):
            ordner[:] = [o for o in ordner if not o.startswith(".")]
            for n in namen:
                if n.endswith(".md"):
                    p = os.path.join(wurzel, n)
                    aktuell.add(p)
                    dateien[p] = int(os.path.getmtime(p))
        neu = [p for p, mt in dateien.items() if _index["dateien"].get(p) != mt]
        weg = [p for p in _index["dateien"] if p not in aktuell]
        if not neu and not weg:
            return True
        raus = {os.path.relpath(p, VAULT).replace("\\", "/") for p in neu + weg}
        behalten = [i for i, c in enumerate(_index["chunks"]) if c["q"] not in raus]
        chunks = [_index["chunks"][i] for i in behalten]
        vec = array.array("f")
        for i in behalten:
            vec.extend(_index["vec"][i * DIM:(i + 1) * DIM])
    hinzu = []
    for p in neu:
        try:
            hinzu += _stuecke(p, open(p, encoding="utf-8", errors="replace").read())
        except OSError:
            pass
    for i in range(0, len(hinzu), 64):
        teil = hinzu[i:i + 64]
        try:
            for v in _embed([c["t"] + "\n" + c["x"] for c in teil], "search_document: "):
                vec.extend(v)
            chunks += teil
        except Exception as e:
            log("Hirn-Index:", e)
            return False
    with _lock:
        _index.update(chunks=chunks, vec=vec, dateien=dateien)
        json.dump({"chunks": chunks, "dateien": dateien}, open(INDEX_META, "w", encoding="utf-8"), ensure_ascii=False)
        with open(INDEX_VEC, "wb") as f:
            f.write(vec.tobytes())
    log("Hirn-Index: %d Abschnitte (%d neu/geändert)" % (len(chunks), len(neu)))
    return True


def suchen(frage, k=8):
    with _lock:
        chunks, vec = _index["chunks"], _index["vec"]
    if not chunks:
        return []
    try:
        q = _embed([frage], "search_query: ")[0]
    except Exception:
        return []
    import operator
    mul = operator.mul
    allgemein = {"claude", "jarvis", "habe", "hast", "gemacht", "thema", "mein", "meine", "meinen", "meiner", "welche",
                 "heißen", "heisst", "heißt", "zum", "über", "eigentlich", "gestern", "heute", "kannst", "wieso", "warum"}
    woerter = {w.rstrip("s") for w in re.findall(r"[a-zäöüß0-9]{4,}", frage.lower()) if w not in allgemein and w.rstrip("s") not in allgemein}
    def bonus(c):   # Stichwort-Verstärkung: Dateiname passt → dessen Wissen (vor allem die Übersicht) zählt mehr
        datei = c["q"].lower().rsplit("/", 1)[-1][:-3]
        b = .12 if any(w and (w in datei or datei in w) for w in woerter) else 0.0
        if b and c["t"].startswith("Liste aller"):
            b += .12
        return b
    werte = [(sum(map(mul, q, vec[i * DIM:(i + 1) * DIM])) + bonus(chunks[i]), i) for i in range(len(chunks))]
    werte.sort(reverse=True)
    return [chunks[i] for s, i in werte[:k] if s > .45]


# ---------------- Antworten ----------------
ACTION_RE = re.compile(r"\b(öffne|starte|schließ|schreib|erstell|bau|programmier|code|lösch|schick|send|installier|änder|"
                       r"kauf|verkauf|such (im|in|nach)|google|recherch|spiel|stell|setz|erinner|termin|notier|merk dir|"
                       r"mach (mir|ein|eine|den|die|das)|zeig|schau|guck|mail|whatsapp|nachricht|bild|foto|video|screenshot|"
                       r"aktualis|update|lade|download|kopier|verschieb|räum|klick|tipp|drück|lautstärke|leiser|lauter|"
                       r"news|nachrichten|kurs|preis|wetter|heute abend|morgen früh|bildschirm|fenster|trading|order)\b", re.I)


def _persoenlichkeit():
    try:
        return open(os.path.join(VAULT, "persoenlichkeit.md"), encoding="utf-8").read()[:1500]
    except OSError:
        return ""


def antworten(frage):
    """Gibt eine kurze Antwort zurück – oder None, wenn Claude übernehmen soll."""
    hat_modell, _ = verfuegbar()
    if not hat_modell or ACTION_RE.search(frage) or len(frage) > 400 or not auf_gpu():
        return None
    wissen = suchen(frage)
    kontext = "\n\n".join("[%s]\n%s" % (c["t"], c["x"]) for c in wissen) or "(nichts Passendes gefunden)"
    jetzt = datetime.datetime.now()
    system = ("Du bist Jarvis (ORB), Larsens persönlicher Sprachassistent auf seinem PC. Antworte IMMER auf Deutsch, "
              "kurz und gesprochen-tauglich (1–3 Sätze), ohne Listen, Tabellen, Markdown oder Emojis. "
              f"Heute ist {jetzt:%A, %d.%m.%Y}, {jetzt:%H:%M} Uhr.\n"
              "Unten steht Wissen aus Larsens Second Brain (seine Notizen, Projekte, früheren Chats). Nutze es, wenn es passt. "
              "Erfinde nichts: wirkt das Wissen unvollständig, sag das ehrlich. Ergibt Larsens Satz keinen Sinn (falsch verstanden), "
              "sag kurz, dass du ihn nicht verstanden hast, und bitte ihn, es nochmal zu sagen. Du hast keine Kamera und siehst Larsen nicht – "
              "behaupte nie, ihn gesehen zu haben. Bei einer einfachen Begrüßung grüß kurz zurück und frag, was er braucht.\n"
              "WICHTIG: Wenn die Anfrage eine Aktion am PC, im Internet oder in Apps verlangt, aktuelle Daten braucht "
              "(News, Kurse, Wetter), Code/Dateien betrifft, nach dir selbst, deinen Funktionen oder Fehlern fragt, mehrere Schritte braucht oder du dir nicht sicher bist, "
              "antworte NUR mit dem Wort [CLAUDE] und sonst nichts.\n\n"
              "Persönlichkeit:\n" + _persoenlichkeit() + "\n\nWissen aus dem Second Brain:\n" + kontext)
    msgs = [{"role": "system", "content": system}] + VERLAUF[-6:] + [{"role": "user", "content": frage}]
    try:
        r = _post("/api/chat", {"model": MODELL, "messages": msgs, "stream": False, "think": False, "keep_alive": "30m",
                                "options": {"temperature": .4, "num_ctx": 4096, "num_predict": 160}}, frist=12)
    except Exception:
        return None
    txt = re.sub(r"(?s)<think>.*?(</think>|$)", "", (r.get("message") or {}).get("content", "")).strip()
    if not txt or "[CLAUDE]" in txt.upper() or len(txt) < 2:
        return None
    # Sicherheitsnetz: englische „Überlegungen“ statt Antwort → lieber Claude fragen als Unsinn vorlesen
    if re.match(r"(?i)(okay|ok|alright|let me|first|the user|so,|hmm|wait)", txt) or re.search(r"(?i)(the user|let me|i need to|translates to)", txt):
        return None
    txt = re.sub(r"[*#_`>|]", "", txt)
    txt = re.sub("[🀀-🫿☀-➿️]", "", txt).strip()   # keine Emojis in der Sprachausgabe
    VERLAUF.extend([{"role": "user", "content": frage}, {"role": "assistant", "content": txt}])
    del VERLAUF[:-12]
    return txt


# ---------------- Dauer-Beobachter ----------------
BEOB_START = re.compile(r"\b(beobachte|überwache|behalte .{1,60} im auge|sag (mir )?bescheid,? (wenn|sobald|falls)|"
                        r"meld(e)? dich,? (wenn|sobald|falls)|gib (mir )?bescheid,? (wenn|sobald|falls))\b", re.I)
BEOB_LISTE = re.compile(r"\bwas (beobachtest|überwachst) du\b|\bwelche beobachter\b|\bliste .{0,12}beobacht", re.I)
BEOB_STOP = re.compile(r"\b(hör auf|stopp?|beende|lösch|entfern).{0,30}(beobacht|überwach)", re.I)


def _beob_laden():
    try:
        return json.load(open(BEOB_DATEI, encoding="utf-8"))
    except Exception:
        return []


def _beob_speichern(liste):
    os.makedirs(BASIS, exist_ok=True)
    json.dump(liste, open(BEOB_DATEI, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def beobachter_befehl(text):
    """Erkennt Beobachter-Befehle. Gibt eine gesprochene Antwort zurück oder None (kein Beobachter-Befehl)."""
    if BEOB_LISTE.search(text):
        l = [b for b in _beob_laden() if b.get("aktiv", True)]
        if not l:
            return "Ich beobachte gerade nichts."
        return "Ich beobachte gerade: " + "; ".join(b["was"] for b in l) + "."
    if BEOB_STOP.search(text):
        l = _beob_laden()
        alle = re.search(r"\b(alle|alles)\b", text, re.I)
        rest = [b for b in l if not (alle or any(w in text.lower() for w in b["was"].lower().split() if len(w) > 3))]
        _beob_speichern(rest)
        n = len(l) - len(rest)
        return "Okay, ich beobachte nichts mehr." if alle else ("Okay, gestoppt." if n else "Den Beobachter hab ich nicht gefunden.")
    if not BEOB_START.search(text):
        return None
    hat_modell, _ = verfuegbar()
    if not hat_modell:
        return None
    prompt = ("Zerlege Larsens Auftrag in JSON mit genau diesen Feldern: "
              '{"was": was beobachtet wird als kurzes Substantiv (z. B. Goldpreis, Bitcoin-Kurs, die Webseite von X), "quelle": "gold"|"bitcoin"|"ethereum"|"wetter"|"url", '
              '"url": URL falls quelle=url sonst "", "art": "zahl"|"text", "op": ">"|"<"|"aenderung", "wert": reine Zahl ohne Tausenderpunkte (z. B. 80000) oder null, '
              '"bedingung": die Bedingung als kurze Aussage ohne wenn (z. B. Gold steigt über 2700 Dollar), "minuten": Prüfabstand (Standard 10)}. '
              "Nur JSON ausgeben.\nAuftrag: " + text)
    try:
        r = _post("/api/chat", {"model": MODELL, "messages": [{"role": "user", "content": prompt}], "stream": False,
                                "think": False, "format": "json", "options": {"temperature": 0, "num_ctx": 4096}}, frist=25)
        b = json.loads((r.get("message") or {}).get("content", "{}"))
    except Exception:
        return None
    if b.get("quelle") == "url" and not str(b.get("url", "")).startswith("http"):
        m = re.search(r"https?://\S+|\b[\w-]+\.(de|com|net|org|io)\b\S*", text)
        if not m:
            return "Welche Webseite soll ich beobachten? Sag mir bitte die Adresse."
        b["url"] = m.group(0) if m.group(0).startswith("http") else "https://" + m.group(0)
    # Zahl aus Larsens eigenem Satz bevorzugen (das Modell liest „80.000“ gern als 80)
    zahlen = [float(z.replace(".", "").replace(",", ".")) for z in re.findall(r"\d[\d.]*(?:,\d+)?", text)]
    if b.get("art") == "zahl" and zahlen:
        try:
            w = float(b.get("wert") or 0)
        except (TypeError, ValueError):
            w = 0
        if not w or max(zahlen) / w >= 999:
            b["wert"] = max(zahlen)
        if b.get("op") in (">", "<") and b.get("wert") is not None:
            was = (b.get("was") or "es"); was = was[:1].upper() + was[1:]
            b["was"] = was
            b["bedingung"] = "%s %s %s %s" % (was, "über" if b["op"] == ">" else "unter",
                                               ("{:,.0f}".format(float(b["wert"]))).replace(",", "."), "steigt" if b["op"] == ">" else "fällt")
    b.update(id=hashlib.md5((text + str(time.time())).encode()).hexdigest()[:8], auftrag=text, aktiv=True,
             erstellt=time.time(), zuletzt=0, letzter_stand="", minuten=max(2, min(1440, int(b.get("minuten") or 10))))
    l = _beob_laden() + [b]
    _beob_speichern(l)
    bed = re.sub(r"(?i)^(wenn|sobald|falls)\s+", "", str(b.get("bedingung") or "sich etwas tut")).rstrip(".")
    return "Alles klar, ich behalte %s im Auge und melde mich, sobald %s." % (b.get("was") or "das", bed)


def _wert(b, hol):
    q = b.get("quelle")
    if q in ("gold", "wetter"):
        t = hol(q) or ""
        zahlen = re.findall(r"-?\d[\d.]*,?\d*", t.replace(".", "").replace(",", ".")) if q == "gold" else []
        return (float(zahlen[0]) if zahlen else None), t
    if q in ("bitcoin", "ethereum"):
        with urllib.request.urlopen("https://api.coingecko.com/api/v3/simple/price?ids=%s&vs_currencies=usd" % q, timeout=15) as r:
            v = json.loads(r.read().decode())[q]["usd"]
        return float(v), "%s steht bei %s Dollar" % (q.capitalize(), v)
    req = urllib.request.Request(b["url"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read(2_000_000).decode("utf-8", "replace")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", html)))[:6000]
    return None, text


def beobachter_pruefen(melden, hol, log=print):
    """Einmal alle fälligen Beobachter prüfen. melden(text) sagt es laut / per Telegram."""
    l = _beob_laden()
    geaendert = False
    for b in l:
        if not b.get("aktiv", True) or time.time() - b.get("zuletzt", 0) < b["minuten"] * 60:
            continue
        b["zuletzt"] = time.time(); geaendert = True
        try:
            zahl, text = _wert(b, hol)
        except Exception as e:
            log("Beobachter %s: %s" % (b.get("was"), e)); continue
        treffer, info = False, ""
        if b.get("art") == "zahl" and zahl is not None and b.get("wert") is not None and b.get("op") in (">", "<"):
            treffer = zahl > float(b["wert"]) if b["op"] == ">" else zahl < float(b["wert"])
            info = text or str(zahl)
        else:
            stand = hashlib.md5(text.encode()).hexdigest()
            if b.get("letzter_stand") and stand != b["letzter_stand"]:
                if b.get("op") == "aenderung":
                    treffer, info = True, "Da hat sich was geändert."
                else:
                    try:
                        r = _post("/api/chat", {"model": MODELL, "stream": False, "think": False, "options": {"temperature": 0},
                                                "messages": [{"role": "user", "content": "Bedingung: %s\nAktueller Inhalt:\n%s\n\n"
                                                              "Ist die Bedingung jetzt erfüllt? Antworte mit JA oder NEIN, dann ein kurzer Satz warum." % (b["bedingung"], text[:5000])}]}, frist=60)
                        a = (r.get("message") or {}).get("content", "").strip()
                        treffer, info = a.upper().startswith("JA"), a[2:].strip(" :.-")
                    except Exception:
                        pass
            b["letzter_stand"] = stand
        if treffer:
            b["aktiv"] = False
            melden("Beobachter: %s. %s" % (b.get("was", ""), info))
    if geaendert:
        _beob_speichern(l)


# ---------------- Tiefenrecherche ----------------
RECHERCHE_RE = re.compile(r"\b(tiefen ?recherche|recherchier(e)? (mal )?(gründlich|ausführlich|tief|genau)|"
                          r"mach (mir )?(eine )?(gründliche |ausführliche |tiefe )?recherche)\b", re.I)


def recherche_auftrag(text):
    """Gibt (titel, auftrag) für eine Hintergrund-Aufgabe zurück oder None."""
    if not RECHERCHE_RE.search(text):
        return None
    thema = re.sub(r"(?i)^(jarvis|orb)[,\s]+", "", text)
    thema = RECHERCHE_RE.sub("", thema).strip(" ,.:!?") or text
    thema = re.sub(r"(?i)^(über|zu|zum|zur|nach|zu dem thema)\s+", "", thema)
    datei = "%s-%s.md" % (datetime.date.today().isoformat(), re.sub(r"[^a-z0-9äöüß]+", "-", thema.lower()).strip("-")[:50] or "recherche")
    auftrag = ("Tiefenrecherche für Larsen zum Thema: „%s“.\n"
               "1. Recherchiere gründlich über mehrere unabhängige Quellen (WebSearch + WebFetch, mindestens 5 Quellen, aktuelle Infos bevorzugen).\n"
               "2. Prüfe Widersprüche zwischen den Quellen und gewichte seriöse Quellen höher.\n"
               "3. Schreib einen gut lesbaren Bericht auf Deutsch nach C:\\Users\\larse\\Documents\\Jarvis\\wissen\\recherche\\%s "
               "mit: # Titel, Datum, ## Kurzfassung (3–5 Sätze), ## Die wichtigsten Punkte, ## Details, ## Offene Fragen, "
               "## Quellen (nummerierte Liste mit Titel und URL). Im Text Quellen mit [1], [2] … belegen.\n"
               "4. Antworte zum Schluss gesprochen-tauglich in 2–3 Sätzen mit dem wichtigsten Ergebnis und sag, dass der Bericht in Jarvis liegt."
               % (thema, datei))
    return "Recherche: " + thema[:28], auftrag
