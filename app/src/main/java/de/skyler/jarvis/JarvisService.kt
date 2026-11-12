package de.skyler.jarvis

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.NoiseSuppressor
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.io.ByteArrayOutputStream
import java.util.Locale
import kotlin.math.sqrt

/**
 * Jarvis im Hintergrund: hört dauerhaft (lautlos, auf dem Handy) auf das Aktivierungswort,
 * nimmt danach den Befehl auf, lässt ihn von Groq verstehen, führt ihn aus und antwortet mit der Handy-Stimme.
 */
class JarvisService : Service() {

    companion object {
        @Volatile var appVisible = false
        const val CH = "jarvis_listen"
        const val ACTION_TALK = "de.skyler.jarvis.TALK"   // Gespräch starten (ohne Aktivierungswort)
        const val ACTION_STOP = "de.skyler.jarvis.STOP"
        const val ACTION_PAUSE = "de.skyler.jarvis.PAUSE" // Mikrofon kurz freigeben (z. B. für ElevenLabs)
        const val ACTION_RESUME = "de.skyler.jarvis.RESUME"
        const val ACTION_RELOAD = "de.skyler.jarvis.RELOAD"
        @Volatile var running = false
            private set

        fun start(ctx: Context, action: String? = null) {
            val i = Intent(ctx, JarvisService::class.java)
            if (action != null) i.action = action
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i) else ctx.startService(i)
        }
    }

    private val tag = "JarvisSvc"
    private val main = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("jarvis", MODE_PRIVATE) }
    @Volatile private var alive = false
    @Volatile private var paused = false
    @Volatile private var speaking = false
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var overlay: Overlay? = null
    private val brain by lazy { Brain(this) }
    private var model: Model? = null
    private var rec: Recognizer? = null

    // IDLE = wartet aufs Aktivierungswort, COMMAND = wartet auf Befehl (kurz), TALK = Gespräch ohne Aktivierungswort
    private enum class Mode { IDLE, COMMAND, TALK }
    @Volatile private var mode = Mode.IDLE
    @Volatile private var deadline = 0L
    @Volatile private var busy = false     // denkt gerade nach
    private var lastCloudCheck = 0L
    private val worker = java.util.concurrent.Executors.newSingleThreadExecutor()  // Sätze der Reihe nach
    private var words = listOf("jarvis")
    private var level = 1

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(NotificationChannel(CH, "Jarvis hört zu", NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false); description = "Damit Jarvis im Hintergrund auf sein Aktivierungswort hören kann."
            })
        }
        reload()
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        else startForeground(1, notification())
        running = true
        Bus.emit("power", JSONObject().put("on", true))
        tts = TextToSpeech(this) { st ->
            ttsReady = st == TextToSpeech.SUCCESS
            if (ttsReady) setupVoice()
        }
        overlay = Overlay(this, { main.post { endTalk() } }, { main.post { startTalk() } })   // × = beenden, Mikro = weiterreden
        overlay?.appVisible = appVisible
        Bus.add(appListener)
        VoskModel.ensure(this) { ok -> if (ok) loadModel() }
        alive = true
        Thread({ audioLoop() }, "jarvis-audio").start()
        main.post(syncTask)
    }

    // Gedächtnis vom PC holen: beim Start und dann alle 15 Minuten
    private val syncTask = object : Runnable {
        override fun run() {
            if (!alive) return
            syncNow()
            main.postDelayed(this, 15 * 60_000L)
        }
    }

    private fun syncNow() {
        if (!Link.paired(this)) return
        Thread({
            try { if (Link.pull(this)) Bus.emit("synced", JSONObject().put("text", "Gedächtnis vom PC übernommen.")) }
            catch (e: Exception) { Log.w(tag, "sync: $e") }
        }, "jarvis-sync").start()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TALK -> startTalk()
            ACTION_STOP -> {   // auch "Ausschalten" in der Mitteilung: bleibt aus, bis du ihn wieder einschaltest
                prefs.edit().putBoolean("background", false).apply()
                endTalk(); Bus.emit("power", JSONObject().put("on", false)); stopSelf()
            }
            ACTION_PAUSE -> { paused = true; endTalk() }
            ACTION_RESUME -> paused = false
            ACTION_RELOAD -> { reload(); setupVoice(); syncNow() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        alive = false
        running = false
        main.removeCallbacks(syncTask)
        endVolume()
        overlay?.destroy()
        Bus.remove(appListener)
        try { tts?.shutdown() } catch (_: Exception) {}
        try { rec?.close(); model?.close() } catch (_: Exception) {}
        Bus.state("ended")
        super.onDestroy()
    }

    private fun reload() {
        words = Wake.words(this)
        level = Wake.level(this)
        val nm = getSystemService(NotificationManager::class.java)
        if (running) nm.notify(1, notification())
    }

    private fun notification(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = PendingIntent.getService(this, 1, Intent(this, JarvisService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE)
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CH) else @Suppress("DEPRECATION") Notification.Builder(this)
        return b.setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Jarvis hört zu")
            .setContentText("Sag „${words.first().replaceFirstChar { it.uppercase() }}“ – ich bin da.")
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Ausschalten", stop).build())
            .setOngoing(true)
            .build()
    }

    // --- Stimme ---------------------------------------------------------------------------------
    private fun setupVoice() {
        val t = tts ?: return
        if (!ttsReady) return
        t.language = Locale.GERMANY
        val voices = try { t.voices?.filter { it.locale.language == "de" } ?: emptyList() } catch (_: Exception) { emptyList() }
        val wanted = prefs.getString("tts_voice", "") ?: ""
        val chosen = voices.firstOrNull { it.name == wanted }
            ?: voices.firstOrNull { !it.isNetworkConnectionRequired && it.name.contains("male", true) && !it.name.contains("female", true) }
            ?: voices.firstOrNull { it.name.contains("deb") || it.name.contains("deg") }
        chosen?.let { t.voice = it }
        t.setSpeechRate(prefs.getFloat("tts_rate", 1.05f))
        t.setPitch(0.9f)
        val list = JSONObject().put("list", JSONArray(voices.map { it.name }.sorted())).put("current", t.voice?.name ?: "")
        prefs.edit().putString("tts_voices", list.toString()).apply()
    }

    // --- Eigene Lautstärke: solange Jarvis spricht, steht die Medienlautstärke auf "seiner" Lautstärke.
    // Drückst du währenddessen die Lautstärketasten, merkt er sich das als neue Jarvis-Lautstärke.
    private var savedVol = -1
    private var setVol = -1
    private var focus: android.media.AudioFocusRequest? = null

    private fun beginVolume() {
        if (savedVol >= 0) return
        val am = getSystemService(AUDIO_SERVICE) as android.media.AudioManager
        val s = android.media.AudioManager.STREAM_MUSIC
        try {
            val f = android.media.AudioFocusRequest.Builder(android.media.AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                .setAudioAttributes(android.media.AudioAttributes.Builder()
                    .setUsage(android.media.AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH).build()).build()
            am.requestAudioFocus(f); focus = f
        } catch (_: Exception) {}
        val max = am.getStreamMaxVolume(s)
        savedVol = am.getStreamVolume(s)
        setVol = Math.round(max * prefs.getInt("jarvis_volume", 70) / 100f).coerceIn(1, max)
        try { am.setStreamVolume(s, setVol, 0) } catch (_: Exception) {}
    }

    private fun endVolume() {
        if (savedVol < 0) return
        val am = getSystemService(AUDIO_SERVICE) as android.media.AudioManager
        val s = android.media.AudioManager.STREAM_MUSIC
        val now = am.getStreamVolume(s)
        if (now != setVol) {   // mit den Tasten verstellt -> neue Jarvis-Lautstärke
            val max = am.getStreamMaxVolume(s)
            prefs.edit().putInt("jarvis_volume", (now * 100 / maxOf(1, max)).coerceIn(10, 100)).apply()
        }
        try { am.setStreamVolume(s, savedVol, 0) } catch (_: Exception) {}
        focus?.let { try { am.abandonAudioFocusRequest(it) } catch (_: Exception) {} }
        focus = null; savedVol = -1; setVol = -1
    }

    private fun speak(text: String, then: () -> Unit) {
        val t = tts
        Bus.emit("agent", JSONObject().put("text", text))
        if (t == null || !ttsReady) { then(); return }
        beginVolume()
        speaking = true
        setState("speaking")
        val id = "j" + System.nanoTime()
        t.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) { if (utteranceId == id) done() }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) { if (utteranceId == id) done() }
            override fun onStop(utteranceId: String?, interrupted: Boolean) { if (utteranceId == id) done() }
            private fun done() {
                main.postDelayed({ speaking = false; endVolume(); rec?.reset(); then() }, 250) // kurz warten: Nachhall nicht mithören
            }
        })
        t.speak(text, TextToSpeech.QUEUE_FLUSH, null, id)
    }

    // --- Ist die Jarvis-App gerade vorne? Dann kein Leuchtrand (die App zeigt selbst, was passiert) ---------
    private val appListener: (String, JSONObject) -> Unit = { type, data ->
        if (type == "app_visible") main.post {
            val o = overlay ?: return@post
            val st = Bus.lastState
            o.setAppVisible(data.optBoolean("on"))
            if (!o.appVisible && st != "ended" && st != "idle") o.setState(st)
        }
    }

    // --- Zustände -----------------------------------------------------------------------------------
    private fun setState(st: String) {
        Bus.state(st)
        main.post {
            val o = overlay ?: return@post
            o.setState(st)
        }
    }

    private fun startTalk() {
        paused = false
        mode = Mode.TALK
        deadline = System.currentTimeMillis() + 45_000
        setState("listening")
        buzz()
    }

    private fun endTalk() {
        mode = Mode.IDLE
        try { tts?.stop() } catch (_: Exception) {}
        speaking = false
        main.post { endVolume() }
        setState("ended")
    }

    private fun onOrbTap() {
        if (speaking) { tts?.stop(); speaking = false; setState("listening"); deadline = System.currentTimeMillis() + 8000 }
        else endTalk()
    }

    private fun buzz() {
        try {
            val v = getSystemService(Vibrator::class.java)
            if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createOneShot(35, 120))
        } catch (_: Exception) {}
    }

    // --- Vosk ---------------------------------------------------------------------------------------
    private fun loadModel() {
        try {
            val m = Model(VoskModel.dir(this).absolutePath)
            model = m
            rec = Recognizer(m, 16000f)
            Log.i(tag, "Vosk bereit")
        } catch (e: Exception) {
            Log.w(tag, "Vosk: $e")
        }
    }

    /** Hört Vosk im laufenden Satz etwas, das wie das Aktivierungswort klingt? (großzügig, Groq prüft genau nach) */
    private fun voskHeardWake(json: String, key: String): Boolean {
        val t = try { JSONObject(json).optString(key) } catch (_: Exception) { "" }
        return t.isNotBlank() && Wake.find(t, words, 2) != null
    }

    // --- Mikrofon-Schleife ---------------------------------------------------------------------------
    @SuppressLint("MissingPermission")
    private fun audioLoop() {
        val rate = 16000
        val minBuf = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val ar = try {
            // VOICE_RECOGNITION: teilt sich das Mikrofon mit anderen Apps (WhatsApp-Sprachnachricht, Anrufe gehen vor)
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, rate, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, 6400))
        } catch (e: Exception) {
            Bus.emit("error", JSONObject().put("text", "Mikrofon nicht verfügbar: ${e.message}")); stopSelf(); return
        }
        try { if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(ar.audioSessionId)?.enabled = true } catch (_: Exception) {}
        ar.startRecording()
        val chunk = ByteArray(3200) // 100 ms
        val pre = ArrayDeque<ByteArray>()
        var utt: ByteArrayOutputStream? = null
        var quiet = 0
        var loud = 0
        var floor = 300.0
        var wakeSeen = false
        var micPaused = false
        while (alive) {
            if (paused) {
                if (!micPaused) { try { ar.stop() } catch (_: Exception) {}; micPaused = true }
                Thread.sleep(200); continue
            } else if (micPaused) { ar.startRecording(); micPaused = false }
            val n = ar.read(chunk, 0, chunk.size)
            if (n <= 0) continue
            val buf = chunk.copyOf(n)
            if (mode != Mode.IDLE && System.currentTimeMillis() > deadline && !busy && !speaking && utt == null) {
                mode = Mode.IDLE; setState("ended")
            }
            if (speaking) { pre.clear(); utt = null; continue }   // nicht sich selbst zuhören

            val rms = rms(buf)
            if (mode == Mode.IDLE && rec != null) {
                val r = rec!!
                if (r.acceptWaveForm(buf, buf.size)) { if (voskHeardWake(r.result, "text")) wakeSeen = true }
                else if (voskHeardWake(r.partialResult, "partial")) wakeSeen = true
            }
            val thr = maxOf(floor * 2.8, 380.0)
            if (utt == null) {
                pre.addLast(buf); if (pre.size > 4) pre.removeFirst()
                if (rms > thr) {
                    loud++
                    if (loud >= 2) {   // 200 ms Stimme -> Satz beginnt
                        utt = ByteArrayOutputStream().also { o -> pre.forEach { o.write(it) } }
                        quiet = 0
                        if (mode != Mode.IDLE) Bus.emit("level", JSONObject().put("kind", "mic").put("value", 0.6))
                    }
                } else {
                    loud = 0
                    floor = floor * 0.97 + rms * 0.03
                }
                continue
            }
            utt.write(buf)
            if (mode != Mode.IDLE) Bus.emit("level", JSONObject().put("kind", "mic").put("value", (rms / 4000).coerceIn(0.0, 1.0)))
            quiet = if (rms > thr * 0.7) 0 else quiet + 1
            val tooLong = utt.size() > 16000 * 2 * 14
            if (quiet >= 8 || tooLong) {     // 0,8 s Pause -> Satz zu Ende
                val pcm = utt.toByteArray()
                utt = null; loud = 0; pre.clear()
                val seconds = pcm.size / 32000.0
                val gotWake = wakeSeen
                wakeSeen = false
                if (seconds < 0.35) continue
                onUtterance(pcm, seconds, gotWake)
            }
        }
        try { ar.stop(); ar.release() } catch (_: Exception) {}
    }

    private fun rms(b: ByteArray): Double {
        var s = 0.0; var i = 0; var c = 0
        while (i + 1 < b.size) {
            val v = ((b[i + 1].toInt() shl 8) or (b[i].toInt() and 0xff)).toShort().toDouble()
            s += v * v; i += 4; c++
        }
        return if (c > 0) sqrt(s / c) else 0.0
    }

    private fun onUtterance(pcm: ByteArray, seconds: Double, voskWake: Boolean) {
        val key = prefs.getString("groq_key", "") ?: ""
        if (key.isBlank()) { Bus.emit("needkey"); return }
        val now = System.currentTimeMillis()
        if (mode == Mode.IDLE) {
            // Ohne Vosk-Treffer nur im "genauen Modus" (oder solange das Modell noch lädt) kurze Sätze prüfen lassen
            val cloud = prefs.getBoolean("wake_cloud", false) || rec == null
            if (!voskWake && !(cloud && seconds < 6 && now - lastCloudCheck > 2500)) return
            lastCloudCheck = now
        }
        busy = true
        worker.execute {
            try {
                val text = Groq.transcribe(key, pcm)
                Log.i(tag, "gehört: $text")
                if (text.isBlank()) return@execute
                if (mode == Mode.IDLE) {
                    val am = getSystemService(AUDIO_SERVICE) as android.media.AudioManager
                    val strict = if (am.isMusicActive) 0 else level   // läuft ein Video/Musik: nur ganz genaues "Jarvis"
                    val cmd = Wake.commandAfter(text, words, strict) ?: return@execute
                    buzz()
                    Bus.emit("user", JSONObject().put("text", text))
                    if (cmd.isBlank()) {   // nur das Aktivierungswort: auf den Befehl warten
                        mode = Mode.COMMAND
                        deadline = System.currentTimeMillis() + 7000
                        setState("listening")
                        return@execute
                    }
                    answer(key, cmd)
                } else {
                    Bus.emit("user", JSONObject().put("text", text))
                    val cmd = Wake.commandAfter(text, words, level)?.takeIf { it.isNotBlank() } ?: text
                    if (Regex("^(tschüss|danke|das war'?s|stopp|ende|gespräch beenden|nichts)\\b", RegexOption.IGNORE_CASE)
                            .containsMatchIn(cmd.trim()) && cmd.split(" ").size <= 4) {
                        main.post { speak(if (cmd.lowercase().startsWith("danke")) "Gern." else "Bis später.") { endTalk() } }
                        return@execute
                    }
                    answer(key, cmd)
                }
            } catch (e: Groq.KeyError) {
                Bus.emit("error", JSONObject().put("text", e.message)); Bus.emit("needkey")
            } catch (e: Exception) {
                Log.w(tag, "utterance: $e")
                if (mode != Mode.IDLE) main.post { speak("Ich komme gerade nicht ins Internet.") { endTalk() } }
            } finally {
                busy = false
            }
        }
    }

    private fun answer(key: String, cmd: String) {
        setState("thinking")
        brain.onStatus = { t -> main.post { overlay?.panel?.state("searching", t) } }
        val reply = try { brain.handle(key, cmd) } catch (e: Exception) { "Das hat nicht geklappt. ${e.message ?: ""}" }
        val card = brain.card
        main.post {
            card?.let { overlay?.card(it) }   // Antwort als Karte im Fenster (außerhalb der Jarvis-App)
            speak(reply) {
                // danach kurz weiterhören wie am PC (ohne Aktivierungswort); im Gespräch länger
                if (mode == Mode.TALK) deadline = System.currentTimeMillis() + 45_000
                else { mode = Mode.COMMAND; deadline = System.currentTimeMillis() + 6000 }
                setState("listening")
            }
        }
    }
}
