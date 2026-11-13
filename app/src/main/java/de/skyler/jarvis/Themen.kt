package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Was dich interessiert – lernt mit der Zeit immer besser:
 * - was du Jarvis fragst und suchen lässt
 * - welche Meldungen du auf der Lage-Seite antippst ("mehr davon" / "weniger" zählt besonders)
 * - was du auf YouTube schaust und welche Musik du hörst
 * - was Jarvis über dich weiß (Gedächtnis) und Themen, die du selbst einträgst
 * Daraus macht Groq einmal am Tag (oder nach genug Neuem) eine Liste von Themen mit Suchbegriffen.
 */
object Themen {
    private const val KEEP_DAYS = 60
    private fun file(ctx: Context) = File(ctx.filesDir, "themen_log.json")
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    @Synchronized
    private fun log(ctx: Context): JSONArray = try { JSONArray(file(ctx).readText()) } catch (_: Exception) { JSONArray() }

    /** Ein Hinweis auf ein Interesse. kind: frage, klick, mehr, weniger */
    @Synchronized
    fun note(ctx: Context, kind: String, text: String) {
        val t = text.trim().take(200); if (t.length < 3) return
        val arr = log(ctx); val now = System.currentTimeMillis()
        arr.put(JSONObject().put("ts", now).put("k", kind).put("t", t))
        val keep = JSONArray(); val cut = now - KEEP_DAYS * 86_400_000L
        for (i in 0 until arr.length()) arr.optJSONObject(i)?.let { if (it.optLong("ts") >= cut) keep.put(it) }
        while (keep.length() > 600) keep.remove(0)
        try { file(ctx).writeText(keep.toString()) } catch (_: Exception) {}
        prefs(ctx).edit().putInt("themen_neu", prefs(ctx).getInt("themen_neu", 0) + if (kind == "frage") 1 else 2).apply()
    }

    /** Aktuelle Themen: [{name, suche, gewicht}] – gelernt + selbst eingetragen, ohne die abgewählten. */
    fun list(ctx: Context): List<JSONObject> {
        val p = prefs(ctx)
        val gone = gone(ctx)
        val out = ArrayList<JSONObject>()
        for (m in manual(ctx)) out.add(JSONObject().put("name", m).put("suche", m).put("gewicht", 3).put("selbst", true))
        val arr = try { JSONArray(p.getString("themen_json", "[]")) } catch (_: Exception) { JSONArray() }
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val n = o.optString("name"); if (n.isBlank() || n.lowercase() in gone || out.any { it.optString("name").equals(n, true) }) continue
            out.add(o)
        }
        return out
    }

    fun manual(ctx: Context): List<String> = (prefs(ctx).getString("themen_selbst", "") ?: "").split(",").map { it.trim() }.filter { it.isNotEmpty() }
    private fun gone(ctx: Context): Set<String> = (prefs(ctx).getString("themen_weg", "") ?: "").split("|").map { it.trim().lowercase() }.filter { it.isNotEmpty() }.toSet()

    /** Thema abwählen (kommt nicht wieder, bis du es selbst einträgst) */
    fun remove(ctx: Context, name: String) {
        val p = prefs(ctx)
        val g = gone(ctx) + name.lowercase()
        val m = manual(ctx).filterNot { it.equals(name, true) }
        p.edit().putString("themen_weg", g.joinToString("|")).putString("themen_selbst", m.joinToString(", ")).apply()
        note(ctx, "weniger", "Thema: $name")
    }

    fun setManual(ctx: Context, csv: String) {
        val list = csv.split(",").map { it.trim() }.filter { it.isNotEmpty() }
        val g = gone(ctx) - list.map { it.lowercase() }.toSet()
        prefs(ctx).edit().putString("themen_selbst", list.joinToString(", ")).putString("themen_weg", g.joinToString("|")).apply()
    }

    /** Kurz für die KI: "Gaming (Euro Truck Simulator), KI, VfB Stuttgart" */
    fun summary(ctx: Context): String = list(ctx).take(10).joinToString(", ") { it.optString("name") }

    /** Einmal am Tag (oder wenn viel Neues dazukam) die Themen neu ableiten. */
    fun refresh(ctx: Context, key: String, force: Boolean = false) {
        val p = prefs(ctx)
        val age = System.currentTimeMillis() - p.getLong("themen_zeit", 0)
        if (!force && age < 24 * 3600_000L && p.getInt("themen_neu", 0) < 15) return
        if (!force && age < 30 * 60_000L) return
        p.edit().putLong("themen_zeit", System.currentTimeMillis()).apply()
        try {
            val arr = log(ctx)
            val recent = (maxOf(0, arr.length() - 120) until arr.length()).mapNotNull { arr.optJSONObject(it) }
            val fragen = recent.filter { it.optString("k") == "frage" }.takeLast(60).joinToString("\n") { "- " + it.optString("t") }
            val klicks = recent.filter { it.optString("k") != "frage" }.takeLast(50).joinToString("\n") { "- [" + it.optString("k") + "] " + it.optString("t") }
            val yt = Interests.top(ctx, "video", 8).joinToString(", ") { it.first }
            val mu = p.getString("music_genres", "") ?: ""
            val mem = try { Memory.facts(ctx).takeLast(40).joinToString("\n") { "- $it" } } catch (_: Exception) { "" }
            val old = p.getString("themen_json", "[]")
            val sys = """Du lernst, wofür sich der Nutzer interessiert, damit sein Assistent Jarvis ihm passende Nachrichten zeigt.
Leite aus den Hinweisen 5 bis 10 Themen ab, die ihn wirklich interessieren (Hobbys, Spiele, Sport/Vereine, Technik, Marken, Orte, Berufliches).
Gewichte: [mehr] und [klick] zählen viel, [weniger] heißt: dieses Thema NICHT nehmen. Fragen an Jarvis zählen mittel, YouTube/Musik zählen mittel.
Keine allgemeinen Themen wie "Nachrichten" oder "Wetter". Keine Gesundheits-, Politik- oder Religionsvorlieben ableiten, die er nicht selbst klar zeigt.
Für jedes Thema: "name" (kurz, Deutsch, z. B. "Euro Truck Simulator 2"), "suche" (gute Google-News-Suche, z. B. "\"Euro Truck Simulator 2\" OR ETS2"),
"gewicht" (1 bis 3). Bisherige Themen (behalte sie, wenn sie noch passen): $old
Antworte NUR mit JSON: {"themen": [ ... ]}"""
            val user = "FRAGEN AN JARVIS:\n$fragen\n\nLAGE-SEITE:\n$klicks\n\nYOUTUBE-KANÄLE: $yt\nMUSIK: $mu\n\nGEDÄCHTNIS:\n$mem"
            val raw = Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", sys))
                .put(JSONObject().put("role", "user").put("content", user)), 900, json = true)
            val obj = JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw)?.value ?: raw)
            val t = obj.optJSONArray("themen") ?: return
            val clean = JSONArray()
            for (i in 0 until minOf(10, t.length())) {
                val o = t.optJSONObject(i) ?: continue
                val n = o.optString("name").trim().take(40); if (n.isBlank()) continue
                clean.put(JSONObject().put("name", n).put("suche", o.optString("suche").ifBlank { n }.take(160)).put("gewicht", o.optInt("gewicht", 2)))
            }
            if (clean.length() > 0) p.edit().putString("themen_json", clean.toString()).putInt("themen_neu", 0).apply()
        } catch (_: Exception) {}
    }
}
