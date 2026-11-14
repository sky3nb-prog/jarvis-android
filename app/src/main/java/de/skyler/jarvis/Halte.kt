package de.skyler.jarvis

import android.content.Context
import android.location.Location
import android.util.Log
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Lernt, wie lange du unterwegs wo hältst (Rewe, Bäcker, Aldi …): Bleibst du außerhalb von zuhause 2 bis 90 Minuten an
 * einer Stelle, schaut er auf OpenStreetMap, welcher Laden dort ist, und merkt sich die Dauer. Danach plant er bei
 * Zwischenstopps mit deiner echten Zeit statt mit 10 Minuten – und der PC weiß es auch (über den Handy-Status).
 */
object Halte {
    private const val TAG = "JarvisHalte"
    private val http = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS).build()
    private fun file(ctx: Context) = File(ctx.filesDir, "halte.json")
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun all(ctx: Context): JSONArray = try { JSONArray(file(ctx).readText()) } catch (_: Exception) { JSONArray() }
    private fun list(ctx: Context) = all(ctx).let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) } }

    /** Jede Minute aus Alltag.tick: Stillstand verfolgen. */
    fun tick(ctx: Context, loc: Location?, home: Boolean) {
        val now = System.currentTimeMillis()
        val cur = try { JSONObject(prefs(ctx).getString("halt_cur", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        if (home) { if (cur.length() > 0) { close(ctx, cur); prefs(ctx).edit().putString("halt_cur", "{}").apply() }; return }
        if (loc == null || now - loc.time > 5 * 60_000L || loc.accuracy > 120) return
        val p = Route.P(loc.latitude, loc.longitude, "")
        val same = cur.has("lat") && Route.distKm(p, Route.P(cur.optDouble("lat"), cur.optDouble("lon"), "")) < 0.12 &&
            now - cur.optLong("last") < 15 * 60_000L
        if (same) cur.put("last", now)
        else {
            if (cur.length() > 0) close(ctx, cur)
            cur.put("lat", loc.latitude).put("lon", loc.longitude).put("t0", now).put("last", now)
        }
        prefs(ctx).edit().putString("halt_cur", cur.toString()).apply()
    }

    private fun close(ctx: Context, cur: JSONObject) {
        val min = (cur.optLong("last") - cur.optLong("t0")) / 60_000.0
        if (min < 2.0 || min > 90.0) return
        // Jeder Halt (auch ohne Laden) zählt, damit gelernte Fahrzeiten ohne die Pause gerechnet werden
        try {
            val raw = JSONArray(prefs(ctx).getString("halt_raw", "[]") ?: "[]")
            raw.put(JSONArray().put(cur.optLong("t0")).put(cur.optLong("last")))
            while (raw.length() > 60) raw.remove(0)
            prefs(ctx).edit().putString("halt_raw", raw.toString()).apply()
        } catch (_: Exception) {}
        val la = cur.optDouble("lat"); val lo = cur.optDouble("lon")
        val exp = try { JSONObject(prefs(ctx).getString("halt_expect", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        Thread({
            val shop = shopAt(la, lo) ?: return@Thread
            val zweck = exp.optString("kind").takeIf { exp.optLong("until") > cur.optLong("t0") && match(shop.first, exp.optString("name")) } ?: ""
            synchronized(this) {
                val a = all(ctx)
                a.put(JSONObject().put("name", shop.first).put("art", shop.second).put("lat", la).put("lon", lo).put("zweck", zweck)
                    .put("t", cur.optLong("t0")).put("min", Math.round(min * 10) / 10.0))
                while (a.length() > 300) a.remove(0)
                try { file(ctx).writeText(a.toString()) } catch (_: Exception) {}
            }
            Log.i(TAG, "Halt bei ${shop.first}: ${min.toInt()} min")
        }, "jarvis-halt").start()
    }

    /** Welcher Laden ist hier (bis 70 m)? (Name, Art) */
    private fun shopAt(la: Double, lo: Double): Pair<String, String>? = try {
        val q = "[out:json][timeout:20];(nwr[\"shop\"](around:70,$la,$lo);nwr[\"amenity\"~\"^(cafe|fast_food|restaurant|fuel|pharmacy|bank|post_office|ice_cream)$\"](around:70,$la,$lo););out center 30;"
        val els = JSONObject(http.newCall(Request.Builder().url("https://overpass-api.de/api/interpreter")
            .post(FormBody.Builder().add("data", q).build()).header("User-Agent", "Jarvis-Handy/1.0 (privat)").build())
            .execute().use { it.body?.string() ?: "{}" }).optJSONArray("elements") ?: JSONArray()
        var best: Pair<String, String>? = null; var bd = 1e9
        for (i in 0 until els.length()) {
            val o = els.optJSONObject(i) ?: continue
            val t = o.optJSONObject("tags") ?: continue
            val name = t.optString("brand").ifBlank { t.optString("name") }
            if (name.isBlank()) continue
            val ola = if (o.has("lat")) o.optDouble("lat") else o.optJSONObject("center")?.optDouble("lat") ?: continue
            val olo = if (o.has("lon")) o.optDouble("lon") else o.optJSONObject("center")?.optDouble("lon") ?: continue
            val d = Route.distKm(Route.P(la, lo, ""), Route.P(ola, olo, ""))
            // Supermärkte bevorzugen (die großen Läden liegen oft neben kleinen)
            val score = d - (if (t.optString("shop") == "supermarket") 0.03 else 0.0)
            if (score < bd) { bd = score; best = name to (t.optString("shop").ifBlank { t.optString("amenity") }) }
        }
        best
    } catch (_: Exception) { null }

    private fun match(name: String, q: String) = q.isNotBlank() && (name.contains(q, true) || q.contains(name, true) && name.length >= 3)

    /** Was er dort will: "kurz" (Brot, schnell was holen) oder "gross" (einkaufen) – "" = nicht gesagt. */
    fun kind(text: String): String = when {
        Regex("(?i)brot|brötchen|bäcker|backwaren|nur (schnell )?|schnell (was|mal)|kurz (was|rein)|getränk|milch|snack|eis\\b|kaffee").containsMatchIn(text) -> "kurz"
        Regex("(?i)einkauf|einkaufen|wocheneinkauf|großeinkauf|grosseinkauf|für die woche|vieles|liste").containsMatchIn(text) -> "gross"
        else -> ""
    }

    /** Plan hat einen Halt an [name] – der nächste Halt dort bekommt den Zweck (zum getrennten Lernen). */
    fun expect(ctx: Context, name: String, kind: String) {
        if (name.isBlank()) return
        prefs(ctx).edit().putString("halt_expect", JSONObject().put("name", name.substringBefore(" (").trim()).put("kind", kind)
            .put("until", System.currentTimeMillis() + 8 * 3_600_000L).toString()).apply()
    }

    /** Gelernte Aufenthaltsdauer (Minuten, Median der letzten 8) bei diesem Laden / dieser Kette und diesem Zweck, null = noch nicht gelernt. */
    fun minutes(ctx: Context, vararg names: String, kind: String = ""): Int? {
        val at = list(ctx).filter { o -> names.any { n -> match(o.optString("name"), n.substringBefore(" (").trim()) } }
        fun med(l: List<JSONObject>): Int? { val v = l.map { it.optDouble("min") }.takeLast(8).sorted(); return if (v.isEmpty()) null else Math.round(v[v.size / 2]).toInt().coerceIn(1, 90) }
        if (kind.isBlank()) return med(at)
        med(at.filter { it.optString("zweck") == kind })?.let { return it }
        val untagged = at.filter { it.optString("zweck").isBlank() }
        return med(untagged.filter { if (kind == "kurz") it.optDouble("min") < 8 else it.optDouble("min") >= 8 })
    }

    /** Minuten fürs Planen: gelernt, sonst Brot 5 / Einkauf 15 / unbekannt 10. */
    fun planMinutes(ctx: Context, name: String, kind: String): Int =
        minutes(ctx, name, kind = kind) ?: when (kind) { "kurz" -> 5; "gross" -> 15; else -> minutes(ctx, name) ?: 10 }

    /** Summe der Halte (Minuten) zwischen a und b – für Fahrzeiten ohne Zwischenstopp. */
    fun dwellBetween(ctx: Context, a: Long, b: Long): Double = try {
        val raw = JSONArray(prefs(ctx).getString("halt_raw", "[]") ?: "[]")
        (0 until raw.length()).mapNotNull { raw.optJSONArray(it) }.filter { it.optLong(0) >= a && it.optLong(1) <= b }
            .sumOf { (it.optLong(1) - it.optLong(0)) / 60_000.0 }
    } catch (_: Exception) { 0.0 }

    /** Kurz für Briefings, Brain und den PC: "Beim REWE hältst du meist 9 Minuten (6 Mal) …" */
    fun summary(ctx: Context): String {
        val g = list(ctx).groupBy { it.optString("name") }.filter { it.key.isNotBlank() }.entries.sortedByDescending { it.value.size }.take(5)
        if (g.isEmpty()) return ""
        fun med(l: List<JSONObject>) = l.map { it.optDouble("min") }.takeLast(8).sorted().let { Math.round(it[it.size / 2]) }
        return "Gelernte Zwischenstopps (wie lange er dort meist hält): " + g.joinToString("; ") { (n, l) ->
            val k = l.filter { it.optString("zweck") == "kurz" }; val e = l.filter { it.optString("zweck") == "gross" }
            val parts = listOfNotNull(k.takeIf { it.isNotEmpty() }?.let { "schnell was holen ${med(it)} Min." },
                e.takeIf { it.isNotEmpty() }?.let { "Einkauf ${med(it)} Min." })
            "$n " + (if (parts.isEmpty()) "${med(l)} Min." else parts.joinToString(", ")) + " (${l.size}×)"
        } + "."
    }

    fun test(ctx: Context): String {
        val cur = try { JSONObject(prefs(ctx).getString("halt_cur", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        val now = if (cur.has("t0")) " Gerade stehst du seit ${(System.currentTimeMillis() - cur.optLong("t0")) / 60_000} Min. an einer Stelle." else ""
        return summary(ctx).ifBlank { "Noch keine Stopps gelernt – sobald du unterwegs irgendwo 2 Minuten hältst (Rewe, Bäcker …), merke ich mir das." } + now
    }
}
