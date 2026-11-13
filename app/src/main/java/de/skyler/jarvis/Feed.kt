package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Mitteilungen: alles, was Jarvis von sich aus meldet (Fahrt-Briefing, Heimweg, Morgen-/Abend-Briefing,
 * Wochenrückblick, Ankunft, Anrufe, Erinnerungen) – geordnet und schön aufbereitet in der App.
 * Tippst du auf die Benachrichtigung, öffnet sich genau diese Mitteilung. Bleibt nur auf dem Handy (30 Tage).
 */
object Feed {
    private fun file(ctx: Context) = File(ctx.filesDir, "mitteilungen.json")

    @Synchronized
    private fun load(ctx: Context): JSONArray = try { JSONArray(file(ctx).readText()) } catch (_: Exception) { JSONArray() }

    /** kind: fahrt, heimweg, morgen, abend, woche, ankunft, anruf, erinnerung, test. Gibt die ID zurück. */
    @Synchronized
    fun add(ctx: Context, kind: String, title: String, sub: String, text: String, data: JSONObject = JSONObject()): String {
        val now = System.currentTimeMillis()
        val id = "m$now"
        val a = load(ctx)
        a.put(JSONObject().put("id", id).put("ts", now).put("kind", kind).put("title", title).put("sub", sub).put("text", text).put("data", data))
        val keep = JSONArray()
        for (i in 0 until a.length()) a.optJSONObject(i)?.let { if (now - it.optLong("ts") < 30 * 86_400_000L) keep.put(it) }
        while (keep.length() > 200) keep.remove(0)
        try { file(ctx).writeText(keep.toString()) } catch (_: Exception) {}
        return id
    }

    /** Neueste zuerst, ohne die Detail-Daten (für die Liste). */
    fun list(ctx: Context): JSONArray {
        val a = load(ctx); val out = JSONArray()
        for (i in a.length() - 1 downTo 0) a.optJSONObject(i)?.let {
            out.put(JSONObject().put("id", it.optString("id")).put("ts", it.optLong("ts")).put("kind", it.optString("kind"))
                .put("title", it.optString("title")).put("sub", it.optString("sub")))
        }
        return out
    }

    fun get(ctx: Context, id: String): JSONObject? {
        val a = load(ctx)
        for (i in 0 until a.length()) a.optJSONObject(i)?.let { if (it.optString("id") == id) return it }
        return null
    }
}
