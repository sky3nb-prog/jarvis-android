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
SECRETS = {"eleven_key": "eleven_key_enc", "groq_key": "groq_key_enc", "telegram_token": "telegram_token_enc"}
LISTS = {"lage_places": 8, "themen_selbst": 12, "flug_places": 6, "discord_channels": 30}


def _opts(pairs):
    return [[n, v] for n, v in pairs]


def _same(names):
    return [[n, n] for n in names]


# Neue Einstellungen (bekommen einen kleinen Punkt, bis du den Bereich einmal angeschaut hast). Bei jedem Update ergänzen.
NEW = ["meine_orte", "meine_wege", "route_an", "hud_layout"]


def unseen(s: dict) -> list:
    seen = set(s.get("seen_new") or [])
    return [k for k in NEW if k not in seen]


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
                 sw("confirm_messages", "Nachrichten vor dem Senden zurückfragen", "WhatsApp, Discord")),
            card("Discord",
                 tx("discord_channels", "Sprachkanäle", "Genaue Namen mit Komma, auch mit Emoji, z. B. 🥒|Gurken, 🥑|Avocado."),
                 btn("custom", "Eigene Befehle bearbeiten (Programme, Ordner, Webseiten)")),
        ]},
        {"id": "hoer", "n": "Zuhören", "i": "◉", "items": [
            card("Aktivierung",
                 tx("wake_words", "Aktivierungswort", "Mehrere Schreibweisen mit Komma, z. B. jarvis, dscharvis"),
                 sel("language", "Sprache", _opts(su.LANGUAGES)),
                 sel("input_device", "Mikrofon", mics, "Wirkt sofort nach dem Speichern."),
                 rng("followup_seconds", "Weiterhören nach einem Befehl", 0, 15, " s", "0 = aus")),
        ]},
        {"id": "stim", "n": "Stimme", "i": "♪", "items": [
            card("Sprechen",
                 sw("speak", "Antworten laut sprechen"),
                 sel("voice_engine", "Stimmenart", _opts(su.ENGINES), "Klappt ElevenLabs nicht, nimmt er die Online-Stimme."),
                 sel("output_device", "Ausgabe", outs, "Z. B. ein Kanal von Elgato Wave Link."),
                 rng("voice_volume", "Lautstärke der Stimme", 10, 100, " %"),
                 rng("voice_pitch", "Tonhöhe", -10, 10),
                 rng("voice_rate", "Sprechtempo", -10, 10),
                 btn("test_voice", "▶ Stimme testen")),
            card("ElevenLabs",
                 sec("eleven_key", "Schlüssel", "elevenlabs.io → Entwickler → API-Schlüssel. Wird verschlüsselt gespeichert."),
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
                 sw("briefing_on_start", "Beim Start ein kurzes Briefing sprechen"),
                 tx("flug_places", "Flugverkehr: eigene Orte", "Mit Komma, z. B. Stuttgart, London.")),
        ]},
        {"id": "wege", "n": "Wege", "i": "➜", "items": [
            card("Meine Orte",
                 note("Eine Zeile pro Ort: Name, Doppelpunkt, Adresse. Dann reicht „Ich will zu Opa“. Gilt auch am Handy."),
                 {"k": "meine_orte", "t": "area", "l": "Orte", "ph": "Opa: Musterstraße 5, 71277 Rutesheim\nArbeit: …"}),
            card("Meine Wege",
                 note("Ein Punkt, über den der Weg führen soll: Name, Doppelpunkt, Ort oder Koordinaten (in Google Maps rechts klicken, Zahlen kopieren). "
                      "Dann geht „über den oberen Feldweg zu Opa“."),
                 {"k": "meine_wege", "t": "area", "l": "Wege", "ph": "oberer Feldweg: 48.8030, 8.9620"}),
            card("Routen schicken",
                 tx("route_an", "Google-Maps-Link per WhatsApp an", "Name aus deinen Kontakten, leer = an niemanden. Gilt auch am Handy."),
                 note("Fragst du am PC, öffnet sich die Route am PC und auf dem Handy, und der PC schickt den Link per WhatsApp.")),
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
                 sw("hud_animation", "Animationen", "Aus = ruhiger und sparsamer")),
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
                 {"k": "gemini_api_key", "t": "text", "l": "Schlüssel", "pw": True, "h": "Nie in Chats oder Mails weitergeben."},
                 btn("test_ai", "Verbindung testen")),
            card("Groq (kostenloser Ersatz)",
                 sec("groq_key", "Schlüssel", "console.groq.com → API Keys. Springt ein, wenn Gemini nicht geht."),
                 btn("test_groq", "Groq testen")),
            card("Hinweis", note("Was du frei sagst, geht zur Beantwortung an Google bzw. Groq. Sag keine Passwörter oder Privates.")),
        ]},
        {"id": "dat", "n": "Meine Daten", "i": "✎", "items": [
            card("Zum Ausfüllen von Formularen",
                 note("„Trag bitte meine E-Mail ein.“ Bleibt nur auf diesem PC. Passwörter gehören nicht hierher."),
                 *[tx("profil_" + k, n) for k, n, _ in profile]),
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

    values = {
        "assistant_name": g("assistant_name"), "address_as": g("address_as"), "persona": g("persona"),
        "autostart": bool(g("autostart")), "greet_on_start": bool(g("greet_on_start")),
        "show_hud_on_start": bool(g("show_hud_on_start")), "confirm_messages": bool(g("confirm_messages")),
        "wake_words": ", ".join(g("wake_words") or []), "language": g("language"),
        "input_device": g("input_device") if not isinstance(g("input_device"), int) else pc_audio.device_name(g("input_device")),
        "output_device": g("output_device") if not isinstance(g("output_device"), int) else pc_audio.device_name(g("output_device")),
        "followup_seconds": g("followup_seconds"), "speak": bool(g("speak")), "voice_engine": g("voice_engine"),
        "voice_volume": s.get("voice_volume", 100), "voice_pitch": g("voice_pitch"), "voice_rate": g("voice_rate"),
        "eleven_voice": g("eleven_voice"), "eleven_model": g("eleven_model"), "edge_voice": g("edge_voice"),
        "windows_voice": g("windows_voice") or "", "chime_volume": g("chime_volume"), "early_chime": bool(g("early_chime")),
        "home_city": g("home_city") or "Leonberg", "home_address": g("home_address") or "",
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
        "gemini_api_key": s.get("gemini_api_key", "") or "",
        "meine_orte": s.get("meine_orte", "") or "", "meine_wege": s.get("meine_wege", "") or "", "route_an": s.get("route_an", "") or "",
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
    for k in ("autostart", "greet_on_start", "show_hud_on_start", "confirm_messages", "speak", "early_chime", "lage_spin",
              "lage_orbits", "map_labels", "lage_sat_tour", "globe_auto_open", "briefing_on_start", "hud_topmost",
              "hud_animation", "show_weather", "announce_events", "show_performance", "show_pc_temps", "show_notifications"):
        if k in v:
            new[k] = bool(v[k])
    for k in ("followup_seconds", "voice_volume", "voice_pitch", "voice_rate", "chime_volume", "orb_size"):
        if k in v:
            new[k] = num(k)
    for k in ("persona", "language", "voice_engine", "eleven_model", "edge_voice", "windows_voice", "hud_mode", "hud_layout",
              "hud_style", "sphere_color", "overlay_style", "orb_corner", "accent", "home_address", "address_as",
              "calendar_url", "gemini_api_key", "meine_orte", "meine_wege", "route_an"):
        if k in v:
            new[k] = text(k)
    for k in ("input_device", "output_device"):
        if k in v:
            new[k] = v[k] or None
    if "assistant_name" in v:
        new["assistant_name"] = text("assistant_name") or d["assistant_name"]
    if "weather_city" in v:
        new["weather_city"] = text("weather_city") or d["weather_city"]
    if "home_city" in v:
        new["home_city"] = text("home_city") or "Leonberg"
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
    if name == "classic":
        ui.q.put(("classic_settings",))
        return {"ok": True, "text": "Klassisches Fenster ist offen."}
    return {"ok": False, "text": "Unbekannt."}
