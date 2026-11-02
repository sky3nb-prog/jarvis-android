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
        Memory.prune(ctx, snap)
        Log.i(TAG, "Stand vom PC: ${snap.optJSONArray("facts")?.length()} Fakten")
        return true
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
