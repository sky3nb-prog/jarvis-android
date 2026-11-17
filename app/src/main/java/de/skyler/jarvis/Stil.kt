package de.skyler.jarvis

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.ContactsContract
import android.util.Log
import androidx.core.app.NotificationCompat
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Dein Schreibstil:
 *  - lernt mit: jede eigene WhatsApp-Nachricht (aus den Benachrichtigungen) + exportierte Chats („Chat exportieren“ → Jarvis)
 *  - Stil-Quiz: echte Antwort von dir vs. Jarvis' Antwort – erkennst du, welche von dir ist?
 *    Wenn Jarvis dich oft genug täuscht (≥ 40 % bei mindestens 10 Runden), ist „selbst schreiben“ freigeschaltet.
 *  - Antworten für ausgewählte Chats: erst mit einem Tipp bestätigen, später (nach dem Quiz) ganz selbst.
 *  - Geburtstagsnachrichten und „plan ein Treffen mit …“ in deinem Stil (Antippen öffnet WhatsApp mit dem Text).
 */
object Stil {
    private const val TAG = "JarvisStil"
    private const val CH = "jarvis_stil"
    private val de = Locale.GERMANY
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    // --- Sammeln ------------------------------------------------------------------------------------------------
    // stil_ich: alle eigenen Nachrichten (global), stil_c_<chat>: deine Nachrichten pro Person/Gruppe,
    // stil_paare: {q (Nachricht davor), a (deine Antwort), chat, ctx (Verlauf davor), src} fürs Quiz und als Beispiele
    private fun arr(ctx: Context, k: String) = try { JSONArray(prefs(ctx).getString(k, "[]")) } catch (_: Exception) { JSONArray() }
    private fun strs(a: JSONArray) = (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() }
    fun samples(ctx: Context): List<String> = strs(arr(ctx, "stil_ich"))
    fun chatSamples(ctx: Context, ck: String): List<String> = strs(arr(ctx, "stil_c_$ck"))
    fun pairs(ctx: Context): List<JSONObject> = arr(ctx, "stil_paare").let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) } }
    fun mitlesen(ctx: Context) = prefs(ctx).getBoolean("stil_mitlesen", true)

    private fun good(t: String) = t.length in 2..300 && !t.startsWith("(") && !t.contains("Medien ausgeschlossen") && !t.contains("<Medien") &&
        !t.contains("Nachricht wurde gelöscht") && !t.contains("Diese Nachricht") && !t.startsWith("http") && !t.contains("null")

    /** Person vergessen: ihre Beispiele und Quiz-Stellen raus. */
    @Synchronized fun forgetChat(ctx: Context, ck: String) {
        val mine = chatSamples(ctx, ck).toSet()
        prefs(ctx).edit().remove("stil_c_$ck").putString("stil_ich", JSONArray(samples(ctx).filter { it !in mine }).toString())
            .putString("stil_paare", JSONArray(pairs(ctx).filter { it.optString("chat") != ck }).toString()).apply()
    }

    /** Mehrere neue eigene Nachrichten auf einmal speichern (schnell, auch für große Exporte). */
    @Synchronized private fun addAll(ctx: Context, ck: String, mine: List<String>, newPairs: List<JSONObject>): Int {
        if (ck.isNotBlank() && Leute.isIgnored(ctx, ck)) return 0   // vergessene Person: nichts mehr lernen
        val ok = mine.map { it.trim() }.filter { good(it) }
        if (ok.isEmpty() && newPairs.isEmpty()) return 0
        val g = LinkedHashSet(samples(ctx)); val before = g.size
        ok.forEach { g.remove(it); g.add(it) }
        val e = prefs(ctx).edit().putString("stil_ich", JSONArray(g.toList().takeLast(800)).toString())
        if (ck.isNotBlank()) {
            val c = LinkedHashSet(chatSamples(ctx, ck)); ok.forEach { c.remove(it); c.add(it) }
            e.putString("stil_c_$ck", JSONArray(c.toList().takeLast(80)).toString())
            val known = (prefs(ctx).getString("stil_chats_all", "") ?: "").split("|").filter { it.isNotBlank() }.toMutableSet()
            if (known.add(ck)) e.putString("stil_chats_all", known.joinToString("|"))
        }
        if (newPairs.isNotEmpty()) {
            val seen = HashSet<String>()
            val all = (pairs(ctx) + newPairs).reversed().filter { seen.add(it.optString("chat") + "|" + it.optString("a")) }.reversed()
            e.putString("stil_paare", JSONArray(all.takeLast(500)).toString())
        }
        val added = g.size - before
        val n = prefs(ctx).getInt("stil_neu", 0) + maxOf(added, 0)
        e.putInt("stil_neu", if (n >= 25) 0 else n).apply()
        if (n >= 25) { toPc(ctx); Thread { try { profile(ctx, false) } catch (_: Exception) {} }.start() }
        return added
    }

    private fun pair(q: String, a: String, ck: String, cx: String, src: String) =
        JSONObject().put("q", q.trim().take(300)).put("a", a.trim()).put("chat", ck).put("ctx", cx.take(500)).put("src", src)

    /** Aus Chats.hist: deine eigene Nachricht aus der Benachrichtigung. */
    fun learn(ctx: Context, text: String, before: String? = null, ck: String = "") {
        val t = text.trim(); if (!good(t)) return
        addAll(ctx, ck, listOf(t), if (!before.isNullOrBlank() && good(before.trim())) listOf(pair(before, t, ck, "", "live")) else emptyList())
    }

    /** Aus der Bedienungshilfe: was gerade im offenen WhatsApp-Chat auf dem Bildschirm steht (auch beim Hochscrollen). */
    fun fromScreen(ctx: Context, chat: String, rows: List<Pair<String, String>>) {
        if (rows.size < 2) return
        val ck = Chats.norm(chat)
        val mine = mutableListOf<String>(); val ps = mutableListOf<JSONObject>()
        for (i in rows.indices) {
            val (von, t) = rows[i]
            if (von != "ich") continue
            mine.add(t)
            val prev = (i - 1 downTo 0).firstOrNull { rows[it].first != "ich" }?.let { rows[it] }
            if (prev != null && i - rows.indexOf(prev) <= 2 && good(prev.second)) {
                val cx = rows.subList(maxOf(0, rows.indexOf(prev) - 3), rows.indexOf(prev)).joinToString("\n") { (v, x) -> "${if (v == "ich") "ICH" else v}: $x" }
                ps.add(pair("${prev.first}: ${prev.second}", t, ck, cx, "bildschirm"))
            }
        }
        val names = prefs(ctx).getString("stil_names", "") ?: ""
        if (!names.split("|").contains(ck)) prefs(ctx).edit().putString("stil_names", "$names|$ck").putString("stil_cn_$ck", chat).apply()
        addAll(ctx, ck, mine, ps)
    }

    /** Neue Beispiele auch an den PC (der schreibt am PC Antworten in deinem Namen). */
    private fun toPc(ctx: Context) {
        if (!Link.paired(ctx)) return
        Thread { try { Link.toPc(ctx, JSONObject().put("kind", "stil").put("from", "phone").put("texte", JSONArray(samples(ctx).takeLast(60))).put("ts", System.currentTimeMillis() / 1000)) } catch (_: Exception) {} }.start()
    }

    /** WhatsApp-Export („Chat exportieren“ → „Ohne Medien“ → Jarvis). Gibt zurück, wie viele Nachrichten von dir gelernt wurden. */
    fun importExport(ctx: Context, fileName: String, text: String): Int {
        val partner = Regex("(?:WhatsApp[- ]Chat mit|WhatsApp Chat with)\\s+(.+?)(?:\\.txt)?$", RegexOption.IGNORE_CASE).find(fileName)?.groupValues?.get(1)?.trim() ?: ""
        val line = Regex("^\\[?(\\d{1,2}[./]\\d{1,2}[./]\\d{2,4}),? (\\d{1,2}:\\d{2})(?::\\d{2})?\\]?\\s*[-–]?\\s*([^:]{1,40}): (.*)$")
        val msgs = mutableListOf<Pair<String, String>>()
        for (raw in text.lines()) {
            val l = raw.replace(Regex("[\u200e\u200f\u202a-\u202e]"), "")
            val m = line.find(l)
            if (m != null) msgs.add(m.groupValues[3].trim() to m.groupValues[4].trim())
            else if (msgs.isNotEmpty() && l.isNotBlank()) msgs[msgs.size - 1] = msgs.last().first to (msgs.last().second + "\n" + l.trim())
        }
        if (msgs.isEmpty()) return 0
        val senders = msgs.groupingBy { it.first }.eachCount()
        var me = prefs(ctx).getString("stil_name", "") ?: ""
        if (me.isBlank() || me !in senders) {
            me = if (partner.isNotBlank()) senders.keys.firstOrNull { !it.equals(partner, true) && senders.size == 2 } ?: "" else ""
            if (me.isBlank()) return -1
            prefs(ctx).edit().putString("stil_name", me).apply()
        }
        val ck = Chats.norm(partner.ifBlank { senders.keys.firstOrNull { it != me } ?: "" })
        if (ck.isNotBlank()) prefs(ctx).edit().putString("stil_cn_$ck", partner.ifBlank { ck }).apply()
        val last = msgs.takeLast(4000)
        val mine = mutableListOf<String>(); val ps = mutableListOf<JSONObject>()
        for (i in last.indices) {
            val (s, t) = last[i]
            if (s != me) continue
            mine.add(t)
            val prev = last.getOrNull(i - 1)
            if (prev != null && prev.first != me && good(prev.second)) {
                val cx = last.subList(maxOf(0, i - 4), i - 1).joinToString("\n") { (v, x) -> "${if (v == me) "ICH" else v}: ${x.take(150)}" }
                ps.add(pair("${prev.first}: ${prev.second}", t, ck, cx, "export"))
            }
        }
        addAll(ctx, ck, mine, ps)
        toPc(ctx)
        Thread { try { profile(ctx, true) } catch (_: Exception) {} }.start()
        return mine.size
    }

    private fun learnQuiet(ctx: Context, t0: String, before: String?, ck: String = "") {
        addAll(ctx, ck, listOf(t0), if (!before.isNullOrBlank() && good(before.trim())) listOf(pair(before, t0, ck, "", "bestaetigt")) else emptyList())
    }

    /** Kurze Beschreibung deines Stils (KI), wird bei jedem Vorschlag mitgegeben. */
    fun profile(ctx: Context, force: Boolean): String {
        val p = prefs(ctx)
        val old = p.getString("stil_profil", "") ?: ""
        if (!force && old.isNotBlank() && System.currentTimeMillis() - p.getLong("stil_profil_t", 0) < 3 * 86_400_000L) return old
        val s = samples(ctx); if (s.size < 15) return old
        val key = p.getString("groq_key", "") ?: ""; if (key.isBlank()) return old
        val raw = Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content",
            "Beschreibe in höchstens 6 knappen Stichpunkten, WIE diese Person auf WhatsApp schreibt (Länge, Groß-/Kleinschreibung, Satzzeichen, " +
                "typische Wörter/Abkürzungen/Begrüßungen, Emojis, Ton). Nur die Stichpunkte."))
            .put(JSONObject().put("role", "user").put("content", s.shuffled().take(150).joinToString("\n"))), 300)
        val prof = raw.trim().take(900)
        if (prof.isNotBlank()) p.edit().putString("stil_profil", prof).putLong("stil_profil_t", System.currentTimeMillis()).apply()
        return prof.ifBlank { old }
    }

    // --- Schreiben wie du -------------------------------------------------------------------------------------------
    /** chat = an wen (normalisiert): dann zählen vor allem deine Nachrichten an genau diese Person / Gruppe. */
    fun write(ctx: Context, aufgabe: String, verlauf: String = "", person: String = "", chat: String = "", exclude: String = ""): String {
        val key = prefs(ctx).getString("groq_key", "") ?: ""; if (key.isBlank()) return ""
        val per = if (chat.isNotBlank()) chatSamples(ctx, chat).filter { it != exclude }.let { it.takeLast(8) + it.dropLast(8).shuffled().take(8) } else emptyList()
        val ex = samples(ctx).filter { it !in per && it != exclude }.let { l -> (l.takeLast(6) + l.dropLast(6).shuffled().take(if (per.isEmpty()) 16 else 8)) }
        val fixes = pairs(ctx).filter { it.optString("src") == "quiz" && (chat.isBlank() || it.optString("chat") == chat) }.takeLast(6)
        val who = prefs(ctx).getString("stil_cn_$chat", "")?.ifBlank { null } ?: chat
        val sys = "Du schreibst eine WhatsApp-Nachricht IM NAMEN des Nutzers, so dass niemand merkt, dass sie nicht von ihm ist. " +
            "Erfinde nichts über ihn (keine Pläne, Orte, Gefühle). Ist unklar, worum es geht: kurz und neutral. " +
            "WICHTIG: Er redet mit jeder Person anders. Sprüche, Beleidigungen oder Insider, die er zu EINER Person gesagt hat (auch in Gruppen), " +
            "gelten nur für diese Person – nie auf andere übertragen. Richte Ton und Nähe nach den Beispielen an genau diese Person.\n" +
            (prefs(ctx).getString("stil_profil", "")?.takeIf { it.isNotBlank() }?.let { "So schreibt er allgemein:\n$it\n" } ?: "") +
            (if (per.isNotEmpty()) "So schreibt er an $who (am wichtigsten):\n" + per.joinToString("\n") + "\n" else "") +
            (if (ex.isNotEmpty()) "Weitere echte Nachrichten von ihm (Stil: Länge, Kleinschreibung, Abkürzungen, Emojis):\n" + ex.joinToString("\n") + "\n" else "") +
            (if (fixes.isNotEmpty()) "So hat er selbst geantwortet, als du es falsch hattest (genau so!):\n" + fixes.joinToString("\n") { "${it.optString("q")} -> ${it.optString("a")}" } + "\n" else "") +
            (if (person.isNotBlank()) "Über die Person: $person\n" else "") +
            "Gib NUR den Nachrichtentext zurück."
        val out = Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", sys))
            .put(JSONObject().put("role", "user").put("content", (if (verlauf.isNotBlank()) "Verlauf:\n$verlauf\n\n" else "") + aufgabe)), 200)
        return Chats.waStyle(out.trim().trim('"', '„', '“'))
    }

    // --- Quiz ---------------------------------------------------------------------------------------------------
    /**
     * Eine zufällige Stelle aus deinen Chats: wer, was davor war, die Nachricht an dich – und zwei Antworten:
     * deine echte und eine von Jarvis (zufällige Reihenfolge). Du tippst, welche DU schreiben würdest – oder schreibst eine eigene.
     * {chat, ctx, q, a, b, mine: 0|1}
     */
    fun quizNext(ctx: Context): JSONObject {
        val p = pairs(ctx).filter { it.optString("a").length >= 2 && it.optString("src") != "quiz" }
        if (p.size < 5) return JSONObject().put("error", "Ich hab noch zu wenig von dir gelesen. Öffne ein paar WhatsApp-Chats und scroll hoch (ich lese mit) oder lade einen Chat-Export.")
        val asked = (prefs(ctx).getString("stil_quiz_seen", "") ?: "").split("|").toSet()
        val pick = p.filter { (it.optString("chat") + it.optString("a")).hashCode().toString() !in asked }.ifEmpty { p }.shuffled().first()
        prefs(ctx).edit().putString("stil_quiz_seen", (asked.toList().takeLast(200) + (pick.optString("chat") + pick.optString("a")).hashCode().toString()).joinToString("|")).apply()
        val ck = pick.optString("chat")
        val who = prefs(ctx).getString("stil_cn_$ck", "")?.ifBlank { null } ?: ck.replaceFirstChar { it.uppercase() }
        val person = try { Leute.promptFor(ctx, ck) } catch (_: Exception) { "" }
        val fake = try { write(ctx, "Neue Nachricht: ${pick.optString("q")}\nSchreib seine Antwort.", pick.optString("ctx"), person, ck, pick.optString("a")) } catch (e: Exception) { "" }
        if (fake.isBlank()) return JSONObject().put("error", "Gerade keine Verbindung zur KI.")
        val mineFirst = Math.random() < 0.5
        return JSONObject().put("chat", who).put("ck", ck).put("ctx", pick.optString("ctx")).put("q", pick.optString("q"))
            .put("a", if (mineFirst) pick.optString("a") else fake).put("b", if (mineFirst) fake else pick.optString("a"))
            .put("mine", if (mineFirst) 0 else 1).put("fake", fake)
    }

    /**
     * pick: 0/1 = die gewählte Antwort, own = deine eigene Antwort (statt beiden).
     * Lernen: eigene Antwort = stärkstes Beispiel; wählst du Jarvis' Antwort, war sie gut genug (zählt als „getäuscht“ und wird Beispiel).
     */
    fun quizAnswer(ctx: Context, q: JSONObject, pick: Int, own: String): JSONObject {
        val ck = q.optString("ck"); val msg = q.optString("q")
        val res: Int
        when {
            own.isNotBlank() -> { res = 2; addAll(ctx, ck, listOf(own), listOf(pair(msg, own, ck, q.optString("ctx"), "quiz"))) }
            pick == q.optInt("mine") -> res = 1
            else -> { res = 0; addAll(ctx, ck, listOf(q.optString("fake")), emptyList()) }
        }
        val a = arr(ctx, "stil_quiz"); a.put(res)
        val l = (0 until a.length()).map { a.optInt(it) }.takeLast(30)
        val xp = prefs(ctx).getInt("stil_xp", 0) + (if (res == 2) 15 else 10)
        prefs(ctx).edit().putString("stil_quiz", JSONArray(l).toString()).putInt("stil_xp", xp).apply()
        return quizState(ctx).put("res", res)
    }

    fun quizState(ctx: Context): JSONObject {
        val a = arr(ctx, "stil_quiz"); val l = (0 until a.length()).map { a.optInt(it) }
        val rated = l.filter { it != 2 }
        val fooled = rated.count { it == 0 }
        val level = if (rated.isEmpty()) 0 else (fooled * 100 / rated.size * 2).coerceAtMost(100)   // 50 % „würde ich auch schreiben“ = 100 %
        val unlocked = rated.size >= 10 && fooled * 100 / rated.size >= 40
        if (unlocked && !prefs(ctx).getBoolean("stil_frei", false)) prefs(ctx).edit().putBoolean("stil_frei", true).apply()
        val xp = prefs(ctx).getInt("stil_xp", 0)
        return JSONObject().put("runden", l.size).put("getaeuscht", fooled).put("level", level).put("frei", prefs(ctx).getBoolean("stil_frei", false))
            .put("xp", xp).put("rang", RANKS.lastOrNull { xp >= it.first }?.second ?: RANKS[0].second)
            .put("beispiele", samples(ctx).size).put("paare", pairs(ctx).size).put("personen", (prefs(ctx).getString("stil_chats_all", "") ?: "").split("|").count { it.isNotBlank() })
            .put("eigene", l.count { it == 2 }).put("profil", prefs(ctx).getString("stil_profil", "") ?: "").put("mitlesen", mitlesen(ctx))
    }

    private val RANKS = listOf(0 to "Fremder", 50 to "Bekannter", 150 to "Kumpel", 300 to "Schreibt fast wie du", 600 to "Dein Doppelgänger", 1000 to "Nicht mehr zu unterscheiden")

    // --- Selbst antworten (ausgewählte Chats) ---------------------------------------------------------------------
    /** "aus" | "bestaetigen" (ein Tipp) | "selbst" (erst nach dem Quiz) */
    fun mode(ctx: Context): String = prefs(ctx).getString("stil_modus", "aus") ?: "aus"
    fun setMode(ctx: Context, m: String) {
        val v = if (m == "selbst" && !prefs(ctx).getBoolean("stil_frei", false)) "bestaetigen" else m
        prefs(ctx).edit().putString("stil_modus", v).apply()
    }
    /** Vom PC: eingelesener Chat-Export {chat, mine:[…], pairs:[{q,a,ctx}]} (in Stücken). */
    fun fromPc(ctx: Context, c: JSONObject): String {
        val chat = c.optString("chat"); val ck = Chats.norm(chat)
        if (ck.isNotBlank()) prefs(ctx).edit().putString("stil_cn_$ck", chat).apply()
        val mine = c.optJSONArray("mine")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList()
        val ps = c.optJSONArray("pairs")?.let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) }.map { pair(it.optString("q"), it.optString("a"), ck, it.optString("ctx"), "export") } } ?: emptyList()
        val n = addAll(ctx, ck, mine, ps)
        if (c.optBoolean("last")) Thread { try { profile(ctx, true) } catch (_: Exception) {} }.start()
        return "ok $n"
    }
    fun setChats(ctx: Context, s: String) {
        prefs(ctx).edit().putString("stil_chats", s.trim()).apply()
        if (s.isNotBlank() && mode(ctx) == "aus") setMode(ctx, "bestaetigen")
    }

    /** „Du darfst Tobi selbst antworten“ */
    fun grant(ctx: Context, name: String): String {
        val l = autoChats(ctx).filter { Chats.norm(it) != Chats.norm(name) } + name
        prefs(ctx).edit().putString("stil_chats", l.joinToString(", ")).apply()
        val frei = prefs(ctx).getBoolean("stil_frei", false)
        if (mode(ctx) == "aus") setMode(ctx, if (frei) "selbst" else "bestaetigen")
        return if (mode(ctx) == "selbst") "Okay, ab jetzt antworte ich $name selbst – in deinem Stil. Du siehst jede Antwort als Mitteilung."
            else "Okay, bei $name schlag ich dir Antworten vor, du tippst nur „Senden“. Ganz selbst geht, sobald du im Stil-Training oft genug meine Antwort nimmst."
    }
    fun revoke(ctx: Context, name: String): String {
        val l = autoChats(ctx).filter { Chats.norm(it) != Chats.norm(name) }
        prefs(ctx).edit().putString("stil_chats", l.joinToString(", ")).apply()
        return "Okay, $name antworte ich nicht mehr."
    }
    fun autoChats(ctx: Context): List<String> = (prefs(ctx).getString("stil_chats", "") ?: "").split(",").map { it.trim() }.filter { it.isNotBlank() }

    private val pending = HashMap<String, JSONObject>()
    private val seenIn = LinkedHashSet<String>()

    /** Aus Chats.onPosted (Einzelchat, neue Nachricht von jemand anderem). */
    fun onIncoming(ctx: Context, chat: String, text: String, verlauf: JSONArray) {
        val m = mode(ctx); if (m == "aus") return
        val ck = Chats.norm(chat)
        synchronized(seenIn) { if (!seenIn.add("$ck|$text")) return; while (seenIn.size > 40) seenIn.remove(seenIn.first()) }
        if (autoChats(ctx).none { Chats.norm(it) == ck || (Chats.norm(it).length >= 3 && ck.contains(Chats.norm(it))) }) return
        Thread({
            try {
                Thread.sleep(45_000)   // kurz warten: antwortest du selbst, lassen wir's
                if (prefs(ctx).getLong("read_$ck", 0) > System.currentTimeMillis() - 50_000L) return@Thread
                val hist = (0 until verlauf.length()).mapNotNull { verlauf.optJSONObject(it) }.takeLast(10)
                    .joinToString("\n") { "${if (it.optString("von") == "ich") "ICH" else it.optString("von")}: ${it.optString("text")}" }
                val person = try { Leute.promptFor(ctx, ck) } catch (_: Exception) { "" }
                val d = write(ctx, "Neue Nachricht von $chat: $text\nSchreib seine Antwort.", hist, person, ck)
                if (d.isBlank()) return@Thread
                if (m == "selbst") {
                    if (Chats.reply(ctx, ck, chat, d)) note(ctx, ck, "Hab $chat geantwortet", d, false)
                } else {
                    synchronized(pending) { pending[ck] = JSONObject().put("chat", chat).put("text", d) }
                    note(ctx, ck, "Antwort an $chat?", d, true)
                }
            } catch (e: Exception) { Log.w(TAG, "auto: $e") }
        }, "jarvis-stil-auto").start()
    }

    fun confirm(ctx: Context, ck: String, send: Boolean) {
        val o = synchronized(pending) { pending.remove(ck) } ?: return
        ctx.getSystemService(NotificationManager::class.java).cancel(ck.hashCode())
        if (!send) return
        val ok = Chats.reply(ctx, ck, o.optString("chat"), o.optString("text"))
        if (ok) { learnQuiet(ctx, o.optString("text"), null); prefs(ctx).edit().putInt("stil_ok", prefs(ctx).getInt("stil_ok", 0) + 1).apply() }
    }

    // --- Geburtstag und Treffen ---------------------------------------------------------------------------------
    fun number(ctx: Context, name: String): String? = try {
        ctx.contentResolver.query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI, arrayOf(ContactsContract.CommonDataKinds.Phone.NUMBER),
            "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?", arrayOf("%$name%"), null)?.use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        }?.replace(Regex("[^+\\d]"), "")?.let { if (it.startsWith("00")) "+" + it.drop(2) else if (it.startsWith("0")) "+49" + it.drop(1) else it }?.removePrefix("+")
    } catch (_: Exception) { null }

    /** WhatsApp mit fertigem Text öffnen (du tippst nur noch auf Senden). */
    fun openIntent(ctx: Context, name: String, text: String): Intent {
        val nr = number(ctx, name)
        val u = if (nr != null) "https://wa.me/$nr?text=" + Uri.encode(text) else "https://wa.me/?text=" + Uri.encode(text)
        return Intent(Intent.ACTION_VIEW, Uri.parse(u)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    fun birthday(ctx: Context, name: String) {
        val d = try { write(ctx, "Schreib $name eine kurze Geburtstagsnachricht.", person = try { Leute.promptFor(ctx, Chats.norm(name)) } catch (_: Exception) { "" }, chat = Chats.norm(name)) } catch (_: Exception) { "" }
        if (d.isBlank()) return
        noteOpen(ctx, "gb_$name", "$name hat Geburtstag", d, openIntent(ctx, name, d))
    }

    /** „Plan ein Treffen mit Max (am Wochenende)“ -> freie Zeiten aus dem Kalender, Nachricht in deinem Stil. */
    fun meet(ctx: Context, name: String, wann: String): String {
        val now = System.currentTimeMillis()
        val ev = Cal.events(ctx, now, now + 8 * 86_400_000L)
        val free = mutableListOf<String>()
        val c = Calendar.getInstance()
        for (dd in 0..7) {
            val day = (c.clone() as Calendar).apply { add(Calendar.DAY_OF_MONTH, dd) }
            val wd = day.get(Calendar.DAY_OF_WEEK); val we = wd == Calendar.SATURDAY || wd == Calendar.SUNDAY
            if (wann.contains("wochenende", true) && !we) continue
            for (h in if (we) listOf(14, 17) else listOf(17)) {
                val s = (day.clone() as Calendar).apply { set(Calendar.HOUR_OF_DAY, h); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0) }.timeInMillis
                if (s < now + 2 * 3600_000L) continue
                if (ev.none { it.begin < s + 3 * 3600_000L && (if (it.end > 0) it.end else it.begin + 3600_000L) > s && !it.allDay }) free.add(SimpleDateFormat("EEEE HH 'Uhr'", de).format(Date(s)))
            }
            if (free.size >= 3) break
        }
        if (free.isEmpty()) return "In den nächsten Tagen ist dein Kalender ziemlich voll."
        val d = try { write(ctx, "Frag $name, ob er/sie Lust hat sich zu treffen. Schlag diese Zeiten vor: ${free.take(3).joinToString(", ")}.",
            person = try { Leute.promptFor(ctx, Chats.norm(name)) } catch (_: Exception) { "" }, chat = Chats.norm(name)) } catch (_: Exception) { "" }
        if (d.isBlank()) return "Gerade komme ich nicht an die KI."
        noteOpen(ctx, "treffen_$name", "Treffen mit $name", d, openIntent(ctx, name, d))
        return "Du hast ${free.take(3).joinToString(", ")} frei. Vorschlag für $name: „$d“ – tipp auf die Mitteilung, dann ist es in WhatsApp, du musst nur noch senden. Wenn ihr euch einigt, trag ich's ein."
    }

    // --- Mitteilungen --------------------------------------------------------------------------------------------
    private fun channel(ctx: Context): NotificationManager {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "Schreiben in deinem Stil", NotificationManager.IMPORTANCE_HIGH))
        return nm
    }

    private fun note(ctx: Context, ck: String, title: String, text: String, ask: Boolean) {
        val b = NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.ic_dialog_email).setContentTitle(title)
            .setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text)).setAutoCancel(true)
        fun act(send: Boolean) = PendingIntent.getBroadcast(ctx, ck.hashCode() + (if (send) 1 else 2),
            Intent(ctx, StilReceiver::class.java).putExtra("ck", ck).putExtra("send", send), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        if (ask) b.addAction(0, "Senden", act(true)).addAction(0, "Nein", act(false))
        try { channel(ctx).notify(ck.hashCode(), b.build()) } catch (_: Exception) {}
    }

    private fun noteOpen(ctx: Context, id: String, title: String, text: String, open: Intent) {
        val b = NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.ic_dialog_email).setContentTitle(title)
            .setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText("$text\n\nAntippen = in WhatsApp öffnen")).setAutoCancel(true)
            .setContentIntent(PendingIntent.getActivity(ctx, id.hashCode(), open, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        try { channel(ctx).notify(id.hashCode(), b.build()) } catch (_: Exception) {}
    }
}

class StilReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val ck = intent.getStringExtra("ck") ?: return
        val send = intent.getBooleanExtra("send", false)
        Thread { try { Stil.confirm(ctx, ck, send) } catch (_: Exception) {} }.start()
    }
}
