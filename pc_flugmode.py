"""
Flugverkehr-Modus im HUD: derselbe Globus wie im Lage-Screen (Globus oder Satellit), darauf die Flugzeuge live.

Oben links wählst du, was du sehen willst: über dir (Leonberg), Deutschland, Europa, USA, die ganze Welt oder eigene
Orte (Einstellungen > Weltlage > "Flugverkehr: eigene Orte"). Klick auf ein Flugzeug = Airline, Typ, Route, Höhe.
Zwischen zwei Abfragen fliegen die Flugzeuge rechnerisch weiter, dadurch bewegen sie sich flüssig.

Daten: airplanes.live / adsb.lol (Umkreis bis 460 km, alle 10 s) und OpenSky (große Gebiete, alle paar Minuten).
"""

import math
import threading
import time

import pc_flights

# Schlüssel, Beschriftung, Mitte (lat, lon), Rechteck (lamin, lomin, lamax, lomax) oder None, Kachelstufe zum Anzeigen
REGIONS = [
    ("home", "⌂ Über mir", None, None, 7.2),
    ("de", "Deutschland", (51.1, 10.4), (47.2, 5.8, 55.1, 15.1), 5.6),
    ("eu", "Europa", (50.0, 12.0), (34.0, -12.0, 63.0, 35.0), 4.0),
    ("us", "USA", (39.0, -97.0), (24.0, -125.0, 50.0, -66.0), 3.7),
    ("welt", "Welt", (30.0, 10.0), (-85.0, -180.0, 85.0, 180.0), 1.0),
]
DE_POINTS = [(50.1, 8.7), (52.5, 13.4), (48.2, 11.6), (53.5, 10.0)]
# Farben: Linie, Fracht, Privat, Militär (hell, dunkel für den Schein)
KIND_COL = {"linie": ("#ffbe50", "#5a3d10"), "fracht": ("#3cc8ff", "#0e3f55"), "privat": ("#6effcd", "#164a3c"),
            "militaer": ("#ff5a5a", "#561616")}
REGION_ZOOM = {"home": 1.0, "de": 1.0, "eu": 1.0, "us": 1.0, "welt": 1.0}


class FlugMixin:
    """Wird in HudWindow eingemischt (nutzt dessen Globus, Leinwand und Schriften)."""

    # --- Daten -----------------------------------------------------------------------------------
    def _flug_init(self):
        if not hasattr(self, "_fl"):
            self._fl = dict(planes=[], ts=0.0, region=None, status="", sel=None, info="", run=False, places={})
        s = self.get_settings()
        if self._fl["region"] is None:
            self._fl["region"] = s.get("flug_region") or "home"
        if not self._fl["run"]:
            self._fl["run"] = True
            threading.Thread(target=self._flug_loop, daemon=True, name="jarvis-flug").start()

    def _flug_regions(self):
        out = list(REGIONS)
        for p in (self.get_settings().get("flug_places") or [])[:6]:
            p = str(p).strip()
            if p:
                out.append(("ort:" + p, p, None, None, 7.2))
        return out

    def _flug_region(self):
        key = self._fl["region"]
        for r in self._flug_regions():
            if r[0] == key:
                return r
        return REGIONS[0]

    def _flug_center(self, r):
        if r[0] == "home":
            return self.LAGE_HOME
        if r[0].startswith("ort:"):
            hit = self._fl["places"].get(r[1])
            if hit is None:
                try:
                    import pc_news

                    g = pc_news._geocode(r[1])
                    hit = (g[0], g[1]) if g else False
                except Exception:  # noqa: BLE001
                    hit = False
                self._fl["places"][r[1]] = hit
            return hit or None
        return r[2]

    def _flug_loop(self):
        last_key, last = None, 0.0
        while True:
            try:
                if self.mode != "flug":
                    time.sleep(1.0)
                    continue
                r = self._flug_region()
                big = r[3] is not None and r[0] in ("eu", "us", "welt")
                every = {"eu": 120, "us": 120, "welt": 180}.get(r[0], 20 if r[0] == "de" else 10)
                if r[0] == last_key and time.time() - last < every:
                    time.sleep(0.5)
                    continue
                last_key, last = r[0], time.time()
                self._fl["status"] = "lade Flugdaten …" if not self._fl["planes"] or self._fl.get("rkey") != r[0] else ""
                if big:
                    planes = pc_flights.area(*r[3])
                elif r[0] == "de":
                    seen, planes = set(), []
                    for la, lo in DE_POINTS:
                        for p in pc_flights.around(la, lo, 250):
                            if p["id"] not in seen:
                                seen.add(p["id"])
                                planes.append(p)
                        time.sleep(1.1)  # die Dienste mögen höchstens eine Anfrage pro Sekunde
                else:
                    c = self._flug_center(r)
                    planes = pc_flights.around(c[0], c[1], 250) if c else []
                    if not c:
                        self._fl["status"] = f"{r[1]} habe ich nicht gefunden."
                if self._fl["region"] == r[0]:
                    self._fl.update(planes=planes, ts=time.time(), rkey=r[0])
                    if planes or c_ok(r):
                        self._fl["status"] = ""
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                self._fl["status"] = ("OpenSky lässt gerade keine Abfrage zu – gleich noch mal." if "429" in msg
                                      else "Flugdaten gerade nicht erreichbar.")
                last = time.time() - 50 if last_key else 0.0
                time.sleep(2.0)

    def flug_show(self, key):
        """Region wählen (Klick auf einen Knopf oder per Sprache)."""
        self._flug_init()
        if key != self._fl["region"]:
            self._fl.update(region=key, planes=[], sel=None, info="", status="lade Flugdaten …")
            s = dict(self.get_settings())
            s["flug_region"] = key
            try:
                self.on_save_settings(s)  # baut das HUD neu auf (gleicher Modus)
            except Exception:  # noqa: BLE001
                pass
        if self.mode == "flug":
            self._flug_chips()
            self._flug_goto()

    def _flug_goto(self):
        import pc_lage

        r = self._flug_region()
        c = self._flug_center(r) if r[0] == "home" or r[0].startswith("ort:") else r[2]
        if not c:
            return
        z = REGION_ZOOM.get(r[0], 1.3)  # immer die Kugel (Weltkarte) – heranzoomen kann man selbst
        self._lage_fly(c[0] - (6 if z <= 1.0 else 0), c[1], zoom=z)

    # --- Anzeige ----------------------------------------------------------------------------------
    def _flug_build(self):
        """Wird von _build_lage im Flug-Modus aufgerufen."""
        self._flug_init()
        c = self.c
        c.itemconfigure(self.lage_big, text="…")
        c.itemconfigure(self.lage_sub, text="FLUGZEUGE IN DER LUFT")
        c.itemconfigure(self.lage_hint, text="Klick auf einen Punkt oder in der Liste = Details · ziehen = drehen · Mausrad = zoomen")
        self._flug_chips()
        c.tag_bind("flplane", "<Button-1>", self._flug_click)
        if not getattr(self, "_flug_entered", False):
            self._flug_entered = True
            self.win.after(200, self._flug_goto)

    def _flug_chips(self):
        c, S, X, Y = self.c, self.lg["S"], self.lg["X"], self.lg["Y"]
        c.delete("lagechip")
        x, y = X(64), Y(192)
        for i, r in enumerate(self._flug_regions()):
            label = r[1]
            on = r[0] == self._fl["region"]
            w = self.f["small"].measure(label) + S(26)
            if x + w > X(480):
                x, y = X(64), y + S(36)
            tag = f"lagechip{i}"
            self._pill(x, y, x + w, y + S(28), "#3a2608" if on else "#06141e", "#ffb446" if on else "#16506a",
                       ("lagechip", tag))
            c.create_text(x + w / 2, y + S(14), text=label, font=self.f["small"],
                          fill="#ffd28c" if on else "#9cc8dc", tags=("lagechip", tag))
            c.tag_bind(tag, "<Button-1>", lambda e, k=r[0]: self.flug_show(k))
            self._hand(tag)
            x += w + S(8)

    def _flug_now(self):
        """Flugzeuge mit ihrer Position JETZT (zwischen zwei Abfragen weitergerechnet)."""
        fl = self._fl
        dt = max(0.0, min(300.0, time.time() - fl["ts"]))
        out = []
        for p in fl["planes"]:
            la, lo = pc_flights.move(p, dt) if dt > 0.5 else (p["lat"], p["lon"])
            out.append((p, la, lo))
        return out

    def _flug_data(self):
        """Einmal pro Sekunde: Zahl, Status, Flugzeuge neu setzen."""
        fl = self._fl
        n = len(fl["planes"])
        r = self._flug_region()
        self.c.itemconfigure(self.lage_big, text=f"{n:,}".replace(",", ".") if n else "…")
        sub = "FLUGZEUGE IN DER LUFT · " + r[1].replace("⌂ ", "").upper()
        if fl["status"]:
            sub += " · " + fl["status"].upper()
        self.c.itemconfigure(self.lage_sub, text=sub)
        if not self._lage_anim and not self._lage_drag and self._zoom_goal is None:
            self._flug_overlay()

    def _flug_overlay(self):
        import pc_lage

        c, S = self.c, self.lg["S"]
        c.delete("lagegeo")
        cx, cy, R = self.lg["cx"], self.lg["cy"], self.lg["R"] * self.lage_zoom
        lat0, lon0 = self.lage_cam
        planes = self._flug_now()
        vis = []
        counts = {k: 0 for k in KIND_COL}
        for p, _, _ in planes:
            counts[self._flug_kind(p)] += 1
        if planes:
            xs, ys, vs, _ = pc_lage.project([q[1] for q in planes], [q[2] for q in planes], lat0, lon0, cx, cy, R)
            G = self.lg["size"] / 2 - S(4)
            vis = [(p, float(x), float(y)) for (p, _, _), x, y, v in zip(planes, xs, ys, vs)
                   if v and abs(x - cx) < G and abs(y - cy) < G]
            if len(vis) > 900:  # sehr viele (Welt): gleichmäßig ausdünnen
                step = len(vis) / 900.0
                vis = [vis[int(i * step)] for i in range(900)]
            r1, r2 = (S(2.2), S(4.5)) if len(vis) < 400 or self.lage_zoom > 2 else (S(1.4), S(3))
            sel = self._fl.get("sel")
            for p, x, y in vis:  # nur Punkte, ohne Schrift
                col, dim = KIND_COL[self._flug_kind(p)]
                c.create_oval(x - r2, y - r2, x + r2, y + r2, fill=dim, outline="", tags=("lagegeo", "flplane"))
                c.create_oval(x - r1, y - r1, x + r1, y + r1, fill=col, outline="", tags=("lagegeo", "flplane"))
            if sel:
                for p, x, y in vis:
                    if p["id"] == sel["id"]:
                        r = S(11)
                        c.create_oval(x - r, y - r, x + r, y + r, outline="#ffffff", width=2, tags="lagegeo")
        self._fl_screen = vis
        self._flug_legend(counts)
        self._flug_list(planes)
        self._flug_card()
        self._raise_top()

    def _flug_kind(self, p):
        k = p.get("_kind")
        if k is None:
            k = p["_kind"] = pc_flights.kind(p)
        return k

    def _flug_legend(self, counts):
        c, S = self.c, self.lg["S"]
        c.delete("fllegend")
        items = [(k, pc_flights.KINDS[k], counts.get(k, 0)) for k in ("linie", "fracht", "privat", "militaer")]
        widths = [self.f["small"].measure(f"{lab} {n}") + S(30) for _, lab, n in items]
        x = self.lg["cx"] - sum(widths) / 2
        y = self.lg["cy"] + self.lg["size"] / 2 + S(22)
        for (k, lab, n), w in zip(items, widths):
            col, dim = KIND_COL[k]
            c.create_oval(x + S(4), y - S(6), x + S(16), y + S(6), fill=dim, outline="", tags=("lagegeo", "fllegend"))
            c.create_oval(x + S(7), y - S(3), x + S(13), y + S(3), fill=col, outline="", tags=("lagegeo", "fllegend"))
            c.create_text(x + S(22), y, text=f"{lab} {n}", anchor="w", fill="#cfe1ea", font=self.f["small"],
                          tags=("lagegeo", "fllegend"))
            x += w

    def _flug_list(self, planes):
        """Rechts: die Flugzeuge als Liste (nächste zuerst), anklickbar."""
        c, S, X, Y = self.c, self.lg["S"], self.lg["X"], self.lg["Y"]
        c.delete("fllist")
        x0, y0, x1, y1 = X(1170), Y(110), X(1572), Y(872)
        c.create_rectangle(x0, y0, x1, y1, fill="#04121c", outline="#16506a", tags="fllist")
        c.create_line(x0 + S(14), y0, x0 + S(70), y0, fill="#ffb446", width=max(2, int(S(3))), tags="fllist")
        r = self._flug_region()
        ref = self._flug_center(r) if (r[0] == "home" or r[0].startswith("ort:")) else tuple(self.lage_cam)
        ref = ref or self.LAGE_HOME
        c.create_text(x0 + S(16), y0 + S(14), text="IM LUFTRAUM · NÄCHSTE ZUERST", anchor="nw", fill="#ffb446",
                      font=self.f["head"], tags="fllist")
        if not planes:
            c.create_text(x0 + S(16), y0 + S(48), text=self._fl.get("status") or "Keine Flugzeuge empfangen.", anchor="nw",
                          fill="#9cc8dc", font=self.f["small"], width=int(x1 - x0 - S(32)), tags="fllist")
            return
        rows = sorted(planes, key=lambda q: pc_flights.distance_km(ref[0], ref[1], q[1], q[2]))
        n = max(1, int((y1 - y0 - S(56)) // S(46)))
        sel = self._fl.get("sel")
        top = rows[:n]
        if sel and all(p["id"] != sel["id"] for p, _, _ in top):
            hit = [q for q in rows if q[0]["id"] == sel["id"]]
            if hit:
                top = hit + top[:-1]
        y = y0 + S(46)
        todo = []
        for i, (p, la, lo) in enumerate(top):
            tag = f"flrow{i}"
            on = sel is not None and p["id"] == sel["id"]
            col, _ = KIND_COL[self._flug_kind(p)]
            if on:
                c.create_rectangle(x0 + S(8), y - S(5), x1 - S(8), y + S(38), fill="#1e1608", outline="#ffb446",
                                   tags=("fllist", tag))
            else:
                c.create_rectangle(x0 + S(8), y - S(5), x1 - S(8), y + S(38), fill="#04121c", outline="",
                                   tags=("fllist", tag))
            c.create_oval(x0 + S(18), y + S(4), x0 + S(26), y + S(12), fill=col, outline="", tags=("fllist", tag))
            c.create_text(x0 + S(34), y, text=(p.get("call") or p.get("id", "")).upper(), anchor="nw",
                          fill="#ffffff" if on else "#ffd68c", font=self.f["label"], tags=("fllist", tag))
            alt = int(round((p.get("alt") or 0) / 100.0) * 100)
            c.create_text(x1 - S(18), y, text=f"{alt:,} m".replace(",", "."), anchor="ne", fill="#c8e6f5",
                          font=self.f["small"], tags=("fllist", tag))
            rt = pc_flights._route_cache.get((p.get("call") or "").strip().upper())
            info = rt[1] if isinstance(rt, tuple) else rt
            if isinstance(info, dict) and info.get("von") and info.get("nach"):
                line = (info.get("airline") + " · " if info.get("airline") else "") + f"{info['von']} → {info['nach']}"
            else:
                line = pc_flights.KINDS[self._flug_kind(p)] + (" · " + p["desc"].title() if p.get("desc") else "")
                if (p.get("call") or "").strip().upper() not in pc_flights._route_cache:
                    todo.append(p)
            km = pc_flights.distance_km(ref[0], ref[1], la, lo)
            c.create_text(x0 + S(34), y + S(19), text=line[:46], anchor="nw", fill="#96bed0", font=self.f["tiny"],
                          tags=("fllist", tag))
            c.create_text(x1 - S(18), y + S(19), text=f"{km:.0f} km", anchor="ne", fill="#6e96aa", font=self.f["tiny"],
                          tags=("fllist", tag))
            c.tag_bind(tag, "<Button-1>", lambda e, p=p: self._flug_select(p))
            self._hand(tag)
            y += S(46)
        self._flug_routes(todo[:8])

    def _flug_routes(self, planes):
        """Routen (von wo nach wo) für die Liste im Hintergrund nachschlagen – höchstens eine pro Sekunde."""
        if getattr(self, "_fl_route_busy", False) or not planes:
            return
        self._fl_route_busy = True

        def run():
            try:
                for p in planes:
                    if self.mode != "flug":
                        break
                    if p.get("call") and any(ch.isdigit() for ch in p["call"]):
                        try:
                            pc_flights.route(p["call"])
                        except Exception:  # noqa: BLE001
                            pass
                        time.sleep(1.0)
            finally:
                self._fl_route_busy = False
        threading.Thread(target=run, daemon=True).start()

    def _flug_select(self, p):
        self._fl["sel"] = p
        self._fl["info"] = "…"
        self._lage_touch = time.time()

        def run(p=p):
            try:
                txt = pc_flights.describe(p, *self.LAGE_HOME)
            except Exception:  # noqa: BLE001
                txt = ""
            if self._fl.get("sel") is p:
                self._fl["info"] = txt
                try:
                    self.win.after(0, self._flug_card)
                except Exception:  # noqa: BLE001
                    pass
        threading.Thread(target=run, daemon=True).start()
        self._flug_overlay()

    def _flug_click(self, e):
        best, bd = None, 1e9
        for p, x, y in getattr(self, "_fl_screen", []):
            d = (x - e.x) ** 2 + (y - e.y) ** 2
            if d < bd:
                best, bd = p, d
        if best is not None and bd <= (self.lg["S"](18)) ** 2:
            self._flug_select(best)

    def _flug_card(self):
        c, S, X, Y = self.c, self.lg["S"], self.lg["X"], self.lg["Y"]
        c.delete("lagecard")
        p = self._fl.get("sel")
        if not p:
            return
        x0, y0, x1 = X(60), Y(650), X(440)
        pad = S(16)
        y = y0 + S(14)
        items = [c.create_text(x0 + pad, y, text=("✈  " + (p.get("call") or p.get("id", "")).upper()), anchor="nw",
                               fill="#ffb446", font=self.f["head"], tags="lagecard")]
        y += S(28)
        lines = [self._fl.get("info") or "",
                 f"Höhe {int(round((p.get('alt') or 0) / 100.0) * 100)} m · {int(p.get('speed') or 0)} km/h · "
                 f"Kurs {int(p.get('track') or 0)}°"]
        for text in lines:
            if not text:
                continue
            items.append(c.create_text(x0 + pad, y, text=text, anchor="nw", fill="#e6f0f8", font=self.f["small"],
                                       width=int(x1 - x0 - 2 * pad), tags="lagecard"))
            bb = c.bbox(items[-1])
            y = (bb[3] if bb else y + S(20)) + S(6)
        y1 = max(y + pad, y0 + S(110))
        rect = c.create_rectangle(x0, y0, x1, y1, fill="#04121c", outline="#16506a", tags="lagecard")
        acc = c.create_line(x0 + S(14), y0, x0 + S(70), y0, fill="#ffb446", width=max(2, int(S(3))), tags="lagecard")
        c.tag_lower(rect, items[0])
        c.tag_raise(acc)


def c_ok(r):
    return r[0] in ("de", "eu", "us", "welt", "home")
