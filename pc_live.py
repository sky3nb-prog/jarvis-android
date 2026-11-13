"""
Live-Gespräch mit Jarvis – so wie auf der ElevenLabs-Sprechseite, aber direkt im PC-Jarvis.

"Jarvis, lass uns reden" (oder der Knopf im HUD): Jarvis verbindet sich mit dem Cloud-Jarvis (ElevenLabs Agent) und
ihr redet ganz natürlich hin und her. Man kann ihn jederzeit unterbrechen, er antwortet sofort mit der George-Stimme.
- Er kennt dich: Was der PC-Jarvis über dich weiß, bekommt der Cloud-Jarvis zu Gesprächsbeginn mit.
- Er kann den PC steuern: Sagst du z. B. "mach Discord auf", führt der PC-Jarvis den Befehl aus (Werkzeug "pc_befehl").
- Beenden: "Tschüss", "Gespräch beenden", "das war's", das X am Overlay – oder einfach eine Weile nichts sagen.

Technik: WebSocket wss://api.elevenlabs.io/v1/convai/conversation, Mikrofon 16 kHz PCM hin, Stimme 16 kHz PCM zurück.
"""

import base64
import json
import queue
import re
import threading
import time

import numpy as np

AGENT_ID = "agent_4701m6c6964efypvmbjqf3e7ak9m"  # aus den Einstellungen überschreibbar
URL = "wss://api.elevenlabs.io/v1/convai/conversation?agent_id={}"
START = re.compile(r"lass uns (?:reden|quatschen|plaudern|sprechen|unterhalten)|gesprächsmodus|live[- ]?(?:modus|gespräch)|"
                   r"unterhalt(?:en wir|e dich) (?:uns|mit mir)|ich will (?:mit dir )?reden", re.I)
END = re.compile(r"\b(?:tschüss|tschau|ciao|bis später|bis dann|gespräch beenden|beende das gespräch|das war'?s|"
                 r"auflegen|leg auf|ende)\b", re.I)
REQUEST = threading.Event()  # vom HUD-Knopf: Gespräch starten, sobald die Hörschleife frei ist
IDLE_TIMEOUT = 45  # Sekunden ohne dass jemand redet -> Gespräch endet


def _prompt(memory: str, persona: str, name: str) -> str:
    now = time.strftime("%A, %d.%m.%Y, %H:%M Uhr")
    return f"""Du bist {name}, der persönliche KI-Butler des Nutzers (Skyler aus Leonberg). Ihr führt gerade ein
gesprochenes Gespräch. {persona}
Antworte kurz und natürlich (meist 1 bis 3 Sätze), wie in einem echten Gespräch, auf Deutsch, ohne Listen.
Es ist {now}.
Wenn der Nutzer möchte, dass am PC etwas passiert (Programm öffnen, Musik, Lautstärke, Discord, Nachricht schreiben,
Timer, Wetter, Lage, PC sperren usw.), benutze das Werkzeug pc_befehl mit dem Befehl in seinen Worten, zum Beispiel
"öffne Discord" oder "spiel lofi auf YouTube", und sag danach kurz, was passiert ist.
{memory}"""


class LiveSession:
    def __init__(self, q, threshold, ui, run_pc, settings: dict):
        self.q, self.ui, self.run_pc = q, ui, run_pc
        self.settings = settings
        self.thr = max(threshold * 1.0, 300.0)
        self.ws = None
        self.play_q: "queue.Queue" = queue.Queue()
        self.playing_until = 0.0
        self.stop = threading.Event()
        self.last_activity = time.time()
        self.out_rate = 16000
        self.in_rate = 16000
        self.error = ""

    # --- Senden ---
    def _send(self, obj):
        try:
            self.ws.send(json.dumps(obj))
        except Exception as e:  # Verbindung weg
            self.error = self.error or str(e)
            self.stop.set()

    def _mic_loop(self):
        """Mikrofon-Blöcke (0,1 s) an den Cloud-Jarvis. Während er spricht, nur laute Stimme durchlassen,
        damit er sich nicht selbst aus den Lautsprechern hört (Unterbrechen geht trotzdem)."""
        silence = b"\x00" * 3200
        while not self.stop.is_set():
            try:
                chunk = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            level = float(np.sqrt(np.mean(np.frombuffer(chunk, dtype="<i2").astype(np.float32) ** 2))) if chunk else 0.0
            speaking = time.time() < self.playing_until
            if speaking and level < self.thr * 2.6:
                chunk = silence[:len(chunk)]
            elif level > self.thr:
                self.last_activity = time.time()
            self._send({"user_audio_chunk": base64.b64encode(chunk).decode("ascii")})
            if time.time() - self.last_activity > IDLE_TIMEOUT and not speaking:
                self.ui.post("Assistent", "Gespräch beendet (Pause zu lang).", 3000, glow=True)
                self.stop.set()

    # --- Abspielen ---
    def _play_loop(self):
        import pc_audio
        import pc_eleven
        import pc_sphere
        import sounddevice as sd

        name = pc_audio.OUTPUT_DEVICE
        idx = pc_audio.resolve_device(name, "output") if name else None
        try:
            stream = sd.RawOutputStream(samplerate=self.out_rate, channels=1, dtype="int16", device=idx)
            rate = self.out_rate
        except Exception:
            rate = int(sd.query_devices(idx if idx is not None else sd.default.device[1], "output")["default_samplerate"])
            stream = sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16", device=idx)
        stream.start()
        try:
            while not self.stop.is_set():
                try:
                    pcm = self.play_q.get(timeout=0.1)
                except queue.Empty:
                    pc_sphere.set_level("out", 0.0)
                    continue
                if pcm is None:
                    continue
                a = np.frombuffer(pcm, dtype="<i2")
                if rate != self.out_rate and len(a):
                    n = int(len(a) * rate / self.out_rate)
                    a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a.astype(np.float32)).astype("<i2")
                self.playing_until = time.time() + len(a) / rate + 0.35
                pc_sphere.set_level("out", min(1.0, float(np.sqrt(np.mean(a.astype(np.float32) ** 2))) / 6000.0))
                for i in range(0, len(a), 1600):  # kleine Stücke, damit Unterbrechen sofort greift
                    if self.stop.is_set() or self.play_q.queue and self.play_q.queue[0] is None:
                        break
                    stream.write(a[i:i + 1600].tobytes())
        finally:
            pc_sphere.set_level("out", 0.0)
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _flush_audio(self):
        try:
            while True:
                self.play_q.get_nowait()
        except queue.Empty:
            pass
        self.play_q.put(None)  # Marker: aktuelles Stück abbrechen
        self.playing_until = 0.0

    # --- Empfangen ---
    def _handle(self, msg: dict):
        t = msg.get("type")
        if t == "audio":
            ev = msg.get("audio_event") or {}
            b64 = ev.get("audio_base_64")
            if b64:
                self.play_q.put(base64.b64decode(b64))
        elif t == "ping":
            ev = msg.get("ping_event") or {}
            self._send({"type": "pong", "event_id": ev.get("event_id")})
        elif t == "interruption":
            self._flush_audio()
        elif t == "user_transcript":
            text = (msg.get("user_transcription_event") or {}).get("user_transcript", "")
            if text:
                self.last_activity = time.time()
                self.ui.post("Du", text, glow=True, log=True)
                if END.search(text) and len(text.split()) <= 5:
                    threading.Timer(2.5, self.stop.set).start()  # Jarvis darf sich noch kurz verabschieden
        elif t == "agent_response":
            text = (msg.get("agent_response_event") or {}).get("agent_response", "")
            if text:
                self.ui.post("Assistent", text, glow=True, log=True)
        elif t == "client_tool_call":
            call = msg.get("client_tool_call") or {}
            threading.Thread(target=self._tool, args=(call,), daemon=True).start()
        elif t == "conversation_initiation_metadata":
            ev = msg.get("conversation_initiation_metadata_event") or {}
            fmt = str(ev.get("agent_output_audio_format") or "pcm_16000")
            m = re.search(r"pcm_(\d+)", fmt)
            if m:
                self.out_rate = int(m.group(1))

    def _tool(self, call: dict):
        name = call.get("tool_name", "")
        params = call.get("parameters") or {}
        result, err = "", False
        try:
            if name == "pc_befehl":
                cmd = str(params.get("befehl") or params.get("command") or "").strip()
                result = self.run_pc(cmd) if cmd else "Kein Befehl angegeben."
            else:
                result, err = f"Unbekanntes Werkzeug {name}", True
        except Exception as e:
            result, err = f"Fehler: {e}", True
        self._send({"type": "client_tool_result", "tool_call_id": call.get("tool_call_id"),
                    "result": str(result)[:1500], "is_error": err})

    def _recv_loop(self):
        while not self.stop.is_set():
            try:
                raw = self.ws.recv()
            except Exception as e:
                if not self.stop.is_set():
                    self.error = self.error or str(e)
                self.stop.set()
                break
            if not raw:
                continue
            try:
                self._handle(json.loads(raw))
            except Exception as e:
                print(f"Live: {e}")

    def _connect(self, with_override: bool):
        import websocket  # Paket websocket-client

        import pc_memory
        import pc_steuerung
        import pc_talk

        agent = (self.settings.get("live_agent_id") or AGENT_ID).strip()
        self.ws = websocket.create_connection(URL.format(agent), timeout=15)
        self.ws.settimeout(None)
        init = {"type": "conversation_initiation_client_data"}
        if with_override:
            persona = pc_steuerung.PERSONAS.get(pc_steuerung.PERSONA, "")
            name = (pc_talk.NAME or "Jarvis").replace(".", "") or "Jarvis"
            init["conversation_config_override"] = {
                "agent": {"prompt": {"prompt": _prompt(pc_memory.prompt_block(), persona, name)},
                          "language": "de"}}
        self.ws.send(json.dumps(init))

    def _open(self) -> str:
        """Verbinden; zuerst mit deinem Wissen (Überschreiben), sonst ohne. Wartet auf die Begrüßungs-Meldung."""
        last = ""
        for override in (True, False):
            try:
                self._connect(with_override=override)
                self.ws.settimeout(8)
                while True:
                    msg = json.loads(self.ws.recv())
                    self._handle(msg)
                    if msg.get("type") == "conversation_initiation_metadata":
                        break
                self.ws.settimeout(None)
                if not override:
                    print("Live: Agent erlaubt kein Überschreiben – Gespräch ohne Gedächtnis.")
                return ""
            except Exception as e:
                last = str(e) or type(e).__name__
                print(f"Live-Verbindung ({'mit' if override else 'ohne'} Gedächtnis): {last}")
                try:
                    self.ws.close()
                except Exception:
                    pass
        return last

    def run(self) -> str:
        """Führt das Gespräch (blockiert bis zum Ende). Gibt einen Fehlertext zurück oder ''."""
        import pc_cancel

        gen = pc_cancel.GEN
        err = self._open()
        if err:
            return f"Ich komme gerade nicht zum Cloud-Jarvis durch ({err[:80]})."
        threads = [threading.Thread(target=f, daemon=True) for f in (self._recv_loop, self._play_loop, self._mic_loop)]
        for th in threads:
            th.start()
        self.ui.post("Gespräch", "Live mit Jarvis – sag „Tschüss“ zum Beenden", glow=True)
        while not self.stop.is_set():
            if pc_cancel.changed(gen):  # X am Overlay
                self.stop.set()
                break
            time.sleep(0.1)
        try:
            self.ws.close()
        except Exception:
            pass
        for th in threads:
            th.join(1.5)
        return ""
