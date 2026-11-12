package de.skyler.jarvis

import android.app.AppOpsManager
import android.app.WallpaperManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.os.Build
import android.os.Process

/**
 * Farben für den Leuchtrand, passend zu dem, was gerade zu sehen ist:
 * - in einer App: die Farben ihres Symbols (WhatsApp grün, YouTube rot, Snapchat gelb …)
 * - auf dem Startbildschirm (oder ohne Erlaubnis): die Farben deines Hintergrundbilds
 * Ohne Bildschirmaufnahme – dafür braucht es nur einmal "Nutzungszugriff" (welche App gerade vorne ist).
 */
object ScreenColors {
    private val cache = HashMap<String, IntArray>()
    private var lastPkg = ""
    private var lastTime = 0L

    fun hasUsageAccess(ctx: Context): Boolean = try {
        val ops = ctx.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = if (Build.VERSION.SDK_INT >= 29)
            ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName)
        else @Suppress("DEPRECATION") ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName)
        mode == AppOpsManager.MODE_ALLOWED
    } catch (_: Exception) { false }

    /** Welche App ist gerade vorne? (null = unbekannt) */
    private fun foreground(ctx: Context): String? {
        if (!hasUsageAccess(ctx)) return null
        return try {
            val usm = ctx.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
            val now = System.currentTimeMillis()
            val ev = usm.queryEvents(maxOf(lastTime, now - 60_000L), now)
            val e = UsageEvents.Event()
            while (ev.hasNextEvent()) {
                ev.getNextEvent(e)
                if (e.eventType == UsageEvents.Event.ACTIVITY_RESUMED || e.eventType == 1) {
                    lastPkg = e.packageName ?: lastPkg
                }
            }
            lastTime = now - 2000
            lastPkg.ifEmpty { null }
        } catch (_: Exception) { null }
    }

    private fun launcher(ctx: Context): String? = try {
        ctx.packageManager.resolveActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), 0)
            ?.activityInfo?.packageName
    } catch (_: Exception) { null }

    /** 3 bis 4 kräftige Farben für den Rand. */
    fun current(ctx: Context): IntArray {
        val pkg = foreground(ctx)
        val key = if (pkg == null || pkg == launcher(ctx) || pkg == ctx.packageName || pkg == "com.android.systemui")
            "wallpaper" else pkg
        cache[key]?.let { return it }
        val cols = (if (key == "wallpaper") wallpaper(ctx) else appIcon(ctx, key)) ?: wallpaper(ctx) ?: DEFAULT
        if (cache.size > 60) cache.clear()
        cache[key] = cols
        return cols
    }

    val DEFAULT = intArrayOf(Color.rgb(255, 176, 60), Color.rgb(60, 200, 255), Color.rgb(255, 120, 30))

    private fun wallpaper(ctx: Context): IntArray? {
        if (Build.VERSION.SDK_INT < 27) return null
        return try {
            val wc = WallpaperManager.getInstance(ctx).getWallpaperColors(WallpaperManager.FLAG_SYSTEM) ?: return null
            val list = listOfNotNull(wc.primaryColor, wc.secondaryColor, wc.tertiaryColor).map { vivid(it.toArgb()) }
            if (list.isEmpty()) null else spread(list)
        } catch (_: Exception) { null }
    }

    private fun appIcon(ctx: Context, pkg: String): IntArray? = try {
        val d = ctx.packageManager.getApplicationIcon(pkg)
        val bmp = Bitmap.createBitmap(40, 40, Bitmap.Config.ARGB_8888)
        d.setBounds(0, 0, 40, 40)
        d.draw(Canvas(bmp))
        dominant(bmp)
    } catch (_: Exception) { null }

    /** Die auffälligsten Farbtöne eines Bildes (nach Farbton sortiert gezählt, Grau/Schwarz/Weiß zählen kaum). */
    private fun dominant(bmp: Bitmap): IntArray? {
        val bins = FloatArray(24)
        val sums = Array(24) { FloatArray(3) }
        val hsv = FloatArray(3)
        for (y in 0 until bmp.height) for (x in 0 until bmp.width) {
            val c = bmp.getPixel(x, y)
            if (Color.alpha(c) < 128) continue
            Color.colorToHSV(c, hsv)
            val w = hsv[1] * hsv[2] * hsv[2]   // bunte, helle Pixel zählen mehr
            if (w < 0.08f) continue
            val b = ((hsv[0] / 15f).toInt()).coerceIn(0, 23)
            bins[b] += w
            sums[b][0] += Color.red(c) * w; sums[b][1] += Color.green(c) * w; sums[b][2] += Color.blue(c) * w
        }
        val order = bins.indices.sortedByDescending { bins[it] }.filter { bins[it] > 0f }
        if (order.isEmpty()) return null
        val picked = mutableListOf<Int>()
        for (b in order) {
            if (picked.any { kotlin.math.abs(it - b).let { d -> minOf(d, 24 - d) } < 3 }) continue
            if (bins[b] < bins[order[0]] * 0.12f) break
            picked.add(b)
            if (picked.size == 3) break
        }
        val cols = picked.map { b ->
            vivid(Color.rgb((sums[b][0] / bins[b]).toInt(), (sums[b][1] / bins[b]).toInt(), (sums[b][2] / bins[b]).toInt()))
        }
        return spread(cols)
    }

    /** Kräftig und hell genug, damit es leuchtet. */
    private fun vivid(c: Int): Int {
        val hsv = FloatArray(3)
        Color.colorToHSV(c, hsv)
        hsv[1] = if (hsv[1] < 0.12f) hsv[1] else maxOf(hsv[1], 0.65f)
        hsv[2] = maxOf(hsv[2], 0.9f)
        return Color.HSVToColor(hsv)
    }

    /** Aus 1–3 Farben einen schönen Verlauf: einfarbige Apps bekommen hellere/dunklere Nachbartöne dazu. */
    private fun spread(cols: List<Int>): IntArray {
        if (cols.size >= 2) return cols.toIntArray()
        val hsv = FloatArray(3)
        Color.colorToHSV(cols[0], hsv)
        val a = Color.HSVToColor(floatArrayOf((hsv[0] + 25f) % 360f, hsv[1], hsv[2]))
        val b = Color.HSVToColor(floatArrayOf((hsv[0] + 335f) % 360f, minOf(1f, hsv[1] * 0.8f), 1f))
        return intArrayOf(cols[0], a, b)
    }
}
