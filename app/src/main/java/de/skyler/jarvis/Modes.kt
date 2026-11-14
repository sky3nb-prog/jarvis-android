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

    fun set(ctx: Context, name: String): String {
        val n = name.lowercase()
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        return when {
            n.startsWith("gam") || n.startsWith("zock") -> {
                val ok = dnd(ctx, true); prefs(ctx).edit().putString("modus", "gaming").apply()
                if (Link.paired(ctx) && !fromPc) Thread { try { Link.command(ctx, JSONObject().put("type", "text").put("text", "gaming modus vom handy"), 15_000) } catch (_: Exception) {} }.start()
                "Gaming-Modus an." + if (ok) " Nicht stören ist an – Anrufe drücke ich weg und sag Bescheid, dass du zockst." else " Erlaub mir bitte einmal „Nicht stören“ – ich hab die Einstellung geöffnet."
            }
            n.startsWith("schul") -> {
                prefs(ctx).edit().putString("modus", "schule").apply()
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
                dnd(ctx, false); prefs(ctx).edit().putString("modus", "").apply()
                try { am.ringerMode = AudioManager.RINGER_MODE_NORMAL } catch (_: Exception) {}
                "Alles wieder normal: Klingelton an, Nicht stören aus."
            }
        }
    }

    @Volatile var fromPc = false
}
