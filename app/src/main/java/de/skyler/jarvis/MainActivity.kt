package de.skyler.jarvis

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
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
        if (res.keys.any { it in Butler.PERMS || it.contains("LOCATION") } && JarvisService.running) JarvisService.start(this, JarvisService.ACTION_RELOAD)
        val mic = res[Manifest.permission.RECORD_AUDIO] ?: hasMic()
        if (!mic) send("error", JSONObject().put("text", "Ohne Mikrofon kann ich dich nicht hören."))
        else {
            startBackground()
            if (pendingTalk) startTalk()
        }
        pendingTalk = false
    }

    private val locPerm = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        if (res.values.any { it }) Here.refresh(this, force = true)
        else send("info", JSONObject().put("text", "Ohne Standort-Erlaubnis nutze ich deinen Wohnort."))
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

    private val textBrain by lazy { Brain(this) }   // für getippte Fragen

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        showOverLock(intent)
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
        web.webChromeClient = object : WebChromeClient() {
            // Handy-Kamera an den PC (nur in der offenen App): Kamera für die Seite freigeben
            override fun onPermissionRequest(request: android.webkit.PermissionRequest) {
                runOnUiThread {
                    if (request.resources.contains(android.webkit.PermissionRequest.RESOURCE_VIDEO_CAPTURE) &&
                        ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
                        request.grant(arrayOf(android.webkit.PermissionRequest.RESOURCE_VIDEO_CAPTURE))
                    else {
                        perms.launch(arrayOf(Manifest.permission.CAMERA))
                        request.deny()
                    }
                }
            }
        }
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

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        showOverLock(intent)
    }

    /** Vom Weckwort geöffnet: über dem Sperrbildschirm zeigen und Bildschirm anschalten (nur solange Jarvis offen ist). */
    private fun showOverLock(i: Intent?) {
        val wake = i?.getBooleanExtra("wake", false) == true
        if (Build.VERSION.SDK_INT >= 27) { setShowWhenLocked(wake); setTurnScreenOn(wake) }
        else {
            @Suppress("DEPRECATION") val f = android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or android.view.WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            if (wake) window.addFlags(f) else window.clearFlags(f)
        }
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

        /** Bedienungshilfen öffnen, damit "Jarvis – Schau mal hier" eingeschaltet werden kann. */
        @JavascriptInterface
        fun openScreenAccess() {
            try { startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } catch (_: Exception) {}
        }

        /** Getippte Frage: Jarvis antwortet leise als Text (gleiche Fähigkeiten wie gesprochen). */
        @JavascriptInterface
        fun askText(text: String) {
            val key = prefs.getString("groq_key", "") ?: ""
            if (key.isBlank()) { send("needkey", JSONObject()); return }
            Thread({
                send("state", JSONObject().put("state", "thinking"))
                val r = try { textBrain.handle(key, text.take(2000)) } catch (e: Exception) { "Das hat nicht geklappt: ${e.message ?: ""}" }
                send("agent", JSONObject().put("text", r))
                send("state", JSONObject().put("state", "ended"))
            }, "jarvis-text").start()
        }

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
            .put("themen_selbst", Themen.manual(this@MainActivity).joinToString(", "))
            .put("assistant_name", prefs.getString("assistant_name", ""))
            .put("anrede", prefs.getString("anrede", ""))
            .put("city", prefs.getString("city", "").let { if (it.isNullOrBlank()) Lage.city(this@MainActivity) else it })
            .put("address", prefs.getString("address", ""))
            .put("screen_ok", ScreenService.enabled()).put("has_gemini", !(prefs.getString("gemini_key", "") ?: "").isBlank())
            .put("calendars", Cal.writable(this@MainActivity)).put("calendar_id", prefs.getLong("calendar_id", -1L))
            .put("orte", prefs.getString("orte", "")).put("wege", prefs.getString("wege", "")).put("route_an", prefs.getString("route_an", ""))
            .put("use_location", prefs.getBoolean("use_location", false))
            .put("here", Here.name(this@MainActivity))
            .put("media_ok", Interests.hasAccess(this@MainActivity))
            .put("wichtig", prefs.getString("wichtig", Chats.DEFAULT)).put("absage", prefs.getString("absage", ""))
            .put("butler", prefs.getBoolean("butler", true)).put("butler_ok", Butler.ready(this@MainActivity))
            .put("files_ok", Chats.filesOk())
            .put("heim_wlan", prefs.getString("heim_wlan", "")).put("weg_auto", prefs.getBoolean("weg_auto", true))
            .put("losfahren", prefs.getBoolean("losfahren", true)).put("feste_wege", prefs.getString("feste_wege", null) ?: Alltag.FESTE_DEFAULT).put("ankunft", prefs.getString("ankunft", ""))
            .put("anzieh", prefs.getString("anzieh", "").let { if (it.isNullOrBlank()) Alltag.ANZIEH_DEFAULT else it })
            .put("brief_morgen", prefs.getBoolean("brief_morgen", true)).put("brief_abend", prefs.getBoolean("brief_abend", true))
            .put("brief_abend_zeit", prefs.getString("brief_abend_zeit", "21:00")).put("rueckblick", prefs.getBoolean("rueckblick", true))
            .put("rueckblick_zeit", prefs.getString("rueckblick_zeit", "18:00"))
            .apply { for (k in listOf("bi_wetter", "bi_anzieh", "bi_termine", "bi_mitnehmen")) put(k, prefs.getBoolean(k, true)) }
            .put("loc_always", android.os.Build.VERSION.SDK_INT < 29 || ContextCompat.checkSelfPermission(this@MainActivity,
                Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED)
            .put("loc_ok", ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED)
            .apply { for (k in listOf("lage_jump", "lage_zoom", "lage_spin", "lage_orbits", "lage_labels", "strand")) put(k, prefs.getBoolean(k, true)) }
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
                .apply { if (o.has("themen_selbst")) Themen.setManual(this@MainActivity, o.optString("themen_selbst")) }
                .putString("assistant_name", o.optString("assistant_name").trim())
                .putString("anrede", o.optString("anrede").trim())
                .putString("city", o.optString("city").trim())
                .putString("address", o.optString("address").trim())
                .putLong("calendar_id", o.optLong("calendar_id", -1L))
                .apply { o.optString("gemini_key").trim().takeIf { it.isNotBlank() }?.let { putString("gemini_key", it) } }
                .putString("orte", o.optString("orte").trim()).putString("wege", o.optString("wege").trim())
                .putString("route_an", o.optString("route_an").trim())
                .putString("wichtig", o.optString("wichtig").trim()).putString("absage", o.optString("absage").trim())
                .putBoolean("butler", o.optBoolean("butler", true))
                .putString("heim_wlan", o.optString("heim_wlan").trim()).putBoolean("weg_auto", o.optBoolean("weg_auto", true))
                .putBoolean("losfahren", o.optBoolean("losfahren", true)).putString("feste_wege", o.optString("feste_wege").trim()).putString("ankunft", o.optString("ankunft").trim())
                .putString("anzieh", o.optString("anzieh").trim().let { if (it == Alltag.ANZIEH_DEFAULT) "" else it })
                .putBoolean("brief_morgen", o.optBoolean("brief_morgen", true)).putBoolean("brief_abend", o.optBoolean("brief_abend", true))
                .putString("brief_abend_zeit", o.optString("brief_abend_zeit", "21:00").trim().ifBlank { "21:00" })
                .putBoolean("rueckblick", o.optBoolean("rueckblick", true))
                .putString("rueckblick_zeit", o.optString("rueckblick_zeit", "18:00").trim().ifBlank { "18:00" })
                .apply { for (k in listOf("bi_wetter", "bi_anzieh", "bi_termine", "bi_mitnehmen")) putBoolean(k, o.optBoolean(k, true)) }
                .putBoolean("use_location", o.optBoolean("use_location", false))
                .apply { for (k in listOf("lage_jump", "lage_zoom", "lage_spin", "lage_orbits", "lage_labels", "strand")) putBoolean(k, o.optBoolean(k, true)) }
                .apply()
            Lage.updateHome(this@MainActivity) { send("home", JSONObject()) }
            Link.pushSettings(this@MainActivity)   // gleiche Einstellungen am PC
            if (o.optBoolean("use_location", false)) Here.refresh(this@MainActivity, force = true)
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

        /** Fernzugriff: Adresse des PCs im Tailscale-Netz + Schlüssel (refresh = beim PC nachfragen). */
        @JavascriptInterface
        fun fernInfo(refresh: Boolean): String = Link.fernInfo(this@MainActivity, refresh).toString()

        /** Aktuelles WLAN als Heim-WLAN (braucht genauen Standort, sonst verrät Android den Namen nicht). */
        @JavascriptInterface
        fun currentWifi(): String {
            if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                runOnUiThread { perms.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)) }
                return ""
            }
            return Alltag.ssid(this@MainActivity) ?: ""
        }

        /** Standort "immer erlauben" (für Zuhause/weg, Ankunft, Fahrten lernen). Erst genau, dann im Hintergrund. */
        @JavascriptInterface
        fun askLocationAlways() = runOnUiThread {
            prefs.edit().putBoolean("use_location", true).apply()
            if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED)
                perms.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
            else if (android.os.Build.VERSION.SDK_INT >= 29) perms.launch(arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION))
        }

        /** Anruf-Butler: Telefon, Anrufliste, Anrufe beenden, SMS. */
        @JavascriptInterface
        fun askButler() = runOnUiThread {
            val missing = Butler.PERMS.filter { ContextCompat.checkSelfPermission(this@MainActivity, it) != PackageManager.PERMISSION_GRANTED }
            if (missing.isNotEmpty()) perms.launch(missing.toTypedArray())
        }

        /** Sprachnachrichten: "Zugriff auf alle Dateien" (nur damit Jarvis die WhatsApp-Sprachnachrichten lesen kann). */
        @JavascriptInterface
        fun askFiles() = runOnUiThread {
            if (android.os.Build.VERSION.SDK_INT >= 30) try {
                startActivity(Intent(android.provider.Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName")))
            } catch (_: Exception) {
                try { startActivity(Intent(android.provider.Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)) } catch (_: Exception) {}
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
                } catch (e: Exception) { send("lage_error", JSONObject().put("text", e.message ?: "Lage nicht erreichbar.").put("ort", ort)) }
            }, "jarvis-lage").start()
        }

        @JavascriptInterface
        fun askLocation() = runOnUiThread {
            locPerm.launch(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION))
        }

        /** Zuhause-Punkt (aus Wohnort/Adresse der Einstellungen) als {lat, lon} oder null */
        @JavascriptInterface
        fun home(): String {
            val p = prefs; val want = "${(p.getString("address", "") ?: "").trim()}|${Lage.city(this@MainActivity)}"
            if (p.getString("home_for", "") != want) Lage.updateHome(this@MainActivity) { send("home", JSONObject()) }
            val la = p.getFloat("home_lat", 999f); val lo = p.getFloat("home_lon", 999f)
            return if (la > 90f) "null" else JSONObject().put("lat", la.toDouble()).put("lon", lo.toDouble()).toString()
        }

        /** Wo das Handy gerade ist (nur wenn erlaubt) */
        @JavascriptInterface
        fun here(): String {
            Here.refresh(this@MainActivity)
            val h = Here.latLon(this@MainActivity) ?: return "null"
            return JSONObject().put("lat", h.first).put("lon", h.second).put("name", Here.name(this@MainActivity)).toString()
        }

        /** Bahndaten der Satelliten (frisch alle 12 Stunden; neue Daten kommen als Ereignis "tle") */
        @JavascriptInterface
        fun tle(): String {
            Sats.refresh(this@MainActivity) { t -> send("tle", JSONObject().put("text", t)) }
            return Sats.cached(this@MainActivity)
        }

        /** Ort -> Koordinaten aus dem Speicher (sonst null und im Hintergrund suchen) */
        @JavascriptInterface
        fun geocode(q: String): String {
            val hit = Lage.geocodeCached(this@MainActivity, q)
            if (hit == null) Thread({ try { Lage.geocode(this@MainActivity, q) } catch (_: Exception) {} }).start()
            return hit?.let { JSONObject().put("lat", it.first).put("lon", it.second).toString() } ?: "null"
        }

        /** Interessen lernen: Tipp auf eine Meldung (klick), "mehr davon" (mehr), "weniger" (weniger) */
        @JavascriptInterface
        fun lageNote(kind: String, text: String) { Themen.note(this@MainActivity, kind, text) }

        /** Gelernte + eigene Themen für die Einstellungen */
        @JavascriptInterface
        fun themen(): String = org.json.JSONArray(Themen.list(this@MainActivity)).toString()

        @JavascriptInterface
        fun themaWeg(name: String) { Themen.remove(this@MainActivity, name) }

        @JavascriptInterface
        fun themenSelbst(csv: String) { Themen.setManual(this@MainActivity, csv) }

        /** Befehl an den PC (Fernbedienung). Antwort kommt als Ereignis "pc_reply". */
        @JavascriptInterface
        fun pcCmd(json: String) {
            val cmd = try { JSONObject(json) } catch (_: Exception) { return }
            if (!Link.paired(this@MainActivity)) { send("pc_reply", JSONObject().put("ok", false).put("text", "Handy und PC sind noch nicht gekoppelt (Einstellungen → Zuhören → Kopplungscode).")); return }
            Thread({
                val r = try { Link.command(this@MainActivity, cmd) } catch (e: Exception) { null }
                if (r == null) send("pc_reply", JSONObject().put("ok", false).put("text", "Der PC antwortet nicht. Läuft Jarvis am PC?"))
                else {
                    r.optJSONObject("status")?.let { prefs.edit().putString("pc_status", it.toString()).apply() }
                    send("pc_reply", r)
                }
            }, "jarvis-pc").start()
        }

        /** Letzter bekannter PC-Status (sofort) – und im Hintergrund frisch holen (force = PC direkt fragen). */
        @JavascriptInterface
        fun pcStatus(force: Boolean): String {
            if (Link.paired(this@MainActivity)) Thread({
                try {
                    val r = if (force) Link.command(this@MainActivity, JSONObject().put("type", "status")) else Link.latestStatus(this@MainActivity)
                    r?.optJSONObject("status")?.let {
                        prefs.edit().putString("pc_status", it.toString()).apply()
                        send("pc_status", it)
                    } ?: send("pc_status", JSONObject().put("online", false).put("unknown", true))
                } catch (_: Exception) {}
            }, "jarvis-pcstatus").start()
            return prefs.getString("pc_status", "") ?: ""
        }

        @JavascriptInterface
        fun paired(): Boolean = Link.paired(this@MainActivity)

        /** Handy-Kacheln: Musik/Videos/WhatsApp öffnen, Wecker/Navigation/Anruf über die normalen Apps */
        @JavascriptInterface
        fun openTile(kind: String) = runOnUiThread {
            val pm = packageManager
            fun launch(vararg pkgs: String): Boolean { for (p in pkgs) { val i = pm.getLaunchIntentForPackage(p) ?: continue; startActivity(i); return true }; return false }
            try {
                when (kind) {
                    "musik" -> if (!launch("deezer.android.app", "com.spotify.music", "com.google.android.apps.youtube.music")) startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://www.deezer.com")))
                    "videos" -> if (!launch("com.google.android.youtube")) startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com")))
                    "whatsapp" -> if (!launch("com.whatsapp")) startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://web.whatsapp.com")))
                    "wecker" -> startActivity(Intent(android.provider.AlarmClock.ACTION_SHOW_ALARMS))
                    "navigation" -> startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=")).setPackage("com.google.android.apps.maps").takeIf { it.resolveActivity(pm) != null }
                        ?: Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0")))
                    "anrufen" -> startActivity(Intent(Intent.ACTION_DIAL))
                }
            } catch (_: Exception) { send("info", JSONObject().put("text", "Das konnte ich nicht öffnen.")) }
        }

        @JavascriptInterface
        fun lageFavorites(): String { Lage.warmFavorites(this@MainActivity); return org.json.JSONArray(Lage.favorites(this@MainActivity)).toString() }

        @JavascriptInterface
        fun city(): String = Lage.city(this@MainActivity)

        @JavascriptInterface
        fun version(): String = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: ""
        } catch (_: Exception) { "" }
    }
}
