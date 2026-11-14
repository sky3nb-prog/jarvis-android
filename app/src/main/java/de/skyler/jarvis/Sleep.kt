package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Schlaf ohne Uhr: Schlaf = von der letzten Berührung des Bildschirms bis zum nächsten Entsperren am Morgen.
 * (YouTube läuft nachts weiter? Egal – gezählt wird ab dem letzten Finger auf dem Display, nicht ab "Bildschirm aus".)
 * Berührungen kommen von der Bedienungshilfe (nur der Zeitpunkt, kein Inhalt). Ist die aus, nimmt er "Bildschirm aus".
 * Kurz nachts aufs Handy schauen (unter 10 Min.) zählt als Unterbrechung, nicht als Aufwachen.
 */
object Sleep {
    private val de = Locale.GERMANY
    private const val KEEP = 10 * 86_400_000L
    @Volatile private var lastTouch = 0L
    @Volatile private var lastLogged = 0L
    private val lock = Any()

    private fun file(ctx: Context) = File(ctx.filesDir, "schlaf_log.json")
    private fun load(ctx: Context): JSONArray = try { JSONArray(file(ctx).readText()) } catch (_: Exception) { JSONArray() }

    private fun add(ctx: Context, t: Long, type: String) = synchronized(lock) {
        val a = load(ctx); val out = JSONArray(); val cut = System.currentTimeMillis() - KEEP
        for (i in 0 until a.length()) a.optJSONArray(i)?.let { if (it.optLong(0) >= cut) out.put(it) }
        out.put(JSONArray().put(t).put(type))
        try { file(ctx).writeText(out.toString()) } catch (_: Exception) {}
    }

    /** Finger auf dem Display (Bedienungshilfe). Höchstens alle 2 Minuten gespeichert, der genaue letzte Zeitpunkt wird beim "aus" nachgetragen. */
    fun touch(ctx: Context) {
        val now = System.currentTimeMillis(); lastTouch = now
        if (now - lastLogged > 120_000L) { lastLogged = now; add(ctx, now, "i") }
    }

    fun screenOff(ctx: Context) {
        val now = System.currentTimeMillis()
        if (lastTouch > lastLogged) { lastLogged = lastTouch; add(ctx, lastTouch, "i") }
        add(ctx, now, "f")
    }

    fun unlock(ctx: Context) = add(ctx, System.currentTimeMillis(), "u")

    /**
     * Die Nacht, die am Morgen von [day] endet (0 = letzte Nacht, 1 = vorletzte …).
     * Ergebnis: start, end, min (geschlafen), wach (Min. Unterbrechungen), quelle ("touch"/"bildschirm") – oder null.
     */
    fun night(ctx: Context, day: Int = 0): JSONObject? {
        val c = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, -day); set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }
        val from = c.timeInMillis - 6 * 3_600_000L            // ab 18 Uhr am Vortag
        val to = minOf(c.timeInMillis + 16 * 3_600_000L, System.currentTimeMillis())   // bis 16 Uhr
        val ev = ArrayList<Pair<Long, String>>()
        val a = load(ctx)
        for (i in 0 until a.length()) a.optJSONArray(i)?.let { val t = it.optLong(0); if (t in from..to) ev.add(t to it.optString(1)) }
        val touch = ev.any { it.second == "i" }
        // Aktiv-Zeitpunkte: mit Bedienungshilfe Berührungen + Entsperren, sonst Entsperren + Bildschirm aus
        val pts = ev.filter { if (touch) it.second == "i" || it.second == "u" else it.second == "u" || it.second == "f" }.map { it.first }.sorted()
        if (pts.size < 2) return null
        // Lücken ab 45 Min. sind Schlaf-Stücke; dazwischen höchstens 10 Min. wach -> zusammen
        data class Gap(var s: Long, var e: Long, var sleep: Long, var wake: Long)
        val gaps = ArrayList<Gap>()
        for (i in 1 until pts.size) {
            val g = pts[i] - pts[i - 1]
            if (g < 45 * 60_000L) continue
            val last = gaps.lastOrNull()
            if (last != null && pts[i - 1] - last.e <= 10 * 60_000L) { last.wake += pts[i - 1] - last.e; last.e = pts[i]; last.sleep += g }
            else gaps.add(Gap(pts[i - 1], pts[i], g, 0))
        }
        val best = gaps.filter { it.sleep >= 3 * 3_600_000L }.maxByOrNull { it.sleep } ?: return null
        return JSONObject().put("start", best.s).put("end", best.e).put("min", best.sleep / 60_000L).put("wach", best.wake / 60_000L)
            .put("quelle", if (touch) "touch" else "bildschirm")
    }

    private fun hm(t: Long) = SimpleDateFormat("H:mm", de).format(Date(t))
    fun dur(min: Long) = "${min / 60}:%02d Std.".format(min % 60)

    /** Kurzer Satz für Briefings/Antworten. */
    fun text(n: JSONObject?): String = if (n == null) "Für letzte Nacht habe ich keine Schlafdaten." else
        "Geschlafen von ${hm(n.optLong("start"))} bis ${hm(n.optLong("end"))} Uhr, also ${dur(n.optLong("min"))}" +
            (if (n.optLong("wach") > 0) ", ${n.optLong("wach")} Min. zwischendurch wach." else ".")

    /** Letzte 7 Nächte (für Wochenrückblick). */
    fun week(ctx: Context): JSONArray = JSONArray().apply { for (d in 6 downTo 0) night(ctx, d)?.let { put(it.put("tag", SimpleDateFormat("EE", de).format(Date(it.optLong("end"))))) } }
}
