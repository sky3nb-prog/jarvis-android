package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Versteht den Befehl (Groq) und führt die passenden Handy-Aktionen aus – wie der PC-Jarvis. */
class Brain(private val ctx: Context) {
    private val history = JSONArray()
    private val actions = Actions(ctx)

    private fun system(): String {
        val now = SimpleDateFormat("EEEE, dd.MM.yyyy, HH:mm 'Uhr'", Locale.GERMANY).format(Date())
        val memory = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getString("memory", "") ?: ""
        return """Du bist Jarvis, der persönliche KI-Butler von Skyler aus Leonberg, hier auf seinem Handy (Samsung).
Im Grundton ernst, souverän und zurückhaltend; trockener, dosierter Humor, nie albern. Antworten kurz und gesprochen
(1 bis 2 Sätze), Deutsch, keine Listen, keine Sonderzeichen. Es ist $now.
$memory
Antworte NUR mit einem JSON-Objekt: {"actions":[ ... ], "say":"<was du sagst>"}
Mögliche Aktionen:
{"action":"open_app","name":"<App-Name, z. B. WhatsApp, Spotify, Instagram, Kamera>"}
{"action":"media","key":"<playpause|play|pause|next|previous>"}
{"action":"volume","what":"<up|down|mute|unmute|set>","value":<0-100 bei set>}
{"action":"alarm","hour":<0-23>,"minute":<0-59>,"label":"<optional>"}
{"action":"timer","seconds":<Sekunden>,"label":"<optional>"}
{"action":"navigate","to":"<Ziel>","mode":"<d|b|w>"}   (d Auto, b Fahrrad, w zu Fuß)
{"action":"call","who":"<Name aus den Kontakten oder Nummer>"}
{"action":"whatsapp","to":"<Name>","text":"<Nachricht in der Ich-Form des Nutzers>"}
{"action":"youtube","query":"<Suche>"}
{"action":"spotify","query":"<Suche>"}
{"action":"search","query":"<Google-Suche>"}
{"action":"url","url":"<Adresse>"}
{"action":"torch","on":<true|false>}
{"action":"settings","what":"<wifi|bluetooth|internet|volume|display|battery>"}
Für reine Fragen oder Plaudern: "actions": [] und die Antwort in "say".
Beispiel: "öffne WhatsApp" -> {"actions":[{"action":"open_app","name":"WhatsApp"}],"say":"WhatsApp ist offen."}"""
    }

    /** Gibt den gesprochenen Text zurück. */
    fun handle(key: String, text: String): String {
        history.put(JSONObject().put("role", "user").put("content", text))
        while (history.length() > 12) history.remove(0)
        val msgs = JSONArray().put(JSONObject().put("role", "system").put("content", system()))
        for (i in 0 until history.length()) msgs.put(history.get(i))
        val raw = Groq.chat(key, msgs, 400, json = true)
        history.put(JSONObject().put("role", "assistant").put("content", raw))
        val obj = try {
            JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw)?.value ?: raw)
        } catch (_: Exception) {
            return raw.replace(Regex("[*#_`{}\"]"), "").trim()
        }
        val results = mutableListOf<String>()
        val acts = obj.optJSONArray("actions") ?: JSONArray()
        for (i in 0 until acts.length()) {
            val a = acts.optJSONObject(i) ?: continue
            actions.run(a)?.let { results.add(it) }
        }
        val say = obj.optString("say").trim()
        // Fehlermeldungen der Aktionen haben Vorrang vor einer zu optimistischen Antwort
        val problems = results.filter { it.contains("nicht") || it.contains("Welche") || it.contains("Wie lange") || it.contains("Für wann") }
        return when {
            problems.isNotEmpty() -> problems.joinToString(" ")
            say.isNotEmpty() -> say
            results.isNotEmpty() -> results.joinToString(" ")
            else -> "Erledigt."
        }
    }
}
