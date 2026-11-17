package de.skyler.jarvis

import android.content.Context
import android.util.Base64
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.OutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.net.ssl.SSLSocketFactory

/**
 * Ganzes Gmail-Postfach lesen (nur lesen, nie löschen oder als gelesen markieren): über IMAP mit einem
 * Google-App-Passwort, das du selbst unter myaccount.google.com → Sicherheit → App-Passwörter anlegst.
 * Alle 15 Minuten: neue Mails der letzten 2 Tage -> Pakete erkennen (DHL, Hermes, Amazon …) und eine kurze Liste
 * „neue Mails“ für „Hab ich neue Mails?“. Das Passwort bleibt auf dem Handy (bzw. verschlüsselt im Konto).
 */
object Mail {
    private const val TAG = "JarvisMail"
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun user(ctx: Context) = prefs(ctx).getString("gmail_user", "") ?: ""
    private fun pw(ctx: Context) = (prefs(ctx).getString("gmail_pw", "") ?: "").replace(" ", "")
    private fun filled(ctx: Context) = user(ctx).contains("@") && pw(ctx).length >= 12
    /** Erst „verbunden“, wenn die Anmeldung bei Google wirklich geklappt hat. */
    fun configured(ctx: Context) = filled(ctx) && prefs(ctx).getBoolean("gmail_ok", false)

    fun set(ctx: Context, user: String, pw: String) {
        val e = prefs(ctx).edit().putString("gmail_user", user.trim())
        if (pw.isNotBlank()) e.putString("gmail_pw", pw.trim())
        e.remove("mail_seen").putBoolean("gmail_ok", false).apply()
    }

    private class Imap(host: String) {
        val sock = SSLSocketFactory.getDefault().createSocket(host, 993).apply { soTimeout = 20_000 }
        val inp = BufferedInputStream(sock.getInputStream()); val out: OutputStream = sock.getOutputStream()
        var n = 0
        private fun line(): String {
            val b = ByteArrayOutputStream()
            while (true) { val c = inp.read(); if (c < 0) break; if (c == '\n'.code) break; if (c != '\r'.code) b.write(c) }
            return String(b.toByteArray(), Charsets.ISO_8859_1)
        }
        /** Antwort bis zur getaggten Zeile; Literale {n} werden mitgelesen. */
        fun read(tag: String): String {
            val sb = StringBuilder()
            while (true) {
                val l = line(); sb.append(l).append('\n')
                Regex("\\{(\\d+)\\}$").find(l)?.let { m ->
                    val len = m.groupValues[1].toInt(); val buf = ByteArray(len); var got = 0
                    while (got < len) { val r = inp.read(buf, got, len - got); if (r < 0) break; got += r }
                    sb.append(String(buf, 0, got, Charsets.ISO_8859_1)).append('\n')
                }
                if (l.startsWith("$tag ")) { if (!l.startsWith("$tag OK")) throw RuntimeException(l.substringAfter(tag).trim()); return sb.toString() }
            }
        }
        fun cmd(c: String): String { val t = "a${++n}"; out.write("$t $c\r\n".toByteArray(Charsets.UTF_8)); out.flush(); return read(t) }
        fun greet() = line()
        fun close() { try { cmd("LOGOUT") } catch (_: Exception) {}; try { sock.close() } catch (_: Exception) {} }
    }

    private fun q(s: String) = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

    /** =?UTF-8?B?…?= / =?UTF-8?Q?…?= in Betreffzeilen entschlüsseln. */
    private fun decode(s: String): String = Regex("=\\?([^?]+)\\?([BbQq])\\?([^?]*)\\?=").replace(s.replace(Regex("\\?=\\s+=\\?"), "?==?")) { m ->
        try {
            val cs = charset(m.groupValues[1])
            val bytes = if (m.groupValues[2].equals("B", true)) Base64.decode(m.groupValues[3], Base64.DEFAULT)
            else { val t = m.groupValues[3].replace('_', ' '); val o = ByteArrayOutputStream(); var i = 0
                while (i < t.length) { if (t[i] == '=' && i + 2 < t.length) { o.write(t.substring(i + 1, i + 3).toInt(16)); i += 3 } else { o.write(t[i].code); i++ } }; o.toByteArray() }
            String(bytes, cs)
        } catch (_: Exception) { m.value }
    }

    /** Echte Anmeldung bei Google. ok = true nur, wenn Google sie angenommen hat. */
    /** Mail-Text lesbar machen: Base64-Teile und =C3=A4-Kodierung auflösen, HTML raus. */
    private fun readable(raw: String): String {
        var t = raw
        // Base64-Abschnitte (Zeilen nur aus Base64-Zeichen) entschlüsseln
        t = Regex("(?m)((?:^[A-Za-z0-9+/=]{60,}\\r?\\n){3,})").replace(t) { m ->
            try { String(Base64.decode(m.value.replace(Regex("\\s"), ""), Base64.DEFAULT), Charsets.UTF_8) } catch (_: Exception) { m.value } }
        // quoted-printable
        t = t.replace(Regex("=\\r?\\n"), "")
        t = Regex("(=[0-9A-F]{2})+").replace(t) { m ->
            try { val b = m.value.split("=").filter { it.length == 2 }.map { it.toInt(16).toByte() }.toByteArray(); String(b, Charsets.UTF_8) } catch (_: Exception) { m.value } }
        t = t.replace(Regex("(?is)<style.*?</style>"), " ").replace(Regex("<[^>]+>"), " ").replace("&nbsp;", " ").replace("&euro;", "€").replace("&amp;", "&")
        return t.replace(Regex("\\s+"), " ")
    }

    fun test(ctx: Context): JSONObject {
        val p = prefs(ctx)
        val r = try {
            if (!filled(ctx)) JSONObject().put("ok", false).put("text", "Trag deine Gmail-Adresse und das App-Passwort (16 Zeichen) ein.") else {
                val im = Imap("imap.gmail.com"); im.greet()
                try { im.cmd("LOGIN ${q(user(ctx))} ${q(pw(ctx))}"); val res = im.cmd("EXAMINE INBOX")
                    val n = Regex("\\* (\\d+) EXISTS").find(res)?.groupValues?.get(1) ?: "?"
                    JSONObject().put("ok", true).put("text", "Verbunden – Google hat die Anmeldung angenommen, im Posteingang sind $n Mails.") } finally { im.close() }
            }
        } catch (e: Exception) {
            val m = e.message ?: ""
            JSONObject().put("ok", false).put("text", if (Regex("(?i)AUTHENTICATIONFAILED|Invalid credentials|LOGIN").containsMatchIn(m))
                "Google hat die Anmeldung abgelehnt – das Passwort stimmt nicht. Es muss ein App-Passwort von Google sein (16 Buchstaben), nicht dein normales."
                else "Keine Verbindung zu Gmail: ${m.take(100)}")
        }
        p.edit().putBoolean("gmail_ok", r.optBoolean("ok")).apply()
        return r
    }

    /** Alle 15 Minuten aus Alltag.tick. */
    fun tick(ctx: Context, say: ((String) -> Unit)?) {
        if (!configured(ctx)) return
        val p = prefs(ctx)
        if (System.currentTimeMillis() - p.getLong("mail_check", 0) < 15 * 60_000L) return
        p.edit().putLong("mail_check", System.currentTimeMillis()).apply()
        Thread({ try { check(ctx, say) } catch (e: Exception) { Log.w(TAG, "mail: $e"); p.edit().putString("mail_err", e.message ?: "").apply() } }, "jarvis-mail").start()
    }

    private fun check(ctx: Context, say: ((String) -> Unit)?) {
        val p = prefs(ctx)
        val seen = try { JSONArray(p.getString("mail_seen", "[]")) } catch (_: Exception) { JSONArray() }
        val seenSet = (0 until seen.length()).map { seen.optString(it) }.toMutableSet()
        val first = seenSet.isEmpty()
        val im = Imap("imap.gmail.com"); im.greet()
        val recent = try { JSONArray(p.getString("mail_recent", "[]")) } catch (_: Exception) { JSONArray() }
        try {
            im.cmd("LOGIN ${q(user(ctx))} ${q(pw(ctx))}")
            im.cmd("EXAMINE INBOX")
            val since = SimpleDateFormat("dd-MMM-yyyy", Locale.US).format(Date(System.currentTimeMillis() - 2 * 86_400_000L))
            val uids = Regex("\\* SEARCH([\\d ]*)").find(im.cmd("UID SEARCH SINCE $since"))?.groupValues?.get(1)?.trim()?.split(" ")?.filter { it.isNotBlank() } ?: emptyList()
            val neu = uids.filter { it !in seenSet }.takeLast(25)
            for (u in neu) {
                val r = im.cmd("UID FETCH $u (BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)] BODY.PEEK[TEXT]<0.8000>)")
                val from = decode(Regex("(?im)^From:\\s*(.+)$").find(r)?.groupValues?.get(1)?.trim() ?: "")
                val subj = decode(Regex("(?im)^Subject:\\s*(.+)$").find(r)?.groupValues?.get(1)?.trim() ?: "")
                val body = readable(r.substringAfter("BODY[TEXT]", "")).take(3000)
                val who = from.substringBefore("<").trim().trim('"').ifBlank { from }
                if (!first) {   // beim ersten Mal nur merken, nicht alles Alte ansagen
                    try { Pakete.fromText(ctx, "", "$who: $subj", body, say) } catch (_: Exception) {}
                    try { Ausgaben.fromMail(ctx, from, subj, body) } catch (_: Exception) {}
                    recent.put(JSONObject().put("from", who).put("subj", subj).put("t", System.currentTimeMillis()))
                }
                seenSet.add(u)
            }
            if (first) uids.forEach { seenSet.add(it) }
        } finally { im.close() }
        while (recent.length() > 15) recent.remove(0)
        p.edit().putString("mail_seen", JSONArray(seenSet.toList().takeLast(400)).toString()).putString("mail_recent", recent.toString()).remove("mail_err").apply()
    }

    /** „Hab ich neue Mails?“ – die letzten aus den vergangenen 24 Stunden. */
    fun summary(ctx: Context): String {
        if (!configured(ctx)) return "Dein Gmail-Postfach ist noch nicht verbunden – Einstellungen → Allgemein → Gmail."
        val a = try { JSONArray(prefs(ctx).getString("mail_recent", "[]")) } catch (_: Exception) { JSONArray() }
        val l = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { System.currentTimeMillis() - it.optLong("t") < 86_400_000L }
        if (l.isEmpty()) return "Seit gestern keine neuen Mails."
        return "${l.size} neue Mail${if (l.size > 1) "s" else ""}: " + l.takeLast(5).reversed().joinToString("; ") { "${it.optString("from")}: ${it.optString("subj")}" } + "."
    }
}
