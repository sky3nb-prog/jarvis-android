"""
Abbrechen per Klick auf das X: hört auf zu sprechen, verwirft die laufende Aufnahme und die offene Antwort.
Jeder Teil merkt sich beim Start die "Generation" und prüft später, ob inzwischen abgebrochen wurde.
"""

GEN = 0
HOOKS: list = []  # Funktionen, die sofort etwas stoppen (z. B. die Sprachausgabe)


def cancel():
    global GEN
    GEN += 1
    for hook in list(HOOKS):
        try:
            hook()
        except Exception:
            pass


def changed(gen: int) -> bool:
    return GEN != gen
