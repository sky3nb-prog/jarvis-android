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
                    else { handled = ""; app.getSystemService(NotificationManager::class.java).cancel(NID) }
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
        if (!on(ctx) || number.isBlank() || handled == number) return
        val name = contact(ctx, number) ?: return     // nicht in den Kontakten: vielleicht Spam -> nichts tun
        handled = number
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

    /** Wegdrücken und Bescheid geben. */
    fun decline(ctx: Context, name: String, number: String) {
        try {
            if (Build.VERSION.SDK_INT >= 28 && has(ctx, Manifest.permission.ANSWER_PHONE_CALLS))
                @Suppress("DEPRECATION") (ctx.getSystemService(Context.TELECOM_SERVICE) as TelecomManager).endCall()
        } catch (e: Exception) { Log.w(TAG, "wegdrücken: $e") }
        ctx.getSystemService(NotificationManager::class.java).cancel(NID)
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
