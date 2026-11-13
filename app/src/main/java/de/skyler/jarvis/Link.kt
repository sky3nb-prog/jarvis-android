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
    fun code(ctx: Context) = prefs(ctx).getString("link_code", "") ?: ""
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
                k == "anrede" || k == "assistant_name" || k == "city" || k == "address" || k == "lage_orte" -> e.putString(k, s.optString(k))
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
        (p.getString("assistant_name", "") ?: "").takeIf { it.isNotBlank() }?.let { set.put("assistant_name", it) }
        set.put("themen_selbst", Themen.manual(ctx).joinToString(", "))
        for (k in BOOL_KEYS) set.put(k, p.getBoolean(k, true))
        post(c, topic(c), JSONObject().put("kind", "settings").put("from", "phone").put("ts", ts).put("settings", set))
    }

    /** Gelernte Themen ans PC schicken (damit der PC-Jarvis dieselben Interessen kennt). */
    fun pushThemen(ctx: Context, themen: JSONArray) {
        val c = code(ctx); if (!paired(ctx)) return
        post(c, topic(c), JSONObject().put("kind", "themen").put("from", "phone").put("ts", System.currentTimeMillis() / 1000).put("themen", themen))
    }

    private fun post(c: String, t: String, msg: JSONObject) {
        Thread({
            try {
                http.newCall(Request.Builder().url(SERVER + t).post(encrypt(msg, c).toRequestBody("text/plain".toMediaType())).build()).execute().close()
            } catch (e: Exception) { Log.w(TAG, "post: $e") }
        }, "jarvis-post").start()
    }

    // --- Fernbedienung für den PC (eigener Kanal) --------------------------------------------------------------
    private fun remoteTopic(c: String) = "jr" + hex(sha("jarvis-remote:" + norm(c))).take(30)

    /** Befehl an den PC schicken und bis zu 15 Sekunden auf die Antwort warten. Antwort: {ok, text, status} oder null. */
    fun command(ctx: Context, cmd: JSONObject): JSONObject? {
        val c = code(ctx); if (!paired(ctx)) return null
        val id = java.util.UUID.randomUUID().toString().take(12)
        val sent = System.currentTimeMillis() / 1000
        val msg = JSONObject().put("kind", "cmd").put("from", "phone").put("id", id).put("ts", sent).put("cmd", cmd)
        http.newCall(Request.Builder().url(SERVER + remoteTopic(c)).post(encrypt(msg, c).toRequestBody("text/plain".toMediaType())).build()).execute().close()
        val until = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < until) {
            Thread.sleep(1500)
            val r = latestStatus(ctx, "${sent - 2}", id)
            if (r != null) return r
        }
        return null
    }

    /** Letzter Status des PCs (Lebenszeichen kommt alle 30 Minuten). re = nur die Antwort auf diesen Befehl. */
    fun latestStatus(ctx: Context, since: String = "45m", re: String? = null): JSONObject? {
        val c = code(ctx); if (!paired(ctx)) return null
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
            if (m.optLong("ts") >= (best?.optLong("ts") ?: 0L)) best = m
        }
        return best
    }

    // --- Aufträge vom PC ans Handy (eigener Kanal "jh…") ------------------------------------------------------
    private fun handyTopic(c: String) = "jh" + hex(sha("jarvis-handy:" + norm(c))).take(30)
    private val stream = http.newBuilder().readTimeout(100, TimeUnit.SECONDS).build()   // ntfy schickt alle 45 s ein Lebenszeichen

    /** Hört den Kanal ab, solange alive() stimmt, und gibt jeden frischen Auftrag des PCs an on(). */
    fun listenPc(ctx: Context, alive: () -> Boolean, on: (JSONObject) -> Unit) {
        var wait = 5_000L
        while (alive()) {
            val c = code(ctx)
            if (!paired(ctx)) { Thread.sleep(60_000); continue }
            try {
                stream.newCall(Request.Builder().url(SERVER + handyTopic(c) + "/json").build()).execute().use { resp ->
                    val src = resp.body?.source() ?: return@use
                    wait = 5_000L
                    while (alive() && !src.exhausted()) {
                        val line = src.readUtf8Line() ?: break
                        val ev = try { JSONObject(line) } catch (_: Exception) { continue }
                        if (ev.optString("event") != "message") continue
                        val m = try { decrypt(ev.optString("message"), c) } catch (_: Exception) { null } ?: continue
                        if (m.optString("from") != "pc") continue
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
    fun replyPc(ctx: Context, re: String, ok: Boolean, text: String, status: JSONObject? = null, url: String? = null) {
        val c = code(ctx); if (!paired(ctx)) return
        val m = JSONObject().put("kind", "phone_reply").put("from", "phone").put("re", re).put("ok", ok)
            .put("text", text).put("ts", System.currentTimeMillis() / 1000)
        if (status != null) m.put("status", status)
        if (url != null) m.put("url", url)
        post(c, remoteTopic(c), m)
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
