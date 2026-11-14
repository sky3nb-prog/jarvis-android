package de.skyler.jarvis

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.graphics.Bitmap
import android.os.Build
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * "Schau mal hier": macht auf Kommando ein Bildschirmfoto (Bedienungshilfe, einmal in den Einstellungen einschalten).
 * Liest keine Inhalte mit. Einzige Ausnahme: der ZEITPUNKT der letzten Berührung (Tippen, Wischen, Tippen auf der Tastatur)
 * wird für die Schlaf-Erkennung gemerkt (Sleep.touch) – was berührt wurde, sieht Jarvis nicht.
 */
class ScreenService : AccessibilityService() {
    companion object {
        @Volatile var inst: ScreenService? = null
            private set

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
    }

    override fun onServiceConnected() { inst = this }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        when (event?.eventType) {
            AccessibilityEvent.TYPE_VIEW_CLICKED, AccessibilityEvent.TYPE_VIEW_LONG_CLICKED, AccessibilityEvent.TYPE_VIEW_SCROLLED,
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> try { Sleep.touch(this) } catch (_: Exception) {}
        }
    }
    override fun onInterrupt() {}
    override fun onUnbind(intent: Intent?): Boolean { inst = null; return super.onUnbind(intent) }
    override fun onDestroy() { inst = null; super.onDestroy() }
}
