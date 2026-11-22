"""
„Schick an die Gruppe“: einmal hinterlegen, welche Gruppe gemeint ist ("Die Gruppe heißt TR9000"), danach
erkennt Jarvis "die Gruppe" / "der Gruppe" / "unsere Gruppe" überall (Sticker, Sprachnachrichten, Nachrichten,
Vorlesen, Singen) als genau diesen Namen – ohne dass man ihn jedes Mal extra sagen muss.
"""
import re

import pc_settings

ALIAS = re.compile(r"^(die|der|unsere|unserer|unser)\s+gruppe$", re.I)
SET = re.compile(
    r"\b(?:die|unsere)\s+gruppe\s+(?:heißt|heisst|ist)\s+(.+)$|"
    r"\bmerk(?:e)?\s+dir\s+(?:die|unsere)\s+gruppe\s+(?:als|mit)?\s*(.+)$|"
    r"\bspeicher(?:e)?\s+(?:die|unsere)\s+gruppe\s+(?:als|mit)?\s*(.+)$",
    re.I,
)


def resolve(name: str) -> str:
    """"die Gruppe"/"unsere Gruppe" -> die hinterlegte Standard-Gruppe. Alles andere bleibt unverändert."""
    if name and ALIAS.match(name.strip()):
        g = str(pc_settings.load().get("default_gruppe") or "").strip()
        return g or name
    return name


def current() -> str:
    return str(pc_settings.load().get("default_gruppe") or "").strip()


def handle(command: str):
    """Sprachbefehl zum Hinterlegen der Standard-Gruppe -> Antwort oder None."""
    low = command.strip(" .!?,").lower()
    m = SET.search(low)
    if not m:
        return None
    frag = next(g for g in m.groups() if g)
    raw = command.strip(" .!?,")
    name = raw[-len(frag):].strip(" .") if raw.lower().endswith(frag.strip()) else frag.strip(" .")
    if not name:
        return None
    d = pc_settings.load()
    d["default_gruppe"] = name
    pc_settings.save(d)
    return f"Alles klar, „die Gruppe“ ist jetzt {name}. Du kannst jetzt einfach „schick an die Gruppe“ sagen."
