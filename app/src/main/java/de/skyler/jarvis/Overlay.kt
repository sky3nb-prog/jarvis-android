package de.skyler.jarvis

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.BlurMaskFilter
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.SweepGradient
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.RoundedCorner
import android.view.View
import android.view.WindowManager
import kotlin.math.sin

/**
 * Solange Jarvis zuhört oder spricht: ein schmaler Leuchtrand einmal ums ganze Handy (wie bei Siri/Gemini)
 * und unten ein gut sichtbares X zum Beenden. Der Rand lässt alle Berührungen durch, man kann normal weiterbedienen.
 */
class Overlay(private val ctx: Context, private val onClose: () -> Unit, onTalk: () -> Unit = {}) {
    private val wm = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var edge: EdgeView? = null
    /** Das Jarvis-Fenster unten (Leiste + Karten), wie bei Gemini */
    val panel = Panel(ctx, onClose, onTalk)
    private val dp = ctx.resources.displayMetrics.density
    var level = 0f
    var state = "listening"

    fun canShow() = Settings.canDrawOverlays(ctx)

    // Lautstärke der Stimme (vom Mikrofon) lässt den Rand mitatmen
    private val busListener: (String, org.json.JSONObject) -> Unit = { type, data ->
        if (type == "level") { level = data.optDouble("value", 0.0).toFloat().coerceIn(0f, 1f); panel.level(level) }
    }

    private fun type() = if (Build.VERSION.SDK_INT >= 26) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
    else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE

    /** Jarvis-App ist gerade vorne: dann kein Rand (die App zeigt ihre eigene Kugel). */
    @Volatile var appVisible = false
    private var visible = false

    /** Zustand (listening, thinking, speaking …) an Rand und Fenster weitergeben. */
    fun setState(st: String) {
        state = st
        if (st == "ended" || st == "idle") { hide(); return }
        show()
        panel.state(st)
    }

    /** Eine Karte mit Ergebnis zeigen (nur außerhalb der Jarvis-App). */
    fun card(data: org.json.JSONObject) {
        if (!canShow() || appVisible) return
        panel.card(data)
    }

    fun setAppVisible(on: Boolean) {
        appVisible = on
        if (on) { hideEdge(); panel.hide() }
    }

    @SuppressLint("ClickableViewAccessibility")
    fun show() {
        if (!canShow() || appVisible) { hide(); return }
        panel.show()
        if (visible) return
        visible = true
        Bus.add(busListener)
        edge?.let { it.restart(); it.visibility = View.VISIBLE }
        if (edge == null) {
            val v = EdgeView(ctx)
            val lp = WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT, type(),
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT)
            lp.flags = lp.flags or WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED  // flüssig über die Grafikkarte
            lp.gravity = Gravity.TOP or Gravity.START
            lp.alpha = 0.8f  // Android lässt Berührungen nur durch Fenster bis 80 % Deckkraft hindurch
            if (Build.VERSION.SDK_INT >= 28)
                lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            try { wm.addView(v, lp); edge = v } catch (_: Exception) {}
        }
    }

    /** Ausblenden: die Fenster bleiben bestehen (nur unsichtbar), dadurch erscheint der Rand beim nächsten Mal sofort. */
    fun hide() {
        hideEdge()
        panel.state("ended")   // Leiste/Karte bleibt noch kurz stehen und blendet sich dann aus
    }

    private fun hideEdge() {
        if (!visible) return
        visible = false
        watching = false   // Farben nicht mehr abfragen, solange nichts zu sehen ist (spart Akku)
        Bus.remove(busListener)
        edge?.visibility = View.GONE
    }

    /** Ganz entfernen (Dienst wird beendet). */
    fun destroy() {
        hide()
        watching = false
        edge?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        edge = null
        panel.destroy()
    }

    // --- Farben passend zum Bildschirm (Hintergrundbild oder vordere App), weich überblendet ---------------
    private var target: IntArray = ScreenColors.DEFAULT
    private val cur = IntArray(4) { ScreenColors.DEFAULT[it % ScreenColors.DEFAULT.size] }
    @Volatile private var watching = false

    private fun startWatching() {
        if (watching) return
        watching = true
        Thread({
            while (watching) {
                try {
                    val t = ScreenColors.current(ctx)
                    if (!t.contentEquals(target)) { target = t; panel.colors(t) }
                } catch (_: Exception) {}
                try { Thread.sleep(1200) } catch (_: InterruptedException) { break }
            }
        }, "jarvis-farben").start()
    }

    /** Einmal pro Bild: aktuelle Farben ein Stück Richtung Ziel schieben (sanfter Wechsel beim App-Wechsel). */
    private fun blend(): IntArray {
        val tg = target
        for (i in cur.indices) {
            val a = cur[i]; val b = tg[i % tg.size]
            fun mix(x: Int, y: Int) = (x + (y - x) * 0.06f).toInt()
            cur[i] = Color.rgb(mix(Color.red(a), Color.red(b)), mix(Color.green(a), Color.green(b)), mix(Color.blue(a), Color.blue(b)))
        }
        return cur
    }

    /** Leuchtrand: Farben vom Bildschirm, ein heller Lichtpunkt läuft ständig im Kreis, atmet mit der Stimme. */
    inner class EdgeView(c: Context) : View(c) {
        private val glow = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
        private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
        private val comet = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND }
        private val rot = Matrix()
        private val rot2 = Matrix()
        private var t = 0f
        private var shown = 0f
        private var lvl = 0f
        private var radius = -1f
        private var dimA = 0f
        private val dim = Paint()

        fun restart() { shown = 0f; startWatching(); postInvalidateOnAnimation() }

        override fun onAttachedToWindow() { super.onAttachedToWindow(); startWatching() }
        override fun onDetachedFromWindow() { watching = false; super.onDetachedFromWindow() }

        private fun cornerRadius(): Float {
            if (radius >= 0) return radius
            var r = 0f
            if (Build.VERSION.SDK_INT >= 31) {
                val ins = rootWindowInsets
                val rc = ins?.getRoundedCorner(RoundedCorner.POSITION_TOP_LEFT)
                if (rc != null) r = rc.radius.toFloat()
            }
            radius = if (r > 0) r else dp * 38
            return radius
        }

        override fun onDraw(canvas: Canvas) {
            if (visibility != VISIBLE) return
            t += 0.016f
            shown = minOf(1f, shown + 0.16f)  // schnell, aber weich einblenden (~0,1 s)
            lvl += (level - lvl) * 0.3f
            val pal = blend()
            dimA += ((if (panel.cardOpen) 1f else 0f) - dimA) * 0.12f
            if (dimA > 0.01f) {   // wie bei Gemini: oben leicht abdunkeln, solange eine Karte offen ist
                dim.shader = android.graphics.LinearGradient(0f, 0f, 0f, height * 0.75f,
                    Color.argb((150 * dimA).toInt(), 0, 0, 0), Color.TRANSPARENT, android.graphics.Shader.TileMode.CLAMP)
                canvas.drawRect(0f, 0f, width.toFloat(), height * 0.75f, dim)
            }
            val speed = when (state) { "thinking" -> 3.0f; "speaking" -> 1.3f; else -> 0.7f }
            val w = width.toFloat(); val h = height.toFloat()
            val breathe = 0.5f + 0.5f * sin(t * 2.4f)
            val base = dp * (if (state == "speaking") 3.8f else 3.2f)
            val thick = base + dp * 4f * lvl
            // Verlauf aus den Bildschirmfarben, zweimal rundherum, nahtlos
            val ring = intArrayOf(pal[0], pal[1], pal[2], pal[3], pal[0], pal[1], pal[2], pal[3], pal[0])
            val sg = SweepGradient(w / 2, h / 2, ring, null)
            rot.setRotate((t * 40f * speed) % 360f, w / 2, h / 2)
            sg.setLocalMatrix(rot)
            val r = cornerRadius()
            val inset = thick / 2
            val rect = RectF(inset, inset, w - inset, h - inset)
            // Schein nach innen: drei breite, immer durchsichtigere Bahnen (ohne Weichzeichner -> flüssig)
            glow.shader = sg
            val ga = shown * (0.55f + 0.25f * breathe + 0.2f * lvl)
            for ((k, a) in listOf(7.5f to 0.16f, 4.5f to 0.30f, 2.4f to 0.55f)) {
                glow.strokeWidth = thick * k
                glow.alpha = (255 * a * ga).toInt().coerceIn(0, 255)
                canvas.drawRoundRect(rect, r, r, glow)
            }
            // Linie am Rand
            line.shader = sg
            line.strokeWidth = thick
            line.alpha = (shown * 255).toInt()
            canvas.drawRoundRect(rect, r, r, line)
            // heller Lichtpunkt, der ständig ums Handy läuft (mit Schweif)
            val head = Color.argb(255, 255, 255, 255)
            val tail = Color.argb(0, 255, 255, 255)
            val cs = SweepGradient(w / 2, h / 2, intArrayOf(tail, tail, Color.argb(90, 255, 255, 255), head, tail),
                floatArrayOf(0f, 0.80f, 0.93f, 0.985f, 1f))
            rot2.setRotate((t * 110f * speed) % 360f, w / 2, h / 2)
            cs.setLocalMatrix(rot2)
            comet.shader = cs
            comet.strokeWidth = thick * 1.5f
            comet.alpha = (shown * 255).toInt()
            canvas.drawRoundRect(rect, r, r, comet)
            postInvalidateOnAnimation()
        }
    }
}
