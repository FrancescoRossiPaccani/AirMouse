import java.awt.GraphicsEnvironment
import java.awt.MouseInfo
import java.awt.Robot
import java.awt.event.InputEvent

enum class MouseButton(val mask: Int) {
    LEFT(InputEvent.BUTTON1_DOWN_MASK),
    RIGHT(InputEvent.BUTTON3_DOWN_MASK),
}

class RobotMouseDriver {
    private val robot = Robot().apply { autoDelay = 0 }
    private val pressed = mutableSetOf<MouseButton>()

    val bounds = GraphicsEnvironment.getLocalGraphicsEnvironment()
        .screenDevices
        .map { it.defaultConfiguration.bounds }
        .reduce { a, b -> a.union(b) }

    fun position(): Pair<Int, Int> {
        val p = MouseInfo.getPointerInfo().location
        return p.x to p.y
    }

    fun moveBy(dx: Int, dy: Int): Pair<Int, Int> {
        val p = MouseInfo.getPointerInfo().location
        val nx = (p.x + dx).coerceIn(bounds.x, bounds.x + bounds.width - 1)
        val ny = (p.y + dy).coerceIn(bounds.y, bounds.y + bounds.height - 1)
        robot.mouseMove(nx, ny)
        return nx to ny
    }

    fun click(button: MouseButton) {
        robot.mousePress(button.mask)
        robot.mouseRelease(button.mask)
    }

    fun doubleClick() {
        click(MouseButton.LEFT)
        click(MouseButton.LEFT)
    }

    fun press(button: MouseButton) {
        if (pressed.add(button)) robot.mousePress(button.mask)
    }

    fun release(button: MouseButton) {
        if (pressed.remove(button)) robot.mouseRelease(button.mask)
    }

    fun releaseAll() = pressed.toList().forEach { release(it) }
}
