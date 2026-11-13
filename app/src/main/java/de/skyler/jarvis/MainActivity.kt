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

    private val perms = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        val mic = res[Manifest.permission.RECORD_AUDIO] ?: hasMic()
        if (!mic) send("error", JSONObject().put("text", "Ohne Mikrofon kann ich dich nicht hören."))
        else {
            startBackground()
            if (pendingTalk) startTalk()
        }
        pendingTalk = false
    }

    private fun hasMic() = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private val busListener: (String, JSONObject) -> Unit = { type, data -> send(type, data) }

    private fun askPermissions() {
        val want = mutableListOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.READ_CONTACTS, Manifest.permission.CALL_PHONE,
            Manifest.permission.READ_CALENDAR, Manifest.permission.WRITE_CALENDAR)
        if (android.os.Build.VERSION.SDK_INT >= 33) want.add(Manifest.permission.POST_NOTIFICATIONS)
        val missing = want.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) startBackground() else perms.launch(missing.toTypedArray())
    }

    /** Hintergrund-Jarvis (Aktivierungswort) starten, wenn eingeschaltet. */
    private fun startBackground() {
        if (!hasMic()) return
        if (prefs.getBoolean("background", true)) JarvisService.start(this)
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
        Bus.add(busListener)
        askPermissions()
    }

    override fun onResume() {
        super.onResume()
        JarvisService.appVisible = true
        Bus.emit("app_visible", JSONObject().put("on", true))
    }

    override fun onPause() {
        JarvisService.appVisible = false
        Bus.emit("app_visible", JSONObject().put("on", false))
        super.onPause()
    }

    override fun onDestroy() {
        talk?.stop()
        Bus.remove(busListener)
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
        if (!hasMic()) { pendingTalk = true; askPermissions(); return }
        if (running()) return
        if (prefs.getString("groq_key", "").isNullOrBlank() && prefs.getString("voice_mode", "free") != "auto") {
            send("needkey", JSONObject()); return
        }
        if (prefs.getString("voice_mode", "free") == "auto" &&
            prefs.getLong("eleven_off_until", 0L) < System.currentTimeMillis()) {
            // George (ElevenLabs): Mikrofon vom Hintergrund-Jarvis kurz freigeben
            JarvisService.start(this, JarvisService.ACTION_PAUSE)
            talk = LiveTalk(this, AGENT_ID, Prompts.voicePrompt(this)) { type, data ->
                if (type == "quota") {
                    prefs.edit().putLong("eleven_off_until", System.currentTimeMillis() + 6 * 3600_000L).apply()
                    runOnUiThread { talk = null; JarvisService.start(this, JarvisService.ACTION_TALK) }
                } else {
                    if (type == "state" && data.optString("state") == "ended") JarvisService.start(this, JarvisService.ACTION_RESUME)
                    send(type, data)
                }
            }.also { it.start() }
            return
        }
        JarvisService.start(this, JarvisService.ACTION_TALK)   // kostenlos: Gespräch über den Hintergrund-Jarvis
    }

    private fun stopTalk() {
        if (talk != null) {
            talk?.stop(); talk = null
            JarvisService.start(this, JarvisService.ACTION_RESUME)
        } else if (JarvisService.running) {
            startService(Intent(this, JarvisService::class.java).setAction(JarvisService.ACTION_PAUSE))
            JarvisService.start(this, JarvisService.ACTION_RESUME)
        }
        send("state", JSONObject().put("state", "ended"))
    }

    private fun running() = talk?.isRunning == true ||
        (JarvisService.running && Bus.lastState != "ended" && Bus.lastState != "idle")

    inner class Bridge {
        @JavascriptInterface
        fun startTalk() = runOnUiThread { this@MainActivity.startTalk() }

        @JavascriptInterface
        fun stopTalk() = runOnUiThread { this@MainActivity.stopTalk() }

        @JavascriptInterface
        fun toggleTalk() = runOnUiThread {
            if (running()) this@MainActivity.stopTalk() else this@MainActivity.startTalk()
        }

        /** Tipp auf die Kugel während er spricht: wie Tippen auf die kleine Kugel. */
        @JavascriptInterface
        fun interrupt() = runOnUiThread { JarvisService.start(this@MainActivity, JarvisService.ACTION_TALK) }

        @JavascriptInterface
        fun getSettings(): String = JSONObject()
            .put("wake_words", prefs.getString("wake_words", "jarvis"))
            .put("wake_level", prefs.getInt("wake_level", 1))
            .put("wake_cloud", prefs.getBoolean("wake_cloud", false))
            .put("background", prefs.getBoolean("background", true))
            .put("overlay", android.provider.Settings.canDrawOverlays(this@MainActivity))
            .put("usage", ScreenColors.hasUsageAccess(this@MainActivity))
            .put("media", Interests.summaryForSettings(this@MainActivity))
            .put("model", VoskModel.ready(this@MainActivity))
            .put("link_code", prefs.getString("link_code", ""))
            .put("jarvis_volume", prefs.getInt("jarvis_volume", 70))
            .put("synced", prefs.getLong("snap_got", 0L))
            .put("facts", Memory.facts(this@MainActivity).size)
            .put("lage_orte", prefs.getString("lage_orte", "Stuttgart"))
            .toString()

        @JavascriptInterface
        fun saveSettings(json: String) {
            val o = JSONObject(json)
            prefs.edit()
                .putString("wake_words", o.optString("wake_words", "jarvis").ifBlank { "jarvis" })
                .putInt("wake_level", o.optInt("wake_level", 1))
                .putBoolean("wake_cloud", o.optBoolean("wake_cloud", false))
                .putBoolean("background", o.optBoolean("background", true))
                .putString("link_code", o.optString("link_code", "").trim().uppercase())
                .putInt("jarvis_volume", o.optInt("jarvis_volume", 70).coerceIn(10, 100))
                .putString("lage_orte", o.optString("lage_orte", "Stuttgart").trim())
                .apply()
            if (Link.paired(this@MainActivity) && !JarvisService.running) Thread({
                try { if (Link.pull(this@MainActivity)) send("synced", JSONObject().put("text", "Gedächtnis vom PC übernommen.")) }
                catch (_: Exception) { send("synced", JSONObject().put("text", "PC gerade nicht erreichbar.")) }
            }).start()
            runOnUiThread {
                if (o.optBoolean("background", true)) {
                    startBackground(); JarvisService.start(this@MainActivity, JarvisService.ACTION_RELOAD)
                } else if (JarvisService.running) {
                    startService(Intent(this@MainActivity, JarvisService::class.java).setAction(JarvisService.ACTION_STOP))
                }
            }
        }

        /** Ein/Aus-Knopf: an = im Hintergrund auf das Aktivierungswort hören, aus = Dienst ganz beenden. */
        @JavascriptInterface
        fun setPower(on: Boolean) {
            prefs.edit().putBoolean("background", on).apply()
            runOnUiThread {
                if (on) {
                    if (!hasMic()) askPermissions() else JarvisService.start(this@MainActivity)
                } else {
                    talk?.stop(); talk = null
                    if (JarvisService.running)
                        startService(Intent(this@MainActivity, JarvisService::class.java).setAction(JarvisService.ACTION_STOP))
                }
            }
        }

        /** Nutzungszugriff: damit der Leuchtrand die Farben der App annehmen kann, die gerade vorne ist. */
        @JavascriptInterface
        fun askUsage() = runOnUiThread {
            try {
                startActivity(Intent(android.provider.Settings.ACTION_USAGE_ACCESS_SETTINGS, Uri.parse("package:$packageName")))
            } catch (_: Exception) {
                try { startActivity(Intent(android.provider.Settings.ACTION_USAGE_ACCESS_SETTINGS)) } catch (_: Exception) {}
            }
        }

        /** "Was ich schaue und höre": Benachrichtigungszugriff, damit Jarvis sieht, was gerade läuft. */
        @JavascriptInterface
        fun askMedia() = runOnUiThread {
            try { startActivity(Intent(android.provider.Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) } catch (_: Exception) {}
        }

        @JavascriptInterface
        fun askOverlay() = runOnUiThread {
            try {
                startActivity(Intent(android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:$packageName")))
            } catch (_: Exception) {}
        }

        @JavascriptInterface
        fun askBattery() = runOnUiThread {
            try {
                @SuppressLint("BatteryLife")
                val i = Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
                startActivity(i)
            } catch (_: Exception) {}
        }

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
        fun getVoiceMode(): String = prefs.getString("voice_mode", "free") ?: "free"

        @JavascriptInterface
        fun setTtsVoice(name: String) {
            prefs.edit().putString("tts_voice", name).apply()
            runOnUiThread { if (JarvisService.running) JarvisService.start(this@MainActivity, JarvisService.ACTION_RELOAD) }
        }

        @JavascriptInterface
        fun getTtsVoices(): String = prefs.getString("tts_voices", "{}") ?: "{}"

        @JavascriptInterface
        fun openUrl(url: String) = runOnUiThread {
            try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } catch (_: Exception) {}
        }

        /** Lage für die Lage-Seite: sofort den letzten Stand, dann (wenn älter als 15 Minuten) frisch im Hintergrund. */
        @JavascriptInterface
        fun getLage(ort: String, force: Boolean) {
            val ctx = this@MainActivity
            Lage.cached(ctx, ort)?.let { send("lage", JSONObject().put("data", it).put("tour", false)) }
            val key = prefs.getString("groq_key", "") ?: ""
            if (key.isBlank()) { send("lage_error", JSONObject().put("text", "Für die Lage brauche ich deinen Groq-Schlüssel (Einstellungen).")); return }
            Thread({
                try {
                    val d = Lage.get(ctx, key, ort, if (force) 0L else Lage.MAX_AGE)
                    send("lage", JSONObject().put("data", d).put("tour", false))
                } catch (e: Exception) { send("lage_error", JSONObject().put("text", e.message ?: "Lage nicht erreichbar.")) }
            }, "jarvis-lage").start()
        }

        @JavascriptInterface
        fun lageFavorites(): String = org.json.JSONArray(Lage.favorites(this@MainActivity)).toString()

        @JavascriptInterface
        fun city(): String = Lage.city(this@MainActivity)

        @JavascriptInterface
        fun version(): String = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: ""
        } catch (_: Exception) { "" }
    }
}
