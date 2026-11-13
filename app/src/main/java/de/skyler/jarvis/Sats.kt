package de.skyler.jarvis

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

/** Bahndaten (TLE) echter Satelliten für die Erde auf der Lage-Seite – von CelesTrak, zweimal am Tag frisch. */
object Sats {
    private val IDS = listOf(25544, 48274, 20580, 40697, 43013)   // ISS, Tiangong, Hubble, Sentinel-2A, NOAA-20
    private val http = OkHttpClient.Builder().callTimeout(20, TimeUnit.SECONDS).build()
    @Volatile private var busy = false

    private fun file(ctx: Context) = File(ctx.filesDir, "satelliten.tle")

    fun cached(ctx: Context): String = try { file(ctx).readText() } catch (_: Exception) { "" }

    /** Im Hintergrund auffrischen, wenn älter als 12 Stunden. onDone bekommt den neuen Text. */
    fun refresh(ctx: Context, onDone: (String) -> Unit) {
        val f = file(ctx)
        if (busy || (f.exists() && System.currentTimeMillis() - f.lastModified() < 12 * 3600_000L && f.length() > 100)) return
        busy = true
        Thread({
            try {
                val got = LinkedHashMap<Int, String>()
                fun take(txt: String) {
                    val l = txt.replace("\r", "").lines()
                    for (i in 0 until l.size - 2) {
                        if (!l[i + 1].startsWith("1 ") || !l[i + 2].startsWith("2 ")) continue
                        val id = l[i + 1].substring(2, 7).trim().toIntOrNull() ?: continue
                        if (id in IDS && id !in got) got[id] = "${l[i].trim()}\n${l[i + 1]}\n${l[i + 2]}"
                    }
                }
                for (g in listOf("stations", "resource", "science")) {
                    try { take(get("https://celestrak.org/NORAD/elements/gp.php?GROUP=$g&FORMAT=tle")) } catch (_: Exception) {}
                }
                for (id in IDS) if (id !in got) try {   // Ersatzquelle, falls CelesTrak gerade bremst
                    val o = JSONObject(get("https://tle.ivanstanojevic.me/api/tle/$id"))
                    got[id] = "${o.optString("name")}\n${o.optString("line1")}\n${o.optString("line2")}"
                } catch (_: Exception) {}
                if (got.isNotEmpty()) {
                    val txt = got.values.joinToString("\n")
                    f.writeText(txt)
                    onDone(txt)
                }
            } finally { busy = false }
        }, "jarvis-sats").start()
    }

    private fun get(url: String): String = http.newCall(Request.Builder().url(url)
        .header("User-Agent", "Jarvis-Handy/1.0 (privat)").build()).execute().use { if (it.isSuccessful) it.body?.string() ?: "" else "" }
}
