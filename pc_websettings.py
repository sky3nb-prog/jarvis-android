"""
Einstellungen für das neue HUD (Webseite im Edge-Fenster), im Stil der Handy-App.

schema(settings)  -> {"tabs": [...], "values": {...}}   Aufbau und aktuelle Werte für die Seite
save(settings, v) -> neues Einstellungs-Dict             Werte der Seite zurück ins Format von pc_settings
run(ui, name, v)  -> {"ok": bool, "text": str}           Knöpfe (Stimme testen, KI testen, Code kopieren …)

Schlüssel werden wie im alten Fenster mit Windows verschlüsselt (pc_secret) und nie an die Seite zurückgegeben:
die Seite bekommt nur "gespeichert" / "leer". Ein leeres Feld beim Speichern heißt: alten Schlüssel behalten.
"""

import os
import threading
import time

import pc_settings

# Felder vom Typ "secret": Schlüssel in der Seite -> gespeichertes Feld
SECRETS = {"steam_api_key": "steam_api_key_enc", "eleven_key": "eleven_key_enc", "groq_key": "groq_key_enc", "telegram_token": "telegram_token_enc"}
LISTS = {"lage_places": 8, "themen_selbst": 12, "discord_channels": 30}


def _opts(pairs):
    return [[n, v] for n, v in pairs]


def FERN_STATUS() -> str:
    try:
        import pc_fern
        import pc_ets2
        ip = pc_fern.tailscale_ip()
        t = (f"Tailscale läuft, dein PC hat die Adresse {ip}." if ip else "Tailscale ist auf diesem PC noch nicht aktiv.")
        return t + (f" ETS2: {pc_ets2.PLUGIN_STATUS}." if pc_ets2.PLUGIN_STATUS else "")
    except Exception:
        return ""


def _same(names):
    return [[n, n] for n in names]


# Neue Einstellungen (bekommen einen kleinen Punkt, bis du den Bereich einmal angeschaut hast). Bei jedem Update ergänzen.
# Dazu kommen automatisch alle Einstellungen, die ein Update neu mitbringt (pc_settings: auto_new).
NEW = ["test_chat", "stil_chats", "discord_server", "piper_voice","sticker_wahl", "schulkal_pc", "ideen_pc", "stundenplan_pc", "voice_engine", "boot_animation", "msg_ask_first", "kommentare", "lieblingskanaele"]
_shown = None   # Kennungen, die es in den Einstellungen wirklich als Feld gibt


def _fields() -> set:
    global _shown
    if _shown is None:
        import re
        try:
            src = open(os.path.abspath(__file__), encoding="utf-8").read()
            _shown = set(re.findall(r'\b(?:sw|tx|sel|rng|sec)\(\s*"(\w+)"', src)) | {"piper_voice", "sticker_wahl", "stundenplan_pc", "schulkal_pc", "ideen_pc", "steam_api_key", "pause_lang"}
        except Exception:
            _shown = set()
    return _shown


def unseen(s: dict) -> list:
    seen = set(s.get("seen_new") or [])
    keys = list(dict.fromkeys(NEW + list(s.get("auto_new") or [])))
    f = _fields()
    return [k for k in keys if k not in seen and (not f or k in f)]


def schema(s: dict) -> dict:
    import pc_audio
    import pc_eleven
    import pc_settingsui as su
    d = pc_settings.DEFAULTS
    g = lambda k, dflt=None: s.get(k, d.get(k, dflt))  # noqa: E731

    try:
        mics = _opts(su.device_choices("input"))
        outs = _opts(su.device_choices("output"))
    except Exception:
        mics, outs = [[su.DEFAULT_IN, None]], [[su.DEFAULT_OUT, None]]
    try:
        winv = [[su.AUTO_WINDOWS, ""]] + _same(pc_audio.windows_voices())
    except Exception:
        winv = [[su.AUTO_WINDOWS, ""]]
    voices = list(pc_eleven.DEFAULT_VOICES)
    if g("eleven_voice") and g("eleven_voice") not in [v for _, v in voices]:
        voices.append((g("eleven_voice_name") or g("eleven_voice"), g("eleven_voice")))
    try:
        import pc_themen
        gelernt = ", ".join(t.get("name", "") for t in pc_themen.learned()) or "noch nichts – frag Jarvis einfach Dinge"
    except Exception:
        gelernt = "–"
    try:
        import pc_link
        link_code, link_status = pc_link.code(), pc_link.STATUS or ""
    except Exception:
        link_code, link_status = "", ""
    try:
        import pc_memory
        profile = [(k, n, pc_memory.profile(k)) for k, n in pc_memory.PROFILE_FIELDS]
    except Exception:
        profile = []

    def sw(k, t, h=""):
        return {"k": k, "t": "sw", "l": t, "h": h}

    def tx(k, t, h="", ph=""):
        return {"k": k, "t": "text", "l": t, "h": h, "ph": ph}

    def sel(k, t, opts, h=""):
        return {"k": k, "t": "sel", "l": t, "o": opts, "h": h}

    def rng(k, t, lo, hi, unit="", h=""):
        return {"k": k, "t": "range", "l": t, "min": lo, "max": hi, "u": unit, "h": h}

    def sec(k, t, h=""):
        return {"k": k, "t": "secret", "l": t, "h": h}

    def btn(a, t):
        return {"t": "btn", "a": a, "l": t}

    def note(t):
        return {"t": "note", "l": t}

    def card(title, *items):
        return {"t": "card", "l": title, "items": list(items)}

    tabs = [
        {"id": "allg", "n": "Allgemein", "i": "☺", "items": [
            card("Über dich",
                 tx("assistant_name", "Name des Assistenten", "Steht im HUD und so stellt er sich vor."),
                 tx("address_as", "Anrede", "Wie er dich anspricht, z. B. Sir oder dein Name. Leer = keine Anrede."),
                 sel("persona", "Art", _opts(su.PERSONAS), "Wie er redet. Er merkt sich, was du ihm erzählst.")),
            card("Start",
                 sw("autostart", "Mit Windows starten", "Leise im Hintergrund"),
                 sw("greet_on_start", "Beim Start kurz begrüßen"),
                 sw("show_hud_on_start", "HUD beim Start öffnen"),
                 sw("boot_animation", "Iron-Man-Start nach dem Anmelden", "Vollbild-Hologramm mit Systemstatus. Testen: „Friday, Startanimation“"),
                 sw("confirm_messages", "Nachrichten vor dem Senden zurückfragen", "WhatsApp, Discord"),
                 sw("msg_ask_first", "Nachrichten wichtiger Leute: erst fragen", "„Neue Nachricht von Mama – weiter oder egal?“ Bei „egal“ ignoriert er sie."),
                 sw("kommentare", "Von selbst melden", "Z. B. nach über 2 Stunden am Stück: „Kurz raus und bewegen?“ – persönlich, lernt mit."),
                 tx("lieblingskanaele", "Lieblingskanäle (neue Videos melden)", "YouTube-Kanäle mit Komma. Außerdem meldet er sich bei voller Festplatte, heißer Grafikkarte und Steam-Angeboten von deiner Wunschliste.", "Kanalname")),
            card("Discord",
                 tx("discord_channels", "Sprachkanäle", "Genaue Namen mit Komma, auch mit Emoji, z. B. 🎮|Zocken, 💬|Quatschen."),
                 btn("custom", "Eigene Befehle bearbeiten (Programme, Ordner, Webseiten)")),
        ]},
        {"id": "hoer", "n": "Zuhören", "i": "◉", "items": [
            card("Aktivierung",
                 tx("wake_words", "Aktivierungswort", "Mehrere Schreibweisen mit Komma, z. B. jarvis, dscharvis"),
                 sel("language", "Sprache", _opts(su.LANGUAGES)),
                 sel("input_device", "Mikrofon", mics, "Wirkt sofort nach dem Speichern."),
                 rng("followup_seconds", "Weiterhören nach einem Befehl", 0, 15, " s", "0 = aus"),
                 rng("pause_lang", "Nachdenkpause beim Reden", 1, 4, " s", "So lange darfst du nach dem Aktivierungswort zwischendurch Pause machen, bevor ich antworte. Für lange Sachen höher stellen.")),
        ]},
        {"id": "stim", "n": "Stimme", "i": "♪", "items": [
            card("Sprechen",
                 sw("speak", "Antworten laut sprechen"),
                 sel("voice_engine", "Stimmenart", _opts(su.ENGINES), "Klappt ElevenLabs nicht, nimmt er die Online-Stimme."),
                 sel("piper_voice", "Schnelle Stimme", _opts(__import__("pc_piper").VOICES), "Für „Schnell“. Eine neue Stimme lädt er beim ersten Testen einmal (10–60 MB), dann geht sie sofort."),
                 sel("output_device", "Ausgabe", outs, "Z. B. ein Kanal von Elgato Wave Link."),
                 rng("voice_volume", "Lautstärke der Stimme", 10, 100, " %"),
                 rng("voice_pitch", "Tonhöhe", -10, 10),
                 rng("voice_rate", "Sprechtempo", -10, 10),
                 btn("test_voice", "▶ Stimme testen")),
            card("Gaming-Rückblick",
                 note("Jarvis merkt sich, was du wie lange zockst, und sagt dir sonntags um 19 Uhr deinen Wochenrückblick (oder auf Frage: „Gaming-Rückblick“)."),
                 sec("steam_api_key", "Steam-Schlüssel (freiwillig, für Erfolge)", "Holst du dir selbst auf steamcommunity.com/dev/apikey – nur dann kann er deine neuen Erfolge nennen.")),
            card("Discord & Clips",
                 sw("discord_hoerbar", "Jarvis in Discord hörbar", "Spielt seine Stimme zusätzlich auf dein Discord-Mikro – Freunde hören ihn, und er ist in Discord-Clips mit drauf."),
                 sel("discord_device", "Zweites Gerät", [["– aus –", ""]] + outs[1:] if outs else [["– aus –", ""]],
                     "Ein Ausgang, der in dein Discord-Mikro geht: bei Wave Link z. B. der Kanal, der im Stream-/Chat-Mix landet, sonst ein virtuelles Kabel (VB-CABLE: hier „CABLE Input“, in Discord als Mikro „CABLE Output“)."),
                 note("Damit Discord überhaupt clippen kann: in Discord → Einstellungen → Registrierte Spiele → „Hinzufügen!“ → PC-Assistent."),
                 tx("discord_server", "Discord-Server für „Wer ist online?“", "Server-ID: in Discord Einstellungen → Erweitert → Entwicklermodus an, dann Rechtsklick auf den Server → „Server-ID kopieren“. Und in den Server-Einstellungen → Widget → „Server-Widget aktivieren“. Kein Bot, keine Anmeldung.", "z. B. 123456789012345678")),
            card("ElevenLabs",
                 sec("eleven_key", "ElevenLabs-Schlüssel", "elevenlabs.io → Entwickler → API-Schlüssel. Wird verschlüsselt gespeichert."),
                 sel("eleven_voice", "Stimme", _opts(voices)),
                 sel("eleven_model", "Modell", _opts(pc_eleven.MODELS)),
                 btn("el_load", "Stimmen aus dem Konto laden")),
            card("Ersatzstimmen",
                 sel("edge_voice", "Online-Stimme", _opts(pc_audio.EDGE_VOICES)),
                 sel("windows_voice", "Windows-Stimme", winv)),
            card("Wecksound",
                 rng("chime_volume", "Lautstärke", 0, 100, " %"),
                 sw("early_chime", "Schon beim Weckwort", "nicht erst am Satzende")),
        ]},
        {"id": "lage", "n": "Lage", "i": "◍", "items": [
            card("Orte",
                 tx("home_city", "Standort", "Mitte der Karte und Ort für lokale Nachrichten."),
                 tx("home_address", "Adresse", "Für den Zuhause-Punkt und als Startpunkt für Routen."),
                 tx("lage_places", "Lieblingsorte", "Mit Komma, z. B. Seoul, New York. Stehen oben auf der Lage-Seite."),
                 tx("themen_selbst", "Eigene Themen (Für dich)", f"Mit Komma. Dazu lernt Jarvis selbst. Gelernt: {gelernt}")),
            card("Globus",
                 sw("lage_spin", "Erde langsam drehen", "Mit echtem Tag und Nacht"),
                 sw("lage_orbits", "Echte Satelliten", "ISS, Hubble … beim Rauszoomen"),
                 sw("map_labels", "Ortsnamen auf der Karte"),
                 sw("lage_sat_tour", "Beim Briefing zu den Orten fliegen")),
            card("Briefing",
                 sw("globe_auto_open", "Bei „Wie ist die Lage?“ zur Lage springen"),
                 sw("briefing_on_start", "Beim Start ein kurzes Briefing sprechen")),
        ]},
        {"id": "wege", "n": "Wege", "i": "➜", "items": [
            card("Meine Orte",
                 note("Eine Zeile pro Ort: Name, Doppelpunkt, Adresse. Dann reicht „Ich will zu Opa“. Gilt auch am Handy."),
                 {"k": "meine_orte", "t": "area", "l": "Orte", "ph": "Oma: Musterstraße 5, 12345 Musterstadt\nArbeit: …"}),
            card("Meine Wege",
                 note("Ein Punkt, über den der Weg führen soll: Name, Doppelpunkt, Ort oder Koordinaten (in Google Maps rechts klicken, Zahlen kopieren). "
                      "Dann geht „über den oberen Feldweg zu Opa“."),
                 {"k": "meine_wege", "t": "area", "l": "Wege", "ph": "Waldweg: 52.5000, 13.4000"}),
            card("Routen schicken",
                 tx("route_an", "Google-Maps-Link per WhatsApp an", "Name aus deinen Kontakten, leer = an niemanden. Gilt auch am Handy."),
                 note("Fragst du am PC, öffnet sich die Route am PC und auf dem Handy, und der PC schickt den Link per WhatsApp.")),
        ]},
        {"id": "leute", "n": "Leute", "i": "☺", "items": [
            card("Schreibstil & Antworten",
                 note("Wie am Handy unter Leute → Schreibstil – alles hier gilt auf beiden Geräten."),
                 sel("stil_modus", "Darf Jarvis in deinem Namen antworten?", [["Aus", "aus"], ["Vorschlag – du sagst/tippst ja", "bestaetigen"], ["Selbst schreiben (erst nach dem Stil-Training am Handy)", "selbst"]],
                     "Gilt nur für die Chats darunter."),
                 tx("stil_chats", "Für diese Chats", "Namen wie in WhatsApp, mit Komma. Per Sprache: „Du darfst Alex selbst antworten“ / „Antworte Alex nicht mehr“.", "z. B. Tobi, Marius"),
                 tx("wa_name", "Dein Name in WhatsApp-Exporten", "So stehst du in exportierten Chats (z. B. „Sky“). Leer = ich erkenne es selbst – bei Gruppen brauch ich ihn.", "z. B. Sky"),
                 tx("test_chat", "Test-Chat (z. B. deine Zweitnummer)", "Nachrichten aus diesem Chat liest Jarvis immer vor – auch wenn WhatsApp offen ist oder keiner am PC sitzt. Kleine Tippfehler im Kontaktnamen sind egal.", "Name wie in WhatsApp"),
                 btn("stil_import", "WhatsApp-Chat-Export wählen (ZIP direkt, nicht entpacken)"),
                 btn("stil_list", "Welche Chats sind schon drin?"),
                 btn("test_handy", "Test: Verbindung zum Handy"),
                 btn("test_ansage", "Test: Nachricht aus dem Test-Chat ansagen"),
                 btn("test_sprach", "Test: Sprachnachricht an den Test-Chat schicken (über WhatsApp am PC)"),
                 note("Export: in WhatsApp Chat öffnen → ⋮ → Mehr → „Chat exportieren“. „Mit Medien“ = er hört auch die Sprachnachrichten an (bis 120 pro Chat). Mehrere ZIPs auf einmal gehen. Nur was innerhalb von 6 Stunden geantwortet wurde, zählt als Antwort. Am Handy lernt er außerdem mit jeder Nachricht und beim Durchscrollen.")),
            card("Wichtige Leute",
                 tx("wichtige_leute", "Namen wie in WhatsApp", "Mit Komma, z. B. Mama, Papa, bester Freund. Gilt auch am Handy."),
                 tx("wa_immer", "Immer vorlesen", "Diese Chats liest er IMMER vor – auch beim Zocken, wenn WhatsApp offen ist oder im Fokus-Modus. Gilt auch am Handy.", "z. B. Mama"),
                 sel("wa_beim_zocken", "Beim Zocken / Discord", [["Trotzdem ansagen", "ansagen"], ["Sammeln und danach sagen", "sammeln"], ["Gar nicht ansagen", "nie"]],
                     "„Immer vorlesen“-Chats und der Test-Chat kommen trotzdem durch."),
                 note("Schreiben sie dir, sagt Jarvis es hier an – auch mitten im Spiel. Sprachnachrichten: „vorlesen“ oder „abspielen“. "
                      "Danach: „antworte du“ (Vorschlag, du sagst ja oder nein) oder „ich antworte“ (du diktierst). "
                      "Gesendet wird über die Benachrichtigung am Handy, WhatsApp geht nicht auf.")),
            card("Sticker",
                 {"t": "sticker", "k": "sticker_wahl"},
                 note("Sag „Schick 200 Sticker in die Gruppe TR9000“ oder „… an Max“ – am PC oder am Handy. Er fragt einmal nach und schickt dann "
                      "den ausgewählten Sticker über WhatsApp am PC (höchstens 1000, mit kleinen Pausen). „Stopp“ hält ihn an. "
                      "Solange er schickt, nicht wegklicken – sobald ein anderes Fenster vorne ist, hört er sofort auf.")),
            card("Anruf-Butler",
                 tx("absage_text", "Absage-Text", "Leer = „Kann gerade nicht, rufe später zurück.“ Gilt auch am Handy."),
                 note("Steht das Handy auf „Nicht stören“, drückt Jarvis Anrufe aus deinen Kontakten weg und schickt diesen Text – "
                      "per WhatsApp hier am PC, wenn er läuft, sonst per SMS. Ein- und ausschalten in der Handy-App.")),
        ]},
        {"id": "fern", "n": "Fernzugriff", "i": "⌁", "items": [
            card("Von unterwegs (Tailscale)",
                 note("Einmal einrichten: Tailscale auf PC und Handy installieren (tailscale.com, kostenlos) und auf beiden mit demselben "
                      "Konto anmelden. Dann zeigt die Handy-App unter Einstellungen → PC & Fernzugriff die Knöpfe für HUD, Webcam und Handy-Kamera. "
                      "Nur deine eigenen Geräte im Tailscale-Netz mit deinem Kopplungscode kommen rein. Beim ersten Mal fragt die "
                      "Windows-Firewall – auf „Zulassen“ klicken."),
                 note(FERN_STATUS()),
                 sw("webcam_fern", "Webcam von unterwegs ansehen erlauben",
                    "Standard aus. Solange jemand zuschaut, steht das groß am Bildschirm. Sag deiner Familie Bescheid.")),
            card("ETS2-Beifahrer",
                 note("Liest Tank, Ziel, Ruhezeit und Auftrag aus dem Spiel (Telemetrie-Plugin, wird automatisch in ETS2 installiert; "
                      "beim nächsten Spielstart einmal die Meldung zu den SDK-Funktionen mit OK bestätigen). Die Fahrt steht im HUD unter INFO."),
                 tx("ets2_quicksave", "Taste fürs Schnellspeichern", "Wird gedrückt, bevor der PC herunterfährt, weil du weg bist. Standard f5.")),
        ]},
        {"id": "anz", "n": "Anzeige", "i": "◐", "items": [
            card("HUD",
                 {"k": "hud_layout", "t": "choice", "l": "Aufbau", "o": [
                     ["PC-Stil", "pc", "Leiste oben, wie bisher"],
                     ["Handy-Stil", "handy", "Fokus · Info · Lage · Steuern unten"]],
                  "h": "Handy-Stil: gleicher Aufbau wie die App, mit der Seite „Steuern“ für dein Handy."},
                 sel("hud_mode", "Modus beim Start", _opts(su.HUD_MODES[:3]) + [["Steuern – dein Handy fernsteuern", "steuern"]]),
                 sel("hud_style", "Stil", _opts(su.HUD_STYLES), "Wirkt nach einem Neustart von Jarvis."),
                 sel("sphere_color", "Farbe der Kugel", _same(su.SPHERE_COLORS)),
                 sw("hud_topmost", "Immer im Vordergrund"),
                 sw("hud_animation", "Animationen", "Aus = ruhiger und sparsamer"),
                 btn("farbe_open", "Deine Farbe (Farbkreis, Helligkeit, Kräftigkeit)")),
            card("Beim Weckwort",
                 sel("overlay_style", "Anzeige", _opts(su.STYLES)),
                 rng("orb_size", "Größe", 40, 120, " px"),
                 sel("orb_corner", "Ecke", _same(pc_settings.CORNERS)),
                 sel("accent", "Farbe", _same(list(pc_settings.THEMES)))),
        ]},
        {"id": "kn", "n": "Knöpfe", "i": "▣", "items": [
            card("Schnellstart-Knöpfe",
                 note("Bis zu 12 Knöpfe im HUD: Symbol, Name und Befehl (das, was du sonst zu Jarvis sagen würdest)."),
                 {"k": "hud_buttons", "t": "buttons", "n": su.BUTTON_SLOTS}),
        ]},
        {"id": "inf", "n": "Infos", "i": "☀", "items": [
            card("Wetter",
                 sw("show_weather", "Wetter anzeigen"),
                 tx("weather_city", "Ort für das Wetter")),
            card("Kalender",
                 {"k": "calendar_url", "t": "text", "l": "Kalender-Adresse", "pw": True,
                  "h": "Google Kalender → Einstellungen → „Privatadresse im iCal-Format“. Mehrere mit Semikolon."},
                 sw("announce_events", "Beim Start die Termine von heute ansagen"),
                 btn("test_cal", "Kalender testen"),
                 btn("classic", "TimeTree und Google-Abgleich einrichten …")),
            card("PC",
                 sw("show_performance", "Leistung anzeigen", "CPU, RAM, GPU"),
                 sw("show_pc_temps", "Temperaturen anzeigen"),
                 sw("show_notifications", "Benachrichtigungen anzeigen", "liest den Windows-Verlauf nur lokal")),
        ]},
        {"id": "ki", "n": "KI", "i": "✦", "items": [
            card("Gemini",
                 note("Mit einem Gemini-Schlüssel versteht Jarvis freie Sätze. Kostenlos auf aistudio.google.com/apikey."),
                 {"k": "gemini_api_key", "t": "text", "l": "Gemini-Schlüssel", "pw": True, "h": "Nie in Chats oder Mails weitergeben."},
                 btn("test_ai", "Verbindung testen")),
            card("Groq (kostenloser Ersatz)",
                 sec("groq_key", "Groq-Schlüssel (kostenloser Ersatz)", "console.groq.com → API Keys. Springt ein, wenn Gemini nicht geht."),
                 btn("test_groq", "Groq testen")),
            card("Hinweis", note("Was du frei sagst, geht zur Beantwortung an Google bzw. Groq. Sag keine Passwörter oder Privates.")),
        ]},
        {"id": "dat", "n": "Meine Daten", "i": "✎", "items": [
            card("Zum Ausfüllen von Formularen",
                 note("„Trag bitte meine E-Mail ein.“ Bleibt nur auf diesem PC. Passwörter gehören nicht hierher."),
                 *[tx("profil_" + k, n) for k, n, _ in profile]),
        ]},
        {"id": "schule", "n": "Schule", "i": "▦", "items": [
            card("Stundenplan", {"t": "plan", "k": "stundenplan_pc"},
                 note("Tipp auf eine Stunde und trag das Fach ein – wird sofort gespeichert und landet auf dem Handy. "
                      "Dort nutzt Jarvis den Plan: in der Stunde still, Nachrichten erst in der Pause.")),
            card("Arbeiten & Hausaufgaben", {"t": "schulkal", "k": "schulkal_pc"},
                 note("Tag anklicken zum Eintragen. Was in schul.cloud am Handy reinkommt, trägt Jarvis selbst ein. "
                      "Er erinnert dich rechtzeitig und fragt dich vor Arbeiten ab, wenn du willst („frag mich ab“).")),
        ]},
        {"id": "ideen", "n": "Ideen", "i": "✧", "items": [
            card("Meine Ideen", {"t": "ideen", "k": "ideen_pc"},
                 note("Sag „Jarvis, ich hab eine Idee: …“ – am PC oder am Handy. Hier stehen alle.")),
        ]},
        {"id": "hdy", "n": "Handy", "i": "✆", "items": [
            card("Handy-App koppeln",
                 note("In der Jarvis-App auf ⚙ → Kopplungscode vom PC eintragen. Alles geht verschlüsselt. Code nicht weitergeben."),
                 {"t": "code", "l": "Kopplungscode", "v": link_code},
                 btn("copy_link", "Code kopieren"),
                 btn("new_link", "Neuen Code erzeugen (alte Kopplung endet)"),
                 note(link_status)),
        ]},
    ]

    tabs = _ordnen(tabs, card)

    values = {
        "assistant_name": g("assistant_name"), "address_as": g("address_as"), "persona": g("persona"),
        "autostart": bool(g("autostart")), "greet_on_start": bool(g("greet_on_start")),
        "show_hud_on_start": bool(g("show_hud_on_start")), "pause_lang": g("pause_lang"), "boot_animation": bool(g("boot_animation")), "msg_ask_first": bool(g("msg_ask_first")), "kommentare": bool(g("kommentare")), "lieblingskanaele": g("lieblingskanaele"), "confirm_messages": bool(g("confirm_messages")),
        "wake_words": ", ".join(g("wake_words") or []), "language": g("language"),
        "input_device": g("input_device") if not isinstance(g("input_device"), int) else pc_audio.device_name(g("input_device")),
        "output_device": g("output_device") if not isinstance(g("output_device"), int) else pc_audio.device_name(g("output_device")),
        "discord_hoerbar": bool(g("discord_hoerbar")), "discord_device": g("discord_device") or "",
        "followup_seconds": g("followup_seconds"), "speak": bool(g("speak")), "voice_engine": g("voice_engine"), "piper_voice": g("piper_voice") or "de_DE-thorsten-medium",
        "voice_volume": s.get("voice_volume", 100), "voice_pitch": g("voice_pitch"), "voice_rate": g("voice_rate"),
        "eleven_voice": g("eleven_voice"), "eleven_model": g("eleven_model"), "edge_voice": g("edge_voice"),
        "windows_voice": g("windows_voice") or "", "chime_volume": g("chime_volume"), "early_chime": bool(g("early_chime")),
        "home_city": g("home_city") or "", "home_address": g("home_address") or "",
        "lage_spin": bool(s.get("lage_spin", True)), "lage_orbits": bool(s.get("lage_orbits", True)),
        "map_labels": bool(g("map_labels")), "lage_sat_tour": bool(g("lage_sat_tour")),
        "globe_auto_open": bool(g("globe_auto_open")), "briefing_on_start": bool(g("briefing_on_start")),
        "hud_mode": g("hud_mode"), "hud_style": s.get("hud_style", "neu"), "hud_layout": s.get("hud_layout", "pc"),
        "sphere_color": g("sphere_color") if g("sphere_color") in su.SPHERE_COLORS else "Gold",
        "hud_topmost": bool(g("hud_topmost")), "hud_animation": bool(g("hud_animation")),
        "overlay_style": g("overlay_style"), "orb_size": g("orb_size"), "orb_corner": g("orb_corner"),
        "accent": g("accent") if g("accent") in pc_settings.THEMES else "Cyan",
        "hud_buttons": [list(b) for b in (pc_settings.DEFAULT_BUTTONS if g("hud_buttons") is None else g("hud_buttons"))],
        "show_weather": bool(g("show_weather")), "weather_city": g("weather_city"),
        "calendar_url": s.get("calendar_url", "") or "", "announce_events": bool(g("announce_events")),
        "show_performance": bool(g("show_performance")), "show_pc_temps": bool(g("show_pc_temps")),
        "show_notifications": bool(g("show_notifications")),
        "webcam_fern": bool(s.get("webcam_fern", False)), "ets2_quicksave": s.get("ets2_quicksave", "f5") or "f5",
        "gemini_api_key": s.get("gemini_api_key", "") or "",
        "meine_orte": s.get("meine_orte", "") or "", "meine_wege": s.get("meine_wege", "") or "", "route_an": s.get("route_an", "") or "",
        "wichtige_leute": s.get("wichtige_leute", "") or "", "absage_text": s.get("absage_text", "") or "",
        "discord_server": s.get("discord_server", "") or "", "stil_chats": s.get("stil_chats", "") or "", "test_chat": s.get("test_chat", "") or "",
        "stil_modus": s.get("stil_modus", "aus") or "aus", "wa_name": s.get("wa_name", "") or "",
        "wa_immer": s.get("wa_immer", "") or "", "wa_beim_zocken": s.get("wa_beim_zocken", "ansagen") or "ansagen",
    }
    for k, n in LISTS.items():
        values[k] = ", ".join(s.get(k) or (d.get(k) or []))
    for k, enc in SECRETS.items():
        values[k] = ""
        values["_has_" + k] = bool(s.get(enc))
    for k, _, v in profile:
        values["profil_" + k] = v
    return {"tabs": tabs, "values": values, "new": unseen(s)}


def _csv(v, n):
    return [p.strip() for p in str(v or "").replace(";", ",").split(",") if p.strip()][:n]


def save(s: dict, v: dict) -> dict:
    import pc_secret
    d = pc_settings.DEFAULTS
    new = dict(s)
    text = lambda k, dflt="": str(v.get(k) if v.get(k) is not None else dflt).strip()  # noqa: E731
    num = lambda k: int(float(v.get(k) if v.get(k) not in (None, "") else d.get(k, 0)))  # noqa: E731
    for k in ("autostart", "greet_on_start", "show_hud_on_start", "boot_animation", "msg_ask_first", "kommentare", "discord_hoerbar", "confirm_messages", "speak", "early_chime", "lage_spin",
              "lage_orbits", "map_labels", "lage_sat_tour", "globe_auto_open", "briefing_on_start", "hud_topmost",
              "hud_animation", "show_weather", "announce_events", "show_performance", "show_pc_temps", "show_notifications", "webcam_fern"):
        if k in v:
            new[k] = bool(v[k])
    for k in ("followup_seconds", "pause_lang", "voice_volume", "voice_pitch", "voice_rate", "chime_volume", "orb_size"):
        if k in v:
            new[k] = num(k)
    for k in ("persona", "language", "voice_engine", "piper_voice", "eleven_model", "edge_voice", "windows_voice", "hud_mode", "hud_layout",
              "hud_style", "sphere_color", "overlay_style", "orb_corner", "accent", "home_address", "address_as",
              "calendar_url", "gemini_api_key", "meine_orte", "meine_wege", "route_an", "wichtige_leute", "absage_text", "ets2_quicksave", "lieblingskanaele",
              "discord_server", "stil_chats", "test_chat", "stil_modus", "wa_name", "wa_immer", "wa_beim_zocken"):
        if k in v:
            new[k] = text(k)
    for k in ("input_device", "output_device", "discord_device"):
        if k in v:
            new[k] = v[k] or None
    if "assistant_name" in v:
        new["assistant_name"] = text("assistant_name") or d["assistant_name"]
    if "weather_city" in v:
        new["weather_city"] = text("weather_city") or d["weather_city"]
    if "home_city" in v:
        new["home_city"] = text("home_city") or ""
    if "wake_words" in v:
        new["wake_words"] = [w.lower() for w in _csv(v["wake_words"], 12)] or list(d["wake_words"])
    for k, n in LISTS.items():
        if k in v:
            new[k] = _csv(v[k], n)
    if "eleven_voice" in v:
        import pc_eleven
        new["eleven_voice"] = text("eleven_voice") or d["eleven_voice"]
        names = dict((vid, n) for n, vid in pc_eleven.DEFAULT_VOICES)
        names.update(v.get("_voice_names") or {})
        new["eleven_voice_name"] = names.get(new["eleven_voice"], s.get("eleven_voice_name", ""))
    for k, enc in SECRETS.items():
        val = str(v.get(k) or "").strip()
        if val:
            new[enc] = pc_secret.protect(val)
        elif v.get("_clear_" + k):
            new[enc] = ""
    if isinstance(v.get("hud_buttons"), list):
        rows = []
        for b in v["hud_buttons"][:12]:
            b = (list(b) + ["", "", ""])[:3]
            sym, name, cmd = (str(x or "").strip() for x in b)
            if name and cmd:
                rows.append([sym or name[:1].upper(), name, cmd])
        new["hud_buttons"] = rows
    try:
        import pc_memory
        for k, _ in pc_memory.PROFILE_FIELDS:
            if "profil_" + k in v and str(v["profil_" + k]).strip() != pc_memory.profile(k):
                pc_memory.set_profile(k, str(v["profil_" + k]))
    except Exception:
        pass
    return new


def _key(s, v, name):
    import pc_secret
    return str(v.get(name) or "").strip() or pc_secret.unprotect(s.get(SECRETS[name], ""))


def run(ui, name: str, v: dict) -> dict:
    """Knöpfe der Einstellungsseite. Läuft im Server-Thread (darf ein paar Sekunden dauern)."""
    s = ui.settings
    if name == "test_voice":
        import pc_audio
        import pc_eleven
        eng = v.get("voice_engine") or "auto"
        pc_eleven.LAST_ERROR = ""
        if eng == "auto" and v.get("piper_voice"):   # neue schnelle Stimme: erst laden (einmalig), dann hören
            import pc_piper
            pc_piper.set_voice(v["piper_voice"])
            if not pc_piper.ready():
                pc_piper.install()
                if not pc_piper.ready():
                    return {"ok": False, "text": "Die Stimme ließ sich nicht laden: " + pc_piper.STATE.get("status", "")}
        out = v.get("output_device") or None
        pc_audio.play_chime(device=out)
        time.sleep(0.6)
        pc_audio.speak("Guten Tag. Alle Systeme sind bereit. Was kann ich für Sie tun?", engine=eng,
                       edge_voice=v.get("edge_voice") or "de-DE-KillianNeural", windows_voice=v.get("windows_voice") or "",
                       pitch=int(float(v.get("voice_pitch") or 0)), rate=int(float(v.get("voice_rate") or 0)), output=out,
                       eleven_key=_key(s, v, "eleven_key"), eleven_voice=v.get("eleven_voice"), eleven_model=v.get("eleven_model"))
        if eng == "eleven" and pc_eleven.LAST_ERROR:
            return {"ok": False, "text": pc_eleven.LAST_ERROR + " (Zu hören war die Ersatzstimme.)"}
        return {"ok": True, "text": "Stimme getestet."}
    if name == "selbstzerstoerung":
        import pc_weg

        def _quit():
            try:
                import pc_steuerung
                pc_steuerung.request_quit()
            except Exception:
                pass
        return pc_weg.destroy(_quit)
    if name == "el_load":
        import pc_eleven
        key = _key(s, v, "eleven_key")
        if not key:
            return {"ok": False, "text": "Trag zuerst den ElevenLabs-Schlüssel ein."}
        found = pc_eleven.list_voices(key)
        return {"ok": True, "text": f"{len(found)} Stimmen in deinem Konto.", "options": {"eleven_voice": _opts(
            list(pc_eleven.DEFAULT_VOICES) + [(n, vid) for n, vid in found if vid not in dict((b, a) for a, b in pc_eleven.DEFAULT_VOICES)])}}
    if name == "test_ai":
        import pc_ai
        ok, msg, _ = pc_ai.test(str(v.get("gemini_api_key") or "").strip())
        return {"ok": ok, "text": msg}
    if name == "test_groq":
        import pc_ai
        key = _key(s, v, "groq_key")
        if not key:
            return {"ok": False, "text": "Trag zuerst den Groq-Schlüssel ein."}
        ok, msg = pc_ai.test_groq(key)
        return {"ok": ok, "text": msg}
    if name == "test_cal":
        import pc_calendar
        url = str(v.get("calendar_url") or "").strip()
        if not url:
            return {"ok": False, "text": "Trag zuerst die Kalender-Adresse ein."}
        try:
            msg = pc_calendar.test(url)
            return {"ok": not str(msg).startswith(("Fehler", "Ging", "Kein")), "text": msg}
        except Exception as e:
            return {"ok": False, "text": f"Ging nicht: {e}"}
    if name == "copy_link":
        import pc_link
        ui.q.put(("clipboard", pc_link.code()))
        return {"ok": True, "text": "Kopiert."}
    if name == "new_link":
        import pc_link
        c = pc_link.code(new=True)
        threading.Thread(target=lambda: pc_link.publish(force=True), daemon=True).start()
        return {"ok": True, "text": "Neuer Code. Trag ihn in der App ein.", "code": c}
    if name == "custom":
        import pc_apps
        pc_apps.ensure_custom_file()
        try:
            os.startfile(os.path.join(pc_apps.base_dir(), pc_apps.CUSTOM_FILE))
        except Exception:
            pass
        return {"ok": True, "text": "Datei mit eigenen Befehlen ist offen."}
    if name == "stil_import":
        import pc_stil
        try:
            paths = pc_stil.pick_files()
        except Exception as e:
            return {"ok": False, "text": f"Dateiauswahl ging nicht ({e})."}
        if not paths:
            return {"ok": False, "text": "Keine Datei gewählt."}
        return {"ok": True, "text": pc_stil.import_files(paths)}
    if name == "test_handy":
        import pc_handy
        import pc_link
        if not pc_handy.paired():
            return {"ok": False, "text": "Handy ist nicht gekoppelt (Code fehlt)."}
        direct = time.time() - pc_link.DIRECT["t"] < 90
        r = pc_handy.ask("ctl", wait=15, what="stil_get")
        weg = "direkt (Tailscale, ohne Limit)" if direct else "über den Kopplungsdienst" + (" – Tageslimit heute erreicht!" if pc_handy.limited() else "")
        return {"ok": bool(r), "text": (f"✓ Handy antwortet, Weg: {weg}." if r else "✕ " + pc_handy.not_reached() + f" (Weg: {weg})")}
    if name == "test_ansage":
        import pc_nachrichten
        t = str(s.get("test_chat") or "").strip() or "Test"
        pc_nachrichten.incoming({"kind": "wa_msg", "sender": t, "chat": t, "text": "Das ist eine Test-Nachricht. Sag „antworte du“.", "key": "", "test": True})
        return {"ok": True, "text": f"Ich sag gleich eine Test-Nachricht von {t} an."}
    if name == "test_sprach":
        import pc_wavoice
        return {"ok": True, "text": pc_wavoice.test()}
    if name == "stil_list":
        import pc_stil
        return {"ok": True, "text": pc_stil.history_text()}
    if name == "classic":
        ui.q.put(("classic_settings",))
        return {"ok": True, "text": "Klassisches Fenster ist offen."}
    return {"ok": False, "text": "Unbekannt."}


def _ordnen(tabs, card):
    """Gleiche Ordnung wie am Handy: DEIN ALLTAG · JARVIS · PC & WELT, wichtigstes zuerst, gleiche Symbole."""
    c = {x["l"]: x for t in tabs for x in t["items"]}
    pick = lambda *n: [c[k] for k in n if k in c]  # noqa: E731

    def split(title, keys):   # Felder aus einer Karte herausnehmen
        cd = c.get(title) or {"items": []}
        out = [i for i in cd["items"] if i.get("k") in keys or i.get("a") in keys]
        cd["items"] = [i for i in cd["items"] if i not in out]
        return out
    nachr = split("Start", {"confirm_messages", "msg_ask_first"})
    ort = split("Orte", {"home_city", "home_address"})
    if "Orte" in c:
        c["Orte"]["l"] = "Lieblingsorte & Themen"
    befehle = split("Discord", {"custom"})
    ki = card("KI & Schlüssel", *[i for n in ("Gemini", "Groq (kostenloser Ersatz)", "Hinweis") for i in (c.get(n) or {"items": []})["items"]])
    infos = card("Infos im HUD", *[i for n in ("Wetter", "PC") for i in (c.get(n) or {"items": []})["items"]])
    if befehle and "Schnellstart-Knöpfe" in c:
        c["Schnellstart-Knöpfe"]["items"] += befehle
    if "Kalender" in c:
        c["Kalender"]["l"] = "Kalender"
    T = lambda i, g, n, ic, items: {"id": i, "g": g, "n": n, "i": ic, "items": [x for x in items if x and x.get("items")]}  # noqa: E731
    A, J, W = "DEIN ALLTAG", "JARVIS", "PC & WELT"
    konto = None
    if __import__("pc_variante").KONTO:   # Jarvis von der Website: eigener Bereich fürs Konto
        try:
            import pc_konto
            ki_ = pc_konto.info()
            kst = (f"Angemeldet als {ki_['email']}." if ki_["loggedIn"] else ("Nicht angemeldet." if ki_["configured"] else "Noch nicht eingerichtet."))
        except Exception:
            kst = ""
        konto = {"id": "konto", "g": "KONTO", "n": "Jarvis-Konto", "i": "👤", "items": [card("Dein Konto", {"t": "note", "l": kst},
                 {"t": "btn", "a": "konto_open", "l": "Anmelden / Konto verwalten"},
                 {"t": "note", "l": "Alles wird mit deinem Passwort verschlüsselt, bevor es ins Konto geht – auch der Server kann es nicht lesen."}),
                 card("Selbstzerstörung",
                      {"t": "note", "l": "Löscht Jarvis komplett von diesem PC: Programm, Einstellungen, Gedächtnis, Stimmen und Autostart. "
                                         "Dein Konto bleibt – lädst du Jarvis neu und meldest dich an, ist alles wieder da."},
                      {"t": "btn", "a": "selbstzerstoerung", "l": "Selbstzerstörung"})]}
    return ([konto] if konto else []) + [
        T("schule", A, "Schule", "🏫", pick("Stundenplan", "Arbeiten & Hausaufgaben")),
        T("wege", A, "Zuhause & Orte", "🗺️", [card("Zuhause", *ort)] + pick("Meine Orte", "Meine Wege", "Routen schicken")),
        T("leute", A, "Leute & Anrufe", "👥", pick("Schreibstil & Antworten", "Wichtige Leute") + [card("Nachrichten", *nachr)] + pick("Sticker", "Anruf-Butler")),
        T("allg", J, "Allgemein", "⚙️", pick("Über dich") + [ki] + pick("Kalender", "Meine Ideen", "Start", "Zum Ausfüllen von Formularen")),
        T("hoer", J, "Zuhören & Stimme", "🎙️", pick("Aktivierung", "Sprechen", "ElevenLabs", "Ersatzstimmen", "Wecksound")),
        T("anz", J, "Anzeige", "◐", pick("HUD", "Beim Weckwort") + [infos] + pick("Schnellstart-Knöpfe")),
        T("fern", W, "PC & Fernzugriff", "📡", pick("Handy-App koppeln", "Von unterwegs (Tailscale)")),
        T("gaming", W, "Gaming & Discord", "🎮", pick("Discord", "Discord & Clips", "Gaming-Rückblick", "ETS2-Beifahrer")),
        T("lage", W, "Lage", "🌍", pick("Lieblingsorte & Themen", "Globus", "Briefing")),
    ]
