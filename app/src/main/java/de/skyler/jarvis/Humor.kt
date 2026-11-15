package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Lernt, welcher Humor bei Skyler ankommt: Reagiert er auf einen Spruch mit "haha", "lol", 😂 … merkt sich Jarvis den Spruch
 * als "kam gut an"; mit "nicht lustig", "lass das", "hör auf" … als "kam nicht an". Die letzten Beispiele stehen im Prompt.
 */
object Humor {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    private val LAUGH = Regex("(?i)\\b(haha+|hehe+|lol|lmao|xd)\\b|😂|🤣|😆|😄|witzig|lustig(?! ist das nicht)|der war gut|geil|nice one|ehrenmann")
    private val NOPE = Regex("(?i)nicht (so )?lustig|lass (das|die witze|den sarkasmus)|hör auf (mit|zu)|kein(e)? (witz|sarkasmus)|nervt|cringe|sei mal ernst|ernsthaft jetzt")

    fun react(ctx: Context, userText: String, history: JSONArray) {
        val good = LAUGH.containsMatchIn(userText); val bad = NOPE.containsMatchIn(userText)
        if (!good && !bad) return
        var last = ""
        for (i in history.length() - 1 downTo 0) { val o = history.optJSONObject(i) ?: continue; if (o.optString("role") == "assistant") { last = o.optString("content"); break } }
        last = try { JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(last)?.value ?: "").let { j ->
            j.optJSONArray("actions")?.let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it)?.optString("text")?.takeIf { t -> t.isNotBlank() } }.joinToString(" ") } ?: j.optString("say") }
        } catch (_: Exception) { last }.ifBlank { last }.take(160)
        if (last.isBlank()) return
        val key = if (good) "humor_gut" else "humor_schlecht"
        val a = try { JSONArray(prefs(ctx).getString(key, "[]")) } catch (_: Exception) { JSONArray() }
        a.put(last); while (a.length() > 8) a.remove(0)
        prefs(ctx).edit().putString(key, a.toString()).apply()
    }

    fun prompt(ctx: Context): String {
        fun l(k: String) = try { JSONArray(prefs(ctx).getString(k, "[]")).let { a -> (0 until a.length()).map { a.optString(it) } } } catch (_: Exception) { emptyList() }
        val g = l("humor_gut").takeLast(4); val b = l("humor_schlecht").takeLast(4)
        if (g.isEmpty() && b.isEmpty()) return ""
        return "Humor, der bei ihm ankommt (mehr davon): " + g.joinToString(" | ").ifBlank { "–" } +
            ". Kam nicht gut an (so nicht mehr): " + b.joinToString(" | ").ifBlank { "–" } + "."
    }
}
