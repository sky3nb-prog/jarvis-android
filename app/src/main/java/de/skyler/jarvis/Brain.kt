package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Versteht den Befehl (Groq) und führt die passenden Handy-Aktionen aus – wie der PC-Jarvis. */
class Brain(private val ctx: Context) {
    companion object {
        private val SETUP = Regex("wie richte ich dich ein|wie (richte|stelle) ich (dich|jarvis) ein|einrichten|anleitung|handbuch|wie funktionierst du|was muss ich (zuerst )?(machen|einstellen)", RegexOption.IGNORE_CASE)
        /** Download-Version: „Wie richte ich dich ein?“ – kurze Anleitung (geht auch ohne KI-Schlüssel). */
        fun setupAnswer(text: String): String? {
            if (BuildConfig.FLAVOR != "konto" || !SETUP.containsMatchIn(text)) return null
            return "So geht's in drei Schritten: 1. Hol dir auf console.groq.com einen kostenlosen KI-Schlüssel (API Keys → Create) und " +
                "trag ihn unter Einstellungen → Allgemein → KI-Schlüssel ein. 2. Trag unter Einstellungen → Zuhause & Orte deinen Wohnort ein. " +
                "3. Sag „Jarvis“ und dann, was du willst. Für den PC lädst du das Programm von derselben Seite und meldest dich mit demselben Konto an."
        }
    }

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
Du kennst den Nutzer, denkst mit und bist ihm einen Schritt voraus. Sei persönlich wie ein guter Freund: nutz seinen Namen und was du über ihn weißt (Familie, Hund, Hobbys, ETS2), frag ab und zu nach, wie es gelaufen ist, und erinnere dich an Dinge, die er dir erzählt hat. Du weißt, was er gerade schaut und hört, und bringst das persönlich ein, wenn es passt (z. B. "Passend zu dem, was du gerade hörst ..."). Du nutzt, was er dir erzählt hat, ganz selbstverständlich, ohne es aufzuzählen, und achtest darauf, wie er drauf ist.
Du handelst selbstständig: Wenn der Nutzer etwas will, tust du es direkt mit den Aktionen unten, statt nachzufragen oder ihm zu erklären, wie es geht. Fehlende Kleinigkeiten ergänzt du sinnvoll (Termin ohne Dauer = 1 Stunde, "morgen früh" = 9 Uhr, "nachmittags" = 15 Uhr, "abends" = 19 Uhr). Nur wenn wirklich etwas Wichtiges fehlt (z. B. wen anrufen), fragst du kurz nach.
Antworten kurz und gesprochen (1 bis 2 Sätze), Deutsch, keine Listen, keine Sonderzeichen.
RATGEBER: Bittet er dich um Rat (Streit in einer Gruppe, "was soll ich machen", "wie soll ich entscheiden", Ärger mit jemandem, schwierige Entscheidung), dann bist du ein fairer, ruhiger Ratgeber und darfst 4 bis 8 Sätze sagen: fehlt Wichtiges, zuerst höchstens zwei kurze Rückfragen; sonst kurz zusammenfassen, beide Seiten fair betrachten, zwei bis drei Möglichkeiten mit Vor- und Nachteilen, eine klare Empfehlung, und anbieten, eine Nachricht vorzuschreiben. Kein Witz dabei. Es ist $now (ISO: $iso).
$cal
${try { Halte.summary(ctx) } catch (_: Exception) { "" }}
${try { Gassi.summary(ctx) } catch (_: Exception) { "" }}
${Stimmung.prompt(ctx)}
${Melden.schoolText(ctx)}
${Schule.prompt(ctx)}
${Humor.prompt(ctx)}
Erwähnt er, dass er gerade isst oder gleich isst (Essen, Mittagessen, Frühstück, "ich ess grad"), wünsch ihm kurz und locker guten Appetit. Essens-Ideen nur leicht und freundlich, nie Kalorien, Diät oder Verbote.
Steht im Gedächtnis, dass ihm Konzentration oder Ordnung schwerfällt oder er sich mehr Struktur wünscht: Erinnerungen konkret und mit Uhrzeit, große Aufgaben in kleine erste Schritte zerlegen, kurz und klar antworten, nie belehren oder vorwerfen, kleine Erfolge feiern.
${Memory.block(ctx)}
${Interests.block(ctx)}
${snap.optJSONObject("pc_media")?.let { pm -> val m = pm.optJSONArray("music"); if (m == null || m.length() == 0) "" else "Am PC hört er vor allem: " + (0 until m.length()).joinToString(", ") { m.optString(it) } + "." } ?: ""}
${Themen.summary(ctx).let { if (it.isBlank()) "" else "Seine Interessen (gelernt): $it. Bring sie ein, wenn es passt." }}
Antworte NUR mit einem JSON-Objekt: {"actions":[ ... ], "say":"<was du sagst>"}
Mögliche Aktionen (mehrere nacheinander sind erlaubt):
{"action":"open_app","name":"<App-Name, z. B. WhatsApp, Spotify, Instagram, Kamera, Galerie>"}
{"action":"media","key":"<playpause|play|pause|next|previous>"}
{"action":"volume","what":"<up|down|mute|unmute|set>","value":<0-100 bei set>}   (Lautstärke von Musik und Videos)
{"action":"jarvis_volume","what":"<up|down|max|set>","value":<10-100 bei set>}   (deine eigene Sprechlautstärke, z. B. "sprich lauter", "du bist zu laut")
{"action":"aufstehen","datum":"yyyy-MM-dd","zeit":"HH:mm"}   (Achtung: zwischen 0 und 5 Uhr nachts meint "morgen" den heutigen Kalendertag. EINMAL aufstehen: "ich will morgen um 7:10 aufstehen", "weck mich morgen, ich muss um 6 raus" – Jarvis stellt die Wecker selbst nach der Einstellung "Minuten vorher", gib KEINE Wecker-Zeiten an)
{"action":"wecker_plan","aufstehen":"HH:mm","tage":"schultage" | "wochenende" | "montags" …}   (IMMER: "an Schultagen will ich um 7:10 aufstehen", "montags um 8" – jeden Abend stellt er die Wecker für den nächsten Tag wieder an)
{"action":"wecker_erinnerung","datum":"yyyy-MM-dd","zeit":"HH:mm","text":"<woran, kurz>","vorlauf":<Minuten früher>}   ("erinnere mich morgen um 10 mit einem Wecker, dass ich los muss" -> vorlauf 15, damit er sich fertig machen kann; Termin oder etwas Wichtiges -> 10; sonstige Erinnerung -> 5; "genau um" -> 0)
{"action":"wecker","zeiten":["HH:mm", …],"aus":false}   (nur wenn er GENAU sagt, wann es klingeln soll: "stell einen Wecker auf 6", "Wecker um 6:30 und 6:40"; aus true = Wecker ausschalten, zeiten leer = alle von Jarvis)
{"action":"wecker_zeigen"}   ("zeig meine Wecker")
{"action":"timer","seconds":<Sekunden>,"label":"<optional>"}   ("Timer auf 10 Minuten" – für Zeitspannen immer Timer, keinen Wecker)
{"action":"calendar_add","title":"<Titel>","start":"<yyyy-MM-ddTHH:mm oder yyyy-MM-dd für ganztägig>","minutes":<Dauer, Standard 60>,"location":"<optional>","remind":<Minuten vorher erinnern, Standard 30>}   (trägt direkt in den Kalender ein – nur echte Termine; kleine Erinnerungen sind "erinnerung")
{"action":"calendar_list","from":"<yyyy-MM-dd>","days":<Anzahl Tage>}   (Termine nachschauen, wenn die Frage über heute und morgen hinausgeht)
{"action":"calendar_delete","title":"<Teil des Titels>","date":"<yyyy-MM-dd, optional>"}
{"action":"route","text":"<der ganze Wegewunsch des Nutzers, wörtlich>"}   (für JEDE Frage nach Weg, Route, Dauer, "wann muss ich los", Bahn/Bus-Verbindung, auch mit Zwischenstopps wie Bäcker oder Supermarkt; plant smart und öffnet Google Maps)
{"action":"navigate","to":"<Ziel>","mode":"<d|b|w>"}   (d Auto, b Fahrrad, w zu Fuß)
{"action":"call","who":"<Name aus den Kontakten oder Nummer>"}
{"action":"screen","frage":"<was er wissen will>","geraet":"handy" | "pc"}   (wenn er sagt "schau mal hier", "was siehst du", "guck mal auf den Bildschirm", "was ist das hier"; "pc" nur wenn er den PC-Bildschirm meint)
{"action":"sticker","to":"<Gruppe oder Person wie in WhatsApp>","anzahl":<Zahl, höchstens 1000>}   ("schick 500 Sticker in die Gruppe TR9000" – ERST nachfragen „Soll ich wirklich 500 Sticker an TR9000 schicken?“ und die Aktion NUR nach seinem Ja; über 1000 sagen, dass mehr WhatsApp sperrt)
{"action":"pc","text":"<Befehl an den Jarvis am PC, so wie man ihn dort sagen würde>"}   (alles, was am PC passieren soll: "mach am PC Musik an", "sperr den PC", "schick mir das Lied vom PC aufs Handy" -> text "schick mir was ich gerade höre aufs handy")
{"action":"whatsapp","to":"<Name>","text":"<Nachricht in der Ich-Form des Nutzers>","jarvis":false}   (jarvis true, wenn er "unter deinem Namen", "als Jarvis", "von dir aus" sagt: dann schreibst DU über ihn in der dritten Person, z. B. "der Nutzer ist um 18 Uhr da", ohne "Hier ist Jarvis" – das kommt automatisch davor; auch für "antworte Mama …")
{"action":"sms","to":"<Name>","text":"<Nachricht>"}
{"action":"heute","datum":"yyyy-MM-dd (leer = heute)","ziel":"<Ort oder Adresse, leer = fester Weg>","los":"HH:mm oder leer","an":"HH:mm oder leer","zuhause":"HH:mm oder leer","aus":false,"stopp":"<Laden unterwegs oder leer, z. B. Rewe>","was":"<was er dort will: Brot, Einkauf … oder leer>"}   (einmaliger Weg an einem Tag. "ich fahr zu Opa und vorher noch zum Rewe einkaufen" -> ziel Opa, stopp Rewe, was Einkauf; "um 15 Uhr Brot holen" -> ziel Rewe bzw. Bäcker, was Brot. GENAU unterscheiden: "los" = Zeit, zu der er HIER losfährt/losgeht ("ich will um 14:50 los zu Oma und Opa", "um 15 Uhr geh ich Brot einkaufen", "um 16:10 fahr ich zu Opa"); "an" = Zeit, zu der er DORT sein will ("ich will um 14:50 bei Oma und Opa sein", "ich muss um 15 Uhr beim Rewe sein", "um 15 Uhr soll ich da sein") – Jarvis rechnet dann selbst, wann er los muss. Nie beides raten. Einkaufen ohne Ort -> ziel "Rewe". "heute will ich um 19 Uhr zuhause sein" -> zuhause; "Donnerstag fahr ich nicht zu Opa" -> aus true. Relative Zeiten mit der aktuellen Uhrzeit ausrechnen: "in einer halben Stunde los zu Oma und Opa" -> los = jetzt + 30 Min.; "in 10 Minuten geh ich" -> los = jetzt + 10; "in einer Stunde muss ich beim Rewe sein" -> an = jetzt + 60)
{"action":"test_fahrt"}   ("schick mir eine Testnachricht", "wie sieht die Nachricht für Donnerstag aus?")
{"action":"heim_sms","an":"<Name, leer = Mama>","text":"<Text, leer = Bin gleich da.>"}   ("schick Mama eine SMS, wenn ich wieder heimkomme", "sag Mama Bescheid, kurz bevor ich zuhause bin" – einmalig, kurz vor dem Heimkommen)
{"action":"gassi","an":true}   ("ich geh mit dem Hund", "Hunderunde starten" – schaltet die Gassi-Erkennung ein; mit SMS-Wunsch zusätzlich heim_sms)
{"action":"test_bahn"}   ("such mir jetzt mal die Bahn zu Oma und Opa raus", "Bahn-Test", "zeig mir die Bahnverbindung mit Ticket" – echte Verbindung ab jetzt, mit Ticket. Er hat KEIN Abo/Schülerticket und braucht immer ein Ticket; kaufen tut er selbst im DB Navigator)
{"action":"losfahren","ziel":"<gespeicherter Ort, z. B. Opa>"}   ("ich fahr jetzt los zu Oma und Opa", "bin unterwegs zu Opa": Wetter-Tipp Rad/Bahn und kurz vor der Ankunft per SMS Bescheid geben)
{"action":"ort_erinnerung","ort":"<gespeicherter Ort wie Opa, oder zuhause>","text":"<woran erinnern>"}   ("erinnere mich, wenn ich bei Opa bin, an das Ladekabel", "wenn ich zu Opa fahre, denk an …", "Donnerstag bei Opa an … denken", "wenn ich heimkomme, erinnere mich an …")
{"action":"briefing","tag":"heute" | "morgen"}   ("gib mir das Briefing", "was ist morgen los und was zieh ich an?")
{"action":"rueckblick"}   ("wie war meine Woche?", "Wochenrückblick", die letzten 7 Tage)
{"action":"erinnerung","text":"<woran, kurz, z. B. Brot holen>","datum":"yyyy-MM-dd oder null","zeit":"HH:mm oder null","in_minuten":<nur bei "in 20 Minuten", sonst 0>}   (IMMER für "erinnere mich um 12:30 an Brot", "erinnere mich in 20 Minuten an den Ofen", "morgen Brot holen", "denk dran, dass ich Montag das Formular abgeben muss" – NICHT in den Kalender. Ohne Uhrzeit: datum setzen, zeit null; Jarvis sucht die beste Gelegenheit. Zwischen 0 und 5 Uhr heißt "morgen" heute.)
{"action":"modus","name":"fokus" | "gaming" | "chill" | "kino" | "schule" | "nacht" | "aus"}   ("Fokus-Modus", "ich muss lernen", "Gaming-Modus", "ich zock jetzt", "Chill-Modus", "Kino-Modus", "Schulmodus", "Gute Nacht", "Modus aus", "Guten Morgen, alles normal")
{"action":"schule","art":"ha" | "arbeit" | "test","fach":"<Fach oder leer>","text":"<was genau, z. B. Seite 42 Nr. 3 oder Thema der Arbeit>","datum":"yyyy-MM-dd"}   ("Hausaufgabe Mathe Seite 42 bis Donnerstag", "nächsten Dienstag schreiben wir Englisch, Vokabeln Unit 3", "am 21.11. ist Bio-Test über Zellen" – Datum selbst ausrechnen)
{"action":"person","wer":"<Name, wie er ihn nennt>","geschenk":true|false}   ("Geschenkidee für Alex", "was soll ich Mama schenken?" -> geschenk true; "was weißt du über Alex?", "wie heißt Alex auf Discord?" -> false)
{"action":"pakete"}   ("wo ist mein Paket?", "kommt heute ein Paket?", "Paketstatus")
{"action":"mails"}   ("hab ich neue Mails?", "was kam per Mail?", "neue E-Mails")
{"action":"ausgaben"}   ("wie viel hab ich diesen Monat ausgegeben?", "meine Ausgaben", "was hab ich bei Amazon ausgegeben?")
{"action":"notfall"}   (NUR wenn er ausdrücklich „Notfall“ sagt oder klar um Hilfe in einer Notlage bittet: „Jarvis, Notfall“, „Hilfe, ich hatte einen Unfall“ – schickt sofort SMS mit Standort an seine Notfall-Person und ruft an)
{"action":"note","fach":"<Fach>","note":"<z. B. 2, 2+, 3->","art":"arbeit" | "test" | ""}   ("in Mathe hab ich eine 2 geschrieben", "Bio-Test zurück: 3 minus")
{"action":"idee","text":"<die Idee in seinen Worten, kurz>"}   ("Jarvis, ich hab eine Idee: …", "schreib auf die Ideenliste …", "merk dir als Idee …")
{"action":"statuscheck"}   ("Statuscheck", "Systemcheck", "laufen alle Systeme?", "ist alles okay mit dir?")
{"action":"gesundheit","was":"heute" | "gestern" | "woche" | "schlaf" | "bilanz"}   ("wie viele Kalorien hab ich heute verbraucht?", "war ich im Defizit?", "wie aktiv war ich die Woche?", "wie hab ich geschlafen?", "Tagesbilanz") – Daten aus Samsung Health und der Schlaf-Erkennung, NIE raten
{"action":"wochenvorschau"}   ("was steht nächste Woche an?", "Wochen-Update", die nächsten 7 Tage)
{"action":"youtube","query":"<Suche>"}
{"action":"youtube_neu","days":<Tage, Standard 7>}   (neue Videos der Kanäle, die der Nutzer gerade viel schaut, plus passende neue Kanäle – für "was kann ich auf YouTube schauen?", "gibt's was Neues von ...?")
{"action":"musik"}   (seine Lieblingssongs und Musikrichtung gerade plus passende neue Songs von Deezer – für "was höre ich so?", "schlag mir Musik vor", "was passt dazu?")
{"action":"lage","ort":"<leer = Welt und Wohnort; \"hier\" = wo das Handy gerade ist; sonst Stadt oder Land>"}   (Lagebericht mit Karte: "wie ist die Lage?", "was ist los in der Welt?", "was gibt es Neues in meiner Stadt?", "was ist in Seoul los?", Nachrichten)
{"action":"fuerdich"}   (Neuigkeiten passend zu seinen Interessen: "was gibt's Neues für mich?", "was interessiert mich heute?", "Neuigkeiten zu meinen Themen")
{"action":"vergleich","items":["<A>","<B>"],"frage":"<worauf es ihm ankommt>"}   ("Was ist besser, A oder B?", "Soll ich das Cube oder das Canyon nehmen?", Kaufberatung: recherchiert im Netz und empfiehlt klar; "say" dann leer lassen)
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
        setupAnswer(text)?.let { card = JSONObject().put("kind", "text").put("text", it).put("say", it); return it }
        Cards.pending = null
        tour = null
        val say = run(key, text)
        card = (Cards.pending ?: JSONObject().put("kind", "text").put("text", say)).put("say", say)
        return say
    }

    /** Kalender-Wünsche laufen über einen festen Ablauf (rechnen, eintragen, nachprüfen), nicht über die freie KI. */
    private var voicePending: Triple<String?, String?, Long>? = null   // (an wen, –, seit wann)
    var termin: Termin.R? = null
    var fromPc = false

    private fun run(key: String, text: String): String {
        termin = null
        Actions.skipConfirm = fromPc
        // „Ich bin jetzt weg“: PC bleibt an und hält sich selbst aktuell (Weg-Modus am PC)
        val lowW = text.lowercase().trim().trim('.', '!', '?')
        // wartet eine Nachricht auf dein Ja? (vorher vorgelesen, damit nichts zu früh rausgeht)
        if (Actions.pending != null) {
            if (Regex("^(?:ja|jo|jap|yes|klar|passt|genau|schick(?:'s| es| ab)?|senden|abschicken|ok(?:ay)?|mach)\\b").containsMatchIn(lowW) && lowW.split(" ").size <= 5)
                actions.confirmPending(true)?.let { return it }
            else if (Regex("^(?:nein|nee|ne|nö|stopp|abbrechen|lass(?: es)?|doch nicht|nicht schicken)\\b").containsMatchIn(lowW))
                actions.confirmPending(false)?.let { return it }
            else Actions.pending = null   // etwas anderes gesagt: Nachricht verwerfen, normal weiter
        }
        if (!fromPc && lowW.split(" ").size <= 8 && Regex("\\bich bin (jetzt |mal |kurz |dann )*(weg|unterwegs|los)\\b|\\bich (geh|gehe|muss) (jetzt |mal )*(los|weg)\\b|\\bweg-?modus\\b").containsMatchIn(lowW)
            && !Regex("\\b(aus|herunter|runter)\\b").containsMatchIn(lowW) && Link.paired(ctx)) {
            val r = try { Link.command(ctx, JSONObject().put("type", "weg_modus").put("on", true), 12_000) } catch (_: Exception) { null }
            return if (r != null) "Alles klar, bis später. Der PC bleibt an, holt sich Updates selbst und schreibt dir, wenn was ist."
                   else "Bis später. Der PC antwortet gerade nicht – ist er an?"
        }
        // „Wo hab ich … hingelegt?“, „… liegt in der Schublade“, Warenkorb öffnen
        try { Dinge.handle(ctx, text)?.let { return it } } catch (_: Exception) {}
        // „Plan ein Treffen mit Max (am Wochenende)“ -> freie Zeiten + Nachricht in seinem Stil
        Regex("\\b(?:plan|mach|organisier|frag)\\w*\\s+(?:mir\\s+)?(?:ein(?:en)?\\s+)?(?:treffen|termin)\\s+mit\\s+([\\p{L}-]+)(.*)$").find(lowW)?.let { m ->
            val name = m.groupValues[1].replaceFirstChar { it.uppercase() }
            return try { Stil.meet(ctx, name, m.groupValues[2]) } catch (e: Exception) { "Das ging gerade nicht (${e.message})." }
        }
        // „Übernimm den Chat mit Max“ / „ich übernehme wieder“
        Regex("^(?:übernimm|übernehme du|übernimmst du)\\s+(?:mal\\s+|jetzt\\s+)?(?:den chat (?:mit|von)\\s+|das gespräch mit\\s+|für mich\\s+)?([\\p{L}-]+)$").find(lowW)?.let { m ->
            if (m.groupValues[1] !in setOf("das", "den", "es", "du")) return Stil.takeover(ctx, m.groupValues[1].replaceFirstChar { it.uppercase() })
        }
        Regex("^(?:ich übernehm\\w*|hör auf zu antworten|lass mich wieder)(?:\\s+(?:wieder|selbst|jetzt))*(?:\\s+(?:bei|mit)\\s+([\\p{L}-]+))?$").find(lowW)?.let { m ->
            return Stil.release(ctx, m.groupValues[1])
        }
        // WhatsApp-Anruf läuft: „drück weg“
        if (Butler.waCall != null && lowW.split(" ").size <= 6 && Regex("\\b(drück\\w* (ihn |sie )?weg|wegdrück\\w*|ablehn\\w*|leg auf|auflegen|kann (jetzt |gerade )?nicht)\\b").containsMatchIn(lowW))
            return Butler.waDecline(ctx)
        // „Schick Max eine Sprachnachricht: ich komm später“ / „Nimm eine Sprachnachricht für Max auf und sag …“
        (Regex("^(?:schick|sende|schicke)\\s+([\\p{L}-]+)\\s+(?:eine |ne )?sprachnachricht\\s*(?:und sag(?:e)?|mit|dass|:|,)?\\s*(.+)$").find(lowW)
            ?: Regex("^antworte\\s+([\\p{L}-]+)\\s+(?:als|per|mit (?:einer )?)\\s*sprachnachricht\\s*(?:und sag(?:e)?|dass|:|,)?\\s*(.+)$").find(lowW)
            ?: Regex("^(?:nimm|nehm|nehme)\\s+(?:mal\\s+)?(?:eine |ne )?sprachnachricht\\s+(?:für|an)\\s+([\\p{L}-]+)\\s+auf\\s*(?:und sag(?:e)?|mit|dass|:|,)?\\s*(.+)$").find(lowW))?.let { m ->
            val name = m.groupValues[1].replaceFirstChar { it.uppercase() }
            val inhalt = text.trim().let { t -> t.substring(minOf(t.length, (t.lowercase().indexOf(m.groupValues[2].take(12)).takeIf { it >= 0 } ?: 0))) }.ifBlank { m.groupValues[2] }
            return try { WaSend.voice(ctx, name, inhalt) } catch (e: Exception) { "Die Sprachnachricht ging nicht (${e.message})." }
        }
        // Sprachnachricht ohne vollständige Angaben: nachfragen (an wen? was?) und die nächste Antwort dafür nehmen
        voicePending?.let { vp ->
            voicePending = null
            if (System.currentTimeMillis() - vp.third < 90_000L && !Regex("^(?:nein|nee|abbrechen|stopp|lass)\\b").containsMatchIn(lowW)) {
                val name = vp.first ?: Regex("^(?:an\\s+)?([\\p{L}-]+)").find(lowW)?.groupValues?.get(1)?.replaceFirstChar { it.uppercase() }
                val inhalt = if (vp.first == null) text.trim().replaceFirst(Regex("^(?:an\\s+)?[\\p{L}-]+[,:]?\\s*", RegexOption.IGNORE_CASE), "") else text.trim()
                if (name != null && inhalt.isNotBlank()) return try { WaSend.voice(ctx, name, inhalt) } catch (e: Exception) { "Die Sprachnachricht ging nicht (${e.message})." }
                if (name != null) { voicePending = Triple(name, null, System.currentTimeMillis()); return "Was soll ich $name sagen?" }
            }
        }
        if (Regex("\\bsprach ?nachricht\\b").containsMatchIn(lowW) && Regex("\\b(?:schick|send|nimm|nehm|aufnehm|mach|kannst du|könntest du)\\w*").containsMatchIn(lowW)) {
            val name = Regex("\\b(?:an|für)\\s+([\\p{L}-]+)").find(lowW)?.groupValues?.get(1)
                ?: Regex("\\b(?:schick|sende)\\w*\\s+(?:bitte\\s+|mal\\s+)*([\\p{L}-]+)\\s+(?:eine|ne)\\s+sprach").find(lowW)?.groupValues?.get(1)
            val n = name?.takeIf { it !in setOf("mir", "dir", "uns", "eine", "ne", "bitte", "mal", "du") }?.replaceFirstChar { it.uppercase() }
            voicePending = Triple(n, null, System.currentTimeMillis())
            return if (n == null) "Klar. An wen soll die Sprachnachricht gehen – und was soll ich sagen?" else "Klar. Was soll ich $n sagen?"
        }
        (Regex("^(?:du darfst|darfst du|du kannst) (?:jetzt |ab jetzt |auch )?([\\p{L}-]+) (?:selbst |alleine |allein |für mich )*(?:antworten|schreiben|zurückschreiben)$").find(lowW)
            ?: Regex("^antworte (?:ab jetzt |jetzt )?(?:selbst |du |für mich |alleine )+(?:auf |an |bei )?([\\p{L}-]+)$").find(lowW))?.let { m ->
            return Stil.grant(ctx, m.groupValues[1].replaceFirstChar { it.uppercase() })
        }
        Regex("^(?:antworte|schreib) ([\\p{L}-]+) nicht mehr(?: selbst)?$|^hör auf,? ([\\p{L}-]+) zu (?:antworten|schreiben)$").find(lowW)?.let { m ->
            return Stil.revoke(ctx, (m.groupValues[1].ifBlank { m.groupValues[2] }).replaceFirstChar { it.uppercase() })
        }
        if (Regex("\\b(?:stil[- ]?quiz|schreibstil[- ]?quiz|quiz (?:zu|über) meinem? (?:schreib)?stil)\\b").containsMatchIn(lowW)) {
            Bus.emit("open_page", JSONObject().put("page", "stil"))
            return "Mach ich auf: Welche Antwort ist von dir? Findest du unter Einstellungen → Leute → Schreibstil."
        }
        if (Termin.wants(text)) {
            think("kalender")
            val r = try { Termin.add(ctx, key, text) } catch (e: Groq.KeyError) { Termin.R(e.message ?: "Der Groq-Schlüssel stimmt nicht.", false) }
                catch (e: Exception) { Termin.R("Den Termin konnte ich gerade nicht eintragen (${e.message ?: "unbekannter Fehler"}).", false) }
            termin = r
            if (r.ok && !fromPc) Link.remindPc(ctx, r.title, r.remindAt)   // der PC erinnert dich auch, wenn er läuft
            history.put(JSONObject().put("role", "user").put("content", text))
            history.put(JSONObject().put("role", "assistant").put("content", r.say))
            return r.say
        }
        Themen.note(ctx, "frage", text)
        Thread({ Themen.refresh(ctx, key) }, "jarvis-themen").start()
        Thread({ Interests.refreshGenres(ctx, key) }, "jarvis-genres").start()   // höchstens einmal am Tag
        Humor.react(ctx, text, history)   // hat er über den letzten Spruch gelacht – oder fand er ihn doof?
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
                "vergleich" -> { onStatus?.invoke("Jarvis vergleicht …"); think("web")
                    val items = a.optJSONArray("items")?.let { arr -> (0 until arr.length()).map { arr.optString(it) } } ?: emptyList()
                    Cards.compare(ctx, key, items, a.optString("frage").ifBlank { text }) }
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
                "screen" -> { onStatus?.invoke("Jarvis schaut hin …"); think("web")
                    if (a.optString("geraet") == "pc") {
                        val r = try { Link.command(ctx, JSONObject().put("type", "screen").put("frage", a.optString("frage").ifBlank { text }), 45_000) } catch (_: Exception) { null }
                        r?.optString("text")?.takeIf { it.isNotBlank() } ?: "Der PC antwortet gerade nicht."
                    } else try { Vision.screen(ctx, a.optString("frage").ifBlank { text }) } catch (e: Exception) { "Das Anschauen ging nicht." } }
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
