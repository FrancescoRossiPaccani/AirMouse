package com.example.airmouse_as.presentation


class GestureRecognizer(
    private val model: ForestModel,
    private val minConfidence: Double = 0.50,
    private val activeDps: Double = 40.0,   // sopra questa velocità angolare il campione fa parte del gesto
) {
    
    fun classify(window: List<GyroSample>): Prediction? {
        val axes = buildWindow(window)
        val pred = model.predict(GestureFeatures.extract(axes))
        return if (pred.confidence >= minConfidence) pred else null
    }

    
    private fun buildWindow(window: List<GyroSample>): Array<DoubleArray> {
        val rates = window.map { it.rateDps() }
        val first = rates.indexOfFirst { it > activeDps }
        val last = rates.indexOfLast { it > activeDps }
        val center = if (first < 0) {
            window.size / 2
        } else {
            (first + last) / 2
        }
        val start = center - GestureFeatures.W / 2

        val out = Array(3) { DoubleArray(GestureFeatures.W) }
        for (i in 0 until GestureFeatures.W) {
            val src = start + i
            if (src in window.indices) {
                out[0][i] = window[src].gx.toDouble()
                out[1][i] = window[src].gy.toDouble()
                out[2][i] = window[src].gz.toDouble()
            }
        }
        return out
    }
}
