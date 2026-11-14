package de.skyler.jarvis

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.PowerManager
import android.provider.Settings
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Systemcheck am Handy ("Friday, Statuscheck"): prüft alles, was Jarvis braucht.
 * Jeder Punkt: id, name, ok (true / false / null = nicht eingerichtet), detail, fix.
 */
object SysCheck {
    private val http = OkHttpClient.Builder().connectTimeout(6, TimeUnit.SECONDS).readTimeout(8, TimeUnit.SECONDS).build()
    @Volatile var last: JSONArray = JSONArray()
    @Volatile var lastT = 0L

    private fun item(id: String, name: String, ok: Boolean?, detail: String, fix: String = "") =
        JSONObject().put("id", id).put("name", name).put("ok", ok ?: JSONObject.NULL).put("detail", detail).put("fix", fix)

    private fun get(url: String, auth: String? = null): Int = try {
        http.newCall(Request.Builder().url(url).apply { if (auth != null) header("Authorization", auth) }.build()).execute().use { it.code }
    } catch (_: Exception) { -1 }

    private fun perm(ctx: Context, p: String) = ctx.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    fun run(ctx: Context): JSONArray {
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val a = JSONArray()
        val net = get("https://www.google.com/generate_204")
        a.put(if (net in 200..399) item("net", "Internet", true, "verbunden") else item("net", "Internet", false, "keine Verbindung", "WLAN oder mobile Daten prüfen."))
        val groq = p.getString("groq_key", "") ?: ""
        if (groq.isBlank()) a.put(item("groq", "Groq (KI)", false, "kein Schlüssel", "Einstellungen → Allgemein: Groq-Schlüssel eintragen."))
        else { val c = get("https://api.groq.com/openai/v1/models", "Bearer $groq")
            a.put(if (c == 200) item("groq", "Groq (KI)", true, "Schlüssel gültig") else item("groq", "Groq (KI)", false, if (c < 0) "nicht erreichbar" else "Fehler $c", "Groq-Schlüssel prüfen (console.groq.com).")) }
        val gem = p.getString("gemini_key", "") ?: ""
        if (gem.isBlank()) a.put(item("gemini", "Gemini (Sehen)", null, "nicht eingerichtet"))
        else { val c = get("https://generativelanguage.googleapis.com/v1beta/models?key=$gem&pageSize=1")
            a.put(if (c == 200) item("gemini", "Gemini (Sehen)", true, "Schlüssel gültig") else item("gemini", "Gemini (Sehen)", false, "Fehler $c", "Gemini-Schlüssel prüfen (Google AI Studio).")) }
        a.put(if (perm(ctx, Manifest.permission.RECORD_AUDIO)) item("mic", "Mikrofon", true, "erlaubt") else item("mic", "Mikrofon", false, "nicht erlaubt", "App öffnen und Mikrofon erlauben."))
        a.put(if (VoskModel.ready(ctx)) item("wake", "Weckwort „Friday“", true, "bereit") else item("wake", "Weckwort „Friday“", false, "Sprachmodell fehlt", "App einmal mit Internet öffnen – das Modell lädt dann."))
        if (!Link.paired(ctx)) a.put(item("pc", "PC-Kopplung", null, "nicht gekoppelt", "Einstellungen → Allgemein: Kopplungscode vom PC eintragen."))
        else a.put(if (Link.pcOnline(ctx)) item("pc", "PC-Kopplung", true, "PC online") else item("pc", "PC-Kopplung", null, "PC aus oder schläft"))
        val listeners = Settings.Secure.getString(ctx.contentResolver, "enabled_notification_listeners") ?: ""
        a.put(if (listeners.contains(ctx.packageName)) item("notif", "Benachrichtigungen lesen", true, "an (WhatsApp, Musik)")
            else item("notif", "Benachrichtigungen lesen", false, "aus", "Einstellungen → Leute & Anrufe: Benachrichtigungszugriff für Jarvis einschalten."))
        val pm = ctx.getSystemService(Context.POWER_SERVICE) as PowerManager
        a.put(if (pm.isIgnoringBatteryOptimizations(ctx.packageName)) item("akku", "Läuft im Hintergrund", true, "Akku: nicht eingeschränkt")
            else item("akku", "Läuft im Hintergrund", false, "Akku spart Jarvis aus", "Android-Einstellungen → Apps → Jarvis → Akku: „Nicht eingeschränkt“."))
        val locAlways = perm(ctx, Manifest.permission.ACCESS_BACKGROUND_LOCATION)
        a.put(if (locAlways) item("loc", "Standort (immer)", true, "erlaubt") else item("loc", "Standort (immer)", false, "nur beim Öffnen", "Einstellungen → Alltag: Standort „Immer erlauben“ (für Wege und Ankunft)."))
        a.put(if (JarvisService.running) item("svc", "Jarvis-Dienst", true, "läuft") else item("svc", "Jarvis-Dienst", false, "läuft nicht", "App öffnen und „Im Hintergrund zuhören“ einschalten."))
        try {
            a.put(if (Health.connected(ctx)) item("health", "Samsung Health", true, "verbunden") else item("health", "Samsung Health", null, "nicht verbunden", "Einstellungen → Gesundheit: Verbinden."))
        } catch (_: Exception) {}
        a.put(if (ScreenService.enabled()) item("screen", "Bedienungshilfe", true, "an (Schlaf genau, „Schau mal hier“)") else item("screen", "Bedienungshilfe", null, "aus"))
        val wx = get("https://api.open-meteo.com/v1/forecast?latitude=48.8&longitude=9.0&current=temperature_2m")
        a.put(if (wx == 200) item("wx", "Wetter", true, "erreichbar") else item("wx", "Wetter", false, "nicht erreichbar", "Internet prüfen."))
        last = a; lastT = System.currentTimeMillis()
        return a
    }

    /** Test-Knopf neben jedem Punkt: probiert es wirklich aus. */
    fun test(ctx: Context, id: String): String = try {
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        when (id) {
            "net" -> { val t0 = System.currentTimeMillis(); val c = get("https://www.google.com/generate_204"); if (c in 200..399) "Internet antwortet in ${System.currentTimeMillis() - t0} ms." else "Keine Verbindung." }
            "groq" -> "Groq sagt: " + Groq.chat(p.getString("groq_key", "") ?: "", JSONArray().put(JSONObject().put("role", "user")
                .put("content", "Sag in höchstens 8 Wörtern auf Deutsch hallo, als Jarvis.")), 40).trim()
            "gemini" -> if (get("https://generativelanguage.googleapis.com/v1beta/models?key=${p.getString("gemini_key", "")}&pageSize=1") == 200) "Gemini antwortet." else "Gemini antwortet nicht – Schlüssel prüfen."
            "mic", "wake" -> "Sag jetzt „Friday“ – wenn die Kugel reagiert und „hört zu“ erscheint, passt alles."
            "pc" -> Link.command(ctx, JSONObject().put("type", "say").put("text", "Test vom Handy – die Verbindung steht.").put("need_active", false), 15_000)
                ?.let { if (it.optBoolean("ok")) "Der PC hat geantwortet und sagt gleich einen Testsatz." else "Der PC hat abgelehnt: ${it.optString("text")}" } ?: "Der PC antwortet nicht (aus oder Jarvis zu)."
            "notif" -> "Schick dir eine WhatsApp von einem deiner wichtigen Leute – am PC wird sie angesagt, wenn alles passt."
            "akku" -> { val b = ctx.registerReceiver(null, android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
                "Akku ${(b?.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1) ?: -1)} %, " + (if ((ctx.getSystemService(Context.POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(ctx.packageName)) "Jarvis darf im Hintergrund laufen." else "Android bremst Jarvis noch.") }
            "loc" -> Alltag.fix?.let { "Letzter Standort vor ${(System.currentTimeMillis() - it.time) / 60_000} Min., genau auf ${it.accuracy.toInt()} m. " + (if (Alltag.isHome(ctx)) "Du bist zuhause." else "Du bist unterwegs.") } ?: "Noch kein Standort – kurz rausgehen oder die App öffnen."
            "svc" -> { JarvisService.say(ctx, "Test. Ich laufe im Hintergrund."); "Ich sage gleich einen Testsatz." }
            "health" -> Health.text(Health.day(ctx, 0))
            "screen" -> Sleep.text(Sleep.night(ctx, 0))
            "wx" -> { val js = JSONObject(http.newCall(Request.Builder().url("https://api.open-meteo.com/v1/forecast?latitude=48.8&longitude=9.0&current=temperature_2m,apparent_temperature").build()).execute().use { it.body?.string() ?: "{}" }).optJSONObject("current")
                "Leonberg gerade ${js?.optDouble("temperature_2m")} °C, gefühlt ${js?.optDouble("apparent_temperature")} °C." }
            else -> "Für diesen Punkt gibt es keinen Test."
        }
    } catch (e: Exception) { "Test ging nicht: ${e.message}" }

    fun summary(a: JSONArray = last): String {
        val bad = (0 until a.length()).map { a.getJSONObject(it) }.filter { it.opt("ok") == false }
        if (bad.isEmpty()) return "Alle Systeme laufen, Sir. ${(0 until a.length()).count { a.getJSONObject(it).opt("ok") == true }} Prüfungen grün."
        return (if (bad.size == 1) "Ein Problem: " else "${bad.size} Probleme: ") + bad.joinToString(" ") { "${it.optString("name")}: ${it.optString("detail")}. ${it.optString("fix")}".trim() }
    }
}
