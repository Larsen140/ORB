"""ORB.exe – bleibt immer dieselbe Datei.
Der eigentliche Code (orb_app.py, server.py, hook.py, index.html) liegt in C:\\Users\\larse\\Orb und wird beim Start
von dort geladen. Ein Update braucht deshalb nie eine neue exe: Dateien ändern, ORB neu starten (update.ps1).
Ist der Code kaputt, stellt der Starter automatisch die letzte Sicherung wieder her."""
import os
import sys

# Diese Importe sorgen nur dafür, dass alles Nötige in der exe steckt – der ORB-Code selbst wird erst zur Laufzeit geladen.
import array, asyncio, ctypes, datetime, difflib, glob, http.server, json, math, random, re, shutil, socket  # noqa
import socketserver, subprocess, tempfile, threading, time, urllib.parse, urllib.request, webbrowser, zipfile  # noqa
import certifi, edge_tts, psutil, sounddevice  # noqa

CODE = os.path.join(os.path.expanduser("~"), "Orb")
BACKUPS = os.path.join(CODE, "Sicherungen")


def restore_latest():
    """Neueste funktionierende Sicherung zurückspielen."""
    zips = sorted(glob.glob(os.path.join(BACKUPS, "ORB_v*.zip")), key=os.path.getmtime, reverse=True)
    if not zips:
        return False
    with zipfile.ZipFile(zips[0]) as z:
        z.extractall(CODE)
    return True


def message(text):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, "ORB", 0x40)
    except Exception:
        pass


sys.path.insert(0, CODE)
try:
    import orb_app
except Exception as e:
    if restore_latest():
        for m in ("orb_app", "server", "hook"):
            sys.modules.pop(m, None)
        message("ORBs Code hatte einen Fehler (%s).\nIch habe die letzte funktionierende Sicherung wiederhergestellt." % e)
        import orb_app
    else:
        message("ORB kann nicht starten: %s" % e)
        sys.exit(1)

orb_app.main()
