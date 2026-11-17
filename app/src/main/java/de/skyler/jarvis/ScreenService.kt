package de.skyler.jarvis

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.graphics.Bitmap
import android.os.Build
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Bedienungshilfe (einmal in den Einstellungen einschalten):
 *  - "Schau mal hier": Bildschirmfoto auf Kommando.
 *  - Zeitpunkt der letzten Berührung für die Schlaf-Erkennung (was berührt wurde, sieht Jarvis nicht).
 *  - NUR in WhatsApp: liest die Nachrichten mit, die gerade auf dem Bildschirm stehen (wenn du einen Chat offen hast
 *    oder hochscrollst), damit Jarvis deinen Schreibstil pro Person lernt. Ausschaltbar: Einstellungen → Leute → Schreibstil.
 *  - Drückt in WhatsApp auf „Senden“, wenn Jarvis gerade selbst etwas verschickt (Sprachnachricht, Absage) – nur dann.
 */
class ScreenService : AccessibilityService() {
    companion object {
        @Volatile var inst: ScreenService? = null
            private set
        private val WA = setOf("com.whatsapp", "com.whatsapp.w4b")
        @Volatile var sendUntil = 0L   // bis dahin darf er in WhatsApp „Senden“ drücken (von Jarvis ausgelöst)

        fun enabled() = inst != null

        /** Bildschirmfoto (oder null, wenn nicht eingeschaltet / nicht möglich). Wartet höchstens 5 Sekunden. */
        fun capture(): Bitmap? {
            val s = inst ?: return null
            if (Build.VERSION.SDK_INT < 30) return null
            var out: Bitmap? = null
            val done = CountDownLatch(1)
            try {
                s.takeScreenshot(Display.DEFAULT_DISPLAY, s.mainExecutor, object : TakeScreenshotCallback {
                    override fun onSuccess(r: ScreenshotResult) {
                        try {
                            out = Bitmap.wrapHardwareBuffer(r.hardwareBuffer, r.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
                        } catch (_: Exception) {}
                        try { r.hardwareBuffer.close() } catch (_: Exception) {}
                        done.countDown()
                    }
                    override fun onFailure(code: Int) { done.countDown() }
                })
            } catch (_: Exception) { done.countDown() }
            done.await(5, TimeUnit.SECONDS)
            return out
        }

        /** Jarvis verschickt gleich selbst etwas über WhatsApp: in den nächsten 20 Sekunden einmal „Senden“ drücken. */
        fun armSend() { sendUntil = System.currentTimeMillis() + 20_000L }
    }

    private var lastRead = 0L
    private val handler = android.os.Handler(android.os.Looper.getMainLooper())
    private val late = Runnable { try { rootInActiveWindow?.packageName?.toString()?.takeIf { it in WA }?.let { readChat(it) } } catch (_: Exception) {} }

    override fun onServiceConnected() { inst = this }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        when (event?.eventType) {
            AccessibilityEvent.TYPE_VIEW_CLICKED, AccessibilityEvent.TYPE_VIEW_LONG_CLICKED, AccessibilityEvent.TYPE_VIEW_SCROLLED,
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> try { Sleep.touch(this) } catch (_: Exception) {}
        }
        val pkg = event?.packageName?.toString() ?: return
        if (pkg !in WA) return
        if (System.currentTimeMillis() < sendUntil) try { if (pressSend()) sendUntil = 0L } catch (_: Exception) {}
        if (event.eventType == AccessibilityEvent.TYPE_VIEW_SCROLLED || event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED ||
            event.eventType == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED) {
            // Beim schnellen Hochscrollen jede neue Bildschirmseite mitnehmen: höchstens alle 0,4 s lesen,
            // und nach dem letzten Scrollen noch einmal (falls er mitten im Wischen stehen blieb)
            val now = System.currentTimeMillis()
            handler.removeCallbacks(late); handler.postDelayed(late, 600)
            if (now - lastRead < 400) return
            lastRead = now
            try { readChat(pkg) } catch (_: Exception) {}
        }
    }

    private fun byId(root: AccessibilityNodeInfo, pkg: String, id: String) = try { root.findAccessibilityNodeInfosByViewId("$pkg:id/$id") ?: emptyList() } catch (_: Exception) { emptyList() }

    private fun pressSend(): Boolean {
        val root = rootInActiveWindow ?: return false
        val pkg = root.packageName?.toString() ?: return false
        val btn = (byId(root, pkg, "send") + byId(root, pkg, "send_btn") + byId(root, pkg, "fab")).firstOrNull { it.isEnabled && it.isVisibleToUser }
            ?: root.findAccessibilityNodeInfosByText("Senden")?.firstOrNull { it.isClickable && it.isVisibleToUser }
            ?: return false
        return btn.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    /** Sichtbare Nachrichten des offenen Chats: eigene (mit Häkchen) und fremde, in Bildschirm-Reihenfolge. */
    private fun readChat(pkg: String) {
        if (!Stil.mitlesen(this)) return
        val root = rootInActiveWindow ?: return
        val title = byId(root, pkg, "conversation_contact_name").firstOrNull()?.text?.toString()?.trim() ?: return
        if (title.isBlank()) return
        val texts = byId(root, pkg, "message_text")
        if (texts.isEmpty()) return
        val rows = mutableListOf<Triple<String, String, Int>>()   // (von, text, y) – von "ich" oder Name; Zitat als "zitat:…"
        for (t in texts) {
            val txt = t.text?.toString()?.trim() ?: continue
            if (txt.isBlank()) continue
            // die Sprechblase: nach oben gehen, bis ein Element mit Häkchen (= eigene) oder Absendername (Gruppe) auftaucht
            var p: AccessibilityNodeInfo? = t.parent; var mine = false; var sender = ""; var quote = ""
            var depth = 0
            while (p != null && depth < 4) {
                if (byIdIn(p, pkg, "status").isNotEmpty()) mine = true
                byIdIn(p, pkg, "name_in_group_tv").firstOrNull()?.text?.toString()?.let { sender = it }
                if (quote.isBlank()) (byIdIn(p, pkg, "quoted_text") + byIdIn(p, pkg, "quoted_message_text")).firstOrNull()?.text?.toString()?.let { quote = it.trim() }
                if (mine || sender.isNotBlank()) break
                p = p.parent; depth++
            }
            val r = android.graphics.Rect(); t.getBoundsInScreen(r)
            rows.add(Triple(if (mine) "ich" else sender.ifBlank { title }, if (quote.isNotBlank() && quote != txt) "$txt\u0000$quote" else txt, r.top))
        }
        rows.sortBy { it.third }
        Stil.fromScreen(this, title, rows.map { it.first to it.second })
    }

    private fun byIdIn(n: AccessibilityNodeInfo, pkg: String, id: String) = try { n.findAccessibilityNodeInfosByViewId("$pkg:id/$id") ?: emptyList() } catch (_: Exception) { emptyList() }

    override fun onInterrupt() {}
    override fun onUnbind(intent: Intent?): Boolean { inst = null; return super.onUnbind(intent) }
    override fun onDestroy() { inst = null; super.onDestroy() }
}
