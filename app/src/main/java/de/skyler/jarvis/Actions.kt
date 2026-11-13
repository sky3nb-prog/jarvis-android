package de.skyler.jarvis

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.os.SystemClock
import android.provider.AlarmClock
import android.provider.ContactsContract
import android.provider.Settings
import android.view.KeyEvent
import androidx.core.content.ContextCompat
import org.json.JSONObject

/** Was Jarvis auf dem Handy tun kann. Jede Aktion gibt einen kurzen Text zurück (für die Antwort). */
class Actions(private val ctx: Context) {

    fun run(a: JSONObject): String? = try {
        when (a.optString("action")) {
            "say" -> null
            "open_app" -> openApp(a.optString("name"))
            "media" -> media(a.optString("key"))
            "volume" -> volume(a.optString("what"), a.optInt("value", -1))
            "alarm" -> alarm(a.optInt("hour", -1), a.optInt("minute", 0), a.optString("label"))
            "timer" -> timer(a.optInt("seconds", 0), a.optString("label"))
            "navigate" -> navigate(a.optString("to"), a.optString("mode", "d"))
            "call" -> call(a.optString("who"))
            "pc" -> pc(a.optString("text"))
            "whatsapp" -> whatsapp(a.optString("to"), a.optString("text"), a.optBoolean("jarvis"))
            "youtube" -> start(Intent(Intent.ACTION_SEARCH).setPackage("com.google.android.youtube")
                .putExtra("query", a.optString("query")), "YouTube sucht nach ${a.optString("query")}.")
                ?: url("https://www.youtube.com/results?search_query=" + Uri.encode(a.optString("query")))
            "spotify" -> start(Intent(Intent.ACTION_VIEW, Uri.parse("spotify:search:" + Uri.encode(a.optString("query")))),
                "Spotify sucht.")
            "url" -> url(a.optString("url"))
            "search" -> url("https://www.google.com/search?q=" + Uri.encode(a.optString("query")))
            "torch" -> torch(a.optBoolean("on", true))
            "settings" -> settings(a.optString("what"))
            "calendar_add" -> Cal.add(ctx, a)
            "calendar_list" -> Cal.list(ctx, a.optString("from"), a.optInt("days", 1))
            "calendar_delete" -> Cal.delete(ctx, a.optString("title"), a.optString("date"))
            "jarvis_volume" -> jarvisVolume(a.optString("what"), a.optInt("value", -1))
            "remember" -> Memory.remember(ctx, a.optString("text"), a.optString("date"))
            "forget" -> Memory.forget(ctx, a.optString("text"))
            "mood" -> { Memory.mood(ctx, a.optString("text")); null }
            "sms" -> sms(a.optString("to"), a.optString("text"))
            "ort_erinnerung" -> Alltag.addPlaceReminder(ctx, a.optString("ort"), a.optString("text"))
            "briefing" -> Alltag.briefingNow(ctx, a.optString("tag") == "morgen")
            "rueckblick" -> Alltag.weekText(ctx) ?: "Für den Rückblick brauche ich den Groq-Schlüssel."
            "youtube_neu" -> Interests.newVideos(ctx, a.optInt("days", 7).coerceIn(1, 30))
            else -> null
        }
    } catch (e: Exception) {
        "Das hat nicht geklappt: ${e.message}"
    }

    private fun start(i: Intent, ok: String): String? = try {
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        ctx.startActivity(i); ok
    } catch (_: Exception) { null }

    private fun url(u: String): String {
        val uri = Uri.parse(if (u.startsWith("http")) u else "https://$u")
        return start(Intent(Intent.ACTION_VIEW, uri), "Ist offen.") ?: "Das kann ich nicht öffnen."
    }

    // --- Apps ---
    private fun norm(s: String) = s.lowercase().replace(Regex("[^a-z0-9äöüß]"), "")

    fun openApp(name: String): String {
        val pm = ctx.packageManager
        val want = norm(name)
        if (want.isEmpty()) return "Welche App?"
        val apps = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
        val best = apps.map { it to norm(it.loadLabel(pm).toString()) }
            .sortedBy { (_, label) -> when { label == want -> 0; label.startsWith(want) -> 1; label.contains(want) -> 2; want.contains(label) && label.length > 2 -> 3; else -> 9 } }
            .firstOrNull()
        if (best == null || run { val l = best.second; !(l == want || l.startsWith(want) || l.contains(want) || (want.contains(l) && l.length > 2)) })
            return "Die App $name habe ich nicht gefunden."
        val launch = pm.getLaunchIntentForPackage(best.first.activityInfo.packageName) ?: return "$name lässt sich nicht öffnen."
        return start(launch, "${best.first.loadLabel(pm)} ist offen.") ?: "$name lässt sich nicht öffnen."
    }

    // --- Musik und Lautstärke ---
    private fun media(key: String): String {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val code = when (key) {
            "next" -> KeyEvent.KEYCODE_MEDIA_NEXT
            "previous" -> KeyEvent.KEYCODE_MEDIA_PREVIOUS
            "pause" -> KeyEvent.KEYCODE_MEDIA_PAUSE
            "play" -> KeyEvent.KEYCODE_MEDIA_PLAY
            else -> KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
        }
        val t = SystemClock.uptimeMillis()
        am.dispatchMediaKeyEvent(KeyEvent(t, t, KeyEvent.ACTION_DOWN, code, 0))
        am.dispatchMediaKeyEvent(KeyEvent(t, t, KeyEvent.ACTION_UP, code, 0))
        return when (key) { "next" -> "Nächster Titel."; "previous" -> "Zurück."; "pause" -> "Pause."; else -> "Okay." }
    }

    private fun volume(what: String, value: Int): String {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val s = AudioManager.STREAM_MUSIC
        val max = am.getStreamMaxVolume(s)
        when (what) {
            "up" -> repeat(2) { am.adjustStreamVolume(s, AudioManager.ADJUST_RAISE, 0) }
            "down" -> repeat(2) { am.adjustStreamVolume(s, AudioManager.ADJUST_LOWER, 0) }
            "mute" -> am.adjustStreamVolume(s, AudioManager.ADJUST_MUTE, 0)
            "unmute" -> am.adjustStreamVolume(s, AudioManager.ADJUST_UNMUTE, 0)
            "set" -> if (value in 0..100) am.setStreamVolume(s, (max * value / 100.0).toInt(), 0)
        }
        return "Lautstärke ${am.getStreamVolume(s) * 100 / maxOf(1, max)} Prozent."
    }

    /** Eigene Lautstärke von Jarvis (unabhängig von der Musik). */
    private fun jarvisVolume(what: String, value: Int): String {
        val p = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        var v = p.getInt("jarvis_volume", 70)
        v = when (what) {
            "up" -> v + 15
            "down" -> v - 15
            "max" -> 100
            "set" -> if (value in 0..100) value else v
            else -> v
        }.coerceIn(10, 100)
        p.edit().putInt("jarvis_volume", v).apply()
        return "Meine Stimme steht jetzt auf $v Prozent."
    }

    private fun sms(to: String, text: String): String {
        val nr = number(to) ?: return "$to finde ich nicht in deinen Kontakten."
        val i = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + Uri.encode(nr))).putExtra("sms_body", text)
        return start(i, "Die SMS an $to ist vorbereitet, tipp nur noch auf Senden.") ?: "SMS geht gerade nicht."
    }

    // --- Wecker, Timer ---
    private fun alarm(h: Int, m: Int, label: String): String {
        if (h !in 0..23) return "Für wann soll der Wecker sein?"
        val i = Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR, h).putExtra(AlarmClock.EXTRA_MINUTES, m)
            .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
        if (label.isNotBlank()) i.putExtra(AlarmClock.EXTRA_MESSAGE, label)
        return start(i, "Wecker auf %d:%02d gestellt.".format(h, m)) ?: "Ich finde keine Wecker-App."
    }

    private fun timer(sec: Int, label: String): String {
        if (sec <= 0) return "Wie lange?"
        val i = Intent(AlarmClock.ACTION_SET_TIMER).putExtra(AlarmClock.EXTRA_LENGTH, sec).putExtra(AlarmClock.EXTRA_SKIP_UI, true)
        if (label.isNotBlank()) i.putExtra(AlarmClock.EXTRA_MESSAGE, label)
        val min = sec / 60
        return start(i, if (min >= 1) "Timer für $min Minuten läuft." else "Timer für $sec Sekunden läuft.") ?: "Ich finde keine Uhr-App."
    }

    // --- Navigation ---
    private fun navigate(to: String, mode: String): String {
        val m = when (mode) { "b", "bike", "fahrrad" -> "b"; "w", "walk", "fuss" -> "w"; else -> "d" }
        return start(Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=" + Uri.encode(to) + "&mode=$m")),
            "Navigation nach $to gestartet.") ?: url("https://www.google.com/maps/dir/?api=1&destination=" + Uri.encode(to))
    }

    // --- Kontakte, Anrufen, WhatsApp ---
    @SuppressLint("Range")
    fun number(who: String): String? {
        if (who.any { it.isDigit() } && who.count { it.isDigit() } >= 5) return who.filter { it.isDigit() || it == '+' }
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) return null
        val uri = ContactsContract.CommonDataKinds.Phone.CONTENT_URI
        val sel = "${ContactsContract.Contacts.DISPLAY_NAME} LIKE ?"
        ctx.contentResolver.query(uri, arrayOf(ContactsContract.CommonDataKinds.Phone.NUMBER), sel, arrayOf("%$who%"), null)?.use { c ->
            if (c.moveToFirst()) return c.getString(0)
        }
        // ungefähr passend (z. B. "Lukas" für "Lucas"): ähnlichsten Namen nehmen
        val want = Wake.norm(who)
        var best: String? = null; var bestD = 99
        ctx.contentResolver.query(uri, arrayOf(ContactsContract.Contacts.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER),
            null, null, null)?.use { c ->
            while (c.moveToNext()) {
                val name = c.getString(0) ?: continue
                val parts = listOf(name) + name.split(" ")
                val d = parts.minOf { Wake.dist(Wake.norm(it), want) }
                if (d < bestD) { bestD = d; best = c.getString(1) }
            }
        }
        return if (bestD <= maxOf(1, want.length / 4)) best else null
    }

    private fun call(who: String): String {
        val nr = number(who) ?: return if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CONTACTS) !=
            PackageManager.PERMISSION_GRANTED) "Ich darf deine Kontakte noch nicht lesen. Erlaube es in der App unter Einstellungen."
            else "$who finde ich nicht in deinen Kontakten."
        val canCall = ContextCompat.checkSelfPermission(ctx, Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED
        val i = Intent(if (canCall) Intent.ACTION_CALL else Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(nr)))
        return start(i, "Ich rufe $who an.") ?: "Anrufen geht gerade nicht."
    }

    /**
     * Versandregeln: Antwort auf einen Chat mit offener Benachrichtigung -> über die Benachrichtigung (nichts geht auf).
     * Sonst: PC läuft -> WhatsApp über den PC. Unterwegs -> SMS (Nummer aus den Kontakten).
     * jarvis = "unter deinem Namen": beginnt mit "Hier ist Jarvis.", Antworten aus dem Chat werden angesagt.
     */
    private fun whatsapp(to: String, text0: String, jarvis: Boolean = false): String {
        val text = if (jarvis) "Hier ist Jarvis. " + text0.replace(Regex("^hier ist jarvis[.,!]?\\s*", RegexOption.IGNORE_CASE), "") else text0
        if (jarvis) Chats.watch(ctx, to, 24)
        if (Chats.reply(ctx, to, to, text)) return "Geschickt an $to: $text"
        try {
            if (Link.paired(ctx) && Link.pcOnline(ctx)) {
                val r = Link.command(ctx, JSONObject().put("type", "wa_send").put("to", to).put("text", text), 25_000)
                if (r?.optBoolean("ok") == true) return "Geschickt an $to, über WhatsApp am PC."
            }
        } catch (_: Exception) {}
        val sms = number(to)
        if (sms != null && Butler.sms(ctx, sms, text)) return "Ich habe $to eine SMS geschickt: $text"
        val nr = number(to)?.let { normNumber(it) }
        val uri = if (nr != null) "https://wa.me/$nr?text=" + Uri.encode(text) else "https://wa.me/?text=" + Uri.encode(text)
        val i = Intent(Intent.ACTION_VIEW, Uri.parse(uri)).setPackage("com.whatsapp")
        return (start(i, if (nr != null) "Die Nachricht an $to ist vorbereitet, tipp nur noch auf Senden."
            else "WhatsApp ist offen, such dir $to aus.") ?: "WhatsApp ist nicht installiert.")
    }

    private fun normNumber(n: String): String {
        var d = n.filter { it.isDigit() || it == '+' }
        if (d.startsWith("00")) d = d.drop(2) else if (d.startsWith("+")) d = d.drop(1) else if (d.startsWith("0")) d = "49" + d.drop(1)
        return d
    }

    // --- Taschenlampe, Einstellungen ---
    private fun torch(on: Boolean): String {
        val cm = ctx.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val id = cm.cameraIdList.firstOrNull() ?: return "Keine Lampe gefunden."
        cm.setTorchMode(id, on)
        return if (on) "Licht an." else "Licht aus."
    }

    private fun settings(what: String): String {
        val action = when (what) {
            "wifi" -> Settings.Panel.ACTION_WIFI
            "bluetooth" -> Settings.ACTION_BLUETOOTH_SETTINGS
            "internet", "mobile" -> Settings.Panel.ACTION_INTERNET_CONNECTIVITY
            "volume" -> Settings.Panel.ACTION_VOLUME
            "display", "brightness" -> Settings.ACTION_DISPLAY_SETTINGS
            "battery" -> Intent.ACTION_POWER_USAGE_SUMMARY
            else -> Settings.ACTION_SETTINGS
        }
        return start(Intent(action), "Hier sind die Einstellungen.") ?: "Die Einstellungen gehen gerade nicht auf."
    }

    /** Auftrag an den PC-Jarvis ("schick mir das Lied vom PC aufs Handy", "mach am PC Musik an"). */
    private fun pc(text: String): String {
        if (text.isBlank()) return "Was soll der PC machen?"
        if (!Link.paired(ctx)) return "Dein PC ist noch nicht gekoppelt."
        val r = try { Link.command(ctx, JSONObject().put("type", "text").put("text", text)) } catch (_: Exception) { null }
        return if (r == null) "Der PC antwortet gerade nicht." else "Hab's dem PC gesagt."
    }
}
