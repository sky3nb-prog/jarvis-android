package de.skyler.jarvis

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import java.io.File
import java.security.KeyStore

/**
 * Selbstzerstörung (nur in der Ausgabe für alle von der Website): Jarvis räumt auf diesem Handy alles weg
 * und deinstalliert sich danach.
 *  1. Dieses Handy aus dem Konto austragen (seine Sicherung im Konto wird gelöscht – andere Geräte bleiben)
 *  2. Modus zurück auf normal (Lautstärken, Nicht stören), von Jarvis gestellte Wecker aus
 *  3. Hintergrund-Dienst beenden, Tresor-Schlüssel löschen
 *  4. Alle Daten der App löschen (Einstellungen, Gedächtnis, Stimmen, Modelle, Zwischenspeicher)
 *  5. Android fragt: „App deinstallieren?“ – Berechtigungen, Widget und Bedienungshilfe verschwinden damit auch.
 */
object Weg {
    private const val TAG = "JarvisWeg"

    fun allowed(ctx: Context) = BuildConfig.FLAVOR == "konto"

    fun destroy(act: Activity, done: (String) -> Unit) {
        if (!allowed(act)) { done("Gibt es nur in der Ausgabe von der Website."); return }
        val ctx = act.applicationContext
        Thread({
            try { Konto.forgetDevice(ctx) } catch (e: Exception) { Log.w(TAG, "Konto: $e") }
            try { Modes.set(ctx, "aus") } catch (e: Exception) { Log.w(TAG, "Modus: $e") }
            try { Wecker.off(ctx, emptyList()) } catch (e: Exception) { Log.w(TAG, "Wecker: $e") }
            try { ctx.stopService(Intent(ctx, JarvisService::class.java)) } catch (e: Exception) { Log.w(TAG, "Dienst: $e") }
            try {
                val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
                ks.aliases().toList().forEach { a -> try { ks.deleteEntry(a) } catch (_: Exception) {} }
            } catch (e: Exception) { Log.w(TAG, "Tresor: $e") }
            wipe(ctx)
            act.runOnUiThread {
                done("Alles gelöscht. Jetzt noch „Deinstallieren“ bestätigen.")
                try {
                    act.startActivity(Intent(Intent.ACTION_DELETE, Uri.parse("package:" + ctx.packageName)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                } catch (e: Exception) { Log.w(TAG, "Deinstallieren: $e") }
                act.finishAndRemoveTask()
                Thread { Thread.sleep(1500); android.os.Process.killProcess(android.os.Process.myPid()) }.start()
            }
        }, "jarvis-weg").start()
    }

    /** Alle Dateien der App löschen – so, als wäre sie frisch installiert. */
    private fun wipe(ctx: Context) {
        try {
            val prefsDir = File(ctx.applicationInfo.dataDir, "shared_prefs")
            prefsDir.listFiles()?.forEach { f ->
                val name = f.name.removeSuffix(".xml")
                try { ctx.getSharedPreferences(name, Context.MODE_PRIVATE).edit().clear().commit() } catch (_: Exception) {}
                try { ctx.deleteSharedPreferences(name) } catch (_: Exception) {}
            }
        } catch (e: Exception) { Log.w(TAG, "Einstellungen: $e") }
        val dirs = listOfNotNull(ctx.filesDir, ctx.cacheDir, ctx.noBackupFilesDir, ctx.codeCacheDir, ctx.getExternalFilesDir(null), ctx.externalCacheDir,
            File(ctx.applicationInfo.dataDir, "databases"), File(ctx.applicationInfo.dataDir, "app_webview"))
        for (d in dirs) try { d.listFiles()?.forEach { it.deleteRecursively() } } catch (e: Exception) { Log.w(TAG, "Dateien $d: $e") }
        try { ctx.databaseList().forEach { ctx.deleteDatabase(it) } } catch (_: Exception) {}
    }
}
