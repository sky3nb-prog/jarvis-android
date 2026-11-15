package de.skyler.jarvis

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.RemoteViews
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * Jarvis-Widget für den Startbildschirm, frei in der Größe: klein = nur die Kugel (antippen = reden),
 * breit = Kugel, Uhr, was als Nächstes ansteht (Stunde, Termin, Arbeit, Paket, Modus) und Mikro-Knopf.
 */
class JarvisWidget : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) { for (id in ids) draw(ctx, mgr, id) }
    override fun onAppWidgetOptionsChanged(ctx: Context, mgr: AppWidgetManager, id: Int, o: Bundle?) = draw(ctx, mgr, id)

    companion object {
        @Volatile private var lastAll = 0L
        /** Alle Widgets neu zeichnen (aus Alltag.tick, höchstens jede Minute). */
        fun refresh(ctx: Context, force: Boolean = false) {
            if (!force && System.currentTimeMillis() - lastAll < 60_000L) return
            lastAll = System.currentTimeMillis()
            try {
                val mgr = AppWidgetManager.getInstance(ctx)
                mgr.getAppWidgetIds(ComponentName(ctx, JarvisWidget::class.java)).forEach { draw(ctx, mgr, it) }
            } catch (_: Exception) {}
        }

        private fun open(ctx: Context, talk: Boolean, code: Int): PendingIntent =
            PendingIntent.getActivity(ctx, code, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra("talk", talk), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

        fun draw(ctx: Context, mgr: AppWidgetManager, id: Int) {
            val o = mgr.getAppWidgetOptions(id)
            val w = o?.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 250) ?: 250
            val h = o?.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 80) ?: 80
            val v: RemoteViews
            if (w < 150) {
                v = RemoteViews(ctx.packageName, R.layout.widget_jarvis_small)
                v.setOnClickPendingIntent(R.id.w_root, open(ctx, true, 41))
            } else {
                v = RemoteViews(ctx.packageName, R.layout.widget_jarvis)
                val (l1, l2) = lines(ctx)
                v.setTextViewText(R.id.w_l1, l1); v.setTextViewText(R.id.w_l2, l2)
                v.setViewVisibility(R.id.w_l2, if (l2.isBlank() || h < 70) View.GONE else View.VISIBLE)
                v.setViewVisibility(R.id.w_clock, if (h < 56) View.GONE else View.VISIBLE)
                v.setViewVisibility(R.id.w_mic, if (w < 200) View.GONE else View.VISIBLE)
                val orb = when { h >= 110 -> 88; h >= 70 -> 64; else -> 44 }
                if (android.os.Build.VERSION.SDK_INT >= 31) {
                    v.setViewLayoutWidth(R.id.w_orb, orb.toFloat(), android.util.TypedValue.COMPLEX_UNIT_DIP)
                    v.setViewLayoutHeight(R.id.w_orb, orb.toFloat(), android.util.TypedValue.COMPLEX_UNIT_DIP)
                }
                v.setOnClickPendingIntent(R.id.w_root, open(ctx, false, 42))
                v.setOnClickPendingIntent(R.id.w_orb, open(ctx, true, 43))
                v.setOnClickPendingIntent(R.id.w_mic, open(ctx, true, 44))
            }
            mgr.updateAppWidget(id, v)
        }

        /** Was gerade wichtig ist – zwei kurze Zeilen. */
        private fun lines(ctx: Context): Pair<String, String> {
            val out = mutableListOf<String>()
            val de = Locale.GERMANY
            try { Modes.current(ctx).takeIf { it.isNotBlank() }?.let { out.add("Modus: " + it.replaceFirstChar { c -> c.uppercase() }) } } catch (_: Exception) {}
            try { Melden.lessonNow(ctx)?.let { out.add("Jetzt: ${it.optString("fach").ifBlank { "Unterricht" }} bis ${it.optString("bis")}") } } catch (_: Exception) {}
            try {
                val now = System.currentTimeMillis()
                Cal.events(ctx, now, now + 36 * 3_600_000L).filter { !it.allDay && it.begin > now }.minByOrNull { it.begin }?.let {
                    val d = Calendar.getInstance().apply { timeInMillis = it.begin }; val today = Calendar.getInstance()
                    out.add((if (d.get(Calendar.DAY_OF_YEAR) == today.get(Calendar.DAY_OF_YEAR)) "" else "Morgen ") + SimpleDateFormat("HH:mm", de).format(Date(it.begin)) + " " + it.title)
                }
            } catch (_: Exception) {}
            try {
                val a = Schule.all(ctx); val today = SimpleDateFormat("yyyy-MM-dd", de).format(Date())
                (0 until a.length()).mapNotNull { a.optJSONObject(it) }.filter { !it.optBoolean("done") && it.optString("datum") >= today && it.optString("art") != "ha" }
                    .minByOrNull { it.optString("datum") }?.let {
                        val dd = ((SimpleDateFormat("yyyy-MM-dd", de).parse(it.optString("datum"))!!.time - SimpleDateFormat("yyyy-MM-dd", de).parse(today)!!.time) / 86_400_000L).toInt()
                        if (dd <= 7) out.add("${if (it.optString("art") == "test") "Test" else "Arbeit"} ${it.optString("fach")} ${when (dd) { 0 -> "heute"; 1 -> "morgen"; else -> "in $dd Tagen" }}".replace("  ", " "))
                    }
            } catch (_: Exception) {}
            try {
                val p = Pakete.all(ctx)
                (0 until p.length()).mapNotNull { p.optJSONObject(it) }.firstOrNull { it.optString("status") == "heute" || it.optString("status") == "abholen" }?.let {
                    out.add("Paket ${it.optString("carrier")} ${if (it.optString("status") == "heute") "kommt heute" else "abholbereit"}".replace("  ", " "))
                }
            } catch (_: Exception) {}
            if (out.isEmpty()) out.add("Alles ruhig. Tipp auf die Kugel zum Reden.")
            return out[0] to out.drop(1).take(2).joinToString(" · ")
        }
    }
}
