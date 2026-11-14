package de.skyler.jarvis

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Echte Jarvis-Erinnerungen (statt Kalender): "Erinnere mich um 12:30 an Brot".
 *  - Kleine Erinnerungen merkt sich Jarvis selbst (nicht im Kalender).
 *  - Auffällige Benachrichtigung (eigener Kanal, Ton + Vibration, Bildschirm an) mit "Erledigt" und "In 15 Min. nochmal".
 *  - Zuhause sagt er sie zusätzlich laut. Keine Reaktion -> nach 5 Minuten noch einmal.
 *  - Auch Kalender-Termine erinnert Jarvis selbst (Termine, die er einträgt, bekommen keinen Kalender-Alarm mehr).
 *  - Erledigungen ohne Uhrzeit ("morgen Brot holen"): an einem Tag mit Weg im Briefing ("denk an …") und auf dem Heimweg,
 *    sonst wenn du heimkommst (ab 13 Uhr) bzw. um 17 Uhr.
 */
object Remind {
    private val de = Locale.GERMANY
    const val CH = "jarvis_erinnerung"
    const val ACTION_FIRE = "de.skyler.jarvis.ERINNERUNG"
    const val ACTION_DONE = "de.skyler.jarvis.ERINNERUNG_OK"
    const val ACTION_SNOOZE = "de.skyler.jarvis.ERINNERUNG_SPAETER"

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun all(ctx: Context): JSONArray = try { JSONArray(prefs(ctx).getString("jv_erinnerungen", "[]")) } catch (_: Exception) { JSONArray() }
    private fun save(ctx: Context, a: JSONArray) { prefs(ctx).edit().putString("jv_erinnerungen", a.toString()).apply() }
    private fun list(a: JSONArray) = (0 until a.length()).mapNotNull { a.optJSONObject(it) }

    /** Neue Erinnerung. at = Zeitpunkt (ms) oder 0, datum = "yyyy-MM-dd" für Erledigungen ohne Uhrzeit. */
    fun add(ctx: Context, text: String, at: Long, datum: String = "", kind: String = "erinnerung"): JSONObject {
        val o = JSONObject().put("id", "r" + System.currentTimeMillis().toString(36) + (0..99).random()).put("text", text.trim())
            .put("at", at).put("datum", datum).put("kind", kind).put("fired", 0).put("ts", System.currentTimeMillis())
        val a = all(ctx); a.put(o); while (a.length() > 200) a.remove(0); save(ctx, a)
        if (at > 0) schedule(ctx, o.getString("id"), at)
        return o
    }

    /** Sprachbefehl: Uhrzeit/Datum selbst ausrechnen (KI liefert nur Text + datum + zeit). */
    fun addSpoken(ctx: Context, text: String, datum: String, zeit: String, inMin: Int): String {
        val t = text.trim().ifBlank { return "Woran soll ich dich erinnern?" }
        val now = System.currentTimeMillis()
        val d = datum.takeIf { Regex("^\\d{4}-\\d{2}-\\d{2}$").matches(it) }
        val z = zeit.takeIf { Regex("^\\d{1,2}:\\d{2}$").matches(it) }
        val at: Long = when {
            inMin > 0 -> now + inMin * 60_000L
            z != null -> {
                val (h, m) = z.split(":").map { it.toInt() }
                val c = Calendar.getInstance().apply { if (d != null) time = SimpleDateFormat("yyyy-MM-dd", de).parse(d)!!; set(Calendar.HOUR_OF_DAY, h); set(Calendar.MINUTE, m); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }
                if (d == null && c.timeInMillis < now) c.add(Calendar.DAY_OF_YEAR, 1)
                c.timeInMillis
            }
            else -> 0L
        }
        if (at in 1 until now - 60_000L) return "Der Zeitpunkt ist schon vorbei – wann genau?"
        val day = d ?: if (at > 0) SimpleDateFormat("yyyy-MM-dd", de).format(Date(at)) else SimpleDateFormat("yyyy-MM-dd", de).format(Date())
        add(ctx, t, at, if (at > 0) "" else day, if (at > 0) "erinnerung" else "erledigung")
        if (at > 0) try { Link.remindPc(ctx, t, at) } catch (_: Exception) {}
        return if (at > 0) "Mach ich: ${when (dayWord(at)) { "heute" -> "um"; else -> dayWord(at) + " um" }} ${SimpleDateFormat("H:mm", de).format(Date(at))} – „$t“."
        else {
            val weg = try { Alltag.wegOn(ctx, day) } catch (_: Exception) { null }
            if (weg != null) "Okay, „$t“ ${dayWordD(day)}. Du bist da zu ${weg} unterwegs – ich sag's dir im Briefing und auf dem Heimweg."
            else "Okay, „$t“ ${dayWordD(day)}. Ich erinnere dich, wenn du heimkommst – spätestens um 17 Uhr."
        }
    }

    private fun dayWord(at: Long): String = dayWordD(SimpleDateFormat("yyyy-MM-dd", de).format(Date(at)))
    private fun dayWordD(d: String): String {
        val f = SimpleDateFormat("yyyy-MM-dd", de); val c = Calendar.getInstance()
        val today = f.format(c.time); c.add(Calendar.DAY_OF_YEAR, 1); val tom = f.format(c.time)
        return when (d) { today -> "heute"; tom -> "morgen"; else -> try { "am " + SimpleDateFormat("EEEE", de).format(f.parse(d)!!) } catch (_: Exception) { d } }
    }

    private fun pi(ctx: Context, action: String, id: String, code: Int) = PendingIntent.getBroadcast(ctx, (id.hashCode() and 0xffff) * 4 + code,
        Intent(ctx, RemindReceiver::class.java).setAction(action).putExtra("id", id), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    fun schedule(ctx: Context, id: String, at: Long) {
        val am = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val p = pi(ctx, ACTION_FIRE, id, 0)
        try {
            if (Build.VERSION.SDK_INT >= 31 && !am.canScheduleExactAlarms()) am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, p)
            else am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, p)
        } catch (_: Exception) { try { am.set(AlarmManager.RTC_WAKEUP, at, p) } catch (_: Exception) {} }
    }

    private fun channel(ctx: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CH) != null) return
        val c = NotificationChannel(CH, "Jarvis-Erinnerungen", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Erinnerungen von Jarvis – laut, mit Vibration, poppen oben auf"
            enableVibration(true); vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 700)
            setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION),
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
            lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
        }
        nm.createNotificationChannel(c)
    }

    private fun atHome(ctx: Context): Boolean = try { Alltag.isHome(ctx) } catch (_: Exception) { false }

    /** Erinnerung jetzt zeigen (und zuhause laut sagen). */
    fun fire(ctx: Context, id: String) {
        val a = all(ctx); val o = list(a).firstOrNull { it.optString("id") == id } ?: return
        if (o.optBoolean("done")) return
        val n = o.optInt("fired") + 1
        o.put("fired", n); save(ctx, a)
        show(ctx, id, o.optString("text"), o.optString("kind"), n > 1)
        if (n < 2) schedule(ctx, id, System.currentTimeMillis() + 5 * 60_000L)   // keine Reaktion -> in 5 Min. nochmal
    }

    private fun show(ctx: Context, id: String, text: String, kind: String, again: Boolean) {
        channel(ctx)
        val title = when (kind) { "termin" -> "Termin"; "erledigung" -> "Nicht vergessen"; else -> "Erinnerung" } + (if (again) " (nochmal)" else "")
        val open = PendingIntent.getActivity(ctx, (id.hashCode() and 0xffff) * 4 + 3, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val b = NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.ic_popup_reminder).setContentTitle("⏰ $title")
            .setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text)).setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_REMINDER).setAutoCancel(true).setContentIntent(open)
            .setVibrate(longArrayOf(0, 400, 200, 400, 200, 700)).setDefaults(NotificationCompat.DEFAULT_SOUND)
            .addAction(0, "✓ Erledigt", pi(ctx, ACTION_DONE, id, 1)).addAction(0, "In 15 Min. nochmal", pi(ctx, ACTION_SNOOZE, id, 2))
        try { ctx.getSystemService(NotificationManager::class.java).notify(id.hashCode(), b.build()) } catch (_: Exception) {}
        try {   // Bildschirm kurz an
            val pm = ctx.getSystemService(Context.POWER_SERVICE) as PowerManager
            @Suppress("DEPRECATION") val wl = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP, "jarvis:erinnerung")
            wl.acquire(6000)
        } catch (_: Exception) {}
        if (atHome(ctx)) JarvisService.say(ctx, (if (kind == "termin") "Kurze Erinnerung: " else "Erinnerung: ") + text)
    }

    fun done(ctx: Context, id: String) {
        val a = all(ctx); list(a).firstOrNull { it.optString("id") == id }?.put("done", true); save(ctx, a)
        ctx.getSystemService(NotificationManager::class.java).cancel(id.hashCode())
        (ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager).cancel(pi(ctx, ACTION_FIRE, id, 0))
    }

    fun snooze(ctx: Context, id: String) {
        val a = all(ctx); list(a).firstOrNull { it.optString("id") == id }?.put("fired", 0); save(ctx, a)
        ctx.getSystemService(NotificationManager::class.java).cancel(id.hashCode())
        schedule(ctx, id, System.currentTimeMillis() + 15 * 60_000L)
    }

    /** Offene Erledigungen (ohne Uhrzeit) für einen Tag – für die Briefings ("denk an …"). */
    fun errands(ctx: Context, day: String): List<JSONObject> = list(all(ctx)).filter { it.optString("kind") == "erledigung" && !it.optBoolean("done") && it.optString("datum") == day }

    /**
     * Jede Minute (aus Alltag.tick): verpasste Erinnerungen nachholen (falls der Wecker verschluckt wurde),
     * Kalender-Termine selbst erinnern, Erledigungen ohne Weg zuhause bzw. um 17 Uhr.
     */
    fun tick(ctx: Context, s: JSONObject, homeNow: Boolean, wegToday: Boolean) {
        val now = System.currentTimeMillis()
        val a = all(ctx); var changed = false
        for (o in list(a)) {
            if (o.optBoolean("done")) continue
            val at = o.optLong("at")
            if (at > 0 && o.optInt("fired") == 0 && now >= at && now - at < 6 * 3_600_000L) fire(ctx, o.optString("id"))
            if (at > 0 && now - at > 3 * 86_400_000L) { o.put("done", true); changed = true }   // alte aufräumen
        }
        // Erledigungen ohne Uhrzeit: kein Weg heute -> wenn du ab 13 Uhr heimkommst, sonst um 17 Uhr
        val today = SimpleDateFormat("yyyy-MM-dd", de).format(Date())
        val h = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
        val wasHome = s.optBoolean("rm_home", true); s.put("rm_home", homeNow)
        val arrived = homeNow && !wasHome
        for (o in errands(ctx, today)) {
            if (o.optInt("fired") > 0) continue
            if (!wegToday && ((arrived && h >= 13) || h >= 17)) fire(ctx, o.optString("id"))
        }
        // Kalender-Termine (auch von anderen, z. B. TimeTree): Jarvis erinnert selbst, Standard 15 Min. vorher
        val lead = prefs(ctx).getInt("termin_vorher", 15)
        if (prefs(ctx).getBoolean("termin_erinnern", true)) try {
            val done = s.optJSONObject("rm_cal") ?: JSONObject().also { s.put("rm_cal", it) }
            for (e in Cal.events(ctx, now, now + (lead + 2) * 60_000L)) {
                if (e.allDay) continue
                val k = "${e.id}_${e.begin}"
                if (done.has(k) || e.begin - now > lead * 60_000L + 30_000L) continue
                if (list(a).any { it.optString("kind") == "termin" && it.optLong("at") > 0 && it.optString("text").startsWith(e.title) &&
                        Math.abs(it.optLong("at") - e.begin) < 86_400_000L }) { done.put(k, now); continue }   // hat Jarvis schon eingeplant
                done.put(k, now)
                val txt = e.title + " um " + SimpleDateFormat("H:mm", de).format(Date(e.begin)) + (if (e.place.isNotBlank()) " – ${e.place}" else "")
                val r = add(ctx, txt, 0L, "", "termin"); fire(ctx, r.getString("id"))
            }
            val it = done.keys(); val old = mutableListOf<String>()
            while (it.hasNext()) { val k = it.next(); if (now - done.optLong(k) > 2 * 86_400_000L) old.add(k) }
            old.forEach { done.remove(it) }
        } catch (_: Exception) {}
        if (changed) save(ctx, a)
    }

    /** Nach einem Neustart des Handys: Wecker neu stellen. */
    fun reschedule(ctx: Context) {
        val now = System.currentTimeMillis()
        for (o in list(all(ctx))) if (!o.optBoolean("done") && o.optLong("at") > now) schedule(ctx, o.optString("id"), o.optLong("at"))
    }
}

class RemindReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val id = intent.getStringExtra("id") ?: return
        when (intent.action) {
            Remind.ACTION_FIRE -> Remind.fire(ctx, id)
            Remind.ACTION_DONE -> Remind.done(ctx, id)
            Remind.ACTION_SNOOZE -> Remind.snooze(ctx, id)
        }
    }
}

/** Nach Neustart oder App-Update: Erinnerungs-Wecker neu stellen. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        try { Remind.reschedule(ctx) } catch (_: Exception) {}
    }
}
