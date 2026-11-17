package de.skyler.jarvis

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Termine aus WhatsApp: Wird in einem Chat etwas fest ausgemacht („Samstag 19 Uhr Kino?“ – „Jo passt“), trägt Jarvis es
 * in den Kalender ein und sagt Bescheid (mit „Rückgängig“). Wird es später abgesagt oder verschoben – auch per
 * Sprachnachricht –, nimmt er es wieder raus bzw. verschiebt es.
 * Die KI bekommt nur die letzten Nachrichten des Chats und entscheidet: neu / abgesagt / verschoben / nichts.
 */
object WaTermine {
    private const val TAG = "JarvisWaTermin"
    private const val CH = "jarvis_watermin"
    private val de = Locale.GERMANY
    // Vorfilter: nur wenn eine Nachricht nach Verabredung klingt, fragen wir die KI (spart Daten)
    private val HINT = Regex("\\b(heute|morgen|übermorgen|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|wochenende|" +
        "um \\d{1,2}|\\d{1,2}[:.]\\d{2}|\\d{1,2} ?uhr|uhr\\b|treffen|termin|verabred|kommst du|bist du dabei|zeit\\?|klappt|passt|" +
        "absag|abgesagt|fällt aus|fällt flach|kann (doch )?nicht|klappt (doch )?nicht|verschieb|später|stattdessen|\\d{1,2}\\.\\d{1,2}\\.)", RegexOption.IGNORE_CASE)

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun on(ctx: Context) = prefs(ctx).getBoolean("wa_termine", true)
    fun setOn(ctx: Context, v: Boolean) = prefs(ctx).edit().putBoolean("wa_termine", v).apply()

    private fun saved(ctx: Context): JSONArray = try { JSONArray(prefs(ctx).getString("wa_termine_list", "[]")) } catch (_: Exception) { JSONArray() }
    private fun store(ctx: Context, a: JSONArray) {
        val now = System.currentTimeMillis()
        val keep = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { it.optLong("start") > now - 86_400_000L }.takeLast(40)
        prefs(ctx).edit().putString("wa_termine_list", JSONArray(keep).toString()).apply()
    }
    fun upcoming(ctx: Context): List<JSONObject> = saved(ctx).let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { it.optLong("start") > System.currentTimeMillis() } }

    @Volatile private var lastAsk = HashMap<String, Long>()

    /** Aus Chats.onPosted: neue Nachricht (Text oder umgewandelte Sprachnachricht) in einem Chat. */
    fun onMessage(ctx: Context, chat: String, sender: String, text: String, verlauf: JSONArray) {
        if (!on(ctx) || text.isBlank() || Leute.isIgnored(ctx, Chats.norm(chat))) return
        if (!HINT.containsMatchIn(text) && upcoming(ctx).none { Chats.norm(it.optString("chat")) == Chats.norm(chat) }) return
        val key = prefs(ctx).getString("groq_key", "") ?: ""
        if (key.isBlank()) return
        synchronized(lastAsk) {   // höchstens alle 20 Sekunden pro Chat
            val ck = Chats.norm(chat)
            if (System.currentTimeMillis() - (lastAsk[ck] ?: 0L) < 20_000L) return
            lastAsk[ck] = System.currentTimeMillis()
        }
        Thread({ try { decide(ctx, key, chat, sender, text, verlauf) } catch (e: Exception) { Log.w(TAG, "$e") } }, "jarvis-watermin").start()
    }

    private fun decide(ctx: Context, key: String, chat: String, sender: String, text: String, verlauf: JSONArray) {
        val mine = upcoming(ctx).filter { Chats.norm(it.optString("chat")) == Chats.norm(chat) }
        val hist = (0 until verlauf.length()).mapNotNull { verlauf.optJSONObject(it) }.takeLast(10).joinToString("\n") { o ->
            val t = SimpleDateFormat("EEE dd.MM. HH:mm", de).format(Date(o.optLong("t")))
            "[$t] ${if (o.optString("von") == "ich") "ICH" else o.optString("von")}: ${o.optString("text")}"
        }
        val sys = """Heute ist ${SimpleDateFormat("EEEE, dd.MM.yyyy, HH:mm", de).format(Date())} Uhr. Du liest einen WhatsApp-Chat ("$chat") des Nutzers (ICH).
Entscheide, ob in den letzten Nachrichten ein Treffen/Termin FEST ausgemacht, abgesagt oder verschoben wurde.
Fest = beide Seiten haben zugestimmt (z. B. "Samstag 19 Uhr Kino?" – "jo passt") oder es wurde klar beschlossen. Nur eine Frage ohne Zusage = "nichts".
Schon eingetragen aus diesem Chat: ${if (mine.isEmpty()) "nichts" else mine.joinToString("; ") { "${it.optString("titel")} am ${SimpleDateFormat("EEE dd.MM. HH:mm", de).format(Date(it.optLong("start")))}" }}
Antworte NUR mit JSON:
{"art":"neu|abgesagt|verschoben|nichts","titel":"<kurz, z. B. Kino mit Max>","datum":"<yyyy-MM-dd>","zeit":"<HH:mm oder leer für ganztägig>","ort":"<oder leer>","welcher":"<bei abgesagt/verschoben: Titel des eingetragenen Termins>"}
Bei "neu" nur, wenn der Termin noch NICHT eingetragen ist. "morgen" = nächster Tag, Wochentage = der nächste solche Tag."""
        val raw = Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", sys))
            .put(JSONObject().put("role", "user").put("content", "$hist\n[neu] $sender: $text")), 250, json = true)
        val j = JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw)?.value ?: raw)
        when (j.optString("art")) {
            "neu" -> add(ctx, chat, j)
            "abgesagt" -> cancel(ctx, chat, j.optString("welcher").ifBlank { j.optString("titel") }, null)
            "verschoben" -> cancel(ctx, chat, j.optString("welcher").ifBlank { j.optString("titel") }, j)
        }
    }

    private fun startOf(j: JSONObject): Pair<Long, Boolean>? {
        val d = j.optString("datum").takeIf { Regex("^\\d{4}-\\d{2}-\\d{2}$").matches(it) } ?: return null
        val z = j.optString("zeit").takeIf { Regex("^\\d{1,2}:\\d{2}$").matches(it) }
        return try {
            if (z != null) SimpleDateFormat("yyyy-MM-dd HH:mm", de).parse("$d $z")!!.time to false
            else SimpleDateFormat("yyyy-MM-dd", de).parse(d)!!.time to true
        } catch (_: Exception) { null }
    }

    private fun add(ctx: Context, chat: String, j: JSONObject, moved: Boolean = false) {
        val titel = j.optString("titel").trim().ifBlank { return }
        val (start, allDay) = startOf(j) ?: return
        if (start < System.currentTimeMillis() - 3600_000L) return
        // schon da? (gleicher Chat, ±3 h)
        if (upcoming(ctx).any { Chats.norm(it.optString("chat")) == Chats.norm(chat) && Math.abs(it.optLong("start") - start) < 3 * 3600_000L }) return
        val a = JSONObject().put("title", titel)
            .put("start", SimpleDateFormat(if (allDay) "yyyy-MM-dd" else "yyyy-MM-dd'T'HH:mm", de).format(Date(start)))
            .put("minutes", 120).put("remind", -1).put("notes", "Aus WhatsApp ($chat) – von Jarvis eingetragen")
        j.optString("ort").takeIf { it.isNotBlank() && it != "null" }?.let { a.put("location", it) }
        val r = Cal.add(ctx, a)
        if (!r.startsWith("Eingetragen")) { Log.w(TAG, r); return }
        if (!allDay) try { Remind.add(ctx, "$titel um ${SimpleDateFormat("H:mm", de).format(Date(start))}", start - 60 * 60_000L, "", "termin") } catch (_: Exception) {}
        val l = saved(ctx); val id = "w" + System.currentTimeMillis()
        l.put(JSONObject().put("id", id).put("chat", chat).put("titel", titel).put("start", start).put("allday", allDay)); store(ctx, l)
        val wann = SimpleDateFormat(if (allDay) "EEEE d.M." else "EEEE d.M., HH:mm 'Uhr'", de).format(Date(start))
        note(ctx, id, if (moved) "Termin verschoben" else "Termin aus WhatsApp", "$titel – $wann (aus dem Chat mit $chat). Steht im Kalender.", true)
    }

    private fun cancel(ctx: Context, chat: String, welcher: String, moveTo: JSONObject?) {
        val l = saved(ctx)
        val mine = (0 until l.length()).mapNotNull { l.optJSONObject(it) }.filter { Chats.norm(it.optString("chat")) == Chats.norm(chat) && it.optLong("start") > System.currentTimeMillis() }
        val w = Chats.norm(welcher)
        val hit = mine.firstOrNull { w.isNotBlank() && (Chats.norm(it.optString("titel")).contains(w) || w.contains(Chats.norm(it.optString("titel")))) }
            ?: mine.minByOrNull { it.optLong("start") } ?: return
        removeFromCal(ctx, hit)
        val rest = JSONArray((0 until l.length()).mapNotNull { l.optJSONObject(it) }.filter { it.optString("id") != hit.optString("id") }); store(ctx, rest)
        if (moveTo != null && startOf(moveTo) != null) {
            if (moveTo.optString("titel").isBlank()) moveTo.put("titel", hit.optString("titel"))
            add(ctx, chat, moveTo, moved = true)
        } else note(ctx, hit.optString("id"), "Termin abgesagt", "${hit.optString("titel")} wurde im Chat mit $chat abgesagt – hab's aus dem Kalender genommen.", false)
    }

    private fun removeFromCal(ctx: Context, o: JSONObject) {
        try { Cal.delete(ctx, o.optString("titel"), SimpleDateFormat("yyyy-MM-dd", de).format(Date(o.optLong("start")))) } catch (e: Exception) { Log.w(TAG, "löschen: $e") }
    }

    /** „Rückgängig“ in der Benachrichtigung. */
    fun undo(ctx: Context, id: String) {
        val l = saved(ctx)
        val o = (0 until l.length()).mapNotNull { l.optJSONObject(it) }.firstOrNull { it.optString("id") == id } ?: return
        removeFromCal(ctx, o)
        store(ctx, JSONArray((0 until l.length()).mapNotNull { l.optJSONObject(it) }.filter { it.optString("id") != id }))
        ctx.getSystemService(NotificationManager::class.java).cancel(id.hashCode())
    }

    private fun note(ctx: Context, id: String, title: String, text: String, undo: Boolean) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "Termine aus WhatsApp", NotificationManager.IMPORTANCE_DEFAULT))
        val b = NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.ic_menu_my_calendar).setContentTitle(title)
            .setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text)).setAutoCancel(true)
        if (undo) b.addAction(0, "Rückgängig", PendingIntent.getBroadcast(ctx, id.hashCode(),
            Intent(ctx, WaTerminReceiver::class.java).putExtra("id", id), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        try { nm.notify(id.hashCode(), b.build()) } catch (_: Exception) {}
    }
}

class WaTerminReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val id = intent.getStringExtra("id") ?: return
        Thread { try { WaTermine.undo(ctx, id) } catch (_: Exception) {} }.start()
    }
}
