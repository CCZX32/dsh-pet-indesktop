package io.github.dshpet.mobile

import android.content.Context
import android.content.SharedPreferences

data class PetOptions(val size: Float = 1f, val wander: Boolean = true, val speech: Boolean = true)

class PetPreferences(context: Context) {
    private val prefs = context.getSharedPreferences("pet", Context.MODE_PRIVATE)
    fun options() = PetOptions(
        prefs.getFloat("size", 1f).takeIf { it.isFinite() }?.coerceIn(.6f, 1.6f) ?: 1f,
        prefs.getBoolean("wander", true), prefs.getBoolean("speech", true))

    fun save(options: PetOptions) {
        prefs.edit().putFloat("size", options.size.takeIf { it.isFinite() }?.coerceIn(.6f, 1.6f) ?: 1f)
            .putBoolean("wander", options.wander).putBoolean("speech", options.speech).apply()
    }

    fun position(): Pair<Double, Double> {
        fun coordinate(key: String, default: Float) =
            (prefs.getFloat(key, default).takeIf { it.isFinite() } ?: default).coerceIn(0f, 1f).toDouble()
        return coordinate("x", .7f) to coordinate("y", 1f)
    }

    fun savePosition(x: Double, y: Double) {
        if (x.isFinite() && y.isFinite()) {
            prefs.edit().putFloat("x", x.coerceIn(0.0, 1.0).toFloat())
                .putFloat("y", y.coerceIn(0.0, 1.0).toFloat()).apply()
        }
    }

    fun reset() = prefs.edit().clear().apply()
    fun subscribe(listener: SharedPreferences.OnSharedPreferenceChangeListener) =
        prefs.registerOnSharedPreferenceChangeListener(listener)
    fun unsubscribe(listener: SharedPreferences.OnSharedPreferenceChangeListener) =
        prefs.unregisterOnSharedPreferenceChangeListener(listener)
}
