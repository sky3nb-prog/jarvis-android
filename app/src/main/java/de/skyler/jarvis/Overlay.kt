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

    /** Leuchtrand: dreht sich langsam, atmet mit der Stimme; beim Nachdenken schneller, beim Sprechen heller. */
    inner class EdgeView(c: Context) : View(c) {
        private val glow = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
        private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
        private val rot = Matrix()
        private var t = 0f
        private var shown = 0f
        private var lvl = 0f
        private var radius = -1f
        private val colors = intArrayOf(
            Color.rgb(255, 176, 60), Color.rgb(255, 120, 30), Color.rgb(60, 200, 255),
            Color.rgb(255, 214, 120), Color.rgb(255, 140, 40), Color.rgb(90, 220, 255), Color.rgb(255, 176, 60))

        init { setLayerType(LAYER_TYPE_SOFTWARE, null) }  // für den weichen Schein (Blur)

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
            val speed = when (state) { "thinking" -> 3.2f; "speaking" -> 1.4f; else -> 0.8f }
            val w = width.toFloat(); val h = height.toFloat()
            val breathe = 0.5f + 0.5f * sin(t * 2.4f)
            val base = dp * (if (state == "speaking") 3.2f else 2.6f)
            val thick = base + dp * 4f * lvl
            val sg = SweepGradient(w / 2, h / 2, colors, null)
            rot.setRotate((t * 60f * speed) % 360f, w / 2, h / 2)
            sg.setLocalMatrix(rot)
            val r = cornerRadius()
            val inset = thick / 2
            val rect = RectF(inset, inset, w - inset, h - inset)
            // weicher Schein nach innen
            glow.shader = sg
            glow.strokeWidth = thick * 4.5f
            glow.maskFilter = BlurMaskFilter(dp * 14, BlurMaskFilter.Blur.NORMAL)
            glow.alpha = (shown * (110 + 70 * breathe + 60 * lvl)).toInt().coerceIn(0, 255)
            canvas.drawRoundRect(rect, r, r, glow)
            // scharfe Linie am Rand
            line.shader = sg
            line.strokeWidth = thick
            line.alpha = (shown * 255).toInt()
            canvas.drawRoundRect(rect, r, r, line)
            postInvalidateOnAnimation()
        }
    }

    /** Rundes X zum Beenden: dunkel mit goldenem Ring, groß genug zum Treffen. */
    inner class CloseView(c: Context) : View(c) {
        private val p = Paint(Paint.ANTI_ALIAS_FLAG)
        override fun onDraw(canvas: Canvas) {
            val w = width.toFloat(); val cx = w / 2; val cy = height / 2f; val r = w * 0.44f
            p.style = Paint.Style.FILL
            p.color = Color.argb(235, 12, 10, 8)
            canvas.drawCircle(cx, cy, r, p)
            p.style = Paint.Style.STROKE
            p.strokeWidth = dp * 2f
            p.color = Color.rgb(255, 176, 60)
            canvas.drawCircle(cx, cy, r, p)
            p.strokeWidth = dp * 3.2f
            p.strokeCap = Paint.Cap.ROUND
            p.color = Color.WHITE
            val k = r * 0.38f
            canvas.drawLine(cx - k, cy - k, cx + k, cy + k, p)
            canvas.drawLine(cx + k, cy - k, cx - k, cy + k, p)
        }
    }
}
