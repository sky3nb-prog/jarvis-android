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
 * Schlaf ohne Uhr, nach deiner Bildschirmzeit: Schlaf = vom letzten Mal Bildschirm aus (bzw. letzte Berührung) bis zum
 * nächsten Bildschirm an / Entsperren am Morgen. Ein Video, das läuft, solange der Bildschirm an ist, zählt als wach.
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

    /** Bildschirm an (auch ohne Entsperren, z. B. Video weiterschauen). */
    fun screenOn(ctx: Context) = add(ctx, System.currentTimeMillis(), "n")

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
        // Wach = Bildschirmzeit: jede Zeit, in der der Bildschirm an war (an/entsperrt bis aus) plus jede Berührung.
        // Kurz angehen ohne Entsperren und ohne Berührung (unter 1 Min., z. B. Benachrichtigung) zählt nicht.
        ev.sortBy { it.first }
        val iv = ArrayList<LongArray>()   // [start, ende, zählt]
        var on = -1L; var real = false
        for ((t, ty) in ev) when (ty) {
            "n", "u" -> { if (on < 0) { on = t; real = false }; if (ty == "u") real = true }
            "i" -> { if (on < 0) iv.add(longArrayOf(t, t, 1)) else real = true }
            "f" -> { if (on >= 0) { iv.add(longArrayOf(on, t, if (real || t - on >= 60_000L) 1 else 0)); on = -1 } else iv.add(longArrayOf(t, t, 1)) }
        }
        if (on >= 0) iv.add(longArrayOf(on, to, 1))
        val awake = iv.filter { it[2] == 1L }.sortedBy { it[0] }
        if (awake.size < 2) return null
        // überlappende Wach-Zeiten zusammenfassen
        val merged = ArrayList<LongArray>()
        for (w in awake) { val l = merged.lastOrNull(); if (l != null && w[0] <= l[1]) l[1] = maxOf(l[1], w[1]) else merged.add(longArrayOf(w[0], w[1])) }
        // Lücken ab 45 Min. zwischen zwei Wach-Zeiten sind Schlaf-Stücke; dazwischen höchstens 10 Min. wach -> zusammen
        data class Gap(var s: Long, var e: Long, var sleep: Long, var wake: Long)
        val gaps = ArrayList<Gap>()
        for (i in 1 until merged.size) {
            val gs = merged[i - 1][1]; val ge = merged[i][0]; val g = ge - gs
            if (g < 45 * 60_000L) continue
            val last = gaps.lastOrNull()
            if (last != null && gs - last.e <= 10 * 60_000L) { last.wake += gs - last.e; last.e = ge; last.sleep += g }
            else gaps.add(Gap(gs, ge, g, 0))
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
