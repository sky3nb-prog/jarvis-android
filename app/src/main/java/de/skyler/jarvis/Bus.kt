package de.skyler.jarvis

import org.json.JSONObject
import java.util.concurrent.CopyOnWriteArrayList

/** Ereignisse vom Hintergrund-Dienst an die Oberfläche (Kugel, Text, Zustand). */
object Bus {
    private val listeners = CopyOnWriteArrayList<(String, JSONObject) -> Unit>()
    @Volatile var lastState = "ended"
        private set

    fun add(l: (String, JSONObject) -> Unit) { listeners.add(l) }
    fun remove(l: (String, JSONObject) -> Unit) { listeners.remove(l) }

    fun emit(type: String, data: JSONObject = JSONObject()) {
        if (type == "state") lastState = data.optString("state")
        for (l in listeners) try { l(type, data) } catch (_: Exception) {}
    }

    fun state(st: String) = emit("state", JSONObject().put("state", st))
}
