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
class Overlay(private val ctx: Context, private val onClose: () -> Unit) {
    private val wm = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var edge: EdgeView? = null
    private var close: CloseView? = null
    private val dp = ctx.resources.displayMetrics.density
    var level = 0f
    var state = "listening"

    fun canShow() = Settings.canDrawOverlays(ctx)

    // Lautstärke der Stimme (vom Mikrofon) lässt den Rand mitatmen
    private val busListener: (String, org.json.JSONObject) -> Unit = { type, data ->
        if (type == "level") level = data.optDouble("value", 0.0).toFloat().coerceIn(0f, 1f)
    }

    private fun type() = if (Build.VERSION.SDK_INT >= 26) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
    else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE

    @SuppressLint("ClickableViewAccessibility")
    fun show() {
        if (!canShow()) return
        if (edge == null && close == null) Bus.add(busListener)
        if (edge == null) {
            val v = EdgeView(ctx)
            val lp = WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT, type(),
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT)
            lp.gravity = Gravity.TOP or Gravity.START
            lp.alpha = 0.8f  // Android lässt Berührungen nur durch Fenster bis 80 % Deckkraft hindurch
            if (Build.VERSION.SDK_INT >= 28)
                lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            try { wm.addView(v, lp); edge = v } catch (_: Exception) {}
        }
        if (close == null) {
            val size = (dp * 58).toInt()
            val v = CloseView(ctx)
            val lp = WindowManager.LayoutParams(size, size, type(),
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT)
            lp.gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            lp.y = (dp * 96).toInt()  // über der Navigationsleiste
            v.setOnTouchListener { view, e ->
                when (e.action) {
                    MotionEvent.ACTION_DOWN -> { view.scaleX = 0.88f; view.scaleY = 0.88f }
                    MotionEvent.ACTION_UP -> { view.scaleX = 1f; view.scaleY = 1f; onClose() }
                    MotionEvent.ACTION_CANCEL -> { view.scaleX = 1f; view.scaleY = 1f }
                }
                true
            }
            try { wm.addView(v, lp); close = v } catch (_: Exception) {}
        }
    }

    fun hide() {
        if (edge != null || close != null) Bus.remove(busListener)
        edge?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        close?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        edge = null
        close = null
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
                try { target = ScreenColors.current(ctx) } catch (_: Exception) {}
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

        init { setLayerType(LAYER_TYPE_SOFTWARE, null) }  // für den weichen Schein (Blur)

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
            t += 0.016f
            shown = minOf(1f, shown + 0.06f)  // sanft einblenden
            lvl += (level - lvl) * 0.25f
            val pal = blend()
            val speed = when (state) { "thinking" -> 3.0f; "speaking" -> 1.3f; else -> 0.7f }
            val w = width.toFloat(); val h = height.toFloat()
            val breathe = 0.5f + 0.5f * sin(t * 2.4f)
            val base = dp * (if (state == "speaking") 3.2f else 2.6f)
            val thick = base + dp * 4f * lvl
            // Verlauf aus den Bildschirmfarben, zweimal rundherum, nahtlos
            val ring = intArrayOf(pal[0], pal[1], pal[2], pal[3], pal[0], pal[1], pal[2], pal[3], pal[0])
            val sg = SweepGradient(w / 2, h / 2, ring, null)
            rot.setRotate((t * 40f * speed) % 360f, w / 2, h / 2)
            sg.setLocalMatrix(rot)
            val r = cornerRadius()
            val inset = thick / 2
            val rect = RectF(inset, inset, w - inset, h - inset)
            // weicher Schein nach innen
            glow.shader = sg
            glow.strokeWidth = thick * 4.5f
            glow.maskFilter = BlurMaskFilter(dp * 14, BlurMaskFilter.Blur.NORMAL)
            glow.alpha = (shown * (120 + 70 * breathe + 60 * lvl)).toInt().coerceIn(0, 255)
            canvas.drawRoundRect(rect, r, r, glow)
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
            comet.strokeWidth = thick * 1.6f
            comet.maskFilter = BlurMaskFilter(dp * 3, BlurMaskFilter.Blur.NORMAL)
            comet.alpha = (shown * 230).toInt()
            canvas.drawRoundRect(rect, r, r, comet)
            postInvalidateOnAnimation()
        }
    }

    /** Rundes X zum Beenden: Ring in den Bildschirmfarben dreht sich, sanftes Pulsieren. */
    inner class CloseView(c: Context) : View(c) {
        private val p = Paint(Paint.ANTI_ALIAS_FLAG)
        private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND }
        private val m = Matrix()
        private var t = 0f
        private var shown = 0f

        init { setLayerType(LAYER_TYPE_SOFTWARE, null) }

        override fun onDraw(canvas: Canvas) {
            t += 0.016f
            shown = minOf(1f, shown + 0.07f)
            val w = width.toFloat(); val cx = w / 2; val cy = height / 2f
            val pulse = 0.5f + 0.5f * sin(t * 3f)
            val r = w * 0.40f * (0.92f + 0.08f * shown)
            val pal = cur
            // Schein
            p.style = Paint.Style.FILL
            p.maskFilter = BlurMaskFilter(dp * (4 + 3 * pulse), BlurMaskFilter.Blur.NORMAL)
            p.color = pal[0]; p.alpha = (shown * (70 + 60 * pulse)).toInt()
            canvas.drawCircle(cx, cy, r * 1.05f, p)
            p.maskFilter = null
            // dunkler Knopf
            p.color = Color.argb((235 * shown).toInt(), 12, 10, 8)
            canvas.drawCircle(cx, cy, r, p)
            // drehender Farbring
            val sg = SweepGradient(cx, cy, intArrayOf(pal[0], pal[1], pal[2], pal[3], pal[0]), null)
            m.setRotate((t * 160f) % 360f, cx, cy)
            sg.setLocalMatrix(m)
            ring.shader = sg
            ring.strokeWidth = dp * 2.6f
            ring.alpha = (shown * 255).toInt()
            canvas.drawCircle(cx, cy, r, ring)
            // X
            p.style = Paint.Style.STROKE
            p.strokeWidth = dp * 3.2f
            p.strokeCap = Paint.Cap.ROUND
            p.color = Color.WHITE
            p.alpha = (shown * 255).toInt()
            val k = r * 0.38f * (0.96f + 0.04f * pulse)
            canvas.drawLine(cx - k, cy - k, cx + k, cy + k, p)
            canvas.drawLine(cx + k, cy - k, cx - k, cy + k, p)
            postInvalidateOnAnimation()
        }
    }
}
