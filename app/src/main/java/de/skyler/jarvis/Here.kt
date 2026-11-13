package de.skyler.jarvis

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import androidx.core.content.ContextCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Wo ist das Handy gerade? (nur wenn in den Einstellungen erlaubt) – letzter bekannter Standort + Ortsname. */
object Here {
    private val http = OkHttpClient.Builder().callTimeout(8, TimeUnit.SECONDS).build()
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    fun enabled(ctx: Context) = prefs(ctx).getBoolean("use_location", false) &&
        (ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED)

    /** Ortsname wie "Leonberg-Eltingen" (leer, wenn aus oder unbekannt) */
    fun name(ctx: Context): String = if (enabled(ctx)) prefs(ctx).getString("here_name", "") ?: "" else ""

    fun latLon(ctx: Context): Pair<Double, Double>? {
        if (!enabled(ctx)) return null
        val p = prefs(ctx); val la = p.getFloat("here_lat", 999f); val lo = p.getFloat("here_lon", 999f)
        return if (la > 90f) null else la.toDouble() to lo.toDouble()
    }

    /** Standort auffrischen (höchstens alle 10 Minuten, im Hintergrund). */
    @SuppressLint("MissingPermission")
    fun refresh(ctx: Context, force: Boolean = false) {
        if (!enabled(ctx)) return
        val p = prefs(ctx)
        if (!force && System.currentTimeMillis() - p.getLong("here_time", 0) < 10 * 60_000) return
        Thread({
            try {
                val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as LocationManager
                val loc = listOf(LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER, LocationManager.PASSIVE_PROVIDER)
                    .mapNotNull { try { lm.getLastKnownLocation(it) } catch (_: Exception) { null } }
                    .maxByOrNull { it.time } ?: return@Thread
                var name = ""
                try {
                    val url = "https://photon.komoot.io/reverse?lat=${loc.latitude}&lon=${loc.longitude}&lang=de&limit=1"
                    val js = http.newCall(Request.Builder().url(url).header("User-Agent", "Jarvis-Handy/1.0 (privat)").build())
                        .execute().use { it.body?.string() ?: "" }
                    val pr = JSONObject(js).optJSONArray("features")?.optJSONObject(0)?.optJSONObject("properties")
                    if (pr != null) {
                        val city = pr.optString("city").ifBlank { pr.optString("town").ifBlank { pr.optString("village") } }
                        val part = pr.optString("district").ifBlank { pr.optString("locality") }
                        name = listOf(city, part).filter { it.isNotBlank() }.distinct().joinToString("-")
                            .ifBlank { pr.optString("name") }
                    }
                } catch (_: Exception) {}
                p.edit().putFloat("here_lat", loc.latitude.toFloat()).putFloat("here_lon", loc.longitude.toFloat())
                    .putString("here_name", name).putLong("here_time", System.currentTimeMillis()).apply()
            } catch (_: Exception) {}
        }, "jarvis-here").start()
    }
}
