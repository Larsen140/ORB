"""ORB-Hook: Claude Code ruft dieses Skript bei Ereignissen auf.
Schreibt den aktuellen Zustand in state.json, den die Kugel-Seite liest.
Gibt nichts aus und beendet sich immer mit 0, damit Claude Code nie blockiert."""
import json
import os
import re
import sys
import time

STATE = os.path.join(os.path.expanduser("~"), "Orb", "state.json")
ORB_RUN = os.environ.get("ORB_RUN") == "1"  # von ORB selbst gestartetes Claude

LABELS = {
    "Read": "Lese Datei",
    "Write": "Schreibe Datei",
    "Edit": "Bearbeite Datei",
    "MultiEdit": "Bearbeite Datei",
    "NotebookEdit": "Bearbeite Notebook",
    "PowerShell": "Führe Befehl aus",
    "Bash": "Führe Befehl aus",
    "Grep": "Durchsuche Inhalte",
    "Glob": "Suche Dateien",
    "WebFetch": "Lade Webseite",
    "WebSearch": "Recherchiere im Web",
    "Agent": "Starte Unteragent",
    "Task": "Starte Unteragent",
    "Artifact": "Veröffentliche Seite",
    "Skill": "Lade Fähigkeit",
    "TodoWrite": "Plane Aufgaben",
    "ToolSearch": "Lade Werkzeug",
}


def load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seq": 0, "mode": "idle", "log": []}


def save(st):
    st["seq"] = int(st.get("seq", 0)) + 1
    st["time"] = time.time()
    tmp = "%s.%d.tmp" % (STATE, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    for i in range(20):
        try:
            os.replace(tmp, STATE)
            return
        except PermissionError:
            time.sleep(.02 * (i + 1))
    try:
        os.remove(tmp)
    except OSError:
        pass


def label_for(tool):
    if tool in LABELS:
        return LABELS[tool]
    if tool.startswith("mcp__"):
        parts = tool.split("__")
        return "Nutze " + (parts[1].replace("claude_ai_", "").replace("_", " ") if len(parts) > 1 else "Dienst")
    return tool


def detail_for(inp):
    if not isinstance(inp, dict):
        return ""
    for k in ("file_path", "notebook_path", "path"):
        if inp.get(k):
            p = str(inp[k]).rstrip("/\\")
            return os.path.basename(p) or p
    for k in ("description", "query", "pattern", "url", "skill", "command", "prompt"):
        if inp.get(k):
            return str(inp[k]).replace("\n", " ")[:90]
    return ""


def last_text(data):
    m = data.get("last_assistant_message")
    if isinstance(m, str) and m.strip():
        return m
    p = data.get("transcript_path")
    if not p or not os.path.exists(p):
        return ""
    time.sleep(0.3)  # Transkript kurz fertig schreiben lassen
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        f.seek(max(0, size - 3_000_000))
        lines = f.read().decode("utf-8", "ignore").splitlines()
    for line in reversed(lines):
        try:
            e = json.loads(line.lstrip("﻿"))
        except Exception:
            continue
        if e.get("type") != "assistant":
            continue
        c = (e.get("message") or {}).get("content")
        if isinstance(c, str) and c.strip():
            return c
        if isinstance(c, list):
            t = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            if t.strip():
                return t
    return ""


def clean(t):
    """Macht aus Markdown vorlesbaren Text."""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`\n]{1,40})`", r"\1", t).replace("`", "")
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "Link", t)
    out = []
    for ln in t.splitlines():
        s = ln.strip()
        if not s or s.startswith("|") or re.fullmatch(r"[-=_*|:\s]+", s):
            continue
        s = re.sub(r"^#+\s*", "", s)
        s = re.sub(r"^>\s*", "", s)
        s = re.sub(r"^[-*•]\s+", "", s)
        s = s.replace("**", "").replace("__", "")
        s = re.sub(r"(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", s)
        if s and s[-1] not in ".!?:;,…":
            s += "."
        out.append(s)
    t = " ".join(out)
    t = re.sub(r"[\U0001F000-\U0001FAFF←-⇿⌀-⏿☀-➿⬀-⯿️‍]", "", t)
    t = t.replace("→", " ").replace("←", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([.,!?:;])", r"\1", t)
    if len(t) > 700:
        cut = t[:700]
        i = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = cut[: i + 1] if i > 200 else cut + " …"
    return t


_ABK = {"z", "b", "d", "h", "u", "a", "o", "s", "v", "ca", "bzw", "usw", "etc", "evtl", "ggf", "inkl", "exkl", "vgl", "nr",
        "dr", "prof", "hr", "fr", "st", "str", "tel", "mio", "mrd", "std", "min", "sek", "max", "zb", "bspw", "allg",
        "ggü", "jh", "jhd", "abs", "art", "bd", "kap", "mr", "mrs", "ms", "no", "vs", "dt", "engl", "ital", "franz"}
_MONATE = {"januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november",
           "dezember", "jan", "feb", "mär", "apr", "jun", "jul", "aug", "sep", "sept", "okt", "nov", "dez"}


def satz_grenzen(t, komma=False):
    """Stellen (Index nach dem Satzzeichen), an denen der Text sauber in Sprech-Stücke geteilt werden darf.
    Nicht bei Abkürzungen („z. B.“, „Dr.“), Datumsangaben („13. November“) oder wenn klein weitergeschrieben wird –
    sonst spricht die Stimme mitten im Satz mit Schluss-Betonung und Pause."""
    out = []
    for m in re.finditer(r"[.!?…:;,](?=\s)" if komma else r"[.!?…:;](?=\s)", t):
        z, rest = m.group(), t[m.end():].lstrip()
        nxt = rest[:1]
        if z != "," and nxt.islower():
            continue   # „… ca. zehn“, „Achtung: das …“ – Satz geht weiter
        if z == ".":
            w = re.search(r"([\wäöüÄÖÜß]+)$", t[:m.start()])
            w = w.group(1) if w else ""
            if w.lower() in _ABK or (len(w) == 1 and w.isalpha()):
                continue
            if w.isdigit() and re.match(r"[\wäöüÄÖÜß]+", rest) and                     re.match(r"[\wäöüÄÖÜß]+", rest).group().lower() in _MONATE:
                continue   # „am 13. November“
        out.append(m.end())
    return out


def split_sentences(t, first_min=12, chunk_min=260):
    """Teilt Text in sprechbare Stücke: erster Satz sofort, danach größere Stücke für flüssigen Klang."""
    sents, a = [], 0
    for e in satz_grenzen(t) + [len(t)]:
        if t[a:e].strip():
            sents.append(t[a:e].strip())
        a = e
    parts, cur = [], ""
    for s in sents:
        cur = (cur + " " + s).strip()
        if len(cur) >= (first_min if not parts else chunk_min):
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    return parts


def main():
    raw = sys.stdin.buffer.read().decode("utf-8", "ignore").lstrip("﻿")
    data = json.loads(raw) if raw.strip() else {}
    ev = data.get("hook_event_name", "")
    if os.environ.get("ORB_BG") == "1":
        return   # Hintergrund-Aufgaben/Entwickler haben ihr eigenes Hologramm – ORBs Hauptanzeige nicht anfassen
    if not ORB_RUN:
        return   # andere Claude-Code-Sitzungen (Terminal, Entwickler) dürfen ORBs Anzeige und Antworten nicht überschreiben
    st = load()
    log = st.get("log") or []

    if ev in ("SessionStart", "SessionEnd"):
        if ORB_RUN:
            return   # Gehirn-Start/-Ende soll ORBs Anzeige nicht auf „Bereit“ zurücksetzen
        st.update(mode="idle", log=[], task="", detail="", say="")
    elif ev == "UserPromptSubmit":
        if ORB_RUN:
            st.update(mode="denkt", log=[], task="", detail="")  # ORB-Server verwaltet die Antwort selbst
        else:
            st.update(mode="denkt", log=[], task="", detail="", say="", parts=[], aid="")
    elif ev == "PreToolUse":
        tool = data.get("tool_name", "")
        task, detail = label_for(tool), detail_for(data.get("tool_input"))
        log = (log + [task + (": " + detail if detail else "")])[-8:]
        st.update(mode="auftrag", task=task, detail=detail, log=log, tool_n=int(st.get("tool_n", 0)) + 1)
    elif ev == "PostToolUse":
        if st.get("mode") != "wartet":
            return  # nur nach einer Freigabe zurückschalten
        st.update(mode="auftrag")
    elif ev == "Notification":
        msg = str(data.get("message", ""))
        ntype = str(data.get("notification_type", ""))
        if "idle" in ntype or "waiting for your input" in msg.lower():
            return
        st.update(mode="wartet", task="Freigabe nötig", detail=msg[:120])
    elif ev == "Stop":
        if ORB_RUN:
            return  # ORB-Server spricht die Antwort schon während sie entsteht
        say = clean(last_text(data))
        st.update(mode="spricht", say=say, parts=split_sentences(say), aid="h%d" % (int(st.get("seq", 0)) + 1), final=True)
    else:
        return
    save(st)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
