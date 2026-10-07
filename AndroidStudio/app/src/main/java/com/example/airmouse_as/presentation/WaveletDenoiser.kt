package com.example.airmouse_as.presentation

import kotlin.math.ln
import kotlin.math.sqrt

/** Denoising wavelet (db4, hard threshold) su finestra scorrevole, un canale per asse. */
class WaveletDenoiser(
    private val nChannels: Int = 9,
    private val window: Int = 64,
    private val delay: Int = 4,
    private val levels: Int = 3,
    private val hard: Boolean = true,
) {
    private companion object {
        val LO = doubleArrayOf(
            0.23037781330885523, 0.7148465705525415, 0.6308807679295904,
            -0.02798376941698385, -0.18703481171888114, 0.030841381835986965,
            0.032883011666982945, -0.010597401784997278,
        )
        // filtro passa-alto: (-1)^j * LO[L-1-j]
        val HI = DoubleArray(LO.size) { j ->
            (if (j % 2 == 0) 1.0 else -1.0) * LO[LO.size - 1 - j]
        }
    }

    private val pad = window / 2
    private val n = window + 2 * pad // 128, divisibile per 2^levels
    private val buf = Array(nChannels) { DoubleArray(window) }
    private var filled = 0

    init {
        require(delay in 0 until window)
        require(n % (1 shl levels) == 0)
    }

    /** Ritorna i valori puliti (ritardati di [delay] campioni) o null finché la finestra non è piena. */
    fun update(sample: FloatArray): FloatArray? {
        for (c in 0 until nChannels) {
            val b = buf[c]
            System.arraycopy(b, 1, b, 0, window - 1)
            b[window - 1] = sample[c].toDouble()
        }
        if (filled < window) filled++
        if (filled < window) return null

        val idx = window - 1 - delay
        return FloatArray(nChannels) { c -> denoise(buf[c])[idx].toFloat() }
    }

    fun reset() {
        buf.forEach { it.fill(0.0) }
        filled = 0
    }

    private fun denoise(x: DoubleArray): DoubleArray {
        // estensione simmetrica (abcd|dcba) a sinistra e destra
        val p = DoubleArray(n) { i ->
            var k = i - pad
            if (k < 0) k = -k - 1
            if (k >= window) k = 2 * window - 1 - k
            x[k]
        }

        // decomposizione
        val details = ArrayList<DoubleArray>()
        var a = p
        repeat(levels) {
            val m = a.size / 2
            val ap = DoubleArray(m)
            val de = DoubleArray(m)
            for (k in 0 until m) {
                var sl = 0.0
                var sh = 0.0
                for (j in LO.indices) {
                    val v = a[(2 * k + j) % a.size]
                    sl += LO[j] * v
                    sh += HI[j] * v
                }
                ap[k] = sl
                de[k] = sh
            }
            details.add(de)
            a = ap
        }

        // soglia universale con sigma dal dettaglio più fine
        val sigma = median(details[0].map { kotlin.math.abs(it) }) / 0.6745
        val thr = sigma * sqrt(2.0 * ln(n.toDouble()))

        // coefficienti grandi = segnale (tenuti), piccoli = rumore (azzerati)
        for (d in details) {
            for (i in d.indices) {
                val v = d[i]
                val av = kotlin.math.abs(v)
                d[i] = if (hard) {
                    if (av >= thr) v else 0.0
                } else {
                    if (av > thr) Math.signum(v) * (av - thr) else 0.0
                }
            }
        }

        // ricostruzione (trasposta della decomposizione)
        var rec = a
        for (lvl in levels - 1 downTo 0) {
            val d = details[lvl]
            val out = DoubleArray(rec.size * 2)
            for (k in rec.indices) {
                for (j in LO.indices) {
                    out[(2 * k + j) % out.size] += LO[j] * rec[k] + HI[j] * d[k]
                }
            }
            rec = out
        }

        // parte centrale = finestra originale
        return rec.copyOfRange(pad, pad + window)
    }

    private fun median(v: List<Double>): Double {
        val s = v.sorted()
        val m = s.size / 2
        return if (s.size % 2 == 0) (s[m - 1] + s[m]) / 2 else s[m]
    }
}