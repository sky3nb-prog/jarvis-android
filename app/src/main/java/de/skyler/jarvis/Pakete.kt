package de.skyler.jarvis

import android.app.Notification
import android.content.Context
import android.service.notification.StatusBarNotification
import org.json.JSONArray
import org.json.JSONObject

/**
 * Pakete verfolgen: Jarvis liest Meldungen von DHL, Hermes, DPD, GLS, UPS, Amazon, Gmail und SMS mit,
 * erkennt Sendungsnummern und den Stand ("heute in Zustellung", "zugestellt") und sagt Bescheid, wenn ein Paket heute kommt.
 * "Wo ist mein Paket?" -> Überblick mit Link zur Sendungsverfolgung.
 */
object Pakete {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    private val APPS = mapOf(
        "de.dhl.paket" to "DHL", "com.hermesworld.hermesapp" to "Hermes", "de.hermes.android" to "Hermes", "com.dpd.yourdpd" to "DPD",
        "com.dpd.mydpd" to "DPD", "de.gls.mobile" to "GLS", "com.gls.app" to "GLS", "com.ups.mobile.android" to "UPS",
        "com.amazon.mShop.android.shopping" to "Amazon", "com.google.android.gm" to "", "com.google.android.apps.messaging" to "",
        "com.samsung.android.messaging" to "")
    private val WORDS = Regex("(?i)sendung|paket|päckchen|zustell|zugestellt|lieferung|geliefert|versand|verschickt|unterwegs|abholbereit|packstation|paketshop|parcel|delivery|shipped|out for delivery")
    private val NR = listOf(
        Regex("\\b(00340\\d{15}|JJD\\d{10,20}|\\d{12}|\\d{20})\\b") to "DHL",
        Regex("\\b(H\\d{19}|\\d{14})\\b") to "Hermes/DPD",
        Regex("\\b(1Z[0-9A-Z]{16})\\b") to "UPS",
        Regex("\\b(TBA\\d{9,12})\\b") to "Amazon")
    private fun status(t: String): String = when {
        Regex("(?i)zugestellt|wurde geliefert|ist da\\b|delivered|abgegeben bei|im briefkasten").containsMatchIn(t) -> "zugestellt"
        Regex("(?i)abholbereit|liegt .*(filiale|packstation|paketshop)|zur abholung").containsMatchIn(t) -> "abholen"
        Regex("(?i)heute|in zustellung|wird zugestellt|zustellfahrzeug|out for delivery|kommt heute").containsMatchIn(t) -> "heute"
        Regex("(?i)morgen").containsMatchIn(t) -> "morgen"
        Regex("(?i)unterwegs|versandt|verschickt|shipped|auf dem weg|im zentrum|bearbeitet").containsMatchIn(t) -> "unterwegs"
        else -> "info"
    }
    private fun carrierOf(t: String, app: String): String = app.ifBlank {
        listOf("DHL", "Hermes", "DPD", "GLS", "UPS", "Amazon").firstOrNull { Regex("(?i)\\b$it\\b").containsMatchIn(t) } ?: ""
    }
    fun link(carrier: String, nr: String): String = when {
        nr.isBlank() -> ""
        carrier.contains("DHL") -> "https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode=$nr"
        carrier.contains("Hermes") -> "https://www.myhermes.de/empfangen/sendungsverfolgung/sendungsinformation/#$nr"
        carrier.contains("DPD") -> "https://tracking.dpd.de/status/de_DE/parcel/$nr"
        carrier.contains("GLS") -> "https://gls-group.com/DE/de/paketverfolgung?match=$nr"
        carrier.contains("UPS") -> "https://www.ups.com/track?tracknum=$nr"
        else -> "https://www.google.com/search?q=" + android.net.Uri.encode("Sendungsverfolgung $nr")
    }

    fun all(ctx: Context): JSONArray = try { JSONArray(prefs(ctx).getString("pakete", "[]")) } catch (_: Exception) { JSONArray() }

    fun onPosted(ctx: Context, sbn: StatusBarNotification, say: ((String) -> Unit)?) {
        val app = APPS[sbn.packageName] ?: return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        val ex = n.extras ?: return
        val title = ex.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: ""
        val text = (ex.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: ex.getCharSequence(Notification.EXTRA_TEXT))?.toString() ?: ""
        val all = "$title $text"
        if (app.isBlank() && !WORDS.containsMatchIn(all)) return          // Gmail/SMS: nur Versandmeldungen
        if (sbn.packageName == "com.amazon.mShop.android.shopping" && !WORDS.containsMatchIn(all)) return
        val nr = NR.firstNotNullOfOrNull { (r, _) -> r.find(all)?.groupValues?.get(1) } ?: ""
        val carrier = carrierOf(all, app)
        val st = status(all)
        if (st == "info" && nr.isBlank()) return
        val a = all(ctx); val now = System.currentTimeMillis()
        // gleiches Paket? (Nummer, sonst Absender + gleicher Tag)
        var o: JSONObject? = null
        for (i in 0 until a.length()) a.optJSONObject(i)?.let { if ((nr.isNotBlank() && it.optString("nr") == nr) || (nr.isBlank() && it.optString("nr").isBlank() && it.optString("carrier") == carrier && now - it.optLong("t") < 3 * 86_400_000L && it.optString("status") != "zugestellt")) o = it }
        val old = o?.optString("status") ?: ""
        val p = o ?: JSONObject().put("first", now).also { a.put(it) }
        p.put("nr", nr.ifBlank { p.optString("nr") }).put("carrier", carrier.ifBlank { p.optString("carrier") }).put("status", st).put("t", now)
            .put("text", (if (title.isNotBlank()) "$title: " else "") + text.take(200))
        while (a.length() > 30) a.remove(0)
        // erledigte nach 3 Tagen raus
        val keep = JSONArray(); for (i in 0 until a.length()) a.optJSONObject(i)?.let { if (it.optString("status") != "zugestellt" || now - it.optLong("t") < 3 * 86_400_000L) keep.put(it) }
        prefs(ctx).edit().putString("pakete", keep.toString()).apply()
        if (st != old && say != null) {
            val wer = p.optString("carrier").ifBlank { "Dein" }.let { if (it == "Dein") "Dein Paket" else "Dein $it-Paket" }
            when (st) {
                "heute" -> say("$wer kommt heute.")
                "abholen" -> say("$wer liegt zum Abholen bereit.")
                "zugestellt" -> if (old.isNotBlank()) say("$wer wurde zugestellt.")
            }
        }
    }

    /** "Wo ist mein Paket?" */
    fun summary(ctx: Context): String {
        val a = all(ctx); if (a.length() == 0) return "Ich sehe gerade keine Pakete. Ich lese Meldungen von DHL, Hermes, DPD, GLS, UPS, Amazon, Gmail und SMS mit."
        val names = mapOf("heute" to "kommt heute", "morgen" to "kommt morgen", "abholen" to "liegt zum Abholen bereit", "unterwegs" to "ist unterwegs", "zugestellt" to "wurde zugestellt", "info" to "hat eine neue Meldung")
        return (0 until a.length()).mapNotNull { a.optJSONObject(it) }.sortedByDescending { it.optLong("t") }.take(5).joinToString(" ") {
            "${it.optString("carrier").ifBlank { "Ein" }}-Paket${if (it.optString("nr").isNotBlank()) " (…${it.optString("nr").takeLast(4)})" else ""} ${names[it.optString("status")] ?: ""}."
        }.replace("Ein-Paket", "Ein Paket")
    }
}
