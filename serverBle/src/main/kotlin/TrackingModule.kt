import kotlin.math.abs
import kotlin.math.sign

class TrackingModule(
    private val mouse: MouseDriver,
    var useRaw: Boolean = false,        // true: giroscopio grezzo, false: filtrato
    private val horizontalAxis: Int = 2,   // 0=x, 1=y, 2=z del giroscopio (paper: yaw = Z)
    private val verticalAxis: Int = 1,     // paper: pitch = Y
    private val horizontalSign: Double = -1.0,
    private val verticalSign: Double = -1.0,
    private val pxPerDeg: Double = 18.0,   // sensibilità base
    private val deadzoneDps: Double = 2.0, // sotto: ignora (tremore e bias)
    private val accel: Double = 0.5,       // 0 = lineare; più alto = più veloce se muovi veloce
    private val historySize: Int = 10,
) {
    private var x = 0.0
    private var y = 0.0
    private var prevTMs: Int? = null
    private var initialized = false
    private val history = ArrayDeque<Pair<Double, Double>>()

    fun onSample(p: ImuPacket) {
        val b = mouse.bounds
        syncWithRealMouse()

        val a = if (useRaw && p.raw != null) p.raw else p.clean
        val dt = prevTMs?.let { ((p.tMs - it) / 1000.0).coerceIn(0.01, 0.15) } ?: 0.05
        prevTMs = p.tMs

        val dx = horizontalSign * curve(Math.toDegrees(a[3 + horizontalAxis].toDouble())) * dt * pxPerDeg
        val dy = verticalSign * curve(Math.toDegrees(a[3 + verticalAxis].toDouble())) * dt * pxPerDeg

        x = (x + dx).coerceIn(b.x.toDouble(), (b.x + b.width - 1).toDouble())
        y = (y + dy).coerceIn(b.y.toDouble(), (b.y + b.height - 1).toDouble())
        mouse.moveTo(x.toInt(), y.toInt())

        history.addLast(x to y)
        while (history.size > historySize) history.removeFirst()
    }

    // Deadzone morbida + leggera accelerazione
    private fun curve(rateDps: Double): Double {
        val m = abs(rateDps) - deadzoneDps
        if (m <= 0) return 0.0
        return sign(rateDps) * m * (1.0 + accel * m / 100.0)
    }

    // Se un gesto è iniziato, gli ultimi campioni erano già l'inizio dello scatto:
    // riporta il cursore a qualche campione fa.
    fun rewind(samples: Int) {
        val idx = history.size - 1 - samples
        if (idx < 0) return
        val (rx, ry) = history[idx]
        x = rx; y = ry
        mouse.moveTo(x.toInt(), y.toInt())
        while (history.size > idx + 1) history.removeLast()
    }

    fun reset() {
        initialized = false
        prevTMs = null
        history.clear()
    }

    // Se l'utente usa il mouse fisico, riparti da dove si trova il cursore davvero
    private fun syncWithRealMouse() {
        val (mx, my) = mouse.position()
        if (!initialized || abs(mx - x) > 3 || abs(my - y) > 3) {
            x = mx.toDouble(); y = my.toDouble()
            initialized = true
        }
    }
}