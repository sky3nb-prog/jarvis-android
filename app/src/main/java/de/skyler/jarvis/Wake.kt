package de.skyler.jarvis

import android.content.Context

/**
 * Aktivierungswort(e) mit Toleranz: "Jarvis", "Javis", "Dschawis" … zählen je nach Einstellung auch.
 * Mehrere Wörter möglich (Einstellungen: mit Komma trennen).
 */
object Wake {
    fun words(ctx: Context): List<String> {
        val raw = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getString("wake_words", "jarvis") ?: "jarvis"
        return raw.split(",", ";").map { it.trim().lowercase() }.filter { it.length >= 2 }.ifEmpty { listOf("jarvis") }
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

    private fun dist(a: String, b: String): Int {
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
        for (w in words) {
            val target = norm(w).replace(" ", "")
            val tol = when (level) { 0 -> if (target.length >= 6) 1 else 0; 2 -> maxOf(2, target.length / 2); else -> if (target.length >= 5) 2 else 1 }
            for (i in toks.indices) {
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

    /** Befehl aus dem Originaltext (mit Großbuchstaben/Umlauten) nach dem Aktivierungswort. */
    fun commandAfter(original: String, words: List<String>, level: Int): String? {
        val rest = find(original, words, level) ?: return null
        if (rest.isEmpty()) return ""
        val origToks = original.split(Regex("\\s+")).filter { it.isNotBlank() }
        val n = rest.split(" ").size
        return origToks.takeLast(n).joinToString(" ").trim(' ', ',', '.', '!', '?')
    }
}
