package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Was du ausgibst – aus deinen Mails (PayPal, Amazon, Rewe, Rechnungen, Kaufbelege), ohne Bank- oder PayPal-Zugang:
 * Jarvis liest nur den Betrag aus der Bestätigungsmail. „Wie viel hab ich diesen Monat ausgegeben?“ und ein Hinweis,
 * wenn du über deiner Grenze bist (Einstellung) oder deutlich mehr als sonst.
 */
object Ausgaben {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun all(ctx: Context): JSONArray = try { JSONArray(prefs(ctx).getString("ausgaben", "[]")) } catch (_: Exception) { JSONArray() }
    private val PAY = Regex("(?i)zahlung|bezahlt|gesendet|kaufbeleg|quittung|rechnung|bestellbestätigung|bestellung|ihr einkauf|order|receipt|payment|abbuchung")
    private val NOPE = Regex("(?i)rückerstattung|erstattung|gutschrift|refund|erhalten von|hat ihnen .* gesendet|geld erhalten|newsletter|angebot|rabatt|gutschein")
    private val AMT = Regex("(\\d{1,4}(?:\\.\\d{3})*,\\d{2})\\s?(?:€|eur)|(?:€|eur)\\s?(\\d{1,4}(?:\\.\\d{3})*,\\d{2})|(\\d{1,4}\\.\\d{2})\\s?(?:€|eur)", RegexOption.IGNORE_CASE)
    private val TOTAL = Regex("(?i)(gesamt\\w*|summe|betrag|zu zahlen|total|insgesamt|zahlung über|sie haben)[^0-9€]{0,40}")

    private fun num(s: String) = s.replace(".", "").replace(",", ".").toDoubleOrNull()
        ?: s.toDoubleOrNull()

    private fun shop(from: String, subj: String): String {
        val t = "$from $subj".lowercase()
        return listOf("paypal" to "PayPal", "amazon" to "Amazon", "rewe" to "Rewe", "ebay" to "eBay", "steam" to "Steam", "zalando" to "Zalando",
            "lieferando" to "Lieferando", "apple" to "Apple", "google" to "Google", "deutsche bahn" to "Bahn", "vvs" to "VVS", "otto" to "Otto")
            .firstOrNull { t.contains(it.first) }?.second ?: from.take(30)
    }

    /** Aus einer Mail (Absender, Betreff, Textanfang). Gibt den Betrag zurück, wenn es eine Ausgabe war. */
    fun fromMail(ctx: Context, from: String, subj: String, body: String): Double? {
        val all = "$subj $body"
        if (!PAY.containsMatchIn(all) || NOPE.containsMatchIn(subj)) return null
        // Betrag: am liebsten der hinter „Gesamt/Summe/Betrag“, sonst der erste im Betreff, sonst der größte im Text
        val near = TOTAL.findAll(all).mapNotNull { m -> AMT.find(all, m.range.last)?.takeIf { it.range.first - m.range.last < 60 } }.firstOrNull()
        val m = near ?: AMT.find(subj) ?: AMT.findAll(body).maxByOrNull { x -> num(x.groupValues.drop(1).first { it.isNotBlank() }) ?: 0.0 }
        val v = m?.groupValues?.drop(1)?.firstOrNull { it.isNotBlank() }?.let { num(it) } ?: return null
        if (v <= 0 || v > 5000) return null
        val a = all(ctx); val now = System.currentTimeMillis(); val who = shop(from, subj)
        for (i in 0 until a.length()) a.optJSONObject(i)?.let {   // gleiche Ausgabe doppelt (z. B. PayPal + Händler)?
            if (Math.abs(it.optDouble("eur") - v) < 0.01 && now - it.optLong("t") < 3 * 86_400_000L) return null
        }
        a.put(JSONObject().put("t", now).put("eur", v).put("bei", who).put("was", subj.take(80)))
        while (a.length() > 400) a.remove(0)
        prefs(ctx).edit().putString("ausgaben", a.toString()).apply()
        warn(ctx)
        return v
    }

    private fun monthStart(back: Int = 0) = Calendar.getInstance().apply { add(Calendar.MONTH, -back); set(Calendar.DAY_OF_MONTH, 1); set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0) }.timeInMillis
    private fun sum(ctx: Context, from: Long, to: Long) = (0 until all(ctx).length()).mapNotNull { all(ctx).optJSONObject(it) }.filter { it.optLong("t") in from until to }

    fun limit(ctx: Context) = prefs(ctx).getInt("ausgaben_limit", 0)
    fun setLimit(ctx: Context, v: Int) = prefs(ctx).edit().putInt("ausgaben_limit", v.coerceIn(0, 100000)).apply()

    private fun warn(ctx: Context) {
        val now = System.currentTimeMillis()
        val month = sum(ctx, monthStart(), now).sumOf { it.optDouble("eur") }
        val key = SimpleDateFormat("yyyy-MM", Locale.GERMANY).format(Date())
        val p = prefs(ctx)
        val lim = limit(ctx)
        val prev = (1..3).map { b -> sum(ctx, monthStart(b), monthStart(b - 1)).sumOf { it.optDouble("eur") } }.filter { it > 0 }
        val avg = if (prev.isEmpty()) 0.0 else prev.average()
        val txt = when {
            lim > 0 && month > lim && p.getString("ausgaben_warn_lim", "") != key -> { p.edit().putString("ausgaben_warn_lim", key).apply()
                "Du hast diesen Monat schon ${"%.0f".format(month)} € ausgegeben – mehr als deine Grenze von $lim €. Vielleicht ein bisschen aufpassen." }
            avg > 20 && month > avg * 1.3 && p.getString("ausgaben_warn_avg", "") != key -> { p.edit().putString("ausgaben_warn_avg", key).apply()
                "Du hast diesen Monat schon ${"%.0f".format(month)} € ausgegeben – sonst sind es um die ${"%.0f".format(avg)} € im ganzen Monat." }
            else -> null
        } ?: return
        try { Melden.deliver(ctx, "Ausgaben", txt) } catch (_: Exception) {}
    }

    /** „Wie viel hab ich diesen Monat ausgegeben?“ */
    fun summary(ctx: Context): String {
        if (!Mail.configured(ctx)) return "Deine Ausgaben lese ich aus den Bestätigungsmails – dafür muss dein Gmail verbunden sein (Einstellungen → Allgemein)."
        val now = System.currentTimeMillis()
        val l = sum(ctx, monthStart(), now)
        if (l.isEmpty()) return "Diesen Monat habe ich noch keine Ausgaben in deinen Mails gefunden. Ich zähle erst ab dem Tag, an dem Gmail verbunden wurde."
        val total = l.sumOf { it.optDouble("eur") }
        val by = l.groupBy { it.optString("bei") }.mapValues { e -> e.value.sumOf { it.optDouble("eur") } }.entries.sortedByDescending { it.value }.take(4)
        val lim = limit(ctx)
        return "Diesen Monat ${"%.2f".format(Locale.GERMANY, total)} € laut deinen Mails: " + by.joinToString(", ") { "${it.key} ${"%.2f".format(Locale.GERMANY, it.value)} €" } + "." +
            (if (lim > 0) " Deine Grenze sind $lim €${if (total > lim) " – die ist überschritten." else ", noch ${"%.0f".format(lim - total)} € Luft."}" else "")
    }
}
