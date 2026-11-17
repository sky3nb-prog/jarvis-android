package de.skyler.jarvis

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

/**
 * Mitteilung vorlesen, Punkt für Punkt. "Friday, weiter" (oder der Knopf) springt zum nächsten Punkt, "stopp" hört auf.
 * Meldet der Seite, welcher Punkt gerade dran ist (Ereignis "read_pos"), damit er hervorgehoben wird.
 */
object ReadAloud {
    @Volatile var active = false
    private var tts: TextToSpeech? = null
    private var ready = false
    private var parts: List<String> = emptyList()
    private var idx = 0

    fun start(ctx: Context, json: String) {
        val a = try { JSONArray(json) } catch (_: Exception) { JSONArray() }
        parts = (0 until a.length()).map { a.optString(it) }
        idx = 0; active = parts.isNotEmpty()
        if (!active) return
        app = ctx.applicationContext
        if (PiperPhone.active(ctx)) { speak(); return }   // gleiche Stimme wie am PC
        if (tts == null) {
            tts = TextToSpeech(ctx.applicationContext) { st ->
                ready = st == TextToSpeech.SUCCESS
                if (ready) { voice(ctx); listen(); speak() }
            }
        } else { voice(ctx); speak() }
    }

    /** Gleiche Stimme wie Jarvis (Einstellungen → Stimme), auch die Online-Stimme des Handys. */
    private fun voice(ctx: Context) {
        val t = tts ?: return
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        t.language = Locale.GERMANY
        val voices = try { t.voices?.filter { it.locale.language == "de" } ?: emptyList() } catch (_: Exception) { emptyList() }
        val wanted = p.getString("tts_voice", "") ?: ""
        (voices.firstOrNull { it.name == wanted }
            ?: voices.firstOrNull { it.isNetworkConnectionRequired && it.name.contains("male", true) && !it.name.contains("female", true) }
            ?: voices.firstOrNull { !it.isNetworkConnectionRequired && it.name.contains("male", true) && !it.name.contains("female", true) })?.let { t.voice = it }
        t.setSpeechRate(p.getFloat("tts_rate", 1.05f))
        t.setPitch(0.9f)
    }

    private fun listen() {
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) {}
            override fun onDone(id: String?) { if (id == "p$idx" && active) { idx++; speak() } }
            @Deprecated("Deprecated in Java") override fun onError(id: String?) {}
        })
    }

    private var app: Context? = null
    private var myRun = 0

    private fun speak() {
        val c = app
        if (c != null && PiperPhone.active(c)) {
            if (idx >= parts.size) { stop(); return }
            Bus.emit("read_pos", JSONObject().put("i", idx))
            val run = ++myRun; val i = idx
            val rate = c.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getFloat("tts_rate", 1.05f)
            if (PiperPhone.speak(c, parts[idx], rate) { if (active && run == myRun && idx == i) { idx++; speak() } }) return
        }
        val t = tts ?: return
        if (!ready) return
        if (idx >= parts.size) { stop(); return }
        Bus.emit("read_pos", JSONObject().put("i", idx))
        t.speak(parts[idx], TextToSpeech.QUEUE_FLUSH, null, "p$idx")
    }

    fun next() { if (!active) return; myRun++; try { PiperPhone.stop() } catch (_: Throwable) {}; idx++; speak() }

    fun stop() {
        active = false
        myRun++; try { PiperPhone.stop() } catch (_: Throwable) {}
        try { tts?.stop() } catch (_: Exception) {}
        Bus.emit("read_end", JSONObject())
    }
}
