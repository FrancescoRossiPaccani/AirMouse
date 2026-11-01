import kotlin.math.abs
import kotlin.math.sign
import kotlin.math.sqrt

class TrackingModule(
    private val mouse: MouseDriver,
    var useRaw: Boolean = true,            // true: giroscopio grezzo, false: filtrato
    private val horizontalAxis: Int = 2,   // 0=x, 1=y, 2=z del giroscopio
    private val verticalAxis: Int = 1,
    private val horizontalSign: Double = -1.0,
    private val verticalSign: Double = -1.0,
    private val basePxPerDeg: Double = 18.0,   // sensibilità base
    private val deadzoneDps: Double = 0.7,
    // Curva a tre zone (gradi/s)
    private val slowDps: Double = 15.0,    // sotto: guadagno fine
    private val fastDps: Double = 60.0,    // sopra: guadagno veloce
    private val slowGain: Double = 0.5,
    private val fastGain: Double = 1.5,
    private val fastSlope: Double = 0.01,  // crescita del guadagno oltre fastDps (per dps)
    // Stima del bias
    private val stillDps: Double = 3.0,    // sotto: mano considerata ferma
    private val stillSamples: Int = 20,    // campioni fermi prima di aggiornare il bias
    private val historySize: Int = 10,
) {
    private var x = 0.0
    private var y = 0.0
    var sensitivity: Double = 1.0
    val position: Pair<Int, Int>
        get() = Math.round(x).toInt() to Math.round(y).toInt()
    private var prevTMs: Int? = null
    private var initialized = false
    private val history = ArrayDeque<Pair<Double, Double>>()

    // Bias del giroscopio per asse, in gradi/s
    private val bias = DoubleArray(3)
    private var stillCount = 0
    private var biasUpdates = 0

    fun onSample(p: ImuPacket) {
        val b = mouse.bounds
        syncWithRealMouse()

        val a = if (useRaw && p.raw != null) p.raw else p.clean
        val g = DoubleArray(3) { Math.toDegrees(a[3 + it].toDouble()) }
        updateBias(g)

        val dt = prevTMs?.let { ((p.tMs - it) / 1000.0).coerceIn(0.01, 0.15) } ?: 0.05
        val pxPerDeg = basePxPerDeg * sensitivity
        prevTMs = p.tMs

        val rateH = g[horizontalAxis] - bias[horizontalAxis]
        val rateV = g[verticalAxis] - bias[verticalAxis]

        val dx = horizontalSign * curve(rateH) * dt * pxPerDeg
        val dy = verticalSign * curve(rateV) * dt * pxPerDeg

        x = (x + dx).coerceIn(b.x.toDouble(), (b.x + b.width - 1).toDouble())
        y = (y + dy).coerceIn(b.y.toDouble(), (b.y + b.height - 1).toDouble())
        mouse.moveTo(Math.round(x).toInt(), Math.round(y).toInt())

        history.addLast(x to y)
        while (history.size > historySize) history.removeFirst()
    }

    // Aggiornamento del Bias
    private fun updateBias(g: DoubleArray) {
        val rate = sqrt((0..2).sumOf { (g[it] - bias[it]) * (g[it] - bias[it]) })
        if (rate < stillDps) {
            if (++stillCount >= stillSamples) {
                // all'inizio converge in fretta, poi segue lentamente le derive
                val alpha = if (biasUpdates < 40) 0.1 else 0.02
                for (i in 0..2) bias[i] += alpha * (g[i] - bias[i])
                biasUpdates++
            }
        } else {
            stillCount = 0
        }
    }

    private fun curve(rateDps: Double): Double {
        val m = abs(rateDps)
        if (m < deadzoneDps) return 0.0
        val gain = when {
            m < slowDps -> slowGain
            m < fastDps -> slowGain + (m - slowDps) / (fastDps - slowDps) * (fastGain - slowGain)
            else -> fastGain + (m - fastDps) * fastSlope
        }
        return sign(rateDps) * m * gain
    }

    fun rewind(samples: Int) {
        val idx = history.size - 1 - samples
        if (idx < 0) return
        val (rx, ry) = history[idx]
        x = rx; y = ry
        mouse.moveTo(Math.round(x).toInt(), Math.round(y).toInt())
        while (history.size > idx + 1) history.removeLast()
    }

    fun reset() {
        initialized = false
        prevTMs = null
        stillCount = 0
        history.clear()
    }

    fun center() {
        val b = mouse.bounds
        x = b.x + b.width / 2.0
        y = b.y + b.height * (0.5 - CENTER_UP_FRACTION)
        mouse.moveTo(Math.round(x).toInt(), Math.round(y).toInt())
        initialized = true
        history.clear()
    }

    private fun syncWithRealMouse() {
        val (mx, my) = mouse.position()
        if (!initialized || abs(mx - x) > 3 || abs(my - y) > 3) {
            x = mx.toDouble(); y = my.toDouble()
            initialized = true
        }
    }
}

private const val CENTER_UP_FRACTION = 0.15