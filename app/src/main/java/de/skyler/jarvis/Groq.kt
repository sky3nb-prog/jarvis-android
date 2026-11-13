package de.skyler.jarvis

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

/** Groq (kostenlos): Whisper für Sprache -> Text (lautlos, sehr genau) und Chat für die Antworten. */
object Groq {
    private val http = OkHttpClient.Builder().callTimeout(30, TimeUnit.SECONDS).build()
    private val chatModels = listOf("llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b",
        "llama-3.1-8b-instant")

    class KeyError(msg: String) : Exception(msg)

    /** PCM 16 kHz mono 16 bit -> Text (Deutsch). */
    fun transcribe(key: String, pcm: ByteArray): String {
        val wav = wav(pcm, 16000)
        for (model in listOf("whisper-large-v3-turbo", "whisper-large-v3")) {
            val body = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("model", model)
                .addFormDataPart("language", "de")
                .addFormDataPart("temperature", "0")
                .addFormDataPart("prompt", "Jarvis, öffne WhatsApp. Jarvis, wie ist das Wetter?")
                .addFormDataPart("response_format", "json")
                .addFormDataPart("file", "sprache.wav", wav.toRequestBody("audio/wav".toMediaType()))
                .build()
            val req = Request.Builder().url("https://api.groq.com/openai/v1/audio/transcriptions")
                .header("Authorization", "Bearer $key").post(body).build()
            http.newCall(req).execute().use { r ->
                val txt = r.body?.string() ?: ""
                if (r.code == 401) throw KeyError("Der Groq-Schlüssel stimmt nicht.")
                if (r.isSuccessful) return JSONObject(txt).optString("text").trim()
                if (r.code != 404 && r.code != 400) throw RuntimeException("Groq-Spracherkennung ${r.code}")
            }
        }
        return ""
    }

    // Groq tauscht Modelle immer wieder aus: Liste einmal am Tag frisch holen, bekannte gute zuerst
    @Volatile private var live: List<String> = emptyList()
    @Volatile private var liveAt = 0L
    private val prefer = listOf("openai/gpt-oss-120b", "llama-3.3-70b-versatile", "moonshotai/kimi-k2", "qwen/", "meta-llama/llama-4",
        "openai/gpt-oss-20b", "llama-3.1-8b-instant")

    private fun models(key: String): List<String> {
        if (live.isNotEmpty() && System.currentTimeMillis() - liveAt < 24 * 3600_000L) return live
        try {
            val r = http.newCall(Request.Builder().url("https://api.groq.com/openai/v1/models").header("Authorization", "Bearer $key").build()).execute()
            r.use {
                if (it.isSuccessful) {
                    val d = JSONObject(it.body?.string() ?: "{}").optJSONArray("data") ?: JSONArray()
                    val ids = (0 until d.length()).mapNotNull { k -> d.optJSONObject(k)?.optString("id") }
                        .filter { id -> !Regex("whisper|guard|tts|playai|orpheus|prompt|compound|allam", RegexOption.IGNORE_CASE).containsMatchIn(id) }
                    if (ids.isNotEmpty()) {
                        live = ids.sortedBy { id -> prefer.indexOfFirst { p -> id.startsWith(p) }.let { x -> if (x < 0) 99 else x } }
                        liveAt = System.currentTimeMillis()
                    }
                }
            }
        } catch (_: Exception) {}
        return live.ifEmpty { chatModels }
    }

    private fun thinks(model: String) = model.contains("gpt-oss") || model.contains("qwen") || model.contains("deepseek")

    fun chat(key: String, messages: JSONArray, maxTokens: Int = 400, json: Boolean = false): String {
        var last: Exception? = null
        for (model in models(key).take(5)) {
            for (withFormat in if (json) listOf(true, false) else listOf(false)) {
                // Modelle, die erst nachdenken, brauchen Platz dafür, sonst bleibt die Antwort leer
                val body = JSONObject().put("model", model).put("messages", messages)
                    .put("max_tokens", if (thinks(model)) maxTokens + 2000 else maxTokens).put("temperature", 0.6)
                if (model.contains("gpt-oss")) body.put("reasoning_effort", "low")
                if (model.contains("qwen")) body.put("reasoning_effort", "none")
                if (withFormat) body.put("response_format", JSONObject().put("type", "json_object"))
                val req = Request.Builder().url("https://api.groq.com/openai/v1/chat/completions")
                    .header("Authorization", "Bearer $key")
                    .post(body.toString().toRequestBody("application/json".toMediaType())).build()
                try {
                    http.newCall(req).execute().use { r ->
                        val txt = r.body?.string() ?: ""
                        if (r.code == 401) throw KeyError("Der Groq-Schlüssel stimmt nicht.")
                        if (r.code == 400 && withFormat) throw IllegalStateException("format")   // gleich ohne JSON-Vorgabe nochmal
                        if (!r.isSuccessful) throw RuntimeException("Groq ${r.code} bei $model")
                        val content = JSONObject(txt).getJSONArray("choices").getJSONObject(0)
                            .getJSONObject("message").optString("content")
                        val clean = content.replace(Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL), "").trim()
                        if (clean.isNotEmpty()) return clean
                        throw RuntimeException("leere Antwort von $model")
                    }
                } catch (e: KeyError) {
                    throw e
                } catch (e: IllegalStateException) {
                    continue
                } catch (e: Exception) {
                    last = e
                    break   // nächstes Modell
                }
            }
        }
        if (live.isNotEmpty()) liveAt = 0L   // beim nächsten Mal die Liste neu holen
        throw last ?: RuntimeException("keine Antwort")
    }

    private fun wav(pcm: ByteArray, rate: Int): ByteArray {
        val out = ByteArrayOutputStream(pcm.size + 44)
        fun i32(v: Int) { out.write(v and 255); out.write(v shr 8 and 255); out.write(v shr 16 and 255); out.write(v shr 24 and 255) }
        fun i16(v: Int) { out.write(v and 255); out.write(v shr 8 and 255) }
        out.write("RIFF".toByteArray()); i32(36 + pcm.size); out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); i32(16); i16(1); i16(1); i32(rate); i32(rate * 2); i16(2); i16(16)
        out.write("data".toByteArray()); i32(pcm.size); out.write(pcm)
        return out.toByteArray()
    }
}
