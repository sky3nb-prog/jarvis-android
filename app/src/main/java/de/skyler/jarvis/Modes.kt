package de.skyler.jarvis

import android.app.AlarmManager
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Routinen per Sprache (Handy-Teil):
 *  - Gaming-Modus: Nicht stören an (Anruf-Butler drückt Anrufe aus den Kontakten weg und schreibt "Kann gerade nicht"), PC: Discord-Sprachkanal.
 *  - Schulmodus: Handy leise (Vibration aus), Anrufe wegdrücken – nur wichtige Leute kommen durch.
 *  - Gute Nacht: Nicht stören (Nachtmodus für Anrufe), Wecker prüfen, Termine von morgen, PC speichert und fährt herunter.
 *  - "Modus aus" / "Guten Morgen": alles wieder normal.
 */
object Modes {
    private val de = Locale.GERMANY
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun current(ctx: Context): String = prefs(ctx).getString("modus", "") ?: ""

    private fun dnd(ctx: Context, on: Boolean): Boolean {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (!nm.isNotificationPolicyAccessGranted) {
            try { ctx.startActivity(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } catch (_: Exception) {}
            return false
        }
        nm.setInterruptionFilter(if (on) NotificationManager.INTERRUPTION_FILTER_PRIORITY else NotificationManager.INTERRUPTION_FILTER_ALL)
        return true
    }

    private fun toPc(ctx: Context, text: String) {
        if (Link.paired(ctx) && !fromPc) Thread { try { Link.command(ctx, JSONObject().put("type", "text").put("text", text), 15_000) } catch (_: Exception) {} }.start()
    }
    private fun clearFokus(ctx: Context) {
        (prefs(ctx).getString("fokus_ids", "") ?: "").split(",").filter { it.isNotBlank() }.forEach { try { Remind.done(ctx, it) } catch (_: Exception) {} }
        prefs(ctx).edit().remove("fokus_ids").apply()
    }

    // --- Einstellbare Modi (Kopie vom PC bzw. hier bearbeitet; leer = Standard) -------------------------------
    private val DEF = """[
      {"id":"fokus","n":"Fokus","i":"◎","h":200,"d":"Lernen ohne Ablenkung","handy":"dnd","sammeln":true,"still":true,"musik":"lofi","discord":"","apps":"","pomo":true,"lern":25,"pause":5,"aus":false},
      {"id":"gaming","n":"Gaming","i":"▶","h":280,"d":"Discord an, Anrufe weg","handy":"dnd","sammeln":false,"still":false,"musik":"","discord":"","apps":"","pomo":false,"lern":25,"pause":5,"aus":false},
      {"id":"chill","n":"Chill","i":"♪","h":160,"d":"Musik an, entspannt","handy":"normal","sammeln":false,"still":false,"musik":"deezer","discord":"","apps":"","pomo":false,"lern":25,"pause":5,"aus":false},
      {"id":"kino","n":"Kino","i":"◐","h":320,"d":"Alles leise, nichts stört","handy":"lautlos","sammeln":true,"still":true,"musik":"","discord":"","apps":"","pomo":false,"lern":25,"pause":5,"aus":false},
      {"id":"schule","n":"Schule","i":"▦","h":45,"d":"Alles stumm, nur Uhr","handy":"stumm","sammeln":false,"still":true,"musik":"","discord":"","apps":"","pomo":false,"lern":25,"pause":5,"aus":false},
      {"id":"nacht","n":"Gute Nacht","i":"☾","h":230,"d":"Handy still, PC aus","handy":"dnd","sammeln":true,"still":true,"musik":"","discord":"","apps":"","pomo":false,"lern":25,"pause":5,"aus":true}]"""
    /** Schulmodus (bzw. jeder Modus mit "Alles stumm"): Jarvis hört nicht zu, spricht nicht, meldet sich nur per Nachricht (Uhr). */
    fun silent(ctx: Context): Boolean {
        val id = current(ctx)
        return id.isNotBlank() && find(ctx, id)?.optString("handy") == "stumm"
    }

    // Lautstärken, die "Alles stumm" auf 0 setzt (Wecker bleibt!) – vorher gemerkt und danach zurückgestellt
    private val STREAMS = intArrayOf(AudioManager.STREAM_MUSIC, AudioManager.STREAM_RING, AudioManager.STREAM_NOTIFICATION,
        AudioManager.STREAM_SYSTEM, 10 /* STREAM_ACCESSIBILITY */, 11 /* STREAM_ASSISTANT (KI-Assistent) */)

    private fun muteAll(ctx: Context) {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        if (!prefs(ctx).contains("vol_backup")) {
            val b = JSONObject()
            STREAMS.forEach { s -> try { b.put(s.toString(), am.getStreamVolume(s)) } catch (_: Exception) {} }
            prefs(ctx).edit().putString("vol_backup", b.toString()).apply()
        }
        dnd(ctx, true)
        STREAMS.forEach { s -> try { am.setStreamVolume(s, 0, 0) } catch (_: Exception) {} }
        try { am.ringerMode = AudioManager.RINGER_MODE_SILENT } catch (_: Exception) {}
    }

    private fun unmuteAll(ctx: Context) {
        val raw = prefs(ctx).getString("vol_backup", null) ?: return
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        try { am.ringerMode = AudioManager.RINGER_MODE_NORMAL } catch (_: Exception) {}
        try { val b = JSONObject(raw); b.keys().forEach { k -> try { am.setStreamVolume(k.toInt(), b.optInt(k), 0) } catch (_: Exception) {} } } catch (_: Exception) {}
        prefs(ctx).edit().remove("vol_backup").apply()
    }

    private fun jarvisRefresh(ctx: Context) {
        try { if (JarvisService.running) JarvisService.start(ctx, JarvisService.ACTION_RELOAD) } catch (_: Exception) {}
    }

    fun cfg(ctx: Context): JSONArray {
        val a = try { JSONArray(prefs(ctx).getString("modi_cfg", "") ?: "").takeIf { it.length() > 0 } } catch (_: Exception) { null } ?: return JSONArray(DEF)
        if (!prefs(ctx).getBoolean("schule_stumm_v1", false)) {   // Wunsch 16.11.: Schulmodus = alles stumm, Jarvis aus, nur Uhr
            for (i in 0 until a.length()) a.optJSONObject(i)?.takeIf { it.optString("id") == "schule" }?.apply { put("handy", "stumm"); put("still", true); put("d", "Alles stumm, nur Uhr") }
            prefs(ctx).edit().putBoolean("schule_stumm_v1", true).putString("modi_cfg", a.toString()).apply()
        }
        return a
    }
    fun setCfg(ctx: Context, a: JSONArray, toPc: Boolean) {
        prefs(ctx).edit().putString("modi_cfg", if (a.length() == 0) "" else a.toString()).apply()
        if (toPc && Link.paired(ctx)) Thread { try { Link.command(ctx, JSONObject().put("type", "modi_cfg").put("cfg", a), 15_000) } catch (_: Exception) {} }.start()
    }
    private fun find(ctx: Context, id: String): JSONObject? { val a = cfg(ctx); return (0 until a.length()).mapNotNull { a.optJSONObject(it) }.firstOrNull { it.optString("id") == id } }

    /** Befehlstext aus dem Modi-Raster ("fokus modus", "gute nacht", "Zeichnen modus" …) -> Modus setzen. */
    fun fromCmd(ctx: Context, t: String): String {
        val l = t.lowercase()
        val a = cfg(ctx)
        val custom = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.firstOrNull { l.startsWith(it.optString("n").lowercase() + " modus") }
        return set(ctx, when {
            l.startsWith("fokus") -> "fokus"; l.startsWith("gaming") -> "gaming"; l.startsWith("chill") -> "chill"; l.startsWith("kino") -> "kino"
            l.startsWith("schul") -> "schule"; l.startsWith("gute nacht") -> "nacht"; custom != null -> custom.optString("id"); else -> "aus" })
    }

    private fun handy(ctx: Context, how: String): Boolean {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        return when (how) {
            "stumm" -> { muteAll(ctx); true }
            "dnd" -> dnd(ctx, true)
            "lautlos" -> { try { am.ringerMode = AudioManager.RINGER_MODE_SILENT } catch (_: Exception) { try { am.ringerMode = AudioManager.RINGER_MODE_VIBRATE } catch (_: Exception) {} }; true }
            "normal" -> { dnd(ctx, false); try { am.ringerMode = AudioManager.RINGER_MODE_NORMAL } catch (_: Exception) {}; true }
            else -> true
        }
    }

    /** name = Modus-Kennung (auch alte Wörter wie "zocken", "gute nacht"); handyOverride kommt vom PC mit. */
    fun set(ctx: Context, name: String, handyOverride: String? = null): String {
        val n = name.lowercase()
        val id = when {
            n.startsWith("fok") || n.startsWith("lern") -> "fokus"; n.startsWith("gam") || n.startsWith("zock") -> "gaming"
            n.startsWith("chill") -> "chill"; n.startsWith("kino") || n.startsWith("film") -> "kino"; n.startsWith("schul") -> "schule"
            n.startsWith("nacht") || n.startsWith("gute") -> "nacht"; n == "aus" || n.startsWith("normal") || n.startsWith("morgen") -> "aus"
            else -> n
        }
        val m = if (id == "aus") null else find(ctx, id)
        clearFokus(ctx)
        if (m?.optString("handy") != "stumm") unmuteAll(ctx)   // vorher „Alles stumm“: Lautstärken zurück
        if (m == null) {   // aus / guten Morgen
            val was = current(ctx)
            handy(ctx, "normal"); prefs(ctx).edit().putString("modus", "").apply(); jarvisRefresh(ctx)
            if (was.isNotBlank() && was != "nacht") toPc(ctx, "modus aus vom handy")
            return "Alles wieder normal: Klingelton an, Nicht stören aus."
        }
        prefs(ctx).edit().putString("modus", id).apply()
        val how = if (m.optString("handy") == "stumm") "stumm" else (handyOverride ?: m.optString("handy", "normal"))
        jarvisRefresh(ctx)
        val ok = handy(ctx, how)
        val label = m.optString("n", id)
        if (id == "nacht") {
            val alarm = (ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager).nextAlarmClock?.triggerTime
            val c = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, 1); set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0) }
            val evs = try { Cal.events(ctx, c.timeInMillis, c.timeInMillis + 86_400_000L).distinctBy { it.id to it.begin }.take(3) } catch (_: Exception) { emptyList() }
            val wake = if (alarm != null && alarm - System.currentTimeMillis() < 20 * 3_600_000L)
                "Dein Wecker klingelt um ${SimpleDateFormat("H:mm", de).format(Date(alarm))}" + Sleep.dur((alarm - System.currentTimeMillis()) / 60_000L).let { " – noch $it." }
                else "Für morgen ist kein Wecker gestellt."
            val ter = if (evs.isEmpty()) "Morgen hast du keine Termine." else "Morgen: " + evs.joinToString(", ") { (if (it.allDay) "" else SimpleDateFormat("H:mm", de).format(Date(it.begin)) + " ") + it.title } + "."
            if (Link.paired(ctx) && !fromPc) Thread { try { if (Link.pcOnline(ctx)) Link.command(ctx, JSONObject().put("type", "text").put("text", "gute nacht vom handy"), 20_000) } catch (_: Exception) {} }.start()
            return "Gute Nacht. $wake $ter" + (if (how == "dnd" && ok) " Nicht stören ist an." else "")
        }
        val pcOn = Link.paired(ctx) && Link.pcOnline(ctx)
        if (!fromPc) toPc(ctx, when (id) { "fokus" -> "fokus modus vom handy"; "gaming" -> "gaming modus vom handy"; "schule" -> "schulmodus vom handy"; else -> "${label.lowercase()} modus vom handy" })
        if (!fromPc && !pcOn && m.optBoolean("pomo")) {   // PC aus: Pausen selbst ansagen (4 Runden)
            val lern = m.optInt("lern", 25); val pause = m.optInt("pause", 5)
            val ids = mutableListOf<String>(); val t0 = System.currentTimeMillis()
            for (r in 1..4) {
                ids.add(Remind.add(ctx, "$label: ${r * lern} Minuten geschafft – $pause Minuten Pause.", t0 + (r * (lern + pause) - pause) * 60_000L, kind = "fokus").optString("id"))
                if (r < 4) ids.add(Remind.add(ctx, "Pause vorbei – weiter geht's.", t0 + r * (lern + pause) * 60_000L, kind = "fokus").optString("id"))
            }
            prefs(ctx).edit().putString("fokus_ids", ids.joinToString(",")).apply()
        }
        return "$label-Modus an." + (if (m.optBoolean("pomo")) " ${m.optInt("lern", 25)} Minuten konzentriert, dann ${m.optInt("pause", 5)} Minuten Pause." else "") +
            when (how) { "dnd" -> if (ok) " Nicht stören ist an." else " Erlaub mir bitte einmal „Nicht stören“ – ich hab die Einstellung geöffnet."; "lautlos" -> " Handy ist lautlos."
                "stumm" -> " Alles ist stumm, ich höre nicht zu und melde mich nur per Nachricht auf der Uhr. Wecker bleiben an."; else -> "" }
    }

    @Volatile var fromPc = false
}
