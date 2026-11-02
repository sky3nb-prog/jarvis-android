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
        free?.stop()
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

    private val prefs by lazy { getSharedPreferences("jarvis", MODE_PRIVATE) }

    private fun startTalk() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            pendingTalk = true
            micPermission.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        if (talk?.isRunning == true || free?.isRunning == true) return
        val prompt = Prompts.voicePrompt(this)
        val elevenOff = prefs.getLong("eleven_off_until", 0L) > System.currentTimeMillis()
        if (elevenOff || prefs.getString("voice_mode", "auto") == "free") {
            startFree(prompt)
            return
        }
        talk = LiveTalk(this, AGENT_ID, prompt) { type, data ->
            if (type == "quota") {
                // ElevenLabs-Guthaben leer: 6 Stunden lang gleich die kostenlose Variante nehmen
                prefs.edit().putLong("eleven_off_until", System.currentTimeMillis() + 6 * 3600_000L).apply()
                runOnUiThread { talk = null; startFree(prompt) }
            } else send(type, data)
        }.also { it.start() }
    }

    private var free: FreeTalk? = null

    private fun startFree(prompt: String) {
        val key = prefs.getString("groq_key", "") ?: ""
        if (key.isBlank()) {
            send("needkey", JSONObject())
            return
        }
        free = FreeTalk(this, key, prompt, prefs.getString("tts_voice", null)) { type, data ->
            if (type == "voices") prefs.edit().putString("tts_voices", data.toString()).apply()
            send(type, data)
        }.also { it.start() }
    }

    private fun stopTalk() {
        talk?.stop()
        talk = null
        free?.stop()
        free = null
    }

    private fun running() = talk?.isRunning == true || free?.isRunning == true

    inner class Bridge {
        @JavascriptInterface
        fun startTalk() = runOnUiThread { this@MainActivity.startTalk() }

        @JavascriptInterface
        fun stopTalk() = runOnUiThread { this@MainActivity.stopTalk() }

        @JavascriptInterface
        fun toggleTalk() = runOnUiThread {
            if (running()) this@MainActivity.stopTalk() else this@MainActivity.startTalk()
        }

        /** Tipp auf die Kugel während er spricht: nur unterbrechen (kostenlose Variante). */
        @JavascriptInterface
        fun interrupt() = runOnUiThread { free?.interrupt() }

        @JavascriptInterface
        fun isTalking(): Boolean = running()

        @JavascriptInterface
        fun setGroqKey(key: String) {
            prefs.edit().putString("groq_key", key.trim()).apply()
        }

        @JavascriptInterface
        fun hasGroqKey(): Boolean = !prefs.getString("groq_key", "").isNullOrBlank()

        @JavascriptInterface
        fun setVoiceMode(mode: String) { prefs.edit().putString("voice_mode", mode).apply() }

        @JavascriptInterface
        fun getVoiceMode(): String = prefs.getString("voice_mode", "auto") ?: "auto"

        @JavascriptInterface
        fun setTtsVoice(name: String) { prefs.edit().putString("tts_voice", name).apply() }

        @JavascriptInterface
        fun getTtsVoices(): String = prefs.getString("tts_voices", "{}") ?: "{}"

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
