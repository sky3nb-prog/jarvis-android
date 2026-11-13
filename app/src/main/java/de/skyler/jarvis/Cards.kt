package de.skyler.jarvis

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

/**
 * Inhalte für die Karten im Jarvis-Fenster: Musik (Deezer), YouTube-Neuheiten und Websuche.
 * Jede Funktion legt die Karte in [pending] ab und gibt einen kurzen Text für die KI zurück.
 */
object Cards {
    @Volatile var pending: JSONObject? = null
    private val http = OkHttpClient.Builder().callTimeout(20, TimeUnit.SECONDS).build()
    private val slow = OkHttpClient.Builder().callTimeout(50, TimeUnit.SECONDS).build()   // Recherche dauert länger

    private fun get(url: String): String = http.newCall(Request.Builder().url(url)
        .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) Jarvis").build()).execute().use { it.body?.string() ?: "" }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    // --- Musik über Deezer ------------------------------------------------------------------------------
    private fun deezerTrack(title: String, artist: String): JSONObject? = try {
        val q = if (artist.isNotBlank()) "artist:\"$artist\" track:\"$title\"" else title
        JSONObject(get("https://api.deezer.com/search?limit=1&q=" + enc(q))).optJSONArray("data")?.optJSONObject(0)
            ?: JSONObject(get("https://api.deezer.com/search?limit=1&q=" + enc("$artist $title"))).optJSONArray("data")?.optJSONObject(0)
    } catch (_: Exception) { null }

    private fun deezerArtistId(name: String): Long? = try {
        JSONObject(get("https://api.deezer.com/search/artist?limit=1&q=" + enc(name))).optJSONArray("data")
            ?.optJSONObject(0)?.optLong("id")?.takeIf { it > 0 }
    } catch (_: Exception) { null }

    private fun trackItem(t: JSONObject, count: Int = 0, why: String = ""): JSONObject = JSONObject()
        .put("title", t.optString("title_short").ifBlank { t.optString("title") })
        .put("artist", t.optJSONObject("artist")?.optString("name") ?: "")
        .put("cover", t.optJSONObject("album")?.optString("cover_medium") ?: "")
        .put("url", "https://www.deezer.com/track/" + t.optLong("id"))
        .put("count", count).put("why", why)

    /** "Was höre ich so?" / "Was passt dazu?": deine Top-Songs, deine Genres und neue Vorschläge (alles aus Deezer). */
    fun music(ctx: Context, suggest: Boolean = true): String {
        val tops = Interests.topTracks(ctx, 4)
        val artists = Interests.top(ctx, "music", 5).map { it.first }
        if (tops.isEmpty() && artists.isEmpty())
            return if (Interests.hasAccess(ctx)) "MUSIK: Ich lerne gerade noch, was du hörst. Hör ein paar Songs auf Deezer, dann kann ich dir etwas vorschlagen."
            else "MUSIK: Ich weiß noch nicht, was du hörst. Erlaube in der Jarvis-App unter Einstellungen den Zugriff auf das, was du schaust und hörst."
        val top = JSONArray()
        for ((title, artist, n) in tops) deezerTrack(title, artist)?.let { top.put(trackItem(it, n)) }
            ?: top.put(JSONObject().put("title", title).put("artist", artist).put("count", n).put("cover", "")
                .put("url", "https://www.deezer.com/search/" + enc("$artist $title")))
        val sug = JSONArray()
        if (suggest) {
            val known = (artists + tops.map { it.second }).map { it.lowercase() }.toSet()
            val seen = HashSet<String>()
            for (a in artists.take(3)) {
                val id = deezerArtistId(a) ?: continue
                val rel = try { JSONObject(get("https://api.deezer.com/artist/$id/related?limit=8")).optJSONArray("data") } catch (_: Exception) { null }
                    ?: continue
                var added = 0
                for (i in 0 until rel.length()) {
                    val r = rel.optJSONObject(i) ?: continue
                    val name = r.optString("name")
                    if (name.lowercase() in known || !seen.add(name.lowercase())) continue
                    val t = try { JSONObject(get("https://api.deezer.com/artist/${r.optLong("id")}/top?limit=1")).optJSONArray("data")?.optJSONObject(0) }
                        catch (_: Exception) { null } ?: continue
                    sug.put(trackItem(t, 0, "ähnlich wie $a"))
                    if (++added >= 2 || sug.length() >= 5) break
                }
                if (sug.length() >= 5) break
            }
        }
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val genres = try { JSONArray(p.getString("music_genres_json", "[]")) } catch (_: Exception) { JSONArray() }
        val card = JSONObject().put("kind", "music").put("top", top).put("suggest", sug).put("genres", genres)
        if (sug.length() > 0) card.put("play", JSONObject().put("label", "Vorschläge in Deezer abspielen")
            .put("url", sug.getJSONObject(0).optString("url")))
        pending = card
        fun names(a: JSONArray) = (0 until a.length()).joinToString("; ") { a.getJSONObject(it).let { o -> "${o.optString("title")} von ${o.optString("artist")}" } }
        return "MUSIK: Lieblingssongs gerade: ${names(top)}. Musikrichtung: ${p.getString("music_genres", "")}. " +
            (if (sug.length() > 0) "Passende neue Vorschläge (auf Deezer): ${names(sug)}." else "")
    }

    // --- YouTube ----------------------------------------------------------------------------------------
    fun youtube(ctx: Context, key: String, days: Int): String {
        val vids = Interests.newVideosData(ctx, days)
        val chans = Interests.top(ctx, "video", 6).map { it.first }
        if (chans.isEmpty()) return Interests.newVideos(ctx, days)
        val arr = JSONArray()
        for (v in vids.take(8)) arr.put(v)
        val more = JSONArray()
        try {   // ähnliche Kanäle, die zu dem passen, was du schaust
            val msgs = JSONArray()
                .put(JSONObject().put("role", "system").put("content",
                    "Nenne 3 echte, bekannte YouTube-Kanäle (deutsch oder international), die jemandem gefallen, der diese Kanäle " +
                        "viel schaut. Nicht die genannten selbst. Antworte nur mit den 3 Namen, durch Komma getrennt."))
                .put(JSONObject().put("role", "user").put("content", chans.joinToString(", ")))
            Groq.chat(key, msgs, 60).split(",").map { it.trim().trim('.', '"') }.filter { it.length in 2..40 }.take(3).forEach {
                more.put(JSONObject().put("name", it).put("url", "https://www.youtube.com/results?search_query=" + enc(it)))
            }
        } catch (_: Exception) {}
        pending = JSONObject().put("kind", "youtube").put("videos", arr).put("more", more)
        return if (arr.length() == 0) "YOUTUBE: Von deinen Lieblingskanälen (${chans.joinToString()}) gibt es seit $days Tagen nichts Neues." +
            (if (more.length() > 0) " Vorschläge für neue Kanäle stehen im Fenster." else "")
        else "YOUTUBE (neu von den Kanälen, die du gerade viel schaust): " +
            (0 until minOf(6, arr.length())).joinToString("; ") { arr.getJSONObject(it).let { o -> "${o.optString("channel")}: „${o.optString("title")}“ (${o.optString("ago")})" } }
    }

    // --- Websuche (Groq mit eingebauter Suche) -----------------------------------------------------------
    /** "Was ist besser, A oder B?": Websuche (Groq compound) + klare Empfehlung; ausführlich im Fenster. */
    fun compare(ctx: android.content.Context, key: String, items: List<String>, frage: String): String {
        val things = items.filter { it.isNotBlank() }.joinToString(" oder ").ifBlank { frage }
        val about = try { Memory.facts(ctx).takeLast(25).joinToString("; ") } catch (_: Exception) { "" }
        val msgs = JSONArray()
            .put(JSONObject().put("role", "system").put("content",
                "Du bist Jarvis und hilfst bei einem Vergleich oder einer Kaufentscheidung. Suche im Internet nach aktuellen Tests, Daten und Preisen. " +
                "Antworte auf Deutsch ohne Markdown in 5 bis 8 Sätzen: erst die wichtigsten Unterschiede (Preis, Qualität, Ausstattung, was für ihn zählt), " +
                "dann eine klare Empfehlung mit Begründung (Ich würde … nehmen, weil …). Hängt es von etwas ab (z. B. Budget), sag es kurz. Erfinde keine Zahlen."))
            .put(JSONObject().put("role", "user").put("content", "Vergleich: $things. $frage" + if (about.isNotBlank()) "\nWas ich über den Nutzer weiß: $about" else ""))
        for (model in listOf("groq/compound", "groq/compound-mini", "compound-beta")) {
            try {
                val body = JSONObject().put("model", model).put("messages", msgs).put("max_tokens", 1200)
                val resp = slow.newCall(Request.Builder().url("https://api.groq.com/openai/v1/chat/completions")
                    .header("Authorization", "Bearer $key")
                    .post(body.toString().toRequestBody("application/json".toMediaType())).build()).execute().use {
                    if (!it.isSuccessful) null else it.body?.string()
                } ?: continue
                val text = JSONObject(resp).getJSONArray("choices").getJSONObject(0).getJSONObject("message").optString("content")
                    .replace(Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL), "").replace(Regex("[*#`]"), "")
                    .replace(Regex("\\[(\\d+)\\]"), "").trim()
                if (text.isBlank()) continue
                pending = JSONObject().put("kind", "web").put("text", text.take(1800)).put("sources", JSONArray())
                return text
            } catch (_: Exception) {}
        }
        return "Die Recherche klappt gerade nicht. Versuch es gleich nochmal."
    }

    fun web(key: String, query: String): String {
        if (query.isBlank()) return "WEB: Wonach soll ich suchen?"
        val msgs = JSONArray()
            .put(JSONObject().put("role", "system").put("content",
                "Suche im Internet und antworte auf Deutsch in 3 bis 5 Sätzen, sachlich und aktuell. Keine Aufzählungszeichen, kein Markdown."))
            .put(JSONObject().put("role", "user").put("content", query))
        for (model in listOf("groq/compound-mini", "groq/compound", "compound-beta-mini", "compound-beta")) {
            try {
                val body = JSONObject().put("model", model).put("messages", msgs).put("max_tokens", 700)
                val resp = http.newCall(Request.Builder().url("https://api.groq.com/openai/v1/chat/completions")
                    .header("Authorization", "Bearer $key")
                    .post(body.toString().toRequestBody("application/json".toMediaType())).build()).execute().use {
                    if (!it.isSuccessful) null else it.body?.string()
                } ?: continue
                val msg = JSONObject(resp).getJSONArray("choices").getJSONObject(0).getJSONObject("message")
                val text = msg.optString("content").replace(Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL), "")
                    .replace(Regex("[*#`]"), "").replace(Regex("\\[(\\d+)\\]"), "").trim()
                if (text.isBlank()) continue
                val sources = JSONArray(); val seen = HashSet<String>()
                val tools = msg.optJSONArray("executed_tools")
                if (tools != null) for (i in 0 until tools.length()) {
                    val res = tools.optJSONObject(i)?.optJSONObject("search_results")?.optJSONArray("results") ?: continue
                    for (k in 0 until res.length()) {
                        val r = res.optJSONObject(k) ?: continue
                        val url = r.optString("url"); if (url.isBlank()) continue
                        val host = Regex("https?://(?:www\\.)?([^/]+)").find(url)?.groupValues?.get(1) ?: continue
                        if (seen.add(host) && sources.length() < 5) sources.put(JSONObject().put("name", host).put("url", url))
                    }
                }
                pending = JSONObject().put("kind", "web").put("text", text.take(1200)).put("sources", sources)
                return "WEB (Suchergebnis, steht ausführlich im Fenster): ${text.take(900)}"
            } catch (_: Exception) {}
        }
        return "WEB: Die Websuche geht gerade nicht."
    }
}
