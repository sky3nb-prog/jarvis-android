package de.skyler.jarvis

import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Deine Interessen aus dem, was du wirklich schaust und hörst (nicht aus Abos):
 * - YouTube: welche Kanäle du in letzter Zeit oft schaust -> "Was kann ich auf YouTube schauen?" = neue Videos davon
 * - Musik: welche Künstler du oft hörst -> Jarvis leitet daraus die Genres ab (einmal am Tag über Groq)
 */
object Interests {
    private const val DAYS = 21
    private val VIDEO_APPS = setOf("com.google.android.youtube", "app.revanced.android.youtube", "com.vanced.android.youtube",
        "app.rvx.android.youtube", "com.google.android.apps.youtube.kids", "org.schabi.newpipe")
    private val http = OkHttpClient.Builder().callTimeout(15, TimeUnit.SECONDS).build()
    private var lastKey = ""

    private fun file(ctx: Context) = File(ctx.filesDir, "interessen.json")
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    fun hasAccess(ctx: Context): Boolean {
        val flat = Settings.Secure.getString(ctx.contentResolver, "enabled_notification_listeners") ?: return false
        val me = ComponentName(ctx, MediaWatch::class.java).flattenToString()
        return flat.split(":").any { it.equals(me, true) }
    }

    @Synchronized
    private fun load(ctx: Context): JSONArray = try { JSONArray(file(ctx).readText()) } catch (_: Exception) { JSONArray() }

    @Synchronized
    fun add(ctx: Context, pkg: String, title: String, artist: String, durMs: Long) {
        val key = "$pkg|$title|$artist"
        if (key == lastKey) return
        lastKey = key
        val arr = load(ctx)
        val now = System.currentTimeMillis()
        // dasselbe in den letzten 20 Minuten nicht doppelt zählen
        for (i in arr.length() - 1 downTo maxOf(0, arr.length() - 15)) {
            val o = arr.optJSONObject(i) ?: continue
            if (o.optString("t") == title && o.optString("a") == artist && now - o.optLong("ts") < 20 * 60_000L) return
        }
        val kind = if (pkg in VIDEO_APPS || pkg.contains("youtube") && !pkg.contains("music")) "video" else "music"
        arr.put(JSONObject().put("ts", now).put("p", pkg).put("k", kind).put("t", title.take(140)).put("a", artist.take(80))
            .put("d", durMs / 1000))
        val cut = now - DAYS * 86_400_000L
        val keep = JSONArray()
        for (i in 0 until arr.length()) arr.optJSONObject(i)?.let { if (it.optLong("ts") >= cut) keep.put(it) }
        while (keep.length() > 1500) keep.remove(0)
        try { file(ctx).writeText(keep.toString()) } catch (_: Exception) {}
    }

    /** Hörzeit Musik (Minuten) seit since – für den Wochenrückblick. */
    fun musicMinutes(ctx: Context, since: Long): Int {
        val arr = load(ctx); var sec = 0L
        for (i in 0 until arr.length()) arr.optJSONObject(i)?.let {
            if (it.optLong("ts") >= since && it.optString("k") == "music") sec += it.optLong("d").let { d -> if (d in 30..900) d else 180 }
        }
        return (sec / 60).toInt()
    }

    /** Die häufigsten Namen (Kanäle oder Künstler), neuere zählen mehr. */
    fun top(ctx: Context, kind: String, n: Int): List<Pair<String, Int>> {
        val arr = load(ctx)
        val now = System.currentTimeMillis()
        val score = HashMap<String, Double>()
        val count = HashMap<String, Int>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            if (o.optString("k") != kind) continue
            val name = o.optString("a").trim().removeSuffix(" - Topic").removeSuffix(" – Topic")
            if (name.isBlank()) continue
            val ageDays = (now - o.optLong("ts")) / 86_400_000.0
            score[name] = (score[name] ?: 0.0) + Math.exp(-ageDays / 7.0)   // was du gerade schaust, zählt mehr
            count[name] = (count[name] ?: 0) + 1
        }
        return score.entries.sortedByDescending { it.value }.take(n).map { it.key to (count[it.key] ?: 0) }
    }

    /** Für die KI: was du gerade so schaust und hörst (kurz). */
    fun block(ctx: Context): String {
        if (!file(ctx).exists()) return ""
        val sb = StringBuilder()
        val yt = top(ctx, "video", 8)
        if (yt.isNotEmpty()) sb.append("YouTube-Kanäle, die der Nutzer in letzter Zeit oft schaut (nicht Abos, sondern was er wirklich schaut): ")
            .append(yt.joinToString(", ") { "${it.first} (${it.second}x)" }).append(".\n")
        val mu = top(ctx, "music", 10)
        if (mu.isNotEmpty()) sb.append("Musik, die er gerade viel hört (Künstler): ")
            .append(mu.joinToString(", ") { "${it.first} (${it.second}x)" }).append(".\n")
        prefs(ctx).getString("music_genres", "")?.takeIf { it.isNotBlank() }?.let { sb.append("Seine Musikrichtung gerade: $it\n") }
        return sb.toString()
    }

    /** Einmal am Tag: aus den Künstlern die Genres ableiten (Groq), damit Jarvis "deinen Geschmack" kennt. */
    fun refreshGenres(ctx: Context, key: String) {
        val p = prefs(ctx)
        if (System.currentTimeMillis() - p.getLong("music_genres_ts", 0L) < 20 * 3600_000L) return
        val mu = top(ctx, "music", 15)
        if (mu.size < 3) return
        try {
            val msgs = JSONArray()
                .put(JSONObject().put("role", "system").put("content",
                    "Du bist Musikexperte. Welche Genres und Stimmungen hört diese Person gerade hauptsächlich? Antworte NUR mit " +
                        "JSON: {\"satz\":\"<ein kurzer deutscher Satz, persönlich, z. B. Du hörst gerade viel ... – eher ...>\"," +
                        "\"genres\":[{\"name\":\"<Genre>\",\"pct\":<Anteil in Prozent>}]} mit 2 bis 4 Genres. Keine Künstler nennen."))
                .put(JSONObject().put("role", "user").put("content",
                    "Gehörte Künstler mit Anzahl: " + mu.joinToString(", ") { "${it.first} ${it.second}x" }))
            val raw = Groq.chat(key, msgs, 220, json = true).trim()
            val o = JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw)?.value ?: raw)
            val satz = o.optString("satz").trim()
            if (satz.isNotBlank()) p.edit().putString("music_genres", satz)
                .putString("music_genres_json", (o.optJSONArray("genres") ?: JSONArray()).toString())
                .putLong("music_genres_ts", System.currentTimeMillis()).apply()
        } catch (_: Exception) {}
    }

    /** Deine meistgehörten Songs: (Titel, Künstler, wie oft) – neuere zählen mehr. */
    fun topTracks(ctx: Context, n: Int): List<Triple<String, String, Int>> {
        val arr = load(ctx)
        val now = System.currentTimeMillis()
        val score = HashMap<String, Double>(); val count = HashMap<String, Int>(); val names = HashMap<String, Pair<String, String>>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            if (o.optString("k") != "music") continue
            val t = o.optString("t").trim(); val a = o.optString("a").trim()
            if (t.isBlank()) continue
            val key = (t + "|" + a).lowercase()
            score[key] = (score[key] ?: 0.0) + Math.exp(-(now - o.optLong("ts")) / 86_400_000.0 / 7.0)
            count[key] = (count[key] ?: 0) + 1
            names[key] = t to a
        }
        return score.entries.sortedByDescending { it.value }.take(n).map { Triple(names[it.key]!!.first, names[it.key]!!.second, count[it.key] ?: 0) }
    }

    /** Neue Videos als Daten für die Karte (Titel, Kanal, Vorschaubild, Link für die YouTube-App). */
    fun newVideosData(ctx: Context, days: Int): List<JSONObject> {
        val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
        val cutoff = System.currentTimeMillis() - days * 86_400_000L
        val out = mutableListOf<Pair<Long, JSONObject>>()
        for ((name, _) in top(ctx, "video", 8)) {
            val id = channelId(ctx, name) ?: continue
            try {
                val xml = get("https://www.youtube.com/feeds/videos.xml?channel_id=$id")
                for (m in Regex("<entry>(.*?)</entry>", RegexOption.DOT_MATCHES_ALL).findAll(xml).take(3)) {
                    val e = m.groupValues[1]
                    val vid = Regex("<yt:videoId>(.*?)</yt:videoId>").find(e)?.groupValues?.get(1) ?: continue
                    val title = (Regex("<title>(.*?)</title>").find(e)?.groupValues?.get(1) ?: "")
                        .replace("&amp;", "&").replace("&quot;", "\"").replace("&#39;", "'")
                    val ts = try { iso.parse((Regex("<published>(.*?)</published>").find(e)?.groupValues?.get(1) ?: "").take(19))?.time ?: 0L } catch (_: Exception) { 0L }
                    if (ts < cutoff) continue
                    val ago = ((System.currentTimeMillis() - ts) / 86_400_000L).toInt()
                    out.add(ts to JSONObject().put("title", title).put("channel", name)
                        .put("thumb", "https://i.ytimg.com/vi/$vid/mqdefault.jpg")
                        .put("url", "https://www.youtube.com/watch?v=$vid")
                        .put("ago", if (ago == 0) "heute" else if (ago == 1) "gestern" else "vor $ago Tagen"))
                }
            } catch (_: Exception) {}
        }
        return out.sortedByDescending { it.first }.map { it.second }
    }

    // --- Neue Videos von den Kanälen, die du viel schaust -------------------------------------------------
    private val channelIds = HashMap<String, String>()

    private fun get(url: String): String = http.newCall(Request.Builder().url(url)
        .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36")
        .header("Accept-Language", "de-DE,de;q=0.9").build()).execute().use { it.body?.string() ?: "" }

    private fun channelId(ctx: Context, name: String): String? {
        channelIds[name]?.let { return it }
        prefs(ctx).getString("ytid_$name", null)?.let { channelIds[name] = it; return it }
        return try {
            val html = get("https://www.youtube.com/results?search_query=" + URLEncoder.encode(name, "UTF-8") + "&sp=EgIQAg%253D%253D")
            val id = Regex("\"channelId\":\"(UC[\\w-]{22})\"").find(html)?.groupValues?.get(1)
            if (id != null) { channelIds[name] = id; prefs(ctx).edit().putString("ytid_$name", id).apply() }
            id
        } catch (_: Exception) { null }
    }

    /** Text für die KI: neue Videos (letzte Tage) der meistgeschauten Kanäle. */
    fun newVideos(ctx: Context, days: Int = 7): String {
        val chans = top(ctx, "video", 8)
        if (chans.isEmpty()) return if (hasAccess(ctx))
            "YOUTUBE: Ich habe noch nicht genug gesehen, was du schaust. Schau ein paar Videos, dann lerne ich es."
        else "YOUTUBE: Ich weiß noch nicht, was du schaust. Erlaube in der Jarvis-App unter Einstellungen den Zugriff " +
            "„Was ich schaue und höre“."
        val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
        val cutoff = System.currentTimeMillis() - days * 86_400_000L
        val out = mutableListOf<String>()
        for ((name, _) in chans) {
            val id = channelId(ctx, name) ?: continue
            try {
                val xml = get("https://www.youtube.com/feeds/videos.xml?channel_id=$id")
                for (m in Regex("<entry>.*?<title>(.*?)</title>.*?<published>(.*?)</published>", RegexOption.DOT_MATCHES_ALL)
                    .findAll(xml).take(3)) {
                    val title = m.groupValues[1].replace("&amp;", "&").replace("&quot;", "\"").replace("&#39;", "'")
                    val ts = try { iso.parse(m.groupValues[2].take(19))?.time ?: 0L } catch (_: Exception) { 0L }
                    if (ts >= cutoff) {
                        val ago = ((System.currentTimeMillis() - ts) / 86_400_000L).toInt()
                        out.add("$name: „$title“ (" + (if (ago == 0) "heute" else if (ago == 1) "gestern" else "vor $ago Tagen") + ")")
                    }
                }
            } catch (_: Exception) {}
            if (out.size >= 10) break
        }
        return if (out.isEmpty()) "YOUTUBE: Von deinen Lieblingskanälen (${chans.joinToString { it.first }}) gibt es seit $days Tagen nichts Neues."
        else "YOUTUBE (neue Videos der Kanäle, die du gerade viel schaust): " + out.joinToString("; ")
    }

    fun summaryForSettings(ctx: Context): String {
        if (!hasAccess(ctx)) return "Noch nicht erlaubt."
        val yt = top(ctx, "video", 3).joinToString(", ") { it.first }
        val mu = top(ctx, "music", 3).joinToString(", ") { it.first }
        return when {
            yt.isBlank() && mu.isBlank() -> "Erlaubt – ich lerne, sobald du etwas schaust oder hörst."
            else -> "Gerade oft: " + listOf(yt, mu).filter { it.isNotBlank() }.joinToString(" · ")
        }
    }
}
