package de.skyler.jarvis

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.aggregate.AggregateMetric
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.time.TimeRangeFilter
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.time.Instant
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Samsung Health über Health Connect (nur lesen): verbrauchte Kalorien, aktive Kalorien, Schritte, Sport-Minuten
 * und – wenn du Essen einträgst – gegessene Kalorien (dann gibt's auch das Defizit). Schlaf kommt NICHT von hier (Sleep.kt).
 */
object Health {
    private const val TAG = "JarvisHealth"
    private val de = Locale.GERMANY
    val PERMS = setOf(
        HealthPermission.getReadPermission(TotalCaloriesBurnedRecord::class),
        HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class),
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(NutritionRecord::class),
    )

    fun status(ctx: Context): Int = try { HealthConnectClient.getSdkStatus(ctx) } catch (_: Exception) { HealthConnectClient.SDK_UNAVAILABLE }
    fun available(ctx: Context) = status(ctx) == HealthConnectClient.SDK_AVAILABLE

    fun granted(ctx: Context): Set<String> = if (!available(ctx)) emptySet() else try {
        runBlocking { HealthConnectClient.getOrCreate(ctx).permissionController.getGrantedPermissions() }
    } catch (e: Exception) { Log.w(TAG, "rechte: $e"); emptySet() }

    fun connected(ctx: Context) = granted(ctx).any { it in PERMS }

    /** Health Connect fehlt/veraltet -> Play Store; sonst die Health-Connect-Einstellungen. */
    fun openStore(ctx: Context) {
        try {
            ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.android.apps.healthdata&url=healthconnect%3A%2F%2Fonboarding"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (_: Exception) {}
    }

    fun openSettings(ctx: Context) {
        for (a in listOf("android.health.connect.action.HEALTH_HOME_SETTINGS", HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS)) {
            try { ctx.startActivity(Intent(a).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); return } catch (_: Exception) {}
        }
    }

    private fun <T : Any> agg(c: HealthConnectClient, m: AggregateMetric<T>, from: Long, to: Long): T? = try {
        runBlocking { c.aggregate(AggregateRequest(setOf(m), TimeRangeFilter.between(Instant.ofEpochMilli(from), Instant.ofEpochMilli(to))))[m] }
    } catch (e: Exception) { Log.w(TAG, "agg: $e"); null }

    private fun dayStart(offset: Int) = Calendar.getInstance().apply {
        add(Calendar.DAY_OF_YEAR, -offset); set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
    }.timeInMillis

    /** Ein Tag (0 = heute bis jetzt). kcal = verbraucht gesamt, aktiv, schritte, sport_min, gegessen (0 = nichts eingetragen), defizit. */
    fun day(ctx: Context, offset: Int = 0): JSONObject? {
        if (!available(ctx)) return null
        val c = try { HealthConnectClient.getOrCreate(ctx) } catch (_: Exception) { return null }
        val g = granted(ctx); if (g.none { it in PERMS }) return null
        val from = dayStart(offset); val to = minOf(from + 86_400_000L, System.currentTimeMillis())
        val o = JSONObject().put("tag", SimpleDateFormat("EE", de).format(Date(from))).put("datum", SimpleDateFormat("yyyy-MM-dd", de).format(Date(from)))
        if (HealthPermission.getReadPermission(TotalCaloriesBurnedRecord::class) in g)
            agg(c, TotalCaloriesBurnedRecord.ENERGY_TOTAL, from, to)?.let { o.put("kcal", Math.round(it.inKilocalories)) }
        if (HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class) in g)
            agg(c, ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL, from, to)?.let { o.put("aktiv", Math.round(it.inKilocalories)) }
        if (HealthPermission.getReadPermission(StepsRecord::class) in g)
            agg(c, StepsRecord.COUNT_TOTAL, from, to)?.let { o.put("schritte", it) }
        if (HealthPermission.getReadPermission(ExerciseSessionRecord::class) in g)
            agg(c, ExerciseSessionRecord.EXERCISE_DURATION_TOTAL, from, to)?.let { o.put("sport_min", it.toMinutes()) }
        if (HealthPermission.getReadPermission(NutritionRecord::class) in g)
            agg(c, NutritionRecord.ENERGY_TOTAL, from, to)?.let { val e = Math.round(it.inKilocalories); if (e > 0) o.put("gegessen", e) }
        if (o.has("kcal") && o.has("gegessen")) o.put("defizit", o.optLong("kcal") - o.optLong("gegessen"))
        return if (o.has("kcal") || o.has("schritte")) o else null
    }

    /** Letzte 7 Tage (heute zuletzt). */
    fun week(ctx: Context): JSONArray = JSONArray().apply { for (d in 6 downTo 0) day(ctx, d)?.let { put(it) } }

    private fun n(v: Long) = "%,d".format(de, v)

    /** Kurzer Text für Antworten ("wie viel hab ich heute verbraucht?"). */
    fun text(d: JSONObject?): String {
        if (d == null) return "Ich komme nicht an deine Gesundheitsdaten. Verbinde mich in den Einstellungen unter Gesundheit mit Health Connect."
        val p = mutableListOf<String>()
        if (d.has("kcal")) p.add("${n(d.optLong("kcal"))} Kalorien verbraucht" + (if (d.has("aktiv")) ", davon ${n(d.optLong("aktiv"))} durch Bewegung" else ""))
        if (d.has("schritte")) p.add("${n(d.optLong("schritte"))} Schritte")
        if (d.optLong("sport_min") > 0) p.add("${d.optLong("sport_min")} Minuten Sport")
        var t = p.joinToString(", ") + "."
        if (d.has("defizit")) { val x = d.optLong("defizit"); t += if (x > 0) " Gegessen ${n(d.optLong("gegessen"))} – also ${n(x)} Kalorien Defizit." else " Gegessen ${n(d.optLong("gegessen"))} – also ${n(-x)} Kalorien Überschuss." }
        return t
    }
}
