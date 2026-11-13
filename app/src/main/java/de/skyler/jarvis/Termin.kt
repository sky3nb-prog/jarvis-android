package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Termine sicher eintragen: "Trag mir in 48 Stunden Zahnarzt in den Kalender ein und erinner mich dran."
 * Die KI liest nur heraus, WAS und WANN (relativ in Minuten oder als Datum/Uhrzeit) – das Rechnen, Eintragen und
 * Nachprüfen macht der Code. Gesagt wird nur, was wirklich im Kalender steht. Danach erinnert auch der PC.
 */
object Termin {
    private val de = Locale.GERMANY
    private val VERB = Regex("\\b(?:ein)?trag\\w*|\\beinträg\\w*|\\bschreib\\w*|\\bnotier\\w*|\\berstell\\w*|\\banleg\\w*|\\bsetz\\w*|\\bfüg\\w*|" +
        "\\bplan\\w*|\\bleg\\w*\\b.*\\ban\\b|\\bin (?:den |meinen |dein |deinen )?kalender\\b.*\\bein\\b|\\bmach\\w*\\b.*\\btermin|\\bmerk\\w*\\b.*\\bkalender|\\berinner\\w*",
        RegexOption.IGNORE_CASE)
    private val WORD = Regex("\\bkalender\\w*|\\btermin\\w*", RegexOption.IGNORE_CASE)
    private val QUESTION = Regex("^(?:was|welche\\w*|wann|wie viele|hab ich|habe ich|steht|zeig\\w*|lies|sag mir was)\\b", RegexOption.IGNORE_CASE)

    /** Will er etwas eintragen? ("Trag … in den Kalender ein", "kannst du mir was im Kalender eintragen in 48 Stunden") */
    fun wants(text: String): Boolean {
        var low = text.lowercase().trim()
        low = low.replace(Regex("^(?:jarvis|friday|hey|okay|ok)[ ,]+"), "").replace(Regex("^(?:kannst du|könntest du|würdest du|bitte)\\s+(?:mir\\s+)?"), "")
        if (QUESTION.containsMatchIn(low) && !Regex("\\b(?:ein)?trag|einträg").containsMatchIn(low)) return false
        return (WORD.containsMatchIn(low) && VERB.containsMatchIn(low)) || low.startsWith("neuer termin") ||
            Regex("^(?:kannst du mich |du sollst mich )?erinner\\w* (?:mich|du mich)\\b").containsMatchIn(low)   // Erinnerungen auch in den Kalender (und an den PC)
    }

    class R(val say: String, val ok: Boolean, val title: String = "", val start: Long = 0, val remindAt: Long = 0)

    fun add(ctx: Context, key: String, text: String): R {
        val now = Date()
        val sys = """Heute ist ${SimpleDateFormat("EEEE, dd.MM.yyyy, HH:mm", de).format(now)} Uhr. Lies aus dem Satz einen Kalendertermin heraus.
Antworte NUR mit JSON:
{"titel":"<kurzer Titel, z. B. Zahnarzt>",
 "relativ_minuten": <Minuten ab jetzt, NUR wenn er relativ spricht: "in 48 Stunden" = 2880, "in 2 Stunden" = 120, "in einer Woche" = 10080; sonst null>,
 "datum":"<yyyy-MM-dd oder null>", "zeit":"<HH:mm oder null>",
 "ganztaegig": <true nur wenn kein Zeitpunkt genannt und nicht relativ>,
 "dauer_minuten": <Standard 60>,
 "erinnern_vorher": <Minuten vorher erinnern; "erinner mich dran" ohne Angabe = 0 bei relativen Zeiten, sonst 30>,
 "ort":"<oder leer>"}
"morgen" = nächster Tag, "übermorgen" = in 2 Tagen, Wochentage = der nächste solche Tag. "morgen früh" = 09:00, "mittags" = 12:00, "nachmittags" = 15:00, "abends" = 19:00."""
        val raw = Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", sys))
            .put(JSONObject().put("role", "user").put("content", text)), 300, json = true)
        val j = JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw)?.value ?: raw)
        val title = j.optString("titel").trim().ifBlank { return R("Wie soll der Termin heißen?", false) }

        // Zeitpunkt selbst ausrechnen
        val rel = if (j.isNull("relativ_minuten")) -1 else j.optInt("relativ_minuten", -1)
        val datum = j.optString("datum").takeIf { Regex("^\\d{4}-\\d{2}-\\d{2}$").matches(it) }
        val zeit = j.optString("zeit").takeIf { Regex("^\\d{1,2}:\\d{2}$").matches(it) }
        var allDay = false
        val start: Long = when {
            rel > 0 -> (now.time + rel * 60_000L).let { Math.round(it / 300_000.0) * 300_000L }   // auf 5 Minuten runden
            datum != null && zeit != null -> SimpleDateFormat("yyyy-MM-dd HH:mm", de).parse("$datum $zeit")!!.time
            datum != null -> { allDay = true; SimpleDateFormat("yyyy-MM-dd", de).parse(datum)!!.time }
            zeit != null -> {
                val (h, m) = zeit.split(":").map { it.toInt() }
                val c = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, h); set(Calendar.MINUTE, m); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }
                if (c.timeInMillis < now.time) c.add(Calendar.DAY_OF_MONTH, 1)
                c.timeInMillis
            }
            else -> return R("Für wann soll ich „$title“ eintragen?", false)
        }
        if (start < now.time - 3600_000L) return R("Der Zeitpunkt für „$title“ liegt in der Vergangenheit. Sag mir bitte nochmal, wann.", false)
        val remind = j.optInt("erinnern_vorher", if (rel > 0) 0 else 30).coerceIn(0, 7 * 24 * 60)

        val a = JSONObject().put("title", title)
            .put("start", SimpleDateFormat(if (allDay) "yyyy-MM-dd" else "yyyy-MM-dd'T'HH:mm", de).format(Date(start)))
            .put("minutes", j.optInt("dauer_minuten", 60).coerceIn(5, 24 * 60))
            .put("remind", if (allDay) (if (j.has("erinnern_vorher")) remind else -1) else remind)
        j.optString("ort").takeIf { it.isNotBlank() && it != "null" }?.let { a.put("location", it) }
        val res = Cal.add(ctx, a)
        if (!res.startsWith("Eingetragen")) return R(res, false)

        // nachprüfen, ob er wirklich drinsteht
        val found = try {
            ctx.contentResolver.query(android.provider.CalendarContract.Events.CONTENT_URI, arrayOf(android.provider.CalendarContract.Events._ID),
                "${android.provider.CalendarContract.Events.TITLE} = ? AND ${android.provider.CalendarContract.Events.DTSTART} >= ? AND ${android.provider.CalendarContract.Events.DTSTART} <= ? AND ${android.provider.CalendarContract.Events.DELETED} = 0",
                arrayOf(title, (start - 36 * 3600_000L).toString(), (start + 36 * 3600_000L).toString()), null)?.use { it.count > 0 } ?: true
        } catch (_: Exception) { true }
        if (!found) return R("Ich wollte „$title“ eintragen, finde es aber nicht in deinem Kalender. Schau bitte in der App, ob der Kalender erlaubt ist.", false)

        val day = SimpleDateFormat("EEEE, d. MMMM", de).format(Date(start))
        val at = if (allDay) day else "$day um ${SimpleDateFormat("H:mm", de).format(Date(start))} Uhr"
        val remindAt = if (allDay) start + 9 * 3600_000L else start - remind * 60_000L   // ganztägig: um 9 Uhr am Tag
        val rem = when {
            allDay -> ""
            remind == 0 -> " Ich erinnere dich genau dann."
            remind < 60 -> " Ich erinnere dich $remind Minuten vorher."
            else -> " Ich erinnere dich ${remind / 60} Stunde${if (remind >= 120) "n" else ""} vorher."
        }
        return R("Steht im Kalender: $title am $at.$rem", true, title, start, remindAt)
    }
}
