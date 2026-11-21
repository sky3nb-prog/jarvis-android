package de.skyler.jarvis

import android.content.Context
import android.provider.ContactsContract
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Leute: Jarvis lernt aus den WhatsApp-Nachrichten, die er mitliest, wer wie ist –
 *  worüber ihr schreibt (Interessen), wie die Person drauf ist (Ton, Stimmung) und wie DU mit ihr schreibst (Länge, Emojis, Spitznamen).
 * Pro Person auch andere Namen (Discord, Spitzname) und der Geburtstag (aus den Kontakten oder selbst eingetragen).
 * Nutzt das für: Antwortvorschläge passend zur Person, Geburtstags-Erinnerung mit Geschenkideen, die zu ihr passen.
 * Alles bleibt auf dem Handy (und für Antworten am PC). Lernt höchstens 6 Chats pro Abend.
 */
object Leute {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    private val de = Locale.GERMANY

    fun all(ctx: Context): JSONObject = try { JSONObject(prefs(ctx).getString("leute", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
    fun save(ctx: Context, o: JSONObject) { prefs(ctx).edit().putString("leute", o.toString()).apply() }

    /** Liste für die Einstellungen (mit Geburtstagen aus den Kontakten). */
    fun list(ctx: Context): JSONArray {
        val o = all(ctx); val bd = contactBirthdays(ctx)
        val ig = ignored(ctx)
        for ((n, d) in bd) { val k = Chats.norm(n); if (k in ig) continue; val p = o.optJSONObject(k) ?: JSONObject().put("name", n).also { o.put(k, it) }; if (p.optString("geburtstag").isBlank()) p.put("geburtstag", d).put("gb_quelle", "kontakte") }
        return JSONArray(o.keys().asSequence().mapNotNull { o.optJSONObject(it)?.put("key", it) }.sortedBy { it.optString("name").lowercase() }.toList())
    }

    /** Aus den Einstellungen: Namen/Geburtstag/andere Namen ändern oder Person löschen. */
    fun edit(ctx: Context, key: String, data: JSONObject?) {
        val o = all(ctx)
        if (data == null) { forget(ctx, key); return }
        val p = o.optJSONObject(key) ?: JSONObject().also { o.put(key, it) }
        for (k in listOf("name", "aliases", "discord", "geburtstag", "interessen", "art", "stil", "geschenk")) if (data.has(k)) p.put(k, data.optString(k).trim())
        if (data.has("art") || data.has("stil") || data.has("interessen")) p.put("selbst", true)   // von dir korrigiert: beim Lernen behalten
        save(ctx, o)
    }

    /** „Vergessen“: Person raus und ab jetzt nichts mehr über sie lernen (auch kein Schreibstil, keine Termine). */
    fun forget(ctx: Context, key: String) {
        val o = all(ctx); o.remove(key); save(ctx, o)
        val ig = ignored(ctx) + key
        prefs(ctx).edit().putString("leute_ignore", ig.joinToString("|")).remove("hist_$key").remove("stil_c_$key").apply()
        try { Stil.forgetChat(ctx, key) } catch (_: Exception) {}
    }
    fun ignored(ctx: Context): Set<String> = (prefs(ctx).getString("leute_ignore", "") ?: "").split("|").filter { it.isNotBlank() }.toSet()
    fun isIgnored(ctx: Context, ck: String) = ck in ignored(ctx)

    /** „+ Person“: selbst hinzufügen (auch jemand, der dir noch nie geschrieben hat). */
    fun add(ctx: Context, name: String) {
        val k = Chats.norm(name); if (k.isBlank()) return
        val o = all(ctx); if (!o.has(k)) o.put(k, JSONObject().put("name", name.trim()))
        save(ctx, o)
        prefs(ctx).edit().putString("leute_ignore", (ignored(ctx) - k).joinToString("|")).apply()
    }

    private fun contactBirthdays(ctx: Context): List<Pair<String, String>> = try {
        val out = mutableListOf<Pair<String, String>>()
        ctx.contentResolver.query(ContactsContract.Data.CONTENT_URI, arrayOf(ContactsContract.Data.DISPLAY_NAME, ContactsContract.CommonDataKinds.Event.START_DATE),
            "${ContactsContract.Data.MIMETYPE}=? AND ${ContactsContract.CommonDataKinds.Event.TYPE}=?",
            arrayOf(ContactsContract.CommonDataKinds.Event.CONTENT_ITEM_TYPE, ContactsContract.CommonDataKinds.Event.TYPE_BIRTHDAY.toString()), null)?.use { c ->
            while (c.moveToNext()) {
                val n = c.getString(0) ?: continue; val d = c.getString(1) ?: continue
                Regex("(\\d{2})-(\\d{2})$").find(d)?.let { out.add(n to "${it.groupValues[1]}-${it.groupValues[2]}") }
            }
        }
        out
    } catch (_: Exception) { emptyList() }

    /** Für Antwortvorschläge: wie die Person ist und wie er mit ihr schreibt. */
    fun promptFor(ctx: Context, ck: String): String {
        val p = all(ctx).optJSONObject(ck) ?: return ""
        return listOf(p.optString("art").takeIf { it.isNotBlank() }?.let { "Die Person: $it" },
            p.optString("stil").takeIf { it.isNotBlank() }?.let { "So schreibt der Nutzer mit ihr: $it" },
            p.optString("interessen").takeIf { it.isNotBlank() }?.let { "Ihr schreibt oft über: $it" }).filterNotNull().joinToString(" ")
    }

    /** Abends: aus den neuen Nachrichten lernen (Groq, kostenlos). */
    fun learn(ctx: Context, force: Boolean = false) {
        val key = prefs(ctx).getString("groq_key", "") ?: ""; if (key.isBlank()) return
        val today = SimpleDateFormat("yyyy-MM-dd", de).format(Date()) + (if (java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY) < 17) "a" else "b")
        if (!force && prefs(ctx).getString("leute_gelernt", "") == today) return
        prefs(ctx).edit().putString("leute_gelernt", today).apply()
        val o = all(ctx); val all = prefs(ctx).all
        var n = 0
        val ig = ignored(ctx)
        // Quellen: Verlauf aus den Benachrichtigungen (hist_) und was du ihnen geschrieben hast (Mitlesen/Export: stil_c_)
        val keys = all.keys.filter { it.startsWith("hist_") || it.startsWith("stil_c_") }.map { it.removePrefix("hist_").removePrefix("stil_c_") }.distinct()
        for (ck in keys) {
            if (n >= 15 || ck in ig || ck.isBlank()) continue
            val a = try { JSONArray(all["hist_$ck"] as? String ?: "[]") } catch (_: Exception) { JSONArray() }
            val own = try { JSONArray(all["stil_c_$ck"] as? String ?: "[]") } catch (_: Exception) { JSONArray() }
            val msgs = (0 until a.length()).mapNotNull { a.optJSONObject(it) } +
                (0 until own.length()).map { JSONObject().put("von", "ich").put("text", own.optString(it)).put("t", 0L) }
            if (msgs.size < 3) continue
            val p = o.optJSONObject(ck) ?: JSONObject().also { o.put(ck, it) }
            val newest = maxOf(msgs.maxOf { it.optLong("t") }, own.length().toLong())
            if (!force && newest <= p.optLong("gelernt_bis")) continue
            val name = p.optString("name").ifBlank { msgs.firstOrNull { it.optString("von") != "ich" }?.optString("von") ?: ck }
            val chat = msgs.joinToString("\n") { (if (it.optString("von") == "ich") "ICH" else it.optString("von")) + ": " + it.optString("text").take(200) }
            val sys = "Du hilfst einem persönlichen Assistenten, die Freunde und Familie des Nutzers zu verstehen. Lies den WhatsApp-Ausschnitt und das bisherige Profil. " +
                "Antworte NUR als JSON: {\"interessen\":\"<Themen/Hobbys der Person, kurz, mit Komma>\",\"art\":\"<wie die Person drauf ist: Ton, typische Stimmung, 1 kurzer Satz>\"," +
                "\"stil\":\"<wie ICH (der Nutzer) mit dieser Person schreibt: Länge, Emojis, Spitznamen, Anrede, Groß/klein – 1 kurzer Satz>\",\"geschenk\":\"<2-3 passende Geschenkideen, mit Komma>\"}. " +
                "Ergänze das alte Profil, statt es wegzuwerfen. Nichts erfinden; wenn unklar, Feld leer lassen. Keine Gesundheits- oder sehr privaten Details."
            val user = "Person: $name\nBisheriges Profil: ${p.optString("interessen")} | ${p.optString("art")} | ${p.optString("stil")} | ${p.optString("geschenk")}\n\nChat:\n$chat"
            try {
                val r = JSONObject(Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", sys)).put(JSONObject().put("role", "user").put("content", user)), 350, json = true)
                    .let { it.substring(it.indexOf('{'), it.lastIndexOf('}') + 1) })
                for (f in listOf("interessen", "art", "stil", "geschenk")) {
                    if (p.optBoolean("selbst") && f != "geschenk" && p.optString(f).isNotBlank()) continue   // deine Korrektur bleibt
                    r.optString(f).trim().takeIf { it.isNotBlank() && it != "null" }?.let { p.put(f, it.take(240)) }
                }
                p.put("name", name).put("gelernt_bis", newest); n++
            } catch (_: Exception) {}
        }
        save(ctx, o)
    }

    /** Geburtstage: 7 Tage, 1 Tag vorher und am Tag – mit Geschenkideen passend zur Person. */
    fun tick(ctx: Context, say: (String) -> Unit) {
        val c = Calendar.getInstance(); val h = c.get(Calendar.HOUR_OF_DAY)
        if (h == 13 || h == 20) try { Thread { learn(ctx) }.start() } catch (_: Exception) {}   // zweimal am Tag weiterlernen (nur Chats mit Neuem)
        if (h !in 9..19) return
        val today = SimpleDateFormat("yyyy-MM-dd", de).format(Date())
        val p = prefs(ctx)
        val l = list(ctx)
        for (i in 0 until l.length()) {
            val x = l.optJSONObject(i) ?: continue
            val gb = x.optString("geburtstag").takeLast(5); if (!Regex("\\d{2}-\\d{2}").matches(gb)) continue
            val d = Calendar.getInstance().apply { set(Calendar.MONTH, gb.take(2).toInt() - 1); set(Calendar.DAY_OF_MONTH, gb.takeLast(2).toInt()); set(Calendar.HOUR_OF_DAY, 12) }
            if (d.timeInMillis < System.currentTimeMillis() - 86_400_000L) d.add(Calendar.YEAR, 1)
            val days = ((d.timeInMillis - Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, 12) }.timeInMillis) / 86_400_000L).toInt()
            if (days !in setOf(0, 1, 7)) continue
            val k = "gb_${x.optString("key")}|$today"; if (p.getBoolean(k, false)) continue
            p.edit().putBoolean(k, true).apply()
            val name = x.optString("name"); val idee = x.optString("geschenk")
            if (days == 0) Thread { try { Stil.birthday(ctx, name) } catch (_: Exception) {} }.start()   // Glückwunsch in deinem Stil, Antippen = WhatsApp
            say(when (days) {
                0 -> "Heute hat $name Geburtstag. Ich hab dir eine Nachricht in deinem Stil vorbereitet – tipp auf die Mitteilung, dann ist sie in WhatsApp."
                1 -> "Morgen hat $name Geburtstag." + if (idee.isNotBlank()) " Falls du noch was brauchst: $idee." else ""
                else -> "In einer Woche hat $name Geburtstag." + if (idee.isNotBlank()) " Geschenkideen, die zu $name passen: $idee." else " Sag „Geschenkidee für $name“, dann überleg ich mir was."
            })
        }
    }

    /** "Geschenkidee für Alex" / "was weißt du über Alex?" */
    fun about(ctx: Context, who: String, gift: Boolean): String {
        val l = list(ctx); val w = Chats.norm(who)
        val x = (0 until l.length()).mapNotNull { l.optJSONObject(it) }.firstOrNull { p ->
            Chats.norm(p.optString("name")).contains(w) || w.contains(Chats.norm(p.optString("name"))) ||
                (p.optString("aliases") + "," + p.optString("discord")).split(",").any { a -> a.isNotBlank() && Chats.norm(a).contains(w) }
        } ?: return "Über $who weiß ich noch nichts. Ich lerne aus euren WhatsApp-Nachrichten."
        val n = x.optString("name")
        if (gift) {
            val key = prefs(ctx).getString("groq_key", "") ?: ""
            if (key.isNotBlank() && x.optString("interessen").isNotBlank()) try {
                return Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", "Schlag 3 konkrete, bezahlbare Geschenkideen für einen Jugendlichen als Schenkenden vor, passend zur Person. Kurz, Deutsch, als ein Satz mit Komma, ohne Einleitung."))
                    .put(JSONObject().put("role", "user").put("content", "Person: $n. Interessen: ${x.optString("interessen")}. Art: ${x.optString("art")}. Bisherige Ideen: ${x.optString("geschenk")}")), 160).trim()
            } catch (_: Exception) {}
            return if (x.optString("geschenk").isNotBlank()) "Für $n: ${x.optString("geschenk")}." else "Für $n hab ich noch keine Idee – ich kenne noch zu wenig. Erzähl mir, was $n mag."
        }
        return listOf("$n:", x.optString("interessen").takeIf { it.isNotBlank() }?.let { "schreibt viel über $it." },
            x.optString("art").takeIf { it.isNotBlank() }, x.optString("geburtstag").takeIf { it.isNotBlank() }?.let { "Geburtstag: ${it.takeLast(2)}.${it.takeLast(5).take(2)}." },
            x.optString("discord").takeIf { it.isNotBlank() }?.let { "Auf Discord: $it." }).filterNotNull().joinToString(" ")
    }
}
