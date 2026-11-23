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
 * Schickt als normale Fotos, in Päckchen von PHOTO_BATCH auf einmal (ACTION_SEND_MULTIPLE statt ACTION_SEND
 * einzeln je Bild) - genau wie am PC (pc_sticker.py, _run_photos). Grund für den Wechsel weg vom echten
 * Sticker: WhatsApp erkennt nur ein einzeln verschicktes Bild als Sticker, mehrere zusammen zeigt es ohnehin
 * nur als Fotos an - wer schnell viele raushauen will, bekommt also automatisch Fotos statt Sticker, dafür
 * geht's in Päckchen deutlich schneller als eins nach dem anderen.
 *
 * Bild-Quelle (Design-Entscheidung, siehe Abschlussbericht): Es gibt in dieser App noch keinen eigenen Sticker-
 * Speicher nur fürs Handy – die Galerie-Auswahl (MainActivity.stickerPickImage/stickerCmd) schickt Bilder direkt
 * zum PC. Als erster, einfacher Wurf nimmt der Sticker-Regen deshalb die zuletzt empfangenen/benutzten WhatsApp-
 * Sticker aus WhatsApps eigenem Medienordner (dort liegen sie schon fertig als .webp) - werden hier aber als
 * ganz normale Bilddateien verschickt, nicht als Sticker.
 */
object StickerRain {
    private const val TAG = "JarvisStickerRain"
    private const val PHOTO_BATCH = 30   // wie am PC: WhatsApp nimmt pro Mal nur begrenzt viele Bilder an
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
                // bis zu PHOTO_BATCH Kopien einmal anlegen, dann für jedes Päckchen wiederverwenden
                val cached = (0 until minOf(PHOTO_BATCH, stickers.size.coerceAtLeast(1))).mapNotNull { i ->
                    val src = stickers[i % stickers.size]
                    val dst = File(dir, "s$i.webp")
                    try {
                        if (!dst.exists() || dst.length() != src.length()) src.copyTo(dst, overwrite = true)
                        FileProvider.getUriForFile(ctx, ctx.packageName + ".files", dst)
                    } catch (_: Exception) { null }
                }
                if (cached.isEmpty()) { onDone("Die Bilder gingen nicht raus."); running = false; return@Thread }
                var rest = count
                while (rest > 0) {
                    if (stopFlag) break
                    // Sicherheitsregel wie am PC ("nur solange WhatsApp vorne ist"): nach dem ersten Päckchen
                    // abbrechen, wenn WhatsApp nicht mehr vorne ist (z. B. weil der Nutzer die App gewechselt hat).
                    if (sent > 0) {
                        val fg = ScreenService.foregroundPkg()
                        if (fg != null && fg !in WA) break
                    }
                    val chunk = minOf(PHOTO_BATCH, rest)
                    val uris = ArrayList((0 until chunk).map { cached[it % cached.size] })
                    ScreenService.armSend()
                    ctx.startActivity(Intent(Intent.ACTION_SEND_MULTIPLE).setType("image/*").setPackage(pkg)
                        .putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris).putExtra("jid", jid)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION))
                    sent += chunk
                    rest -= chunk
                    Thread.sleep((600 + 40L * chunk).coerceAtMost(2500))   // mehr Bilder im Päckchen = mehr Zeit für die Vorschau
                }
            } catch (e: Exception) { Log.w(TAG, "send: $e") }
            running = false
            onDone(when {
                stopFlag && sent > 0 -> "Gestoppt – $sent von $count Bildern waren raus."
                sent >= count -> "Fertig – $sent Bilder an $to, direkt über WhatsApp am Handy."
                sent > 0 -> "$sent von $count Bildern an $to raus, dann hat WhatsApp nicht mehr vorne gelegen – abgebrochen."
                else -> "Die Bilder gingen nicht raus."
            })
        }, "jarvis-stickerrain").start()
    }
}
