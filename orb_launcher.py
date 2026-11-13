"""ORB.exe – Installer, Starter und Updater in einem. Bleibt immer dieselbe Datei.

Beim ersten Start installiert sich ORB nach %LOCALAPPDATA%\\ORB (Verknüpfung auf dem Desktop, im Startmenü und im
Autostart) und lädt den Code aus GitHub (Larsen140/ORB). Bei jedem Start und regelmäßig im Betrieb wird nach einer
neueren Version gesucht. Vor jedem Update wird gesichert; startet der neue Code nicht, wird automatisch zurückgesetzt.
Private Daten (Einstellungen, Schlüssel, Gesprächszustand) liegen in %USERPROFILE%\\Orb und gehen nie zu GitHub."""
import os
import sys

# Diese Importe sorgen nur dafür, dass alles Nötige in der exe steckt – der ORB-Code selbst kommt von GitHub.
import array, asyncio, ctypes, datetime, difflib, glob, http.server, io, json, math, random, re, shutil, socket  # noqa
import socketserver, subprocess, tempfile, threading, time, urllib.parse, urllib.request, webbrowser, zipfile  # noqa
import certifi, edge_tts, psutil, sounddevice  # noqa

REPO = "Larsen140/ORB"
BASE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ORB")
APP = os.path.join(BASE, "app")
BACKUPS = os.path.join(BASE, "Sicherungen")
INSTALLED_EXE = os.path.join(BASE, "ORB.exe")
FROZEN = getattr(sys, "frozen", False)


def message(text, title="ORB"):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    except Exception:
        pass


def http_get(url, timeout=8, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": "ORB", **({"Accept": accept} if accept else {})})
    import ssl
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def remote_sha():
    try:
        return http_get("https://api.github.com/repos/%s/commits/main" % REPO, 6, "application/vnd.github.sha").decode().strip()
    except Exception:
        return None


def local_sha():
    try:
        with open(os.path.join(APP, ".sha")) as f:
            return f.read().strip()
    except Exception:
        return None


def backup():
    if not os.path.exists(os.path.join(APP, "server.py")):
        return
    os.makedirs(BACKUPS, exist_ok=True)
    name = os.path.join(BACKUPS, "ORB_%s_%s.zip" % (time.strftime("%Y-%m-%d_%H%M%S"), (local_sha() or "lokal")[:7]))
    with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
        for f in os.listdir(APP):
            p = os.path.join(APP, f)
            if os.path.isfile(p):
                z.write(p, f)
    for old in sorted(glob.glob(os.path.join(BACKUPS, "ORB_*.zip")), key=os.path.getmtime)[:-15]:
        try:
            os.remove(old)
        except OSError:
            pass


def install_code(sha):
    """Code-Stand von GitHub laden und nach APP legen (vorher sichern)."""
    data = http_get("https://codeload.github.com/%s/zip/%s" % (REPO, sha), 30)
    z = zipfile.ZipFile(io.BytesIO(data))
    files = {}
    for n in z.namelist():
        parts = n.split("/", 1)
        if len(parts) == 2 and parts[1] and not parts[1].endswith("/") and "/" not in parts[1]:
            files[parts[1]] = z.read(n)
    if "server.py" not in files or "orb_app.py" not in files:
        raise RuntimeError("Download unvollständig")
    backup()
    os.makedirs(APP, exist_ok=True)
    for name, content in files.items():
        with open(os.path.join(APP, name), "wb") as f:
            f.write(content)
    with open(os.path.join(APP, ".sha"), "w") as f:
        f.write(sha)


BAD = os.path.join(BASE, "gesperrt.txt")


def bad_shas():
    """Stände, die schon einmal kaputt waren – werden nie wieder automatisch installiert."""
    try:
        with open(BAD) as f:
            return [l.strip() for l in f if l.strip()]
    except Exception:
        return []


def mark_bad(sha):
    if sha and sha not in bad_shas():
        with open(BAD, "a") as f:
            f.write(sha + "\n")


def restore_latest():
    zips = sorted(glob.glob(os.path.join(BACKUPS, "ORB_*.zip")), key=os.path.getmtime, reverse=True)
    if not zips:
        return False
    with zipfile.ZipFile(zips[0]) as z:
        z.extractall(APP)
    os.remove(zips[0])  # diese Sicherung ist jetzt der laufende Stand
    return True


def shortcut(path, target, args="", desc="ORB"):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s'); $s.TargetPath='%s'; $s.Arguments='%s'; "
          "$s.WorkingDirectory='%s'; $s.IconLocation='%s,0'; $s.Description='%s'; $s.Save()"
          % (path, target, args, os.path.dirname(target), target, desc))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, creationflags=0x08000000)


def self_install():
    """Läuft die exe noch nicht aus dem Installationsordner: dorthin kopieren, Verknüpfungen anlegen, von dort starten."""
    if not FROZEN or os.path.normcase(sys.executable) == os.path.normcase(INSTALLED_EXE):
        return
    os.makedirs(BASE, exist_ok=True)
    try:
        shutil.copy2(sys.executable, INSTALLED_EXE)
    except PermissionError:
        pass  # installierte ORB.exe läuft gerade – ist schon da
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    shortcut(os.path.join(desk, "ORB.lnk"), INSTALLED_EXE)
    start_menu = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")
    shortcut(os.path.join(start_menu, "ORB.lnk"), INSTALLED_EXE)
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k not in ("_MEIPASS2", "_MEIPASS")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # frische Umgebung, sonst erbt die neue exe den gleich gelöschten Temp-Ordner
    subprocess.Popen([INSTALLED_EXE] + sys.argv[1:], env=env)
    sys.exit(0)


def update_if_needed(first_run):
    sha = remote_sha()
    if sha and sha != local_sha() and sha not in bad_shas():
        try:
            install_code(sha)
            return True
        except Exception as e:
            if first_run:
                message("ORB konnte nicht von GitHub geladen werden:\n%s\n\nBitte Internetverbindung prüfen." % e)
                sys.exit(1)
    elif first_run and not sha:
        message("ORB braucht beim ersten Start Internet, um sich von GitHub zu laden.")
        sys.exit(1)
    return False


def main():
    self_install()
    if "--zurueck" in sys.argv:
        restore_latest()
    first_run = not os.path.exists(os.path.join(APP, "orb_app.py"))
    if (first_run or "--neustart" not in sys.argv or "--update" in sys.argv) and "--zurueck" not in sys.argv:
        update_if_needed(first_run)
    sys.path.insert(0, APP)
    os.environ["ORB_EXE"] = sys.executable

    def load_code():
        """ORB-Code ausdrücklich aus dem App-Ordner laden – nie eine in die exe eingebaute alte Kopie."""
        import importlib.util
        for m in ("hook", "server", "orb_app"):
            sys.modules.pop(m, None)
        mod = None
        for name in ("hook", "server", "orb_app"):
            spec = importlib.util.spec_from_file_location(name, os.path.join(APP, name + ".py"))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        return mod

    def zurueck(e):
        kaputt = local_sha()
        if restore_latest():
            mark_bad(kaputt)
            message("Die neue ORB-Version hatte einen Fehler (%s).\nIch habe die letzte funktionierende Version wiederhergestellt." % e)
            return True
        message("ORB kann nicht starten: %s" % e)
        return False

    try:
        orb_app = load_code()
    except Exception as e:
        if not zurueck(e):
            sys.exit(1)
        orb_app = load_code()
    t0 = time.time()
    try:
        orb_app.main()
    except Exception as e:   # Fehler direkt beim Start (nicht nur beim Laden) → ebenfalls zurück
        if time.time() - t0 < 30 and zurueck(e):
            orb_app = load_code()
            orb_app.main()
        else:
            raise


if __name__ == "__main__":
    main()
