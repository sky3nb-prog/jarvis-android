package de.skyler.jarvis

import android.app.AlarmManager
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.provider.Settings
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Routinen per Sprache (Handy-Teil):
 *  - Gaming-Modus: Nicht stören an (Anruf-Butler drückt Anrufe aus den Kontakten weg und schreibt "Kann gerade nicht"), PC: Discord "Gurken".
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

    /** Befehlstext aus dem Modi-Raster ("fokus modus", "gute nacht" …) -> Modus setzen. */
    fun fromCmd(ctx: Context, t: String): String {
        val l = t.lowercase()
        return set(ctx, when {
            l.startsWith("fokus") -> if (l.contains("ohne")) "fokus ohne" else "fokus"
            l.startsWith("gaming") -> "gaming"; l.startsWith("chill") -> "chill"; l.startsWith("kino") -> "kino"
            l.startsWith("schul") -> "schule"; l.startsWith("gute nacht") -> "nacht"; else -> "aus" })
    }

    fun set(ctx: Context, name: String): String {
        val n = name.lowercase()
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        if (!n.startsWith("fok")) clearFokus(ctx)
        return when {
            n.startsWith("fok") || n.startsWith("lern") -> {
                val ok = dnd(ctx, true); prefs(ctx).edit().putString("modus", "fokus").apply()
                clearFokus(ctx)
                if (Link.paired(ctx) && !fromPc && Link.pcOnline(ctx)) toPc(ctx, if (n.contains("ohne")) "fokus modus ohne musik vom handy" else "fokus modus vom handy")
                else if (!fromPc) {   // PC aus: Pausen selbst ansagen (4 Runden 25/5)
                    val ids = mutableListOf<String>(); val t0 = System.currentTimeMillis()
                    for (r in 1..4) {
                        ids.add(Remind.add(ctx, "Fokus: ${r * 25} Minuten geschafft – 5 Minuten Pause.", t0 + (r * 30 - 5) * 60_000L, kind = "fokus").optString("id"))
                        if (r < 4) ids.add(Remind.add(ctx, "Pause vorbei – weiter geht's.", t0 + r * 30 * 60_000L, kind = "fokus").optString("id"))
                    }
                    prefs(ctx).edit().putString("fokus_ids", ids.joinToString(",")).apply()
                }
                "Fokus-Modus an: 25 Minuten lernen, dann 5 Minuten Pause." + if (ok) " Nicht stören ist an." else " Erlaub mir bitte einmal „Nicht stören“."
            }
            n.startsWith("chill") -> {
                prefs(ctx).edit().putString("modus", "chill").apply(); dnd(ctx, false)
                toPc(ctx, "chill modus vom handy")
                "Chill-Modus. Lehn dich zurück."
            }
            n.startsWith("kino") || n.startsWith("film") -> {
                prefs(ctx).edit().putString("modus", "kino").apply()
                try { am.ringerMode = AudioManager.RINGER_MODE_SILENT } catch (_: Exception) { try { am.ringerMode = AudioManager.RINGER_MODE_VIBRATE } catch (_: Exception) {} }
                toPc(ctx, "kino modus vom handy")
                "Kino-Modus: Handy ist lautlos, ich sammle alles für später."
            }
            n.startsWith("gam") || n.startsWith("zock") -> {
                val ok = dnd(ctx, true); prefs(ctx).edit().putString("modus", "gaming").apply()
                if (Link.paired(ctx) && !fromPc) Thread { try { Link.command(ctx, JSONObject().put("type", "text").put("text", "gaming modus vom handy"), 15_000) } catch (_: Exception) {} }.start()
                "Gaming-Modus an." + if (ok) " Nicht stören ist an – Anrufe drücke ich weg und sag Bescheid, dass du zockst." else " Erlaub mir bitte einmal „Nicht stören“ – ich hab die Einstellung geöffnet."
            }
            n.startsWith("schul") -> {
                prefs(ctx).edit().putString("modus", "schule").apply()
                toPc(ctx, "schulmodus vom handy")
                try { am.ringerMode = AudioManager.RINGER_MODE_SILENT } catch (_: Exception) { try { am.ringerMode = AudioManager.RINGER_MODE_VIBRATE } catch (_: Exception) {} }
                "Schulmodus an: Handy ist leise, Anrufe drücke ich weg – nur deine wichtigen Leute kommen durch."
            }
            n.startsWith("nacht") || n.startsWith("gute") -> {
                val ok = dnd(ctx, true); prefs(ctx).edit().putString("modus", "nacht").apply()
                val alarm = (ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager).nextAlarmClock?.triggerTime
                val c = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, 1); set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0) }
                val evs = try { Cal.events(ctx, c.timeInMillis, c.timeInMillis + 86_400_000L).distinctBy { it.id to it.begin }.take(3) } catch (_: Exception) { emptyList() }
                val wake = if (alarm != null && alarm - System.currentTimeMillis() < 20 * 3_600_000L)
                    "Dein Wecker klingelt um ${SimpleDateFormat("H:mm", de).format(Date(alarm))}" + Sleep.dur((alarm - System.currentTimeMillis()) / 60_000L).let { " – noch $it." }
                    else "Für morgen ist kein Wecker gestellt."
                val ter = if (evs.isEmpty()) "Morgen hast du keine Termine." else "Morgen: " + evs.joinToString(", ") { (if (it.allDay) "" else SimpleDateFormat("H:mm", de).format(Date(it.begin)) + " ") + it.title } + "."
                if (Link.paired(ctx) && !fromPc) Thread { try { if (Link.pcOnline(ctx)) Link.command(ctx, JSONObject().put("type", "weg"), 20_000) } catch (_: Exception) {} }.start()
                "Gute Nacht. $wake $ter" + (if (ok) " Nicht stören ist an." else "")
            }
            else -> {   // aus / guten Morgen
                val was = current(ctx)
                dnd(ctx, false); prefs(ctx).edit().putString("modus", "").apply()
                if (was.isNotBlank() && was != "nacht") toPc(ctx, "modus aus vom handy")
                try { am.ringerMode = AudioManager.RINGER_MODE_NORMAL } catch (_: Exception) {}
                "Alles wieder normal: Klingelton an, Nicht stören aus."
            }
        }
    }

    @Volatile var fromPc = false
}
