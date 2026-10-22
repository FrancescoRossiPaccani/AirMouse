import kotlinx.coroutines.runBlocking

fun main() {
    val guard = GestureGuard()
    val tracking = TrackingModule()
    val recognizer = GestureRecognizer()

    runBlocking {
        println("In ascolto su UDP 127.0.0.1:9000 ...")
        bridgeEvents().collect { event ->
            when (event) {
                is BridgeEvent.Sample -> {
                    when (val decision = guard.update(event.packet)) {
                        GuardDecision.Tracking -> tracking.onSample(event.packet)
                        GuardDecision.Buffering -> {
                            // cursore congelato => non faccio nulla
                        }
                        is GuardDecision.GestureComplete -> recognizer.onGesture(decision.window)
                    }
                }
                is BridgeEvent.Control -> {
                    println("CONTROLLO: ${event.message}")
                    if (event.message == "bye") guard.reset()
                }
            }
        }
    }
}