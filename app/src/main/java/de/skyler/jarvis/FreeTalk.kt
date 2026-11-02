package de.skyler.jarvis

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Kostenloses Gespräch ohne ElevenLabs:
 * Spracherkennung des Handys -> Groq (kostenlos, sehr schnell) -> Stimme des Handys. Läuft im Kreis, bis
 * "Tschüss" kommt, die Kugel angetippt wird oder eine Weile niemand redet.
 */
class FreeTalk(
    private val context: Context,
    private val groqKey: String,
    private val systemPrompt: String,
    private val voiceName: String?,
    private val onEvent: (type: String, data: JSONObject) -> Unit,
) {
    private val tag = "JarvisFree"
    private val main = Handler(Looper.getMainLooper())
    private val http = OkHttpClient.Builder().callTimeout(25, TimeUnit.SECONDS).build()
    private var recognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    @Volatile var isRunning = false
        private set
    private val history = JSONArray()
    private var lastHeard = System.currentTimeMillis()
    private var lastState = ""
    private val endWords = Regex("\\b(tschüss|tschau|ciao|bis später|bis dann|gespräch beenden|das war'?s|auflegen|ende)\\b",
        RegexOption.IGNORE_CASE)

    fun start() {
        if (isRunning) return
        isRunning = true
        state("connecting")
        tts = TextToSpeech(context) { status ->
            ttsReady = status == TextToSpeech.SUCCESS
            if (ttsReady) setupVoice()
            main.post { if (isRunning) listen() }
        }
    }

    fun stop() {
        if (!isRunning) return
        isRunning = false
        main.post {
            try { recognizer?.destroy() } catch (_: Exception) {}
            recognizer = null
            try { tts?.stop(); tts?.shutdown() } catch (_: Exception) {}
            tts = null
            state("ended")
        }
    }

    /** Laufende Antwort abbrechen (Tipp auf die Kugel während er spricht) und wieder zuhören. */
    fun interrupt() {
        if (!isRunning) return
        tts?.stop()
        main.post { listen() }
    }

    private fun emit(type: String, data: JSONObject) = try { onEvent(type, data) } catch (_: Exception) {}

    private fun state(st: String) {
        if (st == lastState) return
        lastState = st
        emit("state", JSONObject().put("state", st))
    }

    private fun setupVoice() {
        val t = tts ?: return
        t.language = Locale.GERMANY
        val voices = try { t.voices?.filter { it.locale.language == "de" } ?: emptyList() } catch (_: Exception) { emptyList() }
        val chosen: Voice? = voices.firstOrNull { it.name == voiceName }
            ?: voices.filter { !it.isNetworkConnectionRequired || it.features?.contains("networkTimeoutMs") == true }
                .firstOrNull { it.name.contains("male", true) && !it.name.contains("female", true) }
            ?: voices.firstOrNull { it.name.contains("deb") || it.name.contains("deg") }  // männliche Google-Stimmen
        chosen?.let { t.voice = it }
        t.setSpeechRate(1.05f)
        t.setPitch(0.9f)
        emit("voices", JSONObject().put("list", JSONArray(voices.map { it.name }.sorted()))
            .put("current", t.voice?.name ?: ""))
    }

    // --- Zuhören ---------------------------------------------------------------------------------
    private fun listen() {
        if (!isRunning) return
        if (System.currentTimeMillis() - lastHeard > 45_000) {
            emit("agent", JSONObject().put("text", "Ich lege mich wieder hin. Tipp auf mich, wenn du was brauchst."))
            stop()
            return
        }
        try { recognizer?.destroy() } catch (_: Exception) {}
        val r = SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = r
        r.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) = state("listening")
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {
                emit("level", JSONObject().put("kind", "mic").put("value", ((rmsdB + 2f) / 12f).coerceIn(0f, 1f)))
            }
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() = state("thinking")
            override fun onError(error: Int) {
                Log.i(tag, "recognizer error $error")
                if (!isRunning) return
                if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS) {
                    emit("error", JSONObject().put("text", "Ohne Mikrofon kann ich dich nicht hören."))
                    stop(); return
                }
                main.postDelayed({ listen() }, if (error == SpeechRecognizer.ERROR_RECOGNIZER_BUSY) 600 else 150)
            }
            override fun onResults(results: Bundle?) {
                val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim() ?: ""
                if (text.isEmpty()) { listen(); return }
                lastHeard = System.currentTimeMillis()
                emit("user", JSONObject().put("text", text))
                if (endWords.containsMatchIn(text) && text.split(" ").size <= 5) {
                    say("Bis später.") { stop() }
                    return
                }
                ask(text)
            }
            override fun onPartialResults(partial: Bundle?) {
                val t = partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull() ?: return
                if (t.isNotBlank()) emit("partial", JSONObject().put("text", t))
            }
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "de-DE")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 900L)
        }
        r.startListening(intent)
    }

    // --- Denken (Groq) -------------------------------------------------------------------------------
    private fun ask(text: String) {
        state("thinking")
        history.put(JSONObject().put("role", "user").put("content", text))
        Thread({
            val answer = try { groq() } catch (e: Exception) {
                Log.w(tag, "groq: $e")
                "Ich komme gerade nicht ins Internet. ${e.message ?: ""}".trim()
            }
            history.put(JSONObject().put("role", "assistant").put("content", answer))
            while (history.length() > 16) history.remove(0)
            emit("agent", JSONObject().put("text", answer))
            main.post { say(answer) { listen() } }
        }, "jarvis-groq").start()
    }

    private fun groq(): String {
        val models = listOf("llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant")
        var last: Exception? = null
        for (model in models) {
            val msgs = JSONArray().put(JSONObject().put("role", "system").put("content", systemPrompt))
            for (i in 0 until history.length()) msgs.put(history.get(i))
            val body = JSONObject().put("model", model).put("messages", msgs).put("max_tokens", 300).put("temperature", 0.7)
            val req = Request.Builder().url("https://api.groq.com/openai/v1/chat/completions")
                .header("Authorization", "Bearer $groqKey")
                .post(body.toString().toRequestBody("application/json".toMediaType())).build()
            try {
                http.newCall(req).execute().use { resp ->
                    val txt = resp.body?.string() ?: ""
                    if (resp.code == 401) throw IllegalStateException("Der Groq-Schlüssel stimmt nicht.")
                    if (!resp.isSuccessful) throw RuntimeException("Groq ${resp.code}")
                    val content = JSONObject(txt).getJSONArray("choices").getJSONObject(0)
                        .getJSONObject("message").optString("content")
                    val clean = content.replace(Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL), "")
                        .replace(Regex("[*#_`]"), "").trim()
                    if (clean.isNotEmpty()) return clean
                }
            } catch (e: IllegalStateException) {
                throw e
            } catch (e: Exception) {
                last = e
            }
        }
        throw last ?: RuntimeException("keine Antwort")
    }

    // --- Sprechen ----------------------------------------------------------------------------------
    private fun say(text: String, after: () -> Unit) {
        val t = tts
        if (!isRunning || t == null || !ttsReady) { after(); return }
        state("speaking")
        val id = "j" + System.nanoTime()
        t.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) { if (utteranceId == id) main.post { if (isRunning) after() } }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) { if (utteranceId == id) main.post { if (isRunning) after() } }
            override fun onStop(utteranceId: String?, interrupted: Boolean) {}
        })
        t.speak(text, TextToSpeech.QUEUE_FLUSH, null, id)
    }
}
