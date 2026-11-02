package de.skyler.jarvis

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.provider.CalendarContract
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/** Kalender auf dem Handy (Google bzw. Samsung): Termine eintragen, vorlesen, löschen – ohne dass eine App aufgeht. */
object Cal {
    private val de = Locale.GERMANY

    private fun can(ctx: Context, p: String) = ContextCompat.checkSelfPermission(ctx, p) == PackageManager.PERMISSION_GRANTED
    private const val NO_PERM = "Ich darf deinen Kalender noch nicht benutzen. Öffne einmal die Jarvis-App und erlaube den Kalender."

    private fun parse(s: String): Pair<Date, Boolean>? {
        val t = s.trim().replace(' ', 'T')
        for ((f, allDay) in listOf("yyyy-MM-dd'T'HH:mm:ss" to false, "yyyy-MM-dd'T'HH:mm" to false, "yyyy-MM-dd" to true)) {
            try { return SimpleDateFormat(f, de).apply { isLenient = false }.parse(t)!! to allDay } catch (_: Exception) {}
        }
        return null
    }

    /** Ein beschreibbarer Kalender, am liebsten der Haupt-Kalender des Google-Kontos. */
    private fun calendarId(ctx: Context): Long? {
        val cols = arrayOf(CalendarContract.Calendars._ID, CalendarContract.Calendars.IS_PRIMARY,
            CalendarContract.Calendars.ACCOUNT_TYPE, CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL, CalendarContract.Calendars.VISIBLE)
        val want = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getLong("calendar_id", -1L)
        var best: Long? = null; var score = -1
        ctx.contentResolver.query(CalendarContract.Calendars.CONTENT_URI, cols, null, null, null)?.use { c ->
            while (c.moveToNext()) {
                if (c.getInt(3) < CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR) continue
                val id = c.getLong(0)
                if (id == want) return id
                var sc = 0
                if (c.getInt(4) == 1) sc += 1
                if (c.getString(2) == "com.google") sc += 4
                if (c.getInt(1) == 1) sc += 2
                if (sc > score) { score = sc; best = id }
            }
        }
        return best
    }

    fun add(ctx: Context, a: JSONObject): String {
        if (!can(ctx, Manifest.permission.WRITE_CALENDAR)) return NO_PERM
        val title = a.optString("title").trim().ifBlank { return "Wie soll der Termin heißen?" }
        val (start, dayOnly) = parse(a.optString("start")) ?: return "Für wann soll ich das eintragen?"
        val allDay = dayOnly || a.optBoolean("allday", false)
        val cal = calendarId(ctx) ?: return "Ich finde auf dem Handy keinen Kalender, in den ich schreiben darf."
        val endD = parse(a.optString("end"))?.first
        val v = ContentValues()
        v.put(CalendarContract.Events.CALENDAR_ID, cal)
        v.put(CalendarContract.Events.TITLE, title)
        a.optString("location").takeIf { it.isNotBlank() }?.let { v.put(CalendarContract.Events.EVENT_LOCATION, it) }
        a.optString("notes").takeIf { it.isNotBlank() }?.let { v.put(CalendarContract.Events.DESCRIPTION, it) }
        if (allDay) {
            val utc = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply {
                val l = Calendar.getInstance().apply { time = start }
                clear(); set(l.get(Calendar.YEAR), l.get(Calendar.MONTH), l.get(Calendar.DAY_OF_MONTH))
            }
            v.put(CalendarContract.Events.DTSTART, utc.timeInMillis)
            v.put(CalendarContract.Events.DTEND, utc.timeInMillis + 86_400_000L)
            v.put(CalendarContract.Events.ALL_DAY, 1)
            v.put(CalendarContract.Events.EVENT_TIMEZONE, "UTC")
        } else {
            val minutes = a.optInt("minutes", 60).coerceIn(5, 24 * 60)
            v.put(CalendarContract.Events.DTSTART, start.time)
            v.put(CalendarContract.Events.DTEND, endD?.takeIf { it.after(start) }?.time ?: (start.time + minutes * 60_000L))
            v.put(CalendarContract.Events.EVENT_TIMEZONE, TimeZone.getDefault().id)
        }
        val uri = ctx.contentResolver.insert(CalendarContract.Events.CONTENT_URI, v) ?: return "Das Eintragen hat nicht geklappt."
        val remind = a.optInt("remind", if (allDay) -1 else 30)
        if (remind >= 0) {
            val r = ContentValues()
            r.put(CalendarContract.Reminders.EVENT_ID, ContentUris.parseId(uri))
            r.put(CalendarContract.Reminders.MINUTES, remind)
            r.put(CalendarContract.Reminders.METHOD, CalendarContract.Reminders.METHOD_ALERT)
            try { ctx.contentResolver.insert(CalendarContract.Reminders.CONTENT_URI, r) } catch (_: Exception) {}
        }
        val day = SimpleDateFormat("EEEE, d. MMMM", de).format(start)
        return if (allDay) "Eingetragen: $title am $day." else "Eingetragen: $title am $day um ${SimpleDateFormat("H:mm", de).format(start)} Uhr."
    }

    data class Ev(val id: Long, val title: String, val begin: Long, val allDay: Boolean, val place: String)

    fun events(ctx: Context, from: Long, to: Long): List<Ev> {
        if (!can(ctx, Manifest.permission.READ_CALENDAR)) return emptyList()
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().also {
            ContentUris.appendId(it, from); ContentUris.appendId(it, to)
        }.build()
        val cols = arrayOf(CalendarContract.Instances.EVENT_ID, CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN,
            CalendarContract.Instances.ALL_DAY, CalendarContract.Instances.EVENT_LOCATION)
        val out = mutableListOf<Ev>()
        try {
            ctx.contentResolver.query(uri, cols, null, null, CalendarContract.Instances.BEGIN + " ASC")?.use { c ->
                while (c.moveToNext()) out.add(Ev(c.getLong(0), c.getString(1) ?: "Termin", c.getLong(2), c.getInt(3) == 1, c.getString(4) ?: ""))
            }
        } catch (_: Exception) {}
        return out
    }

    private fun dayStart(d: Date): Long = Calendar.getInstance().apply {
        time = d; set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
    }.timeInMillis

    fun describe(list: List<Ev>): String = list.take(15).joinToString("; ") { e ->
        val d = Date(e.begin)
        SimpleDateFormat("EEEE d.M.", de).format(d) + (if (e.allDay) " ganztägig" else " " + SimpleDateFormat("H:mm", de).format(d)) +
            " " + e.title + (if (e.place.isNotBlank()) " (${e.place})" else "")
    }

    fun list(ctx: Context, from: String, days: Int): String {
        if (!can(ctx, Manifest.permission.READ_CALENDAR)) return NO_PERM
        val start = parse(from)?.first?.let { dayStart(it) } ?: dayStart(Date())
        val n = days.coerceIn(1, 31)
        val list = events(ctx, start, start + n * 86_400_000L)
        return if (list.isEmpty()) "KALENDER: keine Termine in diesem Zeitraum." else "KALENDER: " + describe(list)
    }

    /** Für den Hinweistext an die KI: was heute und morgen ansteht. */
    fun context(ctx: Context): String {
        if (!can(ctx, Manifest.permission.READ_CALENDAR)) return ""
        val list = events(ctx, System.currentTimeMillis() - 3600_000L, dayStart(Date()) + 2 * 86_400_000L)
        return if (list.isEmpty()) "Im Kalender steht heute und morgen nichts." else "Kalender heute und morgen: " + describe(list) + "."
    }

    fun delete(ctx: Context, title: String, date: String): String {
        if (!can(ctx, Manifest.permission.WRITE_CALENDAR)) return NO_PERM
        val want = Wake.norm(title)
        if (want.isBlank()) return "Welchen Termin soll ich löschen?"
        val from = parse(date)?.first?.let { dayStart(it) } ?: dayStart(Date())
        val to = if (parse(date) != null) from + 86_400_000L else from + 60 * 86_400_000L
        val hit = events(ctx, from, to).firstOrNull { Wake.norm(it.title).contains(want) || want.contains(Wake.norm(it.title)) }
            ?: return "Den Termin $title finde ich nicht."
        val n = ctx.contentResolver.delete(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, hit.id), null, null)
        return if (n > 0) "Gelöscht: ${hit.title} am ${SimpleDateFormat("EEEE, d. MMMM", de).format(Date(hit.begin))}." else "Löschen ging nicht."
    }
}
