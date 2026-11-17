package de.skyler.jarvis

import android.content.Context
import android.content.Intent
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * „Wo hab ich's hingelegt?“
 *  - „Friday, der Schlüssel liegt in der Schublade“ / „ich hab meine Kopfhörer aufs Regal gelegt“ -> merken
 *  - „Ich hab mein Fahrrad hier abgestellt“ -> mit Standort merken (Antippen öffnet die Karte)
 *  - „Wo ist mein Schlüssel?“ / „Wo hab ich die Kopfhörer hingelegt?“ -> Antwort
 * Dazu: Warenkorb / letzte Bestellung öffnen (Amazon, Rewe) – bezahlen tust du selbst.
 */
object Dinge {
    private val de = Locale.GERMANY
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    private fun all(ctx: Context) = try { JSONArray(prefs(ctx).getString("dinge", "[]")) } catch (_: Exception) { JSONArray() }

    private val PUT = Regex("^(?:ich (?:hab|habe) )?(?:mein(?:e|en|em)? |die |den |das |der )?([\\p{L} -]{2,30}?) (?:liegt|liegen|steht|stehen|hängt|hängen|hab ich|habe ich)" +
        "(?:jetzt )?((?:in|im|auf|auf dem|auf der|unter|unterm|neben|hinter|bei|beim|an|am|zwischen|vor|oben|unten|hier)\\b.{1,60}?)(?: (?:gelegt|gestellt|abgestellt|hingelegt|getan|gepackt|verstaut|geparkt))?$")
    private val PUT2 = Regex("^ich (?:hab|habe) (?:mein(?:e|en|em)? |die |den |das )?([\\p{L} -]{2,30}?) ((?:in|im|auf|auf dem|auf der|unter|unterm|neben|hinter|bei|beim|an|am|vor|hier)\\b.{0,60}?) (?:gelegt|gestellt|abgestellt|hingelegt|getan|gepackt|verstaut|geparkt|gelassen)$")
    private val ASK = Regex("^(?:wo (?:ist|sind|liegt|liegen|steht|stehen|hab ich|habe ich)|weißt du wo) (?:mein(?:e|en)? |die |der |das |den )?([\\p{L} -]{2,30}?)(?: (?:hingelegt|gelegt|hingestellt|abgestellt|gelassen|ist|sind|liegt))?$")

    private fun clean(s: String) = s.lowercase().trim().trim('.', '!', '?', ',').replace(Regex("^(?:jarvis|friday|hey)[ ,]+"), "")

    /** null = nichts für mich; sonst die Antwort. */
    fun handle(ctx: Context, text: String): String? {
        val low = clean(text)
        if (low.split(" ").size > 16) return null
        ASK.find(low)?.let { m ->
            val r = where(ctx, m.groupValues[1].trim())
            val personal = Regex("\\b(mein\\w*|hingelegt|gelegt|abgestellt|hab ich|habe ich)\\b").containsMatchIn(low)
            if (r != null) return r
            if (personal) return "Das hast du mir nicht gesagt. Sag beim nächsten Mal einfach „${m.groupValues[1].trim()} liegt …“, dann merk ich's mir."
            return null
        }
        (PUT2.find(low) ?: PUT.find(low))?.let { m ->
            val what = m.groupValues[1].trim().removePrefix("mein ").removePrefix("meine ")
            val place = m.groupValues[2].trim()
            if (what.length < 2 || what in setOf("ich", "es", "das", "er", "sie", "wir", "heute", "morgen")) return null
            return put(ctx, what, place)
        }
        if (Regex("\\b(?:amazon[- ]?)?warenkorb\\b").containsMatchIn(low) && Regex("\\b(öffne|zeig|mach|geh|auf)\\w*").containsMatchIn(low)) return open(ctx, "amazon")
        if (Regex("\\brewe\\b").containsMatchIn(low) && Regex("\\b(bestell|einkauf|öffne|letzte)\\w*").containsMatchIn(low)) return open(ctx, "rewe")
        return null
    }

    private fun put(ctx: Context, what: String, place0: String): String {
        var place = place0
        val o = JSONObject().put("was", what).put("wo", place).put("t", System.currentTimeMillis())
        if (place == "hier" || place.startsWith("hier ")) {
            try { Here.refresh(ctx); Here.latLon(ctx)?.let { (la, lo) -> o.put("lat", la).put("lon", lo); place = "hier (${Here.name(ctx).ifBlank { "Standort gemerkt" }})"; o.put("wo", place) } } catch (_: Exception) {}
        }
        val k = Chats.norm(what)
        val a = all(ctx); val l = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { Chats.norm(it.optString("was")) != k } + o
        prefs(ctx).edit().putString("dinge", JSONArray(l.takeLast(60)).toString()).apply()
        return "Gemerkt: ${what.replaceFirstChar { it.uppercase() }} – $place."
    }

    private fun where(ctx: Context, what: String): String? {
        val k = Chats.norm(what).removeSuffix("n").removeSuffix("e")
        if (k.length < 2) return null
        val a = all(ctx)
        val hit = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.lastOrNull { val w = Chats.norm(it.optString("was")); w.contains(k) || k.contains(w.removeSuffix("n").removeSuffix("e")) }
            ?: return null
        val wann = SimpleDateFormat("EEEE, HH:mm", de).format(Date(hit.optLong("t")))
        if (hit.has("lat")) try {
            ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("geo:${hit.optDouble("lat")},${hit.optDouble("lon")}?q=${hit.optDouble("lat")},${hit.optDouble("lon")}(${Uri.encode(what)})")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (_: Exception) {}
        return "${hit.optString("was").replaceFirstChar { it.uppercase() }}: ${hit.optString("wo")} (gemerkt $wann Uhr)." + if (hit.has("lat")) " Ich zeig's dir auf der Karte." else ""
    }

    private fun open(ctx: Context, shop: String): String {
        val (url, name) = if (shop == "amazon") "https://www.amazon.de/gp/cart/view.html" to "Amazon-Warenkorb"
            else "https://shop.rewe.de/mydata/meine-einkaeufe" to "Rewe – deine letzten Einkäufe"
        val i = if (shop == "rewe") ctx.packageManager.getLaunchIntentForPackage("de.rewe.app.mobile") ?: Intent(Intent.ACTION_VIEW, Uri.parse(url))
            else Intent(Intent.ACTION_VIEW, Uri.parse(url))
        return try { ctx.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); "Ich mach dir $name auf – kaufen tippst du selbst." }
        catch (_: Exception) { "$name ging nicht auf." }
    }
}
