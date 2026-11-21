package com.example.airmouse_as.presentation

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.SystemClock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.nio.ByteBuffer
import java.nio.ByteOrder

class SensorStreamer(
    context: Context,
    private val onStatus: (String) -> Unit,
) : SensorEventListener {

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var sendJob: Job? = null

    @Volatile private var gyro = FloatArray(3)

    companion object {
        const val RATE_HZ = 20
        private const val SENSOR_DELAY_US = 1_000_000 / RATE_HZ

        // Formato pacchetto (little endian), solo giroscopio: int32 seq | int32 t_ms | 3 x float32 gyro
        private const val HEADER_BYTES = 8
        private const val GYRO_BYTES = 3 * 4
        private const val PACKET_SIZE = HEADER_BYTES + GYRO_BYTES  // 20
    }

    @Volatile var isPaused: Boolean = false
        private set

    fun pause() {
        if (isPaused) return
        isPaused = true
        onStatus("PAUSA (Streaming Sospeso)")
    }

    fun resume() {
        if (!isPaused) return
        isPaused = false
        onStatus("Ripresa...")
    }

    fun start(ble: BleClient) {
        stop()
        startSensors()
        startSending(ble)
    }

    fun stop() {
        isPaused = false
        sensorManager.unregisterListener(this)
        sendJob?.cancel()
        sendJob = null
        onStatus("Stopped")
    }

    private fun startSensors() {
        val sensor = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        if (sensor != null) {
            sensorManager.registerListener(this, sensor, SENSOR_DELAY_US)
        } else {
            onStatus("Missing sensor: gyroscope")
        }
    }

    private fun startSending(ble: BleClient) {
        sendJob = scope.launch {
            try {
                val periodMs = 1000L / RATE_HZ
                var seq = 0
                var next = SystemClock.elapsedRealtime()
                var lastPing = 0L

                while (isActive) {
                    if (isPaused) {
                        val now = SystemClock.elapsedRealtime()
                        if (now - lastPing >= 2000) {   // heartbeat
                            ble.sendCtrl("ping".toByteArray(Charsets.UTF_8))
                            lastPing = now
                        }
                        delay(100)
                        next = SystemClock.elapsedRealtime()
                        continue
                    }

                    val payload = ble.maxPayload
                    if (payload < PACKET_SIZE) {
                        onStatus("MTU too small ($payload B)")
                    } else {
                        val g = gyro   // @Volatile: letto una volta sola
                        val bytes = pack(seq++, SystemClock.elapsedRealtime().toInt(), g)
                        if (ble.send(bytes)) {
                            onStatus("Streaming (BLE, gyro)")
                        } else {
                            onStatus("BLE busy")
                        }
                    }

                    next += periodMs
                    val wait = next - SystemClock.elapsedRealtime()
                    if (wait > 0) delay(wait) else next = SystemClock.elapsedRealtime()
                }
            } catch (e: Exception) {
                if (isActive) onStatus("Error: ${e.message}")
            }
        }
    }

    private fun pack(seq: Int, t: Int, g: FloatArray): ByteArray =
        ByteBuffer.allocate(PACKET_SIZE).order(ByteOrder.LITTLE_ENDIAN)
            .putInt(seq).putInt(t)
            .putFloat(g[0]).putFloat(g[1]).putFloat(g[2])
            .array()

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type == Sensor.TYPE_GYROSCOPE) gyro = event.values.clone()
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}