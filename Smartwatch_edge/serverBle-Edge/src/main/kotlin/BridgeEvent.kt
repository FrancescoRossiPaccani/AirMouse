import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress

interface BridgeEvent {
    data class Command(val cmd: MouseCommand) : BridgeEvent
    data class Control(val message: String) : BridgeEvent   // pause / resume / bye / dpi:.. / mode:..
}


fun listenBridge(port: Int = 9000, onEvent: (BridgeEvent) -> Unit) {
    DatagramSocket(InetSocketAddress(InetAddress.getLoopbackAddress(), port)).use { socket ->
        val buf = ByteArray(256)
        val dp = DatagramPacket(buf, buf.size)
        println("[SERVER] In ascolto su UDP 127.0.0.1:$port")
        while (true) {
            socket.receive(dp)
            if (dp.length < 1) continue
            val text = String(buf, 1, dp.length - 1, Charsets.UTF_8).trim()
            when (buf[0].toInt()) {
                0 -> MouseCommand.parse(text)?.let { onEvent(BridgeEvent.Command(it)) }
                    ?: println("[SERVER] Comando non riconosciuto: '$text'")
                1 -> onEvent(BridgeEvent.Control(text.lowercase()))
            }
        }
    }
}
