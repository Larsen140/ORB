"""Sperre für ORBs Gesprächs-Gehirn (Claude-Hook in Documents\\Jarvis\\.claude\\settings.json).
ORBs Gehirn soll den Programmcode nicht selbst ändern, bauen, kopieren oder ORB beenden – das hat ORB schon
mehrfach kaputt gemacht. Änderungswünsche gehen stattdessen an den Entwickler: entwickler.ps1."""
import json
import re
import sys

HINWEIS = ("Änderungen am ORB-Programm macht nicht das Gesprächs-Gehirn selbst. Gib den Wunsch an den Entwickler weiter: "
           "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\larse\\Orb\\entwickler.ps1 \"<Larsens Wunsch, "
           "möglichst genau>\" – und sag Larsen kurz, dass es beim Entwickler ist.")
try:
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "ignore").lstrip("\ufeff") or "{}")
except Exception:
    sys.exit(0)
tool, inp = data.get("tool_name", ""), data.get("tool_input") or {}


def block(was):
    sys.stderr.write("GESPERRT (%s). %s" % (was, HINWEIS))
    sys.exit(2)


ORB_PFAD = re.compile(r"[\\/]orb[\\/]|[\\/]ORB[\\/]app[\\/]", re.I)
if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    if ORB_PFAD.search(str(inp.get("file_path", "") or inp.get("notebook_path", ""))):
        block("ORB-Programmdateien ändern")
    sys.exit(0)

cmd = str(inp.get("command", ""))
if not cmd or re.search(r"entwickler\.ps1", cmd, re.I):
    sys.exit(0)
VERBOTEN = [
    (r"pyinstaller", "selbst eine exe bauen"),
    (r"(copy-item|rename-item|move-item|remove-item)[^\n]*orb(_alt\w*)?\.exe", "ORB.exe kopieren/umbenennen"),
    (r"stop-process[^\n]*\borb\b|taskkill[^\n]*orb\.exe|8766/quit", "ORB von Hand beenden"),
    (r"(set-content|add-content|out-file|writealltext|copy-item|move-item|remove-item|-replace)[^\n]*[\\/]orb[\\/]", "ORB-Programmdateien ändern"),
    (r"update\.ps1", "selbst veröffentlichen"),
    (r"(remove-item|rmdir|rd |del )[^\n]*documents[\\/]jarvis[\\/]?['\"]?(\s|$|-)", "ganze Wissensbasis löschen"),
]
for pattern, was in VERBOTEN:
    if re.search(pattern, cmd, re.I):
        block(was)
sys.exit(0)
