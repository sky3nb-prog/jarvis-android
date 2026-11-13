package de.skyler.jarvis

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Die Lage wie am PC: holt Nachrichten (tagesschau, DW, BBC, Google News und lokale Meldungen aus dem Wohnort),
 * lässt Groq daraus ein Briefing und Brennpunkte mit Ort machen und setzt die Punkte über OpenStreetMap genau
 * auf den Ort (Tunnel, Platz, Bahnhof ...). Alles wird 15 Minuten zwischengespeichert.
 */
object Lage {
    const val MAX_AGE = 15 * 60 * 1000L
    private val http = OkHttpClient.Builder().callTimeout(12, TimeUnit.SECONDS).build()
    private val pool = Executors.newFixedThreadPool(6)
    private val lock = Any()
    private val mem = HashMap<String, JSONObject>()

    private val FEEDS = listOf(
        "tagesschau" to "https://www.tagesschau.de/index~rss2.xml",
        "tagesschau Ausland" to "https://www.tagesschau.de/ausland/index~rss2.xml",
        "DW" to "https://rss.dw.com/xml/rss-de-all",
        "BBC World" to "https://feeds.bbci.co.uk/news/world/rss.xml",
        "Google Top" to "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de",
        "Google Welt" to "https://news.google.com/rss/headlines/section/topic/WORLD?hl=de&gl=DE&ceid=DE:de",
    )

    private fun localFeeds(city: String): List<Pair<String, String>> {
        val q = if (city.equals("Leonberg", true)) listOf(
            "Lokal Leonberg" to "Leonberg",
            "Lokal Kreiszeitung" to "site:stuttgarter-zeitung.de Leonberg",
            "Lokal Verkehr" to "Engelbergtunnel OR \"Leonberger Dreieck\" OR \"A8 Leonberg\" OR \"A81 Leonberg\" OR \"Leonberg Sperrung\"",
            "Lokal Blaulicht" to "Leonberg Polizei OR Feuerwehr OR Unfall",
            "Lokal Umland" to "Renningen OR Rutesheim OR Ditzingen OR Gerlingen OR \"Weil der Stadt\" OR Weissach",
        ) else listOf("Lokal $city" to city, "Lokal $city Verkehr" to "$city Verkehr OR Sperrung OR Unfall")
        return q.map { (n, s) -> n to "https://news.google.com/rss/search?q=${enc("$s when:3d")}&hl=de&gl=DE&ceid=DE:de" }
    }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    private fun fetch(url: String): String = http.newCall(Request.Builder().url(url)
        .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) Jarvis").build()).execute().use { if (it.isSuccessful) it.body?.string() ?: "" else "" }

    private fun clean(s: String): String = android.text.Html.fromHtml(
        s.replace(Regex("<!\\[CDATA\\[|]]>"), ""), android.text.Html.FROM_HTML_MODE_LEGACY).toString()
        .replace(Regex("<[^>]+>"), " ").replace(Regex("\\s+"), " ").trim()

    /** RSS / RDF -> Meldungen {titel, text, quelle, link} */
    private fun parse(xml: String, src: String, limit: Int): List<JSONObject> {
        val out = ArrayList<JSONObject>()
        val skip = Regex("^(faq|liveblog|live|ticker|newsblog|podcast|video|kommentar)\\b", RegexOption.IGNORE_CASE)
        for (m in Regex("<item[\\s>].*?</item>", RegexOption.DOT_MATCHES_ALL).findAll(xml)) {
            val it = m.value
            fun tag(t: String) = Regex("<$t[^>]*>(.*?)</$t>", RegexOption.DOT_MATCHES_ALL).find(it)?.groupValues?.get(1) ?: ""
            var title = clean(tag("title"))
            if (title.isBlank() || skip.containsMatchIn(title)) continue
            if (src.startsWith("Google") || src.startsWith("Lokal")) title = title.replace(Regex(" - [^-]{2,40}$"), "")
            out.add(JSONObject().put("titel", title).put("text", clean(tag("description")).take(300))
                .put("quelle", src).put("link", clean(tag("link"))))
            if (out.size >= limit) break
        }
        return out
    }

    private fun headlines(city: String): List<JSONObject> {
        val all = FEEDS + localFeeds(city)
        val futures = all.map { (src, url) -> pool.submit<List<JSONObject>> {
            try { parse(fetch(url), src, if (src.startsWith("Lokal")) 10 else 12) } catch (_: Exception) { emptyList() } } }
        val items = ArrayList<JSONObject>(); val seen = HashSet<String>()
        for (f in futures) {
            val list = try { f.get(15, TimeUnit.SECONDS) } catch (_: Exception) { emptyList() }
            for (it in list) { val k = it.optString("titel").lowercase().take(60); if (seen.add(k)) items.add(it) }
        }
        return items
    }

    private const val GENAU = """   "genau" (wie genau der Ort ist: "punkt" = ein bestimmtes Gebäude, Platz, Tunnel, Brücke, Bahnhof, Kreuzung oder
   Autobahnabschnitt; "strasse"; "stadtteil"; "stadt"; "region"; "land") und "suche" (der genaueste Ort aus der Meldung
   als Suchbegriff für eine Karte, immer mit Stadt, z. B. "Engelbergtunnel, Leonberg", "Hauptbahnhof, Stuttgart";
   bei Ländern nur das Land). Nimm den genauesten Ort, den die Meldung hergibt."""

    private fun prompt(city: String) = """Du bist der Lage-Analyst von J.A.R.V.I.S. Unten stehen nummerierte Schlagzeilen (#Nummer [Quelle] Titel: Text).
Meldungen mit [Lokal ...] stammen aus dem Wohnort des Nutzers ($city) und der Umgebung.
Erstelle:
1. "briefing": eine kurze gesprochene Einleitung auf Deutsch, 1 bis 2 Sätze, wie ein Butler ("Die Lage, Sir: ..."), die sagt, was heute das Wichtigste ist.
2. "brennpunkte": die 6 bis 10 wichtigsten Meldungen aus Welt und Deutschland UND zusätzlich bis zu 8 lokale Meldungen aus $city
   und Umgebung (art "lokal"; Verkehr wie Sperrungen, Tunnel, Baustellen, Stau, dazu Blaulicht, Stadtpolitik, Veranstaltungen).
   Doppelte Meldungen nur einmal. Wähle 4 bis 6 davon für die Tour aus ("im_briefing": true): die wichtigsten aus der Welt
   und Deutschland zuerst, die lokalen aus $city am Ende. Die Tour-Punkte stehen zuerst, in der Reihenfolge der Tour.
   Für jede: "nr" (Nummer der Schlagzeile), "titel" (höchstens 6 Wörter, Deutsch), "ort" (Stadt oder Land; lokal: Ortsteil,
   Straße oder Gebäude), "lat", "lon" (Zahlen, so genau wie möglich), "art" (konflikt, politik, wirtschaft, wetter,
   katastrophe, gesellschaft, sport, wissenschaft, lokal), "wichtig" (1 bis 3), "im_briefing" (true/false),
   "text" (2 bis 3 gesprochene Sätze, was dort los ist, sachlich, ohne Sonderzeichen; beginnt NICHT mit dem Ortsnamen),
$GENAU
Antworte NUR mit JSON: {"briefing": "...", "brennpunkte": [ ... ]}"""

    private fun placePrompt(place: String) = """Du bist der Lage-Analyst von J.A.R.V.I.S. Unten stehen nummerierte Schlagzeilen über $place.
Erstelle:
1. "briefing": eine kurze gesprochene Einleitung auf Deutsch, 1 Satz, beginnt mit "Aus $place:".
2. "brennpunkte": die 4 bis 10 interessantesten Meldungen aus $place und Umgebung. Die 3 bis 5 wichtigsten mit "im_briefing": true zuerst.
   Für jede: "nr", "titel" (höchstens 6 Wörter), "ort" (Stadtteil, Straße oder Gebäude), "lat", "lon", "art" (konflikt, politik,
   wirtschaft, wetter, katastrophe, gesellschaft, sport, wissenschaft, lokal), "wichtig" (1 bis 3), "im_briefing",
   "text" (2 bis 3 gesprochene Sätze, was dort los ist; beginnt NICHT mit dem Ortsnamen),
$GENAU
Antworte NUR mit JSON: {"briefing": "...", "brennpunkte": [ ... ]}"""

    private fun summarize(key: String, items: List<JSONObject>, sys: String): JSONObject {
        val use = items.take(45)
        val lines = use.mapIndexed { i, it -> "#$i [${it.optString("quelle")}] ${it.optString("titel")}: ${it.optString("text").take(130)}" }.joinToString("\n")
        val msgs = JSONArray().put(JSONObject().put("role", "system").put("content", sys)).put(JSONObject().put("role", "user").put("content", lines))
        val raw = Groq.chat(key, msgs, 3500, json = true)
        val obj = JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw.replace(Regex("```(json)?"), ""))?.value ?: raw)
        val pts = JSONArray()
        val arr = obj.optJSONArray("brennpunkte") ?: JSONArray()
        for (i in 0 until arr.length()) {
            val p = arr.optJSONObject(i) ?: continue
            val lat = p.optDouble("lat", Double.NaN); val lon = p.optDouble("lon", Double.NaN)
            if (lat.isNaN() || lon.isNaN() || lat !in -90.0..90.0 || lon !in -180.0..180.0) continue
            val src = use.getOrNull(p.optInt("nr", -1))
            pts.put(JSONObject().put("titel", p.optString("titel").take(60)).put("ort", p.optString("ort"))
                .put("lat", lat).put("lon", lon).put("art", p.optString("art", "politik")).put("wichtig", p.optInt("wichtig", 2))
                .put("im_briefing", p.optBoolean("im_briefing")).put("text", p.optString("text").take(400))
                .put("genau", p.optString("genau").lowercase().trim()).put("suche", p.optString("suche").trim())
                .put("link", src?.optString("link") ?: "").put("quelle", src?.optString("quelle") ?: ""))
        }
        return JSONObject().put("briefing", obj.optString("briefing").trim()).put("brennpunkte", pts)
    }

    // --- genaue Orte über Photon / OpenStreetMap ------------------------------------------------------------
    private fun geoFile(ctx: Context) = File(ctx.filesDir, "orte_genau.json")
    private var geoMem: JSONObject? = null

    /** Nur aus dem Speicher (ohne Internet) – für schnelle Antworten an die Oberfläche. */
    fun geocodeCached(ctx: Context, query: String): Pair<Double, Double>? {
        val k = query.lowercase().trim(); if (k.isEmpty()) return null
        synchronized(lock) {
            if (geoMem == null) geoMem = try { JSONObject(geoFile(ctx).readText()) } catch (_: Exception) { JSONObject() }
            return geoMem!!.optJSONArray(k)?.let { it.getDouble(0) to it.getDouble(1) }
        }
    }

    /** Zuhause aus den Einstellungen (Adresse + Wohnort, sonst nur Wohnort) neu bestimmen. */
    @Volatile private var homeBusy = false
    @Volatile private var warmed = ""
    fun updateHome(ctx: Context, onDone: () -> Unit = {}) {
        if (homeBusy) return
        homeBusy = true
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val city = city(ctx); val addr = (p.getString("address", "") ?: "").trim()
        Thread({
            try {
                val hit = (if (addr.isNotBlank()) geocode(ctx, "$addr, $city") else null) ?: geocode(ctx, city)
                if (hit != null) {
                    p.edit().putFloat("home_lat", hit.first.toFloat()).putFloat("home_lon", hit.second.toFloat())
                        .putString("home_for", "$addr|$city").apply()
                    homeBusy = false
                    onDone()   // nur bei Erfolg melden (sonst würde die Oberfläche es endlos neu versuchen)
                }
            } catch (_: Exception) {} finally { homeBusy = false }
        }, "jarvis-home").start()
    }

    /** Lieblingsorte schon mal im Voraus finden (damit ein Tipp sofort hinfliegt). */
    fun warmFavorites(ctx: Context) {
        val list = favorites(ctx); val key = list.joinToString(",")
        if (key == warmed) return
        warmed = key
        Thread({ for (f in list) try { geocode(ctx, f) } catch (_: Exception) {} }, "jarvis-orte").start()
    }

    fun geocode(ctx: Context, query: String, near: Pair<Double, Double>? = null): Pair<Double, Double>? {
        val k = query.lowercase().trim(); if (k.isEmpty()) return null
        synchronized(lock) {
            if (geoMem == null) geoMem = try { JSONObject(geoFile(ctx).readText()) } catch (_: Exception) { JSONObject() }
            geoMem!!.optJSONArray(k)?.let { return it.getDouble(0) to it.getDouble(1) }
            if (geoMem!!.has(k)) return null
        }
        var hit: Pair<Double, Double>? = null; var failed = false
        try {
            val bias = near?.let { "&lat=${it.first}&lon=${it.second}&location_bias_scale=0.5&zoom=12" } ?: ""
            val f = JSONObject(fetch("https://photon.komoot.io/api/?q=${enc(query)}&limit=1&lang=de$bias")).optJSONArray("features")
            f?.optJSONObject(0)?.optJSONObject("geometry")?.optJSONArray("coordinates")?.let { hit = it.getDouble(1) to it.getDouble(0) }
        } catch (_: Exception) { failed = true }
        if (hit == null) try {
            val a = JSONArray(http.newCall(Request.Builder().url("https://nominatim.openstreetmap.org/search?q=${enc(query)}&format=json&limit=1&accept-language=de")
                .header("User-Agent", "Jarvis-Handy/1.0 (privat)").build()).execute().use { it.body?.string() ?: "[]" })
            a.optJSONObject(0)?.let { hit = it.getString("lat").toDouble() to it.getString("lon").toDouble() }
        } catch (_: Exception) { failed = true }
        if (hit != null || !failed) synchronized(lock) {
            geoMem!!.put(k, hit?.let { JSONArray().put(it.first).put(it.second) } ?: JSONObject.NULL)
            try { geoFile(ctx).writeText(geoMem.toString()) } catch (_: Exception) {}
        }
        return hit
    }

    private fun km(a: Double, b: Double, c: Double, d: Double): Double {
        val r = Math.PI / 180; val x = (d - b) * r * Math.cos((a + c) / 2 * r); val y = (c - a) * r
        return Math.sqrt(x * x + y * y) * 6371
    }

    private fun refine(ctx: Context, pts: JSONArray) {
        val todo = (0 until pts.length()).map { pts.getJSONObject(it) }
            .filter { it.optString("suche").isNotBlank() && it.optString("genau") in setOf("punkt", "strasse", "stadtteil") }
        val fs = todo.map { p -> pool.submit {
            val hit = geocode(ctx, p.optString("suche"), p.optDouble("lat") to p.optDouble("lon"))
            if (hit == null || km(hit.first, hit.second, p.optDouble("lat"), p.optDouble("lon")) > 80) p.put("genau", "stadt")
            else { p.put("lat", hit.first).put("lon", hit.second).put("genau_ok", true) }
        } }
        for (f in fs) try { f.get(10, TimeUnit.SECONDS) } catch (_: Exception) {}
    }

    private fun cacheFile(ctx: Context, key: String) = File(ctx.cacheDir, "lage_" + key.replace(Regex("[^a-z0-9]"), "_") + ".json")

    fun city(ctx: Context): String = (ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getString("city", "") ?: "")
        .ifBlank { Memory.snap(ctx).optString("city") }.ifBlank { "Leonberg" }

    /** Lage (ort leer = Welt + Wohnort). Liefert {briefing, brennpunkte, zeit, ort, lat, lon}. */
    fun get(ctx: Context, key: String, ort: String = "", maxAge: Long = MAX_AGE): JSONObject {
        val city = city(ctx)
        var place = ort.trim().trim('.', '?', '!')
        if (place.lowercase() in setOf("hier", "hier in der nähe", "in der nähe", "um mich herum")) place = Here.name(ctx).ifBlank { city }
        val k = if (place.isBlank() || place.equals(city, true)) "welt" else place.lowercase()
        synchronized(lock) {
            val m = mem[k] ?: try { JSONObject(cacheFile(ctx, k).readText()).also { mem[k] = it } } catch (_: Exception) { null }
            if (m != null && System.currentTimeMillis() - m.optLong("zeit") < maxAge) return m
        }
        val data: JSONObject
        if (k == "welt") {
            val items = headlines(city)
            if (items.isEmpty()) throw RuntimeException("Ich komme gerade an keine Nachrichten.")
            data = summarize(key, items, prompt(city))
            data.put("ort", city)
            geocode(ctx, city)?.let { data.put("lat", it.first).put("lon", it.second) }
        } else {
            val q = if (place.contains(" ")) "\"$place\"" else place
            val urls = listOf("Lokal $place" to "https://news.google.com/rss/search?q=${enc("$q when:3d")}&hl=de&gl=DE&ceid=DE:de",
                "Lokal $place (en)" to "https://news.google.com/rss/search?q=${enc("$q when:2d")}&hl=en-US&gl=US&ceid=US:en")
            val items = ArrayList<JSONObject>(); val seen = HashSet<String>()
            for ((src, u) in urls) try { for (it in parse(fetch(u), src, 15)) if (seen.add(it.optString("titel").lowercase().take(60))) items.add(it) } catch (_: Exception) {}
            if (items.isEmpty()) throw RuntimeException("Zu $place habe ich gerade keine Meldungen gefunden.")
            data = summarize(key, items, placePrompt(place))
            data.put("ort", place)
            geocode(ctx, place)?.let { data.put("lat", it.first).put("lon", it.second) }
        }
        refine(ctx, data.getJSONArray("brennpunkte"))
        data.put("zeit", System.currentTimeMillis()).put("stadt", city)
        synchronized(lock) { mem[k] = data; try { cacheFile(ctx, k).writeText(data.toString()) } catch (_: Exception) {} }
        return data
    }

    /** Nur aus dem Speicher (für den schnellen Start der Seite). */
    fun cached(ctx: Context, ort: String = ""): JSONObject? {
        val city = city(ctx)
        val k = if (ort.isBlank() || ort.equals(city, true)) "welt" else ort.lowercase()
        synchronized(lock) { return mem[k] ?: try { JSONObject(cacheFile(ctx, k).readText()) } catch (_: Exception) { null } }
    }

    /** Lieblingsorte (Einstellungen), z. B. "Stuttgart, Seoul" */
    fun favorites(ctx: Context): List<String> = (ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        .getString("lage_orte", "Stuttgart") ?: "").split(",").map { it.trim() }.filter { it.isNotEmpty() }
}
