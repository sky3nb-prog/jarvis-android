package de.skyler.jarvis

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.camera2.CameraManager
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaMetadata
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.KeyEvent
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Das Handy vom PC aus steuern (Seite "Steuern" im PC-HUD):
 * status() = Akku, Klingelton, Lautstärken, was läuft, nächste Termine
 * ctl()    = Musik-Tasten, Lautstärke, Lautlos, Taschenlampe, Handy finden (klingelt laut)
 */
object PhoneCtl {
    @Volatile private var torchOn = false
    private var finder: MediaPlayer? = null
    private val main = Handler(Looper.getMainLooper())
    private val streams = mapOf("medien" to AudioManager.STREAM_MUSIC, "klingel" to AudioManager.STREAM_RING, "wecker" to AudioManager.STREAM_ALARM)

    @Volatile private var gesund = JSONObject()
    @Volatile private var gesundT = 0L

    fun status(ctx: Context): JSONObject {
        val o = JSONObject().put("ts", System.currentTimeMillis() / 1000).put("model", Build.MODEL ?: "Handy")
        try {   // Schlaf und Aktivität: der PC soll es wissen (nicht anzeigen), höchstens alle 10 Min. neu
            if (System.currentTimeMillis() - gesundT > 600_000L) {
                val g = JSONObject()
                Sleep.night(ctx, 0)?.let { g.put("schlaf", "Schlaf letzte Nacht: " + Sleep.text(it)) }
                if (Health.connected(ctx)) Health.day(ctx, 0)?.let { g.put("heute", "Heute: " + Health.text(it)) }
                Halte.summary(ctx).takeIf { it.isNotBlank() }?.let { g.put("halte", it) }
                Gassi.summary(ctx).takeIf { it.isNotBlank() }?.let { g.put("gassi", it) }
                Stimmung.prompt(ctx).takeIf { it.isNotBlank() }?.let { g.put("stimmung", it) }
                gesund = g; gesundT = System.currentTimeMillis()
            }
            if (gesund.length() > 0) o.put("gesund", gesund)
        } catch (_: Exception) {}
        try {
            val b = ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            if (b != null) {
                val lvl = b.getIntExtra(BatteryManager.EXTRA_LEVEL, -1); val sc = b.getIntExtra(BatteryManager.EXTRA_SCALE, 100)
                if (lvl >= 0) o.put("akku", lvl * 100 / maxOf(1, sc))
                o.put("laedt", b.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0)
            }
        } catch (_: Exception) {}
        try {
            val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            o.put("ringer", when (am.ringerMode) { AudioManager.RINGER_MODE_SILENT -> "lautlos"; AudioManager.RINGER_MODE_VIBRATE -> "vibration"; else -> "an" })
            val v = JSONObject()
            for ((k, s) in streams) v.put(k, am.getStreamVolume(s) * 100 / maxOf(1, am.getStreamMaxVolume(s)))
            o.put("vol", v)
        } catch (_: Exception) {}
        o.put("lampe", torchOn)
        playing(ctx)?.let { o.put("playing", it) }
        try {
            val now = System.currentTimeMillis()
            val evs = Cal.events(ctx, now - 30 * 60_000L, now + 8 * 86_400_000L).filter { it.begin >= now - 30 * 60_000L }.take(4)
            val de = Locale.GERMANY
            fun ds(t: Long) = Calendar.getInstance().apply { timeInMillis = t; set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0)
                set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }.timeInMillis
            val arr = JSONArray()
            for (e in evs) {
                val days = ((ds(e.begin) - ds(now) + 3600_000L) / 86_400_000L).toInt()
                val day = when (days) { 0 -> "heute"; 1 -> "morgen"; else -> SimpleDateFormat("EE d.M.", de).format(Date(e.begin)) }
                arr.put(JSONObject().put("when", day + if (e.allDay) "" else " " + SimpleDateFormat("HH:mm", de).format(Date(e.begin))).put("title", e.title))
            }
            o.put("termine", arr)
        } catch (_: Exception) {}
        return o
    }

    private fun playing(ctx: Context): JSONObject? = try {
        val m = ctx.getSystemService(Context.MEDIA_SESSION_SERVICE) as MediaSessionManager
        val list = m.getActiveSessions(ComponentName(ctx, MediaWatch::class.java))
        val c = list.firstOrNull { it.playbackState?.state == PlaybackState.STATE_PLAYING } ?: list.firstOrNull()
        val md = c?.metadata
        val title = md?.getString(MediaMetadata.METADATA_KEY_TITLE)
        if (c == null || title.isNullOrBlank()) null else {
            val pm = ctx.packageManager
            val app = try { pm.getApplicationLabel(pm.getApplicationInfo(c.packageName, 0)).toString() } catch (_: Exception) { c.packageName }
            JSONObject().put("title", title).put("artist", md.getString(MediaMetadata.METADATA_KEY_ARTIST) ?: "")
                .put("app", app).put("on", c.playbackState?.state == PlaybackState.STATE_PLAYING)
        }
    } catch (_: Exception) { null }   // ohne Zugriff auf Mitteilungen sieht die App nicht, was läuft

    fun ctl(ctx: Context, c: JSONObject): String {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        return when (c.optString("what")) {
            "media" -> {
                val code = when (c.optString("key")) { "next" -> KeyEvent.KEYCODE_MEDIA_NEXT; "previous" -> KeyEvent.KEYCODE_MEDIA_PREVIOUS; else -> KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE }
                val t = SystemClock.uptimeMillis()
                am.dispatchMediaKeyEvent(KeyEvent(t, t, KeyEvent.ACTION_DOWN, code, 0))
                am.dispatchMediaKeyEvent(KeyEvent(t, t, KeyEvent.ACTION_UP, code, 0))
                when (c.optString("key")) { "next" -> "Nächster Titel am Handy."; "previous" -> "Zurück am Handy."; else -> "Play/Pause am Handy." }
            }
            "vol" -> {
                val s = streams[c.optString("stream")] ?: return "Diese Lautstärke kenne ich nicht."
                val max = am.getStreamMaxVolume(s)
                try {
                    am.setStreamVolume(s, (c.optDouble("level", .5).coerceIn(0.0, 1.0) * max).toInt(), 0)
                    "Lautstärke am Handy geändert."
                } catch (_: SecurityException) { "Bei „Nicht stören“ darf ich den Klingelton nicht ändern." }
            }
            "lautlos" -> try {
                if (am.ringerMode == AudioManager.RINGER_MODE_NORMAL) { am.ringerMode = AudioManager.RINGER_MODE_VIBRATE; "Handy ist auf Vibration." }
                else { am.ringerMode = AudioManager.RINGER_MODE_NORMAL; "Klingelton am Handy ist wieder an." }
            } catch (_: SecurityException) { "Bei „Nicht stören“ darf ich das nicht umstellen." }
            "lampe" -> try {
                val cm = ctx.getSystemService(Context.CAMERA_SERVICE) as CameraManager
                val id = cm.cameraIdList.firstOrNull() ?: return "Keine Lampe gefunden."
                torchOn = !torchOn; cm.setTorchMode(id, torchOn)
                if (torchOn) "Lampe am Handy an." else "Lampe am Handy aus."
            } catch (_: Exception) { "Die Lampe lässt sich gerade nicht schalten." }
            "finden" -> { find(ctx); "Dein Handy klingelt jetzt 20 Sekunden lang." }
            "finden_stop" -> { stopFind(); "Klingeln gestoppt." }
            "modus" -> { Modes.fromPc = true; try { Modes.set(ctx, c.optString("name")) } finally { Modes.fromPc = false } }
            else -> "Diesen Befehl kenne ich nicht."
        }
    }

    /** Klingelt laut über den Wecker-Kanal (auch wenn das Handy lautlos ist). */
    private fun find(ctx: Context) {
        main.post {
            stopFind()
            try {
                val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                val old = am.getStreamVolume(AudioManager.STREAM_ALARM)
                am.setStreamVolume(AudioManager.STREAM_ALARM, am.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0)
                val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
                finder = MediaPlayer().apply {
                    setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).build())
                    setDataSource(ctx, uri); isLooping = true; prepare(); start()
                }
                main.postDelayed({ stopFind(); try { am.setStreamVolume(AudioManager.STREAM_ALARM, old, 0) } catch (_: Exception) {} }, 20_000)
            } catch (_: Exception) {}
        }
    }

    private fun stopFind() {
        try { finder?.stop(); finder?.release() } catch (_: Exception) {}
        finder = null
    }
}
