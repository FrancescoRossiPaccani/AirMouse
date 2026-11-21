import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking


const val USE_RAW_GYRO = true   // tracking: true grezzo | false filtrato
val SENSITIVITY = doubleArrayOf(0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
const val DEFAULT_SENSITIVITY = 2
const val TIMEOUT_STREAMING_MS = 1500L
const val TIMEOUT_PAUSED_MS = 5000L

enum class PointerMode { MOUSE, LASER }


private val mouse = RobotMouseDriver()
private val guard = GestureGuard()
private val tracking = TrackingModule(mouse, useRaw = USE_RAW_GYRO)
private val actions = GestureActions(mouse)
private val model = ForestModel.load("model/rf.json")
private val recognizer = GestureRecognizer(model)
private val laser = LaserOverlay()

//Variabili di stato
private var paused = false
private var pointerMode = PointerMode.MOUSE
private var connected = false
private var lastSignalNs = 0L
private var lastSeq = -1

fun main() {
    setSensitivity(DEFAULT_SENSITIVITY)
    tracking.center()

    println("Tracking su: ${if (USE_RAW_GYRO) "GREZZO" else "FILTRATO"}")
    println("Schermo ${mouse.bounds.width}x${mouse.bounds.height} | classi modello: ${model.classes}")

    Runtime.getRuntime().addShutdownHook(Thread { shutdown() })

    runBlocking {
        launch {
            while (true) {
                delay(500)
                checkConnection()
            }
        }
        bridgeEvents().collect { event ->
            when (event) {
                is BridgeEvent.Sample -> onSample(event.packet)
                is BridgeEvent.Control -> onControl(event.message)
            }
        }
    }
}


private fun onSample(p: ImuPacket) {
    touch()
    if (p.seq < lastSeq) {
        println("Orologio riavviato")
        resetSession()
        touch()
    }
    lastSeq = p.seq
    if (paused) return

    if (pointerMode == PointerMode.LASER) {
        // solo tracking, gesti ignorati
        tracking.onSample(p)
        val (x, y) = tracking.position
        laser.moveTo(x, y)
        return
    }

    val before = guard.mode
    val decision = guard.update(p)
    if (before == Mode.TRACKING && guard.mode == Mode.GESTURE) tracking.rewind(2)

    when (decision) {
        GuardDecision.Tracking -> tracking.onSample(p)
        GuardDecision.Buffering -> { }
        is GuardDecision.GestureComplete -> {
            val pred = recognizer.classify(decision.window)
            if (pred != null) {
                println("GESTO ${pred.label} (${"%.0f".format(pred.confidence * 100)}%) -> ${actions.execute(pred.label)}")
            } else {
                println("Gesto non riconosciuto")
            }
        }
    }
}

private fun onControl(msg: String) {
    touch()
    when {
        msg == "ping" -> { }
        msg == "bye" -> {
            println("Orologio disconnesso (bye)")
            resetSession()
            connected = false
            tracking.center()
        }
        msg == "pause" -> pause()
        msg == "resume" -> resume()
        msg.startsWith("mode:") -> setMode(msg.removePrefix("mode:"))
        msg.startsWith("dpi:") -> msg.removePrefix("dpi:").toIntOrNull()?.let { setSensitivity(it) }
        msg.startsWith("sync:") -> {
            val parts = msg.split(":")
            paused = false
            parts.getOrNull(1)?.let { setMode(it) }
            parts.getOrNull(2)?.toIntOrNull()?.let { setSensitivity(it) }
            println("Sincronizzato con l'orologio")
        }
        else -> println("Comando sconosciuto: $msg")
    }
}

private fun checkConnection() {
    if (!connected) return
    val silentMs = (System.nanoTime() - lastSignalNs) / 1_000_000
    val limit = if (paused) TIMEOUT_PAUSED_MS else TIMEOUT_STREAMING_MS
    if (silentMs > limit) {
        println("Connessione persa (nessun dato da $silentMs ms)")
        resetSession()
        connected = false
    }
}

private fun shutdown() {
    actions.releaseAll()
    laser.hide()
}

private fun touch() {
    lastSignalNs = System.nanoTime()
    if (!connected) {
        connected = true
        println("Orologio connesso")
    }
}

private fun pause() {
    paused = true
    actions.releaseAll()
    guard.reset()
    println("PAUSA")
}

private fun resume() {
    paused = false
    tracking.reset()
    guard.reset()
    println("RIPRESO")
}

private fun setMode(name: String) {
    val m = if (name == "laser") PointerMode.LASER else PointerMode.MOUSE
    if (m == pointerMode) return
    pointerMode = m
    guard.reset()
    actions.releaseAll()
    if (m == PointerMode.LASER) laser.show() else laser.hide()
    println("Modalità: $m")
}

private fun setSensitivity(i: Int) {
    val idx = i.coerceIn(0, SENSITIVITY.size - 1)
    tracking.sensitivity = SENSITIVITY[idx]
    println("Sensibilità: livello ${idx + 1}/${SENSITIVITY.size} (x${SENSITIVITY[idx]})")
}

private fun resetSession() {
    paused = false
    lastSeq = -1
    guard.reset()
    tracking.reset()
    actions.releaseAll()
}