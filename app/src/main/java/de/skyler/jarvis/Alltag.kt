package de.skyler.jarvis

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.media.AudioManager
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Runde 3 – Jarvis im Alltag (läuft jede Minute im Hintergrund-Dienst):
 *  - Zuhause und weg: Heim-WLAN (und Standort). 5 Minuten weg -> Hinweis mit "Abbrechen", 2 Minuten später fährt der PC
 *    herunter (Musik aus, ETS2 speichern, Programme zu). Wieder da -> "Willkommen zurück" am PC. Ortserinnerungen.
 *  - Rechtzeitig losfahren: Termin mit Ort -> "Fertig machen" und "Jetzt los"; Regen (DWD, ECMWF, GFS) -> Bahn, sonst Rad.
 *    Fahr- und Fertigmach-Zeit lernt er aus echten Fahrten.
 *  - Ankunft ankündigen: ca. 5 Minuten vorher SMS "Hier ist Jarvis. Skyler ist um … da".
 *  - Morgen-Briefing (erstes Entsperren nach dem Wecker), Abend-Briefing, Wochenrückblick am Sonntag.
 */
object Alltag {
    private const val TAG = "JarvisAlltag"
    private const val CH = "jarvis_alltag"
    const val ACTION_CANCEL = "de.skyler.jarvis.WEG_ABBRECHEN"
    private val http = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS).build()
    private val de = Locale.GERMANY
    @Volatile var fix: Location? = null

    const val ANZIEH_DEFAULT = "unter 5 Grad: Winterjacke, Mütze, Handschuhe\n5 bis 12 Grad: Jacke\n12 bis 18 Grad: Pulli oder leichte Jacke\n" +
        "über 18 Grad: T-Shirt\nRegen: Regenjacke, auf dem Rad auch Regenhose\nWind über 30 km/h: winddichte Jacke"

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    private fun on(ctx: Context, k: String, def: Boolean = true) = prefs(ctx).getBoolean(k, def)
    private fun has(ctx: Context, p: String) = ctx.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED
    private fun clock(t: Long) = SimpleDateFormat("H:mm", de).format(Date(t)) + " Uhr"
    private fun today() = SimpleDateFormat("yyyy-MM-dd", de).format(Date())

    // --- Zustand (überlebt Neustarts des Dienstes) ---------------------------------------------------------
    @Synchronized private fun state(ctx: Context): JSONObject = try { JSONObject(prefs(ctx).getString("alltag_state", "{}") ?: "{}") } catch (_: Exception) { JSONObject() }
    @Synchronized private fun save(ctx: Context, s: JSONObject) { prefs(ctx).edit().putString("alltag_state", s.toString()).apply() }
    private fun done(s: JSONObject, k: String) = s.optJSONObject("done")?.has(k) == true
    private fun mark(s: JSONObject, k: String) {
        val d = s.optJSONObject("done") ?: JSONObject()
        val cut = System.currentTimeMillis() - 3 * 86_400_000L
        for (x in d.keys().asSequence().toList()) if (d.optLong(x) < cut) d.remove(x)
        d.put(k, System.currentTimeMillis()); s.put("done", d)
    }

    // --- Standort und WLAN ----------------------------------------------------------------------------------
    fun onFix(loc: Location) { fix = loc }
    private fun fixP(): Route.P? = fix?.takeIf { System.currentTimeMillis() - it.time < 10 * 60_000L }?.let { Route.P(it.latitude, it.longitude, "hier") }

    @Suppress("DEPRECATION")
    fun ssid(ctx: Context): String? = try {
        val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        val s = wm.connectionInfo?.ssid?.trim('"')
        if (s.isNullOrBlank() || s.contains("unknown ssid", true) || s == "0x") null else s
    } catch (_: Exception) { null }

    private fun heimWlan(ctx: Context) = (prefs(ctx).getString("heim_wlan", "") ?: "").trim()

    // --- Benachrichtigungen ----------------------------------------------------------------------------------
    private fun notify(ctx: Context, id: Int, title: String, text: String, cancelAction: Boolean = false, url: String? = null) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "Alltag (Losfahren, Briefings, Zuhause)", NotificationManager.IMPORTANCE_HIGH))
        val b = NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title).setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text)).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH)
        if (cancelAction) b.addAction(0, "Abbrechen", PendingIntent.getBroadcast(ctx, 5, Intent(ctx, AlltagReceiver::class.java).setAction(ACTION_CANCEL),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        val open = if (url != null) Intent(Intent.ACTION_VIEW, Uri.parse(url)) else Intent(ctx, MainActivity::class.java)
        b.setContentIntent(PendingIntent.getActivity(ctx, id, open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        try { nm.notify(id, b.build()) } catch (_: Exception) {}
    }

    /** "Abbrechen" in der Weg-Benachrichtigung: PC bleibt an. */
    fun cancelAway(ctx: Context) {
        val s = state(ctx); s.put("pc_down_at", -1L); save(ctx, s)
        ctx.getSystemService(NotificationManager::class.java).cancel(301)
    }

    private fun pcCmd(ctx: Context, cmd: JSONObject) { if (Link.paired(ctx)) Thread({ try { Link.command(ctx, cmd, 20_000) } catch (_: Exception) {} }).start() }

    /** Am PC sagen, wenn dort jemand sitzt; sonst false. */
    private fun pcSay(ctx: Context, text: String): Boolean = try {
        Link.paired(ctx) && Link.command(ctx, JSONObject().put("type", "say").put("text", text).put("need_active", true), 15_000)?.optBoolean("ok") == true
    } catch (_: Exception) { false }

    private fun quiet(ctx: Context): Boolean {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val nm = ctx.getSystemService(NotificationManager::class.java)
        return am.ringerMode != AudioManager.RINGER_MODE_NORMAL || nm.currentInterruptionFilter > NotificationManager.INTERRUPTION_FILTER_ALL
    }

    // --- Gelernte Fahrten -----------------------------------------------------------------------------------
    private fun tripsFile(ctx: Context) = File(ctx.filesDir, "fahrten.json")
    private fun trips(ctx: Context): JSONArray = try { JSONArray(tripsFile(ctx).readText()) } catch (_: Exception) { JSONArray() }
    private fun list(a: JSONArray) = (0 until a.length()).mapNotNull { a.optJSONObject(it) }

    private fun learned(ctx: Context, to: String, mode: String): Double? {
        val d = list(trips(ctx)).filter { near(it.optString("to"), to) && it.optString("mode") == mode }.map { it.optDouble("min") }
            .filter { it in 2.0..180.0 }.takeLast(5).sorted()
        return if (d.size >= 2) d[d.size / 2] else null
    }

    private fun near(a: String, b: String): Boolean {
        val x = Chats.norm(a); val y = Chats.norm(b)
        return x.isNotBlank() && y.isNotBlank() && (x == y || x.contains(y) && y.length >= 3 || y.contains(x) && x.length >= 3)
    }

    /** Durchschnittliche Fahrzeit (Minuten) von → nach aus deinen echten Fahrten (letzte 6), null = noch nichts gelernt. */
    private fun learnedRoute(ctx: Context, from: String, to: String, mode: String): Double? {
        val d = list(trips(ctx)).filter { near(it.optString("from"), from) && near(it.optString("to"), to) && it.optString("mode") == mode }
            .map { it.optDouble("min") }.filter { it in 2.0..120.0 }.takeLast(6)
        return if (d.isNotEmpty()) d.average() else null
    }

    private fun tripsTo(ctx: Context, to: String) = list(trips(ctx)).count { it.optString("to") == to }

    private fun prepMinutes(s: JSONObject): Int {
        val a = s.optJSONArray("prep") ?: return 15
        val v = (0 until a.length()).map { a.optInt(it) }.takeLast(7).sorted()
        return if (v.size >= 2) v[v.size / 2].coerceIn(5, 45) else 15
    }

    /** Wie lange du nach "Mach dich fertig" brauchst, bis du losfährst (Durchschnitt, Start 5 Minuten). */
    private fun prepBack(s: JSONObject): Int {
        val a = s.optJSONArray("prep_back") ?: return 5
        val v = (0 until a.length()).map { a.optInt(it) }.filter { it in 0..40 }.takeLast(6)
        return if (v.isEmpty()) 5 else Math.round(v.average()).toInt().coerceIn(2, 30)
    }

    /** Testnachricht: so sieht die Nachricht am Donnerstag um 15:45 aus (mit dem Wetter von jetzt). */
    fun testMessage(ctx: Context): String {
        val f = festeWege(ctx).firstOrNull()
        val to = f?.to ?: "Opa"
        val home = Route.home(ctx) ?: return "Trag erst deine Adresse ein (Allgemein → Standort)."
        val dest = Route.place(ctx, to) ?: return "$to steht noch nicht unter Wege → Meine Orte."
        val now = System.currentTimeMillis()
        val pl = tripPlan(ctx, home, dest, now + 5 * 60_000L, to)
        val t = "[Test] " + rideBriefing(ctx, "Um ${clock(now + 5 * 60_000L)} geht's los zu $to.", home, now + 5 * 60_000L, now + 2 * 3_600_000L, pl,
            remindersFor(ctx, to), false) + (if (whoFor(ctx, to) != null) " Ich sag Bescheid, kurz bevor du da bist." else "")
        notify(ctx, 339, "Gleich los zu $to (Test)", t)
        return t
    }

    private fun pathKm(pts: JSONArray, from: Int = 0): Double {
        var k = 0.0
        for (i in maxOf(1, from + 1) until pts.length()) {
            val a = pts.getJSONArray(i - 1); val b = pts.getJSONArray(i)
            k += Route.distKm(Route.P(a.getDouble(1), a.getDouble(2), ""), Route.P(b.getDouble(1), b.getDouble(2), ""))
        }
        return k
    }

    private fun finishTrip(ctx: Context, s: JSONObject, to: String) {
        val t = s.optJSONObject("trip") ?: return
        val start = t.optLong("start"); if (start <= 0) return
        val pts = t.optJSONArray("pts") ?: JSONArray()
        val min = (System.currentTimeMillis() - start) / 60_000.0
        val km = pathKm(pts)
        val kmh = if (min > 0) km / (min / 60) else 0.0
        val mode = when { kmh < 6.5 -> "walk"; kmh < 28 -> "rad"; else -> "bahn" }
        if (min in 2.0..300.0 && to != t.optString("from")) {
            val a = trips(ctx)
            a.put(JSONObject().put("from", t.optString("from")).put("to", to).put("start", start).put("end", System.currentTimeMillis())
                .put("min", min).put("km", km).put("mode", mode))
            while (a.length() > 500) a.remove(0)
            try { tripsFile(ctx).writeText(a.toString()) } catch (_: Exception) {}
            Log.i(TAG, "Fahrt ${t.optString("from")} -> $to: ${min.toInt()} min, ${"%.1f".format(km)} km, $mode")
        }
        s.put("trip", JSONObject().put("from", to).put("start", 0L).put("pts", JSONArray()))
    }

    // --- Ortserinnerungen ("erinnere mich bei Opa an das Ladekabel") -----------------------------------------
    fun addPlaceReminder(ctx: Context, ort: String, text: String): String {
        val a = try { JSONArray(prefs(ctx).getString("ort_erinnerungen", "[]")) } catch (_: Exception) { JSONArray() }
        a.put(JSONObject().put("ort", ort.trim()).put("text", text.trim()).put("ts", System.currentTimeMillis()))
        prefs(ctx).edit().putString("ort_erinnerungen", a.toString()).apply()
        val o = ort.trim().ifBlank { "dort" }
        return if (o.lowercase() in setOf("zuhause", "daheim", "home")) "Mach ich, wenn du heimkommst." else "Mach ich, sobald du bei $o bist."
    }

    private fun placeReminders(ctx: Context, place: String, say: (String) -> Unit) {
        val a = try { JSONArray(prefs(ctx).getString("ort_erinnerungen", "[]")) } catch (_: Exception) { return }
        val keep = JSONArray(); val due = mutableListOf<String>()
        val p = Chats.norm(place)
        for (o in list(a)) {
            val w = Chats.norm(o.optString("ort")).let { if (it in setOf("daheim", "home", "zu hause")) "zuhause" else it }
            if (w.isNotBlank() && (w == p || p.contains(w) || w.contains(p) && p.length >= 3)) due.add(o.optString("text"))
            else if (System.currentTimeMillis() - o.optLong("ts") < 30 * 86_400_000L) keep.put(o)
        }
        if (due.isEmpty()) return
        prefs(ctx).edit().putString("ort_erinnerungen", keep.toString()).apply()
        val t = "Erinnerung: " + due.joinToString(". ")
        notify(ctx, 310, "Erinnerung", t)
        say(t)
    }

    // --- Wetter aus mehreren Modellen (Open-Meteo: DWD ICON, ECMWF, GFS) -------------------------------------
    private var rainCache: Pair<Long, JSONObject>? = null

    /** Regnet es zur Zeit t? Wenn mindestens zwei der drei Modelle Niederschlag sehen. */
    fun rainAt(lat: Double, lon: Double, t: Long): Boolean {
        val js = rainCache?.takeIf { System.currentTimeMillis() - it.first < 30 * 60_000L }?.second ?: try {
            val url = "https://api.open-meteo.com/v1/forecast?latitude=$lat&longitude=$lon&hourly=precipitation" +
                "&models=icon_seamless,ecmwf_ifs025,gfs_seamless&timezone=auto&forecast_days=3"
            JSONObject(http.newCall(Request.Builder().url(url).build()).execute().use { it.body?.string() ?: "{}" }).also { rainCache = System.currentTimeMillis() to it }
        } catch (_: Exception) { return false }
        val h = js.optJSONObject("hourly") ?: return false
        val times = h.optJSONArray("time") ?: return false
        val key = SimpleDateFormat("yyyy-MM-dd'T'HH:00", de).format(Date(t))
        val i = (0 until times.length()).firstOrNull { times.optString(it) == key } ?: return false
        var wet = 0; var seen = 0
        for (m in listOf("icon_seamless", "ecmwf_ifs025", "gfs_seamless")) {
            val a = h.optJSONArray("precipitation_$m") ?: continue
            seen++
            if (maxOf(a.optDouble(i, 0.0), a.optDouble(i + 1, 0.0)) >= 0.2) wet++
        }
        if (seen == 0) h.optJSONArray("precipitation")?.let { a -> return maxOf(a.optDouble(i, 0.0), a.optDouble(i + 1, 0.0)) >= 0.2 }
        return seen > 0 && wet * 2 > seen   // Mehrheit der Modelle
    }

    /** Wetter eines Tages als kurze Datenzeilen fürs Briefing. */
    private fun weatherDay(ctx: Context, dayOffset: Int): String = try {
        val home = Route.home(ctx) ?: return ""
        val url = "https://api.open-meteo.com/v1/forecast?latitude=${home.lat}&longitude=${home.lon}" +
            "&hourly=temperature_2m,apparent_temperature,precipitation_probability,precipitation,wind_speed_10m,weather_code" +
            "&daily=temperature_2m_min,temperature_2m_max,precipitation_sum&timezone=auto&forecast_days=3"
        val js = JSONObject(http.newCall(Request.Builder().url(url).build()).execute().use { it.body?.string() ?: "{}" })
        val h = js.getJSONObject("hourly"); val d = js.getJSONObject("daily")
        val day = SimpleDateFormat("yyyy-MM-dd", de).format(Date(System.currentTimeMillis() + dayOffset * 86_400_000L))
        val sb = StringBuilder()
        val di = (0 until d.getJSONArray("time").length()).firstOrNull { d.getJSONArray("time").getString(it) == day } ?: 0
        sb.append("Tag: min ${d.getJSONArray("temperature_2m_min").optDouble(di)}°, max ${d.getJSONArray("temperature_2m_max").optDouble(di)}°, Regen gesamt ${d.getJSONArray("precipitation_sum").optDouble(di)} mm\n")
        val t = h.getJSONArray("time")
        for (hr in listOf(7, 8, 10, 13, 16, 18, 21)) {
            val i = (0 until t.length()).firstOrNull { t.getString(it) == "${day}T%02d:00".format(hr) } ?: continue
            sb.append("$hr Uhr: ${h.getJSONArray("temperature_2m").optDouble(i)}° (gefühlt ${h.getJSONArray("apparent_temperature").optDouble(i)}°), " +
                "Regen ${h.getJSONArray("precipitation_probability").optInt(i)} % / ${h.getJSONArray("precipitation").optDouble(i)} mm, " +
                "Wind ${h.getJSONArray("wind_speed_10m").optDouble(i)} km/h, Code ${h.getJSONArray("weather_code").optInt(i)}\n")
        }
        sb.toString()
    } catch (e: Exception) { Log.w(TAG, "wetter: $e"); "" }

    // =========================================================================================================
    /** Jede Minute aus dem Dienst (Hintergrund-Thread). say = laut sagen und als Karte zeigen. */
    fun tick(ctx: Context, say: (String) -> Unit) {
        val s = state(ctx)
        try { homeAndAway(ctx, s, say) } catch (e: Exception) { Log.w(TAG, "zuhause: $e") }
        try { arrival(ctx, s) } catch (e: Exception) { Log.w(TAG, "ankunft: $e") }
        try { leaveInTime(ctx, s, say) } catch (e: Exception) { Log.w(TAG, "losfahren: $e") }
        try { routines(ctx, s, say) } catch (e: Exception) { Log.w(TAG, "feste wege: $e") }
        try { alarms(ctx, s) } catch (_: Exception) {}
        try { evening(ctx, s, say) } catch (e: Exception) { Log.w(TAG, "abend: $e") }
        try { weekly(ctx, s) } catch (e: Exception) { Log.w(TAG, "rückblick: $e") }
        save(ctx, s)
    }

    private fun homeAndAway(ctx: Context, s: JSONObject, say: (String) -> Unit) {
        val now = System.currentTimeMillis()
        val home = Route.home(ctx)
        val here = fixP()
        val hw = heimWlan(ctx)
        val ssid = ssid(ctx)
        val wifiKnown = hw.isNotBlank() && has(ctx, Manifest.permission.ACCESS_FINE_LOCATION)
        val onHomeWifi = wifiKnown && ssid != null && ssid.equals(hw, true)
        val dHome = if (here != null && home != null) Route.distKm(here, home) else null
        // Heim-WLAN noch nicht eingetragen: zuhause (Standort) und im WLAN -> übernehmen
        if (hw.isBlank() && ssid != null && dHome != null && dHome < 0.08) prefs(ctx).edit().putString("heim_wlan", ssid).apply()
        val isHome = onHomeWifi || (dHome != null && dHome < 0.15)
        // WLAN weg, aber der letzte Standort (bis 60 Min. alt) war noch zuhause -> eher Router/WLAN-Aussetzer, nicht "weg"
        val lastNearHome = fix?.let { f -> home != null && now - f.time < 60 * 60_000L &&
            Route.distKm(Route.P(f.latitude, f.longitude, ""), home) < 0.3 } ?: false
        val isAway = !isHome && ((wifiKnown && (dHome == null && !lastNearHome || dHome != null && dHome > 0.3)) ||
            (!wifiKnown && dHome != null && dHome > 0.3))
        if (!isHome && !isAway) return   // weiß nicht, wo du bist

        val trip = s.optJSONObject("trip") ?: JSONObject().put("from", "zuhause").put("start", 0L).put("pts", JSONArray())
        s.put("trip", trip)
        // Punkte der Fahrt sammeln
        if (here != null && !isHome) {
            val pts = trip.optJSONArray("pts") ?: JSONArray().also { trip.put("pts", it) }
            val last = if (pts.length() > 0) pts.getJSONArray(pts.length() - 1) else null
            if (last == null || now - last.getLong(0) > 110_000 || Route.distKm(here, Route.P(last.getDouble(1), last.getDouble(2), "")) > 0.04) {
                pts.put(JSONArray().put(fix!!.time).put(here.lat).put(here.lon))
                while (pts.length() > 720) pts.remove(0)
            }
        }

        if (isHome) {
            if (s.optBoolean("away")) {
                val gone = now - s.optLong("away_since", now)
                finishTrip(ctx, s, "zuhause")
                if (gone > 15 * 60_000L && on(ctx, "weg_auto")) pcCmd(ctx, JSONObject().put("type", "heim"))
                placeReminders(ctx, "zuhause", say)
                ctx.getSystemService(NotificationManager::class.java).cancel(301)
            }
            s.put("away", false).put("left_at", 0L).put("pc_down_at", 0L).put("at_place", "zuhause")
            trip.put("from", "zuhause").put("start", 0L).put("pts", JSONArray())
            return
        }

        // weg
        if (!s.optBoolean("away")) {
            if (s.optLong("left_at") <= 0) s.put("left_at", now)
            if (now - s.optLong("left_at") >= 5 * 60_000L) {
                val left = s.optLong("left_at")
                s.put("away", true).put("away_since", left).put("at_place", "")
                trip.put("from", "zuhause").put("start", left)
                // Fertigmach-Zeit lernen: wie lange nach "Fertig machen" bist du wirklich los?
                val ready = s.optLong("last_ready")
                if (ready > 0 && left - ready in 0..90 * 60_000L) {
                    val a = s.optJSONArray("prep") ?: JSONArray()
                    a.put(((left - ready) / 60_000L).toInt()); while (a.length() > 10) a.remove(0)
                    s.put("prep", a).put("last_ready", 0L)
                }
                if (on(ctx, "weg_auto") && Link.paired(ctx) && s.optLong("pc_down_at") != -1L) {
                    s.put("pc_down_at", now + 2 * 60_000L)
                    notify(ctx, 301, "Du bist unterwegs", "Dein PC fährt in 2 Minuten herunter: Musik aus, ETS2 speichern, Programme schließen. " +
                        "Sitzt jemand dran, fragt er vorher.", cancelAction = true)
                }
            }
            return
        }
        val down = s.optLong("pc_down_at")
        if (down > 0 && now >= down) {
            s.put("pc_down_at", 0L)
            ctx.getSystemService(NotificationManager::class.java).cancel(301)
            Thread({ try { if (Link.pcOnline(ctx)) Link.command(ctx, JSONObject().put("type", "weg"), 20_000) } catch (_: Exception) {} }).start()
        }
        // an einem gespeicherten Ort angekommen / losgefahren
        if (here == null) return
        val at = s.optString("at_place")
        if (at.isNotBlank() && at != "zuhause") {
            val p = Route.place(ctx, at)
            if (p == null || Route.distKm(here, p) > 0.3) {   // weg von dort
                s.put("left_place", JSONObject().put("name", at).put("t", now))
                s.put("at_place", ""); trip.put("from", at).put("start", now).put("pts", JSONArray().put(JSONArray().put(now).put(here.lat).put(here.lon)))
            }
            return
        }
        for (name in Route.lines(ctx, "orte").keys) {
            val p = Route.place(ctx, name) ?: continue
            if (Route.distKm(here, p) < 0.15) {
                finishTrip(ctx, s, name)
                s.put("at_place", name)
                placeReminders(ctx, name, say)
                return
            }
        }
        if (trip.optLong("start") <= 0) trip.put("start", now)
    }

    /** Ankunft ankündigen: "Opa: Thomas" in den Einstellungen -> SMS ca. 5 Minuten vorher. */
    /** Wer bekommt bei diesem Ort die Ankunfts-SMS? ("Opa: Opa", "Oma und Opa: Opa" …) */
    private fun whoFor(ctx: Context, place: String): Pair<String, String>? {
        val p = place.lowercase().trim()
        return Route.lines(ctx, "ankunft").entries.firstOrNull { (k, _) -> k == p || p.contains(k) || k.contains(p) }?.toPair()
    }

    /** Ziel, das du gesagt hast ("ich fahr jetzt los zu Opa") oder das ein fester Weg gesetzt hat. */
    private fun targetArrival(ctx: Context, s: JSONObject) {
        val z = s.optJSONObject("ziel") ?: return
        val now = System.currentTimeMillis()
        val start = z.optLong("start"); val name = z.optString("name")
        if (now - start > 3 * 3_600_000L || name.isBlank()) { s.remove("ziel"); return }
        if (s.optString("at_place").equals(name, true)) { s.remove("ziel"); return }   // schon da
        val (place, who) = whoFor(ctx, name) ?: return
        val key = "ankunft|$place|${today()}"
        if (done(s, key)) return
        val dest = Route.place(ctx, name) ?: return
        val here = fixP()
        val est = z.optDouble("min", 20.0)
        val at: Long = if (here != null) {
            val d = Route.distKm(here, dest)
            if (d < 0.3) { s.remove("ziel"); return }
            val gone = (now - start) / 60_000.0
            val left = est * (d / maxOf(0.3, z.optDouble("km", d)))   // Rest der geplanten Zeit nach Strecke
            if (gone < 3 || left > 6) return
            now + (left * 60_000).toLong()
        } else {
            // kein Standort: nach der geschätzten Fahrzeit (5 Minuten vorher)
            if (now < start + ((est - 5) * 60_000).toLong()) return
            start + (est * 60_000).toLong()
        }
        mark(s, key)
        Thread({ sendArrival(ctx, place, who, at, start) }, "jarvis-ankunft").start()
    }

    private fun arrival(ctx: Context, s: JSONObject) {
        targetArrival(ctx, s)
        val trip = s.optJSONObject("trip") ?: return
        val start = trip.optLong("start"); if (start <= 0 || !s.optBoolean("away") && trip.optString("from") == "zuhause") return
        val here = fixP() ?: return
        val pts = trip.optJSONArray("pts") ?: return
        if (pts.length() < 3) return
        val now = System.currentTimeMillis()
        val i0 = (0 until pts.length()).firstOrNull { now - pts.getJSONArray(it).getLong(0) < 5 * 60_000L } ?: return
        val span = (now - pts.getJSONArray(i0).getLong(0)) / 60_000.0
        if (span < 1.5) return
        val speed = pathKm(pts, i0 - 0).let { it / span }   // km pro Minute
        if (speed < 0.08) return   // steht oder läuft langsam
        for ((place, who) in Route.lines(ctx, "ankunft")) {
            val key = "ankunft|$place|${today()}"
            if (done(s, key) || trip.optString("from").equals(place, true)) continue
            val p = Route.place(ctx, place) ?: continue
            val d = Route.distKm(here, p)
            if (d < 0.3 || d > speed * 9) continue
            val eta = d * 1.25 / speed
            if (eta > 6) continue
            mark(s, key)
            val at = now + (eta * 60_000).toLong()
            Thread({ sendArrival(ctx, place, who, at, start) }, "jarvis-ankunft").start()
        }
    }

    private fun sendArrival(ctx: Context, place: String, who: String, at: Long, start: Long) {
        val nr = Actions(ctx).number(who) ?: run { notify(ctx, 320, "Ankunft", "$who finde ich nicht in deinen Kontakten."); return }
        val atS = SimpleDateFormat("H:mm", de).format(Date(at)); val startS = SimpleDateFormat("H:mm", de).format(Date(start))
        var text = "Hier ist Jarvis. Skyler ist um $atS Uhr da, er ist um $startS Uhr losgefahren. Ihr könnt schon mal runterkommen."
        val key = prefs(ctx).getString("groq_key", "") ?: ""
        if (key.isNotBlank()) try {
            val out = Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content",
                "Schreib eine kurze SMS (1 bis 2 Sätze). Sie beginnt genau mit \"Hier ist Jarvis.\" und sagt in der dritten Person: " +
                    "Skyler ist um $atS Uhr da, er ist um $startS Uhr losgefahren, man kann schon runterkommen. " +
                    "Formuliere es jedes Mal etwas anders, freundlich und locker, ohne Emojis. Nur der SMS-Text."))
                .put(JSONObject().put("role", "user").put("content", "Empfänger: $who")), 150).trim().trim('"')
            if (out.startsWith("Hier ist Jarvis") && out.length < 300) text = out
        } catch (_: Exception) {}
        val ok = Butler.sms(ctx, nr, text)
        notify(ctx, 320, if (ok) "Ankunft angekündigt" else "Ankunft: SMS ging nicht", if (ok) "An $who: $text" else "Erlaube SMS in den Einstellungen unter Leute.")
    }

    /** Rechtzeitig losfahren. */
    private fun leaveInTime(ctx: Context, s: JSONObject, say: (String) -> Unit) {
        if (!on(ctx, "losfahren")) return
        val now = System.currentTimeMillis()
        val evs = Cal.events(ctx, now + 5 * 60_000L, now + 10 * 3_600_000L).filter { !it.allDay }
        val plans = s.optJSONObject("lf") ?: JSONObject()
        for (k in plans.keys().asSequence().toList()) if (plans.optJSONObject(k)?.optLong("begin", 0) ?: 0 < now - 3_600_000L) plans.remove(k)
        s.put("lf", plans)
        for (e in evs) {
            val name = Route.savedName(ctx, e.title + " " + e.place) ?: e.place.trim().ifBlank { null } ?: continue
            val id = "${e.id}_${e.begin}"
            var pl = plans.optJSONObject(id)
            if (pl == null || now - pl.optLong("at") > 10 * 60_000L && now < pl.optLong("ready")) {
                pl = plan(ctx, s, e, name) ?: continue
                plans.put(id, pl)
            }
            val ready = pl.optLong("ready"); val leave = pl.optLong("leave")
            if (now >= ready && now < leave && !pl.optBoolean("said_ready")) {
                pl.put("said_ready", true); s.put("last_ready", now)
                val t = pl.optString("ready_text")
                notify(ctx, 330, "Fertig machen: ${e.title}", t)
                deliverSay(ctx, t, say)
            }
            if (now >= leave && now < e.begin && !pl.optBoolean("said_leave")) {
                pl.put("said_leave", true)
                val t = pl.optString("leave_text")
                notify(ctx, 331, "Jetzt los: ${e.title}", t, url = pl.optString("maps").ifBlank { null })
                deliverSay(ctx, t, say)
                if (pl.optBoolean("rare") && pl.optString("maps").isNotBlank()) try {
                    ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(pl.optString("maps"))).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                } catch (_: Exception) {}
            }
        }
    }

    private fun plan(ctx: Context, s: JSONObject, e: Cal.Ev, name: String): JSONObject? {
        val home = Route.home(ctx)
        val from = (if (s.optBoolean("away")) fixP() else null) ?: home ?: fixP() ?: return null
        val dest = Route.place(ctx, name) ?: return null
        val km = Route.distKm(from, dest)
        if (km < 0.25) return null
        val arriveBy = e.begin - 5 * 60_000L
        val prep = prepMinutes(s)
        var mode: String; var leave: Long; var info: String
        val rain = rainAt(from.lat, from.lon, arriveBy - 30 * 60_000L)
        if (km < 1.2) {
            mode = "walking"
            val m = learned(ctx, name, "walk") ?: Route.walkMinutes(from, dest)
            leave = arriveBy - (m * 60_000).toLong(); info = "Zu Fuß brauchst du etwa ${m.toInt()} Minuten."
        } else {
            val bahn = if (rain) Route.bahnBy(from, dest, arriveBy) else null
            if (bahn != null) {
                mode = "transit"; leave = bahn.dep
                info = "Es soll regnen, nimm lieber die ${bahn.line} um ${clock(bahn.rideDep)} ab ${bahn.stop}, an um ${clock(bahn.arr)}."
            } else {
                mode = "bicycling"
                val m = learned(ctx, name, "rad") ?: (Route.bikeMinutes(from, dest) + 3)
                leave = arriveBy - (m * 60_000).toLong()
                info = "Mit dem Rad brauchst du etwa ${m.toInt()} Minuten" + (if (rain) ", nimm Regensachen mit." else ".")
            }
        }
        val title = e.title
        val rare = tripsTo(ctx, name) < 2 && Route.savedName(ctx, name) == null
        return JSONObject().put("at", System.currentTimeMillis()).put("begin", e.begin).put("leave", leave)
            .put("ready", leave - prep * 60_000L).put("mode", mode).put("rare", rare)
            .put("maps", Route.mapsLink(null, dest, mode))
            .put("ready_text", "In $prep Minuten musst du los zu $title. Mach dich fertig. $info")
            .put("leave_text", "Jetzt los zu $title, um ${clock(e.begin)} geht's los. $info")
    }

    // --- Feste Wege: "Donnerstag 15:50 zu Opa, zurück 18:00" -------------------------------------------------
    const val FESTE_DEFAULT = "Donnerstag 15:50 zu Opa, zuhause 18:20"
    private val DAYS = mapOf("mo" to Calendar.MONDAY, "di" to Calendar.TUESDAY, "mi" to Calendar.WEDNESDAY, "do" to Calendar.THURSDAY,
        "fr" to Calendar.FRIDAY, "sa" to Calendar.SATURDAY, "so" to Calendar.SUNDAY)

    class Fest(val day: Int, val h: Int, val m: Int, val to: String, val backH: Int, val backM: Int)

    fun festeWege(ctx: Context): List<Fest> = (prefs(ctx).getString("feste_wege", null)
        ?.let { if (it.trim() == "Donnerstag 15:50 zu Opa, zurück 18:00") FESTE_DEFAULT else it } ?: FESTE_DEFAULT).lines().mapNotNull { l ->
        val r = Regex("(?i)^\\s*(mo|di|mi|do|fr|sa|so)\\w*\\.?\\s+(\\d{1,2})[:.](\\d{2})\\s*(?:uhr)?\\s*(?:zu|zur|zum|nach)?\\s+(.+?)(?:\\s*[,;]?\\s*(?:zurück|heim|wieder zuhause|zuhause|daheim)\\s*(?:an|um|bis)?\\s*(\\d{1,2})[:.](\\d{2}))?\\s*(?:uhr)?\\s*$").find(l)
            ?: return@mapNotNull null
        val g = r.groupValues
        Fest(DAYS[g[1].lowercase().take(2)] ?: return@mapNotNull null, g[2].toInt(), g[3].toInt(), g[4].trim(),
            g[5].toIntOrNull() ?: -1, g[6].toIntOrNull() ?: 0)
    }

    /** Fahrt planen: Regen -> Bahn (erste Verbindung ab "leave"), sonst Rad. */
    private fun tripPlan(ctx: Context, from: Route.P, dest: Route.P, leave: Long, name: String): JSONObject {
        val km = Route.distKm(from, dest)
        val rain = rainAt(from.lat, from.lon, leave)
        if (rain && km >= 1.2) Route.bahnFrom(from, dest, leave)?.let { b ->
            return JSONObject().put("mode", "transit").put("min", (b.arr - leave) / 60_000.0).put("km", km).put("rain", true)
                .put("text", "Es soll regnen, nimm heute die Bahn: ${b.line} um ${clock(b.rideDep)} ab ${b.stop}, an um ${clock(b.arr)}.")
        }
        val walk = km < 1.2
        val min = if (walk) Route.walkMinutes(from, dest) else (learned(ctx, name, "rad") ?: (Route.bikeMinutes(from, dest) + 3))
        return JSONObject().put("mode", if (walk) "walking" else "bicycling").put("min", min).put("km", km).put("rain", rain)
            .put("text", (if (walk) "Zu Fuß" else if (rain) "Es soll regnen, aber ich finde keine Bahn – nimm das Rad mit Regensachen" else "Kein Regen, nimm das Rad") +
                ", du bist gegen ${clock(leave + (min * 60_000).toLong())} da.")
    }

    /** Offene "denk an …"-Notizen für diesen Ort (werden erst bei der Ankunft gelöscht). */
    private fun remindersFor(ctx: Context, place: String): List<String> {
        val a = try { JSONArray(prefs(ctx).getString("ort_erinnerungen", "[]")) } catch (_: Exception) { return emptyList() }
        val p = Chats.norm(place)
        return list(a).filter { o -> val w = Chats.norm(o.optString("ort")); w.isNotBlank() && (w == p || p.contains(w) || w.contains(p) && p.length >= 3) }
            .map { it.optString("text") }
    }

    /**
     * Feste Wege, z. B. "Donnerstag 15:50 zu Opa, zurück 18:00" (alles am Handy, ohne dass du etwas tun musst):
     *  - 5 Minuten vor der Abfahrt (15:45): Briefing – Rad oder Bahn (Regen), wie kalt, was anziehen, worauf achten, "denk an …"
     *  - Abfahrt: Ziel wird gemerkt, ca. 5 Minuten vor der Ankunft geht automatisch die SMS raus (Standort)
     *  - Rückweg ("zurück 18:00" = dann bei Oma und Opa losfahren): 15 und 5 Minuten vorher Bescheid, mit Wetter und Anziehen
     */
    private fun routines(ctx: Context, s: JSONObject, say: (String) -> Unit) {
        val now = System.currentTimeMillis()
        val c = Calendar.getInstance()
        for (f in festeWege(ctx)) {
            if (c.get(Calendar.DAY_OF_WEEK) != f.day) continue
            val leave = todayAt(f.h, f.m)
            val home = Route.home(ctx) ?: continue
            val dest = Route.place(ctx, f.to) ?: continue
            val id = "fest|${f.to}|${today()}"
            val back = if (f.backH >= 0) todayAt(f.backH, f.backM) else 0L
            // Plan ca. 30 Minuten vorher (Wetter, Bahn)
            if (now in leave - 35 * 60_000L..leave + 10 * 60_000L && !done(s, "$id|plan")) {
                mark(s, "$id|plan")
                s.put("fest_plan", tripPlan(ctx, home, dest, leave, f.to).put("id", id))
            }
            val pl = s.optJSONObject("fest_plan")?.takeIf { it.optString("id") == id }
            if (pl != null && now in leave - 5 * 60_000L until leave + 10 * 60_000L && !done(s, "$id|brief")) {
                mark(s, "$id|brief"); s.put("last_ready", now)
                val t = rideBriefing(ctx, "Um ${clock(leave)} geht's los zu ${f.to}.", home, leave, back, pl, remindersFor(ctx, f.to), false) +
                    (if (whoFor(ctx, f.to) != null) " Ich sag Bescheid, kurz bevor du da bist." else "")
                notify(ctx, 332, "Gleich los zu ${f.to}", t); say(t)
            }
            if (pl != null && now in leave..leave + 30 * 60_000L && !done(s, "$id|los")) {   // still: Ziel für die Ankunfts-SMS
                mark(s, "$id|los")
                if (!s.has("ziel")) s.put("ziel", JSONObject().put("name", f.to).put("start", leave).put("min", pl.optDouble("min", 20.0)).put("km", pl.optDouble("km", 5.0)))
            }
            // Rückweg: "zuhause 18:20" = da willst du zuhause ankommen. Jarvis rechnet rückwärts:
            // Ankunft − Fahrzeit (gelernter Durchschnitt) − Fertigmach-Zeit (gelernt, Start 5 Min.) = "Mach dich fertig"-Nachricht
            if (back > 0) {
                val from = dest
                val prepB = prepBack(s)
                if (now in back - 90 * 60_000L..back && !done(s, "$id|bplan")) {
                    mark(s, "$id|bplan")
                    val rain = rainAt(from.lat, from.lon, back - 30 * 60_000L)
                    val bahn = if (rain && Route.distKm(from, home) >= 1.2) Route.bahnBy(from, home, back) else null
                    val ride = learnedRoute(ctx, f.to, "zuhause", "rad") ?: (Route.bikeMinutes(from, home) + 3)
                    val go = bahn?.dep ?: (back - (ride * 60_000).toLong())
                    val text = if (bahn != null) "Es soll regnen, nimm die ${bahn.line} um ${clock(bahn.rideDep)} ab ${bahn.stop}, du bist um ${clock(bahn.arr)} da."
                        else "Mit dem Rad brauchst du etwa ${ride.toInt()} Minuten" + (if (rain) ", nimm Regensachen mit." else ".")
                    s.put("fest_back", JSONObject().put("id", id).put("go", go).put("msg", go - prepB * 60_000L).put("text", text)
                        .put("ride", ride).put("mode", if (bahn != null) "transit" else "bicycling").put("rain", rain))
                }
                val pb = s.optJSONObject("fest_back")?.takeIf { it.optString("id") == id } ?: continue
                val msgAt = pb.optLong("msg"); val go = pb.optLong("go")
                if (now in msgAt until go + 10 * 60_000L && !done(s, "$id|bmsg")) {
                    mark(s, "$id|bmsg"); s.put("back_msg", now)
                    val t = rideBriefing(ctx, "Mach dich fertig, um ${clock(go)} musst du los, dann bist du um ${clock(back)} zuhause.",
                        from, go, 0L, pb, remindersFor(ctx, f.to), false)
                    notify(ctx, 334, "Mach dich fertig – Heimweg", t); say(t)
                }
                // Fertigmach-Zeit lernen: wie lange nach der Nachricht bist du wirklich bei Oma und Opa losgefahren?
                val lp = s.optJSONObject("left_place"); val bm = s.optLong("back_msg")
                if (lp != null && bm > 0 && near(lp.optString("name"), f.to) && lp.optLong("t") - bm in 0..60 * 60_000L && !done(s, "$id|blearn")) {
                    mark(s, "$id|blearn")
                    val a = s.optJSONArray("prep_back") ?: JSONArray()
                    a.put(((lp.optLong("t") - bm) / 60_000L).toInt()); while (a.length() > 8) a.remove(0)
                    s.put("prep_back", a)
                }
            }
        }
    }

    /** Wetter zu einer Stunde: Temperatur, gefühlt, Regen, Wind, Böen, hell/dunkel. */
    private fun hourWeather(lat: Double, lon: Double, t: Long): String = try {
        val url = "https://api.open-meteo.com/v1/forecast?latitude=$lat&longitude=$lon" +
            "&hourly=temperature_2m,apparent_temperature,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,is_day,weather_code" +
            "&timezone=auto&forecast_days=2"
        val h = JSONObject(http.newCall(Request.Builder().url(url).build()).execute().use { it.body?.string() ?: "{}" }).getJSONObject("hourly")
        val key = SimpleDateFormat("yyyy-MM-dd'T'HH:00", de).format(Date(t))
        val i = (0 until h.getJSONArray("time").length()).first { h.getJSONArray("time").getString(it) == key }
        "${h.getJSONArray("temperature_2m").optDouble(i)}° (gefühlt ${h.getJSONArray("apparent_temperature").optDouble(i)}°), " +
            "Regen ${h.getJSONArray("precipitation_probability").optInt(i)} % / ${h.getJSONArray("precipitation").optDouble(i)} mm, " +
            "Wind ${h.getJSONArray("wind_speed_10m").optDouble(i)} km/h, Böen ${h.getJSONArray("wind_gusts_10m").optDouble(i)} km/h, " +
            (if (h.getJSONArray("is_day").optInt(i) == 1) "hell" else "dunkel") + ", Wettercode ${h.getJSONArray("weather_code").optInt(i)}"
    } catch (_: Exception) { "" }

    /** Kurzes Rad-Briefing (gesprochen): Abfahrt, Wetter hin und zurück, Anziehen nach seinen Regeln, worauf er achten muss. */
    private fun rideBriefing(ctx: Context, intro: String, from: Route.P, leave: Long, back: Long, pl: JSONObject,
                             remind: List<String> = emptyList(), short: Boolean = false): String {
        val denk = if (remind.isNotEmpty()) " Denk an: ${remind.joinToString(", ")}." else ""
        val plain = "$intro ${pl.optString("text")}$denk Gute Fahrt!"
        val key = prefs(ctx).getString("groq_key", "") ?: ""
        if (key.isBlank()) return plain
        val w1 = hourWeather(from.lat, from.lon, leave)
        val w2 = if (back > 0) hourWeather(from.lat, from.lon, back) else ""
        if (w1.isBlank()) return plain
        val data = "Ansage: $intro\nVerkehrsmittel: ${pl.optString("text")}\nWetter bei der Abfahrt (${clock(leave)}): $w1" +
            (if (w2.isNotBlank()) "\nWetter auf dem Rückweg (${clock(back)}): $w2" else "") +
            "\nSeine Anzieh-Regeln:\n" + ((prefs(ctx).getString("anzieh", "") ?: "").ifBlank { ANZIEH_DEFAULT }) +
            (if (remind.isNotEmpty()) "\nEr wollte daran erinnert werden: ${remind.joinToString("; ")}" else "")
        val sys = "Du bist Jarvis und gibst Skyler ein kurzes, gesprochenes Briefing für seine Fahrt (" +
            (if (short) "höchstens 2 kurze Sätze: Ansage, Rad oder Bahn, das Wichtigste zum Aufpassen" else "3 bis 5 kurze Sätze") + ", ohne Listen und Sonderzeichen). " +
            "Wenn er an etwas erinnert werden wollte, sag \"Denk an …\". Schließe mit einem kurzen \"Gute Fahrt\" oder \"Viel Erfolg\". " +
            "Beginne mit der Ansage (wann er los muss) und dem Verkehrsmittel (Bahn wegen Regen oder Rad). Dann: wie kalt es ist, was er anziehen soll " +
            "(genau nach seinen Regeln, auch für den Rückweg, wenn es dann kälter oder dunkel ist), und worauf er auf dem Rad achten muss " +
            "(Glätte bei 2 Grad und weniger, starker Wind oder Böen, nasse Straße, Dunkelheit: Licht an). Erfinde nichts, was nicht in den Daten steht."
        return try {
            Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", sys))
                .put(JSONObject().put("role", "user").put("content", data)), 350).replace(Regex("[*#`]"), "").trim().ifBlank { plain }
        } catch (_: Exception) { plain }
    }

    /** "Ich fahr jetzt los zu Opa": Ziel merken, Wetter-Tipp, Bescheid geben kurz vor der Ankunft. */
    fun departNow(ctx: Context, to: String): String {
        val name = Route.savedName(ctx, to) ?: to.trim()
        val dest = Route.place(ctx, name) ?: return "$to kenne ich noch nicht. Trag es unter Wege → Meine Orte ein."
        val from = fixP() ?: Route.home(ctx) ?: return "Ich weiß gerade nicht, wo du bist."
        val now = System.currentTimeMillis()
        val pl = tripPlan(ctx, from, dest, now, name)
        val s = state(ctx)
        s.put("ziel", JSONObject().put("name", name).put("start", now).put("min", pl.optDouble("min", 20.0)).put("km", pl.optDouble("km", 5.0)))
        save(ctx, s)
        val who = whoFor(ctx, name)?.second
        return "Gute Fahrt! ${pl.optString("text")} " +
            (if (who != null) "Ich sag $who Bescheid, kurz bevor du da bist." else "Wem ich Bescheid sagen soll, trägst du unter Alltag → Ankunft ein, z. B. „$name: Opa“.")
    }

    /** Am PC sagen, wenn du dort sitzt, sonst am Handy. */
    private fun deliverSay(ctx: Context, text: String, say: (String) -> Unit) {
        if (pcSay(ctx, text)) return
        if (!quiet(ctx)) say(text)
    }

    // --- Briefings -------------------------------------------------------------------------------------------
    private fun alarms(ctx: Context, s: JSONObject) {
        val am = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val now = System.currentTimeMillis()
        val stored = s.optLong("alarm_next")
        if (stored in 1..now) s.put("alarm_last", stored)
        s.put("alarm_next", am.nextAlarmClock?.triggerTime ?: 0L)
    }

    /** Erstes Entsperren nach dem Wecker -> Morgen-Briefing (auf dem Handy, du hältst es ja gerade). */
    fun onUnlock(ctx: Context, say: (String) -> Unit) {
        if (!on(ctx, "brief_morgen")) return
        val s = state(ctx)
        alarms(ctx, s)
        val last = s.optLong("alarm_last"); val now = System.currentTimeMillis()
        val key = "morgen|${today()}"
        if (last <= 0 || now - last !in 0..3 * 3_600_000L || done(s, key)) return
        mark(s, key); save(ctx, s)
        Thread({
            val t = briefing(ctx, 0) ?: return@Thread
            notify(ctx, 340, "Guten Morgen", t)
            say(t)
        }, "jarvis-morgen").start()
    }

    private fun hm(v: String, def: Int): Pair<Int, Int> = Regex("(\\d{1,2})[:.](\\d{2})").find(v)?.let { it.groupValues[1].toInt() to it.groupValues[2].toInt() }
        ?: (def to 0)

    private fun todayAt(h: Int, m: Int) = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, h); set(Calendar.MINUTE, m); set(Calendar.SECOND, 0) }.timeInMillis

    private fun evening(ctx: Context, s: JSONObject, say: (String) -> Unit) {
        if (!on(ctx, "brief_abend")) return
        val (h, m) = hm(prefs(ctx).getString("brief_abend_zeit", "21:00") ?: "21:00", 21)
        val t0 = todayAt(h, m); val now = System.currentTimeMillis()
        val key = "abend|${today()}"
        if (now < t0 || now > t0 + 2 * 3_600_000L || done(s, key)) return
        mark(s, key)
        Thread({
            val t = briefing(ctx, 1) ?: return@Thread
            notify(ctx, 341, "Für morgen", t)
            if (!pcSay(ctx, t) && !quiet(ctx)) say(t)
        }, "jarvis-abend").start()
    }

    /** day 0 = heute (morgens), 1 = morgen (abends). */
    private fun briefing(ctx: Context, day: Int): String? {
        val key = prefs(ctx).getString("groq_key", "") ?: ""
        if (key.isBlank()) return null
        val p = prefs(ctx)
        val dayStart = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, day); set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0) }.timeInMillis
        val evs = Cal.events(ctx, maxOf(dayStart, if (day == 0) System.currentTimeMillis() else 0), dayStart + 86_400_000L)
        val parts = mutableListOf<String>()
        val want = { k: String -> p.getBoolean(k, true) }
        if (want("bi_wetter") || want("bi_anzieh")) parts.add("Wetter Leonberg ${if (day == 0) "heute" else "morgen"}:\n" + weatherDay(ctx, day))
        if (want("bi_anzieh")) parts.add("Seine Anzieh-Regeln:\n" + (p.getString("anzieh", "") ?: "").ifBlank { ANZIEH_DEFAULT })
        if (want("bi_termine") || want("bi_mitnehmen")) parts.add("Termine:\n" + (Cal.describe(evs).ifBlank { "keine" }))
        if (want("bi_mitnehmen")) parts.add("Was du über ihn weißt:\n" + Memory.facts(ctx).takeLast(40).joinToString("\n") { "- $it" })
        if (day == 1) (ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager).nextAlarmClock?.triggerTime?.let {
            if (it - dayStart in 0..86_400_000L) parts.add("Sein Wecker morgen: ${clock(it)}")
        }
        val topics = listOf("bi_wetter" to "Wetter (vor allem für die Radfahrt morgens und nachmittags)", "bi_anzieh" to "was er anziehen soll, genau nach seinen Regeln",
            "bi_termine" to "Termine", "bi_mitnehmen" to "was er mitnehmen oder vorbereiten sollte (nur wenn es aus den Terminen folgt)")
            .filter { want(it.first) }.joinToString(", ") { it.second }
        val sys = "Du bist Jarvis und gibst Skyler sein ${if (day == 0) "Morgen-Briefing für heute" else "Abend-Briefing für morgen"}. " +
            "Gesprochen, locker, ohne Listen und Sonderzeichen, 4 bis 7 kurze Sätze. Inhalt: $topics" +
            (if (day == 1) ", und zum Schluss, wann sein Wecker klingelt (falls bekannt)." else ".") +
            " Keine Bahn-Verbindungen. Erfinde nichts, was nicht in den Daten steht. Beginne mit " + (if (day == 0) "\"Guten Morgen\"." else "\"Kurz zu morgen\".")
        return try {
            Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", sys))
                .put(JSONObject().put("role", "user").put("content", parts.joinToString("\n\n"))), 500).replace(Regex("[*#`]"), "").trim()
        } catch (e: Exception) { Log.w(TAG, "briefing: $e"); null }
    }

    /** Briefing auf Zuruf ("Was steht morgen an?" bleibt beim Gehirn; das hier für "gib mir das Briefing"). */
    fun briefingNow(ctx: Context, tomorrow: Boolean): String = briefing(ctx, if (tomorrow) 1 else 0) ?: "Fürs Briefing brauche ich den Groq-Schlüssel."

    // --- Wochenrückblick -------------------------------------------------------------------------------------
    private fun weekly(ctx: Context, s: JSONObject) {
        if (!on(ctx, "rueckblick")) return
        val c = Calendar.getInstance()
        if (c.get(Calendar.DAY_OF_WEEK) != Calendar.SUNDAY) return
        val (h, m) = hm(prefs(ctx).getString("rueckblick_zeit", "18:00") ?: "18:00", 18)
        val t0 = todayAt(h, m); val now = System.currentTimeMillis()
        val key = "woche|${today()}"
        if (now < t0 || now > t0 + 4 * 3_600_000L || done(s, key)) return
        mark(s, key)
        Thread({
            val t = weekText(ctx) ?: return@Thread
            notify(ctx, 350, "Dein Wochenrückblick", t)
            try {
                if (Link.paired(ctx)) Link.command(ctx, JSONObject().put("type", "offer").put("need_active", true).put("title", "Wochenrückblick")
                    .put("question", "Dein Wochenrückblick ist da. Soll ich ihn öffnen?").put("text", t), 15_000)
            } catch (_: Exception) {}
        }, "jarvis-woche").start()
    }

    fun weekText(ctx: Context): String? {
        val key = prefs(ctx).getString("groq_key", "") ?: ""
        if (key.isBlank()) return null
        val since = System.currentTimeMillis() - 7 * 86_400_000L
        val week = list(trips(ctx)).filter { it.optLong("end") >= since }
        val visits = week.groupingBy { it.optString("to") }.eachCount().filterKeys { it != "zuhause" }
        val radKm = week.filter { it.optString("mode") == "rad" }.sumOf { it.optDouble("km") }
        val music = Interests.musicMinutes(ctx, since)
        val now = System.currentTimeMillis()
        val next = Cal.events(ctx, now, now + 7 * 86_400_000L)
        val data = "Besuche (Fahrten zu gespeicherten Orten): ${visits.entries.joinToString { "${it.key}: ${it.value}x" }.ifBlank { "keine erfasst" }}\n" +
            "Rad-Kilometer: ${"%.1f".format(radKm)}\nMusik gehört (Handy): etwa ${music / 60} Stunden ${music % 60} Minuten\n" +
            "Termine nächste Woche:\n${Cal.describe(next).ifBlank { "keine" }}\n" +
            "Was du über ihn weißt:\n" + Memory.facts(ctx).takeLast(30).joinToString("\n") { "- $it" }
        val sys = "Du bist Jarvis und schreibst Skylers Wochenrückblick, locker und kurz (6 bis 9 Sätze, ohne Listen): wie oft er bei Opa " +
            "bzw. den Großeltern war, wie viele Kilometer er mit dem Rad gefahren ist, wie lange er Musik gehört hat (keine Liedliste), " +
            "dann die Termine der nächsten Woche und was er dafür mitnehmen oder vorbereiten sollte. Erfinde nichts. Wenn etwas nicht erfasst ist, sag es kurz."
        return try {
            Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", sys)).put(JSONObject().put("role", "user").put("content", data)), 600)
                .replace(Regex("[*#`]"), "").trim()
        } catch (_: Exception) { null }
    }
}

class AlltagReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action == Alltag.ACTION_CANCEL) Alltag.cancelAway(ctx)
    }
}
