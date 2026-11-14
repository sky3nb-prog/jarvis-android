package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.Calendar

/** Was Jarvis über dich weiß: Stand vom PC plus das, was du dem Handy erzählt hast. */
object Memory {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    fun snap(ctx: Context): JSONObject = try { JSONObject(prefs(ctx).getString("brain_snap", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
    private fun local(ctx: Context, key: String) = try { JSONArray(prefs(ctx).getString(key, "[]")) } catch (_: Exception) { JSONArray() }

    private fun key(t: String) = t.trim().lowercase().trimEnd('.', '!')

    fun facts(ctx: Context): List<String> {
        val out = LinkedHashMap<String, String>()
        snap(ctx).optJSONArray("facts")?.let { for (i in 0 until it.length()) it.optString(i).let { t -> out[key(t)] = t } }
        val l = local(ctx, "local_facts")
        for (i in 0 until l.length()) l.optJSONObject(i)?.optString("text")?.let { out[key(it)] = it }
        return out.values.toList()
    }

    /** Kernerinnerung (dauerhaft über dich) – nur die fliegen in die Kugel. */
    fun isCore(t: String) = !Regex("(?i)\\b(heute|morgen|gerade|jetzt|diese woche|nächste woche|übermorgen|gleich)\\b").containsMatchIn(t)

    /** Aus der Karte in der Kugel: genau diese Erinnerung ändern. */
    fun edit(ctx: Context, old: String, new: String): String {
        if (old.isNotBlank()) forget(ctx, old)
        return if (new.isNotBlank()) remember(ctx, new, quiet = true) else "Vergessen."
    }

    fun remember(ctx: Context, text: String, date: String? = null, quiet: Boolean = false): String {
        val t = text.trim().replaceFirstChar { it.uppercase() }
        if (t.length < 3) return "Was soll ich mir merken?"
        if (facts(ctx).any { key(it) == key(t) }) return "Das wusste ich schon."
        val l = local(ctx, "local_facts")
        val o = JSONObject().put("text", t)
        if (!date.isNullOrBlank() && Regex("\\d{2}-\\d{2}").matches(date)) o.put("date", date)
        l.put(o)
        while (l.length() > 300) l.remove(0)
        prefs(ctx).edit().putString("local_facts", l.toString()).apply()
        Link.push(ctx, facts = JSONArray().put(o))
        if (!quiet && isCore(t)) try { Bus.emit("skill", JSONObject().put("title", "Gelernt").put("text", t)) } catch (_: Exception) {}   // ploppt in der Kugel auf
        return "Gemerkt."
    }

    fun forget(ctx: Context, what: String): String {
        val w = what.trim().lowercase()
        if (w.length < 3) return "Was soll ich vergessen?"
        val l = local(ctx, "local_facts"); val keep = JSONArray()
        for (i in 0 until l.length()) l.optJSONObject(i)?.let { if (!it.optString("text").lowercase().contains(w)) keep.put(it) }
        prefs(ctx).edit().putString("local_facts", keep.toString()).apply()
        // auch im PC-Stand sofort ausblenden; der PC löscht es dann richtig
        val s = snap(ctx); val f = s.optJSONArray("facts") ?: JSONArray(); val nf = JSONArray()
        for (i in 0 until f.length()) if (!f.optString(i).lowercase().contains(w)) nf.put(f.optString(i))
        s.put("facts", nf); prefs(ctx).edit().putString("brain_snap", s.toString()).apply()
        Link.push(ctx, forget = JSONArray().put(what.trim()))
        return "Vergessen."
    }

    fun mood(ctx: Context, text: String) {
        if (text.isBlank()) return
        val o = JSONObject().put("text", text.trim()).put("ts", System.currentTimeMillis() / 1000)
        val l = local(ctx, "local_moods"); l.put(o)
        while (l.length() > 10) l.remove(0)
        prefs(ctx).edit().putString("local_moods", l.toString()).apply()
        Link.push(ctx, moods = JSONArray().put(o))
    }

    /** Nach einem neuen PC-Stand: was der PC jetzt schon kennt, muss nicht mehr extra gemerkt werden. */
    fun prune(ctx: Context, snap: JSONObject) {
        val known = HashSet<String>()
        snap.optJSONArray("facts")?.let { for (i in 0 until it.length()) known.add(key(it.optString(i))) }
        val l = local(ctx, "local_facts"); val keep = JSONArray()
        for (i in 0 until l.length()) l.optJSONObject(i)?.let { if (key(it.optString("text")) !in known) keep.put(it) }
        val sinceTs = snap.optLong("ts")
        val m = local(ctx, "local_moods"); val keepM = JSONArray()
        for (i in 0 until m.length()) m.optJSONObject(i)?.let { if (it.optLong("ts") > sinceTs) keepM.put(it) }
        prefs(ctx).edit().putString("local_facts", keep.toString()).putString("local_moods", keepM.toString()).apply()
    }

    private fun moodsText(ctx: Context): String {
        val all = mutableListOf<JSONObject>()
        snap(ctx).optJSONArray("moods")?.let { for (i in 0 until it.length()) it.optJSONObject(i)?.let(all::add) }
        local(ctx, "local_moods").let { for (i in 0 until it.length()) it.optJSONObject(i)?.let(all::add) }
        val now = System.currentTimeMillis() / 1000
        return all.sortedBy { it.optLong("ts") }.takeLast(6).joinToString("; ") {
            val d = ((now - it.optLong("ts")) / 86400).toInt()
            (if (d <= 0) "heute" else if (d == 1) "gestern" else "vor $d Tagen") + ": " + it.optString("text")
        }
    }

    fun upcoming(ctx: Context): String {
        val today = Calendar.getInstance()
        val out = mutableListOf<Pair<Int, String>>()
        snap(ctx).optJSONArray("dates")?.let { arr ->
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val d = o.optString("date"); if (d.length != 5) continue
                val c = Calendar.getInstance().apply {
                    set(Calendar.MONTH, d.substring(0, 2).toInt() - 1); set(Calendar.DAY_OF_MONTH, d.substring(3).toInt())
                    set(Calendar.HOUR_OF_DAY, 23); set(Calendar.MINUTE, 59)
                }
                if (c.before(today)) c.add(Calendar.YEAR, 1)
                val n = ((c.timeInMillis - today.timeInMillis) / 86400000L).toInt()
                if (n <= 14) out.add(n to o.optString("text") + " (" + (if (n == 0) "heute" else if (n == 1) "morgen" else "in $n Tagen") + ")")
            }
        }
        return out.sortedBy { it.first }.joinToString("; ") { it.second }
    }

    /** Persönlichkeit vom PC (oder Standard). */
    fun persona(ctx: Context): String = snap(ctx).optString("persona_text").ifBlank {
        "Persönlichkeit: Im Grundton bist du ernst, souverän und zurückhaltend wie ein erstklassiger Butler. Dein Humor ist " +
            "trocken und sarkastisch, aber dosiert: höchstens ein kurzer, feiner Seitenhieb, längst nicht in jeder Antwort. " +
            "Nie albern, nie gemein. Bei ernsten Themen gar kein Sarkasmus, dann ehrlich und warm."
    }

    fun block(ctx: Context): String {
        val s = snap(ctx)
        val sb = StringBuilder()
        val addr = s.optString("address")
        if (addr.isNotBlank()) sb.append("Sprich den Nutzer mit \"$addr\" an, aber nicht in jedem Satz.\n")
        val prof = s.optJSONObject("profile")
        if (prof != null && prof.length() > 0) {
            sb.append("Daten des Nutzers: ")
            sb.append(prof.keys().asSequence().joinToString(", ") { "$it: ${prof.optString(it)}" }).append(".\n")
        }
        s.optString("home").takeIf { it.isNotBlank() }?.let { sb.append("Adresse des Nutzers (Zuhause): $it.\n") }
        val f = facts(ctx).takeLast(250)
        if (f.isNotEmpty()) sb.append("Das hat der Nutzer dir früher erzählt (\"ich/mein\" meint den Nutzer):\n")
            .append(f.joinToString("\n") { "- $it" }).append('\n')
        moodsText(ctx).takeIf { it.isNotBlank() }?.let { sb.append("So war der Nutzer zuletzt drauf: $it.\n") }
        upcoming(ctx).takeIf { it.isNotBlank() }?.let { sb.append("Demnächst (gemerkte Daten): $it.\n") }
        return sb.toString()
    }
}
