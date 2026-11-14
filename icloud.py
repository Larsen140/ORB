"""iCloud-Kalender über CalDAV (caldav.icloud.com) – nur Python-Bordmittel.
Zugangsdaten (Apple-ID + app-spezifisches Passwort) liegen in der Windows-Anmeldeinformationsverwaltung,
nie in Dateien oder im Repo."""
import base64
import datetime
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from xml.parsers import expat  # ElementTree steckt nicht in der ORB.exe

BASE = "https://caldav.icloud.com/"
TARGET = "ORB/iCloud"
D, C = "{DAV:}", "{urn:ietf:params:xml:ns:caldav}"
_lock = threading.Lock()
_cals = {"user": None, "liste": None, "todo": None}  # gefundene Kalender / Erinnerungslisten (pro Sitzung)
_karten = {"user": None, "buch": None, "t": 0.0, "liste": None}  # Adressbuch (Kontakte nur im Speicher, 5 min)
_cache = {"t": 0.0, "termine": None}           # Widget-Cache
LOG = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB", "icloud.log")


def _log(text):
    """Fehler ins Log – nie Zugangsdaten (nur Status, Host, Pfad)."""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > 200_000:
            os.replace(LOG, LOG + ".alt")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass
    print("iCloud:", text)


class ICloudFehler(Exception):
    """Verständliche Meldung für die Einstellungen."""


# ---------- Windows-Anmeldeinformationsverwaltung ----------
def _advapi():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.c_void_p),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    return ctypes, CREDENTIAL, ctypes.windll.advapi32


def zugang():
    """(apple_id, passwort) oder None."""
    try:
        ctypes, CREDENTIAL, adv = _advapi()
        p = ctypes.POINTER(CREDENTIAL)()
        if not adv.CredReadW(TARGET, 1, 0, ctypes.byref(p)):
            return None
        try:
            c = p.contents
            pw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-8")
            return (c.UserName or "", pw)
        finally:
            adv.CredFree(p)
    except Exception:
        return None


def _speichern(user, pw):
    ctypes, CREDENTIAL, adv = _advapi()
    blob = pw.encode("utf-8")
    buf = ctypes.create_string_buffer(blob, len(blob))
    c = CREDENTIAL(Type=1, TargetName=TARGET, CredentialBlobSize=len(blob),
                   CredentialBlob=ctypes.cast(buf, ctypes.c_void_p), Persist=2, UserName=user)
    if not adv.CredWriteW(ctypes.byref(c), 0):
        raise OSError("Anmeldeinformationen konnten nicht gespeichert werden")


def trennen():
    try:
        ctypes, _, adv = _advapi()
        adv.CredDeleteW(TARGET, 1, 0)
    except Exception:
        pass
    _cals.update(user=None, liste=None, todo=None)
    _karten.update(user=None, buch=None, t=0.0, liste=None)
    _cache.update(t=0.0, termine=None)


def verbunden():
    return zugang() is not None


# ---------- kleines XML-Gerüst (expat) ----------
class _N:
    def __init__(self, tag, attrib):
        self.tag, self.attrib, self.kids, self.teile = tag, attrib, [], []

    @property
    def text(self):
        return "".join(self.teile).strip()

    def kinder(self, tag):
        return [k for k in self.kids if k.tag == tag]

    def alle(self, tag):
        for k in self.kids:
            if k.tag == tag:
                yield k
            yield from k.alle(tag)

    def weg(self, *tags):
        """Erster Nachfahre entlang der Kette tags (jeweils beliebig tief)."""
        for n in self.alle(tags[0]):
            r = n.weg(*tags[1:]) if len(tags) > 1 else n
            if r is not None:
                return r
        return None

    def wtext(self, *tags):
        n = self.weg(*tags)
        return n.text if n is not None else ""


def _xml(data):
    wurzel = _N("", {})
    stapel = [wurzel]
    p = expat.ParserCreate(namespace_separator="}")

    def start(t, a):
        n = _N("{" + t if "}" in t else t, a)
        stapel[-1].kids.append(n)
        stapel.append(n)

    p.StartElementHandler = start
    p.EndElementHandler = lambda t: stapel.pop()
    p.CharacterDataHandler = lambda d: stapel[-1].teile.append(d)
    p.Parse(data, True)
    return wurzel.kids[0] if wurzel.kids else wurzel


# ---------- CalDAV ----------
class _KeinRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # Weiterleitungen behandelt _req selbst (urllib folgt bei PROPFIND/REPORT nicht)


_opener = urllib.request.build_opener(_KeinRedirect)


def _req(method, url, body=None, depth=None, auth=None, extra=None, ctype="text/calendar", kopf=False):
    user, pw = auth or zugang() or ("", "")
    h = {"Authorization": "Basic " + base64.b64encode(("%s:%s" % (user, pw)).encode("utf-8")).decode(),
         "User-Agent": "ORB/1.0 (CalDAV)"}
    if body is not None:
        h["Content-Type"] = ctype + "; charset=utf-8" if method == "PUT" else "application/xml; charset=utf-8"
    if depth is not None:
        h["Depth"] = str(depth)
    h.update(extra or {})
    data = body.encode("utf-8") if isinstance(body, str) else body
    for _ in range(6):
        r = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with _opener.open(r, timeout=15) as resp:
                return (resp.read(), resp.headers) if kopf else resp.read()
        except urllib.error.HTTPError as e:
            ziel = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
            if not ziel:
                raise
            neu = urllib.parse.urljoin(url, ziel)
            if not neu.startswith("https://") or not urllib.parse.urlparse(neu).hostname.endswith(".icloud.com"):
                raise  # Zugangsdaten nur an iCloud schicken
            url = neu
    raise ICloudFehler("Zu viele Weiterleitungen von iCloud")
def _propfind(url, props, depth, auth=None):
    body = ('<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>%s</d:prop></d:propfind>' % props)
    return _xml(_req("PROPFIND", url, body, depth, auth))


def _sammlungen(auth=None):
    """Alle CalDAV-Sammlungen: [{"name", "url", "comps"}] – Kalender und Erinnerungslisten."""
    x = _propfind(BASE, "<d:current-user-principal/>", 0, auth)
    href = x.wtext(D + "current-user-principal", D + "href")
    if not href:
        raise ICloudFehler("iCloud hat kein Benutzerkonto geliefert – Apple-ID prüfen")
    principal = urllib.parse.urljoin(BASE, href)
    x = _propfind(principal, "<c:calendar-home-set/>", 0, auth)
    home_href = x.wtext(C + "calendar-home-set", D + "href")
    if not home_href:
        raise ICloudFehler("iCloud hat keinen Kalenderordner geliefert – ist der Kalender in iCloud aktiviert?")
    home = urllib.parse.urljoin(principal, home_href)   # meist https://pXX-caldav.icloud.com/…
    if not home.endswith("/"):
        home += "/"
    x = _propfind(home, "<d:displayname/><d:resourcetype/><c:supported-calendar-component-set/>", 1, auth)
    out = []
    for r in x.kinder(D + "response"):
        if r.weg(D + "resourcetype", C + "calendar") is None:
            continue
        out.append({"name": r.wtext(D + "displayname"), "comps": [c.attrib.get("name") for c in r.alle(C + "comp")],
                    "url": urllib.parse.urljoin(home, r.kinder(D + "href")[0].text)})
    return out


def _lade(auth=None):
    a = auth or zugang()
    if not a:
        return False
    if _cals["liste"] is None or _cals["user"] != a[0]:
        alle = _sammlungen(a)
        _cals.update(user=a[0],
                     liste=[{"name": k["name"] or "Kalender", "url": k["url"]}
                            for k in alle if not k["comps"] or "VEVENT" in k["comps"]],
                     todo=[{"name": k["name"] or "Erinnerungen", "url": k["url"]} for k in alle if "VTODO" in k["comps"]])
    return True


def _kalender(auth=None):
    """Alle Kalender mit Terminen: [{"name", "url"}]."""
    return _cals["liste"] if _lade(auth) else []


def _listen():
    """Alle Erinnerungslisten (VTODO): [{"name", "url"}]."""
    return _cals["todo"] if _lade() else []


def _ics_zeilen(text):
    zeilen = []
    for z in text.replace("\r\n", "\n").split("\n"):
        if z[:1] in (" ", "\t") and zeilen:
            zeilen[-1] += z[1:]
        elif z:
            zeilen.append(z)
    return zeilen


def _unesc(s):
    return s.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _esc(s):
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _zeit(params, val):
    """-> (lokale naive datetime, ganztägig?)"""
    val = val.strip()
    if "VALUE=DATE" in params.upper() and "DATE-TIME" not in params.upper() or len(val) == 8:
        return datetime.datetime.strptime(val[:8], "%Y%m%d"), True
    dt = datetime.datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
    if val.endswith("Z"):
        return dt.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None), False
    tzid = next((p[5:] for p in params.split(";") if p.upper().startswith("TZID=")), "")
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            return dt.replace(tzinfo=ZoneInfo(tzid.strip('"'))).astimezone().replace(tzinfo=None), False
        except Exception:
            pass
    return dt, False


def _events(ics):
    out, ev = [], None
    for z in _ics_zeilen(ics):
        if z == "BEGIN:VEVENT":
            ev = {}
        elif z == "END:VEVENT" and ev is not None:
            if "start" in ev:
                out.append(ev)
            ev = None
        elif ev is not None and ":" in z:
            k, v = z.split(":", 1)
            name, _, params = k.partition(";")
            name = name.upper()
            try:
                if name == "SUMMARY":
                    ev["titel"] = _unesc(v)
                elif name == "LOCATION":
                    ev["ort"] = _unesc(v)
                elif name == "DTSTART":
                    ev["start"], ev["ganztag"] = _zeit(params, v)
                elif name == "DTEND":
                    ev["ende"] = _zeit(params, v)[0]
            except ValueError:
                pass
    return out


def _utc(dt):
    return dt.astimezone().astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def liste(von=None, bis=None):
    """Termine aller iCloud-Kalender zwischen von und bis (lokale datetime)."""
    von = von or datetime.datetime.combine(datetime.date.today(), datetime.time())
    bis = bis or von + datetime.timedelta(days=60)
    rng = 'start="%s" end="%s"' % (_utc(von), _utc(bis))
    out = []
    for kal in _kalender():
        for expand in (True, False):
            body = ('<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" '
                    'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data>%s'
                    '</c:calendar-data></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
                    '<c:time-range %s/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'
                    % ("<c:expand %s/>" % rng if expand else "", rng))
            try:
                x = _xml(_req("REPORT", kal["url"], body, 1))
                break
            except urllib.error.HTTPError as e:
                if not expand or e.code in (401, 403):
                    raise
        for r in x.kinder(D + "response"):
            hrefs = r.kinder(D + "href")
            if not hrefs:
                continue
            href = urllib.parse.urljoin(kal["url"], hrefs[0].text)
            for ev in _events(r.wtext(C + "calendar-data")):
                ende = ev.get("ende") or ev["start"]
                if ende < von and ev["start"] < von or ev["start"] >= bis:
                    continue
                out.append({"id": href, "titel": ev.get("titel", "Termin"), "ort": ev.get("ort", ""),
                            "kalender": kal["name"], "ganztag": ev["ganztag"],
                            "start": ev["start"].strftime("%Y-%m-%d" if ev["ganztag"] else "%Y-%m-%dT%H:%M"),
                            "ende": ende.strftime("%Y-%m-%d" if ev["ganztag"] else "%Y-%m-%dT%H:%M")})
    out.sort(key=lambda e: e["start"])
    return out


def termine_widget():
    """Für das Termine-Widget: [{"datum", "zeit", "text"}] (60 s zwischengespeichert)."""
    with _lock:
        if _cache["termine"] is not None and time.time() - _cache["t"] < 60:
            return _cache["termine"]
        try:
            jetzt = datetime.datetime.now()
            res = [{"datum": e["start"][:10], "zeit": "" if e["ganztag"] else e["start"][11:16], "text": e["titel"]}
                   for e in liste() if e["ganztag"] or e["ende"] >= jetzt.strftime("%Y-%m-%dT%H:%M")][:6]
            _cache.update(t=time.time(), termine=res)
        except urllib.error.HTTPError as e:
            _log("Termine laden: HTTP %d" % e.code)
            _cache["t"] = time.time() - 40
        except Exception as e:
            _log("Termine laden: %s %s" % (type(e).__name__, str(e)[:150]))
            _cache["t"] = time.time() - 40   # in 20 s erneut versuchen, bis dahin alter Stand
        return _cache["termine"] or []


def _parse(s):
    s = str(s).strip().replace(" ", "T")
    if len(s) == 10:
        return datetime.datetime.strptime(s, "%Y-%m-%d"), True
    return datetime.datetime.fromisoformat(s[:16]), False


def neu(titel, start, ende=None, ort="", notiz="", kalender=""):
    beg, ganz = _parse(start)
    end = _parse(ende)[0] if ende else beg + (datetime.timedelta(days=1) if ganz else datetime.timedelta(hours=1))
    kals = _kalender()
    if not kals:
        raise RuntimeError("Kein iCloud-Kalender gefunden")
    kal = next((k for k in kals if kalender and k["name"].lower() == str(kalender).lower()), kals[0])
    uid = str(uuid.uuid4()).upper()
    if ganz:
        zeit = "DTSTART;VALUE=DATE:%s\r\nDTEND;VALUE=DATE:%s" % (beg.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    else:
        zeit = "DTSTART:%s\r\nDTEND:%s" % (_utc(beg), _utc(end))
    teile = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ORB//DE", "BEGIN:VEVENT", "UID:" + uid,
             "DTSTAMP:" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), zeit,
             "SUMMARY:" + _esc(titel)]
    if ort:
        teile.append("LOCATION:" + _esc(ort))
    if notiz:
        teile.append("DESCRIPTION:" + _esc(notiz))
    teile += ["END:VEVENT", "END:VCALENDAR", ""]
    url = kal["url"].rstrip("/") + "/" + uid + ".ics"
    _req("PUT", url, "\r\n".join(teile), extra={"If-None-Match": "*"})
    _cache["t"] = 0.0
    return {"id": url, "titel": titel, "kalender": kal["name"],
            "start": beg.strftime("%Y-%m-%d" if ganz else "%Y-%m-%dT%H:%M")}


def loeschen(href):
    if not str(href).startswith("https://") or ".icloud.com" not in urllib.parse.urlparse(href).netloc:
        raise ValueError("Ungültige Termin-ID")
    _req("DELETE", href)
    _cache["t"] = 0.0
    return True


# ---------- gemeinsame Helfer ----------
def _pruef_id(href, art="Eintrag"):
    href = str(href).strip()
    host = urllib.parse.urlparse(href).hostname or ""
    if not href.startswith("https://") or not host.endswith(".icloud.com"):
        raise ValueError("Ungültige %s-ID (erst suchen bzw. liste aufrufen)" % art)
    return href


def _falten(zeilen):
    """Zeilen auf höchstens 74 Zeichen falten (iCalendar/vCard) und mit CRLF verbinden."""
    out = []
    for z in zeilen:
        while len(z) > 74:
            out.append(z[:74])
            z = " " + z[74:]
        out.append(z)
    return "\r\n".join(out + [""])


def _jetzt_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pname(z):
    """(gruppe, NAME) einer Inhaltszeile, z. B. 'item1.TEL;type=CELL:…' -> ('item1', 'TEL')."""
    g, _, n = z.split(":", 1)[0].split(";", 1)[0].rpartition(".")
    return g, n.upper()


# ---------- Erinnerungen (CalDAV, VTODO) ----------
def _todos(ics):
    out, t, tief = [], None, 0
    for z in _ics_zeilen(ics):
        if z == "BEGIN:VTODO":
            t, tief = {}, 0
        elif z == "END:VTODO" and t is not None:
            out.append(t)
            t = None
        elif t is not None and z.startswith("BEGIN:"):
            tief += 1                      # z. B. VALARM – dessen Felder nicht mitlesen
        elif t is not None and z.startswith("END:"):
            tief -= 1
        elif t is not None and tief == 0 and ":" in z:
            k, v = z.split(":", 1)
            name, _, params = k.partition(";")
            name = name.upper()
            if name in ("SUMMARY", "DESCRIPTION"):
                t[name] = _unesc(v)
            elif name == "DUE":
                try:
                    t["DUE"] = _zeit(params, v)
                except ValueError:
                    pass
            elif name in ("STATUS", "COMPLETED", "PRIORITY"):
                t[name] = v.strip()
    return out


def erinnerungen(liste_name="", alle=False):
    """Erinnerungen (standardmäßig nur offene) aus allen Listen oder einer bestimmten."""
    listen = _listen()
    if not listen:
        raise ICloudFehler("Keine Erinnerungslisten über iCloud erreichbar (Apple gibt aktualisierte "
                           "Erinnerungen teils nicht mehr per CalDAV heraus)")
    if liste_name:
        listen = [x for x in listen if x["name"].lower() == str(liste_name).lower()] or listen
    body = ('<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VTODO"/></c:comp-filter></c:filter>'
            '</c:calendar-query>')
    out = []
    for li in listen:
        x = _xml(_req("REPORT", li["url"], body, 1))
        for r in x.kinder(D + "response"):
            hrefs = r.kinder(D + "href")
            if not hrefs:
                continue
            for t in _todos(r.wtext(C + "calendar-data")):
                erledigt = t.get("STATUS", "").upper() == "COMPLETED" or bool(t.get("COMPLETED"))
                if erledigt and not alle:
                    continue
                e = {"id": urllib.parse.urljoin(li["url"], hrefs[0].text), "titel": t.get("SUMMARY", "Erinnerung"),
                     "liste": li["name"], "erledigt": erledigt}
                if "DUE" in t:
                    d, ganz = t["DUE"]
                    e["faellig"] = d.strftime("%Y-%m-%d" if ganz else "%Y-%m-%dT%H:%M")
                if t.get("DESCRIPTION"):
                    e["notiz"] = t["DESCRIPTION"][:300]
                if t.get("PRIORITY", "0") not in ("", "0"):
                    e["wichtig"] = True
                out.append(e)
    out.sort(key=lambda e: (e["erledigt"], e.get("faellig") or "9999"))
    return out


def erinnerung_neu(titel, faellig=None, liste_name="", notiz="", wichtig=False):
    listen = _listen()
    if not listen:
        raise ICloudFehler("Keine Erinnerungsliste über iCloud erreichbar")
    li = next((x for x in listen if liste_name and x["name"].lower() == str(liste_name).lower()), listen[0])
    uid = str(uuid.uuid4()).upper()
    teile = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ORB//DE", "BEGIN:VTODO", "UID:" + uid,
             "DTSTAMP:" + _jetzt_utc(), "CREATED:" + _jetzt_utc(), "SUMMARY:" + _esc(titel), "STATUS:NEEDS-ACTION"]
    if notiz:
        teile.append("DESCRIPTION:" + _esc(notiz))
    if wichtig:
        teile.append("PRIORITY:1")
    aus = None
    if faellig:
        d, ganz = _parse(faellig)
        if ganz:
            teile.append("DUE;VALUE=DATE:" + d.strftime("%Y%m%d"))
            aus = d.strftime("%Y-%m-%d")
        else:
            teile += ["DUE:" + _utc(d), "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + _esc(titel),
                      "TRIGGER;VALUE=DATE-TIME:" + _utc(d), "END:VALARM"]
            aus = d.strftime("%Y-%m-%dT%H:%M")
    teile += ["END:VTODO", "END:VCALENDAR"]
    url = li["url"].rstrip("/") + "/" + uid + ".ics"
    _req("PUT", url, _falten(teile), extra={"If-None-Match": "*"})
    return {"id": url, "titel": titel, "liste": li["name"], "faellig": aus}


def erinnerung_erledigt(href, erledigt=True):
    href = _pruef_id(href, "Erinnerungs")
    roh, kopf = _req("GET", href, kopf=True)
    neu, im, tief = [], False, 0
    for z in _ics_zeilen(roh.decode("utf-8", "replace")):
        if z == "BEGIN:VTODO":
            im, tief = True, 0
        elif im and z == "END:VTODO":
            neu += (["STATUS:COMPLETED", "COMPLETED:" + _jetzt_utc(), "PERCENT-COMPLETE:100"] if erledigt
                    else ["STATUS:NEEDS-ACTION"]) + ["LAST-MODIFIED:" + _jetzt_utc()]
            im = False
        elif im and z.startswith("BEGIN:"):
            tief += 1
        elif im and z.startswith("END:"):
            tief -= 1
        elif im and tief == 0 and _pname(z)[1] in ("STATUS", "COMPLETED", "PERCENT-COMPLETE", "LAST-MODIFIED"):
            continue
        neu.append(z)
    etag = kopf.get("ETag")
    _req("PUT", href, _falten(neu), extra={"If-Match": etag} if etag else None)
    return True


def erinnerung_loeschen(href):
    _req("DELETE", _pruef_id(href, "Erinnerungs"))
    return True


# ---------- Kontakte (CardDAV, contacts.icloud.com) ----------
CARD_BASE = "https://contacts.icloud.com/"
CD = "{urn:ietf:params:xml:ns:carddav}"
_TYPEN = {"CELL": "mobil", "IPHONE": "iPhone", "HOME": "privat", "WORK": "arbeit", "MAIN": "Haupt", "FAX": "Fax"}


def _card_propfind(url, props, depth, auth=None):
    body = ('<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" '
            'xmlns:cd="urn:ietf:params:xml:ns:carddav"><d:prop>%s</d:prop></d:propfind>' % props)
    return _xml(_req("PROPFIND", url, body, depth, auth))


def _adressbuch():
    a = zugang()
    if not a:
        raise ICloudFehler("iCloud ist nicht verbunden")
    if _karten["buch"] and _karten["user"] == a[0]:
        return _karten["buch"]
    x = _card_propfind(CARD_BASE, "<d:current-user-principal/>", 0, a)
    href = x.wtext(D + "current-user-principal", D + "href")
    if not href:
        raise ICloudFehler("iCloud-Kontakte: kein Benutzerkonto gefunden")
    principal = urllib.parse.urljoin(CARD_BASE, href)
    x = _card_propfind(principal, "<cd:addressbook-home-set/>", 0, a)
    home = x.wtext(CD + "addressbook-home-set", D + "href")
    if not home:
        raise ICloudFehler("iCloud-Kontakte: kein Adressbuch – Kontakte in iCloud aktiviert?")
    home = urllib.parse.urljoin(principal, home)
    home += "" if home.endswith("/") else "/"
    x = _card_propfind(home, "<d:resourcetype/>", 1, a)
    buch = None
    for r in x.kinder(D + "response"):
        if r.weg(D + "resourcetype", CD + "addressbook") is not None:
            buch = urllib.parse.urljoin(home, r.kinder(D + "href")[0].text)
            break
    if not buch:
        raise ICloudFehler("iCloud-Kontakte: kein Adressbuch gefunden")
    _karten.update(user=a[0], buch=buch, t=0.0, liste=None)
    return buch


def _karten_aus(x, buch, out):
    for r in x.kinder(D + "response"):
        h = r.kinder(D + "href")
        daten = r.wtext(CD + "address-data")
        if h and daten:
            out.append((urllib.parse.urljoin(buch, h[0].text), daten))


def _karten_laden():
    """Alle vCards, nur im Speicher und höchstens 5 min: [(href, text)]."""
    buch = _adressbuch()
    if _karten["liste"] is not None and time.time() - _karten["t"] < 300:
        return _karten["liste"]
    out = []
    try:
        _karten_aus(_xml(_req("REPORT", buch, '<?xml version="1.0" encoding="utf-8"?><cd:addressbook-query '
                              'xmlns:d="DAV:" xmlns:cd="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag/>'
                              '<cd:address-data/></d:prop></cd:addressbook-query>', 1)), buch, out)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise
        # Ersatzweg: Liste der Karten, dann blockweise per multiget holen
        x = _card_propfind(buch, "<d:getetag/>", 1)
        hrefs = [r.kinder(D + "href")[0].text for r in x.kinder(D + "response")
                 if r.kinder(D + "href") and r.kinder(D + "href")[0].text.endswith(".vcf")]
        for i in range(0, len(hrefs), 200):
            teil = "".join("<d:href>%s</d:href>" % h.replace("&", "&amp;") for h in hrefs[i:i + 200])
            _karten_aus(_xml(_req("REPORT", buch, '<?xml version="1.0" encoding="utf-8"?><cd:addressbook-multiget '
                                  'xmlns:d="DAV:" xmlns:cd="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag/>'
                                  '<cd:address-data/></d:prop>%s</cd:addressbook-multiget>' % teil, 1)), buch, out)
    _karten.update(t=time.time(), liste=out)
    return out


def _typ(params, labels, gruppe):
    if gruppe and gruppe in labels:
        return re.sub(r"^_\$!<(.*)>!\$_$", r"\1", labels[gruppe])   # Apple-Standardbeschriftungen
    for t in re.findall(r"(?i)type=([^;]+)", params):
        for x in t.split(","):
            if x.upper() in _TYPEN:
                return _TYPEN[x.upper()]
    return ""


def _kontakt(href, text):
    props = []
    for z in _ics_zeilen(text):
        if ":" in z:
            k, v = z.split(":", 1)
            g, n = _pname(z)
            props.append((n, k.partition(";")[2], v, g))
    labels = {g: _unesc(v) for n, _, v, g in props if n == "X-ABLABEL" and g}
    k = {"id": href, "name": "", "telefon": [], "email": []}
    for name, params, v, g in props:
        if name == "FN":
            k["name"] = _unesc(v)
        elif name == "N" and not k["name"]:
            t = v.split(";")
            k["name"] = " ".join(_unesc(x) for x in (t[1:2] + t[0:1]) if x).strip()
        elif name == "ORG":
            k["firma"] = _unesc(v.split(";")[0])
        elif name in ("TEL", "EMAIL"):
            typ = _typ(params, labels, g)
            (k["telefon"] if name == "TEL" else k["email"]).append(_unesc(v) + (" (%s)" % typ if typ else ""))
        elif name == "ADR":
            adr = ", ".join(_unesc(x) for x in v.split(";") if x.strip())
            if adr:
                k.setdefault("adresse", []).append(adr)
        elif name == "BDAY":
            k["geburtstag"] = v.strip()[:10]
        elif name == "NICKNAME":
            k["spitzname"] = _unesc(v)
        elif name == "NOTE":
            k["notiz"] = _unesc(v)[:300]
    if not k["name"]:
        k["name"] = k.get("firma") or (k["email"] or ["(ohne Name)"])[0]
    return k


def _nummer(s):
    d = re.sub(r"[^\d+]", "", str(s))
    if d.startswith("+49"):
        d = "0" + d[3:]
    elif d.startswith("0049"):
        d = "0" + d[4:]
    return d.replace("+", "")


def kontakte_suche(frage, max_n=10):
    """Nur passende Kontakte – nie das ganze Adressbuch. -> (treffer, anzahl)"""
    frage = str(frage or "").strip().lower()
    if len(frage) < 2:
        raise ValueError("Suchbegriff nötig (mindestens 2 Zeichen)")
    worte = frage.split()
    ziffern = _nummer(frage) if re.fullmatch(r"[\d\s+()/-]{4,}", frage) else ""
    treffer = []
    for href, text in _karten_laden():
        if "VCARD" not in text.upper():
            continue
        k = _kontakt(href, text)
        if ziffern:
            ok = any(ziffern in _nummer(t.split(" (")[0]) for t in k["telefon"])
        else:
            heu = " ".join([k["name"], k.get("firma", ""), k.get("spitzname", "")] + k["email"]).lower()
            ok = all(w in heu for w in worte)
        if ok:
            treffer.append(k)
    treffer.sort(key=lambda k: (not k["name"].lower().startswith(worte[0]), k["name"].lower()))
    return treffer[:max_n], len(treffer)


def _name_n(name):
    t = str(name).split()
    return (_esc(t[-1]) + ";" + _esc(" ".join(t[:-1])) + ";;;") if len(t) > 1 else (_esc(name) + ";;;;")


def _liste(v):
    if not v:
        return []
    return [x.strip() for x in (v if isinstance(v, list) else re.split(r"[,;]", str(v))) if x.strip()]


def _felder(telefon=None, email=None, firma=None, adresse=None, geburtstag=None, notiz=None):
    z = ["TEL;TYPE=CELL;TYPE=VOICE:" + _esc(t) for t in _liste(telefon)]
    z += ["EMAIL;TYPE=INTERNET;TYPE=HOME:" + _esc(e) for e in _liste(email)]
    if firma:
        z.append("ORG:" + _esc(firma) + ";")
    if adresse:
        z.append("ADR;TYPE=HOME:;;" + _esc(adresse) + ";;;;")
    if geburtstag:
        z.append("BDAY:" + datetime.date.fromisoformat(str(geburtstag)[:10]).isoformat())
    if notiz:
        z.append("NOTE:" + _esc(notiz))
    return z


def kontakt_neu(name, telefon=None, email=None, firma="", adresse="", geburtstag="", notiz=""):
    if not str(name or "").strip():
        raise ValueError("Name nötig")
    buch = _adressbuch()
    uid = str(uuid.uuid4()).upper()
    teile = (["BEGIN:VCARD", "VERSION:3.0", "PRODID:-//ORB//DE", "UID:" + uid, "N:" + _name_n(name),
              "FN:" + _esc(name)] + _felder(telefon, email, firma, adresse, geburtstag, notiz)
             + ["REV:" + _jetzt_utc(), "END:VCARD"])
    url = buch.rstrip("/") + "/" + uid + ".vcf"
    _req("PUT", url, _falten(teile), extra={"If-None-Match": "*"}, ctype="text/vcard")
    _karten["t"] = 0.0
    return _kontakt(url, "\n".join(teile))


def kontakt_aendern(href, name=None, telefon=None, email=None, firma=None, adresse=None, geburtstag=None,
                    notiz=None, dazu=False):
    """Angegebene Felder ersetzen (dazu=True: Telefon/E-Mail ergänzen statt ersetzen), Rest bleibt unverändert."""
    href = _pruef_id(href, "Kontakt")
    roh, kopf = _req("GET", href, kopf=True)
    weg = {"REV"}
    if name:
        weg |= {"FN", "N"}
    if telefon and not dazu:
        weg.add("TEL")
    if email and not dazu:
        weg.add("EMAIL")
    for feld, n in ((firma, "ORG"), (adresse, "ADR"), (geburtstag, "BDAY"), (notiz, "NOTE")):
        if feld:
            weg.add(n)
    zeilen = _ics_zeilen(roh.decode("utf-8", "replace"))
    gruppen_weg = {_pname(z)[0] for z in zeilen if _pname(z)[1] in weg and _pname(z)[0]}
    behalten = [z for z in zeilen if _pname(z)[1] not in weg
                and not (_pname(z)[0] in gruppen_weg and _pname(z)[1] == "X-ABLABEL")]
    neu = (["N:" + _name_n(name), "FN:" + _esc(name)] if name else []) \
        + _felder(telefon, email, firma, adresse, geburtstag, notiz) + ["REV:" + _jetzt_utc()]
    ende = max(i for i, z in enumerate(behalten) if z.upper() == "END:VCARD")
    behalten[ende:ende] = neu
    etag = kopf.get("ETag")
    _req("PUT", href, _falten(behalten), extra={"If-Match": etag} if etag else None, ctype="text/vcard")
    _karten["t"] = 0.0
    return _kontakt(href, "\n".join(behalten))


def kontakt_loeschen(href):
    _req("DELETE", _pruef_id(href, "Kontakt"))
    _karten["t"] = 0.0
    return True


def _passwort(pw):
    """App-spezifisches Passwort normalisieren: Leerzeichen weg, Gedankenstriche zu '-', Bindestriche behalten."""
    pw = re.sub(r"[\s ​﻿]", "", str(pw))
    pw = re.sub(r"[‐-―−]", "-", pw)
    if re.fullmatch(r"[A-Za-z]{16}", pw):  # ohne Bindestriche eingetippt
        pw = "-".join(pw[i:i + 4] for i in range(0, 16, 4))
    return pw.lower() if re.fullmatch(r"[A-Za-z]{4}(-[A-Za-z]{4}){3}", pw) else pw


def verbinden(user, pw):
    """Zugang testen und bei Erfolg sicher speichern. Gibt die Kalendernamen zurück."""
    user, pw = re.sub(r"\s", "", str(user)), _passwort(pw)
    if not user or not pw:
        raise ValueError("Apple-ID und app-spezifisches Passwort eingeben")
    if "@" not in user and not user.lstrip("+").isdigit():
        raise ValueError("Apple-ID bitte als E-Mail-Adresse eingeben")
    _cals.update(user=None, liste=None, todo=None)
    try:
        kals = _kalender((user, pw))
    except urllib.error.HTTPError as e:
        _cals.update(user=None, liste=None, todo=None)
        ort = urllib.parse.urlparse(e.url or "").hostname or "?"
        _log("Verbinden fehlgeschlagen: HTTP %d bei %s" % (e.code, ort))
        if e.code == 401:
            raise ValueError("Anmeldung abgelehnt – Apple-ID oder app-spezifisches Passwort falsch "
                             "(Format xxxx-xxxx-xxxx-xxxx, nicht das normale Apple-Passwort)")
        if e.code == 403:
            raise ValueError("Zugriff verweigert – iCloud-Kalender auf dem iPhone aktiviert?")
        raise ValueError("iCloud antwortet mit Fehler %d – später erneut versuchen" % e.code)
    except ICloudFehler as e:
        _cals.update(user=None, liste=None, todo=None)
        _log("Verbinden fehlgeschlagen: %s" % e)
        raise ValueError(str(e))
    except urllib.error.URLError as e:
        _cals.update(user=None, liste=None, todo=None)
        _log("Verbinden fehlgeschlagen: Netzwerk – %s" % type(e.reason).__name__ + " " + str(e.reason)[:150])
        if "CERTIFICATE" in str(e.reason).upper():
            raise ValueError("Sichere Verbindung zu iCloud fehlgeschlagen (Zertifikat)")
        raise ValueError("iCloud nicht erreichbar – Internetverbindung prüfen")
    except Exception as e:
        _cals.update(user=None, liste=None, todo=None)
        _log("Verbinden fehlgeschlagen: %s %s" % (type(e).__name__, str(e)[:150]))
        raise ValueError("iCloud-Verbindung fehlgeschlagen (%s)" % type(e).__name__)
    if not kals:
        _log("Verbunden, aber keine Terminkalender gefunden")
        raise ValueError("Angemeldet, aber keine Kalender gefunden – iCloud-Kalender auf dem iPhone aktivieren")
    _speichern(user, pw)
    _cache.update(t=0.0, termine=None)
    _log("Verbunden, %d Kalender" % len(kals))
    return [k["name"] for k in kals]
