package com.example.airmouse_as.presentation

interface MouseCommand {
    fun toPayload(): String

    data class Move(val dx: Int, val dy: Int) : MouseCommand {
        override fun toPayload() = "M $dx $dy"
    }

    data class Undo(val dx: Int, val dy: Int) : MouseCommand {
        override fun toPayload() = "U $dx $dy"
    }

    data class Click(val button: Button) : MouseCommand {
        override fun toPayload() = "C ${button.code}"
    }

    object DoubleClick : MouseCommand {
        override fun toPayload() = "C D"
    }

    data class Drag(val button: Button, val active: Boolean) : MouseCommand {
        override fun toPayload() = "D ${button.code} ${if (active) 1 else 0}"
    }

    enum class Button(val code: String) { LEFT("L"), RIGHT("R") }
}
