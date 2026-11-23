package de.skyler.jarvis

import android.content.Context
import android.content.Intent
import android.os.Environment
import android.util.Log
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File

/**
 * Sticker-Regen DIREKT übers Handy, über die echte WhatsApp-App – Rückfall, wenn der PC nicht läuft/gekoppelt ist
 * (die normale, erste Variante bleibt Actions.sticker() über Link.command am PC, siehe pc_sticker.py).
 *
 * Vorbild: WaSend.kt (Text/Sprachnachricht per ACTION_SEND mit "jid"-Extra direkt in den richtigen Chat, dann
 * drückt die Bedienungshilfe ScreenService "Senden") und Chats.kt (Zugriff auf den WhatsApp-Medienordner, braucht
 * "Zugriff auf alle Dateien" – ist in dieser App schon vorhanden/genutzt).
 *
 * Bild-Quelle (Design-Entscheidung, siehe Abschlussbericht): Es gibt in dieser App noch keinen eigenen Sticker-
 * Speicher nur fürs Handy – die Galerie-Auswahl (MainActivity.stickerPickImage/stickerCmd) schickt Bilder direkt
 * zum PC. Als erster, einfacher Wurf nimmt der Sticker-Regen deshalb die zuletzt empfangenen/benutzten WhatsApp-
 * Sticker aus WhatsApps eigenem Medienordner (dort liegen sie schon fertig als .webp).
 */
object StickerRain {
    private const val TAG = "JarvisStickerRain"
    @Volatile var running = false
        private set
    @Volatile private var stopFlag = false

    private val WA = setOf("com.whatsapp", "com.whatsapp.w4b")
    private fun waPkg(ctx: Context) = WA.firstOrNull { try { ctx.packageManager.getPackageInfo(it, 0); true } catch (_: Exception) { false } } ?: "com.whatsapp"

    private fun filesOk(): Boolean = Chats.filesOk()

    /** WhatsApp-Sticker auf dem Handy, neueste zuerst (eigener und empfangener Sticker-Ordner, beide WA-Varianten). */
    private fun findStickers(): List<File> {
        if (!filesOk()) return emptyList()
        val root = Environment.getExternalStorageDirectory()
        val dirs = listOf(
            "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Stickers",
            "Android/media/com.whatsapp.w4b/WhatsApp Business/Media/WhatsApp Business Stickers",
            "WhatsApp/Media/WhatsApp Stickers"
        ).map { File(root, it) }.filter { it.isDirectory }
        return try {
            dirs.flatMap { d -> d.walkTopDown().maxDepth(3).filter { it.isFile && it.extension.equals("webp", true) }.toList() }
                .sortedByDescending { it.lastModified() }
        } catch (e: Exception) { Log.w(TAG, "findStickers: $e"); emptyList() }
    }

    fun available(): Boolean = try { findStickers().isNotEmpty() } catch (_: Exception) { false }

    /** „Stopp“ während es läuft: bricht nach dem nächsten Sticker ab. */
    fun cancel() { stopFlag = true }

    /**
     * Schickt bis zu n Sticker an `to`, direkt über die WhatsApp-App (nicht über den PC). Läuft in einem eigenen
     * Thread und ruft `onDone` mit dem Endergebnis auf, sobald fertig oder abgebrochen.
     * UNGETESTET auf echten Geräten – siehe Hinweis im Abschlussbericht.
     */
    fun send(ctx: Context, to: String, n: Int, onDone: (String) -> Unit) {
        if (running) { onDone("Es läuft schon ein Sticker-Regen – erst „Stopp“ sagen."); return }
        if (!ScreenService.enabled()) { onDone("Dafür brauche ich die Bedienungshilfe „Vector – Schau mal hier“ (Einstellungen → Bedienungshilfe einschalten) – ohne PC geht es nur damit."); return }
        val jid = Stil.number(ctx, to)?.let { "$it@s.whatsapp.net" }
        if (jid == null) { onDone("Ich finde $to nicht in deinen Kontakten."); return }
        val stickers = findStickers()
        if (stickers.isEmpty()) {
            onDone(if (!filesOk()) "Dafür brauche ich „Zugriff auf alle Dateien“ (Einstellungen) – ohne PC finde ich sonst keine Sticker."
                else "Ich finde keine WhatsApp-Sticker auf dem Handy, die ich schicken könnte.")
            return
        }
        val count = n.coerceIn(1, 1000)
        stopFlag = false
        running = true
        Thread({
            var sent = 0
            try {
                val pkg = waPkg(ctx)
                val dir = File(ctx.cacheDir, "wa/stickers").apply { mkdirs() }
                for (i in 0 until count) {
                    if (stopFlag) break
                    // Sicherheitsregel wie am PC ("nur solange WhatsApp-Fenster aktiv ist"): nach dem ersten Sticker
                    // abbrechen, wenn WhatsApp nicht mehr vorne ist (z. B. weil der Nutzer die App gewechselt hat).
                    if (sent > 0) {
                        val fg = ScreenService.foregroundPkg()
                        if (fg != null && fg !in WA) break
                    }
                    val src = stickers[i % stickers.size]
                    val dst = File(dir, "s${i % stickers.size}.webp")
                    if (!dst.exists() || dst.length() != src.length()) try { src.copyTo(dst, overwrite = true) } catch (_: Exception) { continue }
                    val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".files", dst)
                    ScreenService.armSend()
                    ctx.startActivity(Intent(Intent.ACTION_SEND).setType("image/webp").setPackage(pkg)
                        .putExtra(Intent.EXTRA_STREAM, uri).putExtra("jid", jid)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION))
                    sent++
                    Thread.sleep(500)
                }
            } catch (e: Exception) { Log.w(TAG, "send: $e") }
            running = false
            onDone(when {
                stopFlag && sent > 0 -> "Gestoppt – $sent von $count Stickern waren raus."
                sent >= count -> "Fertig – $sent Sticker an $to, direkt über WhatsApp am Handy."
                sent > 0 -> "$sent von $count Stickern an $to raus, dann hat WhatsApp nicht mehr vorne gelegen – abgebrochen."
                else -> "Die Sticker gingen nicht raus."
            })
        }, "jarvis-stickerrain").start()
    }
}
