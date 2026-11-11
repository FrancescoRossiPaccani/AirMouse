fun main() {
    val mouse = RobotMouseDriver()
    println("Air Mouse PC (Edge) | schermo ${mouse.bounds.width}x${mouse.bounds.height}")

    Runtime.getRuntime().addShutdownHook(Thread {
        mouse.releaseAll()
    })

    listenBridge { event ->
        when (event) {
            is BridgeEvent.Command -> when (val c = event.cmd) {
                is MouseCommand.Move -> mouse.moveBy(c.dx, c.dy)
                is MouseCommand.Undo -> mouse.moveBy(-c.dx, -c.dy)   // annulla lo scatto iniziale del gesto
                is MouseCommand.Click -> {
                    mouse.click(c.button)
                    println("Click ${c.button}")
                }
                MouseCommand.DoubleClick -> {
                    mouse.doubleClick()
                    println("Doppio click")
                }
                is MouseCommand.Drag -> {
                    if (c.active) mouse.press(c.button) else mouse.release(c.button)
                    println("Blocco ${c.button} ${if (c.active) "ON" else "OFF"}")
                }
            }
            is BridgeEvent.Control -> {
                println("CONTROLLO: ${event.message}")
                if (event.message == "bye") mouse.releaseAll()
            }
        }
    }
}