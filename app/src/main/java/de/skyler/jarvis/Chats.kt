package de.skyler.jarvis

import android.app.Notification
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.service.notification.StatusBarNotification
import android.util.Base64
import android.util.Log
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
    private val PKGS = setOf("com.whatsapp", "com.whatsapp.w4b")

    private class Reply(val action: Notification.Action, val at: Long)
    private val repliers = HashMap<String, Reply>()          // Chat -> Antworten-Knopf der Benachrichtigung
    private val seen = HashMap<String, Long>()                // Chat -> Zeit der letzten gemeldeten Nachricht
    private val recent = ArrayDeque<String>()                 // gegen doppelte Meldungen

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun norm(s: String) = s.lowercase().replace(Regex("[^\\p{L}\\p{N} ]"), " ").replace(Regex("\\s+"), " ").trim()

    fun important(ctx: Context): List<String> =
        (prefs(ctx).getString("wichtig", "") ?: "").split(',', ';', '\n').map { norm(it) }.filter { it.isNotBlank() }

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

    private fun isVoice(t: String) = t.contains("🎤") || Regex("^(?:sprachnachricht|voice message|audio)\\b", RegexOption.IGNORE_CASE).containsMatchIn(t.trim())

    /** Aus MediaWatch.onNotificationPosted. */
    fun onPosted(ctx: Context, sbn: StatusBarNotification) {
        if (sbn.packageName !in PKGS) return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        val ex = n.extras ?: return
        val chat = (ex.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE) ?: ex.getCharSequence(Notification.EXTRA_TITLE))?.toString()
            ?.replace(Regex("\\s*\\(\\d+ (?:Nachrichten|messages)\\)\\s*$"), "")?.replace(Regex(":\\s*$"), "")?.trim() ?: return
        if (chat.isBlank() || chat.equals("WhatsApp", true)) return
        val group = ex.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, false)

        // neueste Nachricht von jemand anderem
        var sender = if (group) "" else chat
        var text = ex.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: ""
        var time = n.`when`
        val msgs = ex.getParcelableArray(Notification.EXTRA_MESSAGES)
        if (msgs != null && msgs.isNotEmpty()) {
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
        if (text.isBlank()) return

        // Antworten-Knopf merken (auch für Chats, die nicht angesagt werden – "antworte Mama" soll gehen)
        n.actions?.firstOrNull { a -> a.remoteInputs?.any { it.allowFreeFormInput } == true }?.let {
            synchronized(repliers) { repliers[norm(chat)] = Reply(it, System.currentTimeMillis()) }
        }

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

    private fun forward(ctx: Context, chat: String, sender: String, text: String, voice: Boolean, time: Long) {
        if (!Link.paired(ctx)) return
        val m = JSONObject().put("kind", "wa_msg").put("from", "phone").put("chat", chat).put("sender", sender)
            .put("text", text).put("voice", voice).put("key", norm(chat)).put("ts", System.currentTimeMillis() / 1000)
        if (voice) {
            val f = voiceFile(time)
            if (f != null) {
                val key = prefs(ctx).getString("groq_key", "") ?: ""
                if (key.isNotBlank()) try { m.put("transcript", Groq.transcribeFile(key, f)) } catch (e: Exception) { Log.w(TAG, "umwandeln: $e") }
                if (f.length() < 700_000) m.put("audio", Base64.encodeToString(f.readBytes(), Base64.NO_WRAP))
            } else Log.i(TAG, "Sprachnachricht-Datei nicht gefunden (Zugriff auf alle Dateien?)")
        }
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
    fun reply(ctx: Context, key: String, chat: String, text: String): Boolean {
        val r = synchronized(repliers) { repliers[norm(key)] ?: repliers[norm(chat)] } ?: return false
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
