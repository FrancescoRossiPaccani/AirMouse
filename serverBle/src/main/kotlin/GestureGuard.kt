import kotlin.math.sqrt

enum class Mode { TRACKING, GESTURE, COOLDOWN }

sealed interface GuardDecision {
    data object Tracking : GuardDecision                       // movimento normale
    data object Buffering : GuardDecision                      // cursore congelato
    data class GestureComplete(val window: List<ImuPacket>) : GuardDecision
}

class GestureGuard(
    private val rateOnDps: Double = 100.0,     // sopra: gesto
    private val rateOffDps: Double = 40.0,     // sotto: tracking
    private val settleSamples: Int = 5,        // campioni per chiudere il gesto
    private val maxGestureSamples: Int = 25,   // sicurezza: oltre non era un gesto
    private val cooldownSamples: Int = 20,     // pausa dopo un gesto
) {
    var mode = Mode.TRACKING
        private set

    private val window = mutableListOf<ImuPacket>()
    private var calm = 0
    private var cooldown = 0

    fun update(p: ImuPacket): GuardDecision {
        val rate = rateDps(p)

        when (mode) {
            Mode.TRACKING -> {
                if (rate > rateOnDps) {
                    mode = Mode.GESTURE
                    window.clear()
                    window += p
                    calm = 0
                    return GuardDecision.Buffering
                }
                return GuardDecision.Tracking
            }

            Mode.GESTURE -> {
                window += p
                calm = if (rate < rateOffDps) calm + 1 else 0

                if (calm >= settleSamples) {
                    mode = Mode.COOLDOWN
                    cooldown = cooldownSamples
                    return GuardDecision.GestureComplete(window.toList())
                }
                if (window.size > maxGestureSamples) {
                    // troppo lungo: era un movimento veloce, non un gesto
                    mode = Mode.TRACKING
                    window.clear()
                    return GuardDecision.Tracking
                }
                return GuardDecision.Buffering
            }

            Mode.COOLDOWN -> {
                if (--cooldown <= 0) mode = Mode.TRACKING
                return GuardDecision.Tracking
            }
        }
    }

    fun reset() {
        mode = Mode.TRACKING
        window.clear()
        calm = 0
        cooldown = 0
    }

    // Velocità angolare in gradi/s
    // Il giroscopio arriva in rad/s
    private fun rateDps(p: ImuPacket): Double {
        val a = p.raw ?: p.clean
        val gx = a[3].toDouble()
        val gy = a[4].toDouble()
        val gz = a[5].toDouble()
        return Math.toDegrees(sqrt(gx * gx + gy * gy + gz * gz))
    }
}