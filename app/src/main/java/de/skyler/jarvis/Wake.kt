package de.skyler.jarvis

import android.content.Context

/**
 * Aktivierungswort(e) mit Toleranz: "Jarvis", "Javis", "Dschawis" … zählen je nach Einstellung auch.
 * Mehrere Wörter möglich (Einstellungen: mit Komma trennen).
 */
object Wake {
    const val DEFAULT = "jarvis, friday"

    fun words(ctx: Context): List<String> {
        var raw = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getString("wake_words", DEFAULT) ?: DEFAULT
        if (raw.trim().lowercase() == "jarvis") raw = DEFAULT   // Jarvis heißt auch Friday
        return raw.split(",", ";").map { it.trim().lowercase() }.filter { it.length >= 2 }.ifEmpty { listOf("jarvis") }
    }

    /** So schreibt die Spracherkennung die Wörter manchmal (deutsch gehört). */
    private val ALIASES = mapOf(
        "friday" to listOf("freitag", "fraidei", "fraidi", "freidi", "frei dei", "fry day"),
        "jarvis" to listOf("jarwis", "javis", "dschawis", "jervis", "charvis", "harvis", "service"),
    )

    private fun variants(w: String): List<String> = listOf(w) + (ALIASES[w] ?: emptyList())

    /**
     * Großzügige Vorprüfung für die Offline-Erkennung (Vosk kennt "Jarvis" nicht und hört z. B. "ja wis"):
     * lieber einmal zu oft bei Groq nachfragen als das Wort verpassen. Groq prüft danach genau.
     */
    fun roughly(text: String, words: List<String>): Boolean {
        val toks = norm(text).split(" ").filter { it.isNotEmpty() }
        if (toks.isEmpty()) return false
        for (w in words) for (v in variants(w)) {
            val target = norm(v).replace(" ", "")
            val tol = maxOf(2, target.length / 2)
            for (i in toks.indices) for (span in 1..3) {
                if (i + span > toks.size) continue
                val cand = toks.subList(i, i + span).joinToString("")
                if (kotlin.math.abs(cand.length - target.length) > tol + 1) continue
                if (dist(cand, target) <= tol) return true
            }
        }
        return false
    }

    /** 0 = streng, 1 = normal, 2 = locker */
    fun level(ctx: Context): Int = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getInt("wake_level", 1)

    /** Lautschrift-ähnlich vereinfachen, damit ähnlich klingende Schreibweisen gleich werden. */
    fun norm(s: String): String = s.lowercase()
        .replace("ä", "e").replace("ö", "o").replace("ü", "u").replace("ß", "s")
        .replace("dsch", "j").replace("tsch", "j").replace("sch", "j").replace("ch", "j")
        .replace("v", "w").replace("ph", "f").replace("y", "i").replace("ie", "i")
        .replace(Regex("(.)\\1+"), "$1")      // doppelte Buchstaben
        .replace(Regex("[^a-z0-9 ]"), " ")
        .replace(Regex("\\s+"), " ").trim()

    fun dist(a: String, b: String): Int {
        val d = IntArray(b.length + 1) { it }
        for (i in 1..a.length) {
            var prev = d[0]; d[0] = i
            for (j in 1..b.length) {
                val tmp = d[j]
                d[j] = minOf(d[j] + 1, d[j - 1] + 1, prev + if (a[i - 1] == b[j - 1]) 0 else 1)
                prev = tmp
            }
        }
        return d[b.length]
    }

    /**
     * Wo im Text steckt das Aktivierungswort? Gibt den Rest danach zurück (der Befehl) oder null.
     * Prüft einzelne Wörter und je zwei hintereinander ("jar wis").
     */
    fun find(text: String, words: List<String>, level: Int): String? {
        val toks = norm(text).split(" ").filter { it.isNotEmpty() }
        if (toks.isEmpty()) return null
        // Das Aktivierungswort steht vorne ("Jarvis, mach ..." / "Hey Jarvis ..."), nicht irgendwo mitten im Gespräch
        val reach = when (level) { 0 -> 2; 2 -> 6; else -> 3 }
        for (w in words.flatMap { variants(it) }) {
            val target = norm(w).replace(" ", "")
            val tol = when (level) {
                0 -> 0
                2 -> maxOf(2, target.length / 3)
                else -> if (target.length >= 8) 2 else if (target.length >= 4) 1 else 0
            }
            for (i in toks.indices) {
                if (i >= reach) break
                for (span in 1..2) {
                    if (i + span > toks.size) continue
                    val cand = toks.subList(i, i + span).joinToString("")
                    if (kotlin.math.abs(cand.length - target.length) > tol + 1) continue
                    if (dist(cand, target) <= tol) {
                        return toks.drop(i + span).joinToString(" ")
                    }
                }
            }
        }
        return null
    }

    /** Hinweis für Whisper: so schreibt man das Aktivierungswort und typische Befehle. */
    fun prompt(ctx: Context): String {
        val w = words(ctx).joinToString(", ") { it.replaceFirstChar { c -> c.uppercase() } }
        return "$w. $w, öffne WhatsApp. $w, ruf Mama an. $w, trag morgen um 15 Uhr Zahnarzt ein. " +
            "$w, stell einen Timer auf 10 Minuten. $w, mach die Musik leiser. $w, wie wird das Wetter?"
    }

    /** Befehl aus dem Originaltext (mit Großbuchstaben/Umlauten) nach dem Aktivierungswort. */
    fun commandAfter(original: String, words: List<String>, level: Int): String? {
        val rest = find(original, words, level) ?: return null
        if (rest.isEmpty()) return ""
        val origToks = original.split(Regex("\\s+")).filter { it.isNotBlank() }
        val n = rest.split(" ").size
        return origToks.takeLast(n).joinToString(" ").trim(' ', ',', '.', '!', '?')
    }
}
