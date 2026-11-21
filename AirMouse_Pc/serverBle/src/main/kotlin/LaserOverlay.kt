import java.awt.Color
import java.awt.Cursor
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.Point
import java.awt.RenderingHints
import java.awt.Toolkit
import java.awt.image.BufferedImage
import javax.swing.JPanel
import javax.swing.JWindow
import javax.swing.SwingUtilities

class LaserOverlay(private val radius: Int = 9) {
    private val diameter = radius * 2 + 12
    private var window: JWindow? = null

    private fun create(): JWindow {
        val w = JWindow()
        try {
            w.background = Color(0, 0, 0, 0)       // trasparenza per pixel
        } catch (e: Exception) {
            println("Trasparenza non supportata($e)")
        }
        w.isAlwaysOnTop = true
        w.focusableWindowState = false              // non ruba il focus
        w.cursor = Toolkit.getDefaultToolkit().createCustomCursor(
            BufferedImage(16, 16, BufferedImage.TYPE_INT_ARGB), Point(0, 0), "blank"
        )
        w.contentPane = object : JPanel() {
            init { isOpaque = false }
            override fun paintComponent(g: Graphics) {
                val g2 = g as Graphics2D
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
                val c = diameter / 2
                val glow = radius + 5
                g2.color = Color(255, 0, 0, 70)
                g2.fillOval(c - glow, c - glow, glow * 2, glow * 2)
                g2.color = Color(255, 30, 30, 235)
                g2.fillOval(c - radius, c - radius, radius * 2, radius * 2)
            }
        }
        w.setSize(diameter, diameter)
        return w
    }

    fun show() = SwingUtilities.invokeLater {
        val w = window ?: create().also { window = it }
        w.isVisible = true
    }

    fun hide() = SwingUtilities.invokeLater { window?.isVisible = false }

    fun moveTo(x: Int, y: Int) = SwingUtilities.invokeLater {
        window?.setLocation(x - diameter / 2, y - diameter / 2)
    }
}