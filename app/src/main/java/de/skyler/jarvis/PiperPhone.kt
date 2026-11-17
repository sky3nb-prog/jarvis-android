package de.skyler.jarvis

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.util.Log
import com.k2fsa.sherpa.onnx.OfflineTts
import com.k2fsa.sherpa.onnx.OfflineTtsConfig
import com.k2fsa.sherpa.onnx.OfflineTtsModelConfig
import com.k2fsa.sherpa.onnx.OfflineTtsVitsModelConfig
import okhttp3.OkHttpClient
import okhttp3.Request
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream
import org.apache.commons.compress.compressors.bzip2.BZip2CompressorInputStream
import java.io.File
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * Dieselben Stimmen wie am PC (Piper), komplett offline auf dem Handy.
 * Jede Stimme wird einmal geladen (≈ 25–110 MB, standardmäßig nur im WLAN) und liegt dann in den App-Daten.
 * Die Auswahl („piper_voice“) ist mit dem PC abgeglichen: dort umgestellt = hier auch.
 */
object PiperPhone {
    private const val TAG = "JarvisPiper"
    private const val BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-"
    const val ANDROID = "android"   // = die normale Handy-Stimme
    val VOICES = listOf(
        "de_DE-thorsten-medium" to "Thorsten (männlich, Standard)",
        "de_DE-thorsten-high" to "Thorsten HD (männlich, natürlicher)",
        "de_DE-karlsson-low" to "Karlsson (männlich)",
        "de_DE-pavoque-low" to "Pavoque (männlich, tief)",
        "de_DE-kerstin-low" to "Kerstin (weiblich)",
        "de_DE-ramona-low" to "Ramona (weiblich)",
        "de_DE-eva_k-x_low" to "Eva (weiblich, sehr schnell)")

    private val http = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()
    @Volatile var status = ""; private set
    @Volatile private var installing: String? = null
    private var engine: OfflineTts? = null
    private var engineVoice = ""
    private val lock = Any()

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun voice(ctx: Context): String = prefs(ctx).getString("piper_voice", VOICES[0].first) ?: VOICES[0].first
    fun setVoice(ctx: Context, v: String) {
        if (v != ANDROID && VOICES.none { it.first == v }) return
        prefs(ctx).edit().putString("piper_voice", v).apply()
        if (v != ANDROID && !ready(ctx, v)) install(ctx, v, anyNetwork = true)
    }

    private fun dir(ctx: Context, v: String) = File(ctx.filesDir, "piper/vits-piper-$v")
    fun ready(ctx: Context, v: String = voice(ctx)): Boolean =
        v != ANDROID && File(dir(ctx, v), "$v.onnx").exists() && File(dir(ctx, v), "tokens.txt").exists() && File(dir(ctx, v), "espeak-ng-data/phontab").exists()
    fun installed(ctx: Context) = VOICES.map { it.first }.filter { ready(ctx, it) }

    /** Soll gerade Piper sprechen? (gewählt und schon geladen) */
    fun active(ctx: Context) = voice(ctx) != ANDROID && ready(ctx)

    private fun wifi(ctx: Context): Boolean = try {
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        cm.getNetworkCapabilities(cm.activeNetwork)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED) == true
    } catch (_: Exception) { false }

    /** Beim Start / regelmäßig: gewählte Stimme nachladen, wenn sie fehlt (nur im WLAN). */
    fun ensure(ctx: Context) {
        val v = voice(ctx)
        if (v != ANDROID && !ready(ctx, v)) install(ctx, v, anyNetwork = false)
    }

    fun install(ctx: Context, v: String, anyNetwork: Boolean) {
        if (installing != null || ready(ctx, v)) return
        if (!anyNetwork && !wifi(ctx)) { status = "wartet aufs WLAN"; return }
        installing = v
        Thread({
            val tmp = File(ctx.cacheDir, "piper-$v.tar.bz2")
            try {
                status = "lade Stimme …"
                http.newCall(Request.Builder().url("$BASE$v.tar.bz2").build()).execute().use { r ->
                    if (!r.isSuccessful) throw Exception("HTTP ${r.code}")
                    val body = r.body!!; val total = body.contentLength()
                    body.byteStream().use { inp -> tmp.outputStream().use { out ->
                        val buf = ByteArray(1 shl 16); var n: Int; var got = 0L
                        while (inp.read(buf).also { n = it } > 0) {
                            out.write(buf, 0, n); got += n
                            if (total > 0) status = "lade Stimme … ${got * 100 / total} %"
                        }
                    } }
                }
                status = "entpacke …"
                val root = File(ctx.filesDir, "piper"); root.mkdirs()
                val target = dir(ctx, v); target.deleteRecursively()
                TarArchiveInputStream(BZip2CompressorInputStream(tmp.inputStream().buffered())).use { tar ->
                    while (true) {
                        val e = tar.nextTarEntry ?: break
                        val out = File(root, e.name)
                        if (!out.canonicalPath.startsWith(root.canonicalPath + File.separator)) continue   // nichts außerhalb schreiben
                        if (e.isDirectory) { out.mkdirs(); continue }
                        out.parentFile?.mkdirs()
                        out.outputStream().use { tar.copyTo(it) }
                    }
                }
                status = if (ready(ctx, v)) "bereit" else "unvollständig"
                Log.i(TAG, "$v: $status")
            } catch (e: Exception) {
                status = "Laden ging nicht: ${e.message}"
                Log.w(TAG, "install $v: $e")
            } finally { tmp.delete(); installing = null }
        }, "jarvis-piper-dl").start()
    }

    private fun tts(ctx: Context): OfflineTts? = synchronized(lock) {
        val v = voice(ctx)
        if (!ready(ctx, v)) return null
        if (engine != null && engineVoice == v) return engine
        try { engine?.release() } catch (_: Exception) {}
        val d = dir(ctx, v)
        val cfg = OfflineTtsConfig(model = OfflineTtsModelConfig(
            vits = OfflineTtsVitsModelConfig(model = File(d, "$v.onnx").path, tokens = File(d, "tokens.txt").path, dataDir = File(d, "espeak-ng-data").path),
            numThreads = 4, provider = "cpu"))
        engine = OfflineTts(config = cfg); engineVoice = v
        engine
    }

    /** Beim Start einmal laden, damit der erste Satz sofort kommt. */
    fun warm(ctx: Context) { Thread({ try { tts(ctx)?.generate("Bereit.", 0, 1.0f) } catch (e: Throwable) { Log.w(TAG, "warm: $e") } }, "jarvis-piper-warm").start() }

    // --- Sprechen: Sätze nacheinander erzeugen und schon abspielen, während der nächste entsteht ---------------
    @Volatile private var gen = 0
    @Volatile private var track: AudioTrack? = null

    fun stop() { gen++; try { track?.pause(); track?.flush(); track?.stop() } catch (_: Exception) {} }

    /** false = geht gerade nicht (dann spricht die Handy-Stimme). onDone kommt aus einem Hintergrund-Thread. */
    fun speak(ctx: Context, text: String, speed: Float, onDone: () -> Unit): Boolean {
        if (!active(ctx)) return false
        val my = ++gen
        val parts = text.split(Regex("(?<=[.!?…])\\s+|\\n+")).map { it.trim() }.filter { it.isNotEmpty() }.ifEmpty { listOf(text) }
        val q = LinkedBlockingQueue<FloatArray>()
        val end = FloatArray(0)
        val rate = intArrayOf(22050)
        val first = java.util.concurrent.CountDownLatch(1)
        var failed = false
        Thread({
            try {
                val t = tts(ctx) ?: throw Exception("keine Stimme")
                rate[0] = t.sampleRate()
                for (p in parts) {
                    if (my != gen) break
                    q.put(t.generate(p, 0, speed.coerceIn(0.6f, 1.8f)).samples); first.countDown()
                }
            } catch (e: Throwable) { Log.w(TAG, "generate: $e"); failed = true }
            first.countDown(); q.put(end)
        }, "jarvis-piper-gen").start()
        Thread({
            try {
                first.await(20, TimeUnit.SECONDS)
                if (failed && q.peek() === end) { onDone(); return@Thread }
                val tr = AudioTrack.Builder()
                    .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    .setAudioFormat(AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_FLOAT).setSampleRate(rate[0]).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .setBufferSizeInBytes(AudioTrack.getMinBufferSize(rate[0], AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_FLOAT) * 4).build()
                track = tr; tr.play()
                var written = 0L
                while (my == gen) {
                    val s = q.poll(20, TimeUnit.SECONDS) ?: break
                    if (s === end) break
                    tr.write(s, 0, s.size, AudioTrack.WRITE_BLOCKING); written += s.size
                }
                if (my == gen) {   // ausklingen lassen
                    val t0 = System.currentTimeMillis()
                    while (my == gen && tr.playbackHeadPosition < written && System.currentTimeMillis() - t0 < 15_000) Thread.sleep(40)
                }
                try { tr.stop() } catch (_: Exception) {}
                tr.release(); if (track === tr) track = null
            } catch (e: Throwable) { Log.w(TAG, "play: $e") }
            onDone()
        }, "jarvis-piper-play").start()
        return true
    }
}
