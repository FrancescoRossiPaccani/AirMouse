import kotlinx.coroutines.runBlocking

const val USE_RAW_GYRO = false   // true: giroscopio grezzo | false: giroscopio filtrato

fun main() {
    val mouse = RobotMouseDriver()
    val guard = GestureGuard()
    val tracking = TrackingModule(mouse, useRaw = USE_RAW_GYRO)
    val actions = GestureActions(mouse)
    val model = ForestModel.load("model/rf.json")
    val recognizer = GestureRecognizer(model)

    println("Tracking su: ${if (USE_RAW_GYRO) "GREZZO" else "FILTRATO"} | schermo ${mouse.bounds.width}x${mouse.bounds.height}")
    println("Classi modello: ${model.classes}")

    Runtime.getRuntime().addShutdownHook(Thread { actions.releaseAll() })

    runBlocking {
        bridgeEvents().collect { event ->
            when (event) {
                is BridgeEvent.Sample -> {
                    val before = guard.mode
                    val decision = guard.update(event.packet)

                    if (before == Mode.TRACKING && guard.mode == Mode.GESTURE) {
                        tracking.rewind(2)   // annulla i campioni dell'inizio dello scatto
                    }

                    when (decision) {
                        GuardDecision.Tracking -> tracking.onSample(event.packet)
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
                is BridgeEvent.Control -> {
                    println("CONTROLLO: ${event.message}")
                    if (event.message == "bye") {
                        guard.reset()
                        tracking.reset()
                        actions.releaseAll()
                    }
                }
            }
        }
    }
}