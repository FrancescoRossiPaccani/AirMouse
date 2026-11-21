import java.awt.GraphicsEnvironment
import java.awt.MouseInfo
import java.awt.Rectangle
import java.awt.Robot
import java.awt.event.InputEvent

enum class MouseButton(val mask: Int) {
    LEFT(InputEvent.BUTTON1_DOWN_MASK),
    RIGHT(InputEvent.BUTTON3_DOWN_MASK),
}

interface MouseDriver {
    val bounds: Rectangle
    fun position(): Pair<Int, Int>
    fun moveTo(x: Int, y: Int)
    fun click(button: MouseButton)
    fun doubleClick()
    fun press(button: MouseButton)
    fun release(button: MouseButton)
}

class RobotMouseDriver : MouseDriver {
    private val robot = Robot().apply { autoDelay = 0 }

    override val bounds: Rectangle = GraphicsEnvironment.getLocalGraphicsEnvironment()
        .screenDevices
        .map { it.defaultConfiguration.bounds }
        .reduce { a, b -> a.union(b) }

    override fun position(): Pair<Int, Int> {
        val p = MouseInfo.getPointerInfo().location
        return p.x to p.y
    }

    override fun moveTo(x: Int, y: Int) = robot.mouseMove(x, y)

    override fun click(button: MouseButton) {
        robot.mousePress(button.mask)
        robot.mouseRelease(button.mask)
    }

    override fun doubleClick() {
        click(MouseButton.LEFT)
        click(MouseButton.LEFT)
    }

    override fun press(button: MouseButton) = robot.mousePress(button.mask)
    override fun release(button: MouseButton) = robot.mouseRelease(button.mask)
}