class GestureActions(private val mouse: MouseDriver) {
    private var leftLocked = false
    private var rightLocked = false

    fun execute(label: String): String = when (label) {
        "RLB" -> { mouse.click(MouseButton.LEFT); "click sinistro" }
        "RRB" -> { mouse.click(MouseButton.RIGHT); "click destro" }
        "UDB" -> { mouse.doubleClick(); "doppio click" }
        "MLB" -> {
            leftLocked = !leftLocked
            if (leftLocked) mouse.press(MouseButton.LEFT) else mouse.release(MouseButton.LEFT)
            if (leftLocked) "blocco sinistro ON" else "blocco sinistro OFF"
        }
        "MRB" -> {
            rightLocked = !rightLocked
            if (rightLocked) mouse.press(MouseButton.RIGHT) else mouse.release(MouseButton.RIGHT)
            if (rightLocked) "blocco destro ON" else "blocco destro OFF"
        }
        else -> "nessuna azione per $label"
    }

    fun releaseAll() {
        if (leftLocked) mouse.release(MouseButton.LEFT)
        if (rightLocked) mouse.release(MouseButton.RIGHT)
        leftLocked = false
        rightLocked = false
    }
}