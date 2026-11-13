"""
Einstellungsfenster für Jarvis. Öffnen: Zahnrad oben links im HUD, Tray-Menü oder per Sprache
"Jarvis, öffne deine Einstellungen". Gespeichert wird in einstellungen.json neben dem Programm.
"""

import os
import threading
import time
import tkinter as tk
from tkinter import ttk

import pc_ai
import pc_memory
import pc_secret
import pc_timetree
import pc_apps
import pc_calendar
import pc_gcal
import pc_audio
import pc_eleven
import pc_settings

# Farben wie im neuen HUD: dunkles Blau, cyan Linien, goldene Akzente
BG = "#04121c"
FIELD = "#0a2233"
FG = "#d2ecf8"
DIM = "#7fb3c8"
ACC = "#3cc8ff"
GOLD = "#ffd678"
LINE = "#16506a"
HOVER = "#0a2a3c"

LANGUAGES = [("Deutsch", "de-DE"), ("English (US)", "en-US"), ("English (UK)", "en-GB"),
             ("Français", "fr-FR"), ("Español", "es-ES"), ("Italiano", "it-IT")]
STYLES = [("Kleiner Kreis", "klein"), ("Leuchtrahmen + großes Textfeld", "gross")]
ENGINES = [("ElevenLabs (sehr natürlich, braucht Schlüssel)", "eleven"),
           ("Automatisch (Online-Stimme, sonst Windows)", "auto"), ("Nur Online-Stimme", "edge"),
           ("Nur Windows-Stimme (offline)", "windows")]
AUTO_WINDOWS = "Automatisch (deutsche Männerstimme)"
GLOBE_THEMES = ["Glut", "Jarvis", "Radar", "Violett"]
NEW_DOT = "#ff5a5a"

# Bereiche der Einstellungen: Titel -> (Symbol, Untertitel in der Liste)
SECTIONS = {
    "Zuhören": ("◉", "Aktivierungswort, Mikrofon, Weiterhören"),
    "Stimme": ("♪", "ElevenLabs, Ausgabe, Tempo, Wecksound"),
    "Weltlage": ("◍", "Lage-Briefing, Karte, Standort"),
    "Anzeige": ("◐", "Farbe, Kugel, Fokus/Info, Overlay"),
    "Knöpfe": ("▣", "Die Schnellstart-Knöpfe oben im HUD"),
    "Infos": ("☀", "Wetter, Kalender, TimeTree, Leistung"),
    "KI": ("✦", "Gemini, kostenloser Ersatz Groq"),
    "Meine Daten": ("✎", "Daten zum Ausfüllen von Formularen"),
    "Google eintragen": ("▦", "TimeTree-Termine in Google Kalender"),
    "Persönlichkeit": ("☺", "Name, Anrede, Begrüßung, eigene Befehle"),
    "Handy": ("✆", "Routen aufs Handy, dein Standort"),
    "Handy-App": ("▣", "Jarvis aufs Handy: gleiches Gedächtnis"),
}

# Neue Einstellungen (bekommen beim ersten Anschauen einen roten Punkt). Bei jedem Update hier ergänzen.
NEW_ITEMS = {
    "Stimme": ["Lautstärke von Jarvis' Stimme", "Stimmenart", "ElevenLabs-Schlüssel", "ElevenLabs-Stimme", "ElevenLabs-Modell"],
    "Weltlage": ["Erde langsam drehen (mit echtem Tag und Nacht)", "Flugverkehr: eigene Orte", "Beim Start ein kurzes Lage-Briefing sprechen",
                 "Bei „Wie ist die Lage?“ die Karte öffnen", "Karte im Vollbild öffnen", "Farben der Karte",
                 "Kartenstil", "Ortsnamen auf der Karte", "Standort", "Lieblingsorte",
                 "Beim Briefing ins Satellitenbild zoomen", "Eigene Themen (Für dich)", "Echte Satelliten um die Erde (ISS, Hubble …)"],
    "Anzeige": ["Modus des HUD", "Farbe der Kugel", "Stil des HUD"],
    "Knöpfe": ["Schnellstart-Knöpfe"],
    "KI": ["Groq-Schlüssel (kostenloser Ersatz)"],
    "Persönlichkeit": ["Art", "Discord-Sprachkanäle"],
    "Handy-App": ["Kopplungscode"],
    "_Handy": ["Meine Adresse", "Aufs Handy schicken über", "Telegram-Bot-Schlüssel", "Meine WhatsApp-Nummer", "Kanal für Nachrichten (ntfy)",
              "Kanal für den Standort (OwnTracks)"],
}
HIDDEN_SECTIONS = {"Handy"}  # vorerst ausgeblendet (kommt mit dem Telefon-Projekt zurück)
PHONE_CHANNELS = [("Telegram – Jarvis' eigener Bot (empfohlen)", "telegram"), ("WhatsApp an mich selbst", "whatsapp"),
                  ("ntfy-App", "ntfy")]
PERSONAS = [("Sarkastisch – ernst, mit trockenem Humor", "sarkastisch"),
            ("Butler – ruhig, trockener Humor", "butler"), ("Locker – wie ein Kumpel", "locker")]
SPHERE_COLORS = ["Gold", "Cyan", "Rot", "Grün", "Violett", "Weiß"]
MAP_STYLES = ["Satellit", "Dunkel"]
HUD_STYLES = [("Neu – wie am Handy (3D-Kugel, Satelliten-Globus)", "neu"), ("Klassisch", "klassisch")]
HUD_MODES = [("Info – Kugel mit allen Infos", "info"), ("Fokus – nur die Kugel", "fokus"),
             ("Lage – Kugel mit Weltlage-Globus", "lage"), ("Flug – Flugverkehr auf dem Globus", "flug")]
BUTTON_SLOTS = 12


def _safe(label, text):
    """Text setzen, auch wenn die Einstellungen inzwischen geschlossen wurden (dann passiert einfach nichts)."""
    try:
        if label is not None and label.winfo_exists():
            label.config(text=text)
    except Exception:
        pass


def has_unseen(settings: dict) -> bool:
    seen = set(settings.get("seen_new") or [])
    return any(i not in seen for items in NEW_ITEMS.values() for i in items)


DEFAULT_IN = "Standard-Mikrofon (Windows-Standard)"
DEFAULT_OUT = "Standard-Ausgabe (Windows-Standard)"


def device_choices(kind: str):
    """Auswahlliste als (Anzeigename, gespeicherter Wert). Wert None = Windows-Standard."""
    first = (DEFAULT_IN if kind == "input" else DEFAULT_OUT, None)
    return [first] + [(name, name) for name in pc_audio.list_devices(kind)]


def apply_style(top):
    st = ttk.Style(top)
    st.theme_use("clam")
    st.configure("J.TFrame", background=BG)
    st.configure("J.TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
    st.configure("Hint.TLabel", background=BG, foreground=DIM, font=("Segoe UI", 8))
    st.configure("J.TCheckbutton", background=BG, foreground=FG, font=("Segoe UI", 10), wraplength=400)
    st.map("J.TCheckbutton", background=[("active", BG)])
    st.configure("J.TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=GOLD, bordercolor=LINE, lightcolor=LINE,
                 darkcolor=LINE)
    st.configure("J.TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG, arrowcolor=GOLD,
                 bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    st.map("J.TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)])
    st.configure("J.Horizontal.TScale", background=ACC, troughcolor=FIELD, bordercolor=LINE, lightcolor=ACC, darkcolor=ACC)
    st.configure("J.TButton", background=FIELD, foreground=FG, bordercolor=LINE, lightcolor=FIELD, darkcolor=FIELD,
                 padding=(14, 6), font=("Segoe UI", 10))
    st.map("J.TButton", background=[("active", "#0d3a52")], bordercolor=[("active", ACC)])
    st.configure("Go.TButton", background="#3a2a0c", foreground=GOLD, bordercolor=GOLD, lightcolor="#3a2a0c",
                 darkcolor="#3a2a0c", padding=(20, 6), font=("Segoe UI Semibold", 10))
    st.map("Go.TButton", background=[("active", "#4d3810")])
    st.configure("J.TNotebook", background=BG, borderwidth=0)
    st.configure("J.TNotebook.Tab", background=FIELD, foreground=FG, padding=(14, 6), borderwidth=0)
    st.map("J.TNotebook.Tab", background=[("selected", "#0a5675")], foreground=[("selected", "white")])
    top.option_add("*TCombobox*Listbox.background", FIELD)
    top.option_add("*TCombobox*Listbox.foreground", FG)
    top.option_add("*TCombobox*Listbox.selectBackground", "#0d3a52")
    top.option_add("*TCombobox*Listbox.selectForeground", GOLD)


class ButtonsDialog:
    """Die neun Schnellstart-Knöpfe des HUD bearbeiten."""

    def __init__(self, parent, current, on_save):
        self.on_save = on_save
        self.top = tk.Toplevel(parent)
        self.top.title("Schnellstart-Knöpfe")
        self.top.configure(bg=BG)
        self.top.resizable(False, False)
        apply_style(self.top)
        frm = ttk.Frame(self.top, padding=16, style="J.TFrame")
        frm.pack()
        for col, title in enumerate(("Symbol", "Beschriftung", "Befehl (so, wie du ihn sagen würdest)")):
            ttk.Label(frm, text=title, style="J.TLabel").grid(row=0, column=col, sticky="w", padx=4, pady=(0, 6))
        self.rows = []
        items = list(current or pc_settings.DEFAULT_BUTTONS) + [("", "", "")] * 9
        for i in range(9):
            g, l, c = (list(items[i]) + ["", "", ""])[:3]
            vars_ = [tk.StringVar(value=g), tk.StringVar(value=l), tk.StringVar(value=c)]
            for col, (v, w) in enumerate(zip(vars_, (5, 16, 38))):
                ttk.Entry(frm, textvariable=v, width=w, style="J.TEntry").grid(row=i + 1, column=col, padx=4, pady=3)
            self.rows.append(vars_)
        ttk.Label(frm, text="Beispiele: öffne discord · musik · pause · eins weiter · komplett stummschalten · "
                            "fahr den pc herunter · youtube lofi beats · öffne downloads",
                  style="Hint.TLabel", wraplength=560).grid(row=10, column=0, columnspan=3, sticky="w", pady=(10, 0))
        bar = ttk.Frame(frm, style="J.TFrame")
        bar.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        ttk.Button(bar, text="Standard", style="J.TButton", command=self._default).pack(side="left")
        ttk.Button(bar, text="Speichern", style="Go.TButton", command=self._save).pack(side="right")
        ttk.Button(bar, text="Abbrechen", style="J.TButton", command=self.top.destroy).pack(side="right", padx=8)

    def _default(self):
        for vars_, (g, l, c) in zip(self.rows, list(pc_settings.DEFAULT_BUTTONS) + [("", "", "")] * 9):
            vars_[0].set(g), vars_[1].set(l), vars_[2].set(c)

    def _save(self):
        out = []
        for g, l, c in self.rows:
            label, cmd = l.get().strip(), c.get().strip()
            if label and cmd:
                out.append([g.get().strip() or label[:1].upper(), label, cmd])
        self.top.destroy()
        self.on_save(out or None)


class SettingsDialog:
    """Einstellungen im Handy-Stil, direkt im HUD (kein eigenes Fenster): erst eine Liste der Bereiche mit Symbol,
    ein Klick öffnet den Bereich, „‹“ führt zurück. Neue Einstellungen tragen beim ersten Mal einen roten Punkt."""

    def __init__(self, parent, settings: dict, on_save, on_seen=None, on_globe=None):
        self.settings, self.on_save, self.on_seen, self.on_globe = dict(settings), on_save, on_seen, on_globe
        self.seen = list(settings.get("seen_new") or [])
        self.buttons = settings.get("hud_buttons")
        self.parent = parent
        k = max(1.0, parent.winfo_fpixels("1i") / 96.0)
        pw, ph = max(300, parent.winfo_width()), max(300, parent.winfo_height())
        width = int(min(pw - 16, max(pw * 0.44, 470 * k)))
        self.top = tk.Frame(parent, bg=BG, highlightthickness=1, highlightbackground=LINE, bd=0)
        self.top.place(relx=0.5, rely=0.5, anchor="center", width=width, height=int(ph * 0.94))
        apply_style(self.top)
        self.wrap = max(260, width - int(70 * k))
        self.k = k

        self.devices = device_choices("input")
        self.out_devices = device_choices("output")
        self.win_voices = [AUTO_WINDOWS] + pc_audio.windows_voices()

        accent = tk.Frame(self.top, bg=BG, height=3)  # Leuchtstreifen oben wie bei den HUD-Karten
        accent.pack(fill="x")
        tk.Frame(accent, bg=ACC, height=3, width=int(70 * k)).place(x=int(16 * k), y=0)
        # Kopfzeile: zurück, Titel, schließen
        head = tk.Frame(self.top, bg=BG)
        head.pack(fill="x", padx=int(10 * k), pady=(int(10 * k), int(4 * k)))
        self.back = tk.Label(head, text="‹", bg=BG, fg=GOLD, font=("Segoe UI", 20), cursor="hand2")
        self.back.bind("<Button-1>", lambda e: self._show_page(None))
        self.title = tk.Label(head, text="EINSTELLUNGEN", bg=BG, fg=ACC, font=("Segoe UI Semibold", 13))
        self.title.pack(side="left", padx=(int(6 * k), 0))
        close = tk.Label(head, text="✕", bg=BG, fg=DIM, font=("Segoe UI Symbol", 13), cursor="hand2")
        close.pack(side="right", padx=int(6 * k))
        close.bind("<Button-1>", lambda e: self.top.destroy())
        close.bind("<Enter>", lambda e: close.config(fg=GOLD))
        close.bind("<Leave>", lambda e: close.config(fg=DIM))
        tk.Frame(self.top, bg=LINE, height=1).pack(fill="x")

        # Fußzeile
        bar = tk.Frame(self.top, bg=BG)
        bar.pack(side="bottom", fill="x", padx=int(12 * k), pady=int(10 * k))
        ttk.Button(bar, text="Standard", style="J.TButton", command=lambda: self._load(pc_settings.DEFAULTS)).pack(side="left")
        ttk.Button(bar, text="Speichern", style="Go.TButton", command=self._save).pack(side="right")
        ttk.Button(bar, text="Abbrechen", style="J.TButton", command=self.top.destroy).pack(side="right", padx=8)
        tk.Frame(self.top, bg=LINE, height=1).pack(side="bottom", fill="x")

        # Scrollbarer Inhalt
        body = tk.Frame(self.top, bg=BG)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.thumb = tk.Canvas(body, bg=BG, width=max(4, int(5 * k)), highlightthickness=0, bd=0)
        self.thumb.pack(side="right", fill="y")
        self.holder = tk.Frame(self.canvas, bg=BG)
        self._win = self.canvas.create_window(0, 0, anchor="nw", window=self.holder)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.holder.bind("<Configure>", lambda e: self._update_scroll())
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.top.bind_all("<MouseWheel>", self._wheel, add="+")

        self.pages: dict = {}  # Titel -> Frame
        self.order: list = []
        self.page_items: dict = {}  # Titel -> neue Einstellungen in diesem Bereich
        self.current = None
        self.frm, self.row = None, 0
        self._build()
        self._load(self.settings)
        self._build_list()
        self._show_page(None)

    # --- Navigation ---
    def _build_list(self):
        k = self.k
        page = tk.Frame(self.holder, bg=BG)
        self.list_page = page
        self.row_dots = {}
        for title in self.order:
            if title in HIDDEN_SECTIONS:
                continue
            icon, sub = SECTIONS.get(title, ("•", ""))
            row = tk.Frame(page, bg=BG, cursor="hand2")
            row.pack(fill="x", padx=int(12 * k), pady=(int(6 * k), 0))
            ic = tk.Canvas(row, width=int(40 * k), height=int(40 * k), bg=BG, highlightthickness=0, bd=0)
            ic.create_oval(2, 2, int(38 * k), int(38 * k), fill="#03101a", outline=LINE, width=2)
            ic.create_text(int(20 * k), int(20 * k), text=icon, fill=GOLD, font=("Segoe UI Symbol", 14))
            ic.pack(side="left", pady=int(6 * k))
            txt = tk.Frame(row, bg=BG)
            txt.pack(side="left", fill="x", expand=True, padx=(int(12 * k), 0))
            name = tk.Label(txt, text=title, bg=BG, fg=FG, font=("Segoe UI Semibold", 11), anchor="w")
            name.pack(fill="x")
            subl = tk.Label(txt, text=sub, bg=BG, fg=DIM, font=("Segoe UI", 9), anchor="w")
            subl.pack(fill="x")
            chev = tk.Label(row, text="›", bg=BG, fg=DIM, font=("Segoe UI", 16))
            chev.pack(side="right", padx=(0, int(4 * k)))
            dot = tk.Label(row, text="●", bg=BG, fg=NEW_DOT, font=("Segoe UI", 9))
            self.row_dots[title] = dot
            if self._unseen_in(title):
                dot.pack(side="right", padx=int(6 * k))
            tk.Frame(page, bg="#0b2636", height=1).pack(fill="x", padx=(int(64 * k), int(12 * k)), pady=(int(6 * k), 0))
            widgets = (row, ic, txt, name, subl, chev, dot)
            for w in widgets:
                w.bind("<Button-1>", lambda e, t=title: self._show_page(t))
                w.bind("<Enter>", lambda e, ws=widgets: [x.config(bg=HOVER) for x in ws if not isinstance(x, tk.Canvas)])
                w.bind("<Leave>", lambda e, ws=widgets: [x.config(bg=BG) for x in ws if not isinstance(x, tk.Canvas)])

    def _show_page(self, title):
        for f in list(self.pages.values()) + [getattr(self, "list_page", None)]:
            if f is not None:
                f.pack_forget()
        if title is None:
            self.current = None
            self.title.config(text="EINSTELLUNGEN")
            self.back.pack_forget()
            for t, dot in getattr(self, "row_dots", {}).items():
                if self._unseen_in(t):
                    dot.pack(side="right", padx=int(6 * self.k))
                else:
                    dot.pack_forget()
            self.list_page.pack(fill="x")
        else:
            self.current = title
            self.title.config(text=title.upper())
            self.back.pack(side="left", before=self.title)
            self.pages[title].pack(fill="both", expand=True, padx=int(16 * self.k), pady=int(10 * self.k))
            new = self._unseen_in(title)
            if new:  # einmal angeschaut: Punkte verschwinden beim nächsten Mal
                self.seen += new
                if self.on_seen:
                    try:
                        self.on_seen(list(self.seen))
                    except Exception:
                        pass
        self.canvas.yview_moveto(0)
        self.top.after(30, self._update_scroll)

    def _unseen_in(self, title) -> list:
        return [i for i in NEW_ITEMS.get(title, []) if i not in self.seen]

    def _update_scroll(self):
        try:
            self.canvas.configure(scrollregion=(0, 0, self.holder.winfo_reqwidth(), self.holder.winfo_reqheight()))
            self._on_scroll(*self.canvas.yview())
        except Exception:
            pass

    def _on_scroll(self, first, last):
        t = self.thumb
        t.delete("all")
        f, l = float(first), float(last)
        if l - f < 0.999:
            h = t.winfo_height()
            t.create_line(2, f * h + 2, 2, l * h - 2, fill=ACC, width=3, capstyle="round")

    def contains(self, x, y) -> bool:
        try:
            x0, y0 = self.top.winfo_rootx(), self.top.winfo_rooty()
            return x0 <= x <= x0 + self.top.winfo_width() and y0 <= y <= y0 + self.top.winfo_height()
        except Exception:
            return False

    def _wheel(self, e):
        if not self.exists() or not self.contains(e.x_root, e.y_root):
            return
        try:
            if isinstance(e.widget, ttk.Combobox):  # Auswahllisten nicht aus Versehen verstellen
                return "break"
        except Exception:
            pass
        self.canvas.yview_scroll(int(-e.delta / 120) * 3, "units")

    # --- Bausteine ---
    def _tab(self, title):
        f = tk.Frame(self.holder, bg=BG)
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)
        self.pages[title] = f
        self.order.append(title)
        self.frm, self.row = f, 0
        self._tab_title = title

    def _is_new(self, label) -> bool:
        return label in NEW_ITEMS.get(getattr(self, "_tab_title", ""), []) and label not in self.seen

    def _label(self, label):
        box = tk.Frame(self.frm, bg=BG)
        tk.Label(box, text=label, bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left")
        if self._is_new(label):
            tk.Label(box, text="  ● NEU", bg=BG, fg=NEW_DOT, font=("Segoe UI", 8, "bold")).pack(side="left")
        return box

    def _field(self, label, factory, hint=None):
        self._label(label).grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(10, 3))
        self.row += 1
        widget = factory(self.frm)
        widget.grid(row=self.row, column=0, columnspan=2, sticky="ew")
        self.row += 1
        if hint:
            ttk.Label(self.frm, text=hint, style="Hint.TLabel", wraplength=self.wrap, justify="left").grid(
                row=self.row, column=0, columnspan=2, sticky="w", pady=(3, 0))
            self.row += 1

    def _combo(self, label, var, values, hint=None):
        self._field(label, lambda p: ttk.Combobox(p, textvariable=var, state="readonly", values=values,
                                                  style="J.TCombobox"), hint)

    def _entry(self, label, var, hint=None):
        self._field(label, lambda p: ttk.Entry(p, textvariable=var, style="J.TEntry"), hint)

    def _check(self, label, var):
        box = tk.Frame(self.frm, bg=BG)
        ttk.Checkbutton(box, text=label, variable=var, style="J.TCheckbutton").pack(side="left")
        if self._is_new(label):
            tk.Label(box, text="  ● NEU", bg=BG, fg=NEW_DOT, font=("Segoe UI", 8, "bold")).pack(side="left", anchor="n")
        box.grid(row=self.row, column=0, columnspan=2, sticky="w", pady=5)
        self.row += 1

    def _scale(self, label, var, lo, hi, unit="", hint=None):
        def factory(parent):
            box = ttk.Frame(parent, style="J.TFrame")
            value = ttk.Label(box, text="", style="J.TLabel", width=8, anchor="e")
            ttk.Scale(box, from_=lo, to=hi, variable=var, style="J.Horizontal.TScale").pack(side="left", fill="x", expand=True)
            value.pack(side="left", padx=(8, 0))
            var.trace_add("write", lambda *a: value.config(text=f"{int(float(var.get()))}{unit}"))
            return box
        self._field(label, factory, hint)

    def _button(self, text, command):
        ttk.Button(self.frm, text=text, style="J.TButton", command=command).grid(
            row=self.row, column=0, columnspan=2, sticky="w", pady=(10, 4))
        self.row += 1

    # --- Aufbau ---
    def _build(self):
        self.v_wake, self.v_lang, self.v_dev, self.v_out = (tk.StringVar() for _ in range(4))
        self.v_follow, self.v_rate, self.v_vol, self.v_pitch = (tk.DoubleVar() for _ in range(4))
        self.v_vvol = tk.DoubleVar()
        self.v_orb, self.v_alpha = tk.DoubleVar(), tk.DoubleVar()
        self.v_engine, self.v_edge, self.v_winvoice = (tk.StringVar() for _ in range(3))
        self.v_style, self.v_corner, self.v_theme = (tk.StringVar() for _ in range(3))
        self.v_city, self.v_name, self.v_addr = (tk.StringVar() for _ in range(3))
        self.v_key, self.v_model = tk.StringVar(), tk.StringVar()
        self.v_groq = tk.StringVar()
        self.groq_status = None
        self.v_el_key, self.v_el_voice, self.v_el_model = (tk.StringVar() for _ in range(3))
        self._el_voices = list(pc_eleven.DEFAULT_VOICES)
        self.v_brief, self.v_gauto, self.v_gfull, self.v_borderless = (tk.BooleanVar() for _ in range(4))
        self.v_gtheme, self.v_gstyle = tk.StringVar(), tk.StringVar()
        self.v_mstyle, self.v_home, self.v_hmode, self.v_sphere = (tk.StringVar() for _ in range(4))
        self.v_places, self.v_persona = tk.StringVar(), tk.StringVar()
        self.v_sattour = tk.BooleanVar()
        self.v_spin, self.v_flplaces = tk.BooleanVar(), tk.StringVar()
        self.v_dchan = tk.StringVar()
        self.v_homeaddr, self.v_ntfy, self.v_loc = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.v_pchan, self.v_mynum, self.v_tg = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.v_mlabels = tk.BooleanVar()
        self.v_themen, self.v_orbits = tk.StringVar(), tk.BooleanVar()
        self.v_hstyle = tk.StringVar()
        self.ai_status = None
        (self.v_speak, self.v_early, self.v_anim, self.v_start, self.v_top, self.v_weather, self.v_notes,
         self.v_temps, self.v_greet, self.v_perf, self.v_confirm, self.v_auto) = (tk.BooleanVar() for _ in range(12))
        self.v_cal = tk.StringVar()
        self.v_tt_on = tk.BooleanVar()
        self.v_tt_mail, self.v_tt_pw, self.v_tt_code = (tk.StringVar() for _ in range(3))
        self.tt_status = None
        self.v_ann, self.v_gc_on = tk.BooleanVar(), tk.BooleanVar()
        self.v_gc_id, self.v_gc_secret, self.v_gc_cal = (tk.StringVar() for _ in range(3))
        self.gc_status = None
        self.gc_combo = None
        self._gc_refresh = ""
        self._gc_cals = {}

        self._tab("Zuhören")
        self._check("Automatisch mit Windows starten (leise im Hintergrund)", self.v_auto)
        self._entry("Aktivierungswort", self.v_wake, "Mehrere Schreibweisen mit Komma trennen, z. B. jarvis, dscharvis")
        self._combo("Sprache", self.v_lang, [n for n, _ in LANGUAGES])
        self._combo("Mikrofon", self.v_dev, [n for n, _ in self.devices], "Wirkt sofort nach dem Speichern.")
        self._scale("Weiterhören nach einem Befehl", self.v_follow, 0, 15, " s",
                    "So lange kannst du ohne Aktivierungswort weitersprechen (0 = aus).")

        self._tab("Stimme")
        self._check("Antworten laut sprechen", self.v_speak)
        self._combo("Ausgabe für Stimme und Wecksound", self.v_out, [n for n, _ in self.out_devices],
                    "Z. B. ein Kanal von Elgato Wave Link. Online-Stimmen brauchen dafür: pip install soundfile")
        self._combo("Stimmenart", self.v_engine, [n for n, _ in ENGINES],
                    "Klappt ElevenLabs mal nicht (kein Internet, Guthaben leer), nimmt er automatisch die Online-Stimme.")
        self._field("ElevenLabs-Schlüssel",
                    lambda p: ttk.Entry(p, textvariable=self.v_el_key, style="J.TEntry", show="•"),
                    "elevenlabs.io → Entwickler → API-Schlüssel. Wird mit Windows verschlüsselt gespeichert.")
        self.el_combo = None

        def voice_box(parent):
            self.el_combo = ttk.Combobox(parent, textvariable=self.v_el_voice, state="readonly",
                                         values=[n for n, _ in self._el_voices], style="J.TCombobox")
            return self.el_combo

        self._field("ElevenLabs-Stimme", voice_box, "„Stimmen laden“ holt alle Stimmen aus deinem ElevenLabs-Konto dazu.")
        self._combo("ElevenLabs-Modell", self.v_el_model, [n for n, _ in pc_eleven.MODELS])
        self._button("Stimmen laden", self._el_load)
        self.el_status = ttk.Label(self.frm, text="", style="Hint.TLabel", wraplength=440)
        self.el_status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1
        self._combo("Online-Stimme (Ersatz)", self.v_edge, [n for n, _ in pc_audio.EDGE_VOICES])
        self._combo("Windows-Stimme", self.v_winvoice, self.win_voices)
        self._scale("Tonhöhe", self.v_pitch, -10, 10)
        self._scale("Sprechtempo", self.v_rate, -10, 10)
        self._scale("Lautstärke von Jarvis' Stimme", self.v_vvol, 10, 100, "%",
                    "Eigene Lautstärke, unabhängig von Windows und Musik. Auch per Sprache: „sprich lauter“.")
        self._scale("Lautstärke Wecksound", self.v_vol, 0, 100, "%")
        self._check("Wecksound schon beim Weckwort (nicht erst am Satzende)", self.v_early)
        self._button("Stimme testen", self._test_voice)

        self._tab("Weltlage")
        ttk.Label(self.frm, text="Jarvis holt Nachrichten von tagesschau, Deutscher Welle, BBC und aus deiner Gegend und fasst "
                  "sie zusammen (mit Gemini-Schlüssel besonders gut). Sag „Jarvis, wie ist die Lage?“, „Was ist los in "
                  "Leonberg?“, „Was fliegt gerade über uns?“ oder „Wie ist die Lage in Deutschland?“. Die Karte öffnest du "
                  "auch mit dem Knopf „Lage“ oben im HUD. Ziehen = verschieben, Mausrad = zoomen, Klick auf einen Punkt = Details.",
                  style="Hint.TLabel", wraplength=self.wrap, justify="left").grid(
            row=self.row, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.row += 1
        self._entry("Standort", self.v_home, "Mitte der Karte und Ort für lokale Nachrichten, z. B. Leonberg.")
        self._entry("Lieblingsorte", self.v_places,
                    "Mit Komma trennen, z. B. Seoul, New York, Hamburg. Stehen oben im Lage-Screen zum Anklicken. "
                    "Oder einfach fragen: „Wie ist die Lage in Tokio?“")
        try:
            import pc_themen
            gelernt = ", ".join(t.get("name", "") for t in pc_themen.learned()) or "noch nichts – frag Jarvis einfach Dinge"
        except Exception:
            gelernt = "–"
        self._entry("Eigene Themen (Für dich)", self.v_themen,
                    "Mit Komma trennen, z. B. Euro Truck Simulator, VfB Stuttgart, KI. Dazu lernt Jarvis von selbst "
                    f"(mit dem Handy zusammen). Gelernt bisher: {gelernt}")
        self._check("Beim Briefing ins Satellitenbild zoomen", self.v_sattour)
        self._check("Erde langsam drehen (mit echtem Tag und Nacht)", self.v_spin)
        self._check("Echte Satelliten um die Erde (ISS, Hubble …)", self.v_orbits)
        self._entry("Flugverkehr: eigene Orte", self.v_flplaces,
                    "Zusätzliche Knöpfe im Flug-Modus, mit Komma getrennt, z. B. Stuttgart, London, Seoul.")
        self._check("Beim Start ein kurzes Lage-Briefing sprechen", self.v_brief)
        self._check("Bei „Wie ist die Lage?“ die Karte öffnen", self.v_gauto)
        self._check("Karte im Vollbild öffnen", self.v_gfull)
        self._combo("Kartenstil", self.v_mstyle, MAP_STYLES,
                    "Satellit = echte Bilder wie Google Earth (bis auf Straßenebene). Dunkel = schlichte Karte in deiner Farbe.")
        self._check("Ortsnamen auf der Karte", self.v_mlabels)
        self._combo("Farben der Karte", self.v_gtheme, GLOBE_THEMES,
                    "Farbe von Punkten, Schrift und dunkler Karte. In der Karte wechselst du sie auch mit ◐.")
        self._button("Karte jetzt öffnen", lambda: self.on_globe and self.on_globe())

        self._tab("Anzeige")
        self._combo("Stil des HUD", self.v_hstyle, [n for n, _ in HUD_STYLES],
                    "Neu = läuft in einem Edge-Fenster, flüssig über die Grafikkarte, gleiches Aussehen wie die Handy-App. "
                    "Wirkt nach einem Neustart von Jarvis.")
        self._combo("Modus des HUD", self.v_hmode, [n for n, _ in HUD_MODES],
                    "Umschalten geht auch unten rechts im HUD oder per Sprache: „Fokus-Modus“ / „Info-Modus“.")
        self._combo("Farbe der Kugel", self.v_sphere, SPHERE_COLORS,
                    "Nach einem Farbwechsel rechnet Jarvis die Kugel einmal neu (ca. 10 bis 30 Sekunden).")
        self._combo("Farbe", self.v_theme, list(pc_settings.THEMES))
        self._combo("Anzeige beim Weckwort", self.v_style, [n for n, _ in STYLES])
        self._scale("Größe des kleinen Kreises", self.v_orb, 40, 120, " px")
        self._combo("Ecke des kleinen Kreises", self.v_corner, pc_settings.CORNERS)
        self._scale("Durchsichtigkeit des HUD", self.v_alpha, 40, 100, " %", "100 % = ganz undurchsichtig.")
        self._check("Animationen im HUD (aus = ruhiger und sparsamer)", self.v_anim)
        self._check("HUD beim Start öffnen", self.v_start)
        self._check("HUD immer im Vordergrund", self.v_top)

        self._tab("Knöpfe")
        self._label("Schnellstart-Knöpfe").grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.row += 1
        ttk.Label(self.frm, text="Bis zu 12 Knöpfe oben im HUD. Symbol (ein Zeichen), Name und Befehl, also das, was du "
                  "sonst zu Jarvis sagen würdest, z. B. „öffne discord“, „musik“, „wie ist die lage“. Leere Zeilen werden "
                  "nicht angezeigt.", style="Hint.TLabel", wraplength=self.wrap, justify="left").grid(
            row=self.row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.row += 1
        self.v_buttons = []
        grid = tk.Frame(self.frm, bg=BG)
        grid.grid(row=self.row, column=0, columnspan=2, sticky="ew")
        grid.columnconfigure(2, weight=2)
        grid.columnconfigure(1, weight=1)
        self.row += 1
        for col, head in enumerate(("", "Name", "Befehl")):
            tk.Label(grid, text=head, bg=BG, fg=DIM, font=("Segoe UI", 9)).grid(row=0, column=col, sticky="w")
        for i in range(BUTTON_SLOTS):
            vs = (tk.StringVar(), tk.StringVar(), tk.StringVar())
            ttk.Entry(grid, textvariable=vs[0], width=3, style="J.TEntry", justify="center").grid(
                row=i + 1, column=0, padx=(0, 6), pady=2)
            ttk.Entry(grid, textvariable=vs[1], width=12, style="J.TEntry").grid(row=i + 1, column=1, sticky="ew", padx=(0, 6), pady=2)
            ttk.Entry(grid, textvariable=vs[2], style="J.TEntry").grid(row=i + 1, column=2, sticky="ew", pady=2)
            self.v_buttons.append(vs)
        ttk.Label(self.frm, text="Symbole zum Kopieren: ♪ ▶ ⏸ « » ◍ ☀ ✉ ☎ ⚙ ★ ♥ ⌂ ✎ ☾ ⏻ D S C W",
                  style="Hint.TLabel", wraplength=self.wrap).grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.row += 1

        self._tab("Infos")
        self._check("Wetter anzeigen", self.v_weather)
        self._entry("Ort für das Wetter", self.v_city, "Auch ohne Einstellung geht: „Wie wird das Wetter in Berlin?“")
        self._field("Kalender-Adresse", lambda p: ttk.Entry(p, textvariable=self.v_cal, style="J.TEntry", show="•"),
                    "Google Kalender: Einstellungen deines Kalenders, ganz unten „Privatadresse im iCal-Format“ kopieren und hier einfügen. "
                    "Statt einer Adresse geht auch der Pfad einer .ics-Datei; mehrere mit Semikolon trennen. Wer die Adresse kennt, kann den Kalender lesen. Termine anlegen öffnet nur Google Kalender zum Speichern.")
        self._button("Kalender testen", self._test_cal)
        self.cal_status = ttk.Label(self.frm, text="", style="Hint.TLabel", wraplength=440)
        self.cal_status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1
        ttk.Separator(self.frm).grid(row=self.row, column=0, columnspan=2, sticky="ew", pady=10)
        self.row += 1
        self._check("TimeTree-Termine mitlesen (inoffiziell, über das Community-Tool timetree-exporter)", self.v_tt_on)
        self._entry("TimeTree-E-Mail", self.v_tt_mail)
        self._field("TimeTree-Passwort", lambda p: ttk.Entry(p, textvariable=self.v_tt_pw, style="J.TEntry", show="•"),
                    "Wird mit Windows verschlüsselt gespeichert und nur an TimeTree gesendet. TimeTree kann das Tool jederzeit blockieren.")
        self._entry("Kalender-Code (optional)", self.v_tt_code,
                    "Nur nötig, wenn du mehrere TimeTree-Kalender hast. Er steht in der Adresse der Kalenderseite auf timetreeapp.com.")
        self._button("1. TimeTree einrichten (installiert das Tool)", self._tt_install)
        self._button("2. Jetzt synchronisieren", self._tt_sync)
        self.tt_status = ttk.Label(self.frm, text="", style="Hint.TLabel", wraplength=440)
        self.tt_status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1
        self._check("Beim Start die Termine von heute ansagen", self.v_ann)
        self._check("Benachrichtigungen anzeigen (liest den Windows-Verlauf nur lokal)", self.v_notes)
        self._check("Leistung anzeigen (CPU, RAM, GPU, Datenträger, Netzwerk wie im Task-Manager)", self.v_perf)
        self._check("PC-Temperaturen anzeigen (wenn Windows sie freigibt)", self.v_temps)

        self._tab("KI")
        ttk.Label(self.frm, text="Mit einem Gemini-Schlüssel versteht Jarvis freie Sätze und kann sich unterhalten. "
                  "Den Schlüssel gibt es kostenlos auf aistudio.google.com/apikey.",
                  style="Hint.TLabel", wraplength=440).grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.row += 1
        self._field("Gemini-Schlüssel", lambda p: ttk.Entry(p, textvariable=self.v_key, style="J.TEntry", show="•"),
                    "Wird nur in der Datei einstellungen.json auf diesem PC gespeichert. Nie in Chats oder Mails weitergeben.")
        self._field("Modell", lambda p: ttk.Combobox(p, textvariable=self.v_model, values=["Automatisch"],
                                                     style="J.TCombobox"),
                    "Automatisch ist richtig. Jarvis sucht sich selbst ein schnelles, aktuelles Modell.")
        self._button("Verbindung testen", self._test_ai)
        self.ai_status = ttk.Label(self.frm, text="", style="Hint.TLabel", wraplength=440)
        self.ai_status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1
        self._field("Groq-Schlüssel (kostenloser Ersatz)",
                    lambda p: ttk.Entry(p, textvariable=self.v_groq, style="J.TEntry", show="•"),
                    "Kostenlos und ohne Bankkarte auf console.groq.com → API Keys. Ist Gemini aufgebraucht oder nicht "
                    "erreichbar, antwortet Jarvis automatisch über Groq. Hast du keinen Gemini-Schlüssel, nimmt er nur Groq.")
        self._button("Groq testen", self._test_groq)
        self.groq_status = ttk.Label(self.frm, text="", style="Hint.TLabel", wraplength=440)
        self.groq_status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1
        ttk.Label(self.frm, text="Hinweis: Was du frei sagst, wird zur Beantwortung an Google geschickt. "
                  "Im kostenlosen Kontingent können Eingaben laut Google zur Produktverbesserung genutzt werden "
                  "(in der EU/Deutschland gelten die Bedingungen für bezahlte Dienste, bitte bei Google nachlesen). "
                  "Sag deshalb keine Passwörter oder Privates.",
                  style="Hint.TLabel", wraplength=440).grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.row += 1

        self._tab("Meine Daten")
        ttk.Label(self.frm, text="Damit kann Jarvis sie auf Zuruf in Formulare tippen: „Trag bitte meine E-Mail ein“. "
                  "Die Daten bleiben nur auf diesem PC (gedaechtnis.json). Passwörter gehören hier nicht hinein.",
                  style="Hint.TLabel", wraplength=440).grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.row += 1
        self.v_profile = {}
        for key, label in pc_memory.PROFILE_FIELDS:
            self.v_profile[key] = tk.StringVar(value=pc_memory.profile(key))
            self._entry(label, self.v_profile[key])

        self._tab("Google eintragen")
        ttk.Label(self.frm, text="Hiermit trägt Jarvis die TimeTree-Termine in einen Google-Kalender ein (gleicher Tag, gleiche Uhrzeit). "
                  "Einmal einrichten:\n"
                  "1. console.cloud.google.com öffnen, neues Projekt anlegen.\n"
                  "2. „APIs und Dienste“ > „Bibliothek“: „Google Calendar API“ aktivieren.\n"
                  "3. „OAuth-Zustimmungsbildschirm“: extern, Name z. B. Jarvis, deine E-Mail als Testnutzer. Danach „App veröffentlichen“, "
                  "sonst läuft die Anmeldung nach 7 Tagen ab.\n"
                  "4. „Anmeldedaten“ > „OAuth-Client-ID“ > Typ „Desktop-App“. Client-ID und Client-Secret hier einfügen.",
                  style="Hint.TLabel", wraplength=470, justify="left").grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.row += 1
        self._entry("Client-ID", self.v_gc_id)
        self._field("Client-Secret", lambda p: ttk.Entry(p, textvariable=self.v_gc_secret, style="J.TEntry", show="•"),
                    "Wird mit Windows verschlüsselt gespeichert.")
        self._button("Bei Google anmelden (öffnet den Browser)", self._gc_login)
        def _mk_combo(p):
            self.gc_combo = ttk.Combobox(p, textvariable=self.v_gc_cal, state="readonly", values=[], style="J.TCombobox")
            return self.gc_combo
        self._field("Ziel-Kalender", _mk_combo, "Erscheint nach der Anmeldung. Am besten ein eigener Kalender nur für TimeTree-Termine.")
        self._button("Kalender-Liste laden", self._gc_load)
        self._check("TimeTree-Termine in diesen Google-Kalender eintragen (beim Start und alle paar Stunden)", self.v_gc_on)
        self._button("Jetzt abgleichen", self._gc_sync)
        self.gc_status = ttk.Label(self.frm, text="", style="Hint.TLabel", wraplength=470)
        self.gc_status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1

        self._tab("Persönlichkeit")
        self._entry("Name des Assistenten", self.v_name, "Steht im HUD und so stellt er sich vor.")
        self._entry("Anrede", self.v_addr, "Wie er dich anspricht, z. B. Sir oder dein Name. Leer = keine Anrede.")
        self._combo("Art", self.v_persona, [n for n, _ in PERSONAS],
                    "Wie er redet. Er merkt sich, was du ihm erzählst und wie du drauf bist, und nutzt es später.")
        self._check("Beim Start kurz begrüßen", self.v_greet)
        self._check("Nachrichten (WhatsApp, Discord) vor dem Senden zurückfragen", self.v_confirm)
        self._entry("Discord-Sprachkanäle", self.v_dchan,
                    "Genaue Namen mit Komma getrennt, auch mit Emoji, z. B. 🥒|Gurken, 🥑|Avocado. Sagen musst du nur "
                    "das Wort („Gurken“, „geh in Avocado“). Namen kopierst du in Discord über Kanal bearbeiten.")
        self._button("Eigene Befehle bearbeiten (Programme, Ordner, Webseiten) …", self._open_custom)

        self._tab("Handy-App")
        import pc_link
        ttk.Label(self.frm, text="Damit Jarvis auf dem Handy dasselbe über dich weiß wie hier (was du ihm erzählt hast, wie du "
                  "drauf bist, seine Art und Anrede): In der Jarvis-App auf ⚙ tippen und bei „Kopplungscode vom PC“ diesen Code "
                  "eintragen. Was du dem Handy erzählst, landet dann auch hier.\n"
                  "Alles geht verschlüsselt über ntfy.sh. Den Code nicht weitergeben.",
                  style="Hint.TLabel", wraplength=self.wrap, justify="left").grid(
            row=self.row, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.row += 1
        self.v_link = tk.StringVar(value=pc_link.code())
        self._field("Kopplungscode", lambda p: ttk.Entry(p, textvariable=self.v_link, style="J.TEntry", state="readonly"))
        self._button("Code kopieren", self._copy_link)
        self._button("Neuen Code erzeugen (alte Kopplung endet)", self._new_link)
        self.link_status = ttk.Label(self.frm, text=pc_link.STATUS, style="Hint.TLabel", wraplength=440)
        self.link_status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1

        self._tab("Handy")
        ttk.Label(self.frm, text="Frag z. B. „Wie lange brauche ich mit dem Fahrrad nach Rutesheim?“. Jarvis nennt dir bis zu "
                  "drei Wege (schnellster, flachster, kürzester) und schickt dir den gewünschten aufs Handy.\n\n"
                  "Am einfachsten mit Telegram (Nachrichten UND Standort, keine zweite SIM nötig):\n"
                  "1. Telegram aufs Handy, dort @BotFather suchen, /newbot schreiben, einen Namen (z. B. Jarvis) und einen "
                  "Benutzernamen, der auf bot endet (z. B. skyler_jarvis_bot), eingeben.\n"
                  "2. BotFather schickt einen Schlüssel (lange Zeichenkette mit Doppelpunkt). Unten eintragen, „Telegram "
                  "testen“, Speichern.\n"
                  "3. Deinen neuen Bot in Telegram öffnen und auf START tippen. Er antwortet „Verbunden“.\n"
                  "4. Standort: im Chat mit dem Bot 📎 > Standort > Live-Standort teilen > bis ich es ausschalte.\n\n"
                  "Andere Wege: WhatsApp an dich selbst (funktioniert nicht mit jeder Nummer) oder ntfy/OwnTracks: Installiere „OwnTracks“, stelle unter Einstellungen den Modus auf HTTP und trage als "
                  "Adresse (URL) https://ntfy.sh/ und dahinter den Standort-Kanal ein. Standort-Freigabe „Immer“ erlauben.\n"
                  "Die Kanäle sind geheime Zufallsnamen – gib sie nicht weiter.",
                  style="Hint.TLabel", wraplength=self.wrap, justify="left").grid(
            row=self.row, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.row += 1
        self._entry("Meine Adresse", self.v_homeaddr, "Startpunkt für Routen, wenn das Handy gerade keinen Standort "
                    "schickt, z. B. Musterstraße 5, 71229 Leonberg.")
        self._combo("Aufs Handy schicken über", self.v_pchan, [n for n, _ in PHONE_CHANNELS])
        self._field("Telegram-Bot-Schlüssel",
                    lambda p: ttk.Entry(p, textvariable=self.v_tg, style="J.TEntry", show="•"),
                    "Von @BotFather in Telegram (sieht aus wie 1234567890:AAH…).")
        self._button("Telegram testen", self._test_telegram)
        self.tg_status = ttk.Label(self.frm, text="", style="Hint.TLabel", wraplength=440)
        self.tg_status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1
        self._entry("Meine WhatsApp-Nummer", self.v_mynum, "Nur für WhatsApp: deine eigene Nummer, z. B. 0170 1234567.")
        self._entry("Kanal für Nachrichten (ntfy)", self.v_ntfy, "Nur für die ntfy-App: dort abonnieren.")
        self._entry("Kanal für den Standort (OwnTracks)", self.v_loc, "In OwnTracks als URL: https://ntfy.sh/<dieser Kanal>")
        self._button("Test aufs Handy schicken", self._test_phone)
        self._button("Standort-Einrichtung (OwnTracks) aufs Handy schicken", self._send_owntracks)
        self.phone_status = ttk.Label(self.frm, text="", style="Hint.TLabel", wraplength=440)
        self.phone_status.grid(row=self.row, column=0, columnspan=2, sticky="w")
        self.row += 1

    def _copy_link(self):
        try:
            self.top.clipboard_clear()
            self.top.clipboard_append(self.v_link.get())
            _safe(self.link_status, "Kopiert.")
        except Exception:
            pass

    def _new_link(self):
        import pc_link
        self.v_link.set(pc_link.code(new=True))
        _safe(self.link_status, "Neuer Code. Trag ihn in der App ein.")
        threading.Thread(target=lambda: pc_link.publish(force=True), daemon=True).start()

    # --- Werte laden / lesen ---
    @staticmethod
    def _label_for(pairs, code, default_index=0):
        for name, c in pairs:
            if c == code:
                return name
        return pairs[default_index][0]

    def _load(self, s: dict):
        d = pc_settings.DEFAULTS
        g = lambda key: s.get(key, d[key])  # noqa: E731
        self.v_wake.set(", ".join(g("wake_words")))
        self.v_lang.set(self._label_for(LANGUAGES, g("language")))
        dev = g("input_device")
        self.v_dev.set(self._label_for(self.devices, pc_audio.device_name(dev) or None if isinstance(dev, int) else dev))
        out = g("output_device")
        self.v_out.set(self._label_for(self.out_devices, pc_audio.device_name(out) or None if isinstance(out, int) else out))
        self.v_follow.set(float(g("followup_seconds")))
        self.v_speak.set(bool(g("speak")))
        self.v_engine.set(self._label_for(ENGINES, g("voice_engine")))
        self.v_edge.set(self._label_for(list(pc_audio.EDGE_VOICES), g("edge_voice")))
        if s is not pc_settings.DEFAULTS:  # "Standard" soll den Schlüssel nicht löschen
            self.v_el_key.set(self.PW_MASK if s.get("eleven_key_enc") else "")
        vid, vname = g("eleven_voice"), g("eleven_voice_name")
        if vid and vid not in [v for _, v in self._el_voices]:
            self._el_voices.append((vname or vid, vid))
            if self.el_combo is not None:
                self.el_combo.configure(values=[n for n, _ in self._el_voices])
        self.v_el_voice.set(self._label_for(self._el_voices, vid))
        self.v_el_model.set(self._label_for(pc_eleven.MODELS, g("eleven_model")))
        self.v_brief.set(bool(g("briefing_on_start")))
        self.v_gauto.set(bool(g("globe_auto_open")))
        self.v_gfull.set(bool(g("globe_fullscreen")))
        self.v_gtheme.set(g("globe_theme") if g("globe_theme") in GLOBE_THEMES else "Glut")
        self.v_gstyle.set(g("globe_style") if g("globe_style") in ("Hologramm", "Satellit") else "Hologramm")
        self.v_mstyle.set(g("map_style") if g("map_style") in MAP_STYLES else "Satellit")
        self.v_mlabels.set(bool(g("map_labels")))
        self.v_home.set(str(g("home_city") or "Leonberg"))
        self.v_places.set(", ".join(g("lage_places") or []))
        self.v_homeaddr.set(str(g("home_address") or ""))
        self.v_ntfy.set(str(g("ntfy_topic") or ""))
        self.v_pchan.set(self._label_for(PHONE_CHANNELS, g("phone_channel")))
        self.v_mynum.set(str(g("my_number") or ""))
        self.v_tg.set(self.PW_MASK if g("telegram_token_enc") else "")
        self.v_loc.set(str(g("loc_topic") or ""))
        self.v_sattour.set(bool(g("lage_sat_tour")))
        self.v_spin.set(bool(s.get("lage_spin", True)))
        self.v_orbits.set(bool(s.get("lage_orbits", True)))
        self.v_themen.set(", ".join(s.get("themen_selbst") or []))
        self.v_flplaces.set(", ".join(s.get("flug_places") or []))
        self.v_dchan.set(", ".join(s.get("discord_channels") or pc_settings.DEFAULTS["discord_channels"]))
        self.v_persona.set(self._label_for(PERSONAS, g("persona")))
        self.v_hmode.set(self._label_for(HUD_MODES, g("hud_mode")))
        self.v_hstyle.set(self._label_for(HUD_STYLES, s.get("hud_style", "neu")))
        self.v_sphere.set(g("sphere_color") if g("sphere_color") in SPHERE_COLORS else "Gold")
        rows = g("hud_buttons")
        rows = [list(b) for b in (pc_settings.DEFAULT_BUTTONS if rows is None else rows)]
        for i, vs in enumerate(self.v_buttons):
            row = rows[i] if i < len(rows) else ["", "", ""]
            for v, val in zip(vs, (list(row) + ["", "", ""])[:3]):
                v.set(str(val or ""))
        self.v_borderless.set(bool(g("hud_borderless")))
        self.v_winvoice.set(g("windows_voice") if g("windows_voice") in self.win_voices else AUTO_WINDOWS)
        self.v_pitch.set(float(g("voice_pitch")))
        self.v_rate.set(float(g("voice_rate")))
        self.v_vol.set(float(g("chime_volume")))
        self.v_vvol.set(float(s.get("voice_volume", 100)))
        self.v_early.set(bool(g("early_chime")))
        self.v_theme.set(g("accent") if g("accent") in pc_settings.THEMES else "Cyan")
        self.v_style.set(self._label_for(STYLES, g("overlay_style")))
        self.v_orb.set(float(g("orb_size")))
        self.v_corner.set(g("orb_corner") if g("orb_corner") in pc_settings.CORNERS else pc_settings.CORNERS[0])
        self.v_alpha.set(float(g("hud_alpha")))
        self.v_anim.set(bool(g("hud_animation")))
        self.v_start.set(bool(g("show_hud_on_start")))
        self.v_top.set(bool(g("hud_topmost")))
        self.v_weather.set(bool(g("show_weather")))
        self.v_city.set(str(g("weather_city")))
        self.v_notes.set(bool(g("show_notifications")))
        self.v_temps.set(bool(g("show_pc_temps")))
        self.v_perf.set(bool(g("show_performance")))
        self.v_cal.set(str(s.get("calendar_url", "") or ""))
        self.v_ann.set(bool(g("announce_events")))
        if s is not pc_settings.DEFAULTS:
            self.v_gc_on.set(bool(s.get("gcal_enabled")))
            self.v_gc_id.set(str(s.get("gcal_client_id", "") or ""))
            self.v_gc_secret.set(self.PW_MASK if s.get("gcal_client_secret_enc") else "")
            self._gc_refresh = pc_secret.unprotect(s.get("gcal_refresh_enc", ""))
            self.v_gc_cal.set(str(s.get("gcal_calendar_name", "") or ""))
            if s.get("gcal_calendar_id"):
                self._gc_cals[str(s.get("gcal_calendar_name", ""))] = s["gcal_calendar_id"]
        if s is not pc_settings.DEFAULTS:
            self.v_tt_on.set(bool(s.get("timetree_enabled")))
            self.v_tt_mail.set(str(s.get("timetree_email", "") or ""))
            self.v_tt_code.set(str(s.get("timetree_code", "") or ""))
            self.v_tt_pw.set(self.PW_MASK if s.get("timetree_password_enc") else "")
        self.v_name.set(str(g("assistant_name")))
        self.v_addr.set(str(g("address_as")))
        self.v_greet.set(bool(g("greet_on_start")))
        self.v_confirm.set(bool(g("confirm_messages")))
        self.v_auto.set(bool(g("autostart")))
        self.buttons = g("hud_buttons")
        if s is not pc_settings.DEFAULTS:  # "Standard" soll den Schlüssel nicht löschen
            self.v_key.set(str(s.get("gemini_api_key", "") or ""))
            self.v_groq.set(self.PW_MASK if s.get("groq_key_enc") else "")
        model = str(g("gemini_model") or "auto")
        self.v_model.set("Automatisch" if model == "auto" else model)

    def _save(self):
        words = [w.strip().lower() for w in self.v_wake.get().split(",") if w.strip()]
        new = dict(self.settings)
        new.update(
            wake_words=words or list(pc_settings.DEFAULTS["wake_words"]),
            language=dict(LANGUAGES).get(self.v_lang.get(), "de-DE"),
            input_device=dict(self.devices).get(self.v_dev.get()),
            output_device=dict(self.out_devices).get(self.v_out.get()),
            followup_seconds=int(float(self.v_follow.get())),
            speak=bool(self.v_speak.get()),
            voice_engine=dict(ENGINES).get(self.v_engine.get(), "auto"),
            edge_voice=dict(pc_audio.EDGE_VOICES).get(self.v_edge.get(), "de-DE-KillianNeural"),
            windows_voice="" if self.v_winvoice.get() == AUTO_WINDOWS else self.v_winvoice.get(),
            voice_pitch=int(float(self.v_pitch.get())),
            voice_rate=int(float(self.v_rate.get())),
            chime_volume=int(float(self.v_vol.get())),
            voice_volume=int(float(self.v_vvol.get())),
            early_chime=bool(self.v_early.get()),
            accent=self.v_theme.get() if self.v_theme.get() in pc_settings.THEMES else "Cyan",
            overlay_style=dict(STYLES).get(self.v_style.get(), "klein"),
            orb_size=int(float(self.v_orb.get())),
            orb_corner=self.v_corner.get(),
            hud_alpha=int(float(self.v_alpha.get())),
            hud_animation=bool(self.v_anim.get()),
            show_hud_on_start=bool(self.v_start.get()),
            hud_topmost=bool(self.v_top.get()),
            show_weather=bool(self.v_weather.get()),
            weather_city=self.v_city.get().strip() or pc_settings.DEFAULTS["weather_city"],
            show_notifications=bool(self.v_notes.get()),
            show_pc_temps=bool(self.v_temps.get()),
            show_performance=bool(self.v_perf.get()),
            assistant_name=self.v_name.get().strip() or pc_settings.DEFAULTS["assistant_name"],
            address_as=self.v_addr.get().strip(),
            greet_on_start=bool(self.v_greet.get()),
            confirm_messages=bool(self.v_confirm.get()),
            autostart=bool(self.v_auto.get()),
            calendar_url=self.v_cal.get().strip(),
            announce_events=bool(self.v_ann.get()),
            gcal_enabled=bool(self.v_gc_on.get()),
            gcal_client_id=self.v_gc_id.get().strip(),
            gcal_client_secret_enc=(self.settings.get("gcal_client_secret_enc", "") if self.v_gc_secret.get() == self.PW_MASK
                                    else pc_secret.protect(self.v_gc_secret.get().strip())),
            gcal_refresh_enc=pc_secret.protect(self._gc_refresh),
            gcal_calendar_id=self._gc_cals.get(self.v_gc_cal.get(), ""),
            gcal_calendar_name=self.v_gc_cal.get(),
            timetree_enabled=bool(self.v_tt_on.get()),
            timetree_email=self.v_tt_mail.get().strip(),
            timetree_code=self.v_tt_code.get().strip(),
            timetree_password_enc=self._pw_token(),
            gemini_api_key=self.v_key.get().strip(),
            groq_key_enc=(self.settings.get("groq_key_enc", "") if self.v_groq.get() == self.PW_MASK
                          else pc_secret.protect(self.v_groq.get().strip())),
            gemini_model="auto" if self.v_model.get() in ("", "Automatisch") else self.v_model.get().strip(),
            eleven_key_enc=(self.settings.get("eleven_key_enc", "") if self.v_el_key.get() == self.PW_MASK
                            else pc_secret.protect(self.v_el_key.get().strip())),
            eleven_voice=dict(self._el_voices).get(self.v_el_voice.get(), pc_settings.DEFAULTS["eleven_voice"]),
            eleven_voice_name=self.v_el_voice.get(),
            eleven_model=dict(pc_eleven.MODELS).get(self.v_el_model.get(), pc_settings.DEFAULTS["eleven_model"]),
            briefing_on_start=bool(self.v_brief.get()),
            globe_auto_open=bool(self.v_gauto.get()),
            globe_fullscreen=bool(self.v_gfull.get()),
            globe_theme=self.v_gtheme.get() if self.v_gtheme.get() in GLOBE_THEMES else "Glut",
            globe_style=self.v_gstyle.get() if self.v_gstyle.get() in ("Hologramm", "Satellit") else "Hologramm",
            map_style=self.v_mstyle.get() if self.v_mstyle.get() in MAP_STYLES else "Satellit",
            map_labels=bool(self.v_mlabels.get()),
            home_city=self.v_home.get().strip() or "Leonberg",
            lage_places=[p.strip() for p in self.v_places.get().replace(";", ",").split(",") if p.strip()][:8],
            lage_sat_tour=bool(self.v_sattour.get()),
            lage_spin=bool(self.v_spin.get()),
            lage_orbits=bool(self.v_orbits.get()),
            themen_selbst=[p.strip() for p in self.v_themen.get().replace(";", ",").split(",") if p.strip()][:12],
            flug_places=[p.strip() for p in self.v_flplaces.get().replace(";", ",").split(",") if p.strip()][:6],
            discord_channels=[p.strip() for p in self.v_dchan.get().replace(";", ",").split(",") if p.strip()][:30],
            home_address=self.v_homeaddr.get().strip(),
            ntfy_topic=self.v_ntfy.get().strip() or self.settings.get("ntfy_topic", ""),
            phone_channel=dict(PHONE_CHANNELS).get(self.v_pchan.get(), "whatsapp"),
            my_number=self.v_mynum.get().strip(),
            telegram_chat=__import__("pc_telegram").CHAT_ID or self.settings.get("telegram_chat", ""),
            telegram_token_enc=(self.settings.get("telegram_token_enc", "") if self.v_tg.get() == self.PW_MASK
                                else pc_secret.protect(self.v_tg.get().strip())),
            loc_topic=self.v_loc.get().strip() or self.settings.get("loc_topic", ""),
            persona=dict(PERSONAS).get(self.v_persona.get(), "sarkastisch"),
            hud_mode=dict(HUD_MODES).get(self.v_hmode.get(), "info"),
            hud_style=dict(HUD_STYLES).get(self.v_hstyle.get(), "neu"),
            sphere_color=self.v_sphere.get() if self.v_sphere.get() in SPHERE_COLORS else "Gold",
            hud_buttons=[[g.get().strip() or n.get().strip()[:1].upper(), n.get().strip(), c.get().strip()]
                         for g, n, c in self.v_buttons if n.get().strip() and c.get().strip()],
            hud_borderless=bool(self.v_borderless.get()),
            seen_new=list(self.seen),
        )
        for key, var in self.v_profile.items():
            if var.get().strip() != pc_memory.profile(key):
                pc_memory.set_profile(key, var.get())
        self.top.destroy()
        self.on_save(new)

    # --- Knöpfe ---
    PW_MASK = "••••••••"

    def _pw_token(self) -> str:
        value = self.v_tt_pw.get()
        if value == self.PW_MASK:
            return self.settings.get("timetree_password_enc", "")
        return pc_secret.protect(value) if value else ""

    def _tt_password(self) -> str:
        value = self.v_tt_pw.get()
        if value == self.PW_MASK:
            return pc_secret.unprotect(self.settings.get("timetree_password_enc", ""))
        return value

    def _tt_show(self, text):
        try:
            self.top.after(0, lambda: _safe(self.tt_status, text))
        except Exception:
            pass

    def _tt_install(self):
        self.tt_status.config(text="Installiere … (das kann eine Minute dauern)")
        threading.Thread(target=lambda: self._tt_show(pc_timetree.install()), daemon=True).start()

    def _tt_sync(self):
        email, pw, code = self.v_tt_mail.get().strip(), self._tt_password(), self.v_tt_code.get().strip()
        self.tt_status.config(text="Hole Termine … (bis zu einer Minute)")

        def run():
            ok, msg = pc_timetree.sync(email, pw, code)
            self._tt_show(msg if ok else "✘ " + msg)

        threading.Thread(target=run, daemon=True).start()

    def _gc_secret(self) -> str:
        value = self.v_gc_secret.get()
        return pc_secret.unprotect(self.settings.get("gcal_client_secret_enc", "")) if value == self.PW_MASK else value.strip()

    def _gc_show(self, text):
        try:
            self.top.after(0, lambda: _safe(self.gc_status, text))
        except Exception:
            pass

    def _gc_apply_creds(self):
        pc_gcal.configure(pc_gcal.ENABLED, self.v_gc_id.get().strip(), self._gc_secret(), self._gc_refresh,
                          self._gc_cals.get(self.v_gc_cal.get(), ""))

    def _gc_login(self):
        cid, secret = self.v_gc_id.get().strip(), self._gc_secret()
        if not cid or not secret:
            self.gc_status.config(text="Trag zuerst Client-ID und Client-Secret ein.")
            return
        self.gc_status.config(text="Der Browser öffnet sich. Melde dich bei Google an und erlaube den Zugriff …")

        def run():
            try:
                self._gc_refresh = pc_gcal.login(cid, secret)
                self._gc_apply_creds()
                self._gc_show("✔ Angemeldet. Lade die Kalender …")
                self.top.after(0, self._gc_load)
            except Exception as e:
                self._gc_show(f"✘ {e}")

        threading.Thread(target=run, daemon=True).start()

    def _gc_load(self):
        if not self._gc_refresh:
            self.gc_status.config(text="Erst bei Google anmelden.")
            return
        self._gc_apply_creds()

        def run():
            try:
                cals = pc_gcal.list_calendars()
            except Exception as e:
                self._gc_show(f"✘ {e}")
                return

            def done():
                self._gc_cals = {name: cid for name, cid in cals}
                self.gc_combo.configure(values=list(self._gc_cals))
                if self.v_gc_cal.get() not in self._gc_cals and cals:
                    self.v_gc_cal.set(cals[0][0])
                self.gc_status.config(text=f"✔ {len(cals)} Kalender gefunden. Wähle den Ziel-Kalender und speichere.")
            try:
                self.top.after(0, done)
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    def _gc_sync(self):
        if not self._gc_cals.get(self.v_gc_cal.get()):
            self.gc_status.config(text="Wähle zuerst einen Ziel-Kalender.")
            return
        self._gc_apply_creds()
        self.gc_status.config(text="Gleiche ab … (das erste Mal kann eine Weile dauern)")

        def run():
            ok, msg = pc_gcal.sync_timetree()
            self._gc_show(("✔ " if ok else "✘ ") + msg)

        threading.Thread(target=run, daemon=True).start()

    def _test_cal(self):
        url = self.v_cal.get().strip()
        self.cal_status.config(text="Teste …")

        def run():
            msg = pc_calendar.test(url) if url else "Es ist noch keine Adresse eingetragen."
            try:
                self.top.after(0, lambda: _safe(self.cal_status, msg))
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    def _test_ai(self):
        key = self.v_key.get().strip()
        self.ai_status.config(text="Teste …")

        def show(text):
            try:
                self.top.after(0, lambda: _safe(self.ai_status, text))
            except Exception:
                pass

        def run():
            ok, msg, names = pc_ai.test(key)
            show(("✔ " if ok else "✘ ") + msg)
            if names:
                try:
                    self.top.after(0, lambda: self._set_models(names))
                except Exception:
                    pass

        threading.Thread(target=run, daemon=True).start()

    def _test_telegram(self):
        import pc_telegram

        value = self.v_tg.get()
        key = pc_secret.unprotect(self.settings.get("telegram_token_enc", "")) if value == self.PW_MASK else value.strip()
        if not key:
            self.tg_status.config(text="Trag zuerst den Schlüssel von @BotFather ein.")
            return
        self.tg_status.config(text="Teste …")

        def run():
            ok, msg = pc_telegram.check(key)
            self.top.after(0, lambda: _safe(self.tg_status, ("✔ " if ok else "✘ ") + msg + (
                " Danach Speichern nicht vergessen." if ok else "")))
        threading.Thread(target=run, daemon=True).start()

    def _send_owntracks(self):
        import pc_phone

        if not self.v_loc.get().strip():
            self.phone_status.config(text="Kein Standort-Kanal eingetragen.")
            return
        chan = dict(PHONE_CHANNELS).get(self.v_pchan.get(), "whatsapp")
        self.phone_status.config(text="Schicke die Anleitung …")

        def run():
            old = (pc_phone.PUSH_TOPIC, pc_phone.CHANNEL, pc_phone.MY_NUMBER, pc_phone.LOC_TOPIC)
            pc_phone.PUSH_TOPIC, pc_phone.CHANNEL = self.v_ntfy.get().strip(), chan
            pc_phone.MY_NUMBER, pc_phone.LOC_TOPIC = self.v_mynum.get().strip(), self.v_loc.get().strip()
            try:
                ok = pc_phone.send_setup()
            finally:
                pc_phone.PUSH_TOPIC, pc_phone.CHANNEL, pc_phone.MY_NUMBER, pc_phone.LOC_TOPIC = old
            self.top.after(0, lambda: _safe(self.phone_status, "✔ Anleitung ist auf deinem Handy." if ok else
                                            "✘ Ging nicht – stimmt die WhatsApp-Nummer?"))
        threading.Thread(target=run, daemon=True).start()

    def _test_phone(self):
        import pc_phone

        topic = self.v_ntfy.get().strip()
        chan = dict(PHONE_CHANNELS).get(self.v_pchan.get(), "whatsapp")
        if chan == "telegram":
            import pc_telegram

            if not pc_telegram.CHAT_ID:
                self.phone_status.config(text="Erst Schlüssel eintragen, Speichern, dann in Telegram beim Bot auf START.")
                return
        if chan == "whatsapp" and not self.v_mynum.get().strip():
            self.phone_status.config(text="Trag zuerst deine WhatsApp-Nummer ein.")
            return
        self.phone_status.config(text="Schicke … (WhatsApp kommt kurz nach vorn)" if chan == "whatsapp" else "Schicke …")

        def run():
            old = (pc_phone.PUSH_TOPIC, pc_phone.CHANNEL, pc_phone.MY_NUMBER)
            pc_phone.PUSH_TOPIC, pc_phone.CHANNEL, pc_phone.MY_NUMBER = topic, chan, self.v_mynum.get().strip()
            try:
                ok = pc_phone.push("Jarvis", "Verbindung steht. Hier kommen ab jetzt deine Routen an.", tags="robot")
            finally:
                pc_phone.PUSH_TOPIC, pc_phone.CHANNEL, pc_phone.MY_NUMBER = old
            loc = ""
            if self.v_loc.get().strip():
                pc_phone.LOC_TOPIC = self.v_loc.get().strip()
                pc_phone._loc["checked"] = 0
                pc_phone.location(max_age=10 ** 9)
                loc = " Standort: " + pc_phone.age_text() + "."
            msg = ("✔ Gesendet – kam die Nachricht an?" if ok else "✘ Senden ging nicht (Internet?).") + loc
            self.top.after(0, lambda: _safe(self.phone_status, msg))
        threading.Thread(target=run, daemon=True).start()

    def _test_groq(self):
        value = self.v_groq.get()
        key = pc_secret.unprotect(self.settings.get("groq_key_enc", "")) if value == self.PW_MASK else value.strip()
        if not key:
            self.groq_status.config(text="Trag zuerst den Groq-Schlüssel ein.")
            return
        self.groq_status.config(text="Teste …")

        def run():
            ok, msg = pc_ai.test_groq(key)
            try:
                self.top.after(0, lambda: _safe(self.groq_status, ("✔ " if ok else "✘ ") + msg))
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def _set_models(self, names):
        try:
            for page in self.pages.values():
                for w in page.winfo_children():
                    if isinstance(w, ttk.Combobox) and w.cget("textvariable") == str(self.v_model):
                        w.configure(values=["Automatisch"] + sorted(names))
        except Exception:
            pass  # Einstellungen wurden inzwischen geschlossen

    def _test_voice(self):
        """Spielt Wecksound und einen Beispielsatz mit den aktuell eingestellten (noch nicht gespeicherten) Werten."""
        kwargs = dict(
            engine=dict(ENGINES).get(self.v_engine.get(), "auto"),
            edge_voice=dict(pc_audio.EDGE_VOICES).get(self.v_edge.get(), "de-DE-KillianNeural"),
            windows_voice="" if self.v_winvoice.get() == AUTO_WINDOWS else self.v_winvoice.get(),
            pitch=int(float(self.v_pitch.get())),
            rate=int(float(self.v_rate.get())),
            output=dict(self.out_devices).get(self.v_out.get()),
            eleven_key=self._el_key(),
            eleven_voice=dict(self._el_voices).get(self.v_el_voice.get()),
            eleven_model=dict(pc_eleven.MODELS).get(self.v_el_model.get()),
        )
        if kwargs["engine"] == "eleven":
            self.el_status.config(text="Teste ElevenLabs …")

        def run():
            pc_audio.play_chime(device=kwargs["output"])
            time.sleep(0.7)
            pc_eleven.LAST_ERROR = ""
            pc_audio.speak("Guten Tag. Alle Systeme sind bereit. Was kann ich für Sie tun?", **kwargs)
            if kwargs["engine"] == "eleven":
                msg = ("✘ " + pc_eleven.LAST_ERROR + " (Zu hören war die Ersatzstimme.)") if pc_eleven.LAST_ERROR \
                    else "✔ ElevenLabs funktioniert."
                self._el_show(msg)

        threading.Thread(target=run, daemon=True).start()

    def _el_key(self) -> str:
        value = self.v_el_key.get()
        return pc_secret.unprotect(self.settings.get("eleven_key_enc", "")) if value == self.PW_MASK else value.strip()

    def _el_show(self, text):
        try:
            self.top.after(0, lambda: _safe(self.el_status, text))
        except Exception:
            pass

    def _el_load(self):
        key = self._el_key()
        if not key:
            self.el_status.config(text="Trag zuerst den ElevenLabs-Schlüssel ein.")
            return
        self.el_status.config(text="Lade Stimmen …")

        def run():
            try:
                found = pc_eleven.list_voices(key)
            except Exception as e:
                self._el_show(f"✘ {e}")
                return

            def done():
                known = {v for _, v in self._el_voices}
                self._el_voices += [(n, v) for n, v in found if v not in known]
                self.el_combo.configure(values=[n for n, _ in self._el_voices])
                self.el_status.config(text=f"✔ {len(found)} Stimmen in deinem Konto. Auswählen, „Stimme testen“, dann Speichern.")
            try:
                self.top.after(0, done)
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    def _edit_buttons(self):
        ButtonsDialog(self.top, self.buttons, lambda value: setattr(self, "buttons", value))

    def _open_custom(self):
        pc_apps.ensure_custom_file()
        try:
            os.startfile(os.path.join(pc_apps.base_dir(), pc_apps.CUSTOM_FILE))
        except Exception:
            pass

    def lift(self):
        self.top.tkraise()

    def exists(self) -> bool:
        try:
            return bool(self.top.winfo_exists())
        except Exception:
            return False
