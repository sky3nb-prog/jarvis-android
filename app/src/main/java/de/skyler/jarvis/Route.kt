package de.skyler.jarvis

import android.content.Context
import android.content.Intent
import android.net.Uri
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Wegeplaner – ganz entspannt gesagt:
 *  "Ich will mit dem Rad los, noch ein belegtes Brötchen beim Trölsch holen und dann auf dem schnellsten Weg
 *   über den oberen Feldweg zu meinen Großeltern nach Rutesheim."
 *  "Noch an einem Supermarkt vorbei, am liebsten Rewe, sonst Aldi – was am besten auf dem Weg liegt."
 *  "Wann muss ich los, wenn ich noch zum Rewe will und dann die Bahn nehme?"
 *
 * 1. Die KI zerlegt den Satz (Start, Ziel, Verkehrsmittel, Zwischenstopps, Wege, Uhrzeit) und kennt aus dem
 *    Gedächtnis Orte wie "Großeltern" oder "oberer Feldweg".
 * 2. Ketten wie Rewe/Aldi/Trölsch sucht er auf OpenStreetMap entlang der Strecke und nimmt den mit dem
 *    kleinsten Umweg (der bevorzugte bekommt einen Vorsprung).
 * 3. Ergebnis: Google-Maps-Route mit allen Zwischenstopps; bei der Bahn echte Verbindungen und "los um …".
 */
object Route {
    private val http = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS).build()
    private val de = Locale.GERMANY
    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    data class P(val lat: Double, val lon: Double, val name: String)
    class Result(val say: String, val url: String?, val sendTo: String? = null, val message: String = "")

    private fun km(a: P, b: P): Double {
        val r = 6371.0; val dLa = Math.toRadians(b.lat - a.lat); val dLo = Math.toRadians(b.lon - a.lon)
        val h = sin(dLa / 2) * sin(dLa / 2) + cos(Math.toRadians(a.lat)) * cos(Math.toRadians(b.lat)) * sin(dLo / 2) * sin(dLo / 2)
        return 2 * r * asin(sqrt(h))
    }

    private val SPEED = mapOf("bicycling" to 16.0, "walking" to 4.8, "driving" to 38.0, "transit" to 4.8)
    private fun minutes(km: Double, mode: String) = km * 1.3 / (SPEED[mode] ?: 16.0) * 60.0   // 1,3 = Wege sind nicht schnurgerade

    /** "Opa: Musterstraße 5, Rutesheim" je Zeile (Einstellungen → Wege, gleich wie am PC) */
    fun lines(ctx: Context, key: String): Map<String, String> =
        (ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getString(key, "") ?: "").lines().mapNotNull { l ->
            // "Name: Adresse", "Name = …" oder ohne Doppelpunkt "Oberer Feldweg 48,79, 8,97" (Name bis zur ersten Zahl)
            var i = l.indexOfFirst { it == ':' || it == '=' }
            var j = i + 1
            if (i <= 0) { i = Regex("\\s-?\\d").find(l)?.range?.first ?: -1; j = i }
            if (i <= 0) null else l.substring(0, i).trim().lowercase() to l.substring(j).trim()
        }.filter { it.first.isNotBlank() && it.second.isNotBlank() }.toMap()

    private fun mine(ctx: Context, q: String): String? {
        val k = q.lowercase().trim().removePrefix("zu ").removePrefix("meinem ").removePrefix("meiner ").removePrefix("meinen ").removePrefix("mein ").removePrefix("meine ").trim()
        for (m in listOf(lines(ctx, "orte"), lines(ctx, "wege"))) {
            m[k]?.let { return it }
            m.entries.firstOrNull { (n, _) -> k.contains(n) || n.contains(k) && k.length >= 3 }?.let { return it.value }
        }
        return null
    }

    // --- für "Rechtzeitig losfahren", Ankunft und Wochenrückblick ------------------------------------------
    fun distKm(a: P, b: P) = km(a, b)

    fun home(ctx: Context): P? {
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val q = listOf(p.getString("address", "") ?: "", Lage.city(ctx)).filter { it.isNotBlank() }.joinToString(", ")
        return Lage.geocode(ctx, q)?.let { P(it.first, it.second, "zuhause") }
    }

    /** Gespeicherter Ort ("Opa") oder Adresse -> Koordinaten. */
    fun place(ctx: Context, q: String): P? {
        val s = q.trim(); if (s.isBlank()) return null
        val v = mine(ctx, s) ?: s
        Regex("^(-?\\d{1,3})[.,](\\d+)\\s*[,;\\s]\\s*(-?\\d{1,3})[.,](\\d+)$").find(v)?.let {
            val g = it.groupValues
            return P("${g[1]}.${g[2]}".toDouble(), "${g[3]}.${g[4]}".toDouble(), s)
        }
        val near = home(ctx)?.let { it.lat to it.lon }
        return Lage.geocode(ctx, v, near)?.let { P(it.first, it.second, s) }
    }

    /** Namen aller gespeicherten Orte (für den Kleiderschrank: drinnen/draußen pro Ort). */
    fun placeNames(ctx: Context): List<String> = lines(ctx, "orte").keys.toList()

    /** Ist der Text ein gespeicherter Ort? Gibt dessen Namen zurück. */
    fun savedName(ctx: Context, text: String): String? {
        val t = text.lowercase()
        return lines(ctx, "orte").keys.firstOrNull { it.length >= 3 && Regex("\\b" + Regex.escape(it) + "\\b").containsMatchIn(t) }
    }

    /** Bahn-Verbindung, um spätestens arriveBy anzukommen (dep = Abmarsch inkl. Fußweg). */
    fun bahnBy(a: P, b: P, arriveBy: Long): Trip? {
        val trips = efa(a, b, arriveBy, true).ifEmpty { dbRest(a, b, arriveBy, true) }
        return trips.lastOrNull { it.arr <= arriveBy } ?: trips.firstOrNull()
    }

    /** Erste Bahn-Verbindung ab Zeit t (dep = Abmarsch inkl. Fußweg). */
    fun bahnFrom(a: P, b: P, t: Long): Trip? {
        val trips = efa(a, b, t, false).ifEmpty { dbRest(a, b, t, false) }
        return trips.firstOrNull { it.dep >= t - 3 * 60_000L } ?: trips.firstOrNull()
    }

    fun mapsLink(a: P?, b: P, mode: String): String =
        if (a == null) "https://www.google.com/maps/dir/?api=1&destination=${b.lat},${b.lon}&travelmode=$mode"
        else mapsUrl(a, emptyList(), b, mode)

    fun bikeMinutes(a: P, b: P) = minutes(km(a, b), "bicycling")
    fun walkMinutes(a: P, b: P) = minutes(km(a, b), "walking")

    private fun prompt(ctx: Context, fromPc: Boolean): String {
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val city = Lage.city(ctx)
        val addr = (p.getString("address", "") ?: "").trim()
        val here = if (fromPc) "" else Here.name(ctx)
        val now = SimpleDateFormat("EEEE, dd.MM.yyyy, HH:mm", de).format(Date())
        return """Du planst Wege für den Nutzer (wohnt in $city${if (addr.isNotBlank()) ", Adresse: $addr" else ""}). Es ist $now.
${if (fromPc) "Er fragt am PC zuhause: \"hier\" heißt zuhause." else "Er fragt am Handy: \"hier\" heißt sein aktueller Standort${if (here.isNotBlank()) " ($here)" else ""}."}
Seine gespeicherten Orte (nimm bei "ziel"/"ort" genau diesen Namen, z. B. "Opa"): ${lines(ctx, "orte").keys.joinToString(", ").ifBlank { "keine" }}
Seine gespeicherten Wege (als Stopp mit "art":"weg" und "ort" = genau dieser Name, an der Stelle, wo er ihn nennt): ${lines(ctx, "wege").keys.joinToString(", ").ifBlank { "keine" }}
Was du sonst über ihn weißt (Orte von Familie und Freunden, seine Lieblingswege usw.):
${Memory.facts(ctx).takeLast(60).joinToString("\n") { "- $it" }}
Zerlege seinen Wunsch in JSON:
{"start":"hier" | "zuhause" | "<Adresse oder Ort>",
 "ziel":"<so genau wie möglich: Adresse mit Ort, z. B. aus dem Gedächtnis; sonst Ort>",
 "ziel_name":"<kurz, wie er es nennt, z. B. Großeltern>",
 "mode":"bicycling" | "walking" | "driving" | "transit",
 "stopps":[ in seiner Reihenfolge, jeder entweder
    {"art":"kette","ketten":["REWE","Aldi"],"was":"Supermarkt","minuten":10}   (Läden/Ketten/Bäckereien: bevorzugte zuerst; minuten = Aufenthalt)
    oder {"art":"ort","ort":"<Adresse oder bekannter Ort>","was":"<kurz>","minuten":5}
    oder {"art":"weg","ort":"<Punkt, über den der Weg führen soll, z. B. aus dem Gedächtnis für 'oberer Feldweg'>","was":"<Name des Wegs>"} ],
 "ankunft":"HH:mm" oder null,   (wenn er irgendwo um eine Uhrzeit sein muss)
 "abfahrt":"HH:mm" oder null,
 "frage":"route" | "wann_los" | "dauer",
 "hinweis":"<ganz kurz, nur wenn etwas fehlt, z. B. 'Adresse der Großeltern kenne ich noch nicht' oder 'welcher Feldweg?', sonst leer>"}
Bäckerei "Trölsch" heißt in OpenStreetMap "Trölsch". Ketten immer so, wie sie im Ladenschild stehen (REWE, ALDI, Lidl, EDEKA, Penny, Netto, dm, Trölsch, Bäcker Treiber …).
Bahn/S-Bahn/Bus/Zug = transit. Ohne Angabe: mit dem Rad wenn er "fahren" und "Rad" sagt, sonst driving.
Antworte NUR mit dem JSON."""
    }

    /** Plant den Weg. fromPc = Frage kam vom PC (dann öffnet der PC die Karte, nicht das Handy). */
    fun plan(ctx: Context, key: String, text: String, fromPc: Boolean = false): Result {
        val raw = Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", prompt(ctx, fromPc)))
            .put(JSONObject().put("role", "user").put("content", text)), 600, json = true)
        val j = JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw)?.value ?: raw)
        val mode = j.optString("mode", "bicycling").let { if (it in SPEED) it else "bicycling" }
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val homeQ = listOf(p.getString("address", "") ?: "", Lage.city(ctx)).filter { it.isNotBlank() }.joinToString(", ")
        val home = Lage.geocode(ctx, homeQ)?.let { P(it.first, it.second, "zuhause") }
        val near = home?.let { it.lat to it.lon }

        fun resolve0(s: String, label: String): P? {
            // Koordinaten mit Punkt oder Komma: "48.79, 8.97", "48,7969, 8,9759", "48,7969 8,9759"
            Regex("^(-?\\d{1,3})[.,](\\d+)\\s*[,;\\s]\\s*(-?\\d{1,3})[.,](\\d+)$").find(s.trim())?.let {
                val g = it.groupValues
                return P("${g[1]}.${g[2]}".toDouble(), "${g[3]}.${g[4]}".toDouble(), label)
            }
            return Lage.geocode(ctx, s, near)?.let { P(it.first, it.second, label.ifBlank { s }) }
        }

        fun resolve(q: String, label: String): P? {
            val s = q.trim()
            if (s.isBlank() || s.equals("zuhause", true)) return home
            if (s.equals("hier", true)) return if (!fromPc) Here.latLon(ctx)?.let { P(it.first, it.second, "hier") } ?: home else home
            mine(ctx, s)?.let { v -> return resolve0(v, label.ifBlank { s }) }
            return resolve0(s, label)
        }

        val start = resolve(j.optString("start", "hier"), "Start") ?: return Result("Ich weiß nicht, wo du losfährst. Schalte am Handy den Standort ein oder trag deine Adresse ein.", null)
        val zielName = j.optString("ziel_name").ifBlank { j.optString("ziel") }
        // Personen ("Oma und Opa", "mein Bruder") nur aus den gespeicherten Orten oder mit echter Adresse – nicht raten
        val PERSON = Regex("\\b(oma|opa|großeltern|grosseltern|mama|papa|mutter|vater|eltern|bruder|schwester|tante|onkel|cousin\\w*|freund\\w*|kumpel|freundin)\\b", RegexOption.IGNORE_CASE)
        val zq = j.optString("ziel")
        if ((PERSON.containsMatchIn(zq) || PERSON.containsMatchIn(zielName)) && mine(ctx, zq) == null && mine(ctx, zielName) == null && !zq.any { it.isDigit() })
            return Result("Wo wohnen ${zielName.ifBlank { zq }}? Trag die Adresse einmal in den Einstellungen unter Wege bei Meine Orte ein, " +
                "zum Beispiel: Oma und Opa: Straße und Hausnummer, Ort. Dann finde ich sie immer.", null)
        val ziel = resolve(zq, zielName) ?: return Result("Das Ziel $zq finde ich nicht.", null)

        // Stopps: feste Orte zuerst, Ketten danach entlang der Strecke zwischen ihren Nachbarn
        val st = j.optJSONArray("stopps") ?: JSONArray()
        val pts = arrayOfNulls<P>(st.length())
        val dwell = IntArray(st.length())
        val notes = mutableListOf<String>()
        for (i in 0 until st.length()) {
            val s = st.optJSONObject(i) ?: continue
            dwell[i] = if (s.optString("art") == "weg") 0 else s.optInt("minuten", 5).coerceIn(0, 60)
            if (s.optString("art") == "weg") {
                // Wege nur aus den Einstellungen – sonst sucht die Karte irgendeinen Feldweg in Deutschland
                val name = s.optString("ort").ifBlank { s.optString("was") }
                val v = mine(ctx, name) ?: mine(ctx, s.optString("was"))
                pts[i] = v?.let { resolve0(it, s.optString("was").ifBlank { name }) }
                if (pts[i] == null) notes.add("„$name“ kenne ich noch nicht, trag ihn unter Einstellungen, Wege ein; ich nehme so lange den normalen Weg")
            } else if (s.optString("art") != "kette") pts[i] = resolve(s.optString("ort"), s.optString("was").ifBlank { s.optString("ort") })
                .also { if (it == null) notes.add("${s.optString("was").ifBlank { s.optString("ort") }} habe ich nicht gefunden") }
        }
        for (i in 0 until st.length()) {
            val s = st.optJSONObject(i) ?: continue
            if (s.optString("art") != "kette") continue
            val a = (i - 1 downTo 0).firstNotNullOfOrNull { pts[it] } ?: start
            val b = (i + 1 until st.length()).firstNotNullOfOrNull { pts[it] } ?: ziel
            val ketten = s.optJSONArray("ketten")?.let { k -> (0 until k.length()).map { k.optString(it) }.filter { it.isNotBlank() } } ?: emptyList()
            pts[i] = bestOnTheWay(a, b, ketten, s.optString("was"))
            if (pts[i] == null) notes.add("${ketten.joinToString(" oder ")} liegt nicht auf dem Weg")
        }
        val stops = (0 until st.length()).mapNotNull { i -> pts[i]?.let { it to dwell[i] } }

        // Bahn: Zwischenstopps zu Fuß, ab dem letzten Stopp mit Bus und Bahn
        if (mode == "transit") return transit(start, stops, ziel, j, notes, fromPc, ctx)

        val chain = listOf(start) + stops.map { it.first } + ziel
        var dist = 0.0; for (k in 1 until chain.size) dist += km(chain[k - 1], chain[k])
        val wait = stops.sumOf { it.second }
        val total = minutes(dist, mode) + wait
        val url = mapsUrl(start, stops.map { it.first }, ziel, mode)
        val how = mapOf("bicycling" to "Mit dem Rad", "walking" to "Zu Fuß", "driving" to "Mit dem Auto")[mode] ?: "Mit dem Rad"
        val over = stops.joinToString(", ") { it.first.name }
        val sb = StringBuilder("$how ${if (over.isNotBlank()) "über $over " else ""}nach $zielName: etwa ${"%.0f".format(dist * 1.3)} Kilometer, rund ${fmtMin(total)}${if (wait > 0) " mit Stopps" else ""}.")
        val ankunft = hm(j.optString("ankunft"))
        if (ankunft != null) sb.append(" Damit du um ${j.optString("ankunft")} da bist, fahr spätestens um ${clock(ankunft - (total * 60_000).toLong() - 5 * 60_000)} los.")
        else if (j.optString("frage") == "wann_los") sb.append(" Wenn du jetzt losfährst, bist du gegen ${clock(System.currentTimeMillis() + (total * 60_000).toLong())} da.")
        if (notes.isNotEmpty()) sb.append(" Hinweis: ${notes.joinToString("; ")}.")
        j.optString("hinweis").takeIf { it.isNotBlank() && it != "null" }?.let { sb.append(" $it.") }
        return finish(ctx, sb, url, "Route nach $zielName", fromPc)
    }

    /** Laden einer Kette mit dem kleinsten Umweg zwischen a und b (OpenStreetMap / Overpass). */
    private fun bestOnTheWay(a: P, b: P, ketten: List<String>, was: String): P? {
        if (ketten.isEmpty()) return null
        val d = km(a, b)
        for (grow in listOf(1.0, 2.5)) {
            val pad = max(1.2, d * 0.25) * grow / 111.0
            val s = min(a.lat, b.lat) - pad; val n = max(a.lat, b.lat) + pad
            val w = min(a.lon, b.lon) - pad * 1.5; val e = max(a.lon, b.lon) + pad * 1.5
            val rx = ketten.joinToString("|") { Regex.escape(it).replace("\\Q", "").replace("\\E", "") }
            val q = "[out:json][timeout:20];(nwr[\"brand\"~\"$rx\",i]($s,$w,$n,$e);nwr[\"name\"~\"$rx\",i][\"shop\"]($s,$w,$n,$e);" +
                "nwr[\"name\"~\"$rx\",i][\"amenity\"]($s,$w,$n,$e););out center 80;"
            val els = try {
                JSONObject(http.newCall(Request.Builder().url("https://overpass-api.de/api/interpreter")
                    .post(FormBody.Builder().add("data", q).build()).header("User-Agent", "Jarvis-Handy/1.0 (privat)").build())
                    .execute().use { it.body?.string() ?: "{}" }).optJSONArray("elements") ?: JSONArray()
            } catch (_: Exception) { JSONArray() }
            var best: P? = null; var bestScore = 1e9
            for (i in 0 until els.length()) {
                val o = els.optJSONObject(i) ?: continue
                val la = if (o.has("lat")) o.optDouble("lat") else o.optJSONObject("center")?.optDouble("lat") ?: continue
                val lo = if (o.has("lon")) o.optDouble("lon") else o.optJSONObject("center")?.optDouble("lon") ?: continue
                val t = o.optJSONObject("tags") ?: JSONObject()
                val label = (t.optString("brand").ifBlank { t.optString("name") }).ifBlank { was }
                val rank = ketten.indexOfFirst { k -> label.contains(k, true) || t.optString("name").contains(k, true) }.let { if (it < 0) ketten.size else it }
                val c = P(la, lo, label + (t.optString("addr:street").takeIf { it.isNotBlank() }?.let { " ($it)" } ?: ""))
                val score = km(a, c) + km(c, b) - d + rank * 0.5   // bevorzugte Kette: 500 m Vorsprung
                if (score < bestScore) { bestScore = score; best = c }
            }
            if (best != null) return best
        }
        return null
    }

    private fun mapsUrl(a: P, via: List<P>, b: P, mode: String): String {
        fun c(p: P) = "${p.lat},${p.lon}"
        val sb = StringBuilder("https://www.google.com/maps/dir/?api=1&origin=${c(a)}&destination=${c(b)}&travelmode=$mode")
        if (via.isNotEmpty() && mode != "transit") sb.append("&waypoints=" + enc(via.joinToString("|") { c(it) }))
        return sb.toString()
    }

    /** Bahn: erst zu Fuß zu den Stopps, dann echte Verbindung (DB/VVS über v6.db.transport.rest). */
    private fun transit(start: P, stops: List<Pair<P, Int>>, ziel: P, j: JSONObject, notes: MutableList<String>, fromPc: Boolean, ctx: Context): Result {
        val chain = listOf(start) + stops.map { it.first }
        var pre = 0.0; for (k in 1 until chain.size) pre += minutes(km(chain[k - 1], chain[k]), "walking")
        pre += stops.sumOf { it.second }
        val from = chain.last()
        val now = System.currentTimeMillis()
        val ankunft = hm(j.optString("ankunft"))
        val abfahrt = hm(j.optString("abfahrt"))
        val whenT = ankunft ?: max(abfahrt ?: 0L, now + (pre * 60_000).toLong())
        val maps = mapsUrl(from, emptyList(), ziel, "transit")
        val zielName = j.optString("ziel_name").ifBlank { ziel.name }
        val trips = efa(from, ziel, whenT, ankunft != null).ifEmpty { dbRest(from, ziel, whenT, ankunft != null) }
        val jo = if (ankunft != null) trips.lastOrNull { it.arr <= ankunft } ?: trips.firstOrNull() else trips.firstOrNull()
        val sb = StringBuilder()
        if (jo == null) {
            sb.append("Die Fahrpläne erreiche ich gerade nicht. Zu Fuß ${if (stops.isNotEmpty()) "über ${stops.joinToString(", ") { it.first.name }} " else ""}brauchst du etwa ${fmtMin(pre)} bis zur Abfahrt; die Bahnverbindung nach $zielName zeigt dir Google Maps.")
        } else {
            val leave = jo.dep - (pre * 60_000).toLong()
            sb.append("Geh um ${clock(leave)} los")
            if (stops.isNotEmpty()) sb.append(", erst ${stops.joinToString(" und ") { it.first.name }}")
            sb.append(". Dann ${jo.line} um ${clock(jo.rideDep)} ab ${jo.stop}, an in $zielName um ${clock(jo.arr)}.")
            if (leave < now - 60_000) sb.append(" Das wird knapp – eigentlich müsstest du schon los sein.")
        }
        if (notes.isNotEmpty()) sb.append(" Hinweis: ${notes.joinToString("; ")}.")
        j.optString("hinweis").takeIf { it.isNotBlank() && it != "null" }?.let { sb.append(" $it.") }
        return finish(ctx, sb, maps, "Verbindung nach $zielName", fromPc)
    }

    class Trip(val dep: Long, val arr: Long, val line: String, val stop: String, val rideDep: Long)

    /** Fahrplan vom VVS (EFA, deckt Stuttgart und Umgebung ab). Zeiten: dep = Abmarsch ab Startpunkt inkl. Fußweg. */
    private fun efa(a: P, b: P, t: Long, arrival: Boolean): List<Trip> = try {
        val d = SimpleDateFormat("yyyyMMdd", de).format(Date(t)); val hm = SimpleDateFormat("HHmm", de).format(Date(t))
        fun c(p: P) = enc("${p.lon}:${p.lat}:WGS84[dd.ddddd]")
        val url = "https://www3.vvs.de/mngvvs/XML_TRIP_REQUEST2?SpEncId=0&coordOutputFormat=EPSG:4326&outputFormat=rapidJSON&language=de" +
            "&locationServerActive=1&macroWebTrip=true&useRealtime=1&type_origin=coord&name_origin=${c(a)}&type_destination=coord" +
            "&name_destination=${c(b)}&itdDate=$d&itdTime=$hm&itdTripDateTimeDepArr=${if (arrival) "arr" else "dep"}"
        val js = JSONObject(http.newCall(Request.Builder().url(url).header("User-Agent", "Jarvis-Handy/1.0 (privat)").build())
            .execute().use { it.body?.string() ?: "{}" }).optJSONArray("journeys") ?: JSONArray()
        (0 until js.length()).mapNotNull { i ->
            val legs = js.optJSONObject(i)?.optJSONArray("legs") ?: return@mapNotNull null
            if (legs.length() == 0) return@mapNotNull null
            fun time(o: JSONObject?, k: String) = parseIso(o?.optString("${k}Estimated")?.takeIf { it.isNotBlank() } ?: o?.optString("${k}Planned"))
            val dep = time(legs.optJSONObject(0)?.optJSONObject("origin"), "departureTime") ?: return@mapNotNull null
            val arr = time(legs.optJSONObject(legs.length() - 1)?.optJSONObject("destination"), "arrivalTime") ?: return@mapNotNull null
            val ride = (0 until legs.length()).mapNotNull { legs.optJSONObject(it) }.firstOrNull { l ->
                val pr = l.optJSONObject("transportation")?.optJSONObject("product")
                val cls = pr?.optInt("class", 100) ?: 100
                cls < 97 && !(pr?.optString("name") ?: "").contains("Fuß", true)
            } ?: return@mapNotNull null
            val tr = ride.optJSONObject("transportation")
            val line = (tr?.optString("disassembledName")?.takeIf { it.isNotBlank() } ?: tr?.optString("number") ?: "").let { n ->
                val prod = tr?.optJSONObject("product")?.optString("name") ?: ""
                if (n.isBlank()) prod.ifBlank { "Bahn" } else if (prod.isNotBlank() && !n.startsWith("S") && !n.startsWith("U")) "$prod $n" else n
            }
            Trip(dep, arr, line, ride.optJSONObject("origin")?.optString("name") ?: "der Haltestelle", time(ride.optJSONObject("origin"), "departureTime") ?: dep)
        }
    } catch (_: Exception) { emptyList() }

    /** Ersatz außerhalb des VVS: Deutsche Bahn über v6.db.transport.rest. */
    private fun dbRest(a: P, b: P, t: Long, arrival: Boolean): List<Trip> = try {
        val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", de).apply { timeZone = TimeZone.getDefault() }
        val url = "https://v6.db.transport.rest/journeys?from.type=location&from.latitude=${a.lat}&from.longitude=${a.lon}&from.address=${enc(a.name)}" +
            "&to.type=location&to.latitude=${b.lat}&to.longitude=${b.lon}&to.address=${enc(b.name)}&results=3&language=de" +
            (if (arrival) "&arrival=" else "&departure=") + enc(iso.format(Date(t)))
        val js = JSONObject(http.newCall(Request.Builder().url(url).header("User-Agent", "Jarvis-Handy/1.0 (privat)").build())
            .execute().use { it.body?.string() ?: "{}" }).optJSONArray("journeys") ?: JSONArray()
        (0 until js.length()).mapNotNull { i ->
            val legs = js.optJSONObject(i)?.optJSONArray("legs") ?: return@mapNotNull null
            val dep = parseIso(legs.optJSONObject(0)?.optString("departure")) ?: return@mapNotNull null
            val arr = parseIso(legs.optJSONObject(legs.length() - 1)?.optString("arrival")) ?: return@mapNotNull null
            val ride = (0 until legs.length()).mapNotNull { legs.optJSONObject(it) }.firstOrNull { !it.optBoolean("walking") } ?: return@mapNotNull null
            Trip(dep, arr, ride.optJSONObject("line")?.optString("name") ?: "Bahn", ride.optJSONObject("origin")?.optString("name") ?: "der Haltestelle",
                parseIso(ride.optString("departure")) ?: dep)
        }
    } catch (_: Exception) { emptyList() }

    /** Google Maps am Handy öffnen (auch wenn am PC gefragt) und den Link per WhatsApp an den eingestellten Kontakt. */
    private fun finish(ctx: Context, sb: StringBuilder, url: String, what: String, fromPc: Boolean): Result {
        val to = (ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getString("route_an", "") ?: "").trim()
        sb.append(if (fromPc) " Die Route ist am PC und auf deinem Handy in Google Maps offen." else " Ich öffne dir die Route in Google Maps.")
        open(ctx, url)
        if (to.isNotBlank()) {
            if (fromPc) sb.append(" Den Link schicke ich $to per WhatsApp.")
            else {
                sb.append(" Für $to ist die WhatsApp mit dem Link fertig, tipp nur auf Senden.")
                android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
                    try { Actions(ctx).run(JSONObject().put("action", "whatsapp").put("to", to).put("text", "$what: $url")) } catch (_: Exception) {}
                }, 2500)
            }
        }
        return Result(sb.toString(), url, to.takeIf { fromPc && it.isNotBlank() }, "$what: $url")
    }

    private fun open(ctx: Context, url: String) {
        try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } catch (_: Exception) {}
    }

    private fun hm(s: String?): Long? {
        val m = Regex("^(\\d{1,2})[:.](\\d{2})$").find((s ?: "").trim()) ?: return null
        val c = java.util.Calendar.getInstance().apply {
            set(java.util.Calendar.HOUR_OF_DAY, m.groupValues[1].toInt()); set(java.util.Calendar.MINUTE, m.groupValues[2].toInt())
            set(java.util.Calendar.SECOND, 0); set(java.util.Calendar.MILLISECOND, 0)
        }
        if (c.timeInMillis < System.currentTimeMillis() - 3600_000L) c.add(java.util.Calendar.DAY_OF_MONTH, 1)
        return c.timeInMillis
    }

    private fun parseIso(s: String?): Long? = try {
        if (s.isNullOrBlank() || s == "null") null else SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", de).parse(s)?.time   // XXX versteht auch "Z"
    } catch (_: Exception) { null }

    private fun clock(t: Long) = SimpleDateFormat("HH:mm", de).format(Date(t)) + " Uhr"
    private fun fmtMin(m: Double): String {
        val n = Math.round(m).toInt().coerceAtLeast(1)
        return if (n < 60) "$n Minuten" else "${n / 60} Stunde${if (n / 60 > 1) "n" else ""}${if (n % 60 > 0) " ${n % 60} Minuten" else ""}"
    }
}
