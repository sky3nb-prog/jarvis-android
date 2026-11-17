package de.skyler.jarvis

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.ContactsContract
import android.telecom.TelecomManager
import android.telephony.PhoneStateListener
import android.telephony.SmsManager
import android.telephony.TelephonyManager
import android.util.Log
import androidx.core.app.NotificationCompat
import org.json.JSONObject

/**
 * Anruf-Butler: Ruft jemand aus deinen Kontakten an und das Handy steht auf "Nicht stören", drückt Jarvis den Anruf
 * weg und schickt "Kann gerade nicht, rufe später zurück". Sonst gibt es beim Klingeln einen Knopf, der dasselbe tut.
 * Unbekannte Nummern (Spam) lässt er in Ruhe. Geschickt wird per WhatsApp am PC, wenn der läuft, sonst per SMS.
 */
object Butler {
    private const val TAG = "JarvisButler"
    private const val CH = "jarvis_anruf"
    private const val NID = 77
    const val ACTION = "de.skyler.jarvis.ABSAGE"
    @Volatile private var listener: PhoneStateListener? = null
    @Volatile private var handled = ""

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun on(ctx: Context) = prefs(ctx).getBoolean("butler", true)
    fun text(ctx: Context) = (prefs(ctx).getString("absage", "") ?: "").ifBlank { "Kann gerade nicht, rufe später zurück." }
    private fun has(ctx: Context, p: String) = ctx.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    val PERMS = listOf(Manifest.permission.READ_PHONE_STATE, Manifest.permission.READ_CALL_LOG,
        Manifest.permission.ANSWER_PHONE_CALLS, Manifest.permission.SEND_SMS)
    fun ready(ctx: Context) = PERMS.all { has(ctx, it) }

    /** Im Dienst auf dem Haupt-Thread aufrufen (Start und nach "Einstellungen gespeichert"). */
    @Suppress("DEPRECATION")
    fun start(ctx: Context) {
        if (listener != null || !has(ctx, Manifest.permission.READ_PHONE_STATE)) return
        val app = ctx.applicationContext
        val l = object : PhoneStateListener() {
            override fun onCallStateChanged(state: Int, number: String?) {
                try {
                    if (state == TelephonyManager.CALL_STATE_RINGING) ringing(app, number ?: "")
                    else { handled = ""; app.getSystemService(NotificationManager::class.java).cancel(NID); hideFloat(app) }
                } catch (e: Exception) { Log.w(TAG, "anruf: $e") }
            }
        }
        try {
            (app.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager).listen(l, PhoneStateListener.LISTEN_CALL_STATE)
            listener = l
        } catch (e: Exception) { Log.w(TAG, "listen: $e") }
    }

    @Suppress("DEPRECATION")
    fun stop(ctx: Context) {
        val l = listener ?: return
        try { (ctx.applicationContext.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager).listen(l, PhoneStateListener.LISTEN_NONE) } catch (_: Exception) {}
        listener = null
    }

    private fun contact(ctx: Context, number: String): String? = try {
        ctx.contentResolver.query(Uri.withAppendedPath(ContactsContract.PhoneLookup.CONTENT_FILTER_URI, Uri.encode(number)),
            arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME), null, null, null)?.use { if (it.moveToFirst()) it.getString(0) else null }
    } catch (_: Exception) { null }

    private fun ringing(ctx: Context, number: String) {
        if (!on(ctx) || handled == number) return
        val name = if (number.isBlank()) null else contact(ctx, number)
        if (name == null) { handled = number; showFloat(ctx, "", number); return }   // unbekannt: nur Auflegen-Knopf, keine Nachricht
        handled = number
        showFloat(ctx, name, number)   // großer Knopf über dem Anruf-Bildschirm
        val nm = ctx.getSystemService(NotificationManager::class.java)
        val modus = Modes.current(ctx)
        val nn = Chats.norm(name); val important = Chats.important(ctx).any { it.isNotBlank() && (nn.contains(it) || it.contains(nn)) }
        if (modus == "schule" && !important) { decline(ctx, name, number); return }   // Schulmodus: nur wichtige Leute kommen durch
        if (nm.currentInterruptionFilter > NotificationManager.INTERRUPTION_FILTER_ALL) {   // "Nicht stören" ist an
            decline(ctx, name, number)
            return
        }
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "Anrufe", NotificationManager.IMPORTANCE_HIGH)
            .apply { description = "Knopf „Kann gerade nicht“ beim Klingeln"; setSound(null, null); enableVibration(false) })
        val pi = PendingIntent.getBroadcast(ctx, 0, Intent(ctx, ButlerReceiver::class.java).setAction(ACTION)
            .putExtra("name", name).putExtra("number", number), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        nm.notify(NID, NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.sym_call_incoming)
            .setContentTitle("$name ruft an").setContentText("„${text(ctx)}“ schicken und wegdrücken")
            .setPriority(NotificationCompat.PRIORITY_HIGH).setCategory(NotificationCompat.CATEGORY_CALL).setTimeoutAfter(60_000)
            .addAction(0, "Kann gerade nicht", pi).setContentIntent(pi).setAutoCancel(true).build())
    }

    // --- Schwebender Knopf über dem Anruf-Bildschirm (die Benachrichtigung sieht man beim Klingeln oft nicht) -------
    @Volatile private var floatView: android.view.View? = null
    private val main = android.os.Handler(android.os.Looper.getMainLooper())

    // --- WhatsApp-Anrufe: Wegdrücken über Jarvis + Nachricht in deinem Stil ------------------------------------------
    @Volatile var waCall: Pair<String, android.app.PendingIntent>? = null; private set
    @Volatile private var waCallAt = 0L

    /** Aus MediaWatch: Benachrichtigung von WhatsApp. Eingehender Anruf = Kategorie „call“ mit „Ablehnen“-Knopf. */
    fun onWaNotification(ctx: Context, sbn: android.service.notification.StatusBarNotification) {
        if (sbn.packageName != "com.whatsapp" && sbn.packageName != "com.whatsapp.w4b") return
        val n = sbn.notification ?: return
        if (n.category != android.app.Notification.CATEGORY_CALL || !on(ctx)) return
        val decline = n.actions?.firstOrNull { a -> Regex("ablehn|decline|abweis|reject", RegexOption.IGNORE_CASE).containsMatchIn(a.title?.toString() ?: "") } ?: return
        val name = (n.extras?.getCharSequence(android.app.Notification.EXTRA_TITLE)?.toString() ?: "").replace(Regex("[\u200e\u200f\u202a-\u202e]"), "").trim()
        if (name.isBlank() || System.currentTimeMillis() - waCallAt < 8_000L && waCall?.first == name) return
        waCall = name to decline.actionIntent; waCallAt = System.currentTimeMillis()
        val nn = Chats.norm(name); val important = Chats.important(ctx).any { it.isNotBlank() && (nn.contains(it) || it.contains(nn)) }
        if (Modes.current(ctx) == "schule" && !important) { waDecline(ctx); return }
        showFloat(ctx, name, "", wa = true)
        main.postDelayed({ if (System.currentTimeMillis() - waCallAt >= 59_000L) waCall = null }, 60_000)
    }

    /** Wegdrücken (auch per Sprache: „Friday, drück weg“) und kurz auf WhatsApp Bescheid geben. */
    fun waDecline(ctx: Context): String {
        val (name, pi) = waCall ?: return "Gerade ruft niemand über WhatsApp an."
        waCall = null; hideFloat(ctx)
        try { pi.send() } catch (e: Exception) { Log.w(TAG, "wa ablehnen: $e") }
        Thread({
            val msg = try { if (Stil.samples(ctx).size >= 20) Stil.write(ctx, "Sag $name kurz, dass du gerade nicht telefonieren kannst und dich später meldest.", chat = Chats.norm(name)) else "" } catch (_: Exception) { "" }
                .ifBlank { text(ctx) }
            Thread.sleep(1500)   // Anruf-Bildschirm erst zugehen lassen
            val ok = try { WaSend.text(ctx, name, msg) } catch (_: Exception) { false }
            Feed.add(ctx, "anruf", "WhatsApp-Anruf von $name weggedrückt", "„$msg“ " + if (ok) "geschickt" else "– Senden ging nicht", msg,
                JSONObject().put("name", name).put("text", msg).put("ok", ok))
        }, "jarvis-wa-absage").start()
        return "Weggedrückt. Ich schreib $name, dass du dich später meldest."
    }

    fun onWaRemoved(ctx: Context, sbn: android.service.notification.StatusBarNotification) {
        if (sbn.packageName != "com.whatsapp" && sbn.packageName != "com.whatsapp.w4b") return
        if (sbn.notification?.category != android.app.Notification.CATEGORY_CALL) return
        if (System.currentTimeMillis() - waCallAt < 1500L) return
        waCall = null; hideFloat(ctx)
    }

    private fun showFloat(ctx: Context, name: String, number: String, wa: Boolean = false) = main.post {
        try {
            if (!android.provider.Settings.canDrawOverlays(ctx) || floatView != null) return@post
            val wm = ctx.getSystemService(Context.WINDOW_SERVICE) as android.view.WindowManager
            val d = ctx.resources.displayMetrics.density
            val box = android.widget.LinearLayout(ctx).apply {
                orientation = android.widget.LinearLayout.VERTICAL
                setPadding((18 * d).toInt(), (12 * d).toInt(), (18 * d).toInt(), (12 * d).toInt())
                background = android.graphics.drawable.GradientDrawable().apply { cornerRadius = 26 * d; setColor(0xF0140C04.toInt()); setStroke((2 * d).toInt(), 0xFFFFAA28.toInt()) }
                elevation = 12 * d
            }
            val title = android.widget.TextView(ctx).apply {
                text = if (wa) "JARVIS · $name ruft über WhatsApp an" else if (name.isNotBlank()) "JARVIS · $name ruft an" else "JARVIS · unbekannte Nummer"
                setTextColor(0xFFFFD678.toInt()); textSize = 12f; letterSpacing = .12f
            }
            val btn = android.widget.TextView(ctx).apply {
                text = if (wa) "Wegdrücken + kurz schreiben" else if (name.isNotBlank()) "Auflegen + „${text(ctx)}“ schicken" else "Auflegen"
                setTextColor(0xFF1A1206.toInt()); textSize = 16f; typeface = android.graphics.Typeface.DEFAULT_BOLD
                gravity = android.view.Gravity.CENTER
                setPadding((14 * d).toInt(), (12 * d).toInt(), (14 * d).toInt(), (12 * d).toInt())
                background = android.graphics.drawable.GradientDrawable().apply { cornerRadius = 22 * d; setColor(0xFFFFC04A.toInt()) }
                setOnClickListener {
                    hideFloat(ctx)
                    if (wa) waDecline(ctx)
                    else if (name.isNotBlank()) decline(ctx, name, number)
                    else try { if (Build.VERSION.SDK_INT >= 28 && has(ctx, Manifest.permission.ANSWER_PHONE_CALLS))
                        @Suppress("DEPRECATION") (ctx.getSystemService(Context.TELECOM_SERVICE) as TelecomManager).endCall() } catch (_: Exception) {}
                }
            }
            box.addView(title); box.addView(btn, android.widget.LinearLayout.LayoutParams(-1, -2).apply { topMargin = (8 * d).toInt() })
            val lp = android.view.WindowManager.LayoutParams(-1, -2,
                if (Build.VERSION.SDK_INT >= 26) android.view.WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY else @Suppress("DEPRECATION") android.view.WindowManager.LayoutParams.TYPE_PHONE,
                android.view.WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED,
                android.graphics.PixelFormat.TRANSLUCENT).apply {
                gravity = android.view.Gravity.TOP; y = (215 * d).toInt(); horizontalMargin = 0f   // unter der Anruf-Leiste oben (die liegt immer darüber), damit der Knopf frei bleibt
            }
            val wrap = android.widget.FrameLayout(ctx).apply { setPadding((16 * d).toInt(), 0, (16 * d).toInt(), 0); addView(box) }
            wm.addView(wrap, lp); floatView = wrap
            main.postDelayed({ hideFloat(ctx) }, 60_000)
        } catch (e: Exception) { Log.w(TAG, "knopf: $e") }
    }

    fun hideFloat(ctx: Context) = main.post {
        val v = floatView ?: return@post
        try { (ctx.getSystemService(Context.WINDOW_SERVICE) as android.view.WindowManager).removeView(v) } catch (_: Exception) {}
        floatView = null
    }

    /** Wegdrücken und Bescheid geben. */
    fun decline(ctx: Context, name: String, number: String) {
        try {
            if (Build.VERSION.SDK_INT >= 28 && has(ctx, Manifest.permission.ANSWER_PHONE_CALLS))
                @Suppress("DEPRECATION") (ctx.getSystemService(Context.TELECOM_SERVICE) as TelecomManager).endCall()
        } catch (e: Exception) { Log.w(TAG, "wegdrücken: $e") }
        ctx.getSystemService(NotificationManager::class.java).cancel(NID); hideFloat(ctx)
        val msg = text(ctx)
        Thread({
            var done = false
            if (Link.paired(ctx) && Link.pcOnline(ctx)) {   // PC läuft: WhatsApp über den PC
                val r = try { Link.command(ctx, JSONObject().put("type", "wa_send").put("to", name).put("text", msg), 25_000) } catch (_: Exception) { null }
                done = r?.optBoolean("ok") == true
            }
            if (!done) done = sms(ctx, number, msg, name)
            Feed.add(ctx, "anruf", "Anruf von $name weggedrückt", "„$msg“ " + if (done) "geschickt" else "– Senden ging nicht", msg,
                JSONObject().put("name", name).put("text", msg).put("ok", done))
        }, "jarvis-absage").start()
    }

    fun sms(ctx: Context, number: String, text: String, who: String = ""): Boolean = try {
        if (!has(ctx, Manifest.permission.SEND_SMS)) false else {
            @Suppress("DEPRECATION")
            val sm = if (Build.VERSION.SDK_INT >= 31) ctx.getSystemService(SmsManager::class.java) else SmsManager.getDefault()
            sm.sendMultipartTextMessage(number, null, sm.divideMessage(text), null, null)
            sent(ctx, who.ifBlank { nameOf(ctx, number) ?: number }, text)
            true
        }
    } catch (e: Exception) { Log.w(TAG, "sms: $e"); false }

    /** Jede SMS, die Jarvis schickt: kurze Bestätigung "SMS ist raus" (wem, was). */
    private fun sent(ctx: Context, who: String, text: String) = try {
        val nm = ctx.getSystemService(android.app.NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(android.app.NotificationChannel("jarvis_sms", "SMS ist raus",
            android.app.NotificationManager.IMPORTANCE_DEFAULT))
        nm.notify(5000 + (System.currentTimeMillis() % 1000).toInt(), androidx.core.app.NotificationCompat.Builder(ctx, "jarvis_sms")
            .setSmallIcon(android.R.drawable.stat_notify_chat).setContentTitle("✓ SMS ist raus – an $who")
            .setContentText(text).setStyle(androidx.core.app.NotificationCompat.BigTextStyle().bigText(text)).setAutoCancel(true)
            .setTimeoutAfter(30 * 60_000L).build())
    } catch (e: Exception) { Log.w(TAG, "sms-info: $e") }

    private fun nameOf(ctx: Context, number: String): String? = try {
        if (!has(ctx, Manifest.permission.READ_CONTACTS)) null else
            ctx.contentResolver.query(android.net.Uri.withAppendedPath(android.provider.ContactsContract.PhoneLookup.CONTENT_FILTER_URI, android.net.Uri.encode(number)),
                arrayOf(android.provider.ContactsContract.PhoneLookup.DISPLAY_NAME), null, null, null)?.use { if (it.moveToFirst()) it.getString(0) else null }
    } catch (_: Exception) { null }
}

class ButlerReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action != Butler.ACTION) return
        Butler.decline(ctx, intent.getStringExtra("name") ?: "", intent.getStringExtra("number") ?: "")
    }
}
