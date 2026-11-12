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

    /** Aktionen, deren Ergebnis Jarvis erst noch in eine Antwort fassen muss. */
    private val infoActions = setOf("calendar_list", "youtube_neu")

    private fun system(): String {
        val now = SimpleDateFormat("EEEE, dd.MM.yyyy, HH:mm 'Uhr'", Locale.GERMANY).format(Date())
        val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm", Locale.GERMANY).format(Date())
        val snap = Memory.snap(ctx)
        val name = snap.optString("name").ifBlank { "Jarvis" }
        val city = snap.optString("city").ifBlank { "Leonberg" }
        val cal = try { Cal.context(ctx) } catch (_: Exception) { "" }
        return """Du bist $name, der KI-Butler aus Iron Man: souverän, loyal, aufmerksam, höflich mit trockenem britischem Humor. Du bist der persönliche J.A.R.V.I.S. des Nutzers (wohnt in $city), hier auf seinem Samsung-Handy. Am PC läuft derselbe Jarvis, ihr teilt euch das Gedächtnis.
${Memory.persona(ctx)}
Du kennst den Nutzer, denkst mit und bist ihm einen Schritt voraus. Du nutzt, was er dir erzählt hat, ganz selbstverständlich, ohne es aufzuzählen, und achtest darauf, wie er drauf ist.
Du handelst selbstständig: Wenn der Nutzer etwas will, tust du es direkt mit den Aktionen unten, statt nachzufragen oder ihm zu erklären, wie es geht. Fehlende Kleinigkeiten ergänzt du sinnvoll (Termin ohne Dauer = 1 Stunde, "morgen früh" = 9 Uhr, "nachmittags" = 15 Uhr, "abends" = 19 Uhr). Nur wenn wirklich etwas Wichtiges fehlt (z. B. wen anrufen), fragst du kurz nach.
Antworten kurz und gesprochen (1 bis 2 Sätze), Deutsch, keine Listen, keine Sonderzeichen. Es ist $now (ISO: $iso).
$cal
${Memory.block(ctx)}
${Interests.block(ctx)}
Antworte NUR mit einem JSON-Objekt: {"actions":[ ... ], "say":"<was du sagst>"}
Mögliche Aktionen (mehrere nacheinander sind erlaubt):
{"action":"open_app","name":"<App-Name, z. B. WhatsApp, Spotify, Instagram, Kamera, Galerie>"}
{"action":"media","key":"<playpause|play|pause|next|previous>"}
{"action":"volume","what":"<up|down|mute|unmute|set>","value":<0-100 bei set>}   (Lautstärke von Musik und Videos)
{"action":"jarvis_volume","what":"<up|down|max|set>","value":<10-100 bei set>}   (deine eigene Sprechlautstärke, z. B. "sprich lauter", "du bist zu laut")
{"action":"alarm","hour":<0-23>,"minute":<0-59>,"label":"<optional>"}
{"action":"timer","seconds":<Sekunden>,"label":"<optional>"}
{"action":"calendar_add","title":"<Titel>","start":"<yyyy-MM-ddTHH:mm oder yyyy-MM-dd für ganztägig>","minutes":<Dauer, Standard 60>,"location":"<optional>","remind":<Minuten vorher erinnern, Standard 30>}   (trägt direkt in den Kalender ein; auch für "erinnere mich morgen um 9 an ..." mit remind 0)
{"action":"calendar_list","from":"<yyyy-MM-dd>","days":<Anzahl Tage>}   (Termine nachschauen, wenn die Frage über heute und morgen hinausgeht)
{"action":"calendar_delete","title":"<Teil des Titels>","date":"<yyyy-MM-dd, optional>"}
{"action":"navigate","to":"<Ziel>","mode":"<d|b|w>"}   (d Auto, b Fahrrad, w zu Fuß)
{"action":"call","who":"<Name aus den Kontakten oder Nummer>"}
{"action":"whatsapp","to":"<Name>","text":"<Nachricht in der Ich-Form des Nutzers>"}
{"action":"sms","to":"<Name>","text":"<Nachricht>"}
{"action":"youtube","query":"<Suche>"}
{"action":"youtube_neu","days":<Tage, Standard 7>}   (neue Videos der Kanäle, die der Nutzer gerade viel schaut – für "was kann ich auf YouTube schauen?", "gibt's was Neues von ...?")
{"action":"spotify","query":"<Suche>"}
{"action":"search","query":"<Google-Suche>"}
{"action":"url","url":"<Adresse>"}
{"action":"torch","on":<true|false>}
{"action":"settings","what":"<wifi|bluetooth|internet|volume|display|battery>"}
{"action":"remember","text":"<ein kurzer Satz über den Nutzer>","date":"<optional MM-TT bei Geburtstagen usw.>"}   (Speichere großzügig alles Dauerhafte, was der Nutzer erzählt: Familie, Freunde, Geburtstage, Vorlieben, Gewohnheiten, Pläne, Arbeit, Hobbys. Keine Passwörter, Kontonummern oder Gesundheitsdaten. Bestätige beiläufig.)
{"action":"forget","text":"<was vergessen werden soll>"}
{"action":"mood","text":"<wie der Nutzer gerade drauf ist, kurz>"}   (still, wenn man es an seinen Worten merkt)
Für reine Fragen oder Plaudern: "actions": [] und die Antwort in "say".
Beispiele: "öffne WhatsApp" -> {"actions":[{"action":"open_app","name":"WhatsApp"}],"say":"WhatsApp ist offen."}
"trag morgen um 15 Uhr Zahnarzt ein" -> {"actions":[{"action":"calendar_add","title":"Zahnarzt","start":"<morgen>T15:00"}],"say":"Steht drin, morgen um drei."}
"mach lauter" -> {"actions":[{"action":"volume","what":"up"}],"say":""}
"meine Schwester heißt Lisa" -> {"actions":[{"action":"remember","text":"Die Schwester des Nutzers heißt Lisa"}],"say":"Notiert."}"""
    }

    /** Gibt den gesprochenen Text zurück. */
    fun handle(key: String, text: String): String {
        Thread({ Interests.refreshGenres(ctx, key) }, "jarvis-genres").start()   // höchstens einmal am Tag
        history.put(JSONObject().put("role", "user").put("content", text))
        while (history.length() > 12) history.remove(0)
        val sys = system()
        val msgs = JSONArray().put(JSONObject().put("role", "system").put("content", sys))
        for (i in 0 until history.length()) msgs.put(history.get(i))
        val raw = Groq.chat(key, msgs, 500, json = true)
        history.put(JSONObject().put("role", "assistant").put("content", raw))
        val obj = try {
            JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw)?.value ?: raw)
        } catch (_: Exception) {
            return raw.replace(Regex("[*#_`{}\"]"), "").trim()
        }
        val results = mutableListOf<String>()
        val infos = mutableListOf<String>()
        val acts = obj.optJSONArray("actions") ?: JSONArray()
        for (i in 0 until acts.length()) {
            val a = acts.optJSONObject(i) ?: continue
            val r = actions.run(a) ?: continue
            if (a.optString("action") in infoActions) infos.add(r) else results.add(r)
        }
        // Nachgeschaute Infos (z. B. Kalender) in eine kurze gesprochene Antwort fassen
        if (infos.isNotEmpty()) {
            val m2 = JSONArray().put(JSONObject().put("role", "system").put("content",
                "Du bist Jarvis. Beantworte die Frage des Nutzers in 1 bis 3 kurzen gesprochenen Sätzen auf Deutsch, nur mit " +
                    "diesen Daten, ohne Listen und Sonderzeichen, Uhrzeiten wie \"um drei\" oder \"um 14 Uhr 30\".\n" + infos.joinToString("\n")))
                .put(JSONObject().put("role", "user").put("content", text))
            val ans = try { Groq.chat(key, m2, 200, json = false).trim() } catch (_: Exception) { infos.joinToString(" ").removePrefix("KALENDER: ") }
            history.put(JSONObject().put("role", "assistant").put("content", ans))
            return (listOf(ans) + results.filter { isProblem(it) }).joinToString(" ")
        }
        val say = obj.optString("say").trim()
        // Fehlermeldungen der Aktionen haben Vorrang vor einer zu optimistischen Antwort
        val problems = results.filter { isProblem(it) }
        return when {
            problems.isNotEmpty() -> problems.joinToString(" ")
            say.isNotEmpty() -> say
            results.isNotEmpty() -> results.joinToString(" ")
            acts.length() > 0 -> "Erledigt."
            else -> "Erledigt."
        }
    }

    private fun isProblem(r: String) = r.contains("nicht") || r.startsWith("Welche") || r.startsWith("Wie lange") ||
        r.startsWith("Für wann") || r.startsWith("Wie soll") || r.startsWith("Was soll") || r.startsWith("Ich darf")
}
