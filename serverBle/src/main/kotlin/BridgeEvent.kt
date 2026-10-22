import java.net.DatagramPacket
import java.net.DatagramSocket
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn

class ImuPacket(
    val seq: Int,
    val tMs: Int,
    val clean: FloatArray,   // acc(3), gyro(3), mag(3) filtrati
    val raw: FloatArray?,    // acc(3), gyro(3), mag(3) grezzi (se presenti)
)

sealed interface BridgeEvent {
    data class Sample(val packet: ImuPacket) : BridgeEvent
    data class Control(val message: String) : BridgeEvent
}

fun parsePacket(data: ByteArray, offset: Int, length: Int): ImuPacket? {
    if (length < 44) return null
    val b = ByteBuffer.wrap(data, offset, length).order(ByteOrder.LITTLE_ENDIAN)
    val seq = b.int
    val tMs = b.int
    val clean = FloatArray(9) { b.float }
    val raw = if (length >= 80) FloatArray(9) { b.float } else null
    return ImuPacket(seq, tMs, clean, raw)
}

fun bridgeEvents(port: Int = 9000): Flow<BridgeEvent> = flow {
    DatagramSocket(port).use { socket ->
        val buf = ByteArray(256)
        val dp = DatagramPacket(buf, buf.size)
        while (true) {
            socket.receive(dp)
            when (buf[0].toInt()) {
                0 -> parsePacket(buf, 1, dp.length - 1)
                    ?.let { emit(BridgeEvent.Sample(it)) }
                1 -> emit(BridgeEvent.Control(String(buf, 1, dp.length - 1).trim().lowercase()))
            }
        }
    }
}.flowOn(Dispatchers.IO)