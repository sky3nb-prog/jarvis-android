package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Kleiderschrank: deine Sachen als Karten mit Temperaturbereich (gefühlte Temperatur in °C).
 * Jarvis wählt danach – nach der KÄLTESTEN Temperatur der ganzen Strecke (auch Rückweg), Fahrtwind eingerechnet.
 * Drinnen-Ziel (z. B. Oma und Opa): drunter nur, was drinnen passt; die warme Jacke kommt drüber und wird dort ausgezogen.
 * Lernt aus "zu kalt / passt / zu warm" nach Ausflügen (verschiebt die Grenzen langsam).
 *
 * Schichten: drunter (T-Shirt …), mitte (Pulli, Hoodie …), jacke, hose, extra (Mütze, Handschuhe, Schal, Regenhose).
 */
object Wardrobe {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    private fun it(id: String, name: String, icon: String, layer: String, min: Int, max: Int, rain: Boolean = false) =
        JSONObject().put("id", id).put("name", name).put("icon", icon).put("layer", layer).put("min", min).put("max", max).put("rain", rain).put("on", true)

    private fun defaults() = JSONArray()
        .put(it("tshirt", "T-Shirt", "👕", "drunter", -30, 40))
        .put(it("langarm", "Langarmshirt", "👕", "drunter", -30, 12).put("on", false))
        .put(it("pulli", "Pulli", "🧶", "mitte", -30, 14))
        .put(it("hoodie", "Hoodie", "🧥", "mitte", 8, 16).put("on", false))
        .put(it("winterjacke", "Winterjacke", "🧥", "jacke", -30, 7))
        .put(it("softshell", "Softshelljacke", "🧥", "jacke", 6, 13))
        .put(it("duenn", "Dünne Jacke", "🧥", "jacke", 12, 18))
        .put(it("regenjacke", "Regenjacke", "☔", "jacke", 10, 30, rain = true))
        .put(it("lang", "Lange Hose", "👖", "hose", -30, 20))
        .put(it("kurz", "Kurze Hose", "🩳", "hose", 20, 40))
        .put(it("muetze", "Mütze", "🧢", "extra", -30, 4))
        .put(it("handschuhe", "Handschuhe", "🧤", "extra", -30, 5))
        .put(it("schal", "Schal", "🧣", "extra", -30, 1))
        .put(it("regenhose", "Regenhose", "👖", "extra", -30, 30, rain = true).put("on", false))

    /** Ganzer Schrank (mit Standards gefüllt). */
    fun get(ctx: Context): JSONObject {
        val o = try { JSONObject(prefs(ctx).getString("schrank", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
        if (!o.has("items")) o.put("items", defaults())
        if (!o.has("dickeJacke")) o.put("dickeJacke", true)        // lieber T-Shirt + dicke Jacke als Pulli drunter
        if (!o.has("wind")) o.put("wind", true)                     // Fahrtwind beim Rad/E-Bike
        if (!o.has("drinnen")) o.put("drinnen", 21)                 // so warm ist es drinnen
        if (!o.has("tag_drinnen")) o.put("tag_drinnen", true)       // tagsüber meist drinnen (Schule)
        if (!o.has("orte")) o.put("orte", JSONObject().put("oma und opa", "drinnen").put("opa", "drinnen"))
        if (!o.has("adj")) o.put("adj", 0.0)                        // gelernt: + = dir ist schnell warm, - = dir ist schnell kalt
        if (!o.has("fragen")) o.put("fragen", true)
        return o
    }

    fun save(ctx: Context, o: JSONObject) { prefs(ctx).edit().putString("schrank", o.toString()).apply() }

    fun isIndoor(ctx: Context, place: String?): Boolean {
        if (place.isNullOrBlank()) return false
        val o = get(ctx).optJSONObject("orte") ?: return false
        val k = place.lowercase().trim()
        return o.keys().asSequence().any { (k.contains(it) || it.contains(k)) && o.optString(it) == "drinnen" }
    }

    private fun items(o: JSONObject) = (0 until o.getJSONArray("items").length()).map { o.getJSONArray("items").getJSONObject(it) }.filter { it.optBoolean("on", true) }

    /**
     * Auswahl. coldest = kälteste gefühlte Temperatur unterwegs, warm = wärmste (für kurze Hose), rain = Regen unterwegs,
     * bike = Rad/E-Bike (Fahrtwind), indoor = längere Zeit drinnen am Ziel.
     * Ergebnis: {jacke, oben, hose, extras[], anziehen[], warum, t}
     */
    fun pick(ctx: Context, coldest: Double, warm: Double = coldest, rain: Boolean = false, bike: Boolean = true, indoor: Boolean = false): JSONObject {
        val o = get(ctx)
        val adj = o.optDouble("adj", 0.0)
        val wind = if (bike && o.optBoolean("wind", true)) 3.0 else 0.0
        val t = coldest - wind + adj                  // so fühlt es sich unterwegs an (gelernt verschoben)
        val tw = warm - wind / 2 + adj
        val all = items(o)
        fun fits(i: JSONObject, x: Double) = x >= i.optInt("min") && x <= i.optInt("max")
        fun layer(l: String) = all.filter { it.optString("layer") == l }
        // Jacke: warmste nötige für die kälteste Temperatur; bei Regen eine regenfeste, sofern es nicht zu kalt dafür ist
        val jackets = layer("jacke").filter { !it.optBoolean("rain") }.sortedBy { it.optInt("min") }
        val rainJ = layer("jacke").firstOrNull { it.optBoolean("rain") }
        var jacke: JSONObject? = jackets.firstOrNull { fits(it, t) }
        val drunter = layer("drunter").filter { fits(it, if (indoor) o.optDouble("drinnen", 21.0) else t) }.maxByOrNull { -it.optInt("max") }
            ?: layer("drunter").firstOrNull()
        var mitte: JSONObject? = null
        val mid = layer("mitte").filter { fits(it, t) }.minByOrNull { it.optInt("max") }
        if (indoor) {
            // drinnen soll man nicht schwitzen: drunter nur T-Shirt (bzw. was für drinnen passt), dafür die Jacke eine Stufe wärmer
            if (mid != null && jacke != null) jacke = jackets.firstOrNull { it.optInt("min") <= t - 4 && fits(it, t) } ?: jackets.firstOrNull { it.optInt("max") >= t && it.optInt("min") <= t - 4 } ?: jacke
            if (t < 0 && mid != null && o.optDouble("drinnen", 21.0) < 20) mitte = mid
        } else if (mid != null) {
            // Lieber dicke Jacke als Pulli drunter? Dann eine Stufe wärmere Jacke statt Pulli, solange es eine gibt
            val warmer = jackets.firstOrNull { it.optInt("min") <= t - 4 && it.optInt("max") >= t }
            if (o.optBoolean("dickeJacke", true) && warmer != null && warmer.optString("id") != jacke?.optString("id") && t > 0) jacke = warmer
            else mitte = mid
        }
        if (rain && rainJ != null && (jacke == null || t >= rainJ.optInt("min"))) jacke = rainJ
        val hose = layer("hose").firstOrNull { fits(it, tw) && fits(it, t + 4) } ?: layer("hose").minByOrNull { it.optInt("min") }
        val extras = layer("extra").filter { (it.optBoolean("rain") && rain && bike) || (!it.optBoolean("rain") && fits(it, t)) }
        val oben = listOfNotNull(drunter?.optString("name"), mitte?.optString("name")).joinToString(" und ")
        val anz = JSONArray().apply { listOfNotNull(jacke, drunter, mitte, hose).forEach { put(it.optString("name")) }; extras.forEach { put(it.optString("name")) } }
        val warum = buildString {
            append("Am kältesten ${"%.0f".format(coldest)} °C")
            if (wind > 0) append(", mit Fahrtwind gefühlt ${"%.0f".format(coldest - wind)} °C")
            if (adj != 0.0) append(" (angepasst ${if (adj > 0) "+" else ""}${"%.1f".format(adj)}°)")
            append(" – ")
            append(jacke?.optString("name") ?: "keine Jacke")
            if (indoor) append(", drunter ${oben.ifBlank { "T-Shirt" }}, weil du drinnen sitzt")
            else if (oben.isNotBlank()) append(", drunter $oben")
            if (rain) append(", Regen unterwegs")
            append(".")
        }
        return JSONObject().put("jacke", jacke?.optString("name") ?: "keine").put("oben", oben.ifBlank { "T-Shirt" })
            .put("hose", hose?.optString("name") ?: "lange Hose").put("extras", JSONArray(extras.map { it.optString("name") }))
            .put("anziehen", anz).put("warum", warum).put("t", t).put("ids", JSONArray(listOfNotNull(jacke, drunter, mitte, hose).map { it.optString("id") } + extras.map { it.optString("id") }))
    }

    /** Für die KI: fester Satz, was er anzieht (die KI formuliert nur). */
    fun line(p: JSONObject): String = "ANZIEHEN (fest, nicht ändern): Jacke: ${p.optString("jacke")}; oben: ${p.optString("oben")}; Hose: ${p.optString("hose")}" +
        (if ((p.optJSONArray("extras")?.length() ?: 0) > 0) "; dazu: ${(0 until p.getJSONArray("extras").length()).joinToString(", ") { p.getJSONArray("extras").getString(it) }}" else "") +
        ". Grund: ${p.optString("warum")}"

    /** Ausflug merken (für die Frage "zu kalt / passt / zu warm" danach). */
    fun rememberTrip(ctx: Context, p: JSONObject, where: String) {
        prefs(ctx).edit().putString("schrank_letzt", JSONObject().put("pick", p).put("wo", where).put("ts", System.currentTimeMillis()).toString()).apply()
    }

    fun lastTrip(ctx: Context): JSONObject? = try { JSONObject(prefs(ctx).getString("schrank_letzt", "") ?: "") } catch (_: Exception) { null }

    /** Rückmeldung: -1 zu kalt, 0 passt, +1 zu warm. Verschiebt langsam (0,5° pro Antwort, höchstens ±5°). */
    fun feedback(ctx: Context, v: Int): String {
        val o = get(ctx)
        val adj = (o.optDouble("adj", 0.0) + when { v < 0 -> -0.5; v > 0 -> 0.5; else -> 0.0 }).coerceIn(-5.0, 5.0)
        o.put("adj", adj)
        val log = o.optJSONArray("log") ?: JSONArray()
        log.put(JSONObject().put("ts", System.currentTimeMillis()).put("v", v).put("t", lastTrip(ctx)?.optJSONObject("pick")?.optDouble("t") ?: 0.0))
        while (log.length() > 40) log.remove(0)
        o.put("log", log)
        save(ctx, o)
        prefs(ctx).edit().remove("schrank_letzt").apply()
        return when { v < 0 -> "Notiert – beim nächsten Mal ziehe ich dich wärmer an."; v > 0 -> "Notiert – nächstes Mal etwas luftiger."; else -> "Super, dann passt es so." }
    }
}
