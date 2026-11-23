package de.skyler.jarvis

import android.content.Context
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec

/**
 * Jarvis-Konto (Test): Anmelden mit E-Mail und Passwort (Firebase), danach liegen deine Einstellungen,
 * dein Gedächtnis und die Kopplung im Konto – auf jedem Handy gleich.
 * Alles wird VOR dem Hochladen mit deinem Passwort verschlüsselt (gleiches Verfahren wie die PC-Kopplung, Schlüssel
 * per PBKDF2 aus Passwort + E-Mail). Der Server sieht nur Kauderwelsch. Passwort vergessen = Daten weg.
 * Firebase-Zugang steht in assets/web/konto_config.json (apiKey, projectId – sind bei Firebase öffentlich gedacht,
 * geschützt wird über die Regeln: jeder darf nur sein eigenes Dokument users/<uid>).
 */
object Konto {
    private const val TAG = "JarvisKonto"
    /** Deine normale App: nur hochladen (Sicherung), nie etwas aus dem Konto über dein Handy schreiben. Einmal verbinden, kein Abmelden. */
    private fun backup(ctx: Context) = ctx.packageName == "de.skyler.jarvis"
    private val http = OkHttpClient.Builder().connectTimeout(12, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS).build()
    private val JSON_T = "application/json; charset=utf-8".toMediaType()
    private val SKIP_FILES = Regex("^(satelliten\\.tle|.*\\.zip|vosk.*)$")

    private fun kp(ctx: Context) = ctx.getSharedPreferences("konto", Context.MODE_PRIVATE)
    private fun jp(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    private var cfgCache: JSONObject? = null
    fun cfg(ctx: Context): JSONObject = cfgCache ?: try {
        JSONObject(ctx.assets.open("web/konto_config.json").bufferedReader().use { it.readText() })
    } catch (_: Exception) { JSONObject() }.also { cfgCache = it }

    /** Läuft die normale Jarvis-App auch auf diesem Handy? Dann hört die Konto-App nicht von selbst im Hintergrund mit. */
    fun parallel(ctx: Context) = try { ctx.packageManager.getPackageInfo("de.skyler.jarvis", 0); ctx.packageName != "de.skyler.jarvis" } catch (_: Exception) { false }

    fun configured(ctx: Context) = cfg(ctx).optString("apiKey").length > 10 && cfg(ctx).optString("projectId").isNotBlank()
    fun loggedIn(ctx: Context) = kp(ctx).getString("uid", "").orEmpty().isNotBlank() && kp(ctx).getString("secret", "").orEmpty().isNotBlank()

    // ---- Tresor: Schlüssel und Anmelde-Tickets liegen verschlüsselt mit dem Android-Schlüsselspeicher (Keystore) ------
    // Der Tresor-Schlüssel steckt in der Hardware des Handys und lässt sich nicht herauskopieren.
    private const val KS_ALIAS = "jarvis_konto_tresor"
    private fun tresorKey(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getEntry(KS_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        g.init(KeyGenParameterSpec.Builder(KS_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build())
        return g.generateKey()
    }
    private fun seal(plain: String): String {
        if (plain.isEmpty()) return ""
        val c = Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.ENCRYPT_MODE, tresorKey())
        val out = c.iv + c.doFinal(plain.toByteArray())
        return "K:" + Base64.encodeToString(out, Base64.NO_WRAP)
    }
    private fun unseal(v: String?): String {
        val t = v.orEmpty()
        if (!t.startsWith("K:")) return t   // alter Stand (vor dem Tresor): wird beim nächsten Speichern verschlüsselt
        return try {
            val b = Base64.decode(t.substring(2), Base64.NO_WRAP)
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, tresorKey(), GCMParameterSpec(128, b, 0, 12))
            String(c.doFinal(b, 12, b.size - 12))
        } catch (e: Exception) { Log.w(TAG, "Tresor: $e"); "" }
    }
    /** Alte, noch unverschlüsselte Werte einmal in den Tresor legen. */
    private fun upgradeTresor(ctx: Context) {
        val p = kp(ctx); val e = p.edit(); var any = false
        for (k in listOf("secret", "secret_old", "id", "refresh")) {
            val v = p.getString(k, "").orEmpty()
            if (v.isNotEmpty() && !v.startsWith("K:")) try { e.putString(k, seal(v)); any = true } catch (x: Exception) { Log.w(TAG, "Tresor: $x") }
        }
        if (any) e.apply()
    }
    private fun secrets(ctx: Context): List<String> {
        upgradeTresor(ctx)
        return listOf(unseal(kp(ctx).getString("secret", "")), unseal(kp(ctx).getString("secret_old", ""))).filter { it.isNotBlank() }.distinct()
    }
    /** Mit dem aktuellen Schlüssel entschlüsseln, sonst mit dem alten (Daten von Geräten, die noch die alte Verschlüsselung nutzen). */
    private fun decryptAny(ctx: Context, data: String): JSONObject? {
        for (k in secrets(ctx)) Link.decrypt(data, k)?.let { return it }
        return null
    }

    fun info(ctx: Context): JSONObject = JSONObject().put("configured", configured(ctx)).put("loggedIn", loggedIn(ctx))
        .put("email", kp(ctx).getString("email", "")).put("lastPush", kp(ctx).getLong("last_push", 0)).put("lastPull", kp(ctx).getLong("last_pull", 0))
        .put("err", kp(ctx).getString("err", "")).put("parallel", parallel(ctx))

    /** v2: 600.000 Durchgänge (heutige Empfehlung). v1: alte 60.000 – nur noch zum Lesen alter Daten. */
    private fun secretOf(email: String, pw: String, v: Int = 2): String {
        val salt = (if (v >= 2) "jarvis-konto2:" else "jarvis-konto:") + email.trim().lowercase()
        val spec = PBEKeySpec(pw.toCharArray(), salt.toByteArray(), if (v >= 2) 600_000 else 60_000, 256)
        val k = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
        return k.joinToString("") { "%02x".format(it) }
    }

    private fun post(url: String, body: String, auth: String? = null, method: String = "POST"): JSONObject {
        val rb = Request.Builder().url(url).method(method, body.toRequestBody(JSON_T))
        if (auth != null) rb.header("Authorization", "Bearer $auth")
        http.newCall(rb.build()).execute().use { r ->
            val t = r.body?.string() ?: "{}"
            val j = try { JSONObject(t) } catch (_: Exception) { JSONObject() }
            if (!r.isSuccessful) throw RuntimeException(fbError(j.optJSONObject("error")?.optString("message") ?: "HTTP ${r.code}"))
            return j
        }
    }

    private fun fbError(m: String): String = when {
        m.startsWith("EMAIL_EXISTS") -> "Die E-Mail hat schon ein Konto – tipp auf „Anmelden“."
        m.startsWith("EMAIL_NOT_FOUND") || m.startsWith("INVALID_LOGIN_CREDENTIALS") || m.startsWith("INVALID_PASSWORD") -> "E-Mail oder Passwort stimmt nicht."
        m.startsWith("WEAK_PASSWORD") -> "Passwort zu kurz – mindestens 6 Zeichen."
        m.startsWith("INVALID_EMAIL") -> "Das ist keine gültige E-Mail."
        m.startsWith("OPERATION_NOT_ALLOWED") -> "In Firebase ist E-Mail/Passwort noch nicht eingeschaltet."
        m.startsWith("TOO_MANY_ATTEMPTS") -> "Zu viele Versuche – kurz warten."
        m.contains("PERMISSION_DENIED") || m.contains("permission") -> "Firebase-Regeln fehlen noch (Firestore → Regeln)."
        else -> m
    }

    /** Anmelden (neu = Konto anlegen). Danach: Daten aus dem Konto holen – oder, wenn das Konto leer ist, dieses Handy hochladen. */
    fun signIn(ctx: Context, email: String, pw: String, neu: Boolean): JSONObject {
        if (!configured(ctx)) return JSONObject().put("ok", false).put("text", "Das Konto ist noch nicht eingerichtet (Firebase fehlt).")
        return try {
            val key = cfg(ctx).optString("apiKey")
            val ep = if (neu) "signUp" else "signInWithPassword"
            val r = post("https://identitytoolkit.googleapis.com/v1/accounts:$ep?key=$key",
                JSONObject().put("email", email.trim()).put("password", pw).put("returnSecureToken", true).toString())
            kp(ctx).edit().putString("email", email.trim()).putString("uid", r.optString("localId"))
                .putString("id", seal(r.optString("idToken"))).putString("refresh", seal(r.optString("refreshToken")))
                .putLong("exp", System.currentTimeMillis() + (r.optString("expiresIn", "3600").toLongOrNull() ?: 3600) * 1000 - 60_000)
                .putString("secret", seal(secretOf(email, pw, 2))).putString("secret_old", seal(secretOf(email, pw, 1)))
                .putString("err", "").commit()
            if (backup(ctx)) { push(ctx, force = true); return JSONObject().put("ok", true).put("text", "Verbunden – dein Vector ist jetzt in deinem Konto gesichert.") }
            val doc = getDoc(ctx)
            val txt = if (doc != null && doc.has("android")) {
                val ok = try { pull(ctx, doc, force = true); true } catch (e: Exception) { false }
                if (ok) "Angemeldet – deine Sachen sind geladen."
                else {   // z. B. nach „Passwort vergessen“: alte Sicherung war mit dem alten Passwort verschlüsselt
                    push(ctx, force = true)
                    "Angemeldet. Die alte Sicherung war mit deinem früheren Passwort verschlüsselt und lässt sich nicht mehr öffnen – dieses Handy ist jetzt der neue Stand im Konto."
                }
            } else { push(ctx, force = true); if (neu) "Konto angelegt – dieses Handy ist jetzt im Konto." else "Angemeldet – dieses Handy ist jetzt im Konto." }
            JSONObject().put("ok", true).put("text", txt)
        } catch (e: Exception) { Log.w(TAG, "signIn: $e"); JSONObject().put("ok", false).put("text", e.message ?: "Ging nicht.") }
    }

    fun signOut(ctx: Context) { kp(ctx).edit().clear().commit() }

    /** „Passwort vergessen“: Firebase schickt eine Mail zum Zurücksetzen. */
    fun resetPassword(ctx: Context, email: String): JSONObject = try {
        if (!configured(ctx)) throw RuntimeException("Das Konto ist noch nicht eingerichtet.")
        if (!email.contains("@")) throw RuntimeException("Bitte zuerst deine E-Mail eintragen.")
        post("https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key=${cfg(ctx).optString("apiKey")}",
            JSONObject().put("requestType", "PASSWORD_RESET").put("email", email.trim()).toString())
        JSONObject().put("ok", true).put("text", "Mail ist unterwegs – schau auch im Spam-Ordner. Danach mit dem neuen Passwort anmelden.")
    } catch (e: Exception) { JSONObject().put("ok", false).put("text", e.message ?: "Ging nicht.") }

    /** Selbstzerstörung: auf diesem Handy abmelden. Die Sicherung im Konto bleibt – nach einer Neuinstallation
     *  und Anmeldung ist alles wieder da. */
    fun forgetDevice(ctx: Context) { signOut(ctx) }

    private fun token(ctx: Context): String {
        val p = kp(ctx)
        upgradeTresor(ctx)
        if (System.currentTimeMillis() < p.getLong("exp", 0)) return unseal(p.getString("id", ""))
        val key = cfg(ctx).optString("apiKey")
        val req = Request.Builder().url("https://securetoken.googleapis.com/v1/token?key=$key")
            .post("grant_type=refresh_token&refresh_token=${unseal(p.getString("refresh", ""))}".toRequestBody("application/x-www-form-urlencoded".toMediaType())).build()
        http.newCall(req).execute().use { r ->
            val j = JSONObject(r.body?.string() ?: "{}")
            if (!r.isSuccessful) throw RuntimeException("Anmeldung abgelaufen – bitte neu anmelden.")
            p.edit().putString("id", seal(j.optString("id_token"))).putString("refresh", seal(j.optString("refresh_token")))
                .putLong("exp", System.currentTimeMillis() + (j.optString("expires_in", "3600").toLongOrNull() ?: 3600) * 1000 - 60_000).apply()
            return j.optString("id_token")
        }
    }

    private fun docUrl(ctx: Context) =
        "https://firestore.googleapis.com/v1/projects/${cfg(ctx).optString("projectId")}/databases/(default)/documents/users/${kp(ctx).getString("uid", "")}"

    /** Das Konto-Dokument als einfache Map (Feldname -> Text/Zahl) oder null, wenn es noch keins gibt. */
    private fun getDoc(ctx: Context): JSONObject? {
        val req = Request.Builder().url(docUrl(ctx)).header("Authorization", "Bearer ${token(ctx)}").build()
        http.newCall(req).execute().use { r ->
            if (r.code == 404) return null
            val j = JSONObject(r.body?.string() ?: "{}")
            if (!r.isSuccessful) throw RuntimeException(fbError(j.optJSONObject("error")?.optString("message") ?: "HTTP ${r.code}"))
            val f = j.optJSONObject("fields") ?: return JSONObject()
            val out = JSONObject()
            f.keys().forEach { k -> val v = f.getJSONObject(k); out.put(k, if (v.has("integerValue")) v.optString("integerValue").toLongOrNull() ?: 0 else v.optString("stringValue")) }
            return out
        }
    }

    private fun patch(ctx: Context, fields: Map<String, Any>) {
        val f = JSONObject()
        fields.forEach { (k, v) -> f.put(k, if (v is Long || v is Int) JSONObject().put("integerValue", v.toString()) else JSONObject().put("stringValue", v.toString())) }
        val mask = fields.keys.joinToString("&") { "updateMask.fieldPaths=$it" }
        post(docUrl(ctx) + "?" + mask, JSONObject().put("fields", f).toString(), token(ctx), "PATCH")
    }

    // ---- Was ins Konto kommt: alle Jarvis-Einstellungen + kleine Datendateien ---------------------------------------
    private fun snapshot(ctx: Context): JSONObject {
        val pr = JSONObject()
        jp(ctx).all.forEach { (k, v) ->
            when (v) {
                is Boolean -> pr.put(k, JSONArray().put("b").put(v))
                is Int -> pr.put(k, JSONArray().put("i").put(v))
                is Long -> pr.put(k, JSONArray().put("l").put(v))
                is Float -> pr.put(k, JSONArray().put("f").put(v.toDouble()))
                is String -> pr.put(k, JSONArray().put("s").put(v))
                is Set<*> -> pr.put(k, JSONArray().put("set").put(JSONArray(v.map { it.toString() })))
            }
        }
        val files = JSONObject()
        ctx.filesDir.listFiles()?.forEach { f ->
            if (f.isFile && f.length() < 400_000 && (f.name.endsWith(".json") || f.name.endsWith(".txt")) && !SKIP_FILES.matches(f.name))
                try { files.put(f.name, f.readText()) } catch (_: Exception) {}
        }
        return JSONObject().put("v", 1).put("prefs", pr).put("files", files).put("geraet", android.os.Build.MODEL)
    }

    private fun apply(ctx: Context, o: JSONObject) {
        val pr = o.optJSONObject("prefs") ?: return
        val keepLocal = setOf("upd_check", "upd_told", "background")
        val e = jp(ctx).edit()
        pr.keys().forEach { k ->
            if (k in keepLocal) return@forEach
            val a = pr.optJSONArray(k) ?: return@forEach
            when (a.optString(0)) {
                "b" -> e.putBoolean(k, a.optBoolean(1)); "i" -> e.putInt(k, a.optInt(1)); "l" -> e.putLong(k, a.optLong(1))
                "f" -> e.putFloat(k, a.optDouble(1).toFloat()); "s" -> e.putString(k, a.optString(1))
                "set" -> { val s = a.optJSONArray(1); e.putStringSet(k, (0 until (s?.length() ?: 0)).map { s!!.optString(it) }.toSet()) }
            }
        }
        e.commit()
        val files = o.optJSONObject("files")
        files?.keys()?.forEach { n -> if (!n.contains("/") && !SKIP_FILES.matches(n)) try { File(ctx.filesDir, n).writeText(files.optString(n)) } catch (_: Exception) {} }
    }

    private fun hash(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }.take(24)

    /** Dieses Handy ins Konto (nur, wenn sich etwas geändert hat – außer force). */
    fun push(ctx: Context, force: Boolean = false): Boolean {
        if (!loggedIn(ctx)) return false
        val snap = snapshot(ctx)
        val h = hash(snap.optJSONObject("prefs").toString() + snap.optJSONObject("files").toString())
        val p = kp(ctx)
        if (!force && h == p.getString("hash", "")) return false
        val now = System.currentTimeMillis()
        val sec = secrets(ctx).firstOrNull() ?: return false
        val fields = mutableMapOf<String, Any>("android" to Link.encrypt(snap, sec), "android_t" to now)
        val code = Link.code(ctx)
        if (code.isNotBlank()) { fields["link"] = Link.encrypt(JSONObject().put("code", code), sec); fields["link_t"] = now }
        patch(ctx, fields)
        p.edit().putString("hash", h).putLong("last_push", now).putLong("remote_t", now).putString("err", "").apply()
        return true
    }

    /** Neueren Stand aus dem Konto holen (z. B. vom zweiten Handy). Kopplung vom PC übernehmen, wenn das Handy noch keine hat. */
    fun pull(ctx: Context, docIn: JSONObject? = null, force: Boolean = false): Boolean {
        if (!loggedIn(ctx) || backup(ctx)) return false
        val doc = docIn ?: getDoc(ctx) ?: return false
        val p = kp(ctx)
        var changed = false
        val lt = doc.optLong("link_t")
        if (doc.optString("link").isNotBlank() && (force || lt > p.getLong("link_t", 0))) {
            val c = decryptAny(ctx, doc.optString("link"))?.optString("code").orEmpty()
            if (c.isNotBlank() && c != Link.code(ctx)) { jp(ctx).edit().putString("link_code", c).commit(); changed = true }
            p.edit().putLong("link_t", lt).apply()
        }
        val t = doc.optLong("android_t")
        if (doc.optString("android").isNotBlank() && (force || t > p.getLong("remote_t", 0))) {
            val o = decryptAny(ctx, doc.optString("android"))
                ?: throw RuntimeException("Daten im Konto passen nicht zu deinem Schlüssel – bitte einmal ab- und wieder anmelden.")
            apply(ctx, o)
            val snap = snapshot(ctx)
            p.edit().putLong("remote_t", t).putLong("last_pull", System.currentTimeMillis())
                .putString("hash", hash(snap.optJSONObject("prefs").toString() + snap.optJSONObject("files").toString())).apply()
            changed = true
        }
        return changed
    }

    /** Alle paar Minuten aus dem Dienst: erst holen (wenn anderswo geändert), dann eigene Änderungen hochladen. */
    @Volatile private var busy = false
    fun tick(ctx: Context) {
        if (!loggedIn(ctx) || busy) return
        val p = kp(ctx)
        if (System.currentTimeMillis() - p.getLong("tick", 0) < 5 * 60_000L) return
        p.edit().putLong("tick", System.currentTimeMillis()).apply()
        busy = true
        Thread({
            try { pull(ctx); push(ctx) } catch (e: Exception) { Log.w(TAG, "sync: $e"); p.edit().putString("err", e.message ?: "").apply() } finally { busy = false }
        }, "jarvis-konto").start()
    }

    fun syncNow(ctx: Context): JSONObject = try {
        val a = pull(ctx); val b = push(ctx, force = true)
        JSONObject().put("ok", true).put("text", (if (a) "Neuen Stand geholt. " else "") + (if (b) "Hochgeladen." else "Alles aktuell."))
    } catch (e: Exception) { JSONObject().put("ok", false).put("text", e.message ?: "Ging nicht.") }
}
