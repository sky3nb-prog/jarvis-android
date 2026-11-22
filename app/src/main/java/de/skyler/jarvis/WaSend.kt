package de.skyler.jarvis

import android.content.Context
import android.content.Intent
import android.media.MediaCodec
import android.media.MediaFormat
import android.media.MediaMuxer
import android.os.Build
import android.util.Log
import androidx.core.content.FileProvider
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * WhatsApp verschicken, ohne dass du tippen musst:
 *  - Text: über die Antworten-Funktion der Benachrichtigung (wenn der Chat gerade eine hat), sonst öffnet Jarvis den Chat
 *    mit dem fertigen Text und die Bedienungshilfe drückt „Senden“.
 *  - Sprachnachricht: Jarvis spricht den Text mit seiner Stimme (Piper), macht daraus eine Audiodatei und schickt sie.
 */
object WaSend {
    private const val TAG = "JarvisWaSend"
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    private fun jid(ctx: Context, name: String): String? = Stil.number(ctx, name)?.let { "$it@s.whatsapp.net" }
    private fun waPkg(ctx: Context) = listOf("com.whatsapp", "com.whatsapp.w4b").firstOrNull {
        try { ctx.packageManager.getPackageInfo(it, 0); true } catch (_: Exception) { false } } ?: "com.whatsapp"

    /** true = verschickt (oder an WhatsApp übergeben, „Senden“ drückt die Bedienungshilfe). */
    fun text(ctx: Context, name: String, text: String): Boolean {
        if (Chats.reply(ctx, name, name, text)) return true
        val j = jid(ctx, name) ?: return false
        return try {
            if (ScreenService.enabled()) ScreenService.armSend()
            ctx.startActivity(Intent(Intent.ACTION_SEND).setType("text/plain").setPackage(waPkg(ctx)).putExtra(Intent.EXTRA_TEXT, Chats.waStyle(text))
                .putExtra("jid", j).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (e: Exception) { Log.w(TAG, "text: $e"); false }
    }

    /** „Schick Max eine Sprachnachricht: ich komm 10 Minuten später“.
     *  raw=true (Normalfall/Diktat): spricht GENAU `wish`, Wort für Wort - keine Umrahmung, nichts dazuerfunden.
     *  raw=false (nur bei „Antworte …“): Jarvis formuliert selbst eine kurze Antwort zum Thema `wish`. */
    fun voice(ctx: Context, name: String, wish: String, raw: Boolean = true): String {
        if (!PiperPhone.active(ctx)) return "Dafür brauch ich meine Stimme: Einstellungen → Zuhören & Stimme → „Jarvis-Stimme“ wählen und einmal laden."
        val j = jid(ctx, name) ?: return "Ich finde $name nicht in deinen Kontakten."
        val key = prefs(ctx).getString("groq_key", "") ?: ""
        val spoken = if (raw) wish.trim() else try {
            if (key.isBlank()) "Hey $name, hier ist Jarvis. Ich soll dir ausrichten: $wish"
            else Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content",
                "Du bist Jarvis, der KI-Assistent des Nutzers, und sprichst eine kurze WhatsApp-Sprachnachricht an $name. " +
                    "Fang locker an (z. B. „Hey $name, hier ist Jarvis“), dann sag den Inhalt in 1–3 kurzen Sätzen, über den Nutzer in der dritten Person " +
                    "(„er“), ohne seinen Namen zu erfinden. Nur der gesprochene Text, keine Emojis."))
                .put(JSONObject().put("role", "user").put("content", wish)), 200).trim().trim('"')
        } catch (_: Exception) { "Hey $name, hier ist Jarvis. Ich soll dir ausrichten: $wish" }
        val dir = File(ctx.cacheDir, "wa").apply { mkdirs() }
        dir.listFiles()?.filter { System.currentTimeMillis() - it.lastModified() > 3600_000L }?.forEach { it.delete() }
        val out = PiperPhone.render(ctx, spoken) ?: return "Die Sprachnachricht konnte ich nicht aufnehmen."
        var f = File(dir, "Jarvis-${System.currentTimeMillis()}.ogg")
        if (!opus(out.first, out.second, f)) { f = File(dir, f.nameWithoutExtension + ".wav"); wav(out.first, out.second, f) }
        return try {
            val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
            if (ScreenService.enabled()) ScreenService.armSend()
            ctx.startActivity(Intent(Intent.ACTION_SEND).setType(if (f.extension == "ogg") "audio/ogg" else "audio/wav").setPackage(waPkg(ctx))
                .putExtra(Intent.EXTRA_STREAM, uri).putExtra("jid", j)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION))
            if (ScreenService.enabled()) "Sprachnachricht an $name ist raus: „$spoken“"
            else "Die Sprachnachricht an $name ist fertig – tipp in WhatsApp noch auf Senden. (Schalte die Bedienungshilfe „Jarvis – Schau mal hier“ an, dann schick ich sie selbst.)"
        } catch (e: Exception) { Log.w(TAG, "voice: $e"); "WhatsApp ging nicht auf (${e.message})." }
    }

    // --- Audio speichern -----------------------------------------------------------------------------------------
    private fun resample(s: FloatArray, from: Int, to: Int): FloatArray {
        if (from == to) return s
        val n = (s.size.toLong() * to / from).toInt()
        return FloatArray(n) { i -> val x = i.toDouble() * from / to; val a = x.toInt(); val f = (x - a).toFloat()
            val p = s.getOrElse(a) { 0f }; val q = s.getOrElse(a + 1) { p }; p + (q - p) * f }
    }

    private fun pcm16(s: FloatArray): ByteArray {
        val b = ByteBuffer.allocate(s.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (v in s) b.putShort((v.coerceIn(-1f, 1f) * 32767).toInt().toShort())
        return b.array()
    }

    /** Ogg/Opus wie eine echte WhatsApp-Sprachnachricht (Android 10+). */
    private fun opus(samples: FloatArray, rate: Int, out: File): Boolean {
        if (Build.VERSION.SDK_INT < 29) return false
        var codec: MediaCodec? = null; var mux: MediaMuxer? = null
        return try {
            val sr = 48000
            val pcm = pcm16(resample(samples, rate, sr))
            val fmt = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_OPUS, sr, 1).apply { setInteger(MediaFormat.KEY_BIT_RATE, 32000) }
            codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_OPUS)
            codec.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE); codec.start()
            mux = MediaMuxer(out.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_OGG)
            var track = -1; var started = false
            var off = 0; var inDone = false; val info = MediaCodec.BufferInfo()
            val t0 = System.currentTimeMillis()
            while (System.currentTimeMillis() - t0 < 30_000) {
                if (!inDone) {
                    val i = codec.dequeueInputBuffer(5_000)
                    if (i >= 0) {
                        val buf = codec.getInputBuffer(i)!!; buf.clear()
                        val n = minOf(buf.remaining() / 2 * 2, pcm.size - off, 960 * 2 * 4)
                        val pts = off.toLong() / 2 * 1_000_000L / sr
                        if (n <= 0) { codec.queueInputBuffer(i, 0, 0, pts, MediaCodec.BUFFER_FLAG_END_OF_STREAM); inDone = true }
                        else { buf.put(pcm, off, n); codec.queueInputBuffer(i, 0, n, pts, 0); off += n }
                    }
                }
                val o = codec.dequeueOutputBuffer(info, 5_000)
                when {
                    o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> { track = mux.addTrack(codec.outputFormat); mux.start(); started = true }
                    o >= 0 -> {
                        val ob = codec.getOutputBuffer(o)!!
                        if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0 && info.size > 0 && started) {
                            ob.position(info.offset); ob.limit(info.offset + info.size); mux.writeSampleData(track, ob, info)
                        }
                        codec.releaseOutputBuffer(o, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                    }
                }
            }
            started && out.length() > 200
        } catch (e: Exception) { Log.w(TAG, "opus: $e"); false }
        finally {
            try { codec?.stop() } catch (_: Exception) {}; try { codec?.release() } catch (_: Exception) {}
            try { mux?.stop() } catch (_: Exception) {}; try { mux?.release() } catch (_: Exception) {}
        }
    }

    private fun wav(samples: FloatArray, rate: Int, out: File) {
        val d = pcm16(samples)
        RandomAccessFile(out, "rw").use { f ->
            f.setLength(0)
            val h = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
            h.put("RIFF".toByteArray()).putInt(36 + d.size).put("WAVE".toByteArray()).put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1)
                .putInt(rate).putInt(rate * 2).putShort(2).putShort(16).put("data".toByteArray()).putInt(d.size)
            f.write(h.array()); f.write(d)
        }
    }
}
