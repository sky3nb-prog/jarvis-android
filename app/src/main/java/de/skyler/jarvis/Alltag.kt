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

    const val ANZIEH_DEFAULT = "Nach der gefühlten Temperatur:\n" +
        "unter 0 Grad: Winterjacke, Pulli, dicke lange Hose, Mütze, Handschuhe, Schal\n" +
        "0 bis 7 Grad: Winterjacke, Pulli, lange Hose, Mütze, Handschuhe\n" +
        "7 bis 12 Grad: Softshelljacke, Pulli, lange Hose\n" +
        "12 bis 17 Grad: dünne Jacke, T-Shirt, lange Hose\n" +
        "17 bis 22 Grad: T-Shirt, dünne lange Hose, dünne Jacke zum Mitnehmen\n" +
        "über 22 Grad: T-Shirt, kurze Hose\n" +
        "Regen: Regenjacke drüber, auf dem Rad Regenhose\n" +
        "Wind über 30 km/h: winddichte Softshelljacke"

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
    private fun notify(ctx: Context, id: Int, title: String, text: String, cancelAction: Boolean = false, url: String? = null, feed: String? = null) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "Alltag (Losfahren, Briefings, Zuhause)", NotificationManager.IMPORTANCE_HIGH))
        val b = NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title).setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text)).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH)
        if (cancelAction) b.addAction(0, "Abbrechen", PendingIntent.getBroadcast(ctx, 5, Intent(ctx, AlltagReceiver::class.java).setAction(ACTION_CANCEL),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        val open = if (url != null) Intent(Intent.ACTION_VIEW, Uri.parse(url))
            else Intent(ctx, MainActivity::class.java).apply { if (feed != null) putExtra("feed", feed) }
        b.setContentIntent(PendingIntent.getActivity(ctx, id, open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        try { nm.notify(id, b.build()) } catch (_: Exception) {}
    }

    /**
     * Nachts noch am Handy (ab 22:30): "Wenn du jetzt schläfst, sind es noch X Stunden bis zum Aufstehen."
     * Einmal, sobald es unter 8½ Stunden sind, und noch einmal unter 6 Stunden. Nur Benachrichtigung, leise.
     */
    private fun sleepNudge(ctx: Context, s: JSONObject) {
        if (!on(ctx, "schlaf_tipp")) return
        val c = Calendar.getInstance(); val h = c.get(Calendar.HOUR_OF_DAY); val mi = c.get(Calendar.MINUTE)
        if (!((h == 22 && mi >= 30) || h == 23 || h < 4)) return
        val pm = ctx.getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
        if (!pm.isInteractive) return
        val now = System.currentTimeMillis()
        val dayStart = Calendar.getInstance().apply { if (h >= 12) add(Calendar.DAY_OF_YEAR, 1); set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }.timeInMillis
        val up = Wecker.upFor(ctx, dayStart) ?: return
        val left = (up - now) / 60_000L
        if (left <= 0) return
        val key = SimpleDateFormat("yyyy-MM-dd", de).format(Date(dayStart))
        val stage = if (left < 6 * 60) 2 else if (left < 8 * 60 + 30) 1 else 0
        if (stage == 0 || s.optInt("schlaf_tipp_$key") >= stage) return
        s.put("schlaf_tipp_$key", stage)
        val t = "Wenn du jetzt schläfst, sind es noch ${Sleep.dur(left)} bis zum Aufstehen um ${SimpleDateFormat("H:mm", de).format(Date(up))}." +
            (if (stage == 2) " Das wird knapp – leg das Handy weg." else "")
        notify(ctx, 346, "Schlafenszeit", t)
    }

    /** Wieder zuhause nach einem echten Ausflug (Briefing mit Anziehen): einmal am Tag "zu kalt / passt / zu warm". */
    const val ACTION_SCHRANK = "de.skyler.jarvis.SCHRANK"
    private fun wardrobeAsk(ctx: Context, s: JSONObject) {
        if (!s.optBoolean("is_home")) return
        val lt = Wardrobe.lastTrip(ctx) ?: return
        if (!Wardrobe.get(ctx).optBoolean("fragen", true)) return
        val now = System.currentTimeMillis(); val age = now - lt.optLong("ts")
        if (age < 60 * 60_000L) return
        if (age > 14 * 3_600_000L) { prefs(ctx).edit().remove("schrank_letzt").apply(); return }
        val key = "schrank|${today()}"
        if (done(s, key)) return
        mark(s, key)
        val p = lt.optJSONObject("pick") ?: return
        val txt = "Du hattest ${p.optString("jacke")} an" + (if (p.optString("oben").isNotBlank()) ", drunter ${p.optString("oben")}" else "") +
            (if (lt.optString("wo").isNotBlank()) " (${lt.optString("wo")})" else "") + ". War das richtig?"
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "Alltag (Losfahren, Briefings, Zuhause)", NotificationManager.IMPORTANCE_HIGH))
        fun act(v: Int, label: String) = NotificationCompat.Action(0, label, PendingIntent.getBroadcast(ctx, 600 + v + 1,
            Intent(ctx, AlltagReceiver::class.java).setAction(ACTION_SCHRANK).putExtra("v", v), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        val b = NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("Wie war's mit den Klamotten?")
            .setContentText(txt).setStyle(NotificationCompat.BigTextStyle().bigText(txt)).setAutoCancel(true)
            .addAction(act(-1, "🥶 Zu kalt")).addAction(act(0, "👍 Passt")).addAction(act(1, "🥵 Zu warm"))
        try { nm.notify(362, b.build()) } catch (_: Exception) {}
    }

    /** Alle 3 Stunden: gibt es eine neuere APK? Dann Benachrichtigung, Antippen lädt sie. */
    private const val APK = "https://github.com/sky3nb-prog/jarvis-android/releases/download/neueste/Jarvis.apk"
    private fun appUpdate(ctx: Context, s: JSONObject) {
        val now = System.currentTimeMillis()
        if (now - s.optLong("upd_check") < 3 * 3_600_000L) return
        s.put("upd_check", now)
        Thread({
            try {
                val js = JSONObject(http.newCall(Request.Builder().url("https://api.github.com/repos/sky3nb-prog/jarvis-android/releases/tags/neueste")
                    .header("Accept", "application/vnd.github+json").build()).execute().use { it.body?.string() ?: "{}" })
                val build = Regex("Build (\\d+)").find(js.optString("name"))?.groupValues?.get(1)?.toLongOrNull() ?: return@Thread
                val pi = ctx.packageManager.getPackageInfo(ctx.packageName, 0)
                val mine = if (Build.VERSION.SDK_INT >= 28) pi.longVersionCode else @Suppress("DEPRECATION") pi.versionCode.toLong()
                val p = prefs(ctx)
                if (build > mine && p.getLong("upd_told", 0) != build) {
                    p.edit().putLong("upd_told", build).apply()
                    notify(ctx, 360, "Neue Jarvis-Version da", "Antippen zum Herunterladen, dann installieren (Build $build).", url = APK)
                }
            } catch (e: Exception) { Log.w(TAG, "update: $e") }
        }, "jarvis-upd").start()
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
    @Volatile var lastTestFeed: String? = null

    fun testMessage(ctx: Context, bahn: Boolean = false): String {
        val f = festeWege(ctx).firstOrNull()
        val to = f?.to ?: "Opa"
        val label = f?.label ?: to
        val home = Route.home(ctx) ?: return "Trag erst deine Adresse ein (Allgemein → Standort)."
        val dest = Route.place(ctx, to) ?: return "Das Ziel „$to“ finde ich nicht. Trag eine genaue Adresse ein."
        val now = System.currentTimeMillis()
        val leave = now + 5 * 60_000L
        val pl = tripPlan(ctx, home, dest, leave, to, f?.mode ?: "ebike", if (bahn) "immer" else (f?.bahnHin ?: "regen"))
        if (bahn && pl.optString("mode") != "transit") return "Ich finde gerade keine Bahnverbindung zu $label (Fahrplan nicht erreichbar oder zu nah)."
        val wer = f?.wer?.ifBlank { null } ?: whoFor(ctx, label)?.second
        val intro = if (pl.optString("mode") == "transit") "Zu $label:" else "Um ${clock(leave)} geht's los zu $label."
        val (t0, fid) = rideBrief(ctx, "fahrt", "Gleich los zu $label (Test)", intro, home, pl.optLong("go", leave), now + 2 * 3_600_000L, pl,
            remindersFor(ctx, label), false, JSONObject().put("ziel", label).put("sms_to", wer ?: "").put("test", true)
                .put("home_at", f?.let { if (it.backH >= 0) todayAt(it.backH, it.backM) else 0L } ?: 0L))
        val t = (if (bahn) "[Bahn-Test] " else "[Test] ") + t0 + (if (wer != null) " Ich sag $wer Bescheid, kurz bevor du da bist." else "")
        notify(ctx, 339, "Gleich los zu $label (Test)", t, feed = fid)
        lastTestFeed = fid
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
                .put("min", min).put("km", km).put("mode", mode).put("path", simplify(pts)))
            while (a.length() > 500) a.remove(0)
            try { tripsFile(ctx).writeText(a.toString()) } catch (_: Exception) {}
            Log.i(TAG, "Fahrt ${t.optString("from")} -> $to: ${min.toInt()} min, ${"%.1f".format(km)} km, $mode")
        }
        s.put("trip", JSONObject().put("from", to).put("start", 0L).put("pts", JSONArray()))
    }

    // --- Ziel selbst erkennen (gelernte Strecken) ----------------------------------------------------------
    /** Strecke ausdünnen: ein Punkt alle ~120 m, höchstens 80 Punkte (fürs Wiedererkennen). */
    private fun simplify(pts: JSONArray): JSONArray {
        val out = JSONArray(); var lastLat = 0.0; var lastLon = 0.0
        for (i in 0 until pts.length()) {
            val p = pts.optJSONArray(i) ?: continue
            val la = p.optDouble(1); val lo = p.optDouble(2)
            if (out.length() == 0 || Route.distKm(Route.P(la, lo, ""), Route.P(lastLat, lastLon, "")) > 0.12) {
                out.put(JSONArray().put(Math.round(la * 1e5) / 1e5).put(Math.round(lo * 1e5) / 1e5)); lastLat = la; lastLon = lo
            }
        }
        while (out.length() > 80) { val k = JSONArray(); for (i in 0 until out.length()) if (i % 2 == 0 || i == out.length() - 1) k.put(out.get(i)); return k }
        return out
    }

    /**
     * Wie gut passt die aktuelle Fahrt zu deinen gelernten Strecken nach [place]? 0..1 (Anteil der letzten Punkte, die
     * höchstens 150 m neben einer früheren Strecke dorthin liegen) – und du kommst dem Ziel näher. -1 = noch keine Strecke gelernt.
     */
    private fun routeScore(ctx: Context, trip: JSONObject, place: String, dest: Route.P?): Double {
        val paths = list(trips(ctx)).filter { near(it.optString("to"), place) && (it.optJSONArray("path")?.length() ?: 0) >= 3 }.takeLast(12).map { it.getJSONArray("path") }
        if (paths.isEmpty()) return -1.0
        val pts = trip.optJSONArray("pts") ?: return 0.0
        if (pts.length() < 4) return 0.0
        val recent = (maxOf(0, pts.length() - 12) until pts.length()).map { pts.getJSONArray(it) }.map { Route.P(it.getDouble(1), it.getDouble(2), "") }
        var hit = 0
        for (p in recent) if (paths.any { path -> (0 until path.length()).any { k -> val q = path.getJSONArray(k); Route.distKm(p, Route.P(q.getDouble(0), q.getDouble(1), "")) < 0.15 } }) hit++
        var score = hit.toDouble() / recent.size
        if (dest != null) {   // muss dem Ziel näher kommen
            val first = pts.getJSONArray(0); val d0 = Route.distKm(Route.P(first.getDouble(1), first.getDouble(2), ""), dest)
            if (Route.distKm(recent.last(), dest) >= d0) score *= 0.3
        }
        return score
    }

    const val ACTION_ZIEL = "de.skyler.jarvis.ZIEL"
    /** Antwort auf "Fährst du zu …?" (Ja/Nein in der Benachrichtigung) */
    fun zielAnswer(ctx: Context, place: String, yes: Boolean) {
        val s = state(ctx); val start = s.optJSONObject("trip")?.optLong("start") ?: 0L
        s.put("ziel_antwort", JSONObject().put("place", place).put("yes", yes).put("start", start)); save(ctx, s)
        ctx.getSystemService(NotificationManager::class.java).cancel(363)
    }

    private fun askZiel(ctx: Context, place: String) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "Alltag (Losfahren, Briefings, Zuhause)", NotificationManager.IMPORTANCE_HIGH))
        fun act(yes: Boolean) = NotificationCompat.Action(0, if (yes) "Ja" else "Nein", PendingIntent.getBroadcast(ctx, if (yes) 701 else 702,
            Intent(ctx, AlltagReceiver::class.java).setAction(ACTION_ZIEL).putExtra("place", place).putExtra("yes", yes), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
        val label = place.replaceFirstChar { it.uppercase() }
        val b = NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.ic_dialog_map).setContentTitle("Fährst du zu $label?")
            .setContentText("Dann sag ich kurz vorher Bescheid und denk an deine Erinnerungen.").setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH)
            .addAction(act(true)).addAction(act(false))
        try { nm.notify(363, b.build()) } catch (_: Exception) {}
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
        notify(ctx, 310, "Erinnerung", t, feed = Feed.add(ctx, "erinnerung", "Erinnerung bei ${place}", due.joinToString(", "), t, JSONObject().put("denk", JSONArray(due)).put("ort", place)))
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
        try { Halte.tick(ctx, fix, isHome(ctx)) } catch (e: Exception) { Log.w(TAG, "halte: $e") }
        try { leaveInTime(ctx, s, say) } catch (e: Exception) { Log.w(TAG, "losfahren: $e") }
        try { routines(ctx, s, say) } catch (e: Exception) { Log.w(TAG, "feste wege: $e") }
        try { alarms(ctx, s) } catch (_: Exception) {}
        try {   // Wecker für morgen (Aufsteh-Zeit an Schultagen/Wochenende)
            Wecker.tick(ctx) { day -> Cal.events(ctx, day, day + 86_400_000L).any { it.allDay && Regex("(?i)ferien|feiertag|frei\\b|urlaub").containsMatchIn(it.title) } }
                ?.let { msg -> notify(ctx, 345, "Wecker für morgen", msg, feed = Feed.add(ctx, "wecker", "Wecker für morgen", msg, msg)) }
        } catch (e: Exception) { Log.w(TAG, "wecker: $e") }
        try {   // Morgen-Briefing: 10 Minuten vor der Aufsteh-Zeit als Benachrichtigung bereit (ohne Entsperren)
            val up = upTime(ctx); val now = System.currentTimeMillis(); val key = "morgen|${today()}"
            if (up != null && now >= up - 10 * 60_000L && now < up + 4 * 3_600_000L && !done(s, key) && on(ctx, "brief_morgen")) {
                mark(s, key); save(ctx, s)
                Thread({
                    val (t, fid) = dayBrief(ctx, 0) ?: return@Thread
                    notify(ctx, 340, "Guten Morgen – dein Tag", t, feed = fid)
                }, "jarvis-morgen").start()
            }
        } catch (_: Exception) {}
        try { evening(ctx, s, say) } catch (e: Exception) { Log.w(TAG, "abend: $e") }
        try { weekly(ctx, s) } catch (e: Exception) { Log.w(TAG, "rückblick: $e") }
        try { bilanz(ctx, s, say) } catch (e: Exception) { Log.w(TAG, "bilanz: $e") }
        try { appUpdate(ctx, s) } catch (_: Exception) {}
        try { sleepNudge(ctx, s) } catch (_: Exception) {}
        try { wardrobeAsk(ctx, s) } catch (_: Exception) {}
        try {   // Akku unter 20 % unterwegs: einmal Bescheid (bis wieder geladen wurde)
            val b = ctx.registerReceiver(null, android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            if (b != null) {
                val lvl = b.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1) * 100 / maxOf(1, b.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, 100))
                val charging = b.getIntExtra(android.os.BatteryManager.EXTRA_PLUGGED, 0) != 0
                if (charging || lvl >= 30) s.put("akku_warn", false)
                else if (lvl in 0..19 && !s.optBoolean("is_home") && !s.optBoolean("akku_warn")) {
                    s.put("akku_warn", true)
                    notify(ctx, 365, "Akku $lvl %", "Du bist unterwegs und der Akku ist unter 20 %. Ich schalte nichts ab – aber lad bald, damit SMS und Navigation weiterlaufen.")
                }
            }
        } catch (_: Exception) {}
        try { Remind.tick(ctx, s, s.optBoolean("is_home"), todayWege(ctx).isNotEmpty()) } catch (e: Exception) { Log.w(TAG, "erinnern: $e") }
        try {   // einmal am Tag still prüfen, nur bei Problemen eine Benachrichtigung
            val now = System.currentTimeMillis()
            if (now - s.optLong("syscheck_t") > 24 * 3_600_000L && Calendar.getInstance().get(Calendar.HOUR_OF_DAY) in 9..21) {
                s.put("syscheck_t", now)
                Thread({
                    try {
                        val a = SysCheck.run(ctx)
                        if ((0 until a.length()).any { a.getJSONObject(it).opt("ok") == false })
                            notify(ctx, 361, "Jarvis-Systemcheck", SysCheck.summary(a))
                    } catch (_: Exception) {}
                }, "jarvis-check").start()
            }
        } catch (_: Exception) {}
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
        s.put("is_home", isHome)

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
        for (name in (Route.lines(ctx, "orte").keys + todayWege(ctx).map { it.to }).distinct()) {
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
        val (place, who) = z.optString("wer").takeIf { it.isNotBlank() }?.let { name to it } ?: whoFor(ctx, z.optString("label").ifBlank { name }) ?: whoFor(ctx, name) ?: return
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
        val ans = s.optJSONObject("ziel_antwort")?.takeIf { it.optLong("start") == start }
        for ((place, who) in Route.lines(ctx, "ankunft")) {
            val key = "ankunft|$place|${today()}"
            if (done(s, key) || trip.optString("from").equals(place, true)) continue
            val p = Route.place(ctx, place) ?: continue
            val d = Route.distKm(here, p)
            if (d < 0.3 || d > speed * 20) continue
            val eta = d * 1.25 / speed
            // Ziel sicher? Fester Weg (Ziel gesetzt) oder genau deine gelernte Strecke -> automatisch. Sonst einmal fragen.
            val planned = s.optJSONObject("ziel")?.let { near(it.optString("name"), place) || near(it.optString("label"), place) } == true
            val score = routeScore(ctx, trip, place, p)
            val sure = planned || score >= 0.8 || (ans != null && ans.optBoolean("yes") && near(ans.optString("place"), place))
            if (ans != null && !ans.optBoolean("yes") && near(ans.optString("place"), place)) continue   // "Nein" gesagt
            if (!sure) {
                val askKey = "zielfrage|$place|$start"
                if (eta <= 14 && score >= 0.0 && !done(s, askKey)) { mark(s, askKey); askZiel(ctx, place) }
                if (eta <= 14 && score < 0 && !done(s, askKey)) { mark(s, askKey); askZiel(ctx, place) }   // neue Strecke: auch fragen
                continue
            }
            if (!done(s, "zielsicher|$place|$start")) {   // sicher erkannt: Ort-Erinnerungen schon unterwegs
                mark(s, "zielsicher|$place|$start")
                val rem = remindersFor(ctx, place)
                if (rem.isNotEmpty() && !planned) notify(ctx, 364, "Unterwegs zu ${place.replaceFirstChar { it.uppercase() }}", "Denk an: ${rem.joinToString(", ")}")
            }
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
        val fid = Feed.add(ctx, "ankunft", if (ok) "Ankunft angekündigt" else "Ankunft: SMS ging nicht", if (ok) "An $who: $text" else "SMS-Recht fehlt",
            if (ok) "An $who: $text" else "Erlaube SMS in den Einstellungen unter Leute.", JSONObject().put("an", who).put("sms", text).put("ok", ok).put("ort", place).put("um", at))
        notify(ctx, 320, if (ok) "Ankunft angekündigt" else "Ankunft: SMS ging nicht", if (ok) "An $who: $text" else "Erlaube SMS in den Einstellungen unter Leute.", feed = fid)
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

    // --- Feste Wege (jede Woche) und einmalige Termine (an einem Datum) ---------------------------------------
    const val FESTE_DEFAULT = "Donnerstag 15:50 zu Opa, zuhause 18:20"
    private val DAYS = mapOf("mo" to Calendar.MONDAY, "di" to Calendar.TUESDAY, "mi" to Calendar.WEDNESDAY, "do" to Calendar.THURSDAY,
        "fr" to Calendar.FRIDAY, "sa" to Calendar.SATURDAY, "so" to Calendar.SUNDAY)

    /** to = Ziel (gespeicherter Ort oder Adresse), name = wie Jarvis es nennt, mode = ebike/rad/fuss, wer = SMS kurz vor der Ankunft an. */
    class Fest(val day: Int, val h: Int, val m: Int, val to: String, val backH: Int, val backM: Int,
               val mode: String = "ebike", val wer: String = "", val name: String = "", val key: String = "",
               val bahnHin: String = "regen", val bahnZurueck: String = "regen") {
        val label get() = name.ifBlank { to }
    }

    private fun hmOf(v: String?): Pair<Int, Int>? = Regex("(\\d{1,2})[:.](\\d{2})").find(v ?: "")?.groupValues?.let { it[1].toInt() to it[2].toInt() }

    private fun festOf(o: JSONObject, day: Int, key: String): Fest? {
        val los = hmOf(o.optString("los")) ?: return null
        val ziel = o.optString("ziel").trim().ifBlank { return null }
        val heim = hmOf(o.optString("zuhause"))
        return Fest(day, los.first, los.second, ziel, heim?.first ?: -1, heim?.second ?: 0,
            o.optString("mode", "ebike").ifBlank { "ebike" }, o.optString("wer").trim(), o.optString("name").trim(), key,
            o.optString("bahn_hin", "regen").ifBlank { "regen" }, o.optString("bahn_zurueck", "regen").ifBlank { "regen" })
    }

    /** Der feste Weg aus der App (Tag, Ziel, Zeiten, Fahrzeug, SMS an). */
    fun festerWeg(ctx: Context): JSONObject {
        prefs(ctx).getString("fester_weg", null)?.let { try { return JSONObject(it) } catch (_: Exception) {} }
        return JSONObject().put("tag", "do").put("ziel", "Opa").put("name", "Oma und Opa").put("los", "15:50").put("zuhause", "18:20")
            .put("mode", "ebike").put("wer", "").put("an", true)
    }

    fun festeWege(ctx: Context): List<Fest> {
        val o = festerWeg(ctx)
        if (!o.optBoolean("an", true)) return emptyList()
        val day = DAYS[o.optString("tag", "do").lowercase().take(2)] ?: return emptyList()
        return listOfNotNull(festOf(o, day, "fest"))
    }

    // Einmalige Termine: [{datum:"2026-11-19", ziel, name, los, zuhause, mode, wer} | {datum, aus:true}]
    fun einmalig(ctx: Context): JSONArray {
        val a = try { JSONArray(prefs(ctx).getString("einmalig", "[]")) } catch (_: Exception) { JSONArray() }
        val keep = JSONArray()
        for (o in list(a)) if (o.optString("datum") >= today()) keep.put(o)   // Vergangenes fällt weg
        return keep
    }

    fun einmaligAdd(ctx: Context, o: JSONObject): String {
        val a = einmalig(ctx)
        val d = o.optString("datum").ifBlank { today() }
        o.put("datum", d)
        if (o.optBoolean("aus")) {
            val keep = JSONArray(); for (x in list(a)) if (!(x.optString("datum") == d && x.optBoolean("aus"))) keep.put(x)
            keep.put(JSONObject().put("datum", d).put("aus", true))
            prefs(ctx).edit().putString("einmalig", keep.toString()).apply()
            return "Okay, am ${dayName(d)} fällt der feste Weg aus."
        }
        if (hmOf(o.optString("los")) == null || o.optString("ziel").isBlank()) return "Gib Ziel und Losfahr-Zeit an."
        a.put(o)
        prefs(ctx).edit().putString("einmalig", a.toString()).apply()
        val los = hmOf(o.optString("los"))!!
        val brief = los.first * 60 + los.second - 5
        return "Eingetragen für ${dayName(d)}: um ${"%d:%02d".format(brief / 60, brief % 60)} bekommst du das Briefing, um ${o.optString("los")} geht's los zu " +
            o.optString("name").ifBlank { o.optString("ziel") } +
            (if (hmOf(o.optString("zuhause")) != null) ", zuhause willst du um ${o.optString("zuhause")} sein – ich schick dich passend los." else ".")
    }

    fun einmaligRemove(ctx: Context, i: Int) {
        val a = einmalig(ctx); val keep = JSONArray()
        for (k in 0 until a.length()) if (k != i) keep.put(a.get(k))
        prefs(ctx).edit().putString("einmalig", keep.toString()).apply()
    }

    private fun dayName(d: String): String = try {
        val t = SimpleDateFormat("yyyy-MM-dd", de).parse(d)!!.time
        val diff = Math.round((t - SimpleDateFormat("yyyy-MM-dd", de).parse(today())!!.time) / 86_400_000.0)
        when (diff) { 0L -> "heute"; 1L -> "morgen"; 2L -> "übermorgen"; else -> SimpleDateFormat("EEEE, d. MMMM", de).format(Date(t)) }
    } catch (_: Exception) { d }

    /** Alle Wege für heute: fester Weg (falls nicht "fällt aus") + einmalige Termine von heute. */
    fun todayWege(ctx: Context): List<Fest> {
        val dow = Calendar.getInstance().get(Calendar.DAY_OF_WEEK)
        val day = list(einmalig(ctx)).filter { it.optString("datum") == today() }
        val base = if (day.any { it.optBoolean("aus") }) emptyList() else festeWege(ctx).filter { it.day == dow }
        return base + day.filter { !it.optBoolean("aus") }.mapIndexedNotNull { i, o -> festOf(o, dow, "einmal$i") }
    }

    /** Weg an einem Tag (yyyy-MM-dd): Name/Ziel oder null – für Erledigungen ohne Uhrzeit. */
    fun wegOn(ctx: Context, d: String): String? {
        val dow = Calendar.getInstance().apply { time = SimpleDateFormat("yyyy-MM-dd", de).parse(d) ?: Date() }.get(Calendar.DAY_OF_WEEK)
        val day = list(einmalig(ctx)).filter { it.optString("datum") == d }
        day.firstOrNull { !it.optBoolean("aus") }?.let { return it.optString("name").ifBlank { it.optString("ziel") } }
        if (day.any { it.optBoolean("aus") }) return null
        return festeWege(ctx).firstOrNull { it.day == dow }?.let { it.label }
    }

    /** Bin ich gerade zuhause? (letzte Erkennung) */
    fun isHome(ctx: Context): Boolean = state(ctx).optBoolean("is_home", false)

    /** Per Sprache: "heute will ich um 19 Uhr zuhause sein", "heute fahr ich nicht zu Opa", "morgen um 14 Uhr zur Musikschule". */
    /**
     * Per Sprache: "heute fahr ich um 16:10 zu Opa" (los = hier losfahren) oder "ich will um 14:50 bei Oma und Opa sein"
     * (an = dort ankommen -> Jarvis rechnet die Losfahr-Zeit selbst: Fahrzeit gelernt, bei Regen/Bahn die passende Verbindung).
     * Danach gleich ein Vorab-Briefing (worauf achten), und der Rest läuft wie beim festen Weg.
     */
    fun setToday(ctx: Context, ziel: String, los: String, zuhause: String, aus: Boolean, datum: String = "", an: String = ""): String {
        val d = datum.ifBlank { today() }
        if (aus) return einmaligAdd(ctx, JSONObject().put("datum", d).put("aus", true))
        val dow = Calendar.getInstance().apply { time = SimpleDateFormat("yyyy-MM-dd", de).parse(d) ?: Date() }.get(Calendar.DAY_OF_WEEK)
        val fw = festerWeg(ctx)
        val sameDest = ziel.isBlank() || near(ziel, fw.optString("ziel")) || near(ziel, fw.optString("name"))
        val f = fw.takeIf { DAYS[it.optString("tag").lowercase().take(2)] == dow && it.optBoolean("an", true) && sameDest }
        val tmpl = if (sameDest) fw else null   // gleiches Ziel wie der feste Weg: SMS-Empfänger, Fahrzeit, Bahn-Einstellung übernehmen
        val o = JSONObject().put("datum", d).put("ziel", ziel.ifBlank { fw.optString("ziel") }.let { if (sameDest) fw.optString("ziel").ifBlank { it } else it })
            .put("name", if (sameDest) fw.optString("name") else "")
            .put("los", los.ifBlank { if (an.isBlank()) f?.optString("los") ?: "" else "" }).put("zuhause", zuhause.ifBlank { f?.optString("zuhause") ?: "" })
            .put("mode", tmpl?.optString("mode") ?: "ebike").put("wer", tmpl?.optString("wer") ?: "")
            .put("bahn_hin", tmpl?.optString("bahn_hin") ?: "regen").put("bahn_zurueck", tmpl?.optString("bahn_zurueck") ?: "regen")
        val label = o.optString("name").ifBlank { o.optString("ziel") }
        val home = Route.home(ctx); val dest = Route.place(ctx, o.optString("ziel"))
        // Ankunftszeit -> Losfahr-Zeit selbst rechnen
        if (an.isNotBlank() && o.optString("los").isBlank()) {
            val (h, m) = hmOf(an) ?: return "Um wie viel Uhr willst du bei $label sein?"
            val arriveAt = Calendar.getInstance().apply { time = SimpleDateFormat("yyyy-MM-dd", de).parse(d) ?: Date(); set(Calendar.HOUR_OF_DAY, h); set(Calendar.MINUTE, m); set(Calendar.SECOND, 0) }.timeInMillis
            if (home == null || dest == null) return "Ich weiß noch nicht, wo $label ist. Trag es unter Wege & Orte ein."
            val guess = tripPlan(ctx, home, dest, arriveAt - 30 * 60_000L, o.optString("ziel"), o.optString("mode"), o.optString("bahn_hin"))
            val leave = if (guess.optString("mode") == "transit") (Route.bahnBy(home, dest, arriveAt)?.dep ?: guess.optLong("go"))
                else arriveAt - ((guess.optDouble("min", 20.0) + 2) * 60_000).toLong()
            o.put("los", SimpleDateFormat("HH:mm", de).format(Date(leave))).put("an", an)
        }
        if (f != null) {   // der feste Weg wird an dem Tag durch den geänderten ersetzt
            val keep = einmalig(ctx); keep.put(JSONObject().put("datum", d).put("aus", true))
            prefs(ctx).edit().putString("einmalig", keep.toString()).apply()
        }
        val r = einmaligAdd(ctx, o)
        // Vorab-Briefing gleich jetzt (nur heute und wenn es noch nicht los geht): worauf achten, was anziehen, Bahn/Rad
        if (d == today() && home != null && dest != null) hmOf(o.optString("los"))?.let { (h, m) ->
            val leave = todayAt(h, m)
            if (leave > System.currentTimeMillis()) Thread({
                try {
                    val pl = tripPlan(ctx, home, dest, leave, o.optString("ziel"), o.optString("mode"), o.optString("bahn_hin"))
                    val back = hmOf(o.optString("zuhause"))?.let { todayAt(it.first, it.second) } ?: 0L
                    val intro = (if (an.isNotBlank()) "Du willst um $an bei $label sein – dafür musst du um ${clock(pl.optLong("go", leave))} los."
                        else "Um ${clock(leave)} geht's los zu $label.") + " Ich sag dir rechtzeitig Bescheid."
                    val (t, fid) = rideBrief(ctx, "fahrt", "Plan: $label um ${an.ifBlank { o.optString("los") }}", intro, home, pl.optLong("go", leave), back, pl,
                        remindersFor(ctx, label), true, JSONObject().put("ziel", label).put("vorschau", true).put("sms_to", o.optString("wer")))
                    notify(ctx, 333, "Plan: $label", t, feed = fid)
                } catch (e: Exception) { Log.w(TAG, "vorab: $e") }
            }, "jarvis-vorab").start()
        }
        return if (an.isNotBlank()) "Okay: um $an bei $label – du musst um ${o.optString("los")} los. Ich schick dir gleich ein kurzes Briefing und sag rechtzeitig Bescheid." else r
    }

    /** Fahrt planen: Regen -> Bahn (erste Verbindung ab "leave"), sonst Rad. */
    /** Ticket-Satz und Kauf-Link (DB Navigator / bahn.de, dort mit PayPal zahlen) zu einer Bahn-Verbindung. */
    private fun ticketInfo(ctx: Context, b: Route.Trip, o: JSONObject): String {
        val art = prefs(ctx).getString("ticket_art", "erwachsen") ?: "erwachsen"
        if (art == "abo") { o.put("ticket", "Dein Abo gilt"); return " Dein Abo gilt." }
        if (b.ticket.isBlank()) return ""
        val price = if (b.price > 0) " für ${"%.2f".format(Locale.GERMANY, b.price)} €" else ""
        o.put("ticket", b.ticket.replace("EinzelTicket", "EinzelTicket").trim()).put("price", b.price)
        o.put("buy", "https://www.bahn.de/buchung/fahrplan/suche#sts=true&so=" + Uri.encode(b.stop) + "&zo=" + Uri.encode(b.destStop.ifBlank { o.optString("ziel_name") }) +
            "&kl=2&hd=" + Uri.encode(SimpleDateFormat("yyyy-MM-dd'T'HH:mm:00", de).format(Date(b.rideDep))) + "&hza=D")
        return " Ticket: ${b.ticket}$price – tipp in der Mitteilung auf „Ticket kaufen“."
    }

    private fun tripPlan(ctx: Context, from: Route.P, dest: Route.P, leave: Long, name: String, vehicle: String = "ebike", bahnPolicy: String = "regen"): JSONObject {
        val km = Route.distKm(from, dest)
        val rain = rainAt(from.lat, from.lon, leave)
        Route.ticketArt = prefs(ctx).getString("ticket_art", "erwachsen") ?: "erwachsen"
        val wantBahn = km >= 1.2 && (bahnPolicy == "immer" || (bahnPolicy != "nie" && rain))
        if (wantBahn) Route.bahnFrom(from, dest, leave)?.let { b ->
            val o = JSONObject().put("mode", "transit").put("go", b.dep).put("min", (b.arr - b.dep) / 60_000.0).put("km", km).put("rain", rain)
                .put("line", b.line).put("ride_dep", b.rideDep).put("stop", b.stop).put("arr", b.arr).put("ziel_name", name)
            val why = if (rain) "es soll regnen" else "so hast du's eingestellt"
            return o.put("text", "Heute fährst du Bahn, $why: geh um ${clock(b.dep)} los, ${b.line} um ${clock(b.rideDep)} ab ${b.stop}, an um ${clock(b.arr)}." + ticketInfo(ctx, b, o))
        }
        val walk = km < 1.2 || vehicle == "fuss"
        val bike = if (vehicle == "rad") "dem Fahrrad" else "dem E-Bike"
        val min = if (walk) Route.walkMinutes(from, dest)
            else (learned(ctx, name, "rad") ?: (Route.distKm(from, dest) * 1.3 / (if (vehicle == "rad") 16.0 else 22.0) * 60 + 3))
        val nLearn = list(trips(ctx)).count { near(it.optString("to"), name) && it.optString("mode") == "rad" }
        return JSONObject().put("mode", if (walk) "walking" else "bicycling").put("go", leave).put("min", min).put("km", km).put("rain", rain)
            .put("vehicle", if (walk) "fuss" else vehicle).put("arr", leave + (min * 60_000).toLong()).put("learned", nLearn)
            .put("text", (if (walk) "Zu Fuß" else if (rain) "Es soll regnen, aber ich finde keine Bahn – nimm $bike und Regensachen" else "Kein Regen, nimm $bike") +
                ", du bist gegen ${clock(leave + (min * 60_000).toLong())} da.")
    }

    /** Offene "denk an …"-Notizen für diesen Ort (werden erst bei der Ankunft gelöscht). */
    private fun remindersFor(ctx: Context, place: String): List<String> {
        val a = try { JSONArray(prefs(ctx).getString("ort_erinnerungen", "[]")) } catch (_: Exception) { return emptyList() }
        val p = Chats.norm(place)
        val errands = try { if (todayWege(ctx).any { near(it.label, place) || near(it.to, place) }) Remind.errands(ctx, today()).map { it.optString("text") } else emptyList() } catch (_: Exception) { emptyList() }
        return list(a).filter { o -> val w = Chats.norm(o.optString("ort")); w.isNotBlank() && (w == p || p.contains(w) || w.contains(p) && p.length >= 3) }
            .map { it.optString("text") } + errands
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
        for (f in todayWege(ctx)) {
            if (c.get(Calendar.DAY_OF_WEEK) != f.day) continue
            val leave = todayAt(f.h, f.m)
            val home = Route.home(ctx) ?: continue
            val dest = Route.place(ctx, f.to) ?: continue
            val id = "fest|${f.key}|${f.to}|${today()}"
            val back = if (f.backH >= 0) todayAt(f.backH, f.backM) else 0L
            val wer = f.wer.ifBlank { whoFor(ctx, f.label)?.second ?: whoFor(ctx, f.to)?.second ?: "" }
            // Plan ca. 30 Minuten vorher (Wetter, Bahn)
            if (now in leave - 35 * 60_000L..leave + 10 * 60_000L && !done(s, "$id|plan")) {
                mark(s, "$id|plan")
                s.put("fest_plan", tripPlan(ctx, home, dest, leave, f.to, f.mode, f.bahnHin).put("id", id))
            }
            val pl = s.optJSONObject("fest_plan")?.takeIf { it.optString("id") == id }
            if (pl != null && now in leave - 5 * 60_000L until leave + 10 * 60_000L && !done(s, "$id|brief")) {
                mark(s, "$id|brief"); s.put("last_ready", now)
                val go = pl.optLong("go", leave)
                val intro = if (pl.optString("mode") == "transit") "Zu ${f.label}:" else "Um ${clock(leave)} geht's los zu ${f.label}."
                val (t0, fid) = rideBrief(ctx, "fahrt", if (pl.optString("mode") == "transit") "Heute fährst du Bahn" else "Gleich los zu ${f.label}", intro,
                    home, go, back, pl, (remindersFor(ctx, f.label) + remindersFor(ctx, f.to)).distinct(), false,
                    JSONObject().put("ziel", f.label).put("sms_to", wer).put("home_at", back).put("fest", f.key == "fest"))
                val t = t0 + (if (wer.isNotBlank()) " Ich sag $wer Bescheid, kurz bevor du da bist." else "")
                notify(ctx, 332, "Gleich los zu ${f.label}", t, feed = fid); say(t)
            }
            if (pl != null && now in pl.optLong("go", leave)..pl.optLong("go", leave) + 30 * 60_000L && !done(s, "$id|los")) {   // still: Ziel für die Ankunfts-SMS
                mark(s, "$id|los")
                if (!s.has("ziel")) s.put("ziel", JSONObject().put("name", f.to).put("label", f.label).put("wer", wer).put("start", pl.optLong("go", leave))
                    .put("min", pl.optDouble("min", 20.0)).put("km", pl.optDouble("km", 5.0)))
            }
            // Rückweg: "zuhause 18:20" = da willst du zuhause ankommen. Jarvis rechnet rückwärts:
            // Ankunft − Fahrzeit (gelernter Durchschnitt) − Fertigmach-Zeit (gelernt, Start 5 Min.) = "Mach dich fertig"-Nachricht
            if (back > 0) {
                val from = dest
                val prepB = prepBack(s)
                if (now in back - 90 * 60_000L..back && !done(s, "$id|bplan")) {
                    mark(s, "$id|bplan")
                    val rain = rainAt(from.lat, from.lon, back - 30 * 60_000L)
                    Route.ticketArt = prefs(ctx).getString("ticket_art", "erwachsen") ?: "erwachsen"
                    val wantB = Route.distKm(from, home) >= 1.2 && (f.bahnZurueck == "immer" || (f.bahnZurueck != "nie" && rain))
                    val bahn = if (wantB) Route.bahnBy(from, home, back) else null   // so, dass du pünktlich zuhause bist
                    val ride = learnedRoute(ctx, f.to, "zuhause", "rad") ?: learnedRoute(ctx, f.label, "zuhause", "rad")
                        ?: (Route.distKm(from, home) * 1.3 / (if (f.mode == "rad") 16.0 else 22.0) * 60 + 3)
                    val go = bahn?.dep ?: (back - (ride * 60_000).toLong())
                    val tko = JSONObject()
                    val text = if (bahn != null) "Jetzt los, ${if (rain) "es soll regnen: " else ""}die ${bahn.line} um ${clock(bahn.rideDep)} ab ${bahn.stop} bringt dich um ${clock(bahn.arr)} heim." + ticketInfo(ctx, bahn, tko.put("ziel_name", "zuhause"))
                        else "Mit dem ${if (f.mode == "rad") "Fahrrad" else "E-Bike"} brauchst du etwa ${ride.toInt()} Minuten" + (if (rain) ", nimm Regensachen mit." else ".")
                    val fb = JSONObject().put("id", id).put("go", go).put("msg", go - prepB * 60_000L).put("text", text)
                        .put("ride", ride).put("mode", if (bahn != null) "transit" else "bicycling").put("rain", rain)
                    if (bahn != null) { fb.put("line", bahn.line).put("ride_dep", bahn.rideDep).put("stop", bahn.stop).put("arr", bahn.arr); for (k in listOf("ticket", "price", "buy")) if (tko.has(k)) fb.put(k, tko.get(k)) }
                    s.put("fest_back", fb)
                }
                val pb = s.optJSONObject("fest_back")?.takeIf { it.optString("id") == id } ?: continue
                val msgAt = pb.optLong("msg"); val go = pb.optLong("go")
                if (now in msgAt until go + 10 * 60_000L && !done(s, "$id|bmsg")) {
                    mark(s, "$id|bmsg"); s.put("back_msg", now)
                    val (t, fid) = rideBrief(ctx, "heimweg", "Mach dich fertig – Heimweg", "Mach dich fertig, um ${clock(go)} musst du los, dann bist du um ${clock(back)} zuhause.",
                        from, go, 0L, pb, remindersFor(ctx, f.label), false, JSONObject().put("ziel", "zuhause").put("home_at", back).put("from", f.label)
                            .put("home_addr", listOf(prefs(ctx).getString("address", "") ?: "", Lage.city(ctx)).filter { it.isNotBlank() }.joinToString(", ")))
                    notify(ctx, 334, "Mach dich fertig – Heimweg", t, feed = fid); say(t)
                }
                // Fertigmach-Zeit lernen: wie lange nach der Nachricht bist du wirklich bei Oma und Opa losgefahren?
                val lp = s.optJSONObject("left_place"); val bm = s.optLong("back_msg")
                if (lp != null && bm > 0 && (near(lp.optString("name"), f.to) || near(lp.optString("name"), f.label)) && lp.optLong("t") - bm in 0..60 * 60_000L && !done(s, "$id|blearn")) {
                    mark(s, "$id|blearn")
                    val a = s.optJSONArray("prep_back") ?: JSONArray()
                    a.put(((lp.optLong("t") - bm) / 60_000L).toInt()); while (a.length() > 8) a.remove(0)
                    s.put("prep_back", a)
                }
            }
        }
    }

    /** Wetter zu einer Stunde (für die Mitteilungsseite): temp, feel, rain_mm, rain_pct, wind, gust, dark, code. */
    fun wxAt(lat: Double, lon: Double, t: Long): JSONObject? = try {
        val url = "https://api.open-meteo.com/v1/forecast?latitude=$lat&longitude=$lon" +
            "&hourly=temperature_2m,apparent_temperature,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,is_day,weather_code" +
            "&timezone=auto&forecast_days=3"
        val h = JSONObject(http.newCall(Request.Builder().url(url).build()).execute().use { it.body?.string() ?: "{}" }).getJSONObject("hourly")
        val key = SimpleDateFormat("yyyy-MM-dd'T'HH:00", de).format(Date(t))
        val i = (0 until h.getJSONArray("time").length()).first { h.getJSONArray("time").getString(it) == key }
        JSONObject().put("t", t).put("temp", Math.round(h.getJSONArray("temperature_2m").optDouble(i)))
            .put("feel", Math.round(h.getJSONArray("apparent_temperature").optDouble(i)))
            .put("rain_mm", h.getJSONArray("precipitation").optDouble(i)).put("rain_pct", h.getJSONArray("precipitation_probability").optInt(i))
            .put("wind", Math.round(h.getJSONArray("wind_speed_10m").optDouble(i))).put("gust", Math.round(h.getJSONArray("wind_gusts_10m").optDouble(i)))
            .put("dark", h.getJSONArray("is_day").optInt(i) != 1).put("code", h.getJSONArray("weather_code").optInt(i))
    } catch (_: Exception) { null }

    private fun wxText(w: JSONObject?): String = if (w == null) "" else
        "${w.optInt("temp")}° (gefühlt ${w.optInt("feel")}°), Regen ${w.optInt("rain_pct")} % / ${w.optDouble("rain_mm")} mm, Wind ${w.optInt("wind")} km/h, " +
            "Böen ${w.optInt("gust")} km/h, ${if (w.optBoolean("dark")) "dunkel" else "hell"}, Wettercode ${w.optInt("code")}"

    /** Kleiderschrank-Auswahl -> Outfit-Karte (Jacke, oben, Hose, Extras) */
    private fun outfitOf(p: JSONObject) = JSONObject().put("jacke", p.optString("jacke")).put("oben", p.optString("oben"))
        .put("hose", p.optString("hose")).put("extras", p.optJSONArray("extras") ?: JSONArray())

    /** Kleiderschrank für einen ganzen Tag (Morgen-/Abend-Briefing): kälteste/wärmste gefühlte Temperatur von 7 bis 19 Uhr. */
    private fun dayPick(ctx: Context, wx: JSONObject?): JSONObject? = try {
        val h = wx?.optJSONArray("hours") ?: throw Exception()
        val f = (0 until h.length()).map { h.getJSONObject(it).optDouble("feel") }.filter { !it.isNaN() }
        if (f.isEmpty()) null else Wardrobe.pick(ctx, f.min(), f.max(), (wx.optInt("rain_pct") >= 50), true, Wardrobe.get(ctx).optBoolean("tag_drinnen", true))
    } catch (_: Exception) { null }

    /** Vorschau für die Kleiderschrank-Seite: was heute (bzw. ab 18 Uhr: morgen) dran ist. */
    fun wardrobeToday(ctx: Context): JSONObject {
        val tomorrow = Calendar.getInstance().get(Calendar.HOUR_OF_DAY) >= 18
        val wx = dayWx(ctx, if (tomorrow) 1 else 0)
        val p = dayPick(ctx, wx) ?: return JSONObject().put("error", "Kein Wetter (Wohnort in den Einstellungen?)")
        return p.put("tag", if (tomorrow) "Morgen" else "Heute").put("min", wx?.optInt("min")).put("max", wx?.optInt("max"))
    }

    /** KI liefert gesprochenen Text + Listen als JSON. */
    private fun aiJson(ctx: Context, sys: String, data: String, maxTok: Int = 600): JSONObject? {
        val key = prefs(ctx).getString("groq_key", "") ?: ""
        if (key.isBlank()) return null
        return try {
            val raw = Groq.chat(key, JSONArray().put(JSONObject().put("role", "system").put("content", sys))
                .put(JSONObject().put("role", "user").put("content", data)), maxTok, json = true)
            JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw)?.value ?: raw)
        } catch (e: Exception) { Log.w(TAG, "ki: $e"); null }
    }

    private fun strs(a: JSONArray?) = JSONArray().apply { if (a != null) for (i in 0 until a.length()) a.optString(i).takeIf { it.isNotBlank() && it != "null" }?.let { put(it.replace(Regex("[*#`]"), "")) } }

    /**
     * Fahrt-Briefing: gesprochener Text + Mitteilung (Seite mit Zeiten, Verkehrsmittel, Wetter hin/zurück, Anziehen, Pass auf, Denk an).
     * Gibt (Text, Mitteilungs-ID) zurück.
     */
    private fun rideBrief(ctx: Context, kind: String, title: String, intro: String, from: Route.P, leave: Long, back: Long, pl: JSONObject,
                          remind: List<String> = emptyList(), short: Boolean = false, extra: JSONObject = JSONObject()): Pair<String, String> {
        val w1 = wxAt(from.lat, from.lon, leave)
        val w2 = if (back > 0) wxAt(from.lat, from.lon, back) else null
        // Kleiderschrank: nach der kältesten Temperatur der ganzen Strecke, Fahrtwind, drinnen am Ziel
        val temps = listOfNotNull(w1?.optDouble("feel"), w2?.optDouble("feel")).filter { !it.isNaN() }
        val bike = pl.optString("mode") != "transit" && pl.optString("vehicle") != "fuss"
        val wet = pl.optBoolean("rain") || listOfNotNull(w1, w2).any { it.optDouble("rain_mm", 0.0) > 0.1 }
        val pick = if (temps.isNotEmpty()) try { Wardrobe.pick(ctx, temps.min(), temps.max(), wet, bike, Wardrobe.isIndoor(ctx, extra.optString("ziel"))) } catch (_: Exception) { null } else null
        if (pick != null && kind == "fahrt" && !extra.optBoolean("test") && !extra.optBoolean("vorschau")) Wardrobe.rememberTrip(ctx, pick, extra.optString("ziel"))
        val data = "Ansage: $intro\nVerkehrsmittel: ${pl.optString("text")}\nWetter bei der Abfahrt (${clock(leave)}): ${wxText(w1)}" +
            (if (w2 != null) "\nWetter auf dem Rückweg (${clock(back)}): ${wxText(w2)}" else "") +
            "\n" + (pick?.let { Wardrobe.line(it) } ?: ("Seine Anzieh-Regeln:\n" + ((prefs(ctx).getString("anzieh", "") ?: "").ifBlank { ANZIEH_DEFAULT }))) +
            (if (remind.isNotEmpty()) "\nEr wollte daran erinnert werden: ${remind.joinToString("; ")}" else "")
        val sys = "Du bist Jarvis und gibst Skyler ein Briefing für seine Fahrt. Antworte NUR mit JSON: " +
            "{\"text\": \"gesprochenes Briefing, " + (if (short) "höchstens 2 kurze Sätze" else "3 bis 5 kurze Sätze") +
            ", ohne Listen und Sonderzeichen: Ansage, Verkehrsmittel (Bahn wegen Regen oder Rad), wie kalt, was anziehen, worauf achten, ggf. 'Denk an …', am Ende 'Gute Fahrt'\", " +
            "\"outfit\": {\"jacke\": \"genau welche Jacke: Winterjacke, Softshelljacke, dünne Jacke, Regenjacke oder keine\", \"oben\": \"T-Shirt, Pulli oder T-Shirt und Pulli\", \"hose\": \"dicke lange Hose, lange Hose, dünne lange Hose oder kurze Hose\", \"extras\": [\"Mütze\", \"Handschuhe\", \"Schal\", \"Regenhose\" – nur was nötig ist]}, \"anziehen\": [\"dieselben Teile als kurze Liste\"], " +
            "\"achtung\": [\"kurze Hinweise: Glätte bei 2 Grad und weniger, starker Wind/Böen, nasse Straße, Dunkelheit: Licht an – nur wenn zutreffend\"]}. " +
            "Erfinde nichts, was nicht in den Daten steht."
        val ai = if (w1 != null) aiJson(ctx, sys, data, 500) else null
        val denk = if (remind.isNotEmpty()) " Denk an: ${remind.joinToString(", ")}." else ""
        val text = ai?.optString("text")?.replace(Regex("[*#`]"), "")?.trim()?.ifBlank { null } ?: "$intro ${pl.optString("text")}$denk Gute Fahrt!"
        val d = JSONObject().put("intro", intro).put("plan", pl).put("leave", leave).put("back", back)
            .put("wx_hin", w1 ?: JSONObject.NULL).put("wx_back", w2 ?: JSONObject.NULL)
            .put("anziehen", pick?.optJSONArray("anziehen") ?: strs(ai?.optJSONArray("anziehen"))).put("achtung", strs(ai?.optJSONArray("achtung")))
            .put("outfit", pick?.let { outfitOf(it) } ?: ai?.optJSONObject("outfit") ?: JSONObject.NULL).put("denk", JSONArray(remind))
            .put("warum", pick?.optString("warum") ?: "")
        for (k in extra.keys()) d.put(k, extra.get(k))
        val sub = listOfNotNull(if (pl.optString("mode") == "transit") "Bahn" else if (pl.optString("vehicle") == "rad") "Fahrrad" else if (pl.optString("vehicle") == "fuss") "zu Fuß" else "E-Bike",
            w1?.let { "${it.optInt("temp")}°" }, (pick?.optJSONArray("anziehen") ?: strs(ai?.optJSONArray("anziehen"))).let { a -> (0 until minOf(3, a.length())).joinToString(", ") { a.optString(it) }.ifBlank { null } }).joinToString(" · ")
        val id = Feed.add(ctx, kind, title, sub, text, d)
        return text to id
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

    /** Am PC anbieten (nur wenn du dran sitzt): "… ist da. Soll ich ihn öffnen?" */
    private fun pcOffer(ctx: Context, title: String, question: String, text: String) {
        try {
            if (Link.paired(ctx)) Link.command(ctx, JSONObject().put("type", "offer").put("need_active", true).put("title", title)
                .put("question", question).put("text", text), 15_000)
        } catch (_: Exception) {}
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

    /** Aufsteh-Zeit heute (einmalig > Plan > zuletzt gestellt), sonst null. */
    private fun upTime(ctx: Context): Long? = try {
        val d0 = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }.timeInMillis
        Wecker.upToday(ctx) ?: Wecker.upFor(ctx, d0)
    } catch (_: Exception) { null }

    /** Ohne Aufsteh-Zeit: erstes Entsperren nach dem Wecker -> Morgen-Briefing als Benachrichtigung. (Mit Aufsteh-Zeit macht das tick.) */
    fun onUnlock(ctx: Context, say: (String) -> Unit) {
        if (!on(ctx, "brief_morgen")) return
        if (upTime(ctx) != null) return
        val s = state(ctx)
        alarms(ctx, s)
        val now = System.currentTimeMillis()
        val key = "morgen|${today()}"
        val up: Long? = null
        val last = up ?: s.optLong("alarm_last")
        if (last <= 0 || now - last !in -2 * 60_000L..3 * 3_600_000L || done(s, key)) return
        mark(s, key); save(ctx, s)
        Thread({
            val (t, fid) = dayBrief(ctx, 0) ?: return@Thread
            notify(ctx, 340, "Guten Morgen – dein Tag", t, feed = fid)
        }, "jarvis-morgen").start()
    }

    private fun hm(v: String, def: Int): Pair<Int, Int> = Regex("(\\d{1,2})[:.](\\d{2})").find(v)?.let { it.groupValues[1].toInt() to it.groupValues[2].toInt() }
        ?: (def to 0)

    private fun todayAt(h: Int, m: Int) = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, h); set(Calendar.MINUTE, m); set(Calendar.SECOND, 0) }.timeInMillis

    private fun evening(ctx: Context, s: JSONObject, say: (String) -> Unit) {
        if (!on(ctx, "brief_abend")) return
        val (h, m) = hm(prefs(ctx).getString("brief_abend_zeit", "20:00") ?: "20:00", 20)
        val t0 = todayAt(h, m); val now = System.currentTimeMillis()
        val key = "abend|${today()}"
        if (now < t0 || now > t0 + 2 * 3_600_000L || done(s, key)) return
        mark(s, key)
        Thread({
            val (t, fid) = eveningBrief(ctx) ?: return@Thread
            notify(ctx, 341, "Dein Tagesabschluss", t, feed = fid)
            pcOffer(ctx, "Tagesabschluss", "Dein Tagesabschluss ist da. Soll ich ihn öffnen?", t)
        }, "jarvis-abend").start()
    }

    /** Wetter eines Tages als Daten: min, max, Regen, und einige Stunden. */
    private fun dayWx(ctx: Context, dayOffset: Int): JSONObject? = try {
        val home = Route.home(ctx) ?: throw Exception("keine Adresse")
        val url = "https://api.open-meteo.com/v1/forecast?latitude=${home.lat}&longitude=${home.lon}" +
            "&hourly=temperature_2m,apparent_temperature,precipitation_probability,precipitation,wind_speed_10m,weather_code,is_day" +
            "&daily=temperature_2m_min,temperature_2m_max,precipitation_sum,precipitation_probability_max,sunset&timezone=auto&forecast_days=3"
        val js = JSONObject(http.newCall(Request.Builder().url(url).build()).execute().use { it.body?.string() ?: "{}" })
        val h = js.getJSONObject("hourly"); val d = js.getJSONObject("daily")
        val day = SimpleDateFormat("yyyy-MM-dd", de).format(Date(System.currentTimeMillis() + dayOffset * 86_400_000L))
        val di = (0 until d.getJSONArray("time").length()).firstOrNull { d.getJSONArray("time").getString(it) == day } ?: 0
        val hours = JSONArray(); val t = h.getJSONArray("time")
        for (hr in listOf(7, 10, 13, 16, 19)) {
            val i = (0 until t.length()).firstOrNull { t.getString(it) == "${day}T%02d:00".format(hr) } ?: continue
            hours.put(JSONObject().put("h", hr).put("temp", Math.round(h.getJSONArray("temperature_2m").optDouble(i)))
                .put("feel", Math.round(h.getJSONArray("apparent_temperature").optDouble(i))).put("rain_pct", h.getJSONArray("precipitation_probability").optInt(i))
                .put("rain_mm", h.getJSONArray("precipitation").optDouble(i)).put("wind", Math.round(h.getJSONArray("wind_speed_10m").optDouble(i)))
                .put("code", h.getJSONArray("weather_code").optInt(i)).put("dark", h.getJSONArray("is_day").optInt(i) != 1))
        }
        JSONObject().put("min", Math.round(d.getJSONArray("temperature_2m_min").optDouble(di))).put("max", Math.round(d.getJSONArray("temperature_2m_max").optDouble(di)))
            .put("rain_sum", d.getJSONArray("precipitation_sum").optDouble(di)).put("rain_pct", d.getJSONArray("precipitation_probability_max").optInt(di))
            .put("sunset", d.getJSONArray("sunset").optString(di).substringAfter("T")).put("hours", hours)
    } catch (e: Exception) { Log.w(TAG, "wetter: $e"); null }

    /** Tages-Update: day 0 = heute (Morgen-Briefing), 1 = morgen (Abend-Briefing). Gibt (Text, Mitteilungs-ID) zurück. */
    fun dayBrief(ctx: Context, day: Int): Pair<String, String>? {
        val p = prefs(ctx)
        val dayStart = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, day); set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0) }.timeInMillis
        val evs = Cal.events(ctx, maxOf(dayStart, if (day == 0) System.currentTimeMillis() - 3_600_000L else 0), dayStart + 86_400_000L)
        val want = { k: String -> p.getBoolean(k, true) }
        val wx = dayWx(ctx, day)
        val wecker = if (day == 1) (ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager).nextAlarmClock?.triggerTime?.takeIf { it - dayStart in 0..86_400_000L } else null
        val wege = if (day == 0) todayWege(ctx).map { "${it.label} um %d:%02d".format(it.h, it.m) } else emptyList()
        val parts = mutableListOf<String>()
        if (wx != null) parts.add("Wetter Leonberg: $wx")
        val pick = dayPick(ctx, wx)
        parts.add(pick?.let { Wardrobe.line(it) } ?: ("Seine Anzieh-Regeln:\n" + (p.getString("anzieh", "") ?: "").ifBlank { ANZIEH_DEFAULT }))
        parts.add("Termine:\n" + (Cal.describe(evs).ifBlank { "keine" }))
        if (wege.isNotEmpty()) parts.add("Feste Wege: ${wege.joinToString()}")
        parts.add("Was du über ihn weißt:\n" + Memory.facts(ctx).takeLast(40).joinToString("\n") { "- $it" })
        if (wecker != null) parts.add("Sein Wecker morgen: ${clock(wecker)}")
        val schlaf = if (day == 0) try { Sleep.night(ctx, 0) } catch (_: Exception) { null } else null
        if (schlaf != null) parts.add("Sein Schlaf letzte Nacht: ${Sleep.text(schlaf)}")
        val topics = listOf("bi_wetter" to "Wetter (vor allem für die Radfahrt)", "bi_anzieh" to "was er anziehen soll, genau nach seinen Regeln",
            "bi_termine" to "Termine", "bi_mitnehmen" to "was er mitnehmen oder vorbereiten sollte (nur wenn es aus den Terminen folgt)")
            .filter { want(it.first) }.joinToString(", ") { it.second }
        val sys = "Du bist Jarvis und gibst Skyler sein ${if (day == 0) "Tages-Update für heute" else "Update für morgen"}. Antworte NUR mit JSON: " +
            "{\"text\": \"gesprochen, locker, ohne Listen und Sonderzeichen, 4 bis 6 kurze Sätze. Inhalt: $topics" +
            (if (wecker != null) ", zum Schluss wann sein Wecker klingelt" else "") +
            (if (schlaf != null) ", und ein halber Satz zum Schlaf nur wenn er unter 7 Stunden war (dann locker, nicht belehrend)" else "") + ". Beginne mit " + (if (day == 0) "'Guten Morgen'" else "'Kurz zu morgen'") + "\", " +
            "\"outfit\": {\"jacke\": \"genau welche Jacke: Winterjacke, Softshelljacke, dünne Jacke, Regenjacke oder keine\", \"oben\": \"T-Shirt, Pulli oder T-Shirt und Pulli\", \"hose\": \"dicke lange Hose, lange Hose, dünne lange Hose oder kurze Hose\", \"extras\": [\"Mütze\", \"Handschuhe\", \"Schal\", \"Regenhose\" – nur was nötig ist]}, \"anziehen\": [\"dieselben Teile als kurze Liste\"], \"achtung\": [\"kurze Hinweise fürs Rad: Glätte, Wind, Regen, früh dunkel – nur wenn zutreffend\"], " +
            "\"mitnehmen\": [\"was mitnehmen/vorbereiten, nur wenn es aus den Terminen folgt\"]}. Keine Bahn-Verbindungen. Erfinde nichts."
        val ai = aiJson(ctx, sys, parts.joinToString("\n\n"), 700) ?: return null
        val text = ai.optString("text").replace(Regex("[*#`]"), "").trim().ifBlank { return null }
        val termine = JSONArray()
        for (e in evs.distinctBy { it.id to it.begin }.take(8)) termine.put(JSONObject().put("zeit",
            if (e.allDay) (if (e.end - e.begin > 86_400_000L) Cal.whenText(e, "EE d.M.") else "ganztägig") else SimpleDateFormat("H:mm", de).format(Date(e.begin)))
            .put("titel", e.title).put("ort", e.place))
        for (f in if (day == 0) todayWege(ctx) else emptyList()) termine.put(JSONObject().put("zeit", "%d:%02d".format(f.h, f.m)).put("titel", "Los zu ${f.label}").put("ort", ""))
        val d = JSONObject().put("day", day).put("datum", SimpleDateFormat("EEEE, d. MMMM", de).format(Date(dayStart)))
            .put("wx", wx ?: JSONObject.NULL).put("anziehen", pick?.optJSONArray("anziehen") ?: strs(ai.optJSONArray("anziehen"))).put("achtung", strs(ai.optJSONArray("achtung")))
            .put("outfit", pick?.let { outfitOf(it) } ?: ai.optJSONObject("outfit") ?: JSONObject.NULL).put("warum", pick?.optString("warum") ?: "")
            .put("mitnehmen", strs(ai.optJSONArray("mitnehmen"))).put("termine", termine).put("wecker", wecker ?: 0L)
            .put("schlaf", schlaf ?: JSONObject.NULL)
        val sub = listOfNotNull(wx?.let { "${it.optInt("min")}–${it.optInt("max")}°" + (if (it.optInt("rain_pct") >= 50) ", Regen" else ", trocken") },
            strs(ai.optJSONArray("anziehen")).optString(0).ifBlank { null }, "${termine.length()} Termin" + (if (termine.length() == 1) "" else "e")).joinToString(" · ")
        val id = Feed.add(ctx, if (day == 0) "morgen" else "abend", if (day == 0) "Guten Morgen" else "Kurz zu morgen", sub, text, d)
        return text to id
    }

    /** Tages-Update auf Zuruf ("gib mir das Briefing", "was ist morgen?") – landet auch in den Mitteilungen. */
    fun briefingNow(ctx: Context, tomorrow: Boolean): String = dayBrief(ctx, if (tomorrow) 1 else 0)?.first ?: "Fürs Briefing brauche ich den Groq-Schlüssel."

    /**
     * Abend: Rückblick auf HEUTE (was los war, Fahrten, Kalorien/Aktivität, Schlaf letzte Nacht) + für MORGEN nur das Nötige:
     * wann du aufstehst (und die Wecker) und was du anziehst. Keine Termine von morgen – die kommen morgens.
     */
    fun eveningBrief(ctx: Context): Pair<String, String>? {
        val p = prefs(ctx)
        val now = System.currentTimeMillis()
        val d0 = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }.timeInMillis
        val d1 = d0 + 86_400_000L
        val heute = Cal.events(ctx, d0, now).distinctBy { it.id to it.begin }
        val fahrten = list(trips(ctx)).filter { it.optLong("end") >= d0 }.map { it.optString("to") }.filter { it != "zuhause" }
        val fit = if (on(ctx, "bilanz")) try { Health.day(ctx, 0) } catch (_: Exception) { null } else null
        val schlaf = try { Sleep.night(ctx, 0) } catch (_: Exception) { null }
        val up = try { Wecker.upFor(ctx, d1) } catch (_: Exception) { null }
        val am = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val firstAlarm = am.nextAlarmClock?.triggerTime?.takeIf { it in d1 until d1 + 86_400_000L }
        val wecker = if (up != null) try { Wecker.timesFor(ctx, SimpleDateFormat("H", de).format(Date(up)).toInt() to SimpleDateFormat("m", de).format(Date(up)).toInt()) } catch (_: Exception) { emptyList() } else emptyList()
        val wx = dayWx(ctx, 1)
        val parts = mutableListOf<String>()
        parts.add("HEUTE – Termine:\n" + Cal.describe(heute).ifBlank { "keine" })
        if (fahrten.isNotEmpty()) parts.add("HEUTE – Fahrten zu: ${fahrten.joinToString()}")
        if (fit != null) parts.add("HEUTE – Aktivität: ${Health.text(fit)}")
        if (schlaf != null) parts.add("Schlaf letzte Nacht: ${Sleep.text(schlaf)}")
        if (up != null) parts.add("Für 8 Stunden Schlaf müsste er um ${SimpleDateFormat("H:mm", de).format(Date(up - 8 * 3_600_000L))} Uhr schlafen.")
        parts.add("MORGEN – " + (if (up != null) "Aufstehen um ${clock(up)}" + (if (wecker.isNotEmpty()) ", Wecker ${wecker.joinToString(", ")}" else "")
            else if (firstAlarm != null) "erster Wecker ${clock(firstAlarm)}" else "kein Wecker, er kann ausschlafen"))
        if (wx != null) parts.add("MORGEN – Wetter Leonberg: $wx")
        val epick = dayPick(ctx, wx)
        parts.add(epick?.let { Wardrobe.line(it) } ?: ("Seine Anzieh-Regeln:\n" + (p.getString("anzieh", "") ?: "").ifBlank { ANZIEH_DEFAULT }))
        val sys = "Du bist Jarvis und gibst Skyler seinen Tagesabschluss am Abend. Antworte NUR mit JSON: " +
            "{\"text\": \"gesprochen, locker, ohne Listen und Sonderzeichen, 3 bis 5 kurze Sätze: kurzer Rückblick auf heute (was los war" +
            (if (fit != null) ", wie viele Kalorien er verbraucht hat und ob er aktiv war, Defizit nur wenn gegessene Kalorien in den Daten stehen" else "") +
            "), dann für morgen NUR: wann er aufsteht (mit dem Tipp, wann er für 8 Stunden Schlaf ins Bett sollte) und was er anziehen soll. KEINE Termine von morgen. Beginne mit 'Dein Tagesabschluss'\", " +
            "\"heute\": [\"2 bis 4 kurze Stichpunkte, was heute los war\"], " +
            "\"outfit\": {\"jacke\": \"genau welche Jacke: Winterjacke, Softshelljacke, dünne Jacke, Regenjacke oder keine\", \"oben\": \"T-Shirt, Pulli oder T-Shirt und Pulli\", \"hose\": \"dicke lange Hose, lange Hose, dünne lange Hose oder kurze Hose\", \"extras\": [\"Mütze\", \"Handschuhe\", \"Schal\", \"Regenhose\" – nur was nötig ist]}, \"anziehen\": [\"dieselben Teile als kurze Liste\"]}. Erfinde nichts."
        val ai = aiJson(ctx, sys, parts.joinToString("\n\n"), 600)
        val text = ai?.optString("text")?.replace(Regex("[*#`]"), "")?.trim()?.ifBlank { null }
            ?: (listOfNotNull(fit?.let { "Heute: " + Health.text(it) }, up?.let { "Morgen stehst du um ${clock(it)} auf." }).joinToString(" ").ifBlank { return null })
        val d = JSONObject().put("datum", SimpleDateFormat("EEEE, d. MMMM", de).format(Date(d0)))
            .put("heute", strs(ai?.optJSONArray("heute"))).put("fit", fit ?: JSONObject.NULL).put("schlaf", schlaf ?: JSONObject.NULL)
            .put("aufstehen", up ?: 0L).put("bett", if (up != null) up - 8 * 3_600_000L else 0L).put("wecker", JSONArray(wecker)).put("erster_wecker", firstAlarm ?: 0L)
            .put("wx", wx ?: JSONObject.NULL).put("outfit", epick?.let { outfitOf(it) } ?: ai?.optJSONObject("outfit") ?: JSONObject.NULL)
            .put("anziehen", epick?.optJSONArray("anziehen") ?: strs(ai?.optJSONArray("anziehen"))).put("warum", epick?.optString("warum") ?: "")
        val sub = listOfNotNull(up?.let { "Aufstehen ${SimpleDateFormat("H:mm", de).format(Date(it))}" },
            strs(ai?.optJSONArray("anziehen")).optString(0).ifBlank { null }, fit?.takeIf { it.has("kcal") }?.let { "%,d kcal".format(de, it.optLong("kcal")) }).joinToString(" · ")
        return text to Feed.add(ctx, "abend", "Dein Tagesabschluss", sub, text, d)
    }

    // --- Wochenrückblick -------------------------------------------------------------------------------------
    private fun weekly(ctx: Context, s: JSONObject) {
        if (!on(ctx, "rueckblick")) return
        val c = Calendar.getInstance()
        if (c.get(Calendar.DAY_OF_WEEK) != Calendar.SUNDAY) return
        val (h, m) = hm(prefs(ctx).getString("rueckblick_zeit", "20:30") ?: "20:30", 20)
        val t0 = todayAt(h, m); val now = System.currentTimeMillis()
        val key = "woche|${today()}"
        if (now < t0 || now > t0 + 4 * 3_600_000L || done(s, key)) return
        mark(s, key)
        Thread({
            val (t, fid) = weekBack(ctx) ?: return@Thread
            try { weekAhead(ctx) } catch (_: Exception) {}
            notify(ctx, 350, "Dein Wochenrückblick", t, feed = fid)
            pcOffer(ctx, "Wochenrückblick", "Dein Wochenrückblick ist da. Soll ich ihn öffnen?", t)
        }, "jarvis-woche").start()
    }

    fun weekText(ctx: Context): String? = weekBack(ctx)?.first
    fun weekBrief(ctx: Context): Pair<String, String>? = weekBack(ctx)

    /** Wochenrückblick: genau die letzten 7 Tage – Besuche, Rad-Kilometer, Musik, was los war. */
    fun weekBack(ctx: Context): Pair<String, String>? {
        val now = System.currentTimeMillis()
        val since = now - 7 * 86_400_000L
        val week = list(trips(ctx)).filter { it.optLong("end") >= since }
        val visits = week.groupingBy { it.optString("to") }.eachCount().filterKeys { it != "zuhause" }
        val radKm = week.filter { it.optString("mode") == "rad" }.sumOf { it.optDouble("km") }
        val music = Interests.musicMinutes(ctx, since)
        val past = Cal.events(ctx, since, now).distinctBy { it.id to it.begin }
        val fit = try { Health.week(ctx) } catch (_: Exception) { JSONArray() }
        val nights = try { Sleep.week(ctx) } catch (_: Exception) { JSONArray() }
        val fl = (0 until fit.length()).map { fit.getJSONObject(it) }
        val nl = (0 until nights.length()).map { nights.getJSONObject(it) }
        val kcalAvg = fl.filter { it.has("kcal") }.map { it.optLong("kcal") }.average().let { if (it.isNaN()) 0L else Math.round(it) }
        val steps = fl.sumOf { it.optLong("schritte") }
        val sleepAvg = nl.map { it.optLong("min") }.average().let { if (it.isNaN()) 0L else Math.round(it) }
        val fitText = if (fl.isEmpty()) "" else "\nAktivität pro Tag (Samsung Health): " + fl.joinToString("; ") { "${it.optString("tag")} ${it.optLong("kcal")} kcal, ${it.optLong("schritte")} Schritte" +
            (if (it.optLong("sport_min") > 0) ", ${it.optLong("sport_min")} Min. Sport" else "") + (if (it.has("defizit")) ", Defizit ${it.optLong("defizit")}" else "") } +
            "\nDurchschnitt verbraucht: $kcalAvg kcal am Tag, Schritte gesamt: $steps"
        val sleepText = if (nl.isEmpty()) "" else "\nSchlaf pro Nacht: " + nl.joinToString("; ") { "${it.optString("tag")} ${Sleep.dur(it.optLong("min"))} (${SimpleDateFormat("H:mm", de).format(Date(it.optLong("start")))}–${SimpleDateFormat("H:mm", de).format(Date(it.optLong("end")))})" } +
            "\nDurchschnitt Schlaf: ${Sleep.dur(sleepAvg)}"
        val data = "Besuche (Fahrten zu gespeicherten Orten): ${visits.entries.joinToString { "${it.key}: ${it.value}x" }.ifBlank { "keine erfasst" }}\n" +
            "Rad-Kilometer: ${"%.1f".format(radKm)}\nFahrten: ${week.size}\nMusik gehört (Handy): etwa ${music / 60} Stunden ${music % 60} Minuten\n" +
            "Termine der letzten 7 Tage:\n${Cal.describe(past).ifBlank { "keine" }}" + fitText + sleepText
        val sys = "Du bist Jarvis und machst Skylers Wochenrückblick über die letzten 7 Tage. Antworte NUR mit JSON: {\"text\": \"gesprochen, locker, 4 bis 6 Sätze, " +
            "ohne Listen: wie oft er bei Oma und Opa war, wie viele Kilometer er Rad gefahren ist, wie lange er Musik gehört hat (keine Liedliste), was sonst los war" +
            (if (fitText.isNotEmpty()) ", wie aktiv er war (Kalorien am Tag, Schritte, aktivster Tag)" else "") + (if (sleepText.isNotEmpty()) ", wie er geschlafen hat (Schnitt, späteste Nacht)" else "") +
            (if (fitText.isNotEmpty() || sleepText.isNotEmpty()) ", dazu ein kurzer motivierender Tipp, nicht belehrend" else "") + "\"}. Erfinde nichts."
        val ai = aiJson(ctx, sys, data, 500) ?: return null
        val text = ai.optString("text").replace(Regex("[*#`]"), "").trim().ifBlank { return null }
        val termine = JSONArray()
        for (e in past.take(14)) termine.put(JSONObject().put("zeit", Cal.whenText(e, "EE d.M.")).put("titel", e.title).put("ort", e.place))
        val besuche = JSONArray(); for ((k, v) in visits) besuche.put(JSONObject().put("ort", k).put("n", v))
        val d = JSONObject().put("richtung", "zurueck").put("besuche", besuche).put("rad_km", Math.round(radKm * 10) / 10.0).put("fahrten", week.size)
            .put("musik_min", music).put("termine", termine).put("fit", fit).put("schlaf", nights).put("kcal_avg", kcalAvg).put("schritte", steps).put("schlaf_avg", sleepAvg)
            .put("von", SimpleDateFormat("EE d.M.", de).format(Date(since))).put("bis", SimpleDateFormat("EE d.M.", de).format(Date(now)))
        val sub = "${visits.values.sum()} Besuche · ${"%.0f".format(radKm)} km Rad · ${music / 60} h Musik"
        return text to Feed.add(ctx, "woche", "Dein Wochenrückblick", sub, text, d)
    }

    // --- Tagesbilanz (Samsung Health + Schlaf) -----------------------------------------------------------------
    private fun bilanz(ctx: Context, s: JSONObject, say: (String) -> Unit) {
        if (!on(ctx, "bilanz") || on(ctx, "brief_abend")) return   // steckt im Tagesabschluss
        val (h, m) = hm(prefs(ctx).getString("bilanz_zeit", "22:00") ?: "22:00", 22)
        val t0 = todayAt(h, m); val now = System.currentTimeMillis()
        val key = "bilanz|${today()}"
        if (now < t0 || now > t0 + 2 * 3_600_000L || done(s, key)) return
        mark(s, key)
        Thread({
            val (t, fid) = dayHealth(ctx) ?: return@Thread
            notify(ctx, 342, "Deine Tagesbilanz", t, feed = fid)
            if (!pcSay(ctx, t) && !quiet(ctx)) say(t)
        }, "jarvis-bilanz").start()
    }

    /** Tagesbilanz: verbraucht, aktiv, Schritte, (Defizit), Schlaf letzte Nacht, Vergleich mit der Woche. (Text, Mitteilungs-ID) */
    fun dayHealth(ctx: Context): Pair<String, String>? {
        val h = try { Health.day(ctx, 0) } catch (_: Exception) { null }
        val sl = try { Sleep.night(ctx, 0) } catch (_: Exception) { null }
        if (h == null && sl == null) return null
        val wk = try { Health.week(ctx) } catch (_: Exception) { JSONArray() }
        val prev = (0 until wk.length()).map { wk.getJSONObject(it) }.dropLast(1)
        val avgK = prev.filter { it.has("kcal") }.map { it.optLong("kcal") }.average().let { if (it.isNaN()) 0L else Math.round(it) }
        val avgS = prev.filter { it.has("schritte") }.map { it.optLong("schritte") }.average().let { if (it.isNaN()) 0L else Math.round(it) }
        val data = "Heute: ${Health.text(h)}\nSchnitt der letzten Tage: $avgK kcal, $avgS Schritte\nSchlaf letzte Nacht: ${Sleep.text(sl)}"
        val sys = "Du bist Jarvis und gibst Skyler am Abend seine Tagesbilanz. Antworte NUR mit JSON: {\"text\": \"gesprochen, locker, 2 bis 4 kurze Sätze, ohne Listen: " +
            "wie viele Kalorien er heute verbraucht hat, ob er im Defizit war (NUR wenn gegessene Kalorien in den Daten stehen), wie aktiv er war im Vergleich zu seinem Schnitt, " +
            "kurz der Schlaf letzte Nacht; zum Schluss ein kleiner Tipp für morgen (z. B. früher schlafen, kurz raus) – freundlich, nicht belehrend, keine Diät-Vorgaben\"}. Erfinde nichts."
        val ai = aiJson(ctx, sys, data, 300)
        val text = ai?.optString("text")?.replace(Regex("[*#`]"), "")?.trim()?.ifBlank { null }
            ?: listOfNotNull(h?.let { "Heute: " + Health.text(it) }, sl?.let { Sleep.text(it) }).joinToString(" ")
        val d = JSONObject().put("fit", h ?: JSONObject.NULL).put("schlaf", sl ?: JSONObject.NULL).put("avg_kcal", avgK).put("avg_schritte", avgS)
            .put("datum", SimpleDateFormat("EEEE, d. MMMM", de).format(Date()))
        val sub = listOfNotNull(h?.takeIf { it.has("kcal") }?.let { "%,d kcal".format(de, it.optLong("kcal")) },
            h?.takeIf { it.has("schritte") }?.let { "%,d Schritte".format(de, it.optLong("schritte")) },
            h?.takeIf { it.has("defizit") }?.let { val x = it.optLong("defizit"); if (x > 0) "Defizit ${"%,d".format(de, x)}" else "Überschuss ${"%,d".format(de, -x)}" },
            sl?.let { "Schlaf ${Sleep.dur(it.optLong("min"))}" }).joinToString(" · ")
        return text to Feed.add(ctx, "bilanz", "Deine Tagesbilanz", sub, text, d)
    }

    /** "Wie viel hab ich heute verbraucht?", "Wie hab ich geschlafen?", "Wie aktiv war ich die Woche?" */
    fun healthAnswer(ctx: Context, was: String): String = when (was) {
        "schlaf" -> Sleep.text(Sleep.night(ctx, 0))
        "gestern" -> Health.day(ctx, 1)?.let { "Gestern: " + Health.text(it) } ?: Health.text(null)
        "woche" -> {
            val fl = Health.week(ctx).let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
            val nl = Sleep.week(ctx).let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
            if (fl.isEmpty() && nl.isEmpty()) Health.text(null) else listOfNotNull(
                fl.takeIf { it.isNotEmpty() }?.let { l ->
                    val avg = l.filter { it.has("kcal") }.map { it.optLong("kcal") }.average().let { if (it.isNaN()) 0L else Math.round(it) }
                    val top = l.maxByOrNull { it.optLong("schritte") }
                    "Die letzten 7 Tage hast du im Schnitt ${"%,d".format(de, avg)} Kalorien am Tag verbraucht und ${"%,d".format(de, l.sumOf { it.optLong("schritte") })} Schritte gemacht" +
                        (if (top != null) ", am aktivsten warst du am ${top.optString("tag")}." else ".")
                },
                nl.takeIf { it.isNotEmpty() }?.let { l -> "Geschlafen hast du im Schnitt ${Sleep.dur(Math.round(l.map { it.optLong("min") }.average()))}." }
            ).joinToString(" ")
        }
        "bilanz" -> dayHealth(ctx)?.first ?: Health.text(null)
        else -> Health.day(ctx, 0)?.let { "Heute bisher: " + Health.text(it) } ?: Health.text(null)
    }

    /** Wochenvorschau: genau die nächsten 7 Tage – Tag für Tag Wetter und Termine (mehrtägige mit "bis"), was vorbereiten. */
    fun weekAhead(ctx: Context): Pair<String, String>? {
        val now = System.currentTimeMillis()
        val start = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }.timeInMillis
        val evs = Cal.events(ctx, now, start + 7 * 86_400_000L).distinctBy { it.id to it.begin }
        // Wetter für 7 Tage
        val wxDays = HashMap<String, JSONObject>()
        try {
            val home = Route.home(ctx)
            if (home != null) {
                val js = JSONObject(http.newCall(Request.Builder().url("https://api.open-meteo.com/v1/forecast?latitude=${home.lat}&longitude=${home.lon}" +
                    "&daily=weather_code,temperature_2m_min,temperature_2m_max,precipitation_probability_max&timezone=auto&forecast_days=8").build())
                    .execute().use { it.body?.string() ?: "{}" }).getJSONObject("daily")
                val t = js.getJSONArray("time")
                for (i in 0 until t.length()) wxDays[t.getString(i)] = JSONObject().put("code", js.getJSONArray("weather_code").optInt(i))
                    .put("min", Math.round(js.getJSONArray("temperature_2m_min").optDouble(i))).put("max", Math.round(js.getJSONArray("temperature_2m_max").optDouble(i)))
                    .put("rain_pct", js.getJSONArray("precipitation_probability_max").optInt(i))
            }
        } catch (_: Exception) {}
        val days = JSONArray()
        val iso = SimpleDateFormat("yyyy-MM-dd", de)
        val isoUtc = SimpleDateFormat("yyyy-MM-dd", de).apply { timeZone = java.util.TimeZone.getTimeZone("UTC") }
        for (k in 0 until 7) {
            val d0 = start + k * 86_400_000L; val d1 = d0 + 86_400_000L
            val dayStr = iso.format(Date(d0))
            val dow = Calendar.getInstance().apply { timeInMillis = d0 }.get(Calendar.DAY_OF_WEEK)
            val te = JSONArray()
            for (e in evs) {
                val eEnd = if (e.end > 0) e.end else e.begin + 1
                val startsToday = (if (e.allDay) isoUtc.format(Date(e.begin)) == dayStr else e.begin in d0 until d1) ||
                    (k == 0 && (if (e.allDay) isoUtc.format(Date(e.begin)) < dayStr else e.begin < d0))   // läuft schon seit vorher
                if (startsToday) te.put(JSONObject().put("zeit", if (e.allDay) (if (e.end - e.begin > 86_400_000L) "bis " + Cal.whenText(e, "EE d.M.").substringAfter(" bis ") else "ganztägig")
                    else SimpleDateFormat("H:mm", de).format(Date(e.begin)) + (if (eEnd - e.begin > 86_400_000L) " – " + SimpleDateFormat("EE d.M.", de).format(Date(eEnd)) else ""))
                    .put("titel", e.title).put("ort", e.place))
            }
            for (f in festeWege(ctx).filter { it.day == dow }) te.put(JSONObject().put("zeit", "%d:%02d".format(f.h, f.m)).put("titel", "Los zu ${f.label}").put("ort", ""))
            days.put(JSONObject().put("tag", SimpleDateFormat("EEEE", de).format(Date(d0))).put("datum", SimpleDateFormat("d.M.", de).format(Date(d0)))
                .put("wx", wxDays[dayStr] ?: JSONObject.NULL).put("termine", te))
        }
        val data = "Die nächsten 7 Tage:\n" + (0 until days.length()).joinToString("\n") { i ->
            val d = days.getJSONObject(i); val w = d.optJSONObject("wx")
            "${d.optString("tag")} ${d.optString("datum")}: " + (if (w != null) "${w.optInt("min")}–${w.optInt("max")} Grad, Regen ${w.optInt("rain_pct")} %. " else "") +
                (0 until d.getJSONArray("termine").length()).joinToString("; ") { j -> d.getJSONArray("termine").getJSONObject(j).let { "${it.optString("zeit")} ${it.optString("titel")}" } }
        } + "\nWas du über ihn weißt:\n" + Memory.facts(ctx).takeLast(30).joinToString("\n") { "- $it" }
        val sys = "Du bist Jarvis und gibst Skyler die Vorschau auf die nächsten 7 Tage. Antworte NUR mit JSON: {\"text\": \"gesprochen, locker, 4 bis 6 Sätze, " +
            "ohne Listen: die wichtigsten Termine und wie das Wetter wird (wann Regen, wann kalt)\", \"mitnehmen\": [\"was er für die Termine mitnehmen oder vorbereiten sollte, " +
            "mit Tag, z. B. 'Di: Sportsachen' – nur wenn es daraus folgt\"]}. Erfinde nichts."
        val ai = aiJson(ctx, sys, data, 600) ?: return null
        val text = ai.optString("text").replace(Regex("[*#`]"), "").trim().ifBlank { return null }
        val n = (0 until days.length()).sumOf { days.getJSONObject(it).getJSONArray("termine").length() }
        val d = JSONObject().put("richtung", "vor").put("tage", days).put("mitnehmen", strs(ai.optJSONArray("mitnehmen")))
            .put("von", SimpleDateFormat("EE d.M.", de).format(Date(start))).put("bis", SimpleDateFormat("EE d.M.", de).format(Date(start + 6 * 86_400_000L)))
        return text to Feed.add(ctx, "vorschau", "Deine nächste Woche", "$n Termine · ${days.length()} Tage", text, d)
    }
}

class AlltagReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action == Alltag.ACTION_CANCEL) Alltag.cancelAway(ctx)
        if (intent.action == Alltag.ACTION_ZIEL) Alltag.zielAnswer(ctx, intent.getStringExtra("place") ?: "", intent.getBooleanExtra("yes", false))
        if (intent.action == Alltag.ACTION_SCHRANK) {
            val r = Wardrobe.feedback(ctx, intent.getIntExtra("v", 0))
            ctx.getSystemService(android.app.NotificationManager::class.java).cancel(362)
            android.widget.Toast.makeText(ctx, r, android.widget.Toast.LENGTH_SHORT).show()
        }
    }
}
