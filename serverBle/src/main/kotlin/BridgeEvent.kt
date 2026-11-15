import java.net.DatagramPacket
import java.net.DatagramSocket
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn

// Formato (little-endian): int32 seq | int32 t_ms | 3 x float32 gyro
class ImuPacket(
    val seq: Int,
    val tMs: Int,
    val clean: FloatArray,   
    val raw: FloatArray?,    
)

sealed interface BridgeEvent {
    data class Sample(val packet: ImuPacket) : BridgeEvent
    data class Control(val message: String) : BridgeEvent
}

fun parsePacket(data: ByteArray, offset: Int, length: Int): ImuPacket? {
    if (length != 20) return null
    val b = ByteBuffer.wrap(data, offset, length).order(ByteOrder.LITTLE_ENDIAN)
    val seq = b.int
    val tMs = b.int
    val clean = FloatArray(9)
    clean[3] = b.float; clean[4] = b.float; clean[5] = b.float
    return ImuPacket(seq, tMs, clean, null)
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