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
_cals = {"user": None, "liste": None}          # gefundene Kalender (pro Sitzung)
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
    _cals.update(user=None, liste=None)
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


def _req(method, url, body=None, depth=None, auth=None, extra=None):
    user, pw = auth or zugang() or ("", "")
    h = {"Authorization": "Basic " + base64.b64encode(("%s:%s" % (user, pw)).encode("utf-8")).decode(),
         "User-Agent": "ORB/1.0 (CalDAV)"}
    if body is not None:
        h["Content-Type"] = "text/calendar; charset=utf-8" if method == "PUT" else "application/xml; charset=utf-8"
    if depth is not None:
        h["Depth"] = str(depth)
    h.update(extra or {})
    data = body.encode("utf-8") if isinstance(body, str) else body
    for _ in range(6):
        r = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with _opener.open(r, timeout=15) as resp:
                return resp.read()
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


def _kalender(auth=None):
    """Alle Kalender mit Terminen: [{"name", "url"}]."""
    a = auth or zugang()
    if not a:
        return []
    if _cals["liste"] is not None and _cals["user"] == a[0]:
        return _cals["liste"]
    x = _propfind(BASE, "<d:current-user-principal/>", 0, a)
    href = x.wtext(D + "current-user-principal", D + "href")
    if not href:
        raise ICloudFehler("iCloud hat kein Benutzerkonto geliefert – Apple-ID prüfen")
    principal = urllib.parse.urljoin(BASE, href)
    x = _propfind(principal, "<c:calendar-home-set/>", 0, a)
    home_href = x.wtext(C + "calendar-home-set", D + "href")
    if not home_href:
        raise ICloudFehler("iCloud hat keinen Kalenderordner geliefert – ist der Kalender in iCloud aktiviert?")
    home = urllib.parse.urljoin(principal, home_href)   # meist https://pXX-caldav.icloud.com/…
    if not home.endswith("/"):
        home += "/"
    x = _propfind(home, "<d:displayname/><d:resourcetype/><c:supported-calendar-component-set/>", 1, a)
    liste = []
    for r in x.kinder(D + "response"):
        if r.weg(D + "resourcetype", C + "calendar") is None:
            continue
        comps = [c.attrib.get("name") for c in r.alle(C + "comp")]
        if comps and "VEVENT" not in comps:
            continue  # z. B. Erinnerungen (VTODO)
        name = r.wtext(D + "displayname") or "Kalender"
        liste.append({"name": name, "url": urllib.parse.urljoin(home, r.kinder(D + "href")[0].text)})
    _cals.update(user=a[0], liste=liste)
    return liste


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
    _cals.update(user=None, liste=None)
    try:
        kals = _kalender((user, pw))
    except urllib.error.HTTPError as e:
        _cals.update(user=None, liste=None)
        ort = urllib.parse.urlparse(e.url or "").hostname or "?"
        _log("Verbinden fehlgeschlagen: HTTP %d bei %s" % (e.code, ort))
        if e.code == 401:
            raise ValueError("Anmeldung abgelehnt – Apple-ID oder app-spezifisches Passwort falsch "
                             "(Format xxxx-xxxx-xxxx-xxxx, nicht das normale Apple-Passwort)")
        if e.code == 403:
            raise ValueError("Zugriff verweigert – iCloud-Kalender auf dem iPhone aktiviert?")
        raise ValueError("iCloud antwortet mit Fehler %d – später erneut versuchen" % e.code)
    except ICloudFehler as e:
        _cals.update(user=None, liste=None)
        _log("Verbinden fehlgeschlagen: %s" % e)
        raise ValueError(str(e))
    except urllib.error.URLError as e:
        _cals.update(user=None, liste=None)
        _log("Verbinden fehlgeschlagen: Netzwerk – %s" % type(e.reason).__name__ + " " + str(e.reason)[:150])
        if "CERTIFICATE" in str(e.reason).upper():
            raise ValueError("Sichere Verbindung zu iCloud fehlgeschlagen (Zertifikat)")
        raise ValueError("iCloud nicht erreichbar – Internetverbindung prüfen")
    except Exception as e:
        _cals.update(user=None, liste=None)
        _log("Verbinden fehlgeschlagen: %s %s" % (type(e).__name__, str(e)[:150]))
        raise ValueError("iCloud-Verbindung fehlgeschlagen (%s)" % type(e).__name__)
    if not kals:
        _log("Verbunden, aber keine Terminkalender gefunden")
        raise ValueError("Angemeldet, aber keine Kalender gefunden – iCloud-Kalender auf dem iPhone aktivieren")
    _speichern(user, pw)
    _cache.update(t=0.0, termine=None)
    _log("Verbunden, %d Kalender" % len(kals))
    return [k["name"] for k in kals]
