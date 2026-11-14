package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.Calendar

/**
 * Wie ist Skyler heute drauf? Eine vorsichtige Einschätzung aus verschiedenen Daten:
 *  Schlaf letzte Nacht, Bewegung (Schritte/Sport), Termine heute (Klassenarbeit, Arzt … = Stress; Geburtstag, Treffen = schön),
 *  ob er draußen war, und was er selbst über seine Laune gesagt hat (das zählt am meisten).
 * Daraus: Wert -2 … +2, kurzes Etikett und Gründe. Jarvis nutzt das, um sich anzupassen (ruhiger, kein Sarkasmus, keine
 * zusätzlichen Vorschläge, behutsam nachfragen – oder locker und mit Humor).
 * Lernt dazu: Sagt Skyler später selbst, wie er drauf ist, vergleicht Jarvis das mit seiner Einschätzung und verschiebt sie.
 */
object Stimmung {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    @Volatile private var cache: JSONObject? = null
    @Volatile private var cacheT = 0L

    private val STRESS = Regex("(?i)klassenarbeit|klausur|\\btest\\b|prüfung|arzt|zahnarzt|elternsprechtag|referat|präsentation|abgabe|vorstellungsgespräch|nachhilfe")
    private val NICE = Regex("(?i)geburtstag|party|feier|kino|treffen|ausflug|urlaub|ferien|frei\\b|zocken|lan")
    private val BAD = Regex("(?i)gestresst|stress|müde|kaputt|traurig|schlecht|genervt|nervt|wütend|sauer|krank|kopfweh|langweilig|einsam|scheiß|mies|keine lust")
    private val GOOD = Regex("(?i)gut drauf|super|mega|geil|happy|glücklich|freu|entspannt|läuft|cool|gut gelaunt|top")

    /** Wertung eines Satzes, den er selbst über sich gesagt hat: -1, 0, +1 */
    fun valence(t: String): Int = when { BAD.containsMatchIn(t) && !Regex("(?i)nicht (so )?(müde|gestresst|schlecht)").containsMatchIn(t) -> -1; GOOD.containsMatchIn(t) -> 1; else -> 0 }

    fun read(ctx: Context): JSONObject {
        val now = System.currentTimeMillis()
        cache?.let { if (now - cacheT < 10 * 60_000L) return it }
        var score = 0.0
        val why = mutableListOf<String>()
        val d0 = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0) }.timeInMillis
        try { Sleep.night(ctx, 0)?.optLong("min")?.takeIf { it > 0 }?.let { m ->
            when { m < 330 -> { score -= 1.0; why.add("nur ${"%.1f".format(java.util.Locale.GERMANY, m / 60.0)} h geschlafen") }
                   m < 400 -> { score -= .5; why.add("eher wenig Schlaf (${m / 60} h ${m % 60} min)") }
                   m >= 480 -> { score += .4; why.add("gut geschlafen") } }
        } } catch (_: Exception) {}
        try { if (Health.connected(ctx)) Health.day(ctx, 0)?.let { f ->
            val h = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
            val st = f.optLong("schritte", -1)
            if (st >= 0 && h >= 16) { if (st < 2000) { score -= .3; why.add("kaum bewegt ($st Schritte)") } else if (st > 8000) { score += .3; why.add("viel bewegt") } }
            if (f.optLong("sport_min") >= 20) { score += .3; why.add("Sport gemacht") }
        } } catch (_: Exception) {}
        try {
            val ev = Cal.events(ctx, d0, d0 + 86_400_000L)
            ev.firstOrNull { STRESS.containsMatchIn(it.title) }?.let { score -= .5; why.add("heute „${it.title}“") }
            ev.firstOrNull { NICE.containsMatchIn(it.title) }?.let { score += .4; why.add("heute „${it.title}“") }
        } catch (_: Exception) {}
        // Was er heute selbst gesagt hat (zählt am meisten)
        try {
            val l = JSONArray(prefs(ctx).getString("local_moods", "[]"))
            Memory.snap(ctx).optJSONArray("moods")?.let { pm -> for (i in 0 until pm.length()) pm.optJSONObject(i)?.let { l.put(it) } }   // auch was er am PC gesagt hat
            for (i in 0 until l.length()) { val o = l.optJSONObject(i) ?: continue
                if (o.optLong("ts") * 1000 >= d0) { val v = valence(o.optString("text")); if (v != 0) { score += v * 1.2; why.add("er sagte: „${o.optString("text")}“") } } }
        } catch (_: Exception) {}
        // gelernt: wie weit lag die Einschätzung bisher daneben?
        val bias = prefs(ctx).getFloat("stimmung_bias", 0f).toDouble()
        score = (score + bias).coerceIn(-2.0, 2.0)
        val label = when { score <= -1.2 -> "eher schlecht drauf"; score <= -.5 -> if (why.any { it.contains("Schlaf") || it.contains("geschlafen") }) "eher müde" else "eher gestresst"
            score >= 1.0 -> "gut drauf"; score >= .4 -> "ganz gut drauf"; else -> "normal" }
        val o = JSONObject().put("score", Math.round(score * 10) / 10.0).put("label", label).put("why", JSONArray(why))
        cache = o; cacheT = now
        prefs(ctx).edit().putString("stimmung_last", o.toString()).apply()
        return o
    }

    /** Für Prompts: Einschätzung + wie er sich anpassen soll. */
    fun prompt(ctx: Context): String = try {
        val o = read(ctx); val s = o.optDouble("score")
        val g = (0 until (o.optJSONArray("why")?.length() ?: 0)).joinToString(", ") { o.getJSONArray("why").optString(it) }
        "Einschätzung, wie er heute drauf ist (vorsichtig, aus Daten): ${o.optString("label")}${if (g.isNotBlank()) " – $g" else ""}. " + when {
            s <= -.5 -> "Passe dich an: ruhig, warm, kurz, KEIN Sarkasmus und keine Witze auf seine Kosten, keine zusätzlichen Vorschläge oder To-dos. Frag höchstens einmal behutsam nach, wie es ihm geht – nicht in jeder Antwort."
            s >= .4 -> "Er ist eher gut drauf: locker, Humor ist okay, freu dich mit."
            else -> "Normaler Ton."
        } + " Sag nie, dass du das aus Daten schließt, außer er fragt."
    } catch (_: Exception) { "" }

    /** Er hat selbst gesagt, wie er drauf ist -> Einschätzung nachjustieren (lernen). */
    fun feedback(ctx: Context, text: String) {
        val v = valence(text); if (v == 0) return
        val last = try { JSONObject(prefs(ctx).getString("stimmung_last", "{}") ?: "{}") } catch (_: Exception) { return }
        if (!last.has("score")) return
        val est = last.optDouble("score") - prefs(ctx).getFloat("stimmung_bias", 0f)   // ohne alten Ausgleich
        val err = v * 1.0 - est.coerceIn(-1.0, 1.0)
        val bias = (prefs(ctx).getFloat("stimmung_bias", 0f) * .8f + (err * .2).toFloat()).coerceIn(-1f, 1f)
        prefs(ctx).edit().putFloat("stimmung_bias", bias).apply()
        cache = null
    }
}
