"""
Einstellungen des Assistenten (Datei einstellungen.json neben dem Programm).

Man ändert sie bequem im HUD über das Zahnrad oben links, oder per Sprache:
"Jarvis, öffne deine Einstellungen". Die Datei kann man auch von Hand bearbeiten.
"""

import json
import os

from pc_apps import base_dir

FILE = "einstellungen.json"

# Farbthemen für HUD und Overlay: Name -> Farbton-Verschiebung in Grad (Cyan ist die Grundfarbe)
THEMES = {"Cyan": 0, "Blau": 25, "Violett": 70, "Rosa": 125, "Rot": 160, "Orange": -165, "Gold": -147, "Grün": -60}
CORNERS = ["oben links", "oben rechts", "unten links", "unten rechts"]

# Schnellstart-Knöpfe im HUD: (Symbol, Beschriftung, Befehl, der beim Klick ausgeführt wird)
DEFAULT_BUTTONS = [
    ("D", "Discord", "öffne discord"),
    ("♪", "Musik", "musik"),
    ("S", "Steam", "öffne steam"),
    ("C", "Chrome", "öffne chrome"),
    ("W", "Windows", "öffne einstellungen"),
    ("«", "Zurück", "eins zurück"),
    ("▶", "Play/Pause", "pause"),
    ("»", "Weiter", "eins weiter"),
    ("⏻", "Beenden", "beende dich"),
]

DEFAULTS = {
    "wake_words": ["jarvis"],  # mehrere Schreibweisen möglich, falls er dich oft anders versteht
    "language": "de-DE",
    "input_device": None,  # None = Standard-Mikrofon, sonst Name des Mikrofons
    "output_device": None,  # None = Windows-Standard, sonst Name des Ausgabegeräts (z. B. Elgato Wave Link)
    "followup_seconds": 5,  # so lange hört er nach einem Befehl weiter zu, ohne Aktivierungswort (0 = aus)
    "speak": True,  # Antworten laut sprechen
    "voice_engine": "auto",  # "auto" = Online-Stimme, sonst Windows; "edge" nur online; "windows" nur offline
    "edge_voice": "de-DE-KillianNeural",  # Online-Stimme (siehe Einstellungen)
    "windows_voice": "",  # leer = automatisch eine deutsche Männerstimme
    "voice_pitch": -3,  # Tonhöhe -10 (tiefer) bis 10 (höher)
    "voice_rate": 0,  # Sprechtempo -10 bis 10
    "chime_volume": 45,  # Lautstärke des Wecksounds 0 bis 100
    "voice_volume": 100,
    "discord_channels": ["🥒|Gurken", "🥑|Avocado", "🥔|Kartoffeln", "🥕|Möhren"],  # Sprachkanäle, genauer Name  # eigene Lautstärke von Jarvis' Stimme 10 bis 100
    "early_chime": True,  # Wecksound schon beim Weckwort mitten im Satz
    "overlay_style": "neu",  # "neu" = 3D-Kugel mit Nervenstrang, "klein" = alter Kreis, "gross" = Leuchtrahmen + Textfeld
    "overlay_v2": False,
    "boot_animation": True,  # Iron-Man-Start nach dem Anmelden (Vollbild-Hologramm, Klick/Esc überspringt)     # einmalig auf das neue Overlay umgestellt
    "orb_size": 68,  # Größe des kleinen Kreises in Pixeln
    "orb_corner": "oben links",  # Ecke des kleinen Kreises
    "accent": "Cyan",  # Farbthema (siehe THEMES)
    "hud_alpha": 100,  # Durchsichtigkeit des HUD-Fensters in Prozent (40 bis 100)
    "hud_animation": True,  # Animationen im HUD (aus = ruhiger und sparsamer)
    "hud_buttons": None,  # eigene Schnellstart-Knöpfe: Liste aus [Symbol, Beschriftung, Befehl]
    "assistant_name": "J.A.R.V.I.S.",  # Name, der im HUD steht und mit dem er sich vorstellt
    "address_as": "",  # wie er dich anspricht, z. B. "Sir" oder dein Name
    "greet_on_start": False,  # beim Start kurz begrüßen
    "show_hud_on_start": True,
    "hud_topmost": False,  # HUD immer im Vordergrund
    "hud_width": 1180,  # Fensterbreite des HUD (ändert sich beim Größe-Ziehen von selbst)
    "show_weather": True,
    "weather_city": "Karlsruhe",
    "show_notifications": True,
    "show_pc_temps": True,
    "timetree_enabled": False,  # TimeTree-Termine über das Tool timetree-exporter holen (inoffiziell)
    "timetree_email": "",
    "timetree_password_enc": "",  # mit Windows verschlüsselt (pc_secret)
    "timetree_code": "",
    "announce_events": True,  # beim Start die Termine von heute ansagen
    "gcal_enabled": False,  # TimeTree-Termine in einen Google-Kalender eintragen
    "gcal_client_id": "",
    "gcal_client_secret_enc": "",
    "gcal_refresh_enc": "",
    "gcal_calendar_id": "",
    "gcal_calendar_name": "",
    "calendar_url": "",  # geheime iCal-Adresse des Google-Kalenders (nur lesen)
    "autostart": False,  # mit Windows starten
    "confirm_messages": False,  # Nachrichten (WhatsApp, Discord) vor dem Senden zurückfragen
    "show_performance": True,  # Karte "Leistung" (CPU, RAM, GPU, Datenträger, Netzwerk) im HUD
    "gemini_api_key": "",  # Schlüssel von aistudio.google.com/apikey (liegt nur hier auf deinem PC)
    "gemini_model": "auto",  # "auto" = Jarvis sucht selbst ein passendes Modell
    "groq_key_enc": "",  # kostenloser Ersatz (console.groq.com), mit Windows verschlüsselt
    "eleven_key_enc": "",  # ElevenLabs-Schlüssel, mit Windows verschlüsselt (pc_secret)
    "eleven_voice": "onwK4e9ZLuTAKqWW03F9",  # Stimmen-ID (Standard: Daniel)
    "eleven_voice_name": "Daniel – britisch, ruhig, souverän (Jarvis-Stil)",
    "eleven_model": "eleven_flash_v2_5",
    "briefing_on_start": True,  # beim Start ein kurzes Lage-Briefing (Weltlage) sprechen
    "globe_auto_open": True,  # bei "wie ist die Lage" den Globus öffnen
    "globe_fullscreen": False,  # Globus gleich im Vollbild öffnen
    "globe_theme": "Glut",  # Farben des Globus: Glut, Jarvis, Radar, Violett
    "globe_style": "Hologramm",  # (alt) Stil des früheren Globus
    "map_style": "Satellit",  # Weltlage-Karte: Satellit (echte Bilder) oder Dunkel (in deiner Farbe)
    "map_labels": True,  # Ortsnamen auf der Karte
    "home_city": "Leonberg",  # dein Standort: Mitte der Karte und lokale Nachrichten
    "hud_mode": "info",  # HUD: "info" (Kugel mit allen Infos) oder "fokus" (nur die Kugel)
    "hud_style": "neu",  # "neu" = wie am Handy (eigenes Fenster, 3D, Satelliten-Globus), "klassisch" = bisheriges HUD
    "meine_orte": "",   # "Opa: Musterstraße 5, Rutesheim" je Zeile (gleich wie am Handy)
    "meine_wege": "",   # "oberer Feldweg: 48.80, 8.96" je Zeile
    "route_an": "",     # Google-Maps-Link per WhatsApp an diesen Kontakt
    "wichtige_leute": "Mama, Saya, Opa, Elijah, Tobi, Marius, Jannis",   # Namen wie in WhatsApp, mit Komma: deren Nachrichten sagt Jarvis an
    "ets2_quicksave": "f5",
    "webcam_fern": False,    # Webcam von unterwegs (Tailscale) ansehen erlauben  # Taste fürs Schnellspeichern in ETS2 (wenn du weggehst)
    "absage_text": "",      # Anruf-Butler: leer = "Kann gerade nicht, rufe später zurück."
    "hud_layout": "pc",  # "pc" = Leiste oben, "handy" = wie die App (Fokus, Info, Lage, Steuern unten)
    "sphere_color": "Gold",  # Farbe der Kugel: Gold, Cyan, Rot, Grün, Violett, Weiß
    "hud_borderless": False,  # (nicht mehr benutzt) HUD hat wieder die normale, eingefärbte Titelleiste
    "lage_places": ["Seoul", "New York"],  # Lieblingsorte für die Lage (Verwandtschaft, Urlaub ...), oben im Lage-Screen
    "lage_spin": True,  # Erde im Lage-Screen langsam drehen (mit echtem Tag und Nacht)
    "lage_orbits": True,  # echte Satelliten (ISS, Hubble ...) um die Erde, wenn man sie ganz sieht
    "themen_selbst": [],  # eigene Interessen für "Für dich" (gelernte kommen von selbst dazu)
    "flug_region": "home",  # Flug-Modus: home, de, eu, us, welt oder ort:<Name>
    "flug_places": [],  # eigene Orte für den Flug-Modus
    "lage_sat_tour": True,  # beim Briefing im Lage-Screen ins Satellitenbild umschalten und nah an die Orte zoomen
    "persona": "sarkastisch",  # Persönlichkeit: sarkastisch, butler, locker
    "home_address": "",  # deine Adresse (Start für Routen, wenn das Handy keinen Standort schickt)
    "phone_channel": "telegram",  # Routen usw. aufs Handy: "telegram" (Bot), "whatsapp" (an dich selbst) oder "ntfy"
    "my_number": "",  # deine WhatsApp-Nummer
    "telegram_token_enc": "",  # Schlüssel von Jarvis' Telegram-Bot (@BotFather), mit Windows verschlüsselt
    "telegram_chat": "",  # dein Chat mit dem Bot (wird beim ersten "Start" gemerkt)
    "ntfy_topic": "",  # geheimer Kanal für Nachrichten aufs Handy (wird beim ersten Start erzeugt)
    "loc_topic": "",  # geheimer Kanal, über den das Handy (OwnTracks) seinen Standort schickt
    "seen_new": [],  # neue Einstellungen, die schon angeschaut wurden (für den "Neu"-Punkt)
}


def path() -> str:
    return os.path.join(base_dir(), FILE)


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(path(), encoding="utf-8") as f:
            stored = json.load(f)
        for key, value in stored.items():
            if key in DEFAULTS:
                data[key] = value
    except Exception:
        pass
    if not data.get("overlay_v2"):   # Update: einmal auf das neue Overlay umstellen (zurück geht in den Einstellungen)
        data["overlay_style"], data["overlay_v2"] = "neu", True
    if not isinstance(data["wake_words"], list) or not data["wake_words"]:
        data["wake_words"] = list(DEFAULTS["wake_words"])
    return data


def save(data: dict) -> bool:
    try:
        with open(path(), "w", encoding="utf-8") as f:
            json.dump({k: data[k] for k in DEFAULTS if k in data}, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Einstellungen konnten nicht gespeichert werden: {e}")
        return False
