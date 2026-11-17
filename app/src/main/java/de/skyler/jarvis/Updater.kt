package de.skyler.jarvis

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.telephony.TelephonyManager
import android.util.Log
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Updates selbst installieren: neue APK im Hintergrund laden und installieren, sobald der Bildschirm aus ist
 * (nicht während eines Anrufs). Ab Android 12 geht das ohne Nachfrage, wenn Jarvis sich vorher einmal selbst
 * installiert hat – beim allerersten Mal fragt Android einmal „Installieren?“ (kommt als Benachrichtigung).
 * Voraussetzung: „Unbekannte Apps installieren“ für Jarvis erlaubt (Einstellungen → System → Updates).
 */
object Updater {
    private const val TAG = "JarvisUpd"
    const val APK = "https://github.com/sky3nb-prog/jarvis-android/releases/download/neueste/Jarvis.apk"
    private const val CH = "jarvis_update"
    private val http = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()
    @Volatile private var busy = false

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun auto(ctx: Context) = prefs(ctx).getBoolean("upd_auto", true)
    fun setAuto(ctx: Context, on: Boolean) = prefs(ctx).edit().putBoolean("upd_auto", on).apply()
    fun canInstall(ctx: Context) = Build.VERSION.SDK_INT < 26 || ctx.packageManager.canRequestPackageInstalls()
    fun pending(ctx: Context) = prefs(ctx).getLong("upd_pending", 0L)

    fun mine(ctx: Context): Long {
        val pi = ctx.packageManager.getPackageInfo(ctx.packageName, 0)
        return if (Build.VERSION.SDK_INT >= 28) pi.longVersionCode else @Suppress("DEPRECATION") pi.versionCode.toLong()
    }

    fun allowIntent(ctx: Context): Intent =
        if (Build.VERSION.SDK_INT >= 26) Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + ctx.packageName))
        else Intent(Settings.ACTION_SECURITY_SETTINGS)

    /** Neuere Version gefunden (läuft im Hintergrund-Thread). true = wird selbst installiert. */
    fun found(ctx: Context, build: Long): Boolean {
        if (!auto(ctx) || !canInstall(ctx)) return false
        val f = file(ctx, build)
        if (!f.exists() || f.length() < 1_000_000) {
            if (!download(f)) return false
            ctx.cacheDir.listFiles()?.filter { it.name.startsWith("upd-") && it != f }?.forEach { it.delete() }
        }
        prefs(ctx).edit().putLong("upd_pending", build).apply()
        if (goodMoment(ctx)) install(ctx, f, build)
        return true
    }

    /** Bildschirm ging aus: wartendes Update jetzt einspielen. */
    fun screenOff(ctx: Context) {
        val b = pending(ctx)
        if (b <= 0) return
        if (b <= mine(ctx)) { prefs(ctx).edit().remove("upd_pending").apply(); return }
        val f = file(ctx, b)
        if (f.exists() && goodMoment(ctx)) install(ctx, f, b)
    }

    private fun file(ctx: Context, build: Long) = File(ctx.cacheDir, "upd-$build.apk")

    private fun goodMoment(ctx: Context): Boolean {
        val screenOn = ctx.getSystemService(PowerManager::class.java)?.isInteractive ?: true
        val call = try { (ctx.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager).callState != TelephonyManager.CALL_STATE_IDLE } catch (_: Exception) { false }
        val h = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY)
        return !screenOn && !call && h in 7..21   // nicht nachts: danach muss Jarvis einmal angetippt werden
    }

    private fun download(f: File): Boolean = try {
        val tmp = File(f.path + ".part")
        http.newCall(Request.Builder().url(APK).build()).execute().use { r ->
            if (!r.isSuccessful) throw Exception("HTTP ${r.code}")
            r.body!!.byteStream().use { inp -> tmp.outputStream().use { inp.copyTo(it) } }
        }
        tmp.renameTo(f)
    } catch (e: Exception) { Log.w(TAG, "download: $e"); false }

    private fun install(ctx: Context, f: File, build: Long) {
        if (busy) return
        busy = true
        try {
            val pi = ctx.packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            params.setAppPackageName(ctx.packageName)
            if (Build.VERSION.SDK_INT >= 31) params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
            val id = pi.createSession(params)
            pi.openSession(id).use { s ->
                s.openWrite("base.apk", 0, f.length()).use { out -> f.inputStream().use { it.copyTo(out) }; s.fsync(out) }
                prefs(ctx).edit().putLong("upd_from", mine(ctx)).apply()
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
                val pend = PendingIntent.getBroadcast(ctx, 777, Intent(ctx, UpdateReceiver::class.java).putExtra("build", build), flags)
                s.commit(pend.intentSender)
            }
        } catch (e: Exception) { Log.w(TAG, "install: $e"); busy = false }
    }

    internal fun result(ctx: Context, i: Intent) {
        busy = false
        val st = i.getIntExtra(PackageInstaller.EXTRA_STATUS, -999)
        when (st) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION") val confirm = i.getParcelableExtra<Intent>(Intent.EXTRA_INTENT) ?: return
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                note(ctx, "Jarvis-Update bereit", "Einmal antippen und „Aktualisieren“ – danach installiert Jarvis Updates selbst.",
                    PendingIntent.getActivity(ctx, 778, confirm, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
            }
            PackageInstaller.STATUS_SUCCESS -> {}
            else -> {
                Log.w(TAG, "Update ging nicht: $st ${i.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)}")
                prefs(ctx).edit().remove("upd_pending").apply()
                val open = PendingIntent.getActivity(ctx, 779, Intent(Intent.ACTION_VIEW, Uri.parse(APK)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE)
                note(ctx, "Neue Jarvis-Version da", "Selbst installieren ging nicht – antippen zum Herunterladen.", open)
            }
        }
    }

    /** Nach dem Update (MY_PACKAGE_REPLACED): kurz Bescheid geben, Antippen startet Jarvis wieder. */
    fun replaced(ctx: Context) {
        val p = prefs(ctx)
        if (p.getLong("upd_from", 0L) == 0L) return
        p.edit().remove("upd_from").remove("upd_pending").apply()
        ctx.cacheDir.listFiles()?.filter { it.name.startsWith("upd-") }?.forEach { it.delete() }
        val v = try { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName } catch (_: Exception) { "" }
        val open = PendingIntent.getActivity(ctx, 780, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE)
        note(ctx, "Jarvis ist aktualisiert ($v)", "Antippen, damit ich wieder zuhöre.", open)
    }

    private fun note(ctx: Context, title: String, text: String, tap: PendingIntent) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel(CH, "Updates", NotificationManager.IMPORTANCE_HIGH))
        val b = NotificationCompat.Builder(ctx, CH).setSmallIcon(android.R.drawable.stat_sys_download_done).setContentTitle(title)
            .setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text)).setAutoCancel(true).setContentIntent(tap)
        try { nm.notify(360, b.build()) } catch (_: Exception) {}
    }
}

class UpdateReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) { Updater.result(ctx, intent) }
}
