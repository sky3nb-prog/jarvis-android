package de.skyler.jarvis

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RadialGradient
import android.graphics.Shader
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/** Kleine goldene Kugel über allen Apps, solange Jarvis zuhört oder spricht (wie das kleine Overlay am PC). */
class Overlay(private val ctx: Context, private val onTap: () -> Unit) {
    private val wm = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var view: OrbView? = null
    var level = 0f
    var state = "listening"

    fun canShow() = Settings.canDrawOverlays(ctx)

    @SuppressLint("ClickableViewAccessibility")
    fun show() {
        if (view != null || !canShow()) return
        val size = (ctx.resources.displayMetrics.density * 84).toInt()
        val v = OrbView(ctx)
        val lp = WindowManager.LayoutParams(size, size,
            if (Build.VERSION.SDK_INT >= 26) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT)
        lp.gravity = Gravity.TOP or Gravity.END
        lp.x = (ctx.resources.displayMetrics.density * 16).toInt()
        lp.y = (ctx.resources.displayMetrics.density * 120).toInt()
        var downX = 0f; var downY = 0f; var startX = 0; var startY = 0; var moved = false
        v.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { downX = e.rawX; downY = e.rawY; startX = lp.x; startY = lp.y; moved = false }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX; val dy = e.rawY - downY
                    if (kotlin.math.abs(dx) + kotlin.math.abs(dy) > 12) moved = true
                    lp.x = (startX - dx).toInt(); lp.y = (startY + dy).toInt()
                    try { wm.updateViewLayout(v, lp) } catch (_: Exception) {}
                }
                MotionEvent.ACTION_UP -> if (!moved) onTap()
            }
            true
        }
        try { wm.addView(v, lp); view = v } catch (_: Exception) {}
    }

    fun hide() {
        view?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        view = null
    }

    inner class OrbView(c: Context) : View(c) {
        private val p = Paint(Paint.ANTI_ALIAS_FLAG)
        private var t = 0f

        override fun onDraw(canvas: Canvas) {
            t += 0.016f
            val w = width.toFloat(); val cx = w / 2; val cy = height / 2f
            val breathe = 1f + 0.06f * sin(t * 2.2f) + 0.18f * level
            val r = w * 0.30f * breathe
            // Leuchten
            p.style = Paint.Style.FILL
            p.shader = RadialGradient(cx, cy, w / 2, intArrayOf(0x99FF9A1E.toInt(), 0x33FF8A00, 0x00000000),
                floatArrayOf(0f, 0.55f, 1f), Shader.TileMode.CLAMP)
            canvas.drawCircle(cx, cy, w / 2, p)
            p.shader = RadialGradient(cx, cy, r, intArrayOf(0xFFFFF0C8.toInt(), 0xFFFFAA28.toInt(), 0xFF3A2000.toInt()),
                floatArrayOf(0f, 0.35f, 1f), Shader.TileMode.CLAMP)
            canvas.drawCircle(cx, cy, r, p)
            p.shader = null
            // drehende Ringe
            p.style = Paint.Style.STROKE
            p.strokeWidth = w * 0.025f
            p.color = if (state == "speaking") 0xFFFFE6A0.toInt() else 0xFFFFC85A.toInt()
            for (k in 0 until 3) {
                val a0 = (t * (40 + k * 25) + k * 120) % 360
                val rr = r * (1.18f + k * 0.12f)
                canvas.drawArc(cx - rr, cy - rr, cx + rr, cy + rr, a0, 70f, false, p)
            }
            // kleine Datenpunkte
            p.style = Paint.Style.FILL
            p.color = 0xFFFFE6B4.toInt()
            for (i in 0 until 10) {
                val a = t * 1.3f + i * (2 * PI.toFloat() / 10)
                canvas.drawCircle(cx + cos(a) * r * 0.7f, cy + sin(a * 1.3f) * r * 0.55f, w * 0.012f, p)
            }
            postInvalidateOnAnimation()
        }
    }
}
