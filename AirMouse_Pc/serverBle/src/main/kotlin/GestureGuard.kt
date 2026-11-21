import kotlin.math.sqrt

enum class Mode { TRACKING, GESTURE, COOLDOWN }

sealed interface GuardDecision {
    data object Tracking : GuardDecision
    data object Buffering : GuardDecision
    data class GestureComplete(val window: List<ImuPacket>) : GuardDecision
}

class GestureGuard(
    private val rateOnDps: Double = 100.0,
    private val rateOffDps: Double = 40.0,
    private val settleSamples: Int = 5,
    private val maxGestureSamples: Int = 30,
    private val cooldownSamples: Int = 20,
    private val preRoll: Int = 4,              // campioni da tenere prima dello scatto
) {
    var mode = Mode.TRACKING
        private set

    private val window = mutableListOf<ImuPacket>()
    private val history = ArrayDeque<ImuPacket>()
    private var calm = 0
    private var cooldown = 0

    private fun remember(p: ImuPacket) {
        history.addLast(p)
        while (history.size > preRoll) history.removeFirst()
    }

    fun update(p: ImuPacket): GuardDecision {
        val rate = rateDps(p)

        when (mode) {
            Mode.TRACKING -> {
                if (rate > rateOnDps) {
                    mode = Mode.GESTURE
                    window.clear()
                    window.addAll(history)
                    window += p
                    calm = 0
                    return GuardDecision.Buffering
                }
                remember(p)
                return GuardDecision.Tracking
            }

            Mode.GESTURE -> {
                window += p
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
                remember(p)
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

    private fun rateDps(p: ImuPacket): Double {
        val gx = p.gyro[0].toDouble()
        val gy = p.gyro[1].toDouble()
        val gz = p.gyro[2].toDouble()
        return Math.toDegrees(sqrt(gx * gx + gy * gy + gz * gz))
    }
}