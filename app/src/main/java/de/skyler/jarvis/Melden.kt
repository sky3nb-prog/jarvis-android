package de.skyler.jarvis

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import androidx.core.app.NotificationCompat
import org.json.JSONArray
import org.json.JSONObject
import java.util.Calendar

/**
 * Wann darf Jarvis am Handy reden – und wann nur eine Nachricht schicken?
 *  - Laut sprechen nur, wenn du zuhause bist ODER deine Kopfhörer verbunden sind (Name in den Einstellungen, z. B. "JBL Tune Beam 2").
 *  - "Nicht stören" an (oder Handy lautlos): nie sprechen, nur Nachricht.
 *  - In der Schule während einer Stunde: gar nichts – er hebt es auf und sagt es in der nächsten Pause (bzw. nach der Schule).
 * Dazu der Stundenplan (Einstellungen → Alltag → Schule): Stunden mit Uhrzeit und Fach, Pausen sind die Lücken dazwischen.
 */
object Melden {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    private const val CH = "jarvis_melden"
    private val DAYS = listOf("mo", "di", "mi", "do", "fr")

    // --- Stundenplan --------------------------------------------------------------------------------------------
    /** Standard (wie Skyler ihn beschrieben hat): Mo/Di/Do bis 15:40, Mi bis 12:25, Fr bis 13:25. Fächer trägt er selbst ein. */
    private fun defPlan(): JSONObject {
        fun l(v: String, b: String) = JSONObject().put("von", v).put("bis", b).put("fach", "")
        val voll = listOf(l("08:00", "08:45"), l("08:45", "09:30"), l("09:50", "10:35"), l("10:40", "11:25"), l("11:40", "12:25"), l("12:25", "13:10"), l("14:10", "14:55"), l("14:55", "15:40"))
        val mi = listOf(l("08:00", "08:45"), l("08:45", "09:30"), l("09:50", "10:35"), l("10:40", "11:25"), l("11:40", "12:25"))
        val fr = listOf(l("08:00", "08:45"), l("08:45", "09:30"), l("09:50", "10:35"), l("10:40", "11:25"), l("11:40", "12:25"), l("12:40", "13:25"))
        fun arr(x: List<JSONObject>) = JSONArray().apply { x.forEach { put(JSONObject(it.toString())) } }
        return JSONObject().put("mo", arr(voll)).put("di", arr(voll)).put("mi", arr(mi)).put("do", arr(voll)).put("fr", arr(fr))
    }
    fun plan(ctx: Context): JSONObject = try { JSONObject(prefs(ctx).getString("stundenplan", "") ?: "").takeIf { it.length() > 0 } } catch (_: Exception) { null } ?: defPlan()
    fun setPlan(ctx: Context, json: String) { try { JSONObject(json); prefs(ctx).edit().putString("stundenplan", json).apply() } catch (_: Exception) {} }

    private fun mins(hm: String): Int = try { hm.substringBefore(":").trim().toInt() * 60 + hm.substringAfter(":").trim().toInt() } catch (_: Exception) { -1 }
    private fun dayKey(c: Calendar = Calendar.getInstance()): String? = when (c.get(Calendar.DAY_OF_WEEK)) {
        Calendar.MONDAY -> "mo"; Calendar.TUESDAY -> "di"; Calendar.WEDNESDAY -> "mi"; Calendar.THURSDAY -> "do"; Calendar.FRIDAY -> "fr"; else -> null }

    /** Heute frei (Ferien/Feiertag im Kalender)? */
    private fun frei(ctx: Context): Boolean = try {
        val d0 = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0) }.timeInMillis
        Cal.events(ctx, d0, d0 + 86_400_000L).any { it.allDay && Regex("(?i)ferien|feiertag|frei\\b|urlaub|brückentag").containsMatchIn(it.title) }
    } catch (_: Exception) { false }

    fun lessons(ctx: Context, key: String? = dayKey()): List<JSONObject> {
        val a = plan(ctx).optJSONArray(key ?: return emptyList()) ?: return emptyList()
        return (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { mins(it.optString("von")) >= 0 && mins(it.optString("bis")) > mins(it.optString("von")) }
            .sortedBy { mins(it.optString("von")) }
    }

    /** Schultag heute? (Stunden im Plan, nicht frei) */
    fun schoolDay(ctx: Context): Boolean = lessons(ctx).isNotEmpty() && !frei(ctx)

    /** Bist du gerade an der Schule? Ort "Schule" aus Meine Orte (bis 400 m) – oder, ohne Ort: unterwegs während der Schulzeit. */
    fun atSchool(ctx: Context): Boolean {
        if (!schoolDay(ctx)) return false
        val now = Calendar.getInstance().let { it.get(Calendar.HOUR_OF_DAY) * 60 + it.get(Calendar.MINUTE) }
        val l = lessons(ctx); val from = mins(l.first().optString("von")) - 15; val to = mins(l.last().optString("bis")) + 10
        if (now !in from..to) return false
        val sp = try { if (Route.placeNames(ctx).any { it.equals("Schule", true) }) Route.place(ctx, "Schule") else null } catch (_: Exception) { null }
        val fx = Alltag.fix?.takeIf { System.currentTimeMillis() - it.time < 20 * 60_000L }
        if (sp != null && fx != null) return Route.distKm(sp, Route.P(fx.latitude, fx.longitude, "")) < 0.4
        return !Alltag.isHome(ctx)
    }

    /** Laufende Stunde (oder null = Pause/keine Schule). */
    fun lessonNow(ctx: Context): JSONObject? {
        if (!atSchool(ctx)) return null
        val now = Calendar.getInstance().let { it.get(Calendar.HOUR_OF_DAY) * 60 + it.get(Calendar.MINUTE) }
        return lessons(ctx).firstOrNull { now >= mins(it.optString("von")) && now < mins(it.optString("bis")) }
    }

    /** Für Prompts: was gerade in der Schule ist. */
    fun schoolText(ctx: Context): String = try {
        if (!schoolDay(ctx)) "" else {
            val l = lessons(ctx); val now = Calendar.getInstance().let { it.get(Calendar.HOUR_OF_DAY) * 60 + it.get(Calendar.MINUTE) }
            val cur = l.firstOrNull { now >= mins(it.optString("von")) && now < mins(it.optString("bis")) }
            val next = l.firstOrNull { mins(it.optString("von")) > now }
            val fach = l.mapNotNull { it.optString("fach").takeIf { f -> f.isNotBlank() } }.distinct()
            "Heute ist Schule (${l.first().optString("von")}–${l.last().optString("bis")})" + (if (fach.isNotEmpty()) ", Fächer: ${fach.joinToString()}" else "") +
                (cur?.let { ", gerade ${it.optString("fach").ifBlank { "Unterricht" }} bis ${it.optString("bis")}" } ?: next?.let { ", nächste Stunde ${it.optString("von")} ${it.optString("fach")}".trimEnd() } ?: ", Schule ist für heute vorbei") + "."
        }
    } catch (_: Exception) { "" }

    // --- Darf er reden? ----------------------------------------------------------------------------------------
    fun headphones(ctx: Context): Boolean = try {
        val want = (prefs(ctx).getString("kopfhoerer", "JBL Tune Beam") ?: "").trim()
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        am.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any { d ->
            val bt = d.type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP || d.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO ||
                (Build.VERSION.SDK_INT >= 31 && (d.type == AudioDeviceInfo.TYPE_BLE_HEADSET || d.type == AudioDeviceInfo.TYPE_BLE_SPEAKER)) ||
                d.type == AudioDeviceInfo.TYPE_WIRED_HEADPHONES || d.type == AudioDeviceInfo.TYPE_WIRED_HEADSET
            bt && (want.isBlank() || d.productName?.toString()?.contains(want, true) == true || d.type == AudioDeviceInfo.TYPE_WIRED_HEADPHONES || d.type == AudioDeviceInfo.TYPE_WIRED_HEADSET)
        }
    } catch (_: Exception) { false }

    fun dnd(ctx: Context): Boolean = try {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val nm = ctx.getSystemService(NotificationManager::class.java)
        am.ringerMode != AudioManager.RINGER_MODE_NORMAL || nm.currentInterruptionFilter > NotificationManager.INTERRUPTION_FILTER_ALL
    } catch (_: Exception) { false }

    /** "speak" = laut sagen (+ Nachricht), "note" = nur Nachricht, "hold" = in der Stunde: aufheben bis zur Pause */
    fun route(ctx: Context): String = when {
        lessonNow(ctx) != null -> "hold"
        dnd(ctx) -> "note"
        Alltag.isHome(ctx) || headphones(ctx) -> "speak"
        else -> "note"
    }

    /** Etwas von selbst sagen – nach den Regeln oben. Gibt zurück, was passiert ist. */
    fun deliver(ctx: Context, title: String, text: String, feedId: String? = null): String {
        val r = route(ctx)
        if (r == "hold") {
            val q = try { JSONArray(prefs(ctx).getString("melden_queue", "[]")) } catch (_: Exception) { JSONArray() }
            q.put(JSONObject().put("title", title).put("text", text).put("fid", feedId ?: "").put("t", System.currentTimeMillis()))
            while (q.length() > 10) q.remove(0)
            prefs(ctx).edit().putString("melden_queue", q.toString()).apply()
            return r
        }
        note(ctx, title, text, feedId)
        if (r == "speak") JarvisService.say(ctx, text)
        return r
    }

    /** In der Pause / nach der Schule: Aufgehobenes nachholen (jede Minute aus Alltag.tick). */
    fun flush(ctx: Context) {
        val q = try { JSONArray(prefs(ctx).getString("melden_queue", "[]")) } catch (_: Exception) { return }
        if (q.length() == 0 || lessonNow(ctx) != null) return
        prefs(ctx).edit().putString("melden_queue", "[]").apply()
        val items = (0 until q.length()).mapNotNull { q.optJSONObject(it) }.filter { System.currentTimeMillis() - it.optLong("t") < 6 * 3_600_000L }
        if (items.isEmpty()) return
        val text = if (items.size == 1) items[0].optString("text") else "Während der Stunde kam: " + items.joinToString(" ") { it.optString("text") }
        deliver(ctx, if (items.size == 1) items[0].optString("title") else "Aus der Stunde", text, items.last().optString("fid").ifBlank { null })
    }

    fun note(ctx: Context, title: String, text: String, feedId: String? = null) = try {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "Jarvis meldet sich", NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(ctx, (feedId ?: title).hashCode(), Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .apply { if (feedId != null) putExtra("feed", feedId) }, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        nm.notify(6000 + (title.hashCode() and 0xff), NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title).setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text)).setContentIntent(open).setAutoCancel(true).build())
    } catch (_: Exception) {}

    // --- Entsperren merken (für "noch im Bett") -------------------------------------------------------------------
    fun unlocked(ctx: Context) { prefs(ctx).edit().putLong("last_unlock", System.currentTimeMillis()).apply() }
    fun lastUnlock(ctx: Context) = prefs(ctx).getLong("last_unlock", 0L)
}
