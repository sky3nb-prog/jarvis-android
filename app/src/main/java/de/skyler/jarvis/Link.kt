package de.skyler.jarvis

import android.content.Context
import android.util.Base64
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.TimeUnit
import java.util.zip.Deflater
import java.util.zip.Inflater
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Verbindung zum PC-Jarvis (gleiches Gedächtnis). Gleiche Verschlüsselung wie pc_link.py:
 * zlib + HMAC-SHA256-Stromverschlüsselung + HMAC-Prüfsumme, übertragen über ntfy.sh.
 */
object Link {
    private const val SERVER = "https://ntfy.sh/"
    private const val TAG = "JarvisLink"
    private val http = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build()

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    @Volatile private var app: Context? = null
    fun code(ctx: Context): String { if (app == null) app = ctx.applicationContext; return prefs(ctx).getString("link_code", "") ?: "" }
    fun paired(ctx: Context) = norm(code(ctx)).length >= 12

    private fun norm(c: String) = c.uppercase().filter { it.isLetterOrDigit() }
    private fun sha(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray())
    private fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }

    private fun topic(c: String) = "jv" + hex(sha("jarvis-topic:" + norm(c))).take(30)
    private fun kEnc(c: String) = sha("jarvis-enc:" + norm(c))
    private fun kMac(c: String) = sha("jarvis-mac:" + norm(c))

    private fun hmac(k: ByteArray, d: ByteArray): ByteArray =
        Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(k, "HmacSHA256")) }.doFinal(d)

    private fun stream(k: ByteArray, nonce: ByteArray, n: Int): ByteArray {
        val out = ByteArrayOutputStream()
        var i = 0
        while (out.size() < n) {
            out.write(hmac(k, nonce + byteArrayOf((i ushr 24).toByte(), (i ushr 16).toByte(), (i ushr 8).toByte(), i.toByte())))
            i++
        }
        return out.toByteArray().copyOf(n)
    }

    fun encrypt(obj: JSONObject, c: String): String {
        val d = Deflater(9)
        d.setInput(obj.toString().toByteArray()); d.finish()
        val buf = ByteArray(65536); val zo = ByteArrayOutputStream()
        while (!d.finished()) zo.write(buf, 0, d.deflate(buf))
        val pt = zo.toByteArray()
        val nonce = ByteArray(16).also { SecureRandom().nextBytes(it) }
        val ks = stream(kEnc(c), nonce, pt.size)
        val ct = ByteArray(pt.size) { (pt[it].toInt() xor ks[it].toInt()).toByte() }
        val tag = hmac(kMac(c), nonce + ct).copyOf(16)
        return "J1." + Base64.encodeToString(nonce + ct + tag, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
    }

    fun decrypt(text: String, c: String): JSONObject? {
        if (!text.startsWith("J1.")) return null
        val raw = Base64.decode(text.substring(3).trim(), Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
        if (raw.size < 33) return null
        val nonce = raw.copyOfRange(0, 16); val ct = raw.copyOfRange(16, raw.size - 16); val tag = raw.copyOfRange(raw.size - 16, raw.size)
        if (!MessageDigest.isEqual(tag, hmac(kMac(c), nonce + ct).copyOf(16))) return null
        val ks = stream(kEnc(c), nonce, ct.size)
        val pt = ByteArray(ct.size) { (ct[it].toInt() xor ks[it].toInt()).toByte() }
        val inf = Inflater(); inf.setInput(pt)
        val out = ByteArrayOutputStream(); val buf = ByteArray(65536)
        while (!inf.finished()) { val n = inf.inflate(buf); if (n == 0 && (inf.needsInput() || inf.needsDictionary())) break; out.write(buf, 0, n) }
        return JSONObject(String(out.toByteArray()))
    }

    /** Holt den neuesten Stand vom PC. true = neuer Stand gespeichert. */
    fun pull(ctx: Context): Boolean {
        val c = code(ctx)
        if (!paired(ctx)) return false
        val body = http.newCall(Request.Builder().url(SERVER + topic(c) + "/json?poll=1&since=12h").build()).execute().use {
            if (!it.isSuccessful) throw RuntimeException("HTTP ${it.code}")
            it.body?.string() ?: ""
        }
        var best: JSONObject? = null
        for (line in body.lines()) {
            val ev = try { JSONObject(line) } catch (_: Exception) { continue }
            if (ev.optString("event") != "message") continue
            var text = ev.optString("message")
            val att = ev.optJSONObject("attachment")
            if (!text.startsWith("J1.") && att != null) {
                text = try {
                    http.newCall(Request.Builder().url(att.optString("url")).build()).execute().use { it.body?.string() ?: "" }
                } catch (_: Exception) { "" }
            }
            val msg = try { decrypt(text, c) } catch (_: Exception) { null } ?: continue
            if (msg.optString("kind") == "snap" && msg.optString("from") == "pc" &&
                msg.optLong("ts") >= (best?.optLong("ts") ?: 0L)) best = msg
        }
        val snap = best ?: return false
        val p = prefs(ctx)
        if (snap.optLong("ts") <= p.getLong("snap_ts", 0L)) return false
        p.edit().putString("brain_snap", snap.toString()).putLong("snap_ts", snap.optLong("ts"))
            .putLong("snap_got", System.currentTimeMillis()).apply()
        applySettings(ctx, snap)
        Memory.prune(ctx, snap)
        Log.i(TAG, "Stand vom PC: ${snap.optJSONArray("facts")?.length()} Fakten")
        return true
    }

    // --- Gemeinsame Einstellungen: wer zuletzt geändert hat, gewinnt ------------------------------------------
    private val BOOL_KEYS = setOf("lage_spin", "lage_labels", "lage_jump", "lage_zoom", "lage_orbits")

    /** Einstellungen vom PC übernehmen, wenn sie neuer sind als die am Handy. */
    private fun applySettings(ctx: Context, snap: JSONObject) {
        val s = snap.optJSONObject("settings") ?: return
        val ts = snap.optLong("settings_ts")
        val p = prefs(ctx)
        if (ts <= p.getLong("settings_ts", 0L)) return
        val e = p.edit()
        for (k in s.keys()) {
            when {
                k in BOOL_KEYS -> e.putBoolean(k, s.optBoolean(k, true))
                k == "themen_selbst" -> Themen.setManual(ctx, s.optString(k))
                k == "test_chat" -> e.putString("test_chat", s.optString(k).trim())
                k == "wa_immer" -> e.putString("wa_immer", s.optString(k).trim())
                k == "wa_beim_zocken" -> e.putString("wa_beim_zocken", s.optString(k).trim())
                k == "stil_modus" -> s.optString(k).takeIf { it in setOf("aus", "bestaetigen", "selbst") }?.let { m ->
                    e.putString("stil_modus", if (m == "selbst" && !p.getBoolean("stil_frei", false)) "bestaetigen" else m) }
                k == "wa_name" -> s.optString(k).trim().takeIf { it.isNotBlank() }?.let { e.putString("stil_name", it) }
                k == "stil_chats" -> { e.putString("stil_chats", s.optString(k).trim()); if (s.optString(k).isNotBlank() && Stil.mode(ctx) == "aus") e.putString("stil_modus", "bestaetigen") }
                k == "piper_voice" -> { val v = s.optString(k); if (v.isNotBlank() && v != PiperPhone.voice(ctx)) { e.putString("piper_voice", v); e.apply(); PiperPhone.ensure(ctx) } }
                k in listOf("anrede", "assistant_name", "city", "address", "lage_orte", "orte", "wege", "route_an", "wichtig", "absage") -> e.putString(k, s.optString(k))
            }
        }
        e.putLong("settings_ts", ts).apply()
        Log.i(TAG, "Einstellungen vom PC übernommen")
    }

    /** Geänderte Einstellungen ans PC schicken. */
    fun pushSettings(ctx: Context) {
        val c = code(ctx); if (!paired(ctx)) return
        val p = prefs(ctx)
        val ts = System.currentTimeMillis() / 1000
        p.edit().putLong("settings_ts", ts).apply()
        val set = JSONObject()
        set.put("city", Lage.city(ctx)).put("address", p.getString("address", "") ?: "").put("anrede", p.getString("anrede", "") ?: "")
            .put("lage_orte", p.getString("lage_orte", "Stuttgart") ?: "")
            .put("orte", p.getString("orte", "") ?: "").put("wege", p.getString("wege", "") ?: "").put("route_an", p.getString("route_an", "") ?: "")
            .put("wichtig", p.getString("wichtig", Chats.DEFAULT) ?: "").put("absage", p.getString("absage", "") ?: "")
        (p.getString("assistant_name", "") ?: "").takeIf { it.isNotBlank() }?.let { set.put("assistant_name", it) }
        set.put("themen_selbst", Themen.manual(ctx).joinToString(", "))
        set.put("piper_voice", PiperPhone.voice(ctx))
        set.put("stil_chats", p.getString("stil_chats", "") ?: "")
        set.put("test_chat", p.getString("test_chat", "") ?: "")
        set.put("wa_immer", p.getString("wa_immer", "") ?: "").put("wa_beim_zocken", p.getString("wa_beim_zocken", "ansagen") ?: "ansagen")
        set.put("stil_modus", p.getString("stil_modus", "aus") ?: "aus").put("wa_name", p.getString("stil_name", "") ?: "")
        for (k in BOOL_KEYS) set.put(k, p.getBoolean(k, true))
        post(c, topic(c), JSONObject().put("kind", "settings").put("from", "phone").put("ts", ts).put("settings", set))
    }

    /** Gelernte Themen ans PC schicken (damit der PC-Jarvis dieselben Interessen kennt). */
    fun pushThemen(ctx: Context, themen: JSONArray) {
        val c = code(ctx); if (!paired(ctx)) return
        post(c, topic(c), JSONObject().put("kind", "themen").put("from", "phone").put("ts", System.currentTimeMillis() / 1000).put("themen", themen))
    }

    /** Tageslimit des Kopplungsdienstes (ntfy.sh: 250 Nachrichten pro Tag und Internet-Anschluss) erreicht? */
    @Volatile var limitAt = 0L
    fun limited() = limitAt > 0 && System.currentTimeMillis() - limitAt < 6 * 3_600_000L

    private fun post(c: String, t: String, msg: JSONObject) {
        Thread({
            val body = encrypt(msg, c)
            if (t == remoteTopic(c) && directPost(body)) return@Thread   // direkt über Tailscale geklappt
            try {
                http.newCall(Request.Builder().url(SERVER + t).post(body.toRequestBody("text/plain".toMediaType())).build()).execute().use { r ->
                    if (r.code == 429) limitAt = System.currentTimeMillis() else if (r.isSuccessful) limitAt = 0L
                }
            } catch (e: Exception) { Log.w(TAG, "post: $e") }
        }, "jarvis-post").start()
    }

    // --- Fernbedienung für den PC (eigener Kanal) --------------------------------------------------------------
    private fun remoteTopic(c: String) = "jr" + hex(sha("jarvis-remote:" + norm(c))).take(30)

    /** Befehl an den PC schicken und bis zu 15 Sekunden auf die Antwort warten. Antwort: {ok, text, status} oder null. */
    fun command(ctx: Context, cmd: JSONObject, waitMs: Long = 15_000): JSONObject? {
        val c = code(ctx); if (!paired(ctx)) return null
        poke()
        val id = java.util.UUID.randomUUID().toString().take(12)
        val sent = System.currentTimeMillis() / 1000
        val msg = JSONObject().put("kind", "cmd").put("from", "phone").put("id", id).put("ts", sent).put("cmd", cmd)
        val body = encrypt(msg, c)
        if (!directPost(body)) http.newCall(Request.Builder().url(SERVER + remoteTopic(c)).post(body.toRequestBody("text/plain".toMediaType())).build()).execute().use { r ->
            if (r.code == 429) { limitAt = System.currentTimeMillis(); return null } else if (r.isSuccessful) limitAt = 0L
        }
        val until = System.currentTimeMillis() + waitMs
        while (System.currentTimeMillis() < until) {
            Thread.sleep(if (directActive()) 300 else 1500)
            val r = latestStatus(ctx, "${sent - 2}", id)
            if (r != null) return r
        }
        return null
    }

    // --- Direkte Verbindung über Tailscale (kein Tageslimit; ntfy nur noch als Ersatz) ------------------------
    private val quick = http.newBuilder().connectTimeout(3, TimeUnit.SECONDS).readTimeout(5, TimeUnit.SECONDS).build()
    private val longPoll = http.newBuilder().connectTimeout(4, TimeUnit.SECONDS).readTimeout(35, TimeUnit.SECONDS).build()
    @Volatile private var directAt = 0L
    @Volatile private var directErr = ""
    private fun errText(e: Exception, code: Int = 0): String = when {
        code == 403 -> "PC lehnt ab (Schlüssel passt nicht – Kopplungscode gleich?)"
        code == 404 -> "PC kennt die direkte Verbindung noch nicht (PC-Update?)"
        code > 0 -> "PC antwortet mit Fehler $code"
        e is java.net.SocketTimeoutException -> "Keine Antwort vom PC – meist blockiert die Windows-Firewall Jarvis (Port 8765)"
        e is java.net.ConnectException -> "PC lehnt die Verbindung ab – läuft Jarvis am PC?"
        e is java.net.UnknownHostException || e is java.net.NoRouteToHostException -> "PC nicht erreichbar – Tailscale am Handy an?"
        else -> e.javaClass.simpleName + ": " + (e.message ?: "")
    }
    fun directActive() = System.currentTimeMillis() - directAt < 60_000L
    private val statusCache = java.util.ArrayDeque<JSONObject>()
    private val seenBodies = java.util.LinkedHashSet<String>()
    private fun seen(b: String): Boolean = synchronized(seenBodies) { if (!seenBodies.add(b.takeLast(64))) true else { while (seenBodies.size > 300) seenBodies.remove(seenBodies.first()); false } }

    /** Für die Einstellungen: läuft die direkte Verbindung, welche Adresse? Adresse auch selbst eintragbar (100.x.y.z). */
    fun directInfo(ctx: Context): JSONObject {
        val f = try { JSONObject(prefs(ctx).getString("pc_fern", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        return JSONObject().put("active", directActive()).put("ip", f.optString("ip")).put("limit", limited()).put("err", directErr)
    }
    /** "Prüfen": sofort eine Probe an den PC (Ergebnis in directInfo). */
    fun directTest(ctx: Context) { code(ctx); Thread { directPost(encrypt(JSONObject().put("kind", "ping").put("from", "phone").put("ts", System.currentTimeMillis() / 1000), code(ctx))) }.start() }

    fun setPcIp(ctx: Context, ip: String) {
        val f = try { JSONObject(prefs(ctx).getString("pc_fern", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        if (Regex("^100\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}$").matches(ip.trim())) prefs(ctx).edit().putString("pc_fern", f.put("ip", ip.trim()).put("port", f.optInt("port", 8765)).toString()).apply()
    }

    private fun directBase(): String? {
        val ctx = app ?: return null
        val f = try { JSONObject(prefs(ctx).getString("pc_fern", "{}") ?: "{}") } catch (_: Exception) { return null }
        val ip = f.optString("ip"); if (ip.isBlank()) return null
        return "http://$ip:${f.optInt("port", 8765)}"
    }
    private fun directPost(body: String): Boolean {
        val base = directBase() ?: return false; val ctx = app ?: return false
        return try {
            quick.newCall(Request.Builder().url("$base/link/in?k=${fernToken(ctx)}").post(body.toRequestBody("text/plain".toMediaType())).build()).execute().use { r ->
                if (r.isSuccessful) { directAt = System.currentTimeMillis(); directErr = ""; true } else { directErr = errText(Exception(), r.code); false }
            }
        } catch (e: Exception) { directErr = errText(e); false }
    }
    private fun remember(m: JSONObject) {
        synchronized(statusCache) { statusCache.addLast(m); while (statusCache.size > 60) statusCache.removeFirst() }
        m.optJSONObject("status")?.optJSONObject("fern")?.let { f -> app?.let { prefs(it).edit().putString("pc_fern", f.toString()).putLong("pc_fern_ts", m.optLong("ts")).apply() } }
    }

    /** Holt Nachrichten des PCs direkt über Tailscale ab (läuft neben listenPc). */
    @Volatile private var dFails = 0
    @Volatile var pcSeenAt = 0L          // letzte Nachricht vom PC (egal auf welchem Weg)
    @Volatile private var wakeUp = false
    /** Gleich wieder versuchen (z. B. du schickst etwas an den PC oder öffnest die Steuern-Seite). */
    fun poke() { wakeUp = true; dFails = 0 }
    private fun nap(ms: Long) { val end = System.currentTimeMillis() + ms; while (System.currentTimeMillis() < end && !wakeUp) Thread.sleep(1000); wakeUp = false }

    private fun directLoop(ctx: Context, alive: () -> Boolean, on: (JSONObject) -> Unit) {
        var after = 0L
        while (alive()) {
            val base = directBase()
            if (base == null || !paired(ctx)) { Thread.sleep(30_000); continue }
            try {
                val js = longPoll.newCall(Request.Builder().url("$base/link/out?k=${fernToken(ctx)}&after=$after&wait=20").build()).execute().use { r ->
                    if (!r.isSuccessful) { directErr = errText(Exception(), r.code); throw RuntimeException("HTTP ${r.code}") }
                    JSONObject(r.body?.string() ?: "{}")
                }
                directAt = System.currentTimeMillis(); directErr = ""
                after = js.optLong("seq", after)
                val a = js.optJSONArray("msgs") ?: JSONArray()
                val c = code(ctx)
                for (i in 0 until a.length()) {
                    val o = a.optJSONObject(i) ?: continue
                    val body = o.optString("body"); if (seen(body)) continue
                    val m = try { decrypt(body, c) } catch (_: Exception) { null } ?: continue
                    if (m.optString("from") != "pc") continue
                    pcSeenAt = System.currentTimeMillis()
                    if (o.optString("t") == "remote") remember(m)
                    else if (Math.abs(System.currentTimeMillis() / 1000 - m.optLong("ts")) <= 120) try { on(m) } catch (e: Exception) { Log.w(TAG, "auftrag direkt: $e") }
                }
            } catch (e: Exception) {
                directAt = 0L
                if (e !is RuntimeException || e.message?.startsWith("HTTP") != true) directErr = errText(e)
                // Tailscale/PC aus: immer seltener versuchen (15 s … 5 Min.) – Akku; bei einem Befehl an den PC sofort wieder
                dFails++
                nap(minOf(300_000L, 15_000L * (1L shl minOf(dFails - 1, 5))))
                continue
            }
            dFails = 0
        }
    }

    /** Letzter Status des PCs (Lebenszeichen kommt alle 30 Minuten). re = nur die Antwort auf diesen Befehl. */
    fun latestStatus(ctx: Context, since: String = "45m", re: String? = null): JSONObject? {
        val c = code(ctx); if (!paired(ctx)) return null
        val now = System.currentTimeMillis() / 1000
        val sinceSec = since.toLongOrNull() ?: Regex("(\\d+)([mh])").find(since)?.let { now - it.groupValues[1].toLong() * (if (it.groupValues[2] == "h") 3600 else 60) } ?: 0L
        synchronized(statusCache) {
            statusCache.filter { it.optString("kind") == "status" && it.optLong("ts") >= sinceSec && (re == null || it.optString("re") == re) }.maxByOrNull { it.optLong("ts") }
        }?.let { return it }
        if (directActive() && re != null) return null   // Antwort kommt direkt – ntfy nicht unnötig fragen
        val body = http.newCall(Request.Builder().url(SERVER + remoteTopic(c) + "/json?poll=1&since=$since").build()).execute().use {
            if (!it.isSuccessful) return null
            it.body?.string() ?: ""
        }
        var best: JSONObject? = null
        for (line in body.lines()) {
            val ev = try { JSONObject(line) } catch (_: Exception) { continue }
            if (ev.optString("event") != "message") continue
            var text = ev.optString("message")
            val att = ev.optJSONObject("attachment")
            if (!text.startsWith("J1.") && att != null) text = try {
                http.newCall(Request.Builder().url(att.optString("url")).build()).execute().use { it.body?.string() ?: "" }
            } catch (_: Exception) { "" }
            val m = try { decrypt(text, c) } catch (_: Exception) { null } ?: continue
            if (m.optString("kind") != "status" || m.optString("from") != "pc") continue
            if (re != null && m.optString("re") != re) continue
            remember(m)
            if (m.optLong("ts") >= (best?.optLong("ts") ?: 0L)) best = m
        }
        return best
    }

    // --- Aufträge vom PC ans Handy (eigener Kanal "jh…") ------------------------------------------------------
    private fun handyTopic(c: String) = "jh" + hex(sha("jarvis-handy:" + norm(c))).take(30)
    private val stream = http.newBuilder().readTimeout(100, TimeUnit.SECONDS).build()   // ntfy schickt alle 45 s ein Lebenszeichen

    /** Hört den Kanal ab, solange alive() stimmt, und gibt jeden frischen Auftrag des PCs an on(). */
    fun listenPc(ctx: Context, alive: () -> Boolean, on: (JSONObject) -> Unit) {
        Thread({ directLoop(ctx, alive, on) }, "jarvis-direkt").start()
        var wait = 5_000L
        var pollSince = System.currentTimeMillis() / 1000
        pcSeenAt = System.currentTimeMillis()   // die ersten 30 Min. normal verbunden
        while (alive()) {
            val c = code(ctx)
            if (!paired(ctx)) { Thread.sleep(60_000); continue }
            // Akku: Seit über 30 Min. nichts vom PC (PC aus) und App nicht offen -> statt Dauerverbindung alle 3 Min. kurz nachsehen
            if (System.currentTimeMillis() - pcSeenAt > 30 * 60_000L && !JarvisService.appVisible) {
                try {
                    http.newCall(Request.Builder().url(SERVER + handyTopic(c) + "/json?poll=1&since=$pollSince").build()).execute().use { resp ->
                        pollSince = System.currentTimeMillis() / 1000 - 5
                        (resp.body?.string() ?: "").lineSequence().forEach { line ->
                            val ev = try { JSONObject(line) } catch (_: Exception) { return@forEach }
                            if (ev.optString("event") != "message" || seen(ev.optString("message"))) return@forEach
                            val m = try { decrypt(ev.optString("message"), c) } catch (_: Exception) { null } ?: return@forEach
                            if (m.optString("from") != "pc") return@forEach
                            pcSeenAt = System.currentTimeMillis()
                            if (Math.abs(System.currentTimeMillis() / 1000 - m.optLong("ts")) <= 300) try { on(m) } catch (e: Exception) { Log.w(TAG, "auftrag: $e") }
                        }
                    }
                } catch (e: Exception) { Log.w(TAG, "poll: $e") }
                nap(3 * 60_000L)
                continue
            }
            pollSince = System.currentTimeMillis() / 1000
            try {
                stream.newCall(Request.Builder().url(SERVER + handyTopic(c) + "/json").build()).execute().use { resp ->
                    val src = resp.body?.source() ?: return@use
                    wait = 5_000L
                    while (alive() && !src.exhausted()) {
                        if (System.currentTimeMillis() - pcSeenAt > 30 * 60_000L && !JarvisService.appVisible) break   // PC lange still -> sparsam nachsehen
                        val line = src.readUtf8Line() ?: break
                        val ev = try { JSONObject(line) } catch (_: Exception) { continue }
                        if (ev.optString("event") != "message") continue
                        if (seen(ev.optString("message"))) continue   // schon direkt bekommen
                        val m = try { decrypt(ev.optString("message"), c) } catch (_: Exception) { null } ?: continue
                        if (m.optString("from") != "pc") continue
                        pcSeenAt = System.currentTimeMillis()
                        if (Math.abs(System.currentTimeMillis() / 1000 - m.optLong("ts")) > 120) continue   // alt
                        try { on(m) } catch (e: Exception) { Log.w(TAG, "auftrag: $e") }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "listenPc: $e")
                Thread.sleep(wait); wait = minOf(120_000L, wait * 2)
            }
        }
    }

    /** Antwort auf einen Auftrag des PCs (der PC spricht sie dann). */
    fun replyPc(ctx: Context, re: String, ok: Boolean, text: String, status: JSONObject? = null, url: String? = null, extra: JSONObject? = null) {
        val c = code(ctx); if (!paired(ctx)) return
        val m = JSONObject().put("kind", "phone_reply").put("from", "phone").put("re", re).put("ok", ok)
            .put("text", text).put("ts", System.currentTimeMillis() / 1000)
        if (status != null) m.put("status", status)
        if (url != null) m.put("url", url)
        if (extra != null) for (k in extra.keys()) m.put(k, extra.get(k))
        post(c, remoteTopic(c), m)
    }

    /** Meldung an den PC (z. B. neue WhatsApp-Nachricht), ohne auf Antwort zu warten. */
    fun toPc(ctx: Context, msg: JSONObject) {
        val c = code(ctx); if (!paired(ctx)) return
        post(c, remoteTopic(c), msg)
    }

    /** Fernzugriff über Tailscale: Schlüssel (aus dem Kopplungscode) und zuletzt gemeldete Adresse des PCs. */
    fun fernToken(ctx: Context) = hex(sha("jarvis-fern:" + norm(code(ctx)))).take(24)

    fun fernInfo(ctx: Context, refresh: Boolean): JSONObject {
        val p = prefs(ctx)
        if (refresh && paired(ctx)) try {
            // Antwort des PCs: {kind:"status", ts, status:{…, fern:{ip, port, cam}}}
            fun fernOf(m: JSONObject?) = m?.optJSONObject("status")?.optJSONObject("fern")
            var m = latestStatus(ctx, "24h")
            if (fernOf(m)?.optString("ip").isNullOrBlank())   // noch keine Adresse: den PC direkt fragen
                command(ctx, JSONObject().put("type", "status"), 15_000)?.let { if (fernOf(it) != null) m = it }
            m?.let { x -> p.edit().putString("pc_fern", (fernOf(x) ?: JSONObject()).toString()).putLong("pc_fern_ts", x.optLong("ts")).apply() }
        } catch (_: Exception) {}
        val f = try { JSONObject(p.getString("pc_fern", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        return f.put("token", if (paired(ctx)) fernToken(ctx) else "").put("paired", paired(ctx)).put("seen", p.getLong("pc_fern_ts", 0L))
    }

    /** Läuft der PC gerade? (Lebenszeichen in den letzten 35 Minuten) */
    fun pcOnline(ctx: Context): Boolean = try {
        val s = latestStatus(ctx, "35m"); s != null && System.currentTimeMillis() / 1000 - s.optLong("ts") < 35 * 60
    } catch (_: Exception) { false }

    /** Dem PC eine Erinnerung mitgeben (er spricht sie zur Zeit, falls er dann läuft). Ohne auf Antwort zu warten. */
    fun remindPc(ctx: Context, title: String, at: Long) {
        val c = code(ctx); if (!paired(ctx) || at <= System.currentTimeMillis()) return
        val cmd = JSONObject().put("type", "remind").put("text", title).put("at", at / 1000)
        post(c, remoteTopic(c), JSONObject().put("kind", "cmd").put("from", "phone").put("id", java.util.UUID.randomUUID().toString().take(12))
            .put("ts", System.currentTimeMillis() / 1000).put("cmd", cmd))
    }

    /** Neues ans PC schicken (Fakten, Stimmungen, Vergessen). */
    fun push(ctx: Context, facts: JSONArray = JSONArray(), moods: JSONArray = JSONArray(), forget: JSONArray = JSONArray()) {
        val c = code(ctx)
        if (!paired(ctx)) return
        val msg = JSONObject().put("kind", "add").put("from", "phone").put("ts", System.currentTimeMillis() / 1000)
            .put("facts", facts).put("moods", moods).put("forget", forget)
        Thread({
            try {
                http.newCall(Request.Builder().url(SERVER + topic(c))
                    .post(encrypt(msg, c).toRequestBody("text/plain".toMediaType())).build()).execute().close()
            } catch (e: Exception) { Log.w(TAG, "push: $e") }
        }, "jarvis-push").start()
    }
}
