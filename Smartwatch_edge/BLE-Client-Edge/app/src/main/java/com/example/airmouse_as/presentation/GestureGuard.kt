package com.example.airmouse_as.presentation

import kotlin.math.sqrt

enum class Mode { TRACKING, GESTURE, COOLDOWN }

data class GyroSample(
    val tMs: Int,
    val gx: Float,
    val gy: Float,
    val gz: Float,
)

// Extension function su GyroSample per calcolare la velocità angolare totale in gradi/s
fun GyroSample.rateDps(): Double {
    val x = gx.toDouble()
    val y = gy.toDouble()
    val z = gz.toDouble()
    return Math.toDegrees(sqrt(x * x + y * y + z * z))
}

interface GuardDecision {
    object Tracking : GuardDecision
    object Buffering : GuardDecision
    data class GestureComplete(val window: List<GyroSample>) : GuardDecision
}


class GestureGuard(
    private val rateOnDps: Double = 100.0,
    private val rateOffDps: Double = 40.0,
    private val settleSamples: Int = 5,
    private val maxGestureSamples: Int = 30,
    private val cooldownSamples: Int = 20,
    private val preRoll: Int = 4,              // campioni da conservare prima dello scatto
) {
    var mode = Mode.TRACKING
        private set

    private val window = mutableListOf<GyroSample>()
    private val history = ArrayDeque<GyroSample>()
    private var calm = 0
    private var cooldown = 0

    private fun remember(s: GyroSample) {
        history.addLast(s)
        while (history.size > preRoll) history.removeFirst()
    }

    fun update(s: GyroSample): GuardDecision {
        val rate = s.rateDps()

        when (mode) {
            Mode.TRACKING -> {
                if (rate > rateOnDps) {
                    mode = Mode.GESTURE
                    window.clear()
                    window.addAll(history)
                    window += s
                    calm = 0
                    return GuardDecision.Buffering
                }
                remember(s)
                return GuardDecision.Tracking
            }

            Mode.GESTURE -> {
                window += s
                calm = if (rate < rateOffDps) calm + 1 else 0

                if (calm >= settleSamples) {
                    mode = Mode.COOLDOWN
                    cooldown = cooldownSamples
                    history.clear()
                    return GuardDecision.GestureComplete(window.toList())
                }
                if (window.size > maxGestureSamples) {
                    mode = Mode.TRACKING
                    window.clear()
                    history.clear()
                    return GuardDecision.Tracking
                }
                return GuardDecision.Buffering
            }

            Mode.COOLDOWN -> {
                remember(s)
                if (--cooldown <= 0) mode = Mode.TRACKING
                return GuardDecision.Tracking
            }
        }
    }

    fun reset() {
        mode = Mode.TRACKING
        window.clear()
        history.clear()
        calm = 0
        cooldown = 0
    }
}
