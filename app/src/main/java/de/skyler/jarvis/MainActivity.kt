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
import org.json.JSONArray
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

    /** Sticker aus der Galerie: auf 512×512 verkleinern und als PNG (Base64) an die Seite – die schickt es an den PC. */
    private val pickSticker = registerForActivityResult(ActivityResultContracts.GetContent()) { uri -> if (uri != null) stickerFromUri(uri) }

    /** Sticker direkt aus der Handy-Tastatur (Samsung/Gboard): kleines Eingabefeld, das Bilder/Sticker annimmt. */
    private fun stickerKeyboard() {
        val et = android.widget.EditText(this).apply {
            hint = "Hier den Sticker aus der Tastatur antippen"
            setTextColor(Color.WHITE); setHintTextColor(Color.GRAY)
            setPadding(40, 30, 40, 30)
        }
        var dlg: android.app.AlertDialog? = null
        ViewCompat.setOnReceiveContentListener(et, arrayOf("image/*")) { _, payload ->
            val clip = payload.clip
            val uri = (0 until clip.itemCount).firstNotNullOfOrNull { clip.getItemAt(it).uri }
            if (uri != null) {
                // gleich hier lesen: die Leseerlaubnis der Tastatur gilt nur kurz
                val bytes = try { contentResolver.openInputStream(uri)?.use { it.readBytes() } } catch (_: Exception) { null }
                if (bytes != null) stickerFromBytes(bytes) else send("sticker_img", JSONObject().put("err", "Den Sticker konnte ich nicht lesen."))
                dlg?.dismiss()
                null
            } else payload
        }
        dlg = android.app.AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
            .setTitle("Sticker aus der Tastatur")
            .setMessage("Tipp ins Feld, öffne in der Tastatur die Sticker und tipp einen an.")
            .setView(et).setNegativeButton("Abbrechen", null).create()
        dlg.setOnShowListener {
            et.requestFocus()
            et.postDelayed({ (getSystemService(INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager).showSoftInput(et, 0) }, 200)
        }
        dlg.show()
    }

    private fun stickerFromUri(uri: Uri) {
        Thread({
            val b = try { contentResolver.openInputStream(uri)?.use { it.readBytes() } } catch (_: Exception) { null }
            if (b != null) stickerFromBytes(b) else send("sticker_img", JSONObject().put("err", "Bild ging nicht"))
        }, "sticker-img").start()
    }

    private fun stickerFromBytes(bytes: ByteArray) {
        Thread({
            try {
                val bmp = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: throw RuntimeException("Das Bild kann ich nicht öffnen.")
                val sc = minOf(512f / bmp.width, 512f / bmp.height, 1f)
                val small = android.graphics.Bitmap.createScaledBitmap(bmp, maxOf(1, (bmp.width * sc).toInt()), maxOf(1, (bmp.height * sc).toInt()), true)
                val out = java.io.ByteArrayOutputStream()
                small.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, out)
                send("sticker_img", JSONObject().put("data", android.util.Base64.encodeToString(out.toByteArray(), android.util.Base64.NO_WRAP)))
            } catch (e: Exception) { send("sticker_img", JSONObject().put("err", e.message ?: "Bild ging nicht")) }
        }, "sticker-img").start()
    }

    private val locPerm = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        if (res.values.any { it }) Here.refresh(this, force = true)
        else send("info", JSONObject().put("text", "Ohne Standort-Erlaubnis nutze ich deinen Wohnort."))
    }

    // Samsung Health über Health Connect: Lese-Rechte anfragen
    private val healthPerm = registerForActivityResult(androidx.health.connect.client.PermissionController.createRequestPermissionResultContract()) { got ->
        send("health", JSONObject().put("connected", got.any { it in Health.PERMS }).put("all", got.containsAll(Health.PERMS)))
    }

    private fun hasMic() = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private val busListener: (String, JSONObject) -> Unit = { type, data ->
        if (type == "read_next") ReadAloud.next() else if (type == "read_stop") ReadAloud.stop() else send(type, data)
    }

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
        JarvisService.start(this)   // läuft immer (Briefings, Erinnerungen); der Schalter macht nur Mikro + Stimme aus
    }

    private val textBrain by lazy { Brain(this) }   // für getippte Fragen

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        showOverLock(intent)
        getSharedPreferences("jarvis", MODE_PRIVATE).let { p ->   // einmalig (Wunsch 14.11.): alle Wecker von Jarvis raus, Schultags-Plan bleibt
            if (!p.getBoolean("zeiten_v2", false))   // Wunsch 14.11.: Tagesabschluss 20:00, Wochenrückblick 20:30
                p.edit().putBoolean("zeiten_v2", true).putString("brief_abend_zeit", "20:00").putString("rueckblick_zeit", "20:30").apply()
            if (!p.getBoolean("wecker_aufraeumen_1", false)) {
                p.edit().putBoolean("wecker_aufraeumen_1", true).apply()
                Thread { try { Wecker.off(this, emptyList()) } catch (_: Exception) {} }.start()
            }
        }
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
        pendingFeed = intent?.getStringExtra("feed")
        if (intent?.getBooleanExtra("talk", false) == true) pendingWidgetTalk = true
        if (intent?.getBooleanExtra("outfit", false) == true) pendingOutfit = true
        web.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) {
                pageReady = true
                pendingFeed?.let { id -> pendingFeed = null; send("feed_open", JSONObject().put("id", id)) }
                if (pendingOutfit) { pendingOutfit = false; web.postDelayed({ send("outfit_ask", JSONObject()) }, 1500) }
                if (pendingWidgetTalk) { pendingWidgetTalk = false; web.postDelayed({ send("widget_talk", JSONObject()) }, 900) }
            }
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
        handleShare(intent)
    }

    @Volatile private var pendingFeed: String? = null
    @Volatile private var pageReady = false

    /** WhatsApp-Export (über „Teilen“ oder die Dateiauswahl) einlesen -> Schreibstil lernen. */
    private val pickExport = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris -> if (uris.isNotEmpty()) importStil(uris) }

    private fun importStil(uris: List<Uri>) {
        Thread({
            var n = 0; var fail = 0
            for (u in uris) try {
                val name = try { contentResolver.query(u, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c -> if (c.moveToFirst()) c.getString(0) else null } } catch (_: Exception) { null } ?: (u.lastPathSegment ?: "")
                val txt = contentResolver.openInputStream(u)?.use { inp ->
                    if (name.endsWith(".zip", true)) java.util.zip.ZipInputStream(inp).use { z ->
                        var e = z.nextEntry; var t = ""
                        while (e != null) { if (e.name.endsWith(".txt")) { t = z.readBytes().toString(Charsets.UTF_8); break }; e = z.nextEntry }
                        t
                    } else inp.readBytes().toString(Charsets.UTF_8)
                } ?: ""
                val r = Stil.importExport(this, name.removeSuffix(".zip"), txt)
                if (r > 0) n += r else fail++
            } catch (e: Exception) { fail++ }
            val msg = if (n > 0) "Schreibstil: $n Nachrichten von dir gelernt." else "Den Export konnte ich nicht lesen – nimm in WhatsApp „Chat exportieren“ → „Ohne Medien“ bei einem Einzelchat."
            runOnUiThread { android.widget.Toast.makeText(this, msg, android.widget.Toast.LENGTH_LONG).show() }
            send("stil_import", JSONObject().put("n", n).put("text", msg))
        }, "jarvis-stil-import").start()
    }

    private fun handleShare(i: Intent?) {
        if (i == null || (i.action != Intent.ACTION_SEND && i.action != Intent.ACTION_SEND_MULTIPLE)) return
        @Suppress("DEPRECATION") val uris: List<Uri> = if (i.action == Intent.ACTION_SEND_MULTIPLE) (i.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM) ?: arrayListOf())
            else listOfNotNull(i.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
        if (uris.isNotEmpty()) importStil(uris.filter { true })
        else i.getStringExtra(Intent.EXTRA_TEXT)?.takeIf { it.length > 200 }?.let { t ->
            Thread { val r = Stil.importExport(this, i.getStringExtra(Intent.EXTRA_SUBJECT) ?: "", t)
                runOnUiThread { android.widget.Toast.makeText(this, if (r > 0) "Schreibstil: $r Nachrichten gelernt." else "Konnte ich nicht lesen.", android.widget.Toast.LENGTH_LONG).show() } }.start()
        }
        i.action = Intent.ACTION_MAIN
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleShare(intent)
        showOverLock(intent)
        intent.getStringExtra("feed")?.let { id -> if (pageReady) send("feed_open", JSONObject().put("id", id)) else pendingFeed = id }
        if (intent.getBooleanExtra("talk", false)) { if (pageReady) send("widget_talk", JSONObject()) else pendingWidgetTalk = true }
        if (intent.getBooleanExtra("outfit", false)) { if (pageReady) send("outfit_ask", JSONObject()) else pendingOutfit = true }
    }
    @Volatile private var pendingWidgetTalk = false
    @Volatile private var pendingOutfit = false

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
        try { Link.poke() } catch (_: Exception) {}
        try { Konto.tick(this) } catch (_: Exception) {}
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

    private val fernBusy = java.util.concurrent.atomic.AtomicBoolean(false)
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
            .put("background", prefs.getBoolean("background", !Konto.parallel(this@MainActivity)))
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
            .put("losfahren", prefs.getBoolean("losfahren", true)).put("ankunft", prefs.getString("ankunft", ""))
            .put("anzieh", prefs.getString("anzieh", "").let { if (it.isNullOrBlank()) Alltag.ANZIEH_DEFAULT else it })
            .put("brief_morgen", prefs.getBoolean("brief_morgen", true)).put("brief_abend", prefs.getBoolean("brief_abend", true))
            .put("brief_abend_zeit", prefs.getString("brief_abend_zeit", "20:00")).put("rueckblick", prefs.getBoolean("rueckblick", true))
            .put("bilanz", prefs.getBoolean("bilanz", true)).put("schlaf_tipp", prefs.getBoolean("schlaf_tipp", true)).put("ticket_art", prefs.getString("ticket_art", "erwachsen"))
            .put("termin_erinnern", prefs.getBoolean("termin_erinnern", true)).put("termin_vorher", prefs.getInt("termin_vorher", 15)).put("bilanz_zeit", prefs.getString("bilanz_zeit", "22:00"))
            .put("rueckblick_zeit", prefs.getString("rueckblick_zeit", "20:30"))
            .put("wecker_an", prefs.getBoolean("wecker_an", true)).put("wecker_schule", prefs.getString("wecker_schule", "7:10"))
            .put("wecker_we", prefs.getString("wecker_we", "")).put("wecker_vorher", Wecker.offsets(this@MainActivity).joinToString(", "))
            .put("wecker_tage", Wecker.tage(this@MainActivity))
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
                .putBoolean("losfahren", o.optBoolean("losfahren", true)).putString("ankunft", o.optString("ankunft").trim())
                .putString("anzieh", o.optString("anzieh").trim().let { if (it == Alltag.ANZIEH_DEFAULT) "" else it })
                .putBoolean("brief_morgen", o.optBoolean("brief_morgen", true)).putBoolean("brief_abend", o.optBoolean("brief_abend", true))
                .putString("brief_abend_zeit", o.optString("brief_abend_zeit", "20:00").trim().ifBlank { "20:00" })
                .putBoolean("rueckblick", o.optBoolean("rueckblick", true))
                .putBoolean("bilanz", o.optBoolean("bilanz", true)).putBoolean("schlaf_tipp", o.optBoolean("schlaf_tipp", true)).putString("ticket_art", o.optString("ticket_art", "erwachsen").ifBlank { "erwachsen" })
                .putBoolean("termin_erinnern", o.optBoolean("termin_erinnern", true)).putInt("termin_vorher", o.optInt("termin_vorher", 15).coerceIn(0, 180)).putString("bilanz_zeit", o.optString("bilanz_zeit", "22:00").trim().ifBlank { "22:00" })
                .putString("rueckblick_zeit", o.optString("rueckblick_zeit", "20:30").trim().ifBlank { "20:30" })
                .putBoolean("wecker_an", o.optBoolean("wecker_an", true)).putString("wecker_schule", o.optString("wecker_schule").trim())
                .putString("wecker_we", o.optString("wecker_we").trim()).putString("wecker_vorher", o.optString("wecker_vorher").trim().ifBlank { Wecker.VORHER_DEFAULT })
                .apply { o.optJSONObject("wecker_tage")?.let { t -> if (t.toString() != Wecker.tage(this@MainActivity).toString()) remove("wecker_tag"); putString("wecker_tage", t.toString()) } }
                .apply { if (o.optString("wecker_schule").trim() != prefs.getString("wecker_schule", "7:10") || o.optString("wecker_we").trim() != prefs.getString("wecker_we", "")) remove("wecker_tag") }
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
                } else {
                    JarvisService.start(this@MainActivity, JarvisService.ACTION_STOP)
                }
            }
        }

        /** Ein/Aus-Knopf: an = im Hintergrund auf das Aktivierungswort hören, aus = Dienst ganz beenden. */
        @JavascriptInterface
        fun setPower(on: Boolean) {
            prefs.edit().putBoolean("background", on).apply()
            runOnUiThread {
                if (on) {
                    if (!hasMic()) askPermissions() else JarvisService.start(this@MainActivity, JarvisService.ACTION_MIC_ON)
                } else {
                    talk?.stop(); talk = null
                    JarvisService.start(this@MainActivity, JarvisService.ACTION_STOP)
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
        fun fernInfo(refresh: Boolean): String {   // Nachfragen beim PC im Hintergrund (sonst hängt die Seite, wenn der PC aus ist)
            if (refresh && fernBusy.compareAndSet(false, true)) Thread({
                try { Link.fernInfo(this@MainActivity, true); send("fern_ready", JSONObject()) } catch (_: Exception) {} finally { fernBusy.set(false) }
            }, "jarvis-fern").start()
            return Link.fernInfo(this@MainActivity, false).toString()
        }

        /** Mitteilung vorlesen (Punkte als JSON-Liste), weiter, stopp */
        @JavascriptInterface
        fun readStart(json: String) = ReadAloud.start(this@MainActivity, json)

        @JavascriptInterface
        fun readNext() = ReadAloud.next()

        @JavascriptInterface
        fun readStop() = ReadAloud.stop()

        /** Mitteilungen */
        @JavascriptInterface
        fun feedList(): String = Feed.list(this@MainActivity).toString()

        @JavascriptInterface
        fun feedGet(id: String): String { Vorschlag.usedFeed(this@MainActivity, id); return Feed.get(this@MainActivity, id)?.toString() ?: "null" }

        /** Test-SMS an eine Person aus den Kontakten. */
        @JavascriptInterface
        fun testSms(wer: String): String {
            val w = wer.trim().ifBlank { return "Wem soll ich die Test-SMS schicken?" }
            val nr = Actions(this@MainActivity).number(w) ?: return "„$w“ finde ich nicht in deinen Kontakten."
            val ok = Butler.sms(this@MainActivity, nr, "Hier ist Jarvis, das ist nur ein Test.", w)
            return if (ok) "Test-SMS an $w ist raus." else "Die SMS ging nicht raus – erlaube SMS in den Einstellungen unter Leute."
        }

        @JavascriptInterface
        fun getGassi(): String = JSONObject().put("an", Gassi.on(this@MainActivity)).put("sms", Gassi.smsOn(this@MainActivity))
            .put("wer", Gassi.who(this@MainActivity)).put("text", Gassi.text(this@MainActivity)).toString()

        @JavascriptInterface
        fun setGassi(an: Boolean, sms: Boolean, wer: String, text: String) {
            prefs.edit().putBoolean("gassi_an", an).putBoolean("gassi_sms", sms).putString("gassi_wer", wer.trim()).putString("gassi_text", text.trim()).apply()
        }

        @JavascriptInterface
        fun gassiTestSms(): String = Gassi.send(this@MainActivity, true)

        @JavascriptInterface
        fun gassiStatus(): String = Gassi.status(this@MainActivity)

        @JavascriptInterface
        fun gassiShare(): String = Gassi.shareToPc(this@MainActivity)

        @JavascriptInterface
        fun coreFacts(): String = org.json.JSONArray(Memory.facts(this@MainActivity).filter { Memory.isCore(it) }.takeLast(16)).toString()

        @JavascriptInterface
        fun factEdit(old: String, text: String): String = Memory.edit(this@MainActivity, old, text)

        @JavascriptInterface
        fun factForget(old: String): String = Memory.forget(this@MainActivity, old)

        @JavascriptInterface
        fun getFlag(k: String, def: Boolean): Boolean = prefs.getBoolean(k, def)

        @JavascriptInterface
        fun setFlag(k: String, v: Boolean) { if (k in listOf("melden", "aufsteh_check", "regen_warnung")) prefs.edit().putBoolean(k, v).apply() }

        @JavascriptInterface
        fun gmailGet(): String = JSONObject().put("user", Mail.user(this@MainActivity)).put("ok", Mail.configured(this@MainActivity)).toString()

        @JavascriptInterface
        fun gmailSet(user: String, pw: String) { Mail.set(this@MainActivity, user, pw) }

        @JavascriptInterface
        fun gmailTest() { Thread({ send("gmail_test", Mail.test(this@MainActivity)) }, "jarvis-mailtest").start() }

        @JavascriptInterface
        fun meldenTest() { Thread({ try { Alltag.checkInTest(this@MainActivity) } catch (_: Exception) {} }, "jarvis-meldetest").start() }

        @JavascriptInterface
        fun watchTest() { Thread({ Thread.sleep(10_000); Alltag.watchTest(this@MainActivity) }, "jarvis-uhrtest").start() }   // 10 s Zeit zum Sperren (Uhr zeigt nur bei gesperrtem Handy)

        @JavascriptInterface
        fun schuleGet(): String {
            val p = Melden.schoolPlace(this@MainActivity)
            return JSONObject().put("ort", p?.let { "%.4f, %.4f".format(java.util.Locale.US, it.lat, it.lon) } ?: "").put("auto", prefs.getBoolean("schule_auto", true))
                .put("da", try { Melden.reallyAtSchool(this@MainActivity) } catch (_: Exception) { false }).toString()
        }
        @JavascriptInterface
        fun schuleHier() { Thread({
            val fx = Alltag.fix?.takeIf { System.currentTimeMillis() - it.time < 10 * 60_000L } ?: run { try { Here.refresh(this@MainActivity, force = true) } catch (_: Exception) {}; null }
            val ll = fx?.let { it.latitude to it.longitude } ?: Here.latLon(this@MainActivity)
            val r = if (ll == null) "Ich weiß gerade nicht, wo du bist – Standort an?" else { prefs.edit().putString("schule_ort", "%.5f,%.5f".format(java.util.Locale.US, ll.first, ll.second)).apply(); "Gemerkt: Hier ist deine Schule." }
            send("t_res", JSONObject().put("id", "sch-st").put("text", r)) }, "jarvis-schule").start() }
        @JavascriptInterface
        fun schuleAdresse(a: String) { Thread({
            val p = try { Route.place(this@MainActivity, a) } catch (_: Exception) { null }
            val r = if (p == null) "Die Adresse finde ich nicht." else { prefs.edit().putString("schule_ort", "%.5f,%.5f".format(java.util.Locale.US, p.lat, p.lon)).apply(); "Gemerkt: ${a.trim()}." }
            send("t_res", JSONObject().put("id", "sch-st").put("text", r)) }, "jarvis-schule").start() }
        @JavascriptInterface
        fun schuleAuto(on: Boolean) { prefs.edit().putBoolean("schule_auto", on).apply() }
        @JavascriptInterface
        fun notfallGet(): String = prefs.getString("notfall_wer", "") ?: ""

        @JavascriptInterface
        fun notfallSet(w: String) { prefs.edit().putString("notfall_wer", w.trim()).apply() }

        @JavascriptInterface
        fun notfallTest() { Thread({ val r = try { Actions(this@MainActivity).notfallTest() } catch (e: Exception) { "Test ging nicht." }; send("nf_test", JSONObject().put("text", r)) }, "jarvis-nftest").start() }

        @JavascriptInterface
        fun testChatGet(): String = prefs.getString("test_chat", "") ?: ""
        @JavascriptInterface
        fun waConfGet(): Boolean = prefs.getBoolean("wa_bestaetigen", true)
        @JavascriptInterface
        fun waConfSet(on: Boolean) { prefs.edit().putBoolean("wa_bestaetigen", on).apply() }
        @JavascriptInterface
        fun ansageGet(): String = JSONObject().put("immer", prefs.getString("wa_immer", "") ?: "").put("zocken", prefs.getString("wa_beim_zocken", "ansagen") ?: "ansagen").toString()
        @JavascriptInterface
        fun ansageSet(immer: String, zocken: String) { prefs.edit().putString("wa_immer", immer.trim()).putString("wa_beim_zocken", zocken).apply(); Thread { try { Link.pushSettings(this@MainActivity) } catch (_: Exception) {} }.start() }
        @JavascriptInterface
        fun testWaPc() { Thread({ val r = try { Chats.testToPc(this@MainActivity) } catch (e: Exception) { "Ging nicht." }; send("t_res", JSONObject().put("id", "t-wapc").put("text", r)) }, "jt").start() }
        @JavascriptInterface
        fun testVoice() { Thread({ val t = prefs.getString("test_chat", "") ?: ""; val r = if (t.isBlank()) "Trag zuerst einen Test-Chat ein." else try { WaSend.voice(this@MainActivity, t, "Das ist ein Test. Wenn du das hörst, klappen Sprachnachrichten vom Handy.") } catch (e: Exception) { "Ging nicht (${e.message})." }; send("t_res", JSONObject().put("id", "t-voice").put("text", r)) }, "jt").start() }
        @JavascriptInterface
        fun testTakeover() { val t = prefs.getString("test_chat", "") ?: ""; val r = if (t.isBlank()) "Trag zuerst einen Test-Chat ein." else Stil.takeover(this@MainActivity, t); send("t_res", JSONObject().put("id", "t-take").put("text", r)) }
        @JavascriptInterface
        fun testChatSet(v: String) { prefs.edit().putString("test_chat", v.trim()).apply(); Thread { try { Link.pushSettings(this@MainActivity) } catch (_: Exception) {} }.start() }

        @JavascriptInterface
        fun ausgabenGet(): String = JSONObject().put("limit", Ausgaben.limit(this@MainActivity)).put("text", Ausgaben.summary(this@MainActivity)).toString()

        @JavascriptInterface
        fun ausgabenLimit(v: Int) = Ausgaben.setLimit(this@MainActivity, v)

        @JavascriptInterface
        fun getMeldenOft(): Int = prefs.getInt("melden_oft", 1)

        @JavascriptInterface
        fun setMeldenOft(v: Int) { prefs.edit().putInt("melden_oft", v.coerceIn(0, 2)).apply() }

        @JavascriptInterface
        fun getSchule(): String = Schule.all(this@MainActivity).toString()

        @JavascriptInterface
        fun setSchule(json: String) { try { Schule.setAll(this@MainActivity, org.json.JSONArray(json)) } catch (_: Exception) {} }

        @JavascriptInterface
        fun getLeute(): String = Leute.list(this@MainActivity).toString()

        @JavascriptInterface
        fun editLeute(key: String, json: String) { try { Leute.edit(this@MainActivity, key, if (json.isBlank()) null else JSONObject(json)) } catch (_: Exception) {} }

        @JavascriptInterface
        fun addLeute(name: String) { Leute.add(this@MainActivity, name) }
        @JavascriptInterface
        fun learnLeute() { Thread { try { Leute.learn(this@MainActivity, true); runOnUiThread { send("leute", JSONObject()) } } catch (_: Exception) {} }.start() }

        @JavascriptInterface
        fun getIdeen(): String = Ideen.all(this@MainActivity).toString()

        @JavascriptInterface
        fun setIdeen(json: String) { try { Ideen.setAll(this@MainActivity, org.json.JSONArray(json)) } catch (_: Exception) {} }

        @JavascriptInterface
        fun modusCmd(t: String): String = try { Modes.fromCmd(this@MainActivity, t) } catch (e: Exception) { "Ging nicht: ${e.message ?: ""}" }

        @JavascriptInterface
        fun getModus(): String = Modes.current(this@MainActivity)

        // --- Jarvis-Konto: einmal verbinden, danach sichert er still (kein Abmelden) ---
        @JavascriptInterface
        fun kontoInfo(): String = Konto.info(this@MainActivity).toString()

        @JavascriptInterface
        fun kontoLogin(email: String, pw: String, neu: Boolean) {
            Thread({ val r = Konto.signIn(this@MainActivity, email, pw, neu); send("konto", r.put("info", Konto.info(this@MainActivity))) }, "konto-login").start()
        }

        @JavascriptInterface
        fun getDirect(): String = Link.directInfo(this@MainActivity).toString()

        @JavascriptInterface
        fun setPcIp(ip: String) = Link.setPcIp(this@MainActivity, ip)

        @JavascriptInterface
        fun directTest() = Link.directTest(this@MainActivity)

        @JavascriptInterface
        fun getModiCfg(): String = Modes.cfg(this@MainActivity).toString()

        @JavascriptInterface
        fun setModiCfg(json: String) { try { Modes.setCfg(this@MainActivity, org.json.JSONArray(json), true) } catch (_: Exception) {} }

        @JavascriptInterface
        fun getPlan(): String = Melden.plan(this@MainActivity).toString()

        @JavascriptInterface
        fun setPlan(json: String) = Melden.setPlan(this@MainActivity, json)

        @JavascriptInterface
        fun getKopf(): String = prefs.getString("kopfhoerer", "JBL Tune Beam") ?: ""

        @JavascriptInterface
        fun setKopf(n: String) { prefs.edit().putString("kopfhoerer", n.trim()).apply() }

        @JavascriptInterface
        fun meldenInfo(): String = "Gerade: " + when (Melden.route(this@MainActivity)) { "speak" -> "ich darf laut reden"; "hold" -> if (Melden.sleeping(this@MainActivity)) "du schläfst – ich bin still bis zur Aufstehzeit" else "Schulstunde – ich hebe alles für die Pause auf"; else -> "nur Nachrichten" } +
            " · zuhause: " + (if (Alltag.isHome(this@MainActivity)) "ja" else "nein") + " · Kopfhörer: " + (if (Melden.headphones(this@MainActivity)) "verbunden" else "nicht verbunden") +
            " · Nicht stören: " + (if (Melden.dnd(this@MainActivity)) "an" else "aus") + Melden.schoolText(this@MainActivity).let { if (it.isNotBlank()) " · $it" else "" }

        @JavascriptInterface
        fun lernInfo(): String = Vorschlag.paused(this@MainActivity)

        @JavascriptInterface
        fun lernReset() = Vorschlag.reset(this@MainActivity)

        /** Tages-, Morgen- oder Wochen-Update jetzt erzeugen (kind: heute, morgen, woche). Antwort kommt als "feed_open". */
        @JavascriptInterface
        fun outfitData(): String {   // sofort die Teile, das Wetter kommt danach (nie das Internet auf dem Seiten-Faden abwarten)
            Thread({ try { send("outfit_t", Alltag.outfitData(this@MainActivity)) } catch (_: Exception) {} }, "jarvis-outfit").start()
            return try { Alltag.outfitItems(this@MainActivity).toString() } catch (_: Exception) { "{}" }
        }

        @JavascriptInterface
        fun outfitToday(): String = try { Wardrobe.today(this@MainActivity).toString() } catch (_: Exception) { "{}" }

        @JavascriptInterface
        fun outfitSave(idsJson: String, v: Int, t: Double): String {
            val ids = try { JSONArray(idsJson).let { a -> (0 until a.length()).map { a.optString(it) } } } catch (_: Exception) { emptyList() }
            return Wardrobe.dayFeedback(this@MainActivity, ids, v, if (t.isNaN() || t < -60) null else t)
        }

        @JavascriptInterface
        fun feedNow(kind: String) {
            Thread({
                val r = try {
                    when (kind) { "woche" -> Alltag.weekAhead(this@MainActivity); "rueckblick" -> Alltag.weekBack(this@MainActivity); "bilanz" -> Alltag.dayHealth(this@MainActivity)
                        "morgen" -> Alltag.eveningBrief(this@MainActivity); "tag_morgen" -> Alltag.dayBrief(this@MainActivity, 1); else -> Alltag.dayBrief(this@MainActivity, 0) }
                } catch (_: Exception) { null }
                if (r != null) send("feed_open", JSONObject().put("id", r.second))
                else send("info", JSONObject().put("text", "Das Update ging gerade nicht (Groq-Schlüssel? Internet?)."))
            }, "jarvis-feed").start()
        }

        /** Gesundheit: Health Connect verbinden (Samsung Health muss dort "Daten teilen" an haben). */
        @JavascriptInterface
        fun healthConnect() = runOnUiThread {
            when (Health.status(this@MainActivity)) {
                androidx.health.connect.client.HealthConnectClient.SDK_AVAILABLE -> try { healthPerm.launch(Health.PERMS) } catch (_: Exception) { Health.openSettings(this@MainActivity) }
                androidx.health.connect.client.HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> Health.openStore(this@MainActivity)
                else -> send("info", JSONObject().put("text", "Health Connect gibt es auf diesem Handy nicht."))
            }
        }

        @JavascriptInterface
        fun healthOpen() = Health.openSettings(this@MainActivity)

        /** Stand für die Seite Gesundheit: verbunden?, heute, letzte Nacht, Schlaf-Genauigkeit (Bedienungshilfe an?). */
        @JavascriptInterface
        fun healthInfo(): String = try {
            val st = Health.status(this@MainActivity)
            JSONObject().put("da", st == androidx.health.connect.client.HealthConnectClient.SDK_AVAILABLE)
                .put("update", st == androidx.health.connect.client.HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED)
                .put("connected", Health.connected(this@MainActivity))
                .put("heute", Health.day(this@MainActivity, 0) ?: JSONObject.NULL)
                .put("schlaf", Sleep.night(this@MainActivity, 0) ?: JSONObject.NULL)
                .put("touch", ScreenService.enabled()).toString()
        } catch (e: Exception) { JSONObject().put("error", e.toString()).toString() }

        /** Jarvis-Erinnerungen (Liste in den Einstellungen) */
        @JavascriptInterface
        fun remindList(): String = org.json.JSONArray(
            (0 until Remind.all(this@MainActivity).length()).map { Remind.all(this@MainActivity).getJSONObject(it) }.filter { !it.optBoolean("done") && it.optString("kind") != "termin" }
        ).toString()

        @JavascriptInterface
        fun remindDone(id: String) = Remind.done(this@MainActivity, id)

        @JavascriptInterface
        fun remindTest() { val r = Remind.add(this@MainActivity, "Test-Erinnerung: So sehen Jarvis-Erinnerungen aus.", System.currentTimeMillis() + 5_000L) }

        @JavascriptInterface
        fun openCalNotif(want: String) = runOnUiThread {   // Benachrichtigungen der Kalender-App/TimeTree ausschalten (Android-Einstellungen der App)
            val pkg = try { packageManager.getPackageInfo(want, 0); want } catch (_: Exception) {
                val key = if (want.contains("timetree")) "timetree" else if (want.contains("samsung")) "samsung.android.calendar" else "calendar"
                packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
                    .map { it.activityInfo.packageName }.firstOrNull { it.lowercase().contains(key) } ?: want }
            try { startActivity(Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, pkg).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            catch (_: Exception) { try { startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$pkg")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } catch (_: Exception) {} }
        }

        @JavascriptInterface
        fun updGet(): String = JSONObject().put("auto", Updater.auto(this@MainActivity)).put("can", Updater.canInstall(this@MainActivity))
            .put("pending", Updater.pending(this@MainActivity)).put("version", try { packageManager.getPackageInfo(packageName, 0).versionName } catch (_: Exception) { "" }).toString()
        @JavascriptInterface
        fun updSet(on: Boolean) = Updater.setAuto(this@MainActivity, on)
        @JavascriptInterface
        fun updAllow() { runOnUiThread { try { startActivity(Updater.allowIntent(this@MainActivity)) } catch (_: Exception) {} } }
        @JavascriptInterface
        fun updNow() { Alltag.updateNow(this@MainActivity) }
        @JavascriptInterface
        fun sysTest(id: String): String {   // Test im Hintergrund – Ergebnis kommt als Event „systest“
            Thread({ val r = try { SysCheck.test(this@MainActivity, id) } catch (e: Exception) { "Test ging nicht." }
                send("systest", JSONObject().put("id", id).put("text", r)) }, "jarvis-systest").start()
            return ""
        }

        /** Kleiderschrank */
        @JavascriptInterface
        fun schrankGet(): String = Wardrobe.get(this@MainActivity).put("ortnamen", org.json.JSONArray(
            (Route.placeNames(this@MainActivity) + listOf(Alltag.festerWeg(this@MainActivity).optString("name"))).filter { it.isNotBlank() }.map { it.lowercase() }.distinct())).toString()

        @JavascriptInterface
        fun schrankSave(json: String) { try { val o = JSONObject(json); o.remove("ortnamen"); Wardrobe.save(this@MainActivity, o) } catch (_: Exception) {} }

        @JavascriptInterface
        fun schrankHeute(): String = try { Alltag.wardrobeToday(this@MainActivity).toString() } catch (e: Exception) { JSONObject().put("error", e.toString()).toString() }

        /** Systemstatus (Seite in den Einstellungen): Handy-Prüfung. */
        @JavascriptInterface
        fun sysCheck(fresh: Boolean): String = try {
            if (fresh || System.currentTimeMillis() - SysCheck.lastT > 120_000L) SysCheck.run(this@MainActivity)
            JSONObject().put("items", SysCheck.last).put("t", SysCheck.lastT).put("text", SysCheck.summary()).toString()
        } catch (e: Exception) { JSONObject().put("items", org.json.JSONArray()).put("text", e.toString()).toString() }

        /** Fester Weg (jede Woche) */
        @JavascriptInterface
        fun festGet(): String = Alltag.festerWeg(this@MainActivity).toString()

        @JavascriptInterface
        fun festSet(json: String) { prefs.edit().putString("fester_weg", JSONObject(json).toString()).apply() }

        /** Einmalige Termine (an einem Datum) */
        @JavascriptInterface
        fun einmaligGet(): String = Alltag.einmalig(this@MainActivity).toString()

        @JavascriptInterface
        fun einmaligAdd(json: String): String = Alltag.einmaligAdd(this@MainActivity, JSONObject(json))

        @JavascriptInterface
        fun einmaligRemove(i: Int) = Alltag.einmaligRemove(this@MainActivity, i)

        /** Testnachricht: so sieht die Donnerstag-Nachricht aus (kommt als Benachrichtigung). */
        @JavascriptInterface
        fun testAlltag() = testAlltag2(false)

        /** Bahn-Test: echte Verbindung zu Oma und Opa ab jetzt, mit Ticket und „Ticket kaufen“. */
        @JavascriptInterface
        fun testBahn() = testAlltag2(true)

        /** Bahn-Test zu einem beliebigen Ziel ("" = Oma und Opa / fester Weg). */
        @JavascriptInterface
        fun testBahnZiel(ziel: String) {
            if (ziel.isBlank()) { testAlltag2(true); return }
            Thread({
                send("state", JSONObject().put("state", "thinking"))
                val t = try { Alltag.bahnTest(this@MainActivity, ziel) } catch (e: Exception) { "Test ging nicht: ${e.message ?: ""}" }
                send("agent", JSONObject().put("text", t))
                Alltag.lastTestFeed?.let { send("feed_open", JSONObject().put("id", it)) }
                send("state", JSONObject().put("state", "ended"))
            }, "jarvis-bahntest").start()
        }

        @JavascriptInterface
        fun getBahn(): String = JSONObject().put("art", prefs.getString("bahn_art", "rad_bahn")).put("app", (if (!prefs.getBoolean("ticket_app_v2", false)) { prefs.edit().putString("ticket_app", "auto").putBoolean("ticket_app_v2", true).apply(); "auto" } else prefs.getString("ticket_app", "auto"))).toString()

        @JavascriptInterface
        fun setBahn(art: String, app: String, ticket: String) {
            prefs.edit().putString("bahn_art", art.ifBlank { "rad_bahn" }).putString("ticket_app", app.ifBlank { "auto" }).putBoolean("ticket_app_v2", true)
                .putString("ticket_art", ticket.ifBlank { "erwachsen" }).apply()
            Alltag.syncBahn(this@MainActivity)
        }

        /** Was er über deine Zwischenstopps gelernt hat. */
        @JavascriptInterface
        fun halteInfo(): String = try { Halte.test(this@MainActivity) } catch (e: Exception) { "" }

        private fun testAlltag2(bahn: Boolean) {
            Thread({
                send("state", JSONObject().put("state", "thinking"))
                val t = try { Alltag.testMessage(this@MainActivity, bahn) } catch (e: Exception) { "Test ging nicht: ${e.message ?: ""}" }
                send("agent", JSONObject().put("text", t))
                Alltag.lastTestFeed?.let { send("feed_open", JSONObject().put("id", it)) }
                send("state", JSONObject().put("state", "ended"))
            }, "jarvis-test").start()
        }

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
        fun stilGet(): String = Stil.quizState(this@MainActivity).put("modus", Stil.mode(this@MainActivity))
            .put("chats", prefs.getString("stil_chats", "") ?: "").put("wa_termine", WaTermine.on(this@MainActivity))
            .put("termine", org.json.JSONArray(WaTermine.upcoming(this@MainActivity))).put("gelernt", Stil.learnedChats(this@MainActivity)).toString()
        @JavascriptInterface
        fun stilImport() { runOnUiThread { try { pickExport.launch(arrayOf("text/plain", "application/zip", "*/*")) } catch (_: Exception) {} } }
        @JavascriptInterface
        fun stilQuiz() { Thread({ val q = try { Stil.quizNext(this@MainActivity) } catch (e: Exception) { JSONObject().put("error", "Ging gerade nicht.") }; send("stil_quiz", q) }, "jarvis-quiz").start() }
        @JavascriptInterface
        fun stilAnswer(q: String, pick: Int, own: String): String = try { Stil.quizAnswer(this@MainActivity, JSONObject(q), pick, own.trim()).toString() } catch (e: Exception) { "{}" }
        @JavascriptInterface
        fun stilBad(q: String) { try { Stil.quizBad(this@MainActivity, JSONObject(q)) } catch (_: Exception) {} }
        @JavascriptInterface
        fun stilMitlesen(on: Boolean) { prefs.edit().putBoolean("stil_mitlesen", on).apply() }
        @JavascriptInterface
        fun accOpen() { runOnUiThread { try { startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS)) } catch (_: Exception) {} } }
        @JavascriptInterface
        fun accOn(): Boolean = ScreenService.enabled()
        @JavascriptInterface
        fun stilSet(modus: String, chats: String, termine: Boolean) {
            val changed = (prefs.getString("stil_chats", "") ?: "") != chats.trim() || Stil.mode(this@MainActivity) != modus
            Stil.setMode(this@MainActivity, modus); prefs.edit().putString("stil_chats", chats.trim()).apply(); WaTermine.setOn(this@MainActivity, termine)
            if (changed) Thread { try { Link.pushSettings(this@MainActivity) } catch (_: Exception) {} }.start()   // auch am PC
        }
        @JavascriptInterface
        fun piperGet(): String = JSONObject().put("voice", PiperPhone.voice(this@MainActivity)).put("status", PiperPhone.status)
            .put("voices", org.json.JSONArray(PiperPhone.VOICES.map { (id, n) -> JSONObject().put("id", id).put("name", n).put("ready", PiperPhone.ready(this@MainActivity, id)) })).toString()
        @JavascriptInterface
        fun piperSet(v: String) { PiperPhone.setVoice(this@MainActivity, v); Thread { try { Link.pushSettings(this@MainActivity) } catch (_: Exception) {} }.start() }
        @JavascriptInterface
        fun piperTest() {
            val c = this@MainActivity
            if (PiperPhone.voice(c) == PiperPhone.ANDROID) { runOnUiThread { android.widget.Toast.makeText(c, "Handy-Stimme gewählt", android.widget.Toast.LENGTH_SHORT).show() }; return }
            if (!PiperPhone.ready(c)) { PiperPhone.install(c, PiperPhone.voice(c), anyNetwork = true); return }
            PiperPhone.speak(c, "Hallo. So klinge ich jetzt – genau wie am PC.", prefs.getFloat("tts_rate", 1.05f)) {}
        }
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
            if (url.startsWith("app:")) {   // App öffnen (z. B. VVS Mobil fürs Ticket), sonst Play Store
                val pkg = url.removePrefix("app:")
                val i = packageManager.getLaunchIntentForPackage(pkg)
                try { startActivity(i ?: Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$pkg"))) }
                catch (_: Exception) { try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=$pkg"))) } catch (_: Exception) {} }
                return@runOnUiThread
            }
            if (url.startsWith("https://www.bahn.de/buchung")) {   // Verbindung mit Ticket direkt im DB Navigator öffnen
                try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).setPackage("de.hafas.android.db")); return@runOnUiThread } catch (_: Exception) {}
            }
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

        /** Sticker am PC: Liste, auswählen, hinzufügen, schicken. Antwort kommt als Ereignis "sticker". */
        @JavascriptInterface
        fun stickerCmd(json: String) {
            val cmd = try { JSONObject(json) } catch (_: Exception) { return }
            if (!Link.paired(this@MainActivity)) { send("sticker", JSONObject().put("ok", false).put("text", "Handy und PC sind noch nicht gekoppelt.")); return }
            Thread({
                val r = try { Link.command(this@MainActivity, cmd, 30_000) } catch (_: Exception) { null }
                send("sticker", (r ?: JSONObject().put("ok", false).put("text", "Der PC antwortet nicht. Läuft Jarvis am PC?")).put("op", cmd.optString("type")))
            }, "jarvis-sticker").start()
        }

        @JavascriptInterface
        fun stickerPickImage() { runOnUiThread { try { pickSticker.launch("image/*") } catch (_: Exception) {} } }

        @JavascriptInterface
        fun stickerKeyboard() { runOnUiThread { try { this@MainActivity.stickerKeyboard() } catch (_: Exception) {} } }

        /** Befehl an den PC (Fernbedienung). Antwort kommt als Ereignis "pc_reply". */
        @JavascriptInterface
        fun pcCmd(json: String) {
            val cmd = try { JSONObject(json) } catch (_: Exception) { return }
            if (!Link.paired(this@MainActivity)) { send("pc_reply", JSONObject().put("ok", false).put("text", "Handy und PC sind noch nicht gekoppelt (Einstellungen → PC & Fernzugriff → Kopplungscode).")); return }
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
