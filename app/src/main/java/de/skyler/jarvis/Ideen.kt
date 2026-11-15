package de.skyler.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** Ideen-Sammler: "Jarvis, ich hab eine Idee: …" -> auf die Liste (hier und am PC, dort im HUD unter Einstellungen → Allgemein). */
object Ideen {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)
    fun all(ctx: Context): JSONArray = try { JSONArray(prefs(ctx).getString("ideen", "[]")) } catch (_: Exception) { JSONArray() }
    fun setAll(ctx: Context, a: JSONArray) { prefs(ctx).edit().putString("ideen", a.toString()).apply() }

    fun add(ctx: Context, text: String, toPc: Boolean = true): String {
        val t = text.trim().trimEnd('.'); if (t.isBlank()) return "Was ist die Idee?"
        val a = all(ctx); a.put(JSONObject().put("t", System.currentTimeMillis()).put("text", t).put("von", "handy")); setAll(ctx, a)
        if (toPc && Link.paired(ctx)) Thread { try { Link.command(ctx, JSONObject().put("type", "text").put("text", "notiere idee vom handy: $t"), 15_000) } catch (_: Exception) {} }.start()
        return "Steht auf deiner Ideenliste: „$t“. Das ist Idee Nummer ${a.length()}."
    }
}
