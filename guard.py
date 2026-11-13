"""Sperre für ORBs eigenes Gehirn (Claude-Hook in Documents\\Jarvis\\.claude\\settings.json).
Blockiert Befehle, die ORB kaputt machen können: selbst eine exe bauen, ORB.exe überschreiben/umbenennen,
ORB von Hand beenden/starten. ORB soll stattdessen update.ps1 benutzen."""
import json
import re
import sys

try:
    data = json.loads(sys.stdin.buffer.read().decode("utf-8", "ignore").lstrip("\ufeff") or "{}")
except Exception:
    sys.exit(0)
cmd = str((data.get("tool_input") or {}).get("command", ""))
if not cmd or "update.ps1" in cmd.lower():
    sys.exit(0)
VERBOTEN = [
    (r"pyinstaller", "selbst eine exe bauen"),
    (r"orb(_alt[\w]*)?\.exe['\"]?\s*(-destination|\s)|copy-item[^\n]*orb\.exe|rename-item[^\n]*orb\.exe|move-item[^\n]*orb\.exe", "ORB.exe kopieren/umbenennen"),
    (r"stop-process[^\n]*\borb\b|taskkill[^\n]*orb\.exe|/quit", "ORB von Hand beenden"),
]
for pattern, what in VERBOTEN:
    if re.search(pattern, cmd, re.I):
        sys.stderr.write(
            "GESPERRT (%s). ORB darf sich nicht selbst bauen, kopieren oder beenden – das hat ihn schon mehrfach kaputt gemacht. "
            "Nach Code-Änderungen in C:\\Users\\larse\\Orb IMMER nur ausführen: "
            "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\larse\\Orb\\update.ps1 "
            "(prüft, lädt zu GitHub hoch, ORB aktualisiert sich dann selbst)." % what)
        sys.exit(2)
sys.exit(0)
