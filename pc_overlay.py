"""
PC-Assistent mit HUD und Overlay (Windows). Das ist die Hauptdatei zum Starten.

- Beim Start öffnet sich das große HUD-Fenster (SHOW_HUD_ON_START).
- Läuft das HUD nicht im Vordergrund, erscheint beim Weckwort nur ein kleiner Kreis oben
  links (OVERLAY_STYLE = "klein"). Er zeigt, ob der Assistent zuhört, nachdenkt oder
  spricht, und daneben ein kleines Textfeld mit dem, was du sagst und was er antwortet.
- Wer das frühere Overlay möchte (Leuchtrahmen um den Bildschirm + Textfeld oben in der
  Mitte), stellt OVERLAY_STYLE = "gross" ein.
- Einstellungen (Aktivierungswort, Stimme, Anzeige, Wetter ...): Zahnrad oben links im HUD,
  Tray-Menü oder per Sprache "Jarvis, öffne deine Einstellungen". Sie werden in
  einstellungen.json neben dem Programm gespeichert.
- Nach einem Befehl hört er noch einige Sekunden weiter zu (FOLLOWUP_SECONDS, in den
  Einstellungen änderbar), du kannst also ohne erneutes Aktivierungswort weitersprechen.
  "Danke" oder "das war's" beendet das Weiterhören sofort.
- Sprachbefehle: "Jarvis, zeig die Oberfläche" / "Jarvis, schließ das HUD" / "Jarvis, beende dich".
- Beenden: Rechtsklick auf das Tray-Symbol (neben der Uhr) -> Beenden.

Alle Dateien müssen im selben Ordner liegen:
    pc_overlay.py (diese), pc_steuerung.py, pc_assistent.py, pc_audio.py, pc_windows.py,
    pc_pill.py, pc_apps.py, pc_hud.py, pc_info.py, pc_settings.py, pc_settingsui.py,
    pc_talk.py (Wetterfragen, Plauderei), pc_remind.py (Timer, Wecker, Erinnerungen)

Setup:  pip install pyautogui sounddevice numpy SpeechRecognition pystray pillow
        (optional für die Netz-Anzeige im HUD: pip install psutil)
Start:  py pc_overlay.py

Als Programm ohne schwarzes Fenster: build.bat ausführen (erzeugt dist\\PC-Assistent.exe).
"""

import ctypes
import math
import os
import queue
import re
import sys

if "--hud" in sys.argv:   # zweiter Prozess: nur das HUD-Fenster (pc_hudwin), ohne Mikrofon usw.
    import pc_hudwin
    pc_hudwin.main()
    sys.exit(0)
if "--orb" in sys.argv:   # dritter Prozess: nur das kleine Overlay (Kugel mit Nervenstrang)
    import pc_orbwin
    pc_orbwin.main()
    sys.exit(0)
import threading
import time
import tkinter as tk
import tkinter.font as tkfont

import sounddevice as sd
import speech_recognition as sr
from PIL import Image, ImageChops, ImageDraw, ImageTk

import pc_apps
import pc_assistent
import pc_audio
import pc_pill as P
import pc_remind
import pc_settings
import pc_steuerung
import pc_talk
from pc_assistent import (
    BLOCK,
    RATE,
    WAKE_WORDS,
    calibrate,
    drain,
    listen_utterance,
    transcribe,
)
from pc_audio import play_chime, speak
from pc_hud import HudWindow
from pc_pill import KEY_RGB, make_orb, make_pill
from pc_steuerung import ask_ai, handle_fixed
import pc_ai
import pc_cancel
import pc_memory
import pc_autostart
import pc_calendar
import pc_gcal
import pc_secret
import pc_timetree
import pc_input
import pc_messages
import pc_eleven
import pc_flights
import pc_map as pc_globe  # die Weltlage ist jetzt eine Satellitenkarte
import pc_news
import pc_handy
import pc_nachrichten
import pc_ets2
import pc_fern
import pc_sehen
import pc_media
import pc_remote
import pc_themen
import pc_webhud
import pc_settingsui
import pc_voiceset
import pc_sphere
import pc_download
import pc_live
import pc_phone
import pc_telegram
import pc_route
import pc_link

# --- Einstellungen ----------------------------------------------------------
# Diese Werte sind nur Vorgaben. Maßgeblich ist einstellungen.json (im HUD änderbar).
OVERLAY_STYLE = "klein"  # "klein" = kleiner Kreis oben links, "gross" = Leuchtrahmen + Textfeld oben
SPEAK = True  # False = Assistent antwortet nur als Text
EARLY_CHIME = True  # Wecksound schon beim Weckwort mitten im Satz (False = erst am Satzende)
RESTART_AUDIO = threading.Event()  # gesetzt, wenn das Mikrofon gewechselt wurde
SLEEPING = threading.Event()  # Schalter im HUD aus: Jarvis hört nicht auf sein Aktivierungswort (Mikro bleibt ungenutzt)
GREET_ON_START = False
FOLLOWUP_SECONDS = 5  # so lange hört er nach einem Befehl ohne Aktivierungswort weiter zu (0 = aus)
END_PHRASES = {"danke", "danke dir", "danke schön", "vielen dank", "das war's", "das wars", "nichts",
               "nein", "nein danke", "abbrechen", "stopp", "stop", "ende", "genug", "schon gut", "vergiss es"}

KEY = "#010101"  # diese Farbe ist durchsichtig (muss zu pc_pill.KEY_RGB passen)
ACCENT = "#7fdcff"
FG = "#f2f2f5"
FG_DIM = "#a8a8b3"
ROLE_COLORS = {"Du": "#7fdcff", "Assistent": "#b6a4ff", "Fehler": "#ff7b7b"}

# Nur für OVERLAY_STYLE = "gross"
GLOW_OUTER = (150, 235, 255)
GLOW_INNER = (30, 110, 210)
GLOW_WIDTH = 22
TEXT_TOP = 40
MAX_LINES = 3


def role_color(role: str) -> str:
    """Farbe der Rollenbeschriftung: "Du" folgt dem Farbthema, die anderen bleiben gleich."""
    return P.shift_hex("#7fdcff") if role == "Du" else ROLE_COLORS.get(role, FG_DIM)


_GREETED = False


pc_assistent_announce = [True]  # Termine beim Start ansagen


def apply_settings(s: dict):
    """Überträgt die Einstellungen auf alle laufenden Teile des Assistenten."""
    global SPEAK, EARLY_CHIME, OVERLAY_STYLE, FOLLOWUP_SECONDS, GREET_ON_START
    words = [w.strip().lower() for w in s.get("wake_words", []) if str(w).strip()]
    WAKE_WORDS[:] = words or ["jarvis"]  # dieselbe Liste, die auch die Erkennung benutzt
    pc_assistent.LANGUAGE = s.get("language", "de-DE")
    new_in = pc_audio.resolve_device(s.get("input_device"), "input")
    if new_in != pc_assistent.INPUT_DEVICE:  # anderes Mikrofon: Hör-Schleife startet sofort neu
        pc_assistent.INPUT_DEVICE = new_in
        RESTART_AUDIO.set()
    pc_audio.OUTPUT_DEVICE = s.get("output_device") or None
    pc_audio.VOICE_RATE = int(s.get("voice_rate", 0))
    pc_audio.VOICE_ENGINE = s.get("voice_engine", "auto")
    pc_audio.EDGE_VOICE = s.get("edge_voice") or "de-DE-KillianNeural"
    pc_audio.WINDOWS_VOICE = s.get("windows_voice", "") or ""
    pc_audio.VOICE_PITCH = int(s.get("voice_pitch", -3))
    pc_eleven.KEY = pc_secret.unprotect(s.get("eleven_key_enc", ""))
    pc_eleven.VOICE_ID = s.get("eleven_voice") or pc_settings.DEFAULTS["eleven_voice"]
    pc_eleven.MODEL = s.get("eleven_model") or pc_settings.DEFAULTS["eleven_model"]
    FOLLOWUP_SECONDS = max(0, int(s.get("followup_seconds", 5)))
    pc_audio.CHIME_VOLUME = max(0.0, min(1.0, float(s.get("chime_volume", 45)) / 100.0))
    pc_audio.VOICE_VOLUME = max(10, min(100, int(s.get("voice_volume", 100))))
    pc_audio.reset_chime()  # Wecksound mit neuer Lautstärke neu erzeugen
    SPEAK = bool(s.get("speak", True))
    EARLY_CHIME = bool(s.get("early_chime", True))
    OVERLAY_STYLE = s.get("overlay_style", "klein")
    GREET_ON_START = bool(s.get("greet_on_start", False))
    P.set_hue_shift(pc_settings.THEMES.get(s.get("accent", "Cyan"), 0))  # Farbthema
    if (s.get("calendar_url") or "").strip() != pc_calendar.URL:
        pc_calendar.URL = (s.get("calendar_url") or "").strip()
        pc_calendar.reset_cache()
    pc_timetree.configure(bool(s.get("timetree_enabled")), s.get("timetree_email", ""),
                          pc_secret.unprotect(s.get("timetree_password_enc", "")), s.get("timetree_code", ""))
    pc_gcal.configure(bool(s.get("gcal_enabled")), s.get("gcal_client_id", ""),
                      pc_secret.unprotect(s.get("gcal_client_secret_enc", "")),
                      pc_secret.unprotect(s.get("gcal_refresh_enc", "")), s.get("gcal_calendar_id", ""))
    pc_assistent_announce[0] = bool(s.get("announce_events", True))
    pc_messages.CONFIRM = bool(s.get("confirm_messages", False))
    want_auto = bool(s.get("autostart", False))
    if want_auto != pc_autostart.is_enabled():
        pc_autostart.set_enabled(want_auto)
    pc_ai.KEY = (s.get("gemini_api_key") or "").strip()
    pc_ai.GROQ_KEY = pc_secret.unprotect(s.get("groq_key_enc", ""))
    pc_ai.MODEL = s.get("gemini_model") or "auto"
    pc_ai.reset_cache()
    pc_talk.NAME = s.get("assistant_name") or "J.A.R.V.I.S."
    pc_talk.ADDRESS = (s.get("address_as") or "").strip()
    pc_talk.CITY = s.get("weather_city") or "Karlsruhe"
    pc_news.CITY = (s.get("home_city") or "Leonberg").strip().title()
    pc_steuerung.PERSONA = s.get("persona") or "sarkastisch"
    pc_steuerung.set_voice_channels(s.get("discord_channels") or [])
    pc_phone.PUSH_TOPIC = (s.get("ntfy_topic") or "").strip()
    pc_phone.CHANNEL = s.get("phone_channel") or "telegram"
    pc_phone.MY_NUMBER = (s.get("my_number") or "").strip()
    token = pc_secret.unprotect(s.get("telegram_token_enc", "")).strip()
    if token != pc_telegram.TOKEN:  # neuer Bot: Chat neu verbinden
        pc_telegram.CHAT_ID = ""
    pc_telegram.TOKEN = token
    pc_telegram.CHAT_ID = str(s.get("telegram_chat") or "") or pc_telegram.CHAT_ID
    if pc_telegram.TOKEN:
        pc_telegram.start()
    else:
        pc_telegram.stop()
    pc_phone.LOC_TOPIC = (s.get("loc_topic") or "").strip()
    pc_route.HOME_ADDRESS = (s.get("home_address") or "").strip()
    pc_route.HOME_CITY = (s.get("home_city") or "Leonberg").strip()


def state_for(role: str, text: str) -> str:
    """Welcher Zustand (für Kreis und HUD) passt zu dieser Meldung?"""
    if role in ("Du", "Ich höre …"):
        return "listening"
    if role == "Assistent":
        return "thinking" if text.startswith("Denke nach") else "speaking"
    if role == "Starte …":
        return "thinking"
    if role == "Fehler":
        return "error"
    return "idle"


def make_style(win: tk.Toplevel, click_through: bool):
    """Fenster klaut keinen Fokus; optional gehen Mausklicks hindurch."""
    try:
        win.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        style = user32.GetWindowLongW(hwnd, -20)
        style |= 0x80000 | 0x80 | 0x08000000  # LAYERED | TOOLWINDOW | NOACTIVATE
        if click_through:
            style |= 0x20  # TRANSPARENT
        user32.SetWindowLongW(hwnd, -20, style)
    except Exception:
        pass


def wrap_text(font: tkfont.Font, text: str, maxw: int, max_lines: int):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if not line or font.measure(trial) <= maxw:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:  # bei langen Sätzen das Ende zeigen
        lines = lines[-max_lines:]
        lines[0] = "… " + lines[0]
    return lines


def gold_pill(w: int, h: int, radius: int, border: int) -> Image.Image:
    """Dunkles Textfeld mit goldenem Rand (wie am Handy)."""
    ss = 3
    W, H, r, b = w * ss, h * ss, radius * ss, border * ss
    outer = Image.new("L", (W, H), 0)
    ImageDraw.Draw(outer).rounded_rectangle((0, 0, W - 1, H - 1), radius=r, fill=255)
    inner = Image.new("L", (W, H), 0)
    ImageDraw.Draw(inner).rounded_rectangle((b, b, W - 1 - b, H - 1 - b), radius=max(0, r - b), fill=255)
    img = Image.new("RGB", (W, H), KEY_RGB)
    img.paste(Image.new("RGB", (W, H), (16, 11, 4)), (0, 0), outer)
    img.paste(Image.new("RGB", (W, H), (190, 128, 40)), (0, 0), ImageChops.subtract(outer, inner))
    return img.resize((w, h), Image.LANCZOS)


class EdgeGlow:
    """Goldener Schein am Bildschirmrand (Klicks gehen durch)."""

    def __init__(self, root: tk.Tk, k: float):
        self.root, self.k = root, k
        self.win = None
        self._job = None
        self._t0 = 0.0

    def _build(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.win = tk.Toplevel(self.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY)
        self.win.attributes("-transparentcolor", KEY)
        self.win.geometry(f"{sw}x{sh}+0+0")
        c = tk.Canvas(self.win, width=sw, height=sh, bg=KEY, highlightthickness=0, bd=0)
        c.pack()
        n = max(10, int(14 * self.k))
        for i in range(n):
            t = i / (n - 1)
            r, g, b = int(255 - 150 * t), int(196 - 130 * t), int(96 - 80 * t)
            c.create_rectangle(i, i, sw - 1 - i, sh - 1 - i, outline=f"#{r:02x}{g:02x}{b:02x}", width=1)
        self.win.update_idletasks()
        make_style(self.win, True)

    def show(self):
        try:
            if self.win is None:
                self._build()
            self.win.deiconify()
            self.win.lift()
            self._t0 = time.time()
            if self._job is None:
                self._pulse()
        except Exception:
            pass

    def _pulse(self):
        if self.win is None or not self.win.winfo_viewable():
            self._job = None
            return
        t = time.time() - self._t0
        self.win.attributes("-alpha", 0.35 + 0.12 * math.sin(t * 2.6) + 0.3 * max(0.0, 1 - t / 0.6))
        self._job = self.root.after(40, self._pulse)

    def hide(self):
        try:
            if self.win is not None:
                self.win.withdraw()
        except Exception:
            pass


# --- Kleiner Kreis oben links ------------------------------------------------------
class CompactOverlay:
    """Winziger animierter Kreis oben links, daneben bei Bedarf ein kleines Textfeld."""

    def __init__(self, root: tk.Tk, k: float, size: int = 68, corner: str = "oben links", on_close=None):
        self.root, self.k = root, k
        self.on_close = on_close
        self.d = int(size * k)
        self.corner = corner
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY)
        self.win.attributes("-transparentcolor", KEY)
        self.canvas = tk.Canvas(self.win, width=self.d, height=self.d, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.orb_item = self.canvas.create_image(0, 0, anchor="nw")
        self.pill_item = self.canvas.create_image(0, 0, anchor="nw")
        self.f_role = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.f_msg = tkfont.Font(family="Segoe UI", size=13)
        self._photo_orb = None
        self._photo_pill = None
        self.state = "idle"
        self._last = None
        self._visible = False
        self._styled = False
        self._anim_job = None
        self._hide_job = None
        self._t0 = time.time()
        self.sphere = None  # pc_sphere.SphereFrames vom HUD
        self._small: dict = {}  # (Größe, Farbe, Bild-Nr.) -> fertiges kleines Bild

    def set_size(self, size: int):
        self.d = int(size * self.k)
        self._last = None  # beim nächsten Anzeigen neu zeichnen

    def set_corner(self, corner: str):
        self.corner = corner
        self._last = None

    def show(self, role: str, text: str, hide_ms: int, state: str):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        self.state = state
        if not text.strip(" …") and state == "listening":
            role, text = "JARVIS HÖRT ZU", "…"
        if (role, text) != self._last:
            self._render(role, text)
            self._last = (role, text)
        self.win.deiconify()
        self.win.lift()
        self._visible = True
        if not self._styled:
            make_style(self.win, False)  # Klicks nur auf sichtbare Teile (für das X), Fokus bleibt unberührt
            self._styled = True
        if self._anim_job is None:
            self._animate()
        if hide_ms:
            self._hide_job = self.root.after(hide_ms, self.hide)

    def _render(self, role: str, text: str):
        k, d = self.k, self.d
        if not text:
            self.canvas.itemconfigure(self.pill_item, state="hidden")
            w = h = d
        else:
            self.canvas.itemconfigure(self.pill_item, state="normal")
            lines = wrap_text(self.f_msg, text, int(380 * k), 2)
            role_h = self.f_role.metrics("linespace")
            line_h = self.f_msg.metrics("linespace")
            content_w = max([self.f_role.measure(role)] + [self.f_msg.measure(l) for l in lines])
            padx, padt, padb = int(20 * k), int(10 * k), int(12 * k)
            xr = int(11 * k)  # Radius des runden X
            pw = content_w + 2 * padx + 2 * xr + int(6 * k)
            ph = max(int(48 * k), padt + role_h + len(lines) * line_h + padb)
            img = gold_pill(pw, ph, int(20 * k), max(1, int(1.5 * k)))
            self._photo_pill = ImageTk.PhotoImage(img)
            gap = int(10 * k)
            h = max(d, ph)
            w = d + gap + pw
            px, py = d + gap, (h - ph) // 2
            self.canvas.delete("txt")
            self.canvas.itemconfigure(self.pill_item, image=self._photo_pill)
            self.canvas.coords(self.pill_item, px, py)
            label = {"Du": "DU", "Assistent": "JARVIS"}.get(role, role.upper())
            self.canvas.create_text(
                px + padx, py + padt, text=label, font=self.f_role,
                fill="#6ec8ff" if role == "Du" else "#ffd678", anchor="nw", tags="txt",
            )
            y = py + padt + role_h
            for line in lines:
                self.canvas.create_text(px + padx, y, text=line, font=self.f_msg, fill="#ffe9c8", anchor="nw", tags="txt")
                y += line_h
        self.canvas.coords(self.orb_item, 0, (h - d) // 2)
        self.canvas.config(width=w, height=h)
        self._draw_close(w, h, bool(text))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        margin = int(22 * k)
        x = margin if "links" in self.corner else sw - w - margin
        # oben: ein Stück tiefer, damit die Kugel und ihr X nicht auf den Fensterknöpfen (_ □ X) anderer Programme liegen
        y = int(78 * k) if "oben" in self.corner else sh - h - int(70 * k)  # unten: über der Taskleiste
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def _close_clicked(self):
        if self.on_close:
            self.on_close()
        else:
            self.hide()

    def _draw_close(self, w: int, h: int, has_text: bool):
        """Rundes X zum Schließen unten rechts an der Kugel (gut zu treffen, weit weg von fremden Fensterknöpfen)."""
        k, r = self.k, max(8, int(10 * self.k))
        cv = self.canvas
        cv.delete("xbtn")
        if has_text:
            cx, cy = w - int(14 * k) - r, h // 2
        else:
            cx, cy = w - r - 1, (h + self.d) // 2 - r - 1
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#1a1006", outline="#a0702a", width=1, tags="xbtn")
        a = max(3, int(r * 0.42))
        for x1, y1, x2, y2 in ((-a, -a, a, a), (-a, a, a, -a)):
            cv.create_line(cx + x1, cy + y1, cx + x2, cy + y2, fill="#ffd28c", width=max(2, int(1.8 * k)),
                           capstyle="round", tags="xbtn")
        cv.tag_bind("xbtn", "<Button-1>", lambda e: self._close_clicked())
        cv.tag_bind("xbtn", "<Enter>", lambda e: cv.config(cursor="hand2"))
        cv.tag_bind("xbtn", "<Leave>", lambda e: cv.config(cursor=""))
        cv.tag_raise("xbtn")

    def _animate(self):
        if not self._visible:
            self._anim_job = None
            return
        img = self._sphere_img(time.time() - self._t0)
        if img is None:
            img = make_orb(self.d, time.time() - self._t0, self.state)
        self._photo_orb = ImageTk.PhotoImage(img)
        self.canvas.itemconfigure(self.orb_item, image=self._photo_orb)
        self._anim_job = self.root.after(50, self._animate)

    def _sphere_img(self, t):
        """Die goldene HUD-Kugel in klein, auf durchsichtigem Grund (dunkle Ränder werden ausgeblendet)."""
        sp = self.sphere
        if sp is None or sp.ready() < pc_sphere.FRAMES:
            return None
        speed = 2.2 if self.state in ("listening", "speaking", "thinking") else 1.0
        i = int(t * speed * pc_sphere.FRAMES / 4.0) % pc_sphere.FRAMES
        key = (self.d, sp.color, i)
        img = self._small.get(key)
        if img is None:
            src = sp.get(i)
            if src is None:
                return None
            d = self.d
            w = src.width
            m = int(w * 0.09)  # Rand ohne Kugel abschneiden, damit sie das kleine Feld füllt
            img = src.crop((m, m, w - m, w - m)).resize((d, d), Image.LANCZOS)
            lum = img.convert("L").point(lambda v: 255 if v > 22 else 0)
            circle = Image.new("L", (d, d), 0)
            ImageDraw.Draw(circle).ellipse((1, 1, d - 2, d - 2), fill=255)
            mask = ImageChops.multiply(lum, circle)
            img = Image.composite(img, Image.new("RGB", (d, d), KEY_RGB), mask)
            if len(self._small) > 4 * pc_sphere.FRAMES:
                self._small.clear()
            self._small[key] = img
        return img

    def hide(self):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
        self._hide_job = None
        self._visible = False
        self.win.withdraw()


# --- Früheres Overlay: Leuchtrahmen + Textfeld oben (OVERLAY_STYLE = "gross") ----------
class BigOverlay:
    def __init__(self, root: tk.Tk, k: float):
        self.root, self.k = root, k
        self.sw, self.sh = root.winfo_screenwidth(), root.winfo_screenheight()

        self.frame = tk.Toplevel(root)
        self.frame.withdraw()
        self.frame.overrideredirect(True)
        self.frame.attributes("-topmost", True)
        self.frame.configure(bg=KEY)
        self.frame.attributes("-transparentcolor", KEY)
        self.frame.geometry(f"{self.sw}x{self.sh}+0+0")
        self.canvas = tk.Canvas(self.frame, width=self.sw, height=self.sh, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self._draw_glow()

        self.text = tk.Toplevel(root)
        self.text.withdraw()
        self.text.overrideredirect(True)
        self.text.attributes("-topmost", True)
        self.text.configure(bg=KEY)
        self.text.attributes("-transparentcolor", KEY)
        self.tcanvas = tk.Canvas(self.text, width=10, height=10, bg=KEY, highlightthickness=0, bd=0)
        self.tcanvas.pack()
        self.tcanvas.bind("<Button-1>", self._on_click)
        self.tcanvas.bind("<Motion>", self._on_motion)
        self.f_role = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_msg = tkfont.Font(family="Segoe UI", size=20)
        self._photo = None
        self._x_hit = (0, 0, 0)
        self._last = None
        self._hide_job = None
        self._anim_job = None
        self._glow_on = False
        self._t0 = 0.0
        self._styled = False

    def _draw_glow(self):
        self.canvas.delete("all")
        n = max(8, int(GLOW_WIDTH * self.k))
        outer, inner = P.shift_rgb(GLOW_OUTER), P.shift_rgb(GLOW_INNER)
        for i in range(n):
            t = i / (n - 1)
            r, g, b = (int(a + (c - a) * t) for a, c in zip(outer, inner))
            self.canvas.create_rectangle(
                i, i, self.sw - 1 - i, self.sh - 1 - i, outline=f"#{r:02x}{g:02x}{b:02x}", width=1
            )

    def refresh_theme(self):
        self._draw_glow()
        self._last = None

    def _render_text(self, role: str, text: str):
        k = self.k
        maxw = min(int(900 * k), self.sw - int(240 * k))
        lines = wrap_text(self.f_msg, text, maxw, MAX_LINES) if text else []
        role_h = self.f_role.metrics("linespace")
        line_h = self.f_msg.metrics("linespace")
        content_w = max([self.f_role.measure(role)] + [self.f_msg.measure(l) for l in lines])
        pad_x, pad_top, pad_bot, gap = int(44 * k), int(20 * k), int(22 * k), int(8 * k)
        w = max(int(300 * k), content_w + 2 * pad_x)
        h = pad_top + role_h + (gap + len(lines) * line_h if lines else 0) + pad_bot
        xr = int(13 * k)
        xc = (w - int(27 * k), int(27 * k))
        self._photo = ImageTk.PhotoImage(make_pill(w, h, int(30 * k), max(2, int(2 * k)), xc, xr))
        c = self.tcanvas
        c.config(width=w, height=h)
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._photo)
        c.create_text(w // 2, pad_top, text=role, font=self.f_role, fill=role_color(role), anchor="n")
        y = pad_top + role_h + gap
        for line in lines:
            c.create_text(w // 2, y, text=line, font=self.f_msg, fill=FG, anchor="n")
            y += line_h
        self._x_hit = (xc[0], xc[1], xr + int(6 * k))
        return w, h

    def _over_x(self, event) -> bool:
        cx, cy, r = self._x_hit
        return (event.x - cx) ** 2 + (event.y - cy) ** 2 <= r * r

    def _on_click(self, event):
        if self._over_x(event):
            self.hide()

    def _on_motion(self, event):
        self.tcanvas.config(cursor="hand2" if self._over_x(event) else "")

    def show(self, role: str, text: str, hide_ms: int, glow: bool):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if (role, text) != self._last:
            w, h = self._render_text(role, text)
            self.text.geometry(f"{w}x{h}+{(self.sw - w) // 2}+{int(TEXT_TOP * self.k)}")
            self._last = (role, text)
        self.text.deiconify()
        self.text.lift()
        if glow and not self._glow_on:
            self._glow_on = True
            self._t0 = time.time()
            self.frame.attributes("-alpha", 1.0)
            self.frame.deiconify()
            self.frame.lift()
        elif not glow:
            self._glow_on = False
            self.frame.withdraw()
        if not self._styled:
            make_style(self.frame, True)
            make_style(self.text, False)
            self._styled = True
        if self._glow_on and self._anim_job is None:
            self._animate()
        if hide_ms:
            self._hide_job = self.root.after(hide_ms, self.hide)

    def _animate(self):
        if not self._glow_on:
            self._anim_job = None
            return
        t = time.time() - self._t0
        flash = max(0.0, 1.0 - t / 0.7)
        alpha = 0.5 + 0.15 * math.sin(t * 3.0) + 0.35 * flash
        self.frame.attributes("-alpha", min(1.0, max(0.2, alpha)))
        self._anim_job = self.root.after(33, self._animate)

    def hide(self):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
        self._hide_job = None
        self._glow_on = False
        self.frame.withdraw()
        self.text.withdraw()


# --- Steuerzentrale für alle Anzeigen ---------------------------------------------------
class UI:
    """Nimmt Meldungen aus jedem Thread entgegen und verteilt sie an HUD und Overlay."""

    def __init__(self, on_hud_command, settings: dict):
        self.settings = settings
        self.root = tk.Tk()
        self.root.withdraw()
        self.k = max(1.0, self.root.winfo_fpixels("1i") / 96.0)  # Skalierung (Windows-Zoom)
        self.compact = CompactOverlay(self.root, self.k, settings.get("orb_size", 68), settings.get("orb_corner", "oben links"),
                                      on_close=self.cancel_all)
        self.big = None
        self.style = "klein"
        self._set_style(settings.get("overlay_style", "neu"))
        self.hud = HudWindow(
            self.root, self.k, on_hud_command,
            get_settings=lambda: self.settings,
            on_save_settings=self.apply_and_save,
            on_width=self._width_changed,
        )
        self.globe = pc_globe.GlobeWindow(self.root, self.k, lambda: self.settings, self.post_setting,
                                          host=lambda: self.hud.win)  # Karte öffnet sich im HUD selbst
        self.hud.on_globe = lambda: self.globe.show("weltlage", region=None)
        self.hud.map = self.globe  # Satellitenbild im Lage-Screen
        self.compact.sphere = self.hud.sphere  # das kleine Overlay zeigt dieselbe goldene Kugel wie das HUD
        self.q: queue.Queue = queue.Queue()
        self._idle_job = None
        self.web = None   # neues HUD (wie am Handy) im Edge-Fenster
        try:
            if settings.get("hud_style", "neu") == "neu" and pc_webhud.available():
                self.web = pc_webhud.WebHud(self, lambda t, silent=False: on_hud_command(t, silent))
        except Exception as e:
            print(f"Neues HUD nicht verfügbar ({e}), nehme das klassische.")
            self.web = None
        self.orb = None   # neues kleines Overlay (Kugel + Nervenstrang), braucht den HUD-Server
        if self.web and settings.get("overlay_style", "neu") == "neu":
            self._start_orb()
        self._allow_old = False   # nur für Dinge, die es im neuen HUD noch nicht gibt (Flug-Modus, Routen-Karte)
        if self.web:
            old_show = self.hud.show

            def guarded_show():
                if self._allow_old or not self.web.show():
                    old_show()
            self.hud.show = guarded_show
        self.root.after(100, self._poll)
        if settings.get("show_hud_on_start", True) and "--autostart" not in sys.argv:
            self.root.after(300, self._show_main_hud)

    # Aus jedem Thread aufrufbar
    def post(self, role: str, text: str = "", hide_ms: int = 0, glow: bool = False, log: bool = False):
        self.q.put(("msg", role, text, hide_ms, glow, log))

    def show_hud(self):
        self.q.put(("hud", "show"))

    def hide_hud(self):
        self.q.put(("hud", "hide"))

    def open_settings(self):
        self.q.put(("hud", "settings"))

    def post_setting(self, key: str, value):
        self.q.put(("set", key, value))

    def show_globe(self, view: str = "weltlage"):
        self.q.put(("globe", view))

    def close_globe(self):
        self.q.put(("globe", "close"))

    def tour_globe(self, seconds: float):
        self.q.put(("globe_tour", seconds))

    def show_lage_place(self, place: str, data: dict):
        self.q.put(("lage_place", place, data))

    def cancel_all(self):
        """X am kleinen Overlay: wie "abbrechen". Er hört auf zu reden, die Aufnahme wird verworfen und eine offene
        Rückfrage verfällt. Das Programm läuft weiter und wartet wieder auf das Aktivierungswort."""
        pc_cancel.cancel()
        pc_steuerung.PENDING = None
        if self._idle_job:
            self.root.after_cancel(self._idle_job)
            self._idle_job = None
        self.compact.hide()
        if self.big:
            self.big.hide()
        self.hud.set_state("idle")
        self.hud.set_status("abgebrochen")

    def post_quit(self):
        self.q.put(("quit",))

    # Nur im Tk-Thread
    def _show_main_hud(self):
        if self.web and self.web.show():
            return
        self.hud.show()

    def _hud_visible(self) -> bool:
        return self.web.is_visible() if self.web else self.hud.is_visible()

    def _hud_front(self) -> bool:
        return self.web.is_foreground() if self.web else self.hud.is_foreground()

    def sleeping(self) -> bool:
        return SLEEPING.is_set()

    def set_listening(self, on: bool):
        """Schalter oben rechts im HUD (und im Tray): an = hört aufs Aktivierungswort, aus = schläft."""
        if on:
            SLEEPING.clear()
        else:
            SLEEPING.set()
            pc_cancel.cancel()   # was gerade läuft, abbrechen
        if self.web:
            self.web.push("power", {"on": on})
            self.web.push("state", {"state": "idle"})
        self.hud.set_status("bereit" if on else "schläft")

    def think(self, kinds):
        if self.web:
            self.web.push("think", {"kinds": kinds, "ms": 4500})

    def _open_web_settings(self):
        """Einstellungen im neuen HUD öffnen (als Fenster im HUD, wie am Handy)."""
        self.compact.hide()
        if self.big:
            self.big.hide()
        if self.web.is_visible():
            self.web.show()
            self.web.push("open_settings")
        else:
            self.web.open_on_connect = True   # sobald die Seite verbunden ist
            self.web.show()

    def _open_classic_settings(self):
        """Altes Einstellungsfenster (für TimeTree und den Google-Abgleich, die es im HUD noch nicht gibt)."""
        try:
            if getattr(self, "_set_win", None) and self._set_win.winfo_exists():
                self._set_win.lift()
                return
            win = tk.Toplevel(self.root)
            win.title("Jarvis – Einstellungen")
            win.configure(bg="#04121c")
            w, h = int(820 * self.k), int(860 * self.k)
            win.geometry(f"{w}x{h}+{(self.root.winfo_screenwidth() - w) // 2}+{max(0, (self.root.winfo_screenheight() - h) // 2)}")
            win.update_idletasks()
            self._set_win = win
            dlg = pc_settingsui.SettingsDialog(win, self.settings, self.apply_and_save)

            def watch():
                try:
                    if not dlg.exists():
                        win.destroy()
                        return
                except Exception:
                    return
                win.after(400, watch)
            win.after(400, watch)
        except Exception as e:
            print(f"Einstellungen konnten nicht geöffnet werden: {e}")
            self.hud.show()
            self.root.after(250, self.hud.open_settings)

    def _start_orb(self):
        try:
            import pc_orbwin
            self.orb = pc_orbwin.OrbWin(self.web.port, self.settings.get("orb_corner", "oben links"))
        except Exception as e:
            print("Neues Overlay nicht verfügbar:", e)
            self.orb = None

    def _orb_ok(self) -> bool:
        return bool(self.style == "neu" and self.orb and self.orb.ok())

    def _set_style(self, style: str):
        self.style = style if style in ("gross", "neu") else "klein"
        if self.style == "neu" and getattr(self, "web", None) and getattr(self, "orb", None) is None:
            self._start_orb()
        if self.style != "neu" and getattr(self, "orb", None):
            self.orb.stop()
            self.orb = None
        if self.style == "gross" and self.big is None:
            self.big = BigOverlay(self.root, self.k)

    def apply_and_save(self, new: dict):
        """Wird vom Einstellungsfenster (und der Nadel im HUD) aufgerufen."""
        old = self.settings
        self.settings = new
        if self.web and {k: v for k, v in old.items() if k not in ("hud_mode", "hud_width", "seen_new")} != \
                {k: v for k, v in new.items() if k not in ("hud_mode", "hud_width", "seen_new")}:
            self.web.push("settings", {})   # neues HUD lädt die geänderten Einstellungen
        if self.web and new.get("hud_mode") != old.get("hud_mode") and new.get("hud_mode") in ("fokus", "info", "lage", "steuern"):
            self.web.push("mode", {"mode": new["hud_mode"]})
        pc_settings.save(new)
        apply_settings(new)
        self._set_style(new.get("overlay_style", "neu"))
        if self.orb:
            self.orb.set_corner(new.get("orb_corner", "oben links"))
        self.compact.set_size(new.get("orb_size", 68))
        self.compact.set_corner(new.get("orb_corner", "oben links"))
        if self.big:
            self.big.refresh_theme()
        self.hud.apply_settings(new)
        self.globe.apply_settings(new)

    def _width_changed(self, width: int):
        self.settings["hud_width"] = width
        pc_settings.save(self.settings)


    def _show_hud_only(self):
        self.compact.hide()
        if self.big:
            self.big.hide()
        self.hud.show()

    def _old_only(self):
        """Etwas, das es nur im alten HUD gibt (Flug, Routen): altes zeigen, neues zu."""
        self.compact.hide()
        if self.big:
            self.big.hide()
        if self.web:
            self.web.hide()
        self._allow_old = True
        try:
            self.hud.show()
        finally:
            self._allow_old = False

    def _close_old(self):
        try:
            self.globe.close()
        except Exception:
            pass
        self.hud.hide()

    def _show_lage(self, place: str = None):
        if self.web:   # neues HUD: Lage-Seite im Edge-Fenster
            self.compact.hide()
            if self.big:
                self.big.hide()
            self._close_old()
            self.web.show()
            if place:
                threading.Thread(target=self.web._get_lage, args=(place, False), daemon=True).start()
            self.web.push("mode", {"mode": "lage"})
            return
        self._show_hud_only()
        if self.hud.mode != "lage":
            self._mode_before_lage = self.hud.mode
            self.hud.set_mode("lage")
    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "quit":
                    if self.orb:
                        self.orb.stop()
                    self.root.destroy()
                    return
                if item[0] == "apply":   # Einstellungen vom Handy übernommen
                    self.apply_and_save(item[1])
                elif item[0] == "web_settings":
                    self._open_web_settings()
                elif item[0] == "listen":
                    self.set_listening(item[1])
                elif item[0] == "classic_settings":
                    self._open_classic_settings()
                elif item[0] == "clipboard":
                    self.root.clipboard_clear()
                    self.root.clipboard_append(item[1])
                elif item[0] == "set":
                    new = dict(self.settings)
                    new[item[1]] = item[2]
                    self.apply_and_save(new)
                elif item[0] == "speak_chunk":
                    try:
                        if self.web:
                            self.web.on_text(item[1])
                        else:
                            self.hud.lage_on_text(item[1])
                    except Exception:
                        pass
                elif item[0] == "globe_tour":  # Briefing läuft: im HUD-Lage-Modus die Orte abfliegen
                    secs = item[1]
                    self._show_lage()
                    if self.web:
                        threading.Thread(target=self.web.tour, args=(secs,), daemon=True).start()
                    else:
                        self.root.after(400, lambda secs=secs: self.hud.lage_tour(secs))
                elif item[0] == "globe" and self.web and item[1] not in ("luftraum", "close"):
                    # neues HUD: alle Karten-Wünsche landen auf der Lage-Seite
                    v = item[1]
                    self._show_lage(self.settings.get("home_city") or "Leonberg" if v == "leonberg" else None)
                elif item[0] == "globe":
                    if item[1] == "close" and self.web:
                        self.web.push("mode", {"mode": "info"})
                        self._close_old()
                    elif item[1] == "close":
                        self.globe.close()
                        if self.hud.mode == "lage":
                            self.hud.set_mode(getattr(self, "_mode_before_lage", "info"))
                    elif item[1] == "luftraum":  # Flugverkehr = Flug-Modus im HUD (gleicher Globus)
                        self._old_only() if self.web else self._show_hud_only()
                        if self.hud.mode != "flug":
                            self._mode_before_lage = self.hud.mode
                            self.hud.set_mode("flug")
                    elif item[1] in ("weltlage", "welt"):  # Weltlage = Hologramm-Globus im HUD (Vorschaubild 3)
                        self._show_lage()
                        if not self.web:
                            self.root.after(300, lambda: self.hud.show_place(None))
                    elif self.globe.is_open():
                        self.globe.show(item[1], region=None)
                    else:
                        self._show_hud_only()  # Datenpunkt fliegt aus der Kugel, dann öffnet sich die Karte
                        view = item[1]
                        self.hud.launch(lambda view=view: self.globe.show(view, region=None))
                elif item[0] == "routes":  # Wege auf der Karte im HUD zeigen
                    self._old_only() if self.web else self._show_hud_only()
                    self.globe.show(None, region=None)
                    self.globe.set_routes(*item[1:])
                elif item[0] == "lage_place":  # "Wie ist die Lage in Seoul?"
                    self._show_lage()
                    place, data = item[1], item[2]
                    if self.web:
                        d = dict(data or {})
                        d.pop("schlagzeilen", None)
                        d.setdefault("stadt", self.settings.get("home_city") or "Leonberg")
                        self.web.push("lage", {"data": d, "tour": True})
                    else:
                        self.root.after(300, lambda: self.hud.show_place(place, data))
                elif item[0] == "hud":
                    if item[1] == "toggle":   # Knopf auf dem Handy
                        item = ("hud", "hide" if self._hud_visible() else "show")
                    if self.web and item[1] == "show":
                        self.compact.hide()
                        if self.big:
                            self.big.hide()
                        self._close_old()
                        self._show_main_hud()
                    elif self.web and item[1] == "settings":
                        self._open_web_settings()
                    elif self.web and item[1] == "hide":
                        self.web.hide()
                    elif item[1] in ("show", "settings"):
                        self.compact.hide()
                        if self.big:
                            self.big.hide()
                        self.hud.show()
                        if item[1] == "settings":
                            self.root.after(250, self.hud.open_settings)
                    else:
                        self.hud.hide()
                else:
                    self._handle(*item[1:])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, role: str, text: str, hide_ms: int, glow: bool, log: bool):
        state = state_for(role, text)
        self.hud.set_state(state)
        if self.web:
            self.web.push("state", {"state": state})
            if text.strip(" …") and role in ("Du", "Assistent"):
                self.web.push("msg", {"role": role, "text": text})
        shown = text if text.strip(" …") else ""
        self.hud.set_status(f"{role}: {shown}" if shown and role in ("Du", "Assistent") else (shown or role))
        if log and shown:
            self.hud.add_log(role, shown)
        if self._idle_job:
            self.root.after_cancel(self._idle_job)
            self._idle_job = None
        if hide_ms:
            self._idle_job = self.root.after(hide_ms, self._to_idle)
        if self._hud_front():  # HUD liegt vorn: Der Reaktor zeigt den Zustand, kein Overlay nötig
            self.compact.hide()
            if self.big:
                self.big.hide()
            if self.web:
                self.web.push("orb", {"show": False})
            return
        if self._orb_ok():     # neues Overlay: Kugel mit Nervenstrang (bekommt state/msg oben schon über /events)
            self.compact.hide()
            if self.big:
                self.big.hide()
            self.web.push("orb", {"show": True})
            return
        if self.style == "gross" and self.big:
            self.compact.hide()
            self.big.show(role, text, hide_ms, glow)
        else:
            if self.big:
                self.big.hide()
            self.compact.show(role, text, hide_ms, state)

    def _to_idle(self):
        self._idle_job = None
        self.hud.set_state("idle")
        if self.web:
            self.web.push("state", {"state": "idle"})
        self.hud.set_status("bereit")


# --- Tray-Symbol (optional, braucht pystray + pillow) ---------------------------------
def start_tray(ui: UI, stop: threading.Event):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        print("Hinweis: pystray fehlt, kein Tray-Symbol. Beenden mit Strg+C.")
        return None

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((6, 6, 58, 58), fill=ACCENT)

    def on_show(icon, item):
        ui.show_hud()

    def on_settings(icon, item):
        ui.open_settings()

    def on_quit(icon, item):
        stop.set()
        icon.stop()
        ui.post_quit()

    icon = pystray.Icon(
        "pc_assistent",
        img,
        "PC-Assistent",
        menu=pystray.Menu(
            pystray.MenuItem("HUD anzeigen", on_show, default=True),
            pystray.MenuItem("Einstellungen", on_settings),
            pystray.MenuItem("Zuhören", lambda icon, item: ui.q.put(("listen", SLEEPING.is_set())),
                             checked=lambda item: not SLEEPING.is_set()),
            pystray.MenuItem("Beenden", on_quit),
        ),
    )
    icon.run_detached()
    return icon


# --- Assistent im Hintergrund-Thread -------------------------------------------------------
def spoken(result: str) -> str:
    """Macht aus technischen Meldungen einen natürlichen gesprochenen Satz."""
    parts = []
    for line in result.splitlines():
        low = line.lower().strip()
        if not low:
            continue
        if low.startswith(("taste gedrückt", "geöffnet:")):
            line = "Okay."
        elif "api_key" in low:
            line = "Dafür brauche ich den A P I Schlüssel."
        elif any(w in low for w in ("fehlgeschlagen", "konnte", "unbekannt", "nicht erlaubt")):
            line = "Das hat leider nicht geklappt."
        line = line.replace("API", "A P I")
        if not parts or parts[-1] != line:
            parts.append(line)
    return " ".join(parts)


_HOME = {}


def home_position():
    """Breite, Länge und Name des Standorts (Einstellung "home_city", Standard Leonberg), einmal ermittelt."""
    city = pc_news.CITY or "Leonberg"
    if city.lower() == "leonberg":
        return pc_globe.HOME_DEFAULT
    if _HOME.get("city") != city:
        try:
            import pc_info

            lat, lon, name = pc_info.geocode(city)
            _HOME.update(city=city, pos=(float(lat), float(lon), name))
        except Exception:
            return pc_globe.HOME_DEFAULT
    return _HOME["pos"]


def world_command(command: str, ui: "UI"):
    """Weltlage, Luftraum und Globus per Sprache. Gibt die Antwort zurück oder None."""
    low = pc_talk._norm(command)
    auto = bool(ui.settings.get("globe_auto_open", True))
    if pc_news.CLOSE.search(low):
        ui.close_globe()
        return "Globus geschlossen."
    if pc_news.LUFT.search(low):
        ui.show_globe("luftraum")
        ui.post("Assistent", "Ich schaue in den Luftraum …", glow=True)
        lat, lon, _ = home_position()
        try:
            return pc_flights.summary(pc_flights.around(lat, lon, 250), lat, lon)
        except Exception:
            return "Die Flugdaten sind gerade nicht erreichbar. Der Globus zeigt, was ich bekomme."
    city = (ui.settings.get("home_city") or "Leonberg").lower()
    if city in low and re.search(r"lage|los|neu|passiert|nachrichten|news|zeig|karte", low):
        ui.show_globe("leonberg")
        data = pc_news.get() or {}
        pts = [q for q in data.get("brennpunkte") or [] if q.get("art") == "lokal"]
        if not pts:
            return f"Hier ist {city.title()}. Gerade habe ich keine besonderen lokalen Meldungen."
        return f"Aus {city.title()} und Umgebung: " + ". ".join(f"{q['titel']} in {q['ort']}" for q in pts[:4]) + "."
    m = pc_news.PLACE_ASK.search(low)
    if m and not re.match(r"(?:deutschland|der welt|welt|europa|der gegend|der nähe)$", m.group(1).strip()):
        place = m.group(1).strip().title()
        ui.post("Assistent", f"Ich schaue, was in {place} los ist …", glow=True)
        data = pc_news.get_place(place) or {}
        ui.show_lage_place(place, data)
        text = (data.get("briefing") or "").strip()
        if text:
            ui.tour_globe(len(text) / 14.0)
        return text or f"Zu {place} finde ich gerade nichts."
    if pc_news.DEUTSCHLAND.search(low):
        ui.show_globe("deutschland")
        data = pc_news.get() or {}
        pts = [q for q in data.get("brennpunkte") or [] if q.get("deutschland")]
        if not pts:
            return "Hier ist Deutschland. Gerade habe ich keine besonderen Meldungen mit Ort in Deutschland."
        return "Aus Deutschland: " + ". ".join(f"{q['titel']} in {q['ort']}" for q in pts[:3]) + "."
    if pc_news.SHOW.search(low):
        ui.show_globe("weltlage")
        return "Bitte sehr, die Weltlage."
    if pc_news.LAGE.search(low):
        if auto:
            ui.show_globe("weltlage")
        ui.post("Assistent", "Ich hole die aktuelle Lage …", glow=True)
        text = pc_news.briefing_text(timeout_s=25)
        if text and auto:  # während er spricht, fliegt der Globus die Brennpunkte ab
            ui.tour_globe(len(text) / 14.0)
        return text or "Ich komme gerade nicht an die Nachrichten."
    return None


def run_command(command: str, ui: UI, ai_available: bool, shutdown, quiet_unknown: bool = False, out: list = None,
                silent: bool = False) -> bool:
    """Führt einen Befehl aus. Gibt False zurück, wenn er im leisen Modus nichts damit anfangen konnte."""
    ai_available = pc_ai.available()  # zählt live, auch wenn der Schlüssel erst jetzt eingetragen wurde
    gen = pc_cancel.GEN
    print(f"Befehl: {command}")
    if command != "__nachricht__":   # Ansage einer Nachricht: kein "Du hast gesagt"
        ui.post("Du", command, glow=True, log=True)
    try:
        pc_themen.note(command)   # daraus lernt Jarvis (zusammen mit dem Handy), was dich interessiert
        ui.think(pc_webhud.think_for(command))   # passende Symbole im Gehirn der Kugel leuchten auf
    except Exception:
        pass
    if out is None and pc_live.START.search(command):  # "lass uns reden": Live-Gespräch (startet die Hörschleife)
        ui.post("Assistent", "Ich verbinde dich mit mir …", 3000, glow=True)
        pc_live.REQUEST.set()
        return True
    t_start = time.time()
    result = pc_nachrichten.handle(command)  # Nachrichten von wichtigen Leuten: vorlesen, abspielen, antworten
    if result is None:
        result = pc_ets2.handle(command)  # ETS2-Beifahrer: "wie weit noch?", "wie viel Sprit?"
    if result is None:
        result = pc_input.handle(command)  # "trag meine E-Mail ein", "drück Enter"
    if result is None:
        result = pc_voiceset.handle(command, ui.settings)  # Einstellungen per Sprache ("dein Aktivierungswort ist ...")
    if result is None:
        result = pc_sehen.handle(command)  # "schau mal hier": Bildschirm ansehen (PC oder Handy)
    if result is None:
        result = pc_handy.plan_route(command)  # smarter Wegeplaner (Zwischenstopps, Bahn, "wann muss ich los") übers Handy
    if result is None:
        result = pc_messages.handle(command)  # WhatsApp- und Discord-Nachrichten schreiben
    if result is None:
        result = pc_download.handle(command)  # Dateien und Programme herunterladen
    if result is None:
        result = pc_route.handle(command)  # Routen ("wie lange mit dem Fahrrad nach ...") und aufs Handy schicken
    if result is None and re.search(r"wo bin ich|wo befinde ich mich|mein standort", command.lower()):
        result = pc_phone.where_text()
    if result is None:
        result = pc_handy.handle(command)  # Anrufen, Handy-Kalender, "am Handy …", "schick mir das Lied aufs Handy"
    if result is None:
        result = pc_timetree.handle(command) or pc_calendar.handle(command)  # TimeTree-Abgleich, Termine aus dem Kalender
    if result is None:
        result = pc_memory.handle(command)  # "merk dir ...", "was weißt du über mich"
    if result is None:
        result = pc_remind.handle(command)  # Timer, Wecker, Erinnerungen
    if result is None:
        result = world_command(command, ui)  # Weltlage, Luftraum, Globus
    if result is None:
        result = handle_fixed(command)
    if result is None:  # einfache Fragen, Wetter, Plauderei, Rechnen: ohne Schlüssel
        result = pc_talk.answer(command, on_wait=lambda: ui.post("Assistent", "Einen Moment …", glow=True),
                                ai=ai_available)
    if result is None and not ai_available and quiet_unknown:
        return False  # beim Weiterhören nicht jedes Gespräch im Raum kommentieren
    if result is None:
        if ai_available:
            ui.post("Assistent", "Denke nach …", glow=True)
            t_ai = time.time()
            result = ask_ai(command)
            print(f"Zeit: KI hat {time.time() - t_ai:.1f} s gebraucht")
        else:
            result = "Das habe ich leider nicht verstanden. Für freie Gespräche trag bitte den Gemini-Schlüssel in den Einstellungen unter KI ein."
    if pc_cancel.changed(gen):  # mit dem X abgebrochen: nichts mehr sagen oder anzeigen
        return True
    while pc_steuerung.SETTING_REQUESTS:  # Einstellungen, die per Sprache geändert wurden
        key, value = pc_steuerung.SETTING_REQUESTS.pop(0)
        ui.post_setting(key, value)
    request, pc_steuerung.HUD_REQUEST = pc_steuerung.HUD_REQUEST, None
    if request == "show":
        ui.show_hud()
    elif request == "hide":
        ui.hide_hud()
    elif request == "settings":
        ui.open_settings()
    print(result)
    print(f"Zeit: Antwort fertig nach {time.time() - t_start:.1f} s (danach folgt das Sprechen)")
    if out is not None:  # aus dem Live-Gespräch: Ergebnis zurückgeben, nicht selbst sprechen
        out.append(result)
        ui.post("Assistent", result, 3000, glow=True, log=True)
        return True
    talk = SPEAK and not silent   # getippt (silent): nur als Text antworten
    if talk:
        ui.post("Assistent", result, glow=True, log=True)
        speak(spoken(result))
    if pc_steuerung.QUIT_REQUESTED:
        shutdown()
        return True
    ui.post("Assistent", result, 2500 if talk else 8000, glow=True, log=not talk)
    return True


class Session:
    """Eine Äußerung. Nach ihrem Ende dürfen Zwischenergebnisse nichts mehr anzeigen."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = True
        self.woke = False


class LiveTranscriber:
    """Erkennt zwischendurch den bisher gesprochenen Teil (höchstens eine Anfrage gleichzeitig)."""

    def __init__(self, recognizer: sr.Recognizer, handler):
        self.recognizer = recognizer
        self.handler = handler
        self.busy = False

    def submit(self, raw: bytes):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._work, args=(raw,), daemon=True).start()

    def _work(self, raw: bytes):
        try:
            text = transcribe(self.recognizer, raw, quiet=True)
            if text:
                self.handler(text)
        except Exception:
            pass
        finally:
            self.busy = False


def listen_live(q, threshold, handler, live_rec, max_wait=None):
    sess = Session()
    live = LiveTranscriber(live_rec, lambda text: handler(sess, text))
    raw = listen_utterance(q, threshold, max_wait=max_wait, on_progress=live.submit)
    with sess.lock:
        sess.active = False
    return raw, sess


def follow_seconds() -> int:
    """So lange hört er nach einem Befehl weiter zu. Bei einer offenen Rückfrage (z. B. Herunterfahren) länger."""
    return 10 if pc_steuerung.awaiting() else FOLLOWUP_SECONDS


class BargeIn:
    """Während Jarvis spricht, hört er weiter auf sein Aktivierungswort. Sagst du es, hört er sofort auf zu reden
    (und macht gleich mit dem Befehl dahinter weiter, z. B. "Jarvis, stopp" oder "Jarvis, mach Musik an")."""

    STOP_WORDS = re.compile(r"^(?:stopp?|halt|ruhe|still|sei still|hör auf|aufhören|abbrechen|danke|okay|ok|schon gut|"
                            r"genug|leise|pause)?\W*$", re.I)

    def __init__(self, q, threshold, recognizer):
        self.q, self.rec = q, recognizer
        self.thr = threshold * 1.3  # etwas lauter als Stille: die eigene Stimme aus den Boxen soll nicht zählen
        self.hit = False
        self.command = ""
        self._stop = threading.Event()
        self._busy = False
        self._next = None
        self._lock = threading.Lock()
        self._t = None

    def __enter__(self):
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._t:
            self._t.join(1.0)
        return False

    def _run(self):
        buf, quiet = [], 0
        echo = 0.0   # wie laut die eigene Stimme aus den Boxen gerade im Mikrofon ankommt (gleitender Mittelwert)
        while not self._stop.is_set() and not self.hit:
            try:
                chunk = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            if not pc_audio._speaking:  # nur während er spricht
                buf, quiet = [], 0
                continue
            lvl = pc_assistent.rms(chunk)
            loud = lvl > max(self.thr, echo * 1.6)
            echo = echo * 0.97 + lvl * 0.03 if not loud else echo * 0.995 + lvl * 0.005
            if loud:
                buf.append(chunk)
                quiet = 0
            elif buf:
                buf.append(chunk)
                quiet += 1
            # kurze Stücke (das Weckwort ist kurz) und nichts verwerfen: ist die Erkennung beschäftigt, kommt das
            # neueste Stück als Nächstes dran (vorher ging es verloren, deshalb klappte das Unterbrechen oft nicht)
            if buf and (quiet >= 3 or len(buf) >= 22):
                if len(buf) - quiet >= 2:
                    raw = b"".join(buf)
                    with self._lock:
                        if self._busy:
                            self._next = raw
                        else:
                            self._busy = True
                            threading.Thread(target=self._check, args=(raw,), daemon=True).start()
                buf = buf[-2:] if len(buf) >= 22 else []   # bei langen Stücken etwas Überlappung behalten
                quiet = 0

    def _heard(self, text: str):
        low = (text or "").lower()
        wake = next((w for w in WAKE_WORDS if w in low), None)
        if not wake:   # ungenau gehört, z. B. "freitag" statt "friday"
            words = re.findall(r"[a-zäöüß]+", low)
            for w in WAKE_WORDS:
                for i, x in enumerate(words):
                    if len(x) >= 4 and _similar(x, w):
                        return w, " ".join(text.split()[i + 1:]) if len(text.split()) > i else ""
            return None, ""
        return wake, text[low.index(wake) + len(wake):].strip(" ,.!?")

    def _check(self, raw):
        while raw is not None:
            try:
                text = transcribe(self.rec, raw, quiet=True)
                wake, rest = self._heard(text)
                if wake and not self.hit and not self._stop.is_set():
                    self.hit = True
                    rest = rest.strip(" ,.!?")
                    self.command = "" if self.STOP_WORDS.match(rest) else rest
                    print(f"Unterbrochen: {text}")
                    pc_cancel.cancel()  # sofort still
            except Exception:
                pass
            with self._lock:
                raw, self._next = (self._next, None) if not self.hit else (None, None)
                if raw is None:
                    self._busy = False


def _similar(a: str, b: str) -> bool:
    """Ähnlich genug fürs Weckwort (höchstens ein Buchstabe pro vier anders)."""
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def assistant_loop(ui: UI, stop: threading.Event, shutdown):
    try:
        ai_available = pc_ai.available()
        recognizer = sr.Recognizer()
        live_rec = sr.Recognizer()
        q: queue.Queue = queue.Queue()

        def callback(indata, frames, t, status):
            raw = bytes(indata)
            q.put(raw)
            try:  # Lautstärke für die "atmende" Kugel im HUD
                pc_sphere.set_level("mic", max(0.0, (pc_assistent.rms(raw) - 150) / 2500))
            except Exception:
                pass

        def wake_handler(sess: Session, text: str):
            low = text.lower()
            wake = next((w for w in WAKE_WORDS if w in low), None)
            if not wake:
                return
            shown = text[low.index(wake) + len(wake):].strip(" ,.!?")
            with sess.lock:
                if not sess.active:
                    return
                if not sess.woke:
                    sess.woke = True
                    if EARLY_CHIME:
                        play_chime()
                ui.post("Du", shown or "…", glow=True)

        def follow_handler(sess: Session, text: str):
            with sess.lock:
                if sess.active:
                    ui.post("Du", text, glow=True)

        with sd.RawInputStream(
            samplerate=RATE,
            blocksize=BLOCK,
            dtype="int16",
            channels=1,
            device=pc_assistent.INPUT_DEVICE,
            callback=callback,
        ):
            ui.post("Starte …", "Messe Umgebungslautstärke, bitte kurz ruhig sein")
            threshold = calibrate(q)
            wake_hint = f"Sag „{WAKE_WORDS[0]}“" + (f" · KI: {pc_ai.provider_name()}" if pc_ai.available() else "")
            print("Bereit.", wake_hint)
            ui.post("Bereit", wake_hint, 3000)
            global _GREETED
            if (GREET_ON_START or pc_assistent_announce[0] or ui.settings.get("briefing_on_start", True)) and not _GREETED:
                _GREETED = True
                if pc_assistent_announce[0]:
                    pc_timetree.wait_first_sync(25)  # neueste Termine holen, bevor er sie ansagt
                    day = pc_calendar.today_text()
                else:
                    day = ""
                hello = ((pc_talk.greeting() if GREET_ON_START else pc_talk.short_hello()) + " " + day + " "
                         + pc_memory.upcoming_text()).strip()
                if ui.settings.get("briefing_on_start", True):
                    lage = pc_news.briefing_text(timeout_s=15)
                    if lage:
                        hello += " Kurz zur Lage: " + lage
                ui.post("Assistent", hello, 4000, glow=True, log=True)
                if SPEAK:
                    with BargeIn(q, threshold, recognizer):
                        speak(hello)
                    drain(q)

            def live_talk():
                """Live-Gespräch mit dem Cloud-Jarvis (natürliches Hin und Her, unterbrechbar)."""
                drain(q)

                def run_pc(c):
                    out = []
                    run_command(c, ui, ai_available, shutdown, out=out)
                    return out[0] if out else "Erledigt."
                err = pc_live.LiveSession(q, threshold, ui, run_pc, ui.settings).run()
                drain(q)
                if err:
                    ui.post("Fehler", err, 6000)
                    if SPEAK:
                        speak(err)
                else:
                    ui.post("Bereit", f"Sag „{WAKE_WORDS[0]}“", 2500)

            while not stop.is_set() and not RESTART_AUDIO.is_set():
                if SLEEPING.is_set():   # ausgeschaltet: nichts auswerten, bis er wieder an ist
                    drain(q)
                    stop.wait(0.3)
                    continue
                if pc_live.REQUEST.is_set():  # Knopf im HUD oder "lass uns reden"
                    pc_live.REQUEST.clear()
                    live_talk()
                    continue
                if pc_nachrichten.take_announce():   # Nachricht von einem wichtigen Menschen: ansagen wie eine Antwort
                    gen = pc_cancel.GEN
                    play_chime()
                    command = "__nachricht__"
                else:
                    gen = pc_cancel.GEN
                    raw, sess = listen_live(q, threshold, wake_handler, live_rec, max_wait=1)
                    if raw is None:
                        continue
                    if pc_audio.busy_recently():  # das war wohl meine eigene Stimme (z. B. eine Erinnerung)
                        continue
                    print("Zeit: Satzende erkannt, starte Spracherkennung")
                    text = transcribe(recognizer, raw)
                    if pc_cancel.changed(gen):
                        drain(q)
                        continue
                    wake = None
                    if text:
                        print(f"Gehört: {text}")
                        low = text.lower()
                        wake = next((w for w in WAKE_WORDS if w in low), None)
                    if not wake:
                        if sess.woke:  # Live-Anzeige war schon da, am Ende passte es aber nicht
                            ui.post("Nicht verstanden", "Bitte nochmal", 2000, glow=True)
                        continue

                    command = text[low.index(wake) + len(wake):].strip(" ,.!?")
                    if not (sess.woke and EARLY_CHIME):
                        play_chime()

                    if not command:
                        ui.post("Ich höre …", "Sag deinen Befehl", glow=True)
                        time.sleep(0.7)  # Sound ausklingen lassen, damit das Mikrofon ihn nicht hört
                        drain(q)
                        raw, _ = listen_live(q, threshold, follow_handler, live_rec, max_wait=6)
                        if pc_cancel.changed(gen):
                            drain(q)
                            continue
                        if raw is None:
                            ui.post("Nichts gehört", "", 1500, glow=True)
                            continue
                        command = transcribe(recognizer, raw).strip()
                        if not command:
                            ui.post("Nicht verstanden", "Bitte nochmal", 2000, glow=True)
                            continue
                def run_barge(cmd, quiet_unknown=False):
                    """Befehl ausführen; wird er beim Reden unterbrochen, gleich den neuen Befehl nehmen."""
                    ok = False
                    while True:
                        with BargeIn(q, threshold, recognizer) as bi:
                            ok = run_command(cmd, ui, ai_available, shutdown, quiet_unknown=quiet_unknown)
                        drain(q)
                        if not bi.hit:
                            return ok, False
                        play_chime()
                        if not bi.command:
                            ui.post("Ich höre …", "", 2500, glow=True)
                            return True, True
                        cmd, quiet_unknown = bi.command, False
                        ui.post("Du", cmd, glow=True)

                _, barged = run_barge(command)
                if pc_live.REQUEST.is_set():
                    pc_live.REQUEST.clear()
                    live_talk()
                    continue
                if barged:
                    gen = pc_cancel.GEN  # unterbrochen: danach normal weiterhören
                if pc_cancel.changed(gen):
                    continue

                # Weiterhören: ohne Aktivierungswort weitersprechen, solange die Zeit läuft
                def _fs():   # nach einer Nachrichten-Ansage länger zuhören (Antwort ohne Aktivierungswort)
                    return max(follow_seconds(), 20) if pc_nachrichten.awaiting() else follow_seconds()
                deadline = time.time() + _fs() if _fs() > 0 else 0
                while time.time() < deadline and not stop.is_set() and not pc_steuerung.QUIT_REQUESTED:
                    ui.post("Ich höre …", "", int((deadline - time.time()) * 1000) + 300, glow=True)
                    raw, _ = listen_live(q, threshold, follow_handler, live_rec, max_wait=max(0.5, deadline - time.time()))
                    if raw is None or pc_cancel.changed(gen):
                        break
                    heard = transcribe(recognizer, raw).strip()
                    print(f"Gehört (weiter): {heard}")
                    if pc_cancel.changed(gen):
                        break
                    if not heard:
                        continue  # Rauschen: die Restzeit läuft weiter
                    low2 = heard.lower()
                    wake2 = next((w for w in WAKE_WORDS if w in low2), None)
                    if wake2:
                        play_chime()
                    follow = (heard[low2.index(wake2) + len(wake2):] if wake2 else heard).strip(" ,.!?")
                    if not follow:  # nur das Aktivierungswort gesagt: Zeit neu starten
                        deadline = time.time() + _fs()
                        continue
                    if follow.lower() in END_PHRASES and not pc_steuerung.awaiting():
                        ui.post("Assistent", "Gern.", 1500, glow=True)
                        if SPEAK:
                            speak("Gern.")
                        drain(q)
                        break
                    ok, barged = run_barge(follow, quiet_unknown=True)
                    if pc_live.REQUEST.is_set():
                        pc_live.REQUEST.clear()
                        live_talk()
                        break
                    if barged:
                        gen = pc_cancel.GEN
                    if ok:
                        drain(q)
                        deadline = time.time() + _fs()  # nach jedem Befehl erneut die volle Zeit
    except Exception as e:
        print(f"Fehler im Assistenten: {e}")
        ui.post("Fehler", str(e), 8000)


def on_reminder_due(item: dict, late: float, ui: UI):
    """Ein Timer, Wecker oder eine Erinnerung ist fällig."""
    text = pc_remind.due_text(item, late)
    print(text)
    ui.post("Assistent", text, 10000, glow=True, log=True)
    play_chime()
    time.sleep(0.8)
    if SPEAK:
        speak(text)


def on_download_done(text: str, ui: UI):
    """Ein Download oder eine Installation ist fertig."""
    ui.post("Assistent", text, 9000, glow=True, log=True)
    if SPEAK:
        speak(text)


def assistant_runner(ui: UI, stop: threading.Event, shutdown):
    """Startet die Hör-Schleife und startet sie bei einem Mikrofonwechsel neu."""
    while not stop.is_set():
        RESTART_AUDIO.clear()
        assistant_loop(ui, stop, shutdown)
        if not RESTART_AUDIO.is_set():
            break


# --- Start -----------------------------------------------------------------------------------
_MUTEX = None


SHOW_EVENT = "Jarvis.PCAssistent.ShowHud"


def signal_show():
    """Dem schon laufenden Jarvis sagen: HUD zeigen."""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenEventW.restype = ctypes.c_void_p
        h = k32.OpenEventW(0x0002, False, SHOW_EVENT)   # EVENT_MODIFY_STATE
        if h:
            k32.SetEvent(ctypes.c_void_p(h))
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        pass


def listen_show(ui):
    """Wartet auf signal_show() von einem zweiten Start und öffnet dann das HUD."""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateEventW.restype = ctypes.c_void_p
        h = k32.CreateEventW(None, False, False, SHOW_EVENT)
        if not h:
            return
        while True:
            if k32.WaitForSingleObject(ctypes.c_void_p(h), 0xFFFFFFFF) == 0:
                ui.show_hud()
    except Exception:
        pass


def make_start_shortcut():
    """Verknüpfung „Jarvis“ im Startmenü (zum Anheften an die Taskleiste). Nur bei der fertigen .exe."""
    if not getattr(sys, "frozen", False):
        return
    try:
        folder = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
        lnk = os.path.join(folder, "Jarvis.lnk")
        if os.path.isdir(folder) and not os.path.exists(lnk):
            import subprocess
            ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{sys.executable}';"
                  f"$s.WorkingDirectory='{os.path.dirname(sys.executable)}';$s.IconLocation='{sys.executable},0';"
                  "$s.Description='Jarvis öffnen';$s.Save()")
            subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], timeout=20,
                           creationflags=0x08000000)
    except Exception as e:
        print(f"Startmenü-Verknüpfung ging nicht: {e}")


def already_running() -> bool:
    """Verhindert, dass der Assistent zweimal gleichzeitig läuft (zwei Mikrofon-Hörer)."""
    global _MUTEX
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k32.CreateMutexW.restype = ctypes.c_void_p
        _MUTEX = k32.CreateMutexW(None, False, "Jarvis.PCAssistent.SingleInstance")
        return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False


class _LogTee:
    """Schreibt alle Meldungen mit Uhrzeit zusätzlich in jarvis_log.txt (neben dem Programm).
    So sieht man auch bei der unsichtbaren PC-Assistent.exe, wo Zeit verloren geht."""

    def __init__(self, stream, f):
        self.stream, self.f, self.start = stream, f, True

    def write(self, s):
        if self.stream is not None:
            try:
                self.stream.write(s)
            except Exception:
                pass
        try:
            out = []
            for ch in s.splitlines(keepends=True):
                if self.start:
                    out.append(time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d} ")
                out.append(ch)
                self.start = ch.endswith("\n")
            self.f.write("".join(out))
        except Exception:
            pass
        return len(s)

    def flush(self):
        for x in (self.stream, self.f):
            try:
                x.flush()
            except Exception:
                pass


def setup_log():
    try:
        path = os.path.join(pc_apps.base_dir(), "jarvis_log.txt")
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".alt")
        f = open(path, "a", encoding="utf-8", buffering=1)
        f.write(f"\n===== Start {time.strftime('%d.%m.%Y %H:%M:%S')} =====\n")
        sys.stdout = _LogTee(sys.stdout, f)
        sys.stderr = _LogTee(sys.stderr, f)
    except Exception:
        pass


VERSION = "2026-11-14 02:40"   # bei jedem Update neu: steht im Protokoll, damit klar ist, welcher Stand läuft


def main():
    setup_log()
    print(f"Jarvis-Version: {VERSION}")
    if already_running():
        if "--autostart" not in sys.argv:   # z. B. Klick auf das angeheftete Symbol: laufenden Jarvis nach vorne holen
            signal_show()
        print("Jarvis läuft schon – HUD wird gezeigt.")
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:  # eigene Kennung, damit das Anheften an die Taskleiste sauber funktioniert
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Jarvis.PCAssistent")
    except Exception:
        pass
    settings = pc_settings.load()
    if not settings.get("ntfy_topic") or not settings.get("loc_topic"):  # geheime Handy-Kanäle einmalig erzeugen
        settings["ntfy_topic"] = settings.get("ntfy_topic") or pc_phone.new_topic("nachricht")
        settings["loc_topic"] = settings.get("loc_topic") or pc_phone.new_topic("standort")
        pc_settings.save(settings)
    apply_settings(settings)
    ai_available = pc_ai.available()
    stop = threading.Event()

    def hud_command(cmd: str, silent: bool = False):  # Klick auf einen Knopf im HUD, getippte Frage (silent)
        threading.Thread(target=run_command, args=(cmd, ui, ai_available, shutdown), kwargs={"silent": silent}, daemon=True).start()

    ui = UI(hud_command, settings)
    icon = start_tray(ui, stop)
    threading.Thread(target=listen_show, args=(ui,), daemon=True).start()   # Klick aufs angeheftete Symbol
    threading.Thread(target=make_start_shortcut, daemon=True).start()

    def shutdown():
        stop.set()
        if icon:
            try:
                icon.stop()
            except Exception:
                pass
        ui.post_quit()

    threading.Thread(target=pc_apps.preload, daemon=True).start()  # Programmliste vorladen
    if settings.get("briefing_on_start", True):  # Nachrichten schon mal holen, damit das Briefing beim Start bereit ist
        threading.Thread(target=pc_news.get, daemon=True).start()
    pc_remind.Scheduler(lambda item, late: on_reminder_due(item, late, ui)).start()  # Timer und Erinnerungen
    pc_download.NOTIFY = lambda text: on_download_done(text, ui)
    pc_telegram.ON_CHAT_ID = lambda cid: ui.post_setting("telegram_chat", cid)
    pc_route.ON_SHOW = lambda routes, idx, a, b: ui.q.put(("routes", routes, idx, a, b))
    pc_audio.ON_CHUNK = lambda text: ui.q.put(("speak_chunk", text))  # Briefing: Globus fliegt passend zum Satz
    pc_steuerung.ON_SETTING = ui.post_setting  # z. B. "sprich lauter" speichert die neue Stimm-Lautstärke
    threading.Thread(target=pc_audio.windows_voices, daemon=True).start()  # Windows-Stimmen für die Einstellungen
    pc_link.ON_SETTINGS = lambda new: ui.q.put(("apply", new))  # Einstellungen, die am Handy geändert wurden
    pc_link.start(stop)  # Gedächtnis und Persönlichkeit mit der Handy-App abgleichen
    def _status(t):
        ui.post("Assistent", t, glow=True)
        if SPEAK:
            speak(t)
    pc_nachrichten.ON_STATUS = _status   # "Einen Moment, ich formuliere …"
    pc_remote.ON_TEXT = hud_command  # "Befehl an den PC" vom Handy
    pc_remote.ON_HUD = lambda: ui.q.put(("hud", "toggle"))
    pc_remote.SETTINGS = lambda: ui.settings
    pc_nachrichten.ON_SHOW = lambda title, text: ui.post(title, text, 60000, glow=True, log=True)
    pc_remote.start(stop)  # Handy als Fernbedienung
    pc_ets2.ON_SAY = lambda t: pc_nachrichten.incoming({"kind": "say", "force": True, "text": t})   # dezent, wie eine Nachricht
    pc_ets2.start(stop)  # ETS2-Beifahrer (Telemetrie-Plugin)
    pc_fern.HUD_PORT = lambda: (ui.web.port if getattr(ui, "web", None) else 0)
    pc_fern.SETTINGS = lambda: ui.settings
    pc_fern.ON_WATCH = lambda on: ui.post("Fernzugriff", "Die Webcam wird gerade von unterwegs angesehen." if on else "Webcam aus.",
                                          0 if on else 4000, glow=True, log=True)
    pc_fern.start(stop)  # HUD, Webcam und Handy-Kamera über Tailscale
    pc_media.start(stop)  # mitschreiben, was du hörst und schaust (für deine Interessen)
    threading.Thread(target=assistant_runner, args=(ui, stop, shutdown), daemon=True).start()
    try:
        ui.root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if icon:
            try:
                icon.stop()
            except Exception:
                pass


if __name__ == "__main__":
    main()
