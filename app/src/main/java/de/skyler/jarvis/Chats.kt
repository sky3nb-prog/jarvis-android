package de.skyler.jarvis

import android.app.Notification
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Base64
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * WhatsApp-Nachrichten wichtiger Leute an den PC melden (der sagt sie an, auch mitten im Spiel)
 * und die Antwort über die "Antworten"-Funktion der Benachrichtigung zurückschicken – WhatsApp geht dabei nirgends auf.
 *
 * Wer wichtig ist, steht in den Einstellungen ("Wichtige Leute", Namen wie in WhatsApp). Dazu kommen Chats, in die
 * Jarvis "unter seinem Namen" geschrieben hat (24 Stunden lang, Auftrag "watch" vom PC).
 * Sprachnachrichten: die Datei aus dem WhatsApp-Ordner (braucht "Zugriff auf alle Dateien"), mit Groq in Text umgewandelt.
 */
object Chats {
    private const val TAG = "JarvisChats"
    const val DEFAULT = "Mama, Saya, Opa, Elijah, Tobi, Marius, Jannis"
    private val PKGS = setOf("com.whatsapp", "com.whatsapp.w4b")

    private class Reply(val action: Notification.Action, val at: Long)
    private val repliers = HashMap<String, Reply>()          // Chat -> Antworten-Knopf der Benachrichtigung
    private val seen = HashMap<String, Long>()                // Chat -> Zeit der letzten gemeldeten Nachricht
    private val recent = ArrayDeque<String>()                 // gegen doppelte Meldungen
    private val termSeen = LinkedHashSet<String>()            // schon auf Termine geprüft

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun norm(s: String) = s.lowercase().replace(Regex("[^\\p{L}\\p{N} ]"), " ").replace(Regex("\\s+"), " ").trim()

    fun important(ctx: Context): List<String> =
        (prefs(ctx).getString("wichtig", Chats.DEFAULT) ?: "").split(',', ';', '\n').map { norm(it) }.filter { it.isNotBlank() }

    private fun watched(ctx: Context): List<String> {
        val o = try { JSONObject(prefs(ctx).getString("watch", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        val now = System.currentTimeMillis() / 1000
        return o.keys().asSequence().filter { o.optLong(it) > now }.toList()
    }

    /** Vom PC: "Hier ist Jarvis …" wurde an name geschickt -> Antworten aus diesem Chat melden. */
    fun watch(ctx: Context, name: String, hours: Int) {
        val o = try { JSONObject(prefs(ctx).getString("watch", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        val now = System.currentTimeMillis() / 1000
        for (k in o.keys().asSequence().toList()) if (o.optLong(k) < now) o.remove(k)
        o.put(norm(name), now + hours.coerceIn(1, 72) * 3600L)
        prefs(ctx).edit().putString("watch", o.toString()).apply()
    }

    private fun matches(list: List<String>, vararg names: String) =
        names.map { norm(it) }.filter { it.isNotBlank() }.any { n -> list.any { it == n || n.startsWith("$it ") } }

    private val SYSTEM = Regex("Nachrichtenverlauf|message history|Ende-zu-Ende|end-to-end|hat dich hinzugefügt|added you|" +
        "hat die Gruppe|changed the group|Diese Nachricht wurde gelöscht|This message was deleted|verpasster (?:Sprach|Video)?anruf|" +
        "missed (?:voice |video )?call|^\\d+ neue Nachrichten|new messages$", RegexOption.IGNORE_CASE)

    private fun isVoice(t: String) = t.contains("🎤") || Regex("^(?:sprachnachricht|voice message|audio)\\b", RegexOption.IGNORE_CASE).containsMatchIn(t.trim())

    /** Aus MediaWatch.onNotificationPosted. */
    fun onPosted(ctx: Context, sbn: StatusBarNotification) {
        if (sbn.packageName !in PKGS) return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        if (n.category == Notification.CATEGORY_CALL) return   // Anrufe macht der Butler
        val ex = n.extras ?: return
        val chat0 = (ex.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE) ?: ex.getCharSequence(Notification.EXTRA_TITLE))?.toString()
            ?.replace(Regex("\\s*\\(\\d+ (?:Nachrichten|messages)\\)\\s*$"), "")?.replace(Regex(":\\s*$"), "")?.trim() ?: return
        val chat = chat0.replace(Regex("[\u200e\u200f\u202a-\u202e]"), "").trim()
        if (chat.isBlank() || chat.equals("WhatsApp", true)) return
        val group = ex.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, false)

        // neueste Nachricht von jemand anderem
        var sender = if (group) "" else chat
        var text = ex.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: ""
        var time = n.`when`
        val msgs = ex.getParcelableArray(Notification.EXTRA_MESSAGES)
        // eigene Nachrichten aus dem Verlauf der Benachrichtigung (ohne Absender = von ihm) für den Gesprächsverlauf merken
        msgs?.mapNotNull { it as? Bundle }?.forEach { b ->
            val s = b.getCharSequence("sender")?.toString() ?: (if (Build.VERSION.SDK_INT >= 28) (b.getParcelable<android.app.Person>("sender_person"))?.name?.toString() else null)
            val t = b.getCharSequence("text")?.toString()?.trim() ?: ""
            if (t.isNotBlank()) hist(ctx, norm(chat), if (s.isNullOrBlank()) "ich" else s, t, b.getLong("time", 0L))
        }
        // Termine aus WhatsApp (alle Chats, auch deine eigenen Antworten wie „jo passt“)
        try {
            val lb = msgs?.mapNotNull { it as? Bundle }?.lastOrNull()
            val lt = (lb?.getCharSequence("text") ?: ex.getCharSequence(Notification.EXTRA_TEXT))?.toString()?.replace(Regex("[‎‏‪-‮]"), "")?.trim() ?: ""
            val lw = lb?.getLong("time", n.`when`) ?: n.`when`
            val ls = lb?.let { b -> b.getCharSequence("sender")?.toString() ?: (if (Build.VERSION.SDK_INT >= 28) (b.getParcelable<android.app.Person>("sender_person"))?.name?.toString() else null) }
            val sig = "${norm(chat)}|$lt|$lw"
            if (lt.isNotBlank() && !SYSTEM.containsMatchIn(lt) && System.currentTimeMillis() - lw < 15 * 60_000L && synchronized(termSeen) { termSeen.add(sig).also { while (termSeen.size > 60) termSeen.remove(termSeen.first()) } }) {
                val who = if (ls.isNullOrBlank() && msgs != null) "ich" else (ls ?: chat)
                if (isVoice(lt) && !group) Thread({
                    val key = prefs(ctx).getString("groq_key", "") ?: ""
                    val f = if (key.isNotBlank()) voiceFile(lw) else null
                    val tx = if (f != null) try { Groq.transcribeFile(key, f) } catch (_: Exception) { "" } else ""
                    if (tx.isNotBlank()) WaTermine.onMessage(ctx, chat, who, "(Sprachnachricht) $tx", verlauf(ctx, norm(chat)))
                }, "jarvis-watermin-voice").start()
                else if (!isVoice(lt)) WaTermine.onMessage(ctx, chat, who, lt, verlauf(ctx, norm(chat)))
            }
        } catch (e: Exception) { Log.w(TAG, "Termine: $e") }
        if (msgs != null && msgs.isNotEmpty()) {
            (msgs.lastOrNull() as? Bundle)?.let { b ->   // letzte Nachricht ohne Absender = du hast geantwortet
                val s = b.getCharSequence("sender")?.toString() ?: (if (Build.VERSION.SDK_INT >= 28) (b.getParcelable<android.app.Person>("sender_person"))?.name?.toString() else null)
                if (s.isNullOrBlank()) { markRead(ctx, norm(chat)); return }
            }
            val last = msgs.mapNotNull { it as? Bundle }.lastOrNull { b ->
                val s = b.getCharSequence("sender")?.toString()
                    ?: (if (Build.VERSION.SDK_INT >= 28) (b.getParcelable<android.app.Person>("sender_person"))?.name?.toString() else null)
                !s.isNullOrBlank()   // ohne Absender = eigene Nachricht
            } ?: return
            text = last.getCharSequence("text")?.toString() ?: text
            time = last.getLong("time", time)
            sender = last.getCharSequence("sender")?.toString()
                ?: (if (Build.VERSION.SDK_INT >= 28) (last.getParcelable<android.app.Person>("sender_person"))?.name?.toString() else null) ?: sender
        } else if (group && text.contains(": ")) {
            sender = text.substringBefore(": "); text = text.substringAfter(": ")
        }
        val inv = Regex("[\u200e\u200f\u202a-\u202e]")
        text = text.replace(inv, "").trim(); sender = sender.replace(inv, "").trim()
        if (text.isBlank() || SYSTEM.containsMatchIn(text)) return   // WhatsApp-Hinweise, keine echte Nachricht

        // Antworten-Knopf merken (auch für Chats, die nicht angesagt werden – "antworte Mama" soll gehen)
        n.actions?.firstOrNull { a -> a.remoteInputs?.any { it.allowFreeFormInput } == true }?.let {
            synchronized(repliers) { repliers[norm(chat)] = Reply(it, System.currentTimeMillis()) }
        }

        if (!group && !isVoice(text) && System.currentTimeMillis() - time < 10 * 60_000L) try { Stil.onIncoming(ctx, chat, text, verlauf(ctx, norm(chat))) } catch (_: Exception) {}
        val wanted = matches(important(ctx), chat, sender) || matches(watched(ctx), chat, sender)
        if (!wanted) return
        val ck = norm(chat)
        synchronized(seen) {
            if (time <= (seen[ck] ?: 0L)) return
            val sig = "$ck|$sender|$text"
            if (sig in recent) return
            seen[ck] = time; recent.addLast(sig); while (recent.size > 30) recent.removeFirst()
        }
        if (System.currentTimeMillis() - time > 10 * 60_000L) return   // alte Nachricht, die nur neu angezeigt wird
        val voice = isVoice(text)
        Thread({ forward(ctx, chat, sender.ifBlank { chat }, text, voice, time) }, "jarvis-chat").start()
    }

    /** WhatsApp nimmt die Benachrichtigung weg, wenn du den Chat liest (Handy oder PC) – dann nicht mehr ansagen. */
    fun onRemoved(ctx: Context, sbn: StatusBarNotification, reason: Int) {
        if (sbn.packageName !in PKGS) return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        if (reason != NotificationListenerService.REASON_APP_CANCEL && reason != NotificationListenerService.REASON_APP_CANCEL_ALL &&
            reason != NotificationListenerService.REASON_CLICK) return
        val ex = n.extras ?: return
        val chat = (ex.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE) ?: ex.getCharSequence(Notification.EXTRA_TITLE))?.toString()
            ?.replace(Regex("\\s*\\(\\d+ (?:Nachrichten|messages)\\)\\s*$"), "")?.replace(Regex(":\\s*$"), "")
            ?.replace(Regex("[\u200e\u200f\u202a-\u202e]"), "")?.trim() ?: return
        if (chat.isBlank() || chat.equals("WhatsApp", true)) return
        markRead(ctx, norm(chat))
    }

    private val readSent = HashMap<String, Long>()
    private val forwardedAt = HashMap<String, Long>()   // wann zuletzt eine Nachricht dieses Chats an den PC ging
    fun markRead(ctx: Context, ck: String) {
        prefs(ctx).edit().putLong("read_$ck", System.currentTimeMillis()).apply()
        // Nur melden, wenn der PC von diesem Chat überhaupt etwas weiß (sonst unnötige Nachrichten – der Dienst hat ein Tageslimit)
        val fw = synchronized(forwardedAt) { forwardedAt[ck] ?: 0L }
        if (fw == 0L || System.currentTimeMillis() - fw > 60 * 60_000L) return
        synchronized(readSent) { if ((readSent[ck] ?: 0L) >= fw) return; readSent[ck] = System.currentTimeMillis() }
        if (Link.paired(ctx)) Thread { try { Link.toPc(ctx, JSONObject().put("kind", "wa_read").put("from", "phone").put("key", ck).put("ts", System.currentTimeMillis() / 1000)) } catch (_: Exception) {} }.start()
    }

    private fun forward(ctx: Context, chat: String, sender: String, text: String, voice: Boolean, time: Long) {
        if (!Link.paired(ctx)) return
        val m = JSONObject().put("kind", "wa_msg").put("from", "phone").put("chat", chat).put("sender", sender)
            .put("text", text).put("voice", voice).put("key", norm(chat)).put("ts", System.currentTimeMillis() / 1000)
        val key = prefs(ctx).getString("groq_key", "") ?: ""
        var inFile: File? = null
        if (voice) {
            val f = voiceFile(time); inFile = f
            if (f != null) {
                markVoice(ctx, f)
                if (key.isNotBlank()) try { m.put("transcript", Groq.transcribeFile(key, f)) } catch (e: Exception) { Log.w(TAG, "umwandeln: $e") }
                if (f.length() < 700_000) m.put("audio", Base64.encodeToString(f.readBytes(), Base64.NO_WRAP))
            } else Log.i(TAG, "Sprachnachricht-Datei nicht gefunden (Zugriff auf alle Dateien?)")
        }
        // Seine eigenen Sprachnachrichten kurz davor (neue Dateien, die nicht von anderen kamen) -> Inhalt für den Verlauf
        try { ownVoices(ctx, key, norm(chat), inFile) } catch (e: Exception) { Log.w(TAG, "eigene Sprachnachricht: $e") }
        hist(ctx, norm(chat), sender, if (voice) "(Sprachnachricht) " + m.optString("transcript", "Inhalt unbekannt") else text, time)
        m.put("verlauf", verlauf(ctx, norm(chat)))
        synchronized(forwardedAt) { forwardedAt[norm(chat)] = System.currentTimeMillis() }
        try { Leute.promptFor(ctx, norm(chat)).takeIf { it.isNotBlank() }?.let { m.put("person", it) } } catch (_: Exception) {}
        Link.toPc(ctx, m)
    }

    fun filesOk(): Boolean = Build.VERSION.SDK_INT < 30 || Environment.isExternalStorageManager()

    /** Neueste Sprachnachricht im WhatsApp-Ordner (WhatsApp lädt sie meist sofort; kurz darauf warten). */
    private fun voiceFile(time: Long): File? {
        if (!filesOk()) return null
        val root = Environment.getExternalStorageDirectory()
        val dirs = listOf("Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Voice Notes",
            "Android/media/com.whatsapp.w4b/WhatsApp Business/Media/WhatsApp Business Voice Notes",
            "WhatsApp/Media/WhatsApp Voice Notes").map { File(root, it) }.filter { it.isDirectory }
        repeat(10) {
            val f = dirs.flatMap { d -> d.walkTopDown().maxDepth(2).filter { it.isFile && it.name.endsWith(".opus") }.toList() }
                .maxByOrNull { it.lastModified() }
            if (f != null && f.lastModified() >= time - 90_000L && f.length() > 0) {
                Thread.sleep(800)   // fertig schreiben lassen
                return f
            }
            Thread.sleep(1500)
        }
        return null
    }

    /** Antwort über die Benachrichtigung schicken. true = geklappt. */
    // --- Gesprächsverlauf pro Chat (für sinnvolle Antwortvorschläge) ---------------------------------------------
    @Synchronized private fun hist(ctx: Context, ck: String, von: String, text: String, t: Long, learn: Boolean = true) {
        val a = try { JSONArray(prefs(ctx).getString("hist_$ck", "[]")) } catch (_: Exception) { JSONArray() }
        val tt = if (t > 0) t else System.currentTimeMillis()
        for (i in 0 until a.length()) a.optJSONObject(i)?.let { if (it.optString("text") == text && (it.optString("von") == von)) return }
        if (von == "ich" && learn) try {   // deine eigene Nachricht: Schreibstil mitlernen (mit der Nachricht davor fürs Quiz)
            val before = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { it.optLong("t") <= tt }.lastOrNull()
            Stil.learn(ctx, text, before?.takeIf { it.optString("von") != "ich" }?.let { "${it.optString("von")}: ${it.optString("text")}" }, ck)
        } catch (_: Exception) {}
        a.put(JSONObject().put("von", von).put("text", text.take(400)).put("t", tt))
        val l = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.sortedBy { it.optLong("t") }.takeLast(14)
        prefs(ctx).edit().putString("hist_$ck", JSONArray(l).toString()).apply()
    }
    private fun verlauf(ctx: Context, ck: String): JSONArray = try {
        val a = JSONArray(prefs(ctx).getString("hist_$ck", "[]"))
        JSONArray((0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { System.currentTimeMillis() - it.optLong("t") < 3 * 86_400_000L }.takeLast(10))
    } catch (_: Exception) { JSONArray() }

    private fun markVoice(ctx: Context, f: File) {
        val s = (prefs(ctx).getString("voice_seen", "") ?: "").split("|").takeLast(40) + f.name
        prefs(ctx).edit().putString("voice_seen", s.joinToString("|")).apply()
    }

    /** Neue Sprachnachrichten-Dateien der letzten 30 Min., die nicht von anderen kamen = seine eigenen -> umwandeln, in den Verlauf. */
    private fun ownVoices(ctx: Context, key: String, ck: String, except: File?) {
        if (!filesOk() || key.isBlank()) return
        val root = Environment.getExternalStorageDirectory()
        val seen = (prefs(ctx).getString("voice_seen", "") ?: "").split("|").toSet()
        val dirs = listOf("Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Voice Notes", "WhatsApp/Media/WhatsApp Voice Notes").map { File(root, it) }.filter { it.isDirectory }
        val fresh = dirs.flatMap { d -> d.walkTopDown().maxDepth(3).filter { it.isFile && it.name.endsWith(".opus") && System.currentTimeMillis() - it.lastModified() < 30 * 60_000L }.toList() }
            .filter { it.name !in seen && it != except }.sortedBy { it.lastModified() }.takeLast(2)
        for (f in fresh) {
            markVoice(ctx, f)
            val t = try { Groq.transcribeFile(key, f) } catch (_: Exception) { "" }
            if (t.isNotBlank()) hist(ctx, ck, "ich", "(seine Sprachnachricht, wahrscheinlich an diesen Chat) $t", f.lastModified())
        }
    }

    /** Wie Skyler schreibt: ohne Punkt, Komma, Doppelpunkt, Gedankenstrich (12:30, 2,5 und E-Mail bleiben). */
    fun waStyle(t0: String): String {
        var t = t0.trim().trim('"', '„', '“')
        t = t.replace(Regex("\\s+[–—-]+\\s+"), " ").replace(Regex("[–—]"), " ")
        t = t.replace(Regex("(?<!\\d)[.,;:](?!\\d)"), " ").replace(Regex("(?<=\\d)[.,;:](?=\\s|$)"), " ")
        t = t.replace(Regex("\\.{2,}|…"), " ").replace(Regex("[ \\t]{2,}"), " ").replace(Regex(" +([?!])"), "$1")
        return t.trim()
    }

    fun reply(ctx: Context, key: String, chat: String, text0: String): Boolean {
        val text = waStyle(text0)
        val r = synchronized(repliers) { repliers[norm(key)] ?: repliers[norm(chat)] } ?: return false
        try { hist(ctx, norm(key).ifBlank { norm(chat) }, "ich", text, System.currentTimeMillis(), learn = false) } catch (_: Exception) {}
        return try {
            val ins = r.action.remoteInputs ?: return false
            val intent = Intent(); val b = Bundle()
            for (ri in ins) b.putCharSequence(ri.resultKey, text)
            RemoteInput.addResultsToIntent(ins, intent, b)
            r.action.actionIntent.send(ctx, 0, intent)
            true
        } catch (e: Exception) { Log.w(TAG, "antworten: $e"); false }
    }
}
