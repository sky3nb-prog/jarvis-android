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
    // Was Whisper bei Stille oder Rauschen gern "erfindet" -> wegwerfen
    private val hallucinations = Regex("(untertitel|amara\\.org|vielen dank für(s)? zuschauen|tschüss und bis zum nächsten mal|" +
        "copyright|swr \\d|zdf|ard|abonnier|danke fürs zuhören)", RegexOption.IGNORE_CASE)

    fun transcribe(key: String, pcm: ByteArray, prompt: String = "Jarvis, öffne WhatsApp. Jarvis, wie ist das Wetter?"): String {
        val wav = wav(pcm, 16000)
        // erst das genaueste Modell (large-v3), bei Problemen das schnellere
        for (model in listOf("whisper-large-v3", "whisper-large-v3-turbo")) {
            val body = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("model", model)
                .addFormDataPart("language", "de")
                .addFormDataPart("temperature", "0")
                .addFormDataPart("prompt", prompt)
                .addFormDataPart("response_format", "verbose_json")
                .addFormDataPart("file", "sprache.wav", wav.toRequestBody("audio/wav".toMediaType()))
                .build()
            val req = Request.Builder().url("https://api.groq.com/openai/v1/audio/transcriptions")
                .header("Authorization", "Bearer $key").post(body).build()
            http.newCall(req).execute().use { r ->
                val txt = r.body?.string() ?: ""
                if (r.code == 401) throw KeyError("Der Groq-Schlüssel stimmt nicht.")
                if (r.isSuccessful) {
                    val o = JSONObject(txt)
                    val segs = o.optJSONArray("segments")
                    // Teile, bei denen Whisper selbst sicher ist, dass niemand spricht, weglassen
                    val text = if (segs != null && segs.length() > 0) {
                        (0 until segs.length()).map { segs.getJSONObject(it) }
                            .filter { it.optDouble("no_speech_prob", 0.0) < 0.6 && it.optDouble("avg_logprob", 0.0) > -1.0 }
                            .joinToString(" ") { it.optString("text").trim() }
                    } else o.optString("text")
                    val t = text.trim()
                    return if (hallucinations.containsMatchIn(t)) "" else t
                }
                if (r.code != 404 && r.code != 400) throw RuntimeException("Groq-Spracherkennung ${r.code}")
            }
        }
        return ""
    }

    fun chat(key: String, messages: JSONArray, maxTokens: Int = 400, json: Boolean = false): String {
        var last: Exception? = null
        for (model in chatModels) {
            val body = JSONObject().put("model", model).put("messages", messages).put("max_tokens", maxTokens)
                .put("temperature", 0.6)
            if (json && model.startsWith("llama")) body.put("response_format", JSONObject().put("type", "json_object"))
            val req = Request.Builder().url("https://api.groq.com/openai/v1/chat/completions")
                .header("Authorization", "Bearer $key")
                .post(body.toString().toRequestBody("application/json".toMediaType())).build()
            try {
                http.newCall(req).execute().use { r ->
                    val txt = r.body?.string() ?: ""
                    if (r.code == 401) throw KeyError("Der Groq-Schlüssel stimmt nicht.")
                    if (!r.isSuccessful) throw RuntimeException("Groq ${r.code}")
                    val content = JSONObject(txt).getJSONArray("choices").getJSONObject(0)
                        .getJSONObject("message").optString("content")
                    val clean = content.replace(Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL), "").trim()
                    if (clean.isNotEmpty()) return clean
                }
            } catch (e: KeyError) {
                throw e
            } catch (e: Exception) {
                last = e
            }
        }
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
