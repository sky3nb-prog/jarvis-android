package de.skyler.jarvis

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import android.widget.FrameLayout
import org.json.JSONObject

class MainActivity : ComponentActivity() {

    companion object {
        const val AGENT_ID = "agent_4701m6c6964efypvmbjqf3e7ak9m"
    }

    private lateinit var web: WebView
    private var talk: LiveTalk? = null
    private var pendingTalk = false

    private val micPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok && pendingTalk) startTalk()
        else if (!ok) send("error", JSONObject().put("text", "Ohne Mikrofon kann ich dich nicht hören."))
        pendingTalk = false
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.setBackgroundColor(Color.BLACK)
        web.overScrollMode = View.OVER_SCROLL_NEVER
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            @Suppress("DEPRECATION")
            allowFileAccessFromFileURLs = true
        }
        web.webChromeClient = WebChromeClient()
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.scheme == "file") return false
                startActivity(Intent(Intent.ACTION_VIEW, url)) // Links im Browser öffnen
                return true
            }
        }
        web.addJavascriptInterface(Bridge(), "Android")
        web.loadUrl("file:///android_asset/web/index.html")
        // Android 15+: App liegt unter Status- und Navigationsleiste -> Abstand passend zu den Leisten
        val root = FrameLayout(this)
        root.setBackgroundColor(Color.BLACK)
        root.addView(web, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val b = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            v.setPadding(b.left, b.top, b.right, b.bottom)
            WindowInsetsCompat.CONSUMED
        }
        setContentView(root)
    }

    override fun onDestroy() {
        talk?.stop()
        super.onDestroy()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        web.evaluateJavascript("window.jarvis && window.jarvis.back()") { r ->
            if (r != "true") {
                @Suppress("DEPRECATION")
                super.onBackPressed()
            }
        }
    }

    private fun send(type: String, data: JSONObject) {
        val js = "window.jarvis && window.jarvis.onEvent(${JSONObject.quote(type)}, ${data})"
        runOnUiThread { web.evaluateJavascript(js, null) }
        if (type == "state") {
            val st = data.optString("state")
            runOnUiThread {
                if (st == "ended") window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }
    }

    private fun startTalk() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            pendingTalk = true
            micPermission.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        if (talk?.isRunning == true) return
        val prompt = Prompts.voicePrompt(this)
        talk = LiveTalk(this, AGENT_ID, prompt) { type, data -> send(type, data) }.also { it.start() }
    }

    private fun stopTalk() {
        talk?.stop()
        talk = null
    }

    inner class Bridge {
        @JavascriptInterface
        fun startTalk() = runOnUiThread { this@MainActivity.startTalk() }

        @JavascriptInterface
        fun stopTalk() = runOnUiThread { this@MainActivity.stopTalk() }

        @JavascriptInterface
        fun toggleTalk() = runOnUiThread {
            if (talk?.isRunning == true) this@MainActivity.stopTalk() else this@MainActivity.startTalk()
        }

        @JavascriptInterface
        fun isTalking(): Boolean = talk?.isRunning == true

        @JavascriptInterface
        fun openUrl(url: String) = runOnUiThread {
            try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } catch (_: Exception) {}
        }

        @JavascriptInterface
        fun version(): String = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: ""
        } catch (_: Exception) { "" }
    }
}
