package de.skyler.jarvis

import android.content.Context
import android.location.Location
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Hunderunde erkennen: Du gehst von zuhause los, läufst langsam (Gehtempo) eine Runde in der Nähe und kommst zurück.
 *  - Optional: ca. 1 Minute bevor du wieder da bist, SMS an Mama (oder wen du einträgst): "Bin gleich da."
 *  - Jede Runde wird gemerkt (Dauer, Strecke) – "wie lange war ich heute Gassi?"
 * Ein- und ausschaltbar (Einstellungen → Alltag → Gassi).
 */
object Gassi {
    private const val TAG = "JarvisGassi"
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    private fun file(ctx: Context) = File(ctx.filesDir, "gassi.json")
    fun walks(ctx: Context): JSONArray = try { JSONArray(file(ctx).readText()) } catch (_: Exception) { JSONArray() }

    fun on(ctx: Context) = prefs(ctx).getBoolean("gassi_an", false)
    fun smsOn(ctx: Context) = prefs(ctx).getBoolean("gassi_sms", false)
    fun who(ctx: Context) = (prefs(ctx).getString("gassi_wer", "Mama") ?: "Mama").ifBlank { "Mama" }
    fun text(ctx: Context) = (prefs(ctx).getString("gassi_text", "") ?: "").ifBlank { "Bin gleich da." }

    private fun st(ctx: Context) = try { JSONObject(prefs(ctx).getString("gassi_cur", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
    private fun put(ctx: Context, o: JSONObject) = prefs(ctx).edit().putString("gassi_cur", o.toString()).apply()

    /** Jede Minute aus Alltag.tick. */
    fun tick(ctx: Context, loc: Location?, home: Boolean) {
        if (!on(ctx)) { if (st(ctx).length() > 0) put(ctx, JSONObject()); return }
        val now = System.currentTimeMillis()
        val c = st(ctx)
        if (home) {
            if (c.has("start")) finish(ctx, c, now)
            put(ctx, JSONObject()); return
        }
        val h = Route.home(ctx) ?: return
        if (loc == null || now - loc.time > 3 * 60_000L || loc.accuracy > 80) return
        val p = Route.P(loc.latitude, loc.longitude, "")
        val d = Route.distKm(h, p) * 1000
        if (!c.has("start")) c.put("start", now).put("km", 0.0).put("maxd", d).put("lat", p.lat).put("lon", p.lon).put("d", d)
        else {
            val step = Route.distKm(Route.P(c.optDouble("lat"), c.optDouble("lon"), ""), p)
            if (step > 0.015) c.put("km", c.optDouble("km") + step).put("lat", p.lat).put("lon", p.lon)
            c.put("maxd", maxOf(c.optDouble("maxd"), d))
        }
        val min = (now - c.optLong("start")) / 60_000.0
        val kmh = if (min > 0) c.optDouble("km") / (min / 60) else 0.0
        val prevD = c.optDouble("d", d); c.put("d", d)
        // Gehtempo, in der Nähe (unter 3 km), mindestens 5 Min. und 250 m weg gewesen -> jetzt auf dem Rückweg, gleich da?
        val walking = kmh in 0.5..6.5 && c.optDouble("maxd") < 3000
        c.put("walk", walking)
        if (walking && smsOn(ctx) && !c.optBoolean("sms") && min >= 5 && c.optDouble("maxd") >= 250 && d < 160 && d < prevD - 15) {
            c.put("sms", true)
            Thread({ send(ctx, false) }, "jarvis-gassi-sms").start()
        }
        put(ctx, c)
    }

    private fun finish(ctx: Context, c: JSONObject, now: Long) {
        val min = (now - c.optLong("start")) / 60_000.0
        val km = c.optDouble("km")
        val kmh = if (min > 0) km / (min / 60) else 0.0
        if (min < 5 || min > 180 || kmh > 6.5 || c.optDouble("maxd") < 150 || c.optDouble("maxd") > 3000) return
        val a = walks(ctx)
        a.put(JSONObject().put("start", c.optLong("start")).put("end", now).put("min", Math.round(min)).put("km", Math.round(km * 100) / 100.0))
        while (a.length() > 200) a.remove(0)
        try { file(ctx).writeText(a.toString()) } catch (_: Exception) {}
        Log.i(TAG, "Hunderunde: ${min.toInt()} min, ${"%.2f".format(km)} km")
        try { Feed.add(ctx, "test", "Hunderunde", "${Math.round(min)} Min., ${"%.1f".format(java.util.Locale.GERMANY, km)} km",
            "Gassi-Runde erkannt: ${Math.round(min)} Minuten, ${"%.1f".format(java.util.Locale.GERMANY, km)} Kilometer.") } catch (_: Exception) {}
    }

    /** SMS "Bin gleich da" (test = mit "Test" davor, sofort). */
    fun send(ctx: Context, test: Boolean): String {
        val w = who(ctx)
        val nr = Actions(ctx).number(w) ?: return "„$w“ finde ich nicht in deinen Kontakten."
        val t = (if (test) "Test von Jarvis: " else "") + text(ctx)
        val ok = Butler.sms(ctx, nr, t)
        try { Feed.add(ctx, "ankunft", if (ok) "Gassi: SMS an $w" else "Gassi: SMS ging nicht", t, if (ok) "An $w: $t" else "SMS-Recht fehlt (Einstellungen → Leute).") } catch (_: Exception) {}
        return if (ok) "SMS an $w geschickt: „$t“" else "Die SMS ging nicht raus – erlaube SMS in den Einstellungen unter Leute."
    }

    /** Für Brain und Einstellungen. */
    fun summary(ctx: Context): String {
        val a = walks(ctx); if (a.length() == 0) return ""
        val l = (0 until a.length()).mapNotNull { a.optJSONObject(it) }
        val dayStart = java.util.Calendar.getInstance().apply { set(java.util.Calendar.HOUR_OF_DAY, 0); set(java.util.Calendar.MINUTE, 0) }.timeInMillis
        val today = l.filter { it.optLong("start") >= dayStart }
        val week = l.filter { it.optLong("start") >= System.currentTimeMillis() - 7 * 86_400_000L }
        return "Hunderunden: heute ${today.size} (${today.sumOf { it.optInt("min") }} Min.), letzte 7 Tage ${week.size}, im Schnitt ${if (week.isEmpty()) 0 else week.sumOf { it.optInt("min") } / week.size} Min."
    }

    fun status(ctx: Context): String {
        val c = st(ctx)
        val now = if (c.has("start")) " Gerade unterwegs seit ${(System.currentTimeMillis() - c.optLong("start")) / 60_000} Min." +
            (if (c.optBoolean("walk")) " (Gehtempo)" else "") else ""
        return summary(ctx).ifBlank { "Noch keine Hunderunde erkannt." } + now
    }
}
