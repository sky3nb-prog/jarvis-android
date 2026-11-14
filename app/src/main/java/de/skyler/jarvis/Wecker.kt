package de.skyler.jarvis

import android.content.Context
import android.content.Intent
import android.provider.AlarmClock
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Wecker über die Uhr-App des Handys (Samsung Uhr): "Wecker um 6", "ich will um 7:30 aufstehen, Wecker um 6:45, 6:50, 7 und 7:05".
 * Jarvis merkt sich, welche Wecker er gestellt hat (gleicher Name "Jarvis"), stellt einen schon vorhandenen nicht doppelt,
 * sondern schaltet ihn wieder ein, und gibt das Morgen-Briefing passend zur Aufsteh-Zeit.
 */
object Wecker {
    private val de = Locale.GERMANY
    const val LABEL = "Jarvis"
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    private fun hm(s: String): Pair<Int, Int>? = Regex("(\\d{1,2})(?:[:.](\\d{2}))?").find(s.trim())?.groupValues?.let {
        val h = it[1].toInt(); val m = it[2].toIntOrNull() ?: 0
        if (h in 0..23 && m in 0..59) h to m else null
    }

    /** Welche Wecker Jarvis gestellt hat: [{h, m, tage:[…]}] */
    fun liste(ctx: Context): JSONArray = try { JSONArray(prefs(ctx).getString("wecker_liste", "[]")) } catch (_: Exception) { JSONArray() }

    private fun days(tage: String): ArrayList<Int>? = when (tage.lowercase().trim()) {
        "werktags", "wochentags", "mo-fr", "schultage" -> arrayListOf(Calendar.MONDAY, Calendar.TUESDAY, Calendar.WEDNESDAY, Calendar.THURSDAY, Calendar.FRIDAY)
        "täglich", "jeden tag", "immer" -> arrayListOf(Calendar.SUNDAY, Calendar.MONDAY, Calendar.TUESDAY, Calendar.WEDNESDAY, Calendar.THURSDAY, Calendar.FRIDAY, Calendar.SATURDAY)
        "wochenende" -> arrayListOf(Calendar.SATURDAY, Calendar.SUNDAY)
        else -> null
    }

    /** Nächster Zeitpunkt für h:m (heute, wenn noch nicht vorbei, sonst morgen). */
    private fun nextAt(h: Int, m: Int): Long {
        val c = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, h); set(Calendar.MINUTE, m); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }
        if (c.timeInMillis <= System.currentTimeMillis()) c.add(Calendar.DAY_OF_YEAR, 1)
        return c.timeInMillis
    }

    /**
     * Wecker stellen. zeiten = ["6:45","6:50",…], aufstehen = "7:30" (optional), tage = "" | "werktags" | "täglich" | "wochenende".
     * Läuft die Uhr-App kurz im Hintergrund an (ohne Fenster).
     */
    fun set(ctx: Context, zeiten: List<String>, aufstehen: String = "", tage: String = ""): String {
        val times = zeiten.mapNotNull { hm(it) }.distinct().sortedBy { it.first * 60 + it.second }
        val up = hm(aufstehen)
        if (times.isEmpty() && up == null) return "Für wann soll der Wecker sein?"
        val d = days(tage)
        val list = liste(ctx)
        var neu = 0; var wieder = 0
        for ((h, m) in times) {
            val known = (0 until list.length()).any { list.optJSONObject(it)?.let { o -> o.optInt("h") == h && o.optInt("m") == m } == true }
            val i = Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR, h).putExtra(AlarmClock.EXTRA_MINUTES, m)
                .putExtra(AlarmClock.EXTRA_MESSAGE, LABEL).putExtra(AlarmClock.EXTRA_SKIP_UI, true).putExtra(AlarmClock.EXTRA_VIBRATE, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION)
            if (d != null) i.putExtra(AlarmClock.EXTRA_DAYS, d)
            try { ctx.startActivity(i) } catch (_: Exception) { return "Ich finde keine Wecker-App." }
            if (known) wieder++ else { neu++; list.put(JSONObject().put("h", h).put("m", m).put("tage", tage)) }
            Thread.sleep(900)   // der Uhr-App Zeit lassen, sonst gehen Wecker verloren
        }
        prefs(ctx).edit().putString("wecker_liste", list.toString()).apply()
        // Aufsteh-Zeit: dann kommt das Morgen-Briefing (beim nächsten Mal; bei "werktags"/"täglich" jedes Mal)
        val upT = up ?: times.lastOrNull()
        if (upT != null) prefs(ctx).edit().putString("aufstehen", JSONObject().put("h", upT.first).put("m", upT.second).put("tage", tage)
            .put("datum", SimpleDateFormat("yyyy-MM-dd", de).format(Date(nextAt(upT.first, upT.second)))).put("erster", times.firstOrNull()?.let { "%d:%02d".format(it.first, it.second) } ?: "")
            .toString()).apply()
        val zt = times.joinToString(", ") { "%d:%02d".format(it.first, it.second) }
        val day = if (d != null) " ($tage)" else if (times.isNotEmpty() && nextAt(times[0].first, times[0].second) - System.currentTimeMillis() > 12 * 3_600_000L) " für morgen" else ""
        return (if (times.size == 1) "Wecker auf $zt gestellt$day." else "Wecker auf $zt gestellt$day.") +
            (if (wieder > 0 && neu == 0) " Die gab es schon, ich hab sie wieder eingeschaltet." else if (wieder > 0) " $wieder davon gab es schon, die hab ich wieder eingeschaltet." else "") +
            (if (up != null) " Aufstehen um ${"%d:%02d".format(up.first, up.second)} – dann bekommst du dein Tages-Update." else "")
    }

    /** Wecker ausschalten: bestimmte Zeiten oder alle von Jarvis. */
    fun off(ctx: Context, zeiten: List<String>): String {
        val times = zeiten.mapNotNull { hm(it) }
        val list = liste(ctx)
        val targets = if (times.isEmpty()) (0 until list.length()).mapNotNull { list.optJSONObject(it)?.let { o -> o.optInt("h") to o.optInt("m") } } else times
        if (targets.isEmpty()) return "Ich habe keine Wecker gestellt, die ich ausschalten könnte."
        for ((h, m) in targets) {
            val i = Intent(AlarmClock.ACTION_DISMISS_ALARM).putExtra(AlarmClock.EXTRA_ALARM_SEARCH_MODE, AlarmClock.ALARM_SEARCH_MODE_TIME)
                .putExtra(AlarmClock.EXTRA_HOUR, h).putExtra(AlarmClock.EXTRA_MINUTES, m).putExtra(AlarmClock.EXTRA_SKIP_UI, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            try { ctx.startActivity(i) } catch (_: Exception) {}
            Thread.sleep(900)
        }
        if (times.isEmpty()) prefs(ctx).edit().remove("aufstehen").apply()
        return "Wecker ${targets.joinToString(", ") { "%d:%02d".format(it.first, it.second) }} ausgeschaltet."
    }

    /** Aufsteh-Zeit für heute (Millisekunden) oder null. */
    fun upToday(ctx: Context): Long? {
        val o = try { JSONObject(prefs(ctx).getString("aufstehen", "{}") ?: "{}") } catch (_: Exception) { return null }
        if (!o.has("h")) return null
        val today = SimpleDateFormat("yyyy-MM-dd", de).format(Date())
        val d = days(o.optString("tage"))
        val dow = Calendar.getInstance().get(Calendar.DAY_OF_WEEK)
        if (o.optString("datum") != today && (d == null || dow !in d)) return null
        return Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, o.optInt("h")); set(Calendar.MINUTE, o.optInt("m")); set(Calendar.SECOND, 0) }.timeInMillis
    }

    // --- Automatisch: "An Schultagen will ich um 7:10 aufstehen" -> jeden Abend die Wecker für morgen ---------
    /** Minuten vor dem Aufstehen, z. B. "25, 20, 10, 5" -> 6:45, 6:50, 7:00, 7:05 bei 7:10. */
    fun offsets(ctx: Context): List<Int> = (prefs(ctx).getString("wecker_vorher", "25, 20, 10, 5") ?: "").split(',', ';', ' ')
        .mapNotNull { it.trim().removePrefix("-").toIntOrNull() }.filter { it in 1..180 }.distinct().sortedDescending().ifEmpty { listOf(25, 20, 10, 5) }

    /** Aufsteh-Zeit für einen Tag (Schultag Mo–Fr oder Wochenende) laut Einstellung, sonst null. */
    /** Aufsteh-Zeit je Wochentag (Calendar.SUNDAY=1 … SATURDAY=7), "" = kein Wecker. */
    fun tage(ctx: Context): JSONObject {
        val p = prefs(ctx)
        p.getString("wecker_tage", null)?.let { try { return JSONObject(it) } catch (_: Exception) {} }
        val o = JSONObject(); val sch = p.getString("wecker_schule", "7:10") ?: ""; val we = p.getString("wecker_we", "") ?: ""
        for (d in 1..7) o.put(d.toString(), if (d == Calendar.SATURDAY || d == Calendar.SUNDAY) we else sch)
        return o
    }

    fun planFor(ctx: Context, dow: Int): Pair<Int, Int>? {
        val p = prefs(ctx)
        if (!p.getBoolean("wecker_an", true)) return null
        if (p.contains("wecker_tage")) return hm(tage(ctx).optString(dow.toString()))
        val v = if (dow == Calendar.SATURDAY || dow == Calendar.SUNDAY) p.getString("wecker_we", "") else p.getString("wecker_schule", "7:10")
        return hm(v ?: "")
    }

    fun timesFor(ctx: Context, up: Pair<Int, Int>): List<String> = offsets(ctx).map { o ->
        val t = up.first * 60 + up.second - o; "%d:%02d".format(((t + 1440) % 1440) / 60, ((t + 1440) % 1440) % 60)
    }

    /** Per Sprache: Aufsteh-Zeit für Schultage oder Wochenende festlegen (und, wenn es schon Abend ist, gleich für morgen stellen). */
    fun setPlan(ctx: Context, aufstehen: String, tage: String, vorher: String = ""): String {
        val up = hm(aufstehen) ?: return "Um wie viel Uhr willst du aufstehen?"
        val low = tage.lowercase()
        val we = low.contains("wochenende")
        val names = mapOf("mo" to 2, "di" to 3, "mi" to 4, "do" to 5, "fr" to 6, "sa" to 7, "so" to 1)
        val days = Regex("\\b(mo|di|mi|do|fr|sa|so)\\w*").findAll(low).mapNotNull { names[it.groupValues[1]] }.toSet()
            .ifEmpty { if (we) setOf(7, 1) else setOf(2, 3, 4, 5, 6) }
        val o = tage(ctx); for (d in days) o.put(d.toString(), "%d:%02d".format(up.first, up.second))
        prefs(ctx).edit().putString("wecker_tage", o.toString()).putBoolean("wecker_an", true)
            .apply { if (vorher.isNotBlank()) putString("wecker_vorher", vorher) }.apply()
        prefs(ctx).edit().remove("wecker_tag").apply()   // heute Abend neu stellen
        val ts = timesFor(ctx, up)
        val dn = listOf("", "So", "Mo", "Di", "Mi", "Do", "Fr", "Sa")
        return "Okay: ${days.sortedBy { (it + 5) % 7 }.joinToString(", ") { dn[it] }} aufstehen um ${"%d:%02d".format(up.first, up.second)}. " +
            "Ich stelle dir jeden Abend die Wecker für den nächsten Tag: ${ts.joinToString(", ")}. Dein Tages-Update kommt um ${"%d:%02d".format(up.first, up.second)}."
    }

    /** Aus dem Hintergrund (jede Minute): ab 19 Uhr die Wecker für morgen stellen, wenn morgen ein Tag mit Aufsteh-Zeit ist. */
    fun tick(ctx: Context, frei: (Long) -> Boolean): String? {
        val c = Calendar.getInstance()
        if (c.get(Calendar.HOUR_OF_DAY) < 19) return null
        val tomorrow = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, 1); set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0) }
        val key = SimpleDateFormat("yyyy-MM-dd", de).format(tomorrow.time)
        if (prefs(ctx).getString("wecker_tag", "") == key) return null
        prefs(ctx).edit().putString("wecker_tag", key).apply()
        val up = planFor(ctx, tomorrow.get(Calendar.DAY_OF_WEEK)) ?: return null
        if (frei(tomorrow.timeInMillis)) return "Morgen ist frei (Ferien/Feiertag im Kalender) – ich stelle keinen Wecker."
        return set(ctx, timesFor(ctx, up), "%d:%02d".format(up.first, up.second), "")
    }

    fun openApp(ctx: Context): String = try {
        ctx.startActivity(Intent(AlarmClock.ACTION_SHOW_ALARMS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); "Hier sind deine Wecker."
    } catch (_: Exception) { "Die Uhr-App geht gerade nicht auf." }
}
