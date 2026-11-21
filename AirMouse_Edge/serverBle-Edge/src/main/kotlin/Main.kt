enum class PointerMode { MOUSE, LASER }

private val mouse = RobotMouseDriver()
private val laser = LaserOverlay()
private var pointerMode = PointerMode.MOUSE

fun main() {
    println("Air Mouse PC (Edge) | schermo ${mouse.bounds.width}x${mouse.bounds.height}")

    Runtime.getRuntime().addShutdownHook(Thread {
        mouse.releaseAll()
        laser.hide()
    })

    listenBridge { event ->
        when (event) {
            is BridgeEvent.Command -> when (val c = event.cmd) {
                is MouseCommand.Move -> {
                    val (x, y) = mouse.moveBy(c.dx, c.dy)
                    if (pointerMode == PointerMode.LASER) laser.moveTo(x, y)
                }
                is MouseCommand.Undo -> {
                    if (pointerMode == PointerMode.MOUSE) {
                        mouse.moveBy(-c.dx, -c.dy)   // annulla lo scatto iniziale del gesto
                    }
                }
                is MouseCommand.Click -> if (pointerMode == PointerMode.MOUSE) {
                    mouse.click(c.button)
                    println("Click ${c.button}")
                }
                MouseCommand.DoubleClick -> if (pointerMode == PointerMode.MOUSE) {
                    mouse.doubleClick()
                    println("Doppio click")
                }
                is MouseCommand.Drag -> if (pointerMode == PointerMode.MOUSE) {
                    if (c.active) mouse.press(c.button) else mouse.release(c.button)
                    println("Blocco ${c.button} ${if (c.active) "ON" else "OFF"}")
                }
            }
            is BridgeEvent.Control -> onControl(event.message)
        }
    }
}

private fun onControl(msg: String) {
    when {
        msg == "ping" -> { }
        msg == "bye" -> {
            println("Orologio disconnesso (bye)")
            mouse.releaseAll()
            setMode("mouse")
        }
        msg == "pause" -> {
            mouse.releaseAll()
            println("PAUSA")
        }
        msg == "resume" -> println("RIPRESO")
        msg.startsWith("mode:") -> setMode(msg.removePrefix("mode:"))
        msg.startsWith("dpi:") -> println("DPI impostato su: ${msg.removePrefix("dpi:")}")
        msg.startsWith("sync:") -> {
            val parts = msg.split(":")
            parts.getOrNull(1)?.let { setMode(it) }
            println("Sincronizzato con l'orologio (${msg})")
        }
        else -> println("CONTROLLO: $msg")
    }
}

private fun setMode(name: String) {
    val m = if (name == "laser") PointerMode.LASER else PointerMode.MOUSE
    if (m == pointerMode) return
    pointerMode = m
    mouse.releaseAll()
    if (m == PointerMode.LASER) {
        val (x, y) = mouse.position()
        laser.moveTo(x, y)
        laser.show()
    } else {
        laser.hide()
    }
    println("Modalità: $m")
}
