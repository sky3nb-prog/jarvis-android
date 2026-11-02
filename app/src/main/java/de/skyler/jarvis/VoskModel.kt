package de.skyler.jarvis

import android.content.Context
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit
import java.util.zip.ZipInputStream

/**
 * Kleines deutsches Sprachmodell (Vosk, ca. 45 MB) für das Aktivierungswort – läuft ganz auf dem Handy,
 * ohne Internet und ohne Töne. Wird beim ersten Start einmal heruntergeladen.
 */
object VoskModel {
    private const val URL = "https://alphacephei.com/vosk/models/vosk-model-small-de-0.15.zip"
    @Volatile private var loading = false

    fun dir(ctx: Context) = File(ctx.filesDir, "vosk-de")
    fun ready(ctx: Context) = File(dir(ctx), "ready").exists()

    fun ensure(ctx: Context, done: (Boolean) -> Unit) {
        if (ready(ctx)) { done(true); return }
        if (loading) return
        loading = true
        Thread({
            val ok = try { download(ctx); true } catch (e: Exception) { Log.w("JarvisVosk", "download: $e"); false }
            loading = false
            done(ok)
        }, "jarvis-model").start()
    }

    private fun download(ctx: Context) {
        Bus.emit("model", JSONObject().put("text", "Lade die Spracherkennung fürs Aktivierungswort (45 MB, einmalig) …"))
        val http = OkHttpClient.Builder().readTimeout(60, TimeUnit.SECONDS).build()
        val zip = File(ctx.cacheDir, "vosk.zip")
        http.newCall(Request.Builder().url(URL).build()).execute().use { r ->
            if (!r.isSuccessful) throw RuntimeException("HTTP ${r.code}")
            r.body!!.byteStream().use { inp -> zip.outputStream().use { out -> inp.copyTo(out, 1 shl 16) } }
        }
        val target = dir(ctx)
        target.deleteRecursively()
        target.mkdirs()
        ZipInputStream(zip.inputStream()).use { z ->
            while (true) {
                val e = z.nextEntry ?: break
                val name = e.name.substringAfter('/', "")     // oberster Ordner im Zip fällt weg
                if (name.isEmpty()) continue
                val f = File(target, name)
                if (!f.canonicalPath.startsWith(target.canonicalPath)) continue
                if (e.isDirectory) f.mkdirs() else { f.parentFile?.mkdirs(); f.outputStream().use { z.copyTo(it) } }
            }
        }
        zip.delete()
        File(target, "ready").writeText("ok")
        Bus.emit("model", JSONObject().put("text", "Fertig – ich höre jetzt auf mein Aktivierungswort."))
    }
}
