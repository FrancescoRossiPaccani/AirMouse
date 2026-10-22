import kotlinx.coroutines.runBlocking

fun fmt(a: FloatArray, from: Int) =
    "%+.3f %+.3f %+.3f".format(a[from], a[from + 1], a[from + 2])

fun main() = runBlocking {
    println("In ascolto su UDP 127.0.0.1:9000 ...")
    bridgeEvents().collect { event ->
        when (event) {
            is BridgeEvent.Sample -> {
                val p = event.packet
                println(
                    "seq=${p.seq} t=${p.tMs}ms | " +
                            "acc[${fmt(p.clean, 0)}] gyro[${fmt(p.clean, 3)}] mag[${fmt(p.clean, 6)}]" +
                            (p.raw?.let { " | rawGyro[${fmt(it, 3)}]" } ?: "")
                )
            }
            is BridgeEvent.Control -> println("CONTROLLO: ${event.message}")
        }
    }
}