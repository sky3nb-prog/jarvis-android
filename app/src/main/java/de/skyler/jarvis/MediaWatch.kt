package de.skyler.jarvis

import android.content.ComponentName
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.service.notification.NotificationListenerService

/**
 * Merkt sich, was du auf dem Handy schaust und hörst (YouTube, Spotify, Deezer, YouTube Music …):
 * Titel und Kanal bzw. Künstler aus der "Läuft gerade"-Anzeige von Android. Daraus lernt Jarvis deine Interessen.
 * Braucht einmal "Benachrichtigungszugriff" (Einstellungen). Gespeichert wird nur auf dem Handy.
 */
class MediaWatch : NotificationListenerService() {
    private var msm: MediaSessionManager? = null
    private val controllers = HashMap<String, MediaController>()
    private val callbacks = HashMap<String, MediaController.Callback>()

    private val sessionsListener = MediaSessionManager.OnActiveSessionsChangedListener { list -> attach(list ?: emptyList()) }

    override fun onListenerConnected() {
        super.onListenerConnected()
        try {
            val m = getSystemService(MEDIA_SESSION_SERVICE) as MediaSessionManager
            msm = m
            val comp = ComponentName(this, MediaWatch::class.java)
            m.addOnActiveSessionsChangedListener(sessionsListener, comp)
            attach(m.getActiveSessions(comp))
        } catch (_: Exception) {}
    }

    override fun onListenerDisconnected() {
        try { msm?.removeOnActiveSessionsChangedListener(sessionsListener) } catch (_: Exception) {}
        for ((k, c) in controllers) callbacks[k]?.let { try { c.unregisterCallback(it) } catch (_: Exception) {} }
        controllers.clear(); callbacks.clear()
        super.onListenerDisconnected()
    }

    override fun onNotificationPosted(sbn: android.service.notification.StatusBarNotification?) {
        if (sbn != null) try { Chats.onPosted(this, sbn) } catch (_: Exception) {}
    }

    private fun attach(list: List<MediaController>) {
        for (c in list) {
            val key = c.sessionToken.toString()
            if (controllers.containsKey(key)) continue
            val cb = object : MediaController.Callback() {
                override fun onMetadataChanged(metadata: MediaMetadata?) = record(c)
                override fun onPlaybackStateChanged(state: PlaybackState?) = record(c)
            }
            try { c.registerCallback(cb) } catch (_: Exception) { continue }
            controllers[key] = c; callbacks[key] = cb
            record(c)
        }
    }

    private fun record(c: MediaController) {
        try {
            if (c.playbackState?.state != PlaybackState.STATE_PLAYING) return
            val md = c.metadata ?: return
            val title = md.getString(MediaMetadata.METADATA_KEY_TITLE) ?: return
            val artist = md.getString(MediaMetadata.METADATA_KEY_ARTIST)
                ?: md.getString(MediaMetadata.METADATA_KEY_ALBUM_ARTIST) ?: ""
            val dur = md.getLong(MediaMetadata.METADATA_KEY_DURATION)
            Interests.add(this, c.packageName ?: "", title, artist, dur)
        } catch (_: Exception) {}
    }
}
