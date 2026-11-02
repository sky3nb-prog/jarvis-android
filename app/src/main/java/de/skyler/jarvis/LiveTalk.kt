package de.skyler.jarvis

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.Build
import android.util.Base64
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt

/**
 * Live-Gespräch mit dem Cloud-Jarvis (ElevenLabs Agent) über WebSocket.
 * Mikrofon (16 kHz, mit Echo-Unterdrückung des Handys) -> Agent, Stimme des Agenten -> Lautsprecher.
 */
class LiveTalk(
    private val context: Context,
    private val agentId: String,
    private val promptOverride: String?,
    private val onEvent: (type: String, data: JSONObject) -> Unit,
) {
    private val tag = "JarvisLive"
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private var ws: WebSocket? = null
    private val running = AtomicBoolean(false)
    private var record: AudioRecord? = null
    private var track: AudioTrack? = null
    private var outRate = 16000
    private val playQueue = LinkedBlockingQueue<ByteArray>()
    @Volatile private var flushRequested = false
    @Volatile private var opened = false
    @Volatile private var triedWithoutOverride = false
    private val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var lastLevelSent = 0L

    val isRunning: Boolean get() = running.get()

    fun start() {
        if (running.getAndSet(true)) return
        emit("state", JSONObject().put("state", "connecting"))
        connect(promptOverride != null)
    }

    fun stop() {
        if (!running.getAndSet(false)) return
        try { ws?.close(1000, "bye") } catch (_: Exception) {}
        ws = null
        stopAudio()
        emit("state", JSONObject().put("state", "ended"))
    }

    @Volatile private var lastState = ""

    private fun emit(type: String, data: JSONObject) {
        if (type == "state") {
            val st = data.optString("state")
            if (st == lastState) return
            lastState = st
        }
        try { onEvent(type, data) } catch (e: Exception) { Log.w(tag, "emit: $e") }
    }

    private fun connect(withOverride: Boolean) {
        opened = false
        val attempt = ++attempts
        // Wächter: kommt nach 8 Sekunden keine Antwort, ohne Extras nochmal bzw. Fehler anzeigen
        Thread({
            Thread.sleep(8000)
            if (running.get() && !opened && attempt == attempts) {
                Log.w(tag, "timeout (override=$withOverride)")
                try { ws?.cancel() } catch (_: Exception) {}
                retryOrEnd(withOverride, "keine Antwort vom Server", attempt)
            }
        }, "jarvis-watchdog").start()
        val req = Request.Builder()
            .url("wss://api.elevenlabs.io/v1/convai/conversation?agent_id=$agentId")
            .build()
        ws = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (attempt != attempts) return
                val init = JSONObject().put("type", "conversation_initiation_client_data")
                if (withOverride && promptOverride != null) {
                    init.put("conversation_config_override", JSONObject().put("agent",
                        JSONObject()
                            .put("prompt", JSONObject().put("prompt", promptOverride))
                            .put("language", "de")))
                }
                webSocket.send(init.toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (attempt != attempts) return
                try { handle(webSocket, JSONObject(text)) } catch (e: Exception) {
                    Log.w(tag, "msg: $e")
                    emit("error", JSONObject().put("text", "Fehler: ${e.message}"))
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(tag, "failure: $t")
                if (attempt == attempts) retryOrEnd(withOverride, (t.message ?: t.javaClass.simpleName) +
                    (response?.let { " (HTTP ${it.code})" } ?: ""), attempt)
            }

            // Server beendet die Verbindung (z. B. wenn Überschreiben nicht erlaubt ist): sauber schließen
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(tag, "closing $code $reason")
                try { webSocket.close(1000, null) } catch (_: Exception) {}
                if (attempt == attempts) retryOrEnd(withOverride, "Code $code ${reason}".trim(), attempt)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(tag, "closed $code $reason")
                if (attempt == attempts) retryOrEnd(withOverride, "Code $code ${reason}".trim(), attempt)
            }
        })
    }

    /** Erlaubt der Agent kein Überschreiben, schließt er sofort – dann einmal ohne versuchen. */
    @Volatile private var attempts = 0
    @Volatile private var handled = -1

    private fun retryOrEnd(withOverride: Boolean, reason: String, attempt: Int) {
        if (!running.get()) return
        synchronized(this) {
            if (handled == attempt) return
            handled = attempt
        }
        if (!opened && withOverride && !triedWithoutOverride && !reason.contains("quota", true)) {
            triedWithoutOverride = true
            connect(false)
            return
        }
        if (!opened && (reason.contains("quota", true) || reason.contains("credits", true))) {
            emit("quota", JSONObject().put("text", reason))
            running.set(false)
            try { ws?.cancel() } catch (_: Exception) {}
            return
        }
        if (!opened) {
            val text = when {
                reason.contains("quota", true) || reason.contains("credits", true) ->
                    "Das ElevenLabs-Guthaben ist für diesen Monat aufgebraucht. Live-Gespräche gehen erst wieder, " +
                        "wenn es sich erneuert oder aufgeladen wird."
                else -> "Keine Verbindung zu Jarvis: $reason"
            }
            emit("error", JSONObject().put("text", text))
        }
        stop()
    }

    private fun handle(webSocket: WebSocket, msg: JSONObject) {
        when (msg.optString("type")) {
            "conversation_initiation_metadata" -> {
                val ev = msg.optJSONObject("conversation_initiation_metadata_event")
                val fmt = ev?.optString("agent_output_audio_format") ?: "pcm_16000"
                Regex("pcm_(\\d+)").find(fmt)?.let { outRate = it.groupValues[1].toInt() }
                opened = true
                emit("state", JSONObject().put("state", "listening"))
                try { startAudio() } catch (e: Exception) {
                    Log.w(tag, "audio: $e")
                    emit("error", JSONObject().put("text", "Mikrofon/Lautsprecher-Fehler: ${e.message}"))
                    stop()
                }
            }
            "audio" -> {
                val b64 = msg.optJSONObject("audio_event")?.optString("audio_base_64") ?: return
                if (b64.isNotEmpty()) playQueue.put(Base64.decode(b64, Base64.DEFAULT))
            }
            "ping" -> {
                val id = msg.optJSONObject("ping_event")?.opt("event_id")
                webSocket.send(JSONObject().put("type", "pong").put("event_id", id).toString())
            }
            "interruption" -> {
                playQueue.clear()
                flushRequested = true
                emit("state", JSONObject().put("state", "listening"))
            }
            "user_transcript" -> {
                val t = msg.optJSONObject("user_transcription_event")?.optString("user_transcript") ?: ""
                if (t.isNotBlank()) emit("user", JSONObject().put("text", t))
            }
            "agent_response" -> {
                val t = msg.optJSONObject("agent_response_event")?.optString("agent_response") ?: ""
                if (t.isNotBlank()) emit("agent", JSONObject().put("text", t))
            }
            "client_tool_call" -> {
                val call = msg.optJSONObject("client_tool_call") ?: return
                // Werkzeuge (PC steuern, Handy steuern) kommen in den nächsten Etappen
                webSocket.send(JSONObject()
                    .put("type", "client_tool_result")
                    .put("tool_call_id", call.optString("tool_call_id"))
                    .put("result", "Das kann ich vom Handy aus noch nicht – kommt in einem der nächsten Updates.")
                    .put("is_error", false).toString())
            }
        }
    }

    // --- Audio ---------------------------------------------------------------------------------
    private fun useSpeaker() = try { useSpeakerInner() } catch (e: Exception) { Log.w(tag, "speaker: $e") }

    private fun useSpeakerInner() {
        audio.mode = AudioManager.MODE_IN_COMMUNICATION
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val speaker = audio.availableCommunicationDevices.firstOrNull {
                it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
            }
            // Kopfhörer/Bluetooth haben Vorrang, sonst Lautsprecher statt Hörmuschel
            val headset = audio.availableCommunicationDevices.firstOrNull {
                it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || it.type == AudioDeviceInfo.TYPE_WIRED_HEADSET ||
                    it.type == AudioDeviceInfo.TYPE_BLE_HEADSET || it.type == AudioDeviceInfo.TYPE_USB_HEADSET
            }
            (headset ?: speaker)?.let { audio.setCommunicationDevice(it) }
        } else {
            @Suppress("DEPRECATION")
            audio.isSpeakerphoneOn = true
        }
    }

    @SuppressLint("MissingPermission")
    private fun startAudio() {
        useSpeaker()
        val inRate = 16000
        val minIn = AudioRecord.getMinBufferSize(inRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, inRate,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minIn, 6400))
        record = rec
        try {
            if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(rec.audioSessionId)?.enabled = true
            if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(rec.audioSessionId)?.enabled = true
        } catch (e: Exception) { Log.w(tag, "fx: $e") }

        val minOut = AudioTrack.getMinBufferSize(outRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val tr = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setAudioFormat(AudioFormat.Builder()
                .setSampleRate(outRate)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
            .setBufferSizeInBytes(maxOf(minOut, outRate))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        track = tr
        tr.play()
        rec.startRecording()

        Thread({
            val buf = ByteArray(3200) // 100 ms
            while (running.get() && record != null) {
                val n = rec.read(buf, 0, buf.size)
                if (n > 0) {
                    val chunk = if (n == buf.size) buf else buf.copyOf(n)
                    val b64 = Base64.encodeToString(chunk, Base64.NO_WRAP)
                    ws?.send("{\"user_audio_chunk\":\"$b64\"}")
                    level("mic", chunk)
                }
            }
        }, "jarvis-mic").start()

        Thread({
            while (running.get() && track != null) {
                val pcm = playQueue.poll(100, TimeUnit.MILLISECONDS)
                if (flushRequested) {
                    flushRequested = false
                    try { tr.pause(); tr.flush(); tr.play() } catch (_: Exception) {}
                }
                if (pcm == null) {
                    continue
                }
                emit("state", JSONObject().put("state", "speaking"))
                var off = 0
                while (off < pcm.size && running.get() && !flushRequested) {
                    val len = minOf(3200, pcm.size - off)
                    tr.write(pcm, off, len)
                    level("out", pcm.copyOfRange(off, off + len))
                    off += len
                }
                if (playQueue.isEmpty()) emit("state", JSONObject().put("state", "listening"))
            }
        }, "jarvis-play").start()
    }

    private fun level(kind: String, pcm: ByteArray) {
        val now = System.currentTimeMillis()
        if (now - lastLevelSent < 70) return
        lastLevelSent = now
        var sum = 0.0
        var i = 0
        var count = 0
        while (i + 1 < pcm.size) {
            val s = ((pcm[i + 1].toInt() shl 8) or (pcm[i].toInt() and 0xff)).toShort().toDouble()
            sum += s * s
            i += 8
            count++
        }
        val rms = if (count > 0) sqrt(sum / count) else 0.0
        emit("level", JSONObject().put("kind", kind).put("value", minOf(1.0, rms / 5000.0)))
    }

    private fun stopAudio() {
        try { record?.stop() } catch (_: Exception) {}
        try { record?.release() } catch (_: Exception) {}
        record = null
        try { track?.stop() } catch (_: Exception) {}
        try { track?.release() } catch (_: Exception) {}
        track = null
        playQueue.clear()
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) audio.clearCommunicationDevice()
            audio.mode = AudioManager.MODE_NORMAL
        } catch (_: Exception) {}
    }
}
