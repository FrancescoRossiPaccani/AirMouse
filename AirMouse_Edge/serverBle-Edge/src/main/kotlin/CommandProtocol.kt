// Comandi Smartwatch -> PC
// Formato testuale: "M dx dy", "U dx dy", "C L|R|D", "D L|R 0|1".

interface MouseCommand {
    data class Move(val dx: Int, val dy: Int) : MouseCommand
    data class Undo(val dx: Int, val dy: Int) : MouseCommand
    data class Click(val button: MouseButton) : MouseCommand
    object DoubleClick : MouseCommand
    data class Drag(val button: MouseButton, val active: Boolean) : MouseCommand

    companion object {
        fun parse(text: String): MouseCommand? {
            val p = text.trim().split(" ")
            return when (p[0]) {
                "M" -> if (p.size == 3) Move(p[1].toIntOrNull() ?: return null, p[2].toIntOrNull() ?: return null) else null
                "U" -> if (p.size == 3) Undo(p[1].toIntOrNull() ?: return null, p[2].toIntOrNull() ?: return null) else null
                "C" -> when (p.getOrNull(1)) {
                    "L" -> Click(MouseButton.LEFT)
                    "R" -> Click(MouseButton.RIGHT)
                    "D" -> DoubleClick
                    else -> null
                }
                "D" -> Drag(button(p.getOrNull(1)) ?: return null, p.getOrNull(2) == "1")
                else -> null
            }
        }

        private fun button(code: String?) = when (code) {
            "L" -> MouseButton.LEFT
            "R" -> MouseButton.RIGHT
            else -> null
        }
    }
}
