package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Dazulernen bei Vorschlägen: Was du immer wieder ignorierst, schlägt Jarvis nicht mehr vor.
 * Jede Art (z. B. "bahn" = Bahn bei Regen, "schlaf_tipp", "schrank") merkt sich, ob du darauf eingegangen bist.
 * 5× hintereinander nicht genutzt -> 14 Tage Pause (danach einmal neu probieren, beim nächsten Mal 30 Tage).
 * In den Einstellungen (Dazulernen) siehst du, was pausiert ist, und kannst alles wieder anmachen.
 */
object Vorschlag {
    private const val LIMIT = 5
    val NAMES = mapOf("bahn" to "Bahn bei Regen vorschlagen", "schlaf_tipp" to "Schlafens-Hinweis nachts", "schrank" to "Frage nach den Klamotten",
        "pc_offer" to "Angebote am PC (Rückblick vorlesen)", "rueckblick" to "Wochenrückblick", "halt" to "Zwischenstopp vorschlagen")

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    @Synchronized private fun load(ctx: Context): JSONObject = try { JSONObject(prefs(ctx).getString("vorschlag", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
    @Synchronized private fun save(ctx: Context, o: JSONObject) { prefs(ctx).edit().putString("vorschlag", o.toString()).apply() }
    private fun k(o: JSONObject, kind: String): JSONObject = o.optJSONObject(kind) ?: JSONObject().put("log", JSONArray()).also { o.put(kind, it) }

    /** Jarvis hat das gerade vorgeschlagen (id = Mitteilungs-ID, wenn es eine gibt). */
    @Synchronized fun shown(ctx: Context, kind: String, id: String = "") {
        val o = load(ctx); val e = k(o, kind); val log = e.optJSONArray("log") ?: JSONArray()
        log.put(JSONObject().put("t", System.currentTimeMillis()).put("id", id).put("used", false))
        while (log.length() > 12) log.remove(0)
        e.put("log", log)
        // Pause fällig? (die letzten 5 seit dem letzten Neustart der Art alle ignoriert)
        val since = e.optLong("since")
        val recent = (0 until log.length()).mapNotNull { log.optJSONObject(it) }.filter { it.optLong("t") >= since }.takeLast(LIMIT)
        if (recent.size >= LIMIT && recent.none { it.optBoolean("used") }) {
            val n = e.optInt("pausen") + 1
            val until = System.currentTimeMillis() + (if (n >= 2) 30L else 14L) * 86_400_000L
            e.put("pause_bis", until).put("pausen", n).put("since", until)
            save(ctx, o)
            try {
                val name = NAMES[kind] ?: kind
                Feed.add(ctx, "test", "Dazugelernt", name, "Du bist auf „$name“ die letzten $LIMIT Male nicht eingegangen – ich lass das erstmal " +
                    "${if (n >= 2) "einen Monat" else "zwei Wochen"} weg. In den Einstellungen unter Dazulernen kannst du es wieder anmachen.")
            } catch (_: Exception) {}
            return
        }
        save(ctx, o)
    }

    /** Du bist darauf eingegangen (Mitteilung geöffnet, Knopf gedrückt, Bahn genommen …). */
    @Synchronized fun used(ctx: Context, kind: String) {
        val o = load(ctx); val e = o.optJSONObject(kind) ?: return
        val log = e.optJSONArray("log") ?: return
        for (i in log.length() - 1 downTo 0) { val x = log.optJSONObject(i) ?: continue; if (!x.optBoolean("used")) { x.put("used", true); break } }
        e.put("pausen", 0); save(ctx, o)
    }

    /** Mitteilung mit dieser ID wurde geöffnet -> die passende Art zählt als genutzt. */
    @Synchronized fun usedFeed(ctx: Context, id: String) {
        if (id.isBlank()) return
        val o = load(ctx)
        for (kind in o.keys().asSequence().toList()) {
            val log = o.optJSONObject(kind)?.optJSONArray("log") ?: continue
            for (i in 0 until log.length()) { val x = log.optJSONObject(i) ?: continue
                if (x.optString("id") == id && !x.optBoolean("used")) { x.put("used", true); o.optJSONObject(kind)?.put("pausen", 0); save(ctx, o); return } }
        }
    }

    /** Darf Jarvis das gerade vorschlagen? */
    fun allowed(ctx: Context, kind: String): Boolean = load(ctx).optJSONObject(kind)?.optLong("pause_bis")?.let { it < System.currentTimeMillis() } ?: true

    /** Für die Einstellungen: was gerade pausiert ist. */
    fun paused(ctx: Context): String {
        val o = load(ctx); val now = System.currentTimeMillis()
        val l = o.keys().asSequence().mapNotNull { kind -> o.optJSONObject(kind)?.optLong("pause_bis")?.takeIf { it > now }?.let { kind to it } }.toList()
        if (l.isEmpty()) return "Nichts pausiert – du nutzt alles, was ich vorschlage."
        return "Pausiert, weil du nicht drauf eingehst: " + l.joinToString(", ") { (kind, t) -> "${NAMES[kind] ?: kind} (noch ${(t - now) / 86_400_000L + 1} Tage)" } + "."
    }

    fun reset(ctx: Context) {
        val o = load(ctx)
        for (kind in o.keys().asSequence().toList()) o.optJSONObject(kind)?.put("pause_bis", 0L)?.put("pausen", 0)?.put("since", System.currentTimeMillis())
        save(ctx, o)
    }
}
