import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

// Porting di feats() / axis_feats() di train.py. Input: 3 assi (gx, gy, gz) x W campioni.
object GestureFeatures {
    const val W = 32
    const val N_CANDIDATES = 165   // 3 assi x (20 tempo + 14 freq + 20 tempo-freq) + 3 correlazioni

    // Filtri db2
    private val DEC_LO = doubleArrayOf(
        -0.12940952255126037, 0.2241438680420134, 0.8365163037378079, 0.48296291314453414
    )
    private val DEC_HI = doubleArrayOf(
        -0.48296291314453414, 0.8365163037378079, -0.2241438680420134, -0.12940952255126037
    )

    fun extract(axes: Array<DoubleArray>): DoubleArray {
        require(axes.size == 3 && axes.all { it.size == W }) { "Serve una finestra 3 x $W" }
        val f = ArrayList<Double>(N_CANDIDATES)
        for (a in 0 until 3)
            f += axisFeats(axes[a])
        for ((a, b) in listOf(0 to 1, 0 to 2, 1 to 2))
            f += corr(axes[a], axes[b])
        check(f.size == N_CANDIDATES) { "Feature attese $N_CANDIDATES, ottenute ${f.size}" }
        return f.toDoubleArray()
    }

    private fun corr(a: DoubleArray, b: DoubleArray): Double {
        val ma = a.average()
        val mb = b.average()
        val sa = sqrt(a.sumOf { (it - ma) * (it - ma) } / a.size)
        val sb = sqrt(b.sumOf { (it - mb) * (it - mb) } / b.size)
        if (sa < 1e-9 || sb < 1e-9)
            return 0.0
        var s = 0.0
        for (i in a.indices)
            s += (a[i] - ma) * (b[i] - mb)
        return (s / a.size) / (sa * sb)
    }

    private fun axisFeats(x: DoubleArray): List<Double> {
        val n = x.size
        val mean = x.average()
        val d = DoubleArray(n) { x[it] - mean }
        val den = d.sumOf { it * it }
        val variance = den / n
        val std = sqrt(variance)

        var skew = 0.0
        var kurt = 0.0
        if (std >= 1e-9) {
            skew = d.sumOf { (it / std).pow(3) } / n
            kurt = d.sumOf { (it / std).pow(4) } / n
        }
        val energy = x.sumOf { it * it }

        var zcr = 0
        for (i in 1 until n) if ((d[i] >= 0) != (d[i - 1] >= 0)) zcr++

        val hi = mean + 0.5 * std
        val lo = mean - 0.5 * std
        var nPeaks = 0
        var nValleys = 0
        var firstPeak = -1
        var firstValley = -1
        for (i in 1 until n - 1) {
            if (x[i] > x[i - 1] && x[i] > x[i + 1] && x[i] > hi) {
                if (firstPeak < 0) firstPeak = i
                nPeaks++
            }
            if (x[i] < x[i - 1] && x[i] < x[i + 1] && x[i] < lo) {
                if (firstValley < 0) firstValley = i
                nValleys++
            }
        }
        val order = if (nPeaks > 0 && nValleys > 0) (if (firstPeak < firstValley) 1.0 else -1.0) else 0.0

        var ar1 = 0.0
        var ar2 = 0.0
        if (den > 1e-18) {
            for (i in 0 until n - 1)
                ar1 += d[i] * d[i + 1]
            for (i in 0 until n - 2)
                ar2 += d[i] * d[i + 2]
            ar1 /= den
            ar2 /= den
        }

        var iMax = 0
        var iMin = 0
        for (i in 1 until n) {
            if (x[i] > x[iMax])
                iMax = i
            if (x[i] < x[iMin])
                iMin = i
        }

        val time = listOf(
            mean, variance, std, x[iMax], x[iMin], x[iMax] - x[iMin], skew, kurt,
            sqrt(energy / n), energy, d.sumOf { abs(it) } / n, median(x),
            zcr.toDouble(), nPeaks.toDouble(), nValleys.toDouble(), order,
            iMax.toDouble() / (n - 1), iMin.toDouble() / (n - 1), ar1, ar2,
        )

        // Frequenza: modulo dell'rfft (DFT diretta, n = 32 e' piccolo)
        val bins = n / 2 + 1
        val mag = DoubleArray(bins) { k ->
            var re = 0.0
            var im = 0.0
            for (t in 0 until n) {
                val ang = 2.0 * PI * k * t / n
                re += x[t] * cos(ang)
                im -= x[t] * sin(ang)
            }
            hypot(re, im)
        }
        val sp = mag.copyOfRange(1, bins)
        val spMean = sp.average()
        var iDom = 0
        for (i in 1 until sp.size)
            if (sp[i] > sp[iDom])
                iDom = i
        val freq = ArrayList<Double>()
        for (k in 0 until 10)
            freq += mag[k]
        freq += sp.sumOf { it * it }
        freq += median(sp)
        freq += sp.sumOf { (it - spMean) * (it - spMean) } / sp.size
        freq += (iDom + 1).toDouble()

        // Tempo-frequenza: wavedec db2 livello 3 -> [cA3, cD3, cD2, cD1]
        var approx = x
        val details = ArrayList<DoubleArray>()
        repeat(3) {
            val (lowPass, highPass) = dwt(approx)
            details += highPass
            approx = lowPass
        }
        val coeffs = listOf(approx) + details.reversed()
        val tf = ArrayList<Double>()
        for (c in coeffs) {
            val m = c.average()
            tf += sqrt(c.sumOf { it * it } / c.size)
            tf += c.sumOf { (it - m) * (it - m) } / c.size
            tf += c.max()
            tf += c.min()
            tf += m
        }
        return time + freq + tf
    }

    private fun median(v: DoubleArray): Double {
        val s = v.sortedArray()
        val n = s.size
        return if (n % 2 == 1) s[n / 2] else (s[n / 2 - 1] + s[n / 2]) / 2.0
    }

    // Un livello di DWT con estensione simmetrica (mode='symmetric')
    private fun dwt(x: DoubleArray): Pair<DoubleArray, DoubleArray> {
        val n = x.size
        fun ext(i: Int): Double = when {
            i < 0 -> x[-i - 1]
            i >= n -> x[2 * n - 1 - i]
            else -> x[i]
        }
        val outLen = (n + DEC_LO.size - 1) / 2
        val lo = DoubleArray(outLen)
        val hi = DoubleArray(outLen)
        for (i in 0 until outLen) {
            val m = 2 * i + 1
            var l = 0.0
            var h = 0.0
            for (j in DEC_LO.indices) {
                val v = ext(m - j)
                l += DEC_LO[j] * v
                h += DEC_HI[j] * v
            }
            lo[i] = l
            hi[i] = h
        }
        return lo to hi
    }
}