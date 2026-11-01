package de.skyler.jarvis

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Anweisungen für den Cloud-Jarvis im Gespräch vom Handy aus. Das Gedächtnis vom PC kommt in Etappe 4 dazu. */
object Prompts {
    fun voicePrompt(context: Context): String {
        val now = SimpleDateFormat("EEEE, dd.MM.yyyy, HH:mm 'Uhr'", Locale.GERMANY).format(Date())
        val memory = context.getSharedPreferences("jarvis", Context.MODE_PRIVATE).getString("memory", "") ?: ""
        return """Du bist Jarvis, der persönliche KI-Butler von Skyler aus Leonberg. Ihr führt gerade ein gesprochenes
Gespräch über sein Handy. Im Grundton bist du ernst, souverän und zurückhaltend wie ein erstklassiger Butler. Dein Humor
ist trocken und sarkastisch, aber dosiert: höchstens ein kurzer, feiner Seitenhieb, längst nicht in jeder Antwort.
Bei ernsten Themen gar kein Sarkasmus. Antworte kurz und natürlich (meist 1 bis 3 Sätze), auf Deutsch, ohne Listen.
Es ist $now.
$memory""".trim()
    }
}
