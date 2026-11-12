package de.skyler.jarvis

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONObject

/**
 * Das Jarvis-Fenster über anderen Apps (wie bei Gemini): unten die Leiste, darüber Karten mit Antworten,
 * Musik (öffnet Deezer), YouTube-Videos (öffnet YouTube) und Web-Ergebnissen.
 * Gezeichnet als kleine Webseite über die Grafikkarte – dadurch flüssig und scharf. Das Fenster ist immer genau
 * so hoch wie sein Inhalt, darüber kann man die App ganz normal bedienen.
 */
class Panel(private val ctx: Context, private val onClose: () -> Unit, private val onTalk: () -> Unit) {
    private val wm = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val main = Handler(Looper.getMainLooper())
    private val dp = ctx.resources.displayMetrics.density
    private var web: WebView? = null
    private var lp: WindowManager.LayoutParams? = null
    private var ready = false
    private val queue = ArrayList<String>()
    var visible = false
        private set
    /** true, solange eine Karte offen ist (dann dunkelt der Rand oben etwas ab, wie bei Gemini) */
    @Volatile var cardOpen = false
        private set
    private var hideJob: Runnable? = null

    @SuppressLint("SetJavaScriptEnabled")
    private fun create() {
        if (web != null) return
        val w = WebView(ctx)
        w.setBackgroundColor(Color.TRANSPARENT)
        w.setLayerType(View.LAYER_TYPE_HARDWARE, null)
        w.isVerticalScrollBarEnabled = false
        w.overScrollMode = View.OVER_SCROLL_NEVER
        w.settings.javaScriptEnabled = true
        w.settings.domStorageEnabled = true
        w.webViewClient = object : WebViewClient() {}
        w.addJavascriptInterface(Bridge(), "Panel")
        w.loadUrl("file:///android_asset/panel/panel.html")
        val type = if (Build.VERSION.SDK_INT >= 26) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE
        val p = WindowManager.LayoutParams(WindowManager.LayoutParams.MATCH_PARENT, (dp * 120).toInt(), type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
            PixelFormat.TRANSLUCENT)
        p.gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
        p.y = (dp * 24).toInt()  // etwas über der Navigationsleiste
        lp = p
        try { wm.addView(w, p); web = w } catch (_: Exception) {}
        w.visibility = View.GONE
    }

    private fun js(type: String, data: JSONObject) {
        val code = "window.J && J.ev(${JSONObject.quote(type)}, $data)"
        main.post {
            val w = web ?: return@post
            if (!ready) { queue.add(code); return@post }
            w.evaluateJavascript(code, null)
        }
    }

    fun show() {
        main.post {
            create()
            hideJob?.let { main.removeCallbacks(it) }; hideJob = null
            if (!visible) { visible = true; web?.visibility = View.VISIBLE }
        }
    }

    fun state(st: String, text: String? = null) {
        val o = JSONObject().put("state", st)
        if (text != null) o.put("text", text)
        js("state", o)
        // Gespräch vorbei: Karte noch eine Weile stehen lassen, dann von selbst ausblenden
        main.post {
            hideJob?.let { main.removeCallbacks(it) }; hideJob = null
            if (st == "ended") {
                val r = Runnable { hide() }
                hideJob = r
                main.postDelayed(r, if (cardOpen) 25_000L else 2_500L)
            }
        }
    }

    fun level(v: Float) = js("level", JSONObject().put("value", v.toDouble()))

    fun colors(c: IntArray) {
        val arr = org.json.JSONArray()
        for (i in 0 until minOf(3, c.size)) arr.put(String.format("#%06X", 0xFFFFFF and c[i]))
        js("colors", JSONObject().put("c", arr))
    }

    fun card(data: JSONObject) { show(); cardOpen = true; js("card", data) }

    fun hide() {
        main.post {
            hideJob?.let { main.removeCallbacks(it) }; hideJob = null
            if (!visible) return@post
            js("hide", JSONObject())
            cardOpen = false
            main.postDelayed({ if (!visible) web?.visibility = View.GONE }, 450)
            visible = false
        }
    }

    fun destroy() {
        main.post {
            web?.let { try { wm.removeView(it) } catch (_: Exception) {}; it.destroy() }
            web = null; ready = false; visible = false
        }
    }

    private fun openLink(url: String, app: String) {
        if (url.isBlank()) return
        val i = Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        when (app) {
            "youtube" -> i.setPackage("com.google.android.youtube")
            "deezer" -> i.setPackage("deezer.android.app")
        }
        try { ctx.startActivity(i) } catch (_: Exception) {
            try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } catch (_: Exception) {}
        }
    }

    inner class Bridge {
        @JavascriptInterface fun ready() = main.post {
            ready = true
            val w = web ?: return@post
            // Die Karte darf höchstens 60 % des Bildschirms hoch werden (nicht des eigenen Fensters, das wächst ja mit)
            val hCss = ctx.resources.displayMetrics.heightPixels / dp
            w.evaluateJavascript("window.J && J.ev('screen', {h: $hCss})", null)
            for (c in queue) w.evaluateJavascript(c, null)
            queue.clear()
        }

        /** Inhalt ist so hoch -> Fenster genau so hoch machen (CSS-Pixel). */
        @JavascriptInterface fun size(cssPx: Int) = main.post {
            val p = lp ?: return@post
            val h = (cssPx * dp).toInt().coerceIn((dp * 60).toInt(), (ctx.resources.displayMetrics.heightPixels * 0.92).toInt())
            if (kotlin.math.abs(p.height - h) > 2) {
                p.height = h
                try { wm.updateViewLayout(web, p) } catch (_: Exception) {}
            }
        }

        @JavascriptInterface fun close() = main.post { hide(); onClose() }
        @JavascriptInterface fun talk() = main.post { onTalk() }
        @JavascriptInterface fun mini(on: Boolean) { cardOpen = !on }
        @JavascriptInterface fun open(url: String, app: String) = main.post { this@Panel.openLink(url, app) }
    }
}
