package de.skyler.jarvis

import android.content.Context
import android.location.Location
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Hunderunde erkennen: Du gehst von zuhause los, läufst langsam (Gehtempo) eine Runde in der Nähe und kommst zurück.
 *  - Optional: kurz bevor du wieder da bist, SMS an Mama (oder wen du einträgst): "Bin gleich da."
 *    Erkennt "gleich da" auf zwei Wegen: (1) du kommst dem Haus wieder deutlich näher (auch bei kurzen Runden),
 *    (2) deine Standardrunde (gelernt aus den letzten Runden): du bist an der Stelle, die etwa 1 Minute vor dem Ende liegt.
 *  - Einmalig per Sprache: "schick Mama eine SMS, wenn ich wieder heimkomme" (geht auch ohne Gassi-Schalter).
 *  - Protokoll jeder Minute (Standort, Genauigkeit, Abstand, zuhause ja/nein, warum keine SMS) – geht am Ende der
 *    Runde automatisch an den PC (gassi_log.json), damit man nachsehen kann, was er gesehen hat.
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
    private inline fun <T> tryOr(f: () -> T): T? = try { f() } catch (_: Exception) { null }
    private fun once(ctx: Context): JSONObject? = tryOr { JSONObject(prefs(ctx).getString("heim_sms", "{}") ?: "{}") }?.takeIf { it.optLong("until") > System.currentTimeMillis() }

    /** Einmalige SMS beim Heimkommen (per Sprache). */
    fun heimSms(ctx: Context, wer: String, text: String): String {
        val w = wer.ifBlank { who(ctx) }
        prefs(ctx).edit().putString("heim_sms", JSONObject().put("wer", w).put("text", text.ifBlank { "Bin gleich da." })
            .put("until", System.currentTimeMillis() + 6 * 3_600_000L).toString()).apply()
        return "Mach ich – kurz bevor du wieder zuhause bist, schreibe ich $w „${text.ifBlank { "Bin gleich da." }}“."
    }

    /** Protokoll (letzte 90 Einträge): [Uhrzeit, lat, lon, Genauigkeit m, Abstand m, zuhause 0/1, Notiz] */
    private fun log(ctx: Context, loc: Location?, d: Double, home: Boolean, note: String) {
        val a = tryOr { JSONArray(prefs(ctx).getString("gassi_dbg", "[]")) } ?: JSONArray()
        a.put(JSONArray().put(SimpleDateFormat("HH:mm:ss", Locale.GERMANY).format(Date())).put(loc?.latitude?.let { Math.round(it * 1e5) / 1e5 } ?: 0)
            .put(loc?.longitude?.let { Math.round(it * 1e5) / 1e5 } ?: 0).put(loc?.accuracy?.toInt() ?: -1).put(d.toInt()).put(if (home) 1 else 0).put(note))
        while (a.length() > 90) a.remove(0)
        prefs(ctx).edit().putString("gassi_dbg", a.toString()).apply()
    }

    /** Jede Minute aus Alltag.tick. */
    fun tick(ctx: Context, loc: Location?, home: Boolean) {
        val one = once(ctx)
        if (!on(ctx) && one == null) { if (st(ctx).length() > 0) put(ctx, JSONObject()); return }
        val now = System.currentTimeMillis()
        val c = st(ctx)
        val h = Route.home(ctx)
        val fresh = loc != null && now - loc.time < 4 * 60_000L && loc.accuracy <= 150
        val d = if (h != null && loc != null) Route.distKm(h, Route.P(loc.latitude, loc.longitude, "")) * 1000 else -1.0
        if (home) {
            if (c.has("start") || !prefs(ctx).getBoolean("gassi_wasHome", false)) log(ctx, loc, d, true, if (c.has("start")) "zuhause erkannt – Runde zu Ende" else "zuhause")
            prefs(ctx).edit().putBoolean("gassi_wasHome", true).apply()
            if (c.has("start")) finish(ctx, c, now)
            put(ctx, JSONObject()); return
        }
        prefs(ctx).edit().putBoolean("gassi_wasHome", false).apply()
        if (h == null) { log(ctx, loc, -1.0, false, "keine Heimadresse"); return }
        if (!fresh) { log(ctx, loc, d, false, if (loc == null) "kein Standort" else "Standort zu alt/ungenau"); return }
        val p = Route.P(loc!!.latitude, loc.longitude, "")
        if (!c.has("start")) c.put("start", now).put("km", 0.0).put("maxd", d).put("lat", p.lat).put("lon", p.lon).put("d", d).put("pts", JSONArray())
        else {
            val step = Route.distKm(Route.P(c.optDouble("lat"), c.optDouble("lon"), ""), p)
            if (step > 0.012) c.put("km", c.optDouble("km") + step).put("lat", p.lat).put("lon", p.lon)
            c.put("maxd", maxOf(c.optDouble("maxd"), d))
        }
        val pts = c.optJSONArray("pts") ?: JSONArray().also { c.put("pts", it) }
        pts.put(JSONArray().put(Math.round(p.lat * 1e5) / 1e5).put(Math.round(p.lon * 1e5) / 1e5)); while (pts.length() > 120) pts.remove(0)
        val min = (now - c.optLong("start")) / 60_000.0
        val kmh = if (min > 0) c.optDouble("km") / (min / 60) else 0.0
        val prevD = c.optDouble("d", d); c.put("d", d)
        val maxd = c.optDouble("maxd")
        val walking = kmh <= 7.0 && maxd < 3000
        c.put("walk", walking)
        // (1) wieder deutlich näher am Haus (auch kurze Runden ab 120 m)
        val near = d < maxOf(70.0, minOf(220.0, maxd * 0.45))
        val closer = d < prevD - 8
        val byDist = min >= 3 && maxd >= 120 && near && closer
        // (2) Standardrunde: Stelle ~1 Min. vor dem Ende der üblichen Runde erreicht
        val byRound = min >= 3 && standardPoint(ctx)?.let { sp -> Route.distKm(p, sp) * 1000 < 45 && min > medianMin(ctx) * 0.5 } == true
        val want = (on(ctx) && smsOn(ctx) && walking) || one != null
        val why = when {
            c.optBoolean("sms") -> "SMS schon raus"
            !want -> "SMS-Schalter aus"
            min < 3 -> "erst ${min.toInt()} Min. unterwegs"
            maxd < 120 && !byRound -> "noch nicht weit genug weg (max ${maxd.toInt()} m)"
            !near && !byRound -> "noch ${d.toInt()} m weg (SMS ab ${maxOf(70.0, minOf(220.0, maxd * 0.45)).toInt()} m)"
            !closer && !byRound -> "nicht näher gekommen (${prevD.toInt()} → ${d.toInt()} m)"
            else -> "→ SMS"
        }
        log(ctx, loc, d, false, "${min.toInt()} min, ${"%.1f".format(Locale.GERMANY, kmh)} km/h, max ${maxd.toInt()} m: $why")
        c.put("why", why)
        if (want && !c.optBoolean("sms") && (byDist || byRound)) {
            c.put("sms", true)
            val w = one?.optString("wer") ?: who(ctx); val t = one?.optString("text") ?: text(ctx)
            if (one != null) prefs(ctx).edit().remove("heim_sms").apply()
            Thread({ sendTo(ctx, w, t) }, "jarvis-gassi-sms").start()
        }
        put(ctx, c)
    }

    /** Median-Dauer der letzten Runden (Minuten). */
    private fun medianMin(ctx: Context): Double {
        val v = (0 until walks(ctx).length()).mapNotNull { walks(ctx).optJSONObject(it)?.optDouble("min") }.takeLast(7).sorted()
        return if (v.isEmpty()) 15.0 else v[v.size / 2]
    }

    /** Stelle auf deiner Standardrunde, die ca. 80 m (gut 1 Minute) vor dem Ende liegt – aus der letzten Runde mit Weg. */
    private fun standardPoint(ctx: Context): Route.P? {
        val a = walks(ctx)
        val l = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { (it.optJSONArray("path")?.length() ?: 0) >= 4 }
        if (l.size < 2) return null
        val path = l.last().optJSONArray("path") ?: return null
        var acc = 0.0
        for (i in path.length() - 1 downTo 1) {
            val b = path.getJSONArray(i); val q = path.getJSONArray(i - 1)
            acc += Route.distKm(Route.P(b.getDouble(0), b.getDouble(1), ""), Route.P(q.getDouble(0), q.getDouble(1), "")) * 1000
            if (acc >= 80) return Route.P(q.getDouble(0), q.getDouble(1), "")
        }
        return null
    }

    private fun finish(ctx: Context, c: JSONObject, now: Long) {
        val min = (now - c.optLong("start")) / 60_000.0
        val km = c.optDouble("km")
        val kmh = if (min > 0) km / (min / 60) else 0.0
        val ok = !(min < 4 || min > 180 || kmh > 7.0 || c.optDouble("maxd") < 100 || c.optDouble("maxd") > 3000)
        if (ok) {
            val a = walks(ctx)
            a.put(JSONObject().put("start", c.optLong("start")).put("end", now).put("min", Math.round(min)).put("km", Math.round(km * 100) / 100.0)
                .put("maxd", c.optDouble("maxd").toInt()).put("path", c.optJSONArray("pts") ?: JSONArray()).put("sms", c.optBoolean("sms")))
            while (a.length() > 200) a.remove(0)
            try { file(ctx).writeText(a.toString()) } catch (_: Exception) {}
            Log.i(TAG, "Hunderunde: ${min.toInt()} min, ${"%.2f".format(km)} km")
            try { Feed.add(ctx, "test", "Hunderunde", "${Math.round(min)} Min., ${"%.1f".format(Locale.GERMANY, km)} km",
                "Gassi-Runde erkannt: ${Math.round(min)} Minuten, ${"%.1f".format(Locale.GERMANY, km)} Kilometer, bis ${c.optDouble("maxd").toInt()} m weit weg.") } catch (_: Exception) {}
        }
        Thread({ shareToPc(ctx) }, "jarvis-gassi-log").start()   // Protokoll an den PC (zum Nachsehen)
    }

    /** Protokoll + letzte Runden an den PC schicken (landet dort als gassi_log.json). */
    fun shareToPc(ctx: Context): String = try {
        if (!Link.paired(ctx)) "Nicht mit dem PC gekoppelt." else {
            val dbg = tryOr { JSONArray(prefs(ctx).getString("gassi_dbg", "[]")) } ?: JSONArray()
            val a = walks(ctx); val last = JSONArray(); for (i in maxOf(0, a.length() - 3) until a.length()) last.put(a.get(i))
            val r = Link.command(ctx, JSONObject().put("type", "gassi_log").put("need_active", false).put("log", dbg).put("runden", last)
                .put("home", Route.home(ctx)?.let { JSONArray().put(Math.round(it.lat * 1e4) / 1e4).put(Math.round(it.lon * 1e4) / 1e4) } ?: JSONArray()), 20_000)
            if (r?.optBoolean("ok") == true) "Protokoll ist am PC (gassi_log.json)." else "Der PC hat nicht geantwortet."
        }
    } catch (e: Exception) { "Ging nicht: ${e.message}" }

    private fun sendTo(ctx: Context, w: String, t: String): String {
        val nr = Actions(ctx).number(w) ?: return "„$w“ finde ich nicht in deinen Kontakten."
        val ok = Butler.sms(ctx, nr, t, w)
        try { Feed.add(ctx, "ankunft", if (ok) "Gassi: SMS an $w" else "Gassi: SMS ging nicht", t, if (ok) "An $w: $t" else "SMS-Recht fehlt (Einstellungen → Leute).") } catch (_: Exception) {}
        return if (ok) "SMS an $w geschickt: „$t“" else "Die SMS ging nicht raus – erlaube SMS in den Einstellungen unter Leute."
    }

    /** SMS "Bin gleich da" (test = mit "Test" davor, sofort). */
    fun send(ctx: Context, test: Boolean): String = sendTo(ctx, who(ctx), (if (test) "Test von Jarvis: " else "") + text(ctx))

    /** Für Brain und Einstellungen. */
    fun summary(ctx: Context): String {
        val a = walks(ctx); if (a.length() == 0) return ""
        val l = (0 until a.length()).mapNotNull { a.optJSONObject(it) }
        val dayStart = java.util.Calendar.getInstance().apply { set(java.util.Calendar.HOUR_OF_DAY, 0); set(java.util.Calendar.MINUTE, 0) }.timeInMillis
        val today = l.filter { it.optLong("start") >= dayStart }
        val week = l.filter { it.optLong("start") >= System.currentTimeMillis() - 7 * 86_400_000L }
        return "Hunderunden: heute ${today.size} (${today.sumOf { it.optInt("min") }} Min.), letzte 7 Tage ${week.size}, im Schnitt ${if (week.isEmpty()) 0 else week.sumOf { it.optInt("min") } / week.size} Min."
    }

    /** Genauer Stand für die Einstellungen: läuft er mit, wie weit weg, warum (noch) keine SMS, letzte Einträge. */
    fun status(ctx: Context): String {
        val c = st(ctx)
        val sb = StringBuilder(summary(ctx).ifBlank { "Noch keine Hunderunde gespeichert." })
        if (c.has("start")) sb.append(" · Läuft seit ${(System.currentTimeMillis() - c.optLong("start")) / 60_000} Min., ${c.optDouble("d").toInt()} m vom Haus, weitester Punkt ${c.optDouble("maxd").toInt()} m. SMS: ${c.optString("why")}")
        else sb.append(" · Gerade keine Runde (zuhause oder noch kein Standort).")
        once(ctx)?.let { sb.append(" · Einmal-SMS an ${it.optString("wer")} ist vorgemerkt.") }
        val dbg = tryOr { JSONArray(prefs(ctx).getString("gassi_dbg", "[]")) } ?: JSONArray()
        if (dbg.length() > 0) {
            sb.append("\nLetzte Einträge:")
            for (i in maxOf(0, dbg.length() - 4) until dbg.length()) dbg.optJSONArray(i)?.let { e ->
                sb.append("\n${e.optString(0)}: ${if (e.optInt(5) == 1) "zuhause" else "${e.optInt(4)} m"}, ±${e.optInt(3)} m – ${e.optString(6)}")
            }
        }
        return sb.toString()
    }
}
