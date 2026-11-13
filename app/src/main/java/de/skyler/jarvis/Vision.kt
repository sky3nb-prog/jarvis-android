package de.skyler.jarvis

import android.content.Context
import android.graphics.Bitmap
import android.util.Base64
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

/**
 * Bilder verstehen ("Schau mal hier"): Gemini (eigener Schlüssel in den Einstellungen), sonst ein Bild-Modell bei Groq,
 * falls es dort gerade eins gibt. Das Bild geht nur zur Auswertung raus und wird nicht gespeichert.
 */
object Vision {
    private val http = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()

    private const val SYS = "Du bist Jarvis, der persönliche Assistent des Nutzers. Du siehst ein Bildschirmfoto (oder Foto) von ihm. " +
        "Beantworte seine Frage dazu auf Deutsch, gesprochen klingend, kurz (2 bis 5 Sätze), konkret auf das bezogen, was zu sehen ist. " +
        "Wenn er nichts Bestimmtes fragt, sag knapp, was zu sehen ist und was daran wichtig sein könnte. " +
        "Lies keine Passwörter, Kontonummern oder Codes vor, auch wenn sie zu sehen sind."

    private fun jpeg(b: Bitmap): String {
        val max = 1400
        val s = if (b.width > max || b.height > max) {
            val f = max.toFloat() / maxOf(b.width, b.height)
            Bitmap.createScaledBitmap(b, (b.width * f).toInt(), (b.height * f).toInt(), true)
        } else b
        val out = ByteArrayOutputStream()
        s.compress(Bitmap.CompressFormat.JPEG, 80, out)
        return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }

    fun ask(ctx: Context, bmp: Bitmap, question: String): String {
        val img = jpeg(bmp)
        val q = question.ifBlank { "Was siehst du hier?" }
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val gem = (p.getString("gemini_key", "") ?: "").trim()
        if (gem.isNotBlank()) {
            for (model in listOf("gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest")) {
                try {
                    val body = JSONObject()
                        .put("systemInstruction", JSONObject().put("parts", JSONArray().put(JSONObject().put("text", SYS))))
                        .put("contents", JSONArray().put(JSONObject().put("role", "user").put("parts", JSONArray()
                            .put(JSONObject().put("inline_data", JSONObject().put("mime_type", "image/jpeg").put("data", img)))
                            .put(JSONObject().put("text", q)))))
                        .put("generationConfig", JSONObject().put("maxOutputTokens", 2000).put("temperature", 0.5))
                    val txt = http.newCall(Request.Builder().url("https://generativelanguage.googleapis.com/v1beta/models/$model:generateContent")
                        .header("x-goog-api-key", gem).post(body.toString().toRequestBody("application/json".toMediaType())).build())
                        .execute().use { if (it.isSuccessful) it.body?.string() else null } ?: continue
                    val parts = JSONObject(txt).optJSONArray("candidates")?.optJSONObject(0)?.optJSONObject("content")?.optJSONArray("parts") ?: continue
                    val ans = (0 until parts.length()).joinToString("") { parts.optJSONObject(it)?.optString("text") ?: "" }.trim()
                    if (ans.isNotBlank()) return ans.replace(Regex("[*#`]"), "")
                } catch (_: Exception) {}
            }
        }
        val groq = (p.getString("groq_key", "") ?: "").trim()
        val vm = if (groq.isNotBlank()) Groq.visionModel(groq) else null
        if (vm != null) try {
            val content = JSONArray().put(JSONObject().put("type", "text").put("text", q))
                .put(JSONObject().put("type", "image_url").put("image_url", JSONObject().put("url", "data:image/jpeg;base64,$img")))
            val body = JSONObject().put("model", vm).put("max_tokens", 700).put("messages", JSONArray()
                .put(JSONObject().put("role", "system").put("content", SYS))
                .put(JSONObject().put("role", "user").put("content", content)))
            val txt = http.newCall(Request.Builder().url("https://api.groq.com/openai/v1/chat/completions").header("Authorization", "Bearer $groq")
                .post(body.toString().toRequestBody("application/json".toMediaType())).build()).execute().use { if (it.isSuccessful) it.body?.string() else null }
            val ans = txt?.let { JSONObject(it).optJSONArray("choices")?.optJSONObject(0)?.optJSONObject("message")?.optString("content") }?.trim()
            if (!ans.isNullOrBlank()) return ans.replace(Regex("[*#`]"), "")
        } catch (_: Exception) {}
        return if (gem.isBlank()) "Zum Anschauen brauche ich einen Gemini-Schlüssel. Trag ihn in den Einstellungen unter Allgemein ein, " +
            "kostenlos auf aistudio.google.com." else "Ich konnte das Bild gerade nicht auswerten."
    }

    /** "Schau mal hier" am Handy: Bildschirmfoto + Frage. */
    fun screen(ctx: Context, question: String): String {
        if (!ScreenService.enabled()) return "Dafür musst du einmal den Bildschirm-Zugriff einschalten: Einstellungen, Allgemein, " +
            "Bildschirm-Zugriff einrichten, dann Jarvis – Schau mal hier aktivieren."
        val b = ScreenService.capture() ?: return "Das Bildschirmfoto hat nicht geklappt."
        return ask(ctx, b, question)
    }
}
