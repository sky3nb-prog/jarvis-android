package de.skyler.jarvis

import android.app.Notification
import android.content.Context
import android.service.notification.StatusBarNotification
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Schule: Arbeiten, Tests und Hausaufgaben in einem Kalender (am Handy und am PC eintragbar).
 *  - Selbst eintragen (Kalender in den Einstellungen, am PC unter Schule) oder per Sprache:
 *    "Hausaufgabe Mathe Seite 42 bis Donnerstag", "nächsten Dienstag schreiben wir Englisch über Vokabeln Unit 3".
 *  - schul.cloud: Jarvis liest die Benachrichtigungen mit. Steht darin eine Arbeit/ein Test/eine Hausaufgabe mit Datum,
 *    trägt er sie ein; alles andere merkt er sich, damit er weiß, was ihr gerade macht (hilft beim Lernen).
 *  - Erinnert: Hausaufgabe am Vortag nachmittags; Arbeit 5, 3, 2 und 1 Tag vorher mit kleinem Lern-Stupser, am Tag selbst „Viel Erfolg“.
 */
object Schule {
    const val PKG = "de.heinekingmedia.schulcloud"
    private val de = Locale.GERMANY
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    private fun day(t: Long) = SimpleDateFormat("yyyy-MM-dd", de).format(Date(t))

    fun all(ctx: Context): JSONArray = try { JSONArray(prefs(ctx).getString("schule_eintraege", "[]")) } catch (_: Exception) { JSONArray() }
    fun setAll(ctx: Context, a: JSONArray) {
        val keep = JSONArray(); val cut = day(System.currentTimeMillis() - 30 * 86_400_000L)
        for (i in 0 until a.length()) a.optJSONObject(i)?.let { if (it.optString("datum") >= cut) keep.put(it) }
        prefs(ctx).edit().putString("schule_eintraege", keep.toString()).apply()
    }

    fun add(ctx: Context, art: String, fach: String, text: String, datum: String, quelle: String = "ich"): JSONObject {
        val a = all(ctx)
        for (i in 0 until a.length()) a.optJSONObject(i)?.let {   // gleiche schon da? (z. B. aus schul.cloud doppelt)
            if (it.optString("datum") == datum && it.optString("art") == art && it.optString("fach").equals(fach, true)) {
                if (text.isNotBlank() && !it.optString("text").contains(text)) it.put("text", (it.optString("text") + " · " + text).trim(' ', '·'))
                setAll(ctx, a); return it
            }
        }
        val o = JSONObject().put("id", "s" + System.currentTimeMillis().toString(36)).put("art", art).put("fach", fach.trim())
            .put("text", text.trim()).put("datum", datum).put("done", false).put("quelle", quelle).put("ts", System.currentTimeMillis())
        a.put(o); setAll(ctx, a); return o
    }

    private fun artName(a: String) = when (a) { "arbeit" -> "Arbeit"; "test" -> "Test"; "ha" -> "Hausaufgabe"; else -> "Termin" }

    /** Sprachbefehl (Aktion "schule"). */
    fun spoken(ctx: Context, art: String, fach: String, text: String, datum: String): String {
        if (datum.isBlank()) return "Für wann ist das?"
        val o = add(ctx, art.ifBlank { "ha" }, fach, text, datum)
        val wann = try { SimpleDateFormat("EEEE, d. MMMM", de).format(SimpleDateFormat("yyyy-MM-dd", de).parse(datum)!!) } catch (_: Exception) { datum }
        return "${artName(o.optString("art"))}${if (fach.isNotBlank()) " in $fach" else ""} am $wann ist eingetragen." +
            if (o.optString("art") in setOf("arbeit", "test")) " Ich erinnere dich rechtzeitig und helfe beim Lernen." else " Ich erinnere dich am Tag davor."
    }

    // --- schul.cloud mitlesen ----------------------------------------------------------------------------------
    private val ARBEIT = Regex("(?i)klassenarbeit|klausur|\\barbeit\\b|lernzielkontrolle|\\blzk\\b")
    private val TEST = Regex("(?i)\\btest\\b|vokabeltest|\\bquiz\\b|\\bhü\\b|ex\\b|stegreifaufgabe")
    private val HA = Regex("(?i)hausaufgabe|\\bha\\b|bis (montag|dienstag|mittwoch|donnerstag|freitag|morgen)|abgeben|erledigen")
    private val WD = listOf("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")

    /** Datum im Text finden: 21.11., 21.11.2026, morgen, übermorgen, (nächsten) Dienstag. */
    fun findDate(t: String, now: Long = System.currentTimeMillis()): String? {
        val l = t.lowercase()
        Regex("(\\d{1,2})\\.(\\d{1,2})\\.(\\d{2,4})?").find(l)?.let { m ->
            val c = Calendar.getInstance()
            val d = m.groupValues[1].toInt(); val mo = m.groupValues[2].toInt()
            if (d in 1..31 && mo in 1..12) {
                var y = m.groupValues[3].takeIf { it.isNotBlank() }?.toInt()?.let { if (it < 100) it + 2000 else it } ?: c.get(Calendar.YEAR)
                c.set(y, mo - 1, d, 12, 0)
                if (m.groupValues[3].isBlank() && c.timeInMillis < now - 60 * 86_400_000L) { y += 1; c.set(Calendar.YEAR, y) }
                return day(c.timeInMillis)
            }
        }
        if (l.contains("übermorgen")) return day(now + 2 * 86_400_000L)
        if (Regex("\\bmorgen\\b").containsMatchIn(l)) return day(now + 86_400_000L)
        for ((i, w) in WD.withIndex()) if (Regex("\\b$w").containsMatchIn(l)) {
            val c = Calendar.getInstance().apply { timeInMillis = now }
            val today = (c.get(Calendar.DAY_OF_WEEK) + 5) % 7   // Mo=0
            var add = (i - today + 7) % 7; if (add == 0) add = 7
            return day(now + add * 86_400_000L)
        }
        return null
    }

    private fun findFach(ctx: Context, t: String): String {
        val fächer = mutableSetOf("Mathe", "Deutsch", "Englisch", "Französisch", "Latein", "Spanisch", "Bio", "Biologie", "Chemie", "Physik", "Geschichte",
            "Erdkunde", "Geografie", "Gemeinschaftskunde", "Gemeinschaftskunde", "WBS", "Religion", "Ethik", "Sport", "Kunst", "Musik", "Informatik", "NwT", "Technik", "AES")
        try { val p = Melden.plan(ctx); for (k in listOf("mo", "di", "mi", "do", "fr")) p.optJSONArray(k)?.let { a -> for (i in 0 until a.length()) a.optJSONObject(i)?.optString("fach")?.takeIf { it.isNotBlank() }?.let { fächer.add(it) } } } catch (_: Exception) {}
        return fächer.firstOrNull { Regex("(?i)\\b${Regex.escape(it)}").containsMatchIn(t) }?.let { if (it == "Biologie") "Bio" else it } ?: ""
    }

    fun onPosted(ctx: Context, sbn: StatusBarNotification) {
        if (sbn.packageName != PKG) return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        val ex = n.extras ?: return
        val title = (ex.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE) ?: ex.getCharSequence(Notification.EXTRA_TITLE))?.toString()?.trim() ?: ""
        val text = (ex.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: ex.getCharSequence(Notification.EXTRA_TEXT))?.toString()?.trim() ?: return
        if (text.isBlank()) return
        // merken (was ihr gerade macht)
        val log = try { JSONArray(prefs(ctx).getString("schulcloud_log", "[]")) } catch (_: Exception) { JSONArray() }
        for (i in 0 until log.length()) if (log.optJSONObject(i)?.optString("text") == text) return   // schon gesehen
        log.put(JSONObject().put("t", System.currentTimeMillis()).put("von", title).put("text", text.take(600)))
        while (log.length() > 80) log.remove(0)
        prefs(ctx).edit().putString("schulcloud_log", log.toString()).apply()
        // Arbeit/Test/Hausaufgabe mit Datum? -> eintragen
        val all = "$title $text"
        val art = when { ARBEIT.containsMatchIn(all) -> "arbeit"; TEST.containsMatchIn(all) -> "test"; HA.containsMatchIn(all) -> "ha"; else -> return }
        val datum = findDate(text) ?: return
        if (datum < day(System.currentTimeMillis())) return
        val fach = findFach(ctx, all)
        val thema = Regex("(?i)(?:thema|themen|über|zu|inhalt)[:\\s]+([^.!?\\n]{3,80})").find(text)?.groupValues?.get(1)?.trim() ?: text.take(80)
        add(ctx, art, fach, thema, datum, "schul.cloud")
        val wann = try { SimpleDateFormat("EEEE, d.M.", de).format(SimpleDateFormat("yyyy-MM-dd", de).parse(datum)!!) } catch (_: Exception) { datum }
        Melden.note(ctx, "Aus schul.cloud eingetragen", "${artName(art)}${if (fach.isNotBlank()) " $fach" else ""} am $wann – $thema")
    }

    // --- Erinnern ---------------------------------------------------------------------------------------------
    fun tick(ctx: Context, say: (String) -> Unit) {
        val now = System.currentTimeMillis(); val c = Calendar.getInstance(); val h = c.get(Calendar.HOUR_OF_DAY)
        val today = day(now); val p = prefs(ctx)
        val a = all(ctx)
        val items = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { !it.optBoolean("done") }
        fun daysTo(d: String) = try { ((SimpleDateFormat("yyyy-MM-dd", de).parse(d)!!.time - SimpleDateFormat("yyyy-MM-dd", de).parse(today)!!.time) / 86_400_000L).toInt() } catch (_: Exception) { -99 }
        fun once(k: String): Boolean { val key = "sch_$k|$today"; if (p.getBoolean(key, false)) return false; p.edit().putBoolean(key, true).apply(); return true }
        if (h in 16..19) {
            val ha = items.filter { it.optString("art") == "ha" && daysTo(it.optString("datum")) == 1 }
            if (ha.isNotEmpty() && once("ha")) say("Für morgen hast du noch Hausaufgaben: " + ha.joinToString(", ") { listOf(it.optString("fach"), it.optString("text")).filter { s -> s.isNotBlank() }.joinToString(" – ") } + ".")
            for (x in items.filter { it.optString("art") in setOf("arbeit", "test") }) {
                val d = daysTo(x.optString("datum"))
                if (d in setOf(5, 3, 2, 1) && once("lern_${x.optString("id")}")) {
                    val f = x.optString("fach").ifBlank { "die" }; val t = x.optString("text")
                    say(when (d) {
                        1 -> "Morgen ist die ${artName(x.optString("art"))} in $f. Heute nochmal kurz alles durchgehen und früh schlafen – soll ich dich abfragen?"
                        2 -> "Übermorgen $f${if (t.isNotBlank()) " ($t)" else ""}. Zeit für eine Lernrunde – sag „frag mich ab“, wenn ich helfen soll."
                        else -> "In $d Tagen schreibst du $f${if (t.isNotBlank()) " – $t" else ""}. Fang heute mit 20 Minuten an, dann wird's entspannt."
                    })
                }
            }
        }
        if (h in 6..8) {
            val heute = items.filter { it.optString("art") in setOf("arbeit", "test") && it.optString("datum") == today }
            if (heute.isNotEmpty() && once("erfolg")) say("Heute: ${heute.joinToString(" und ") { artName(it.optString("art")) + " " + it.optString("fach") }}. Du schaffst das – viel Erfolg!")
        }
    }

    /** Für die KI: was ansteht und was zuletzt in schul.cloud kam (damit er beim Lernen helfen kann). */
    fun prompt(ctx: Context): String = try {
        val today = day(System.currentTimeMillis())
        val a = all(ctx); val up = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { !it.optBoolean("done") && it.optString("datum") >= today }.sortedBy { it.optString("datum") }.take(8)
        val log = JSONArray(prefs(ctx).getString("schulcloud_log", "[]"))
        val last = (maxOf(0, log.length() - 8) until log.length()).mapNotNull { log.optJSONObject(it) }.joinToString(" | ") { it.optString("von") + ": " + it.optString("text").take(160) }
        (if (up.isNotEmpty()) "Schule – steht an: " + up.joinToString("; ") { "${it.optString("datum")} ${artName(it.optString("art"))} ${it.optString("fach")} ${it.optString("text")}".trim() } + ". " else "") +
            (if (last.isNotBlank()) "Zuletzt in schul.cloud: $last. " else "") +
            (if (up.isNotEmpty() || last.isNotBlank()) "Wenn er lernen will („frag mich ab“, „erklär mir …“): stell ihm passende Fragen zum Thema, eine nach der anderen, und erklär kurz, was falsch war." else "")
    } catch (_: Exception) { "" }
}
