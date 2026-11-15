"""
Ideen-Sammler: "Jarvis, ich hab eine Idee: …" / "schreib auf die Ideenliste …" -> ideen.json (neben den Einstellungen).
Ideen vom Handy kommen als "notiere idee vom handy: …". Anschauen und löschen: HUD → Einstellungen → Allgemein → Meine Ideen.
"""
import json
import os
import re
import time


def _file() -> str:
    import pc_settings
    return os.path.join(os.path.dirname(pc_settings.path()), "ideen.json")


def all_() -> list:
    try:
        with open(_file(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def save(items: list):
    try:
        with open(_file(), "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=1)
    except Exception as e:
        print("Ideen speichern ging nicht:", e)


def add(text: str, von: str = "pc") -> str:
    t = text.strip().strip(" .,:;")
    if not t:
        return "Was ist die Idee?"
    items = all_()
    if any(i.get("text", "").lower() == t.lower() for i in items):
        return "Die steht schon auf deiner Ideenliste."
    items.append({"t": time.time(), "text": t, "von": von})
    save(items)
    return f"Steht auf deiner Ideenliste: „{t}“. Das ist Idee Nummer {len(items)}."


IDEA = re.compile(r"^(?:jarvis,?\s+)?(?:notiere idee( vom handy)?:\s*|ich hab(?:e)? (?:da )?(?:eine|ne|'ne) idee[,:]?\s*(?:und zwar[,:]?\s*)?|"
                  r"schreib (?:das )?auf (?:die|meine) ideen ?liste:?\s*|merk dir (?:als|eine) idee:?\s*|neue idee:?\s*)(.+)$", re.I)


def handle(text: str):
    m = IDEA.match(text.strip())
    if m and len(m.group(2).split()) >= 2:
        return add(m.group(2), "handy" if m.group(1) else "pc")
    if re.search(r"was (steht|ist) auf (meiner|der) ideen ?liste|meine ideen\b|lies (mir )?(meine )?ideen vor", text, re.I):
        items = all_()
        if not items:
            return "Deine Ideenliste ist noch leer."
        last = items[-5:]
        return f"Du hast {len(items)} Ideen. Die neuesten: " + "; ".join(i["text"] for i in reversed(last)) + "."
    return None
