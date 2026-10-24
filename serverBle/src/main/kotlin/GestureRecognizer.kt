import kotlin.math.sqrt

class GestureRecognizer(
    private val model: ForestModel,
    private val minConfidence: Double = 0.50,
    private val activeDps: Double = 40.0,   // sopra questa velocità il campione fa parte del gesto
) {
    // Restituisce il gesto riconosciuto oppure null se la confidenza è troppo bassa
    fun classify(window: List<ImuPacket>): Prediction? {
        val axes = buildWindow(window)
        val pred = model.predict(GestureFeatures.extract(axes))
        return if (pred.confidence >= minConfidence) pred else null
    }

    fun onGesture(window: List<ImuPacket>) {
        val axes = buildWindow(window)
        val pred = model.predict(GestureFeatures.extract(axes))
        if (pred.confidence >= minConfidence) {
            println("GESTO: ${pred.label} (confidenza ${"%.0f".format(pred.confidence * 100)}%, ${window.size} campioni)")
        } else {
            println("Gesto non riconosciuto (migliore: ${pred.label} ${"%.0f".format(pred.confidence * 100)}%)")
        }
    }

    // Finestra di W campioni centrata sulla parte "attiva" del gesto, riempita con zeri ai bordi
    private fun buildWindow(window: List<ImuPacket>): Array<DoubleArray> {
        val rates = window.map { rateDps(it) }
        val first = rates.indexOfFirst { it > activeDps }
        val last = rates.indexOfLast { it > activeDps }
        val center =
            if (first < 0)
                window.size / 2
            else
                    (first + last) / 2
        val start = center - GestureFeatures.W / 2

        val out = Array(3) { DoubleArray(GestureFeatures.W) }
        for (i in 0 until GestureFeatures.W) {
            val src = start + i
            if (src in window.indices) {
                for (a in 0 until 3)
                    out[a][i] = window[src].clean[3 + a].toDouble()
            }
        }
        return out
    }

    private fun rateDps(p: ImuPacket): Double {
        val gx = p.clean[3].toDouble()
        val gy = p.clean[4].toDouble()
        val gz = p.clean[5].toDouble()
        return Math.toDegrees(sqrt(gx * gx + gy * gy + gz * gz))
    }
}