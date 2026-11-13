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
    private val infoActions = setOf("calendar_list", "youtube_neu", "web", "musik")
    /** Zwischenstand fürs Fenster, z. B. "Jarvis sucht im Web …" */
    var onStatus: ((String) -> Unit)? = null
    /** Welche "Hirnregionen" gerade arbeiten (für die Symbole in der Kugel) */
    private fun think(vararg kinds: String) = Bus.emit("think", JSONObject().put("kinds", JSONArray(kinds.toList())).put("ms", 4500))
    /** Karte zur letzten Antwort (Musik, YouTube, Web oder einfach der Antworttext) */
    @Volatile var card: JSONObject? = null
    /** Lage für die Tour (Jarvis fliegt auf der Karte von Punkt zu Punkt und erzählt) */
    @Volatile var tour: JSONObject? = null

    private fun system(): String {
        val now = SimpleDateFormat("EEEE, dd.MM.yyyy, HH:mm 'Uhr'", Locale.GERMANY).format(Date())
        val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm", Locale.GERMANY).format(Date())
        val snap = Memory.snap(ctx)
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val name = (p.getString("assistant_name", "") ?: "").ifBlank { snap.optString("name").ifBlank { "Jarvis" } }
        val city = Lage.city(ctx)
        val anrede = (p.getString("anrede", "") ?: "").trim()
        Here.refresh(ctx)
        val here = Here.name(ctx)
        val addr = (p.getString("address", "") ?: "").trim()
        val ortInfo = (if (here.isNotBlank()) "\nDas Handy ist gerade in: $here." else "") +
            (if (addr.isNotBlank()) "\nAdresse des Nutzers (Startpunkt für Wege): $addr, $city." else "") +
            (if (anrede.isNotBlank()) "\nSprich den Nutzer mit \"$anrede\" an." else "")
        val cal = try { Cal.context(ctx) } catch (_: Exception) { "" }
        return """Du bist $name, der KI-Butler aus Iron Man: souverän, loyal, aufmerksam, höflich mit trockenem britischem Humor. Du bist der persönliche J.A.R.V.I.S. des Nutzers (wohnt in $city), hier auf seinem Samsung-Handy. Am PC läuft derselbe Jarvis, ihr teilt euch das Gedächtnis.
${Memory.persona(ctx)}$ortInfo
Du kennst den Nutzer, denkst mit und bist ihm einen Schritt voraus. Du weißt, was er gerade schaut und hört, und bringst das persönlich ein, wenn es passt (z. B. "Passend zu dem, was du gerade hörst ..."). Du nutzt, was er dir erzählt hat, ganz selbstverständlich, ohne es aufzuzählen, und achtest darauf, wie er drauf ist.
Du handelst selbstständig: Wenn der Nutzer etwas will, tust du es direkt mit den Aktionen unten, statt nachzufragen oder ihm zu erklären, wie es geht. Fehlende Kleinigkeiten ergänzt du sinnvoll (Termin ohne Dauer = 1 Stunde, "morgen früh" = 9 Uhr, "nachmittags" = 15 Uhr, "abends" = 19 Uhr). Nur wenn wirklich etwas Wichtiges fehlt (z. B. wen anrufen), fragst du kurz nach.
Antworten kurz und gesprochen (1 bis 2 Sätze), Deutsch, keine Listen, keine Sonderzeichen. Es ist $now (ISO: $iso).
$cal
${Memory.block(ctx)}
${Interests.block(ctx)}
${Themen.summary(ctx).let { if (it.isBlank()) "" else "Seine Interessen (gelernt): $it. Bring sie ein, wenn es passt." }}
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
{"action":"route","text":"<der ganze Wegewunsch des Nutzers, wörtlich>"}   (für JEDE Frage nach Weg, Route, Dauer, "wann muss ich los", Bahn/Bus-Verbindung, auch mit Zwischenstopps wie Bäcker oder Supermarkt; plant smart und öffnet Google Maps)
{"action":"navigate","to":"<Ziel>","mode":"<d|b|w>"}   (d Auto, b Fahrrad, w zu Fuß)
{"action":"call","who":"<Name aus den Kontakten oder Nummer>"}
{"action":"pc","text":"<Befehl an den Jarvis am PC, so wie man ihn dort sagen würde>"}   (alles, was am PC passieren soll: "mach am PC Musik an", "sperr den PC", "schick mir das Lied vom PC aufs Handy" -> text "schick mir was ich gerade höre aufs handy")
{"action":"whatsapp","to":"<Name>","text":"<Nachricht in der Ich-Form des Nutzers>"}
{"action":"sms","to":"<Name>","text":"<Nachricht>"}
{"action":"youtube","query":"<Suche>"}
{"action":"youtube_neu","days":<Tage, Standard 7>}   (neue Videos der Kanäle, die der Nutzer gerade viel schaut, plus passende neue Kanäle – für "was kann ich auf YouTube schauen?", "gibt's was Neues von ...?")
{"action":"musik"}   (seine Lieblingssongs und Musikrichtung gerade plus passende neue Songs von Deezer – für "was höre ich so?", "schlag mir Musik vor", "was passt dazu?")
{"action":"lage","ort":"<leer = Welt und Wohnort; \"hier\" = wo das Handy gerade ist; sonst Stadt oder Land>"}   (Lagebericht mit Karte: "wie ist die Lage?", "was ist los in der Welt?", "was gibt es Neues in Leonberg?", "was ist in Seoul los?", Nachrichten)
{"action":"fuerdich"}   (Neuigkeiten passend zu seinen Interessen: "was gibt's Neues für mich?", "was interessiert mich heute?", "Neuigkeiten zu meinen Themen")
{"action":"web","query":"<Suchanfrage>"}   (im Internet nachschauen: Nachrichten, Öffnungszeiten, Fakten, "schau mal nach ...", alles Aktuelle)
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

    /** Gibt den gesprochenen Text zurück; die passende Karte fürs Fenster liegt danach in [card]. */
    fun handle(key: String, text: String): String {
        Cards.pending = null
        tour = null
        val say = run(key, text)
        card = (Cards.pending ?: JSONObject().put("kind", "text").put("text", say)).put("say", say)
        return say
    }

    private fun run(key: String, text: String): String {
        Themen.note(ctx, "frage", text)
        Thread({ Themen.refresh(ctx, key) }, "jarvis-themen").start()
        Thread({ Interests.refreshGenres(ctx, key) }, "jarvis-genres").start()   // höchstens einmal am Tag
        history.put(JSONObject().put("role", "user").put("content", text))
        while (history.length() > 12) history.remove(0)
        val sys = system()
        val msgs = JSONArray().put(JSONObject().put("role", "system").put("content", sys))
        for (i in 0 until history.length()) msgs.put(history.get(i))
        think("gedaechtnis")   // er denkt nach und nutzt, was er über dich weiß
        if (Regex("wetter|regen|temperatur|grad|sonne|schnee", RegexOption.IGNORE_CASE).containsMatchIn(text)) think("wetter")
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
            when (a.optString("action")) {
                "youtube", "youtube_neu" -> think("videos")
                "musik", "spotify", "media" -> think("musik")
                "web", "search", "url" -> think("web")
                "calendar_add", "calendar_list", "calendar_delete", "alarm", "timer" -> think("kalender")
                "lage" -> think("lage", "nachrichten")
                "fuerdich" -> think("nachrichten", "gedaechtnis")
                "remember", "forget", "mood" -> think("gedaechtnis")
                "navigate" -> think("lage")
            }
            val r = when (a.optString("action")) {
                "web" -> { onStatus?.invoke("Jarvis sucht im Web …"); Cards.web(key, a.optString("query").ifBlank { text }) }
                "musik" -> { onStatus?.invoke("Schaue, was du hörst …"); Cards.music(ctx) }
                "lage", "fuerdich" -> {
                    onStatus?.invoke("Jarvis prüft die Lage …")
                    val city = Lage.city(ctx)
                    val ort = if (a.optString("action") == "fuerdich") "@fuerdich" else a.optString("ort").trim().let { if (it.equals(city, true)) "" else it }
                    try {
                        val d = Lage.get(ctx, key, ort)
                        tour = d
                        val intro = d.optString("briefing").ifBlank { "Hier ist die Lage." }
                        history.put(JSONObject().put("role", "assistant").put("content", "(Lagebericht gezeigt) " + intro))
                        return intro
                    } catch (e: Exception) { e.message ?: "Die Lage kann ich gerade nicht abrufen." }
                }
                "youtube_neu" -> { onStatus?.invoke("Schaue bei deinen Kanälen …"); Cards.youtube(ctx, key, a.optInt("days", 7).coerceIn(1, 30)) }
                "route" -> { onStatus?.invoke("Jarvis plant den Weg …"); think("lage")
                    try { Route.plan(ctx, key, a.optString("text").ifBlank { text }).say } catch (e: Exception) { "Den Weg konnte ich gerade nicht planen." } }
                else -> actions.run(a)
            } ?: continue
            if (a.optString("action") in infoActions) infos.add(r) else results.add(r)
        }
        // Nachgeschaute Infos (z. B. Kalender) in eine kurze gesprochene Antwort fassen
        if (infos.isNotEmpty()) {
            val m2 = JSONArray().put(JSONObject().put("role", "system").put("content",
                "Du bist Jarvis, persönlich und souverän. Beantworte die Frage des Nutzers in 1 bis 3 kurzen gesprochenen Sätzen " +
                    "auf Deutsch, nur mit diesen Daten, ohne Listen und Sonderzeichen, Uhrzeiten wie \"um drei\". Die Einzelheiten " +
                    "(Songs, Videos, Quellen) stehen schon im Fenster auf dem Bildschirm – nenne nur das Wichtigste.\n" + infos.joinToString("\n")))
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
