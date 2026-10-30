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

    @Volatile private var acc = FloatArray(3)
    @Volatile private var gyro = FloatArray(3)
    @Volatile private var mag = FloatArray(3)

    companion object {
        const val RATE_HZ = 20
        const val SEND_RAW = false
        // false: invia solo il grezzo (44 byte); il denoise per i gesti lo fa il PC (DENOISE_ON_PC = true)
        const val DENOISE_ON_WATCH = false
        private const val SENSOR_DELAY_US = 1_000_000 / RATE_HZ

        // Formato pacchetto (little endian):
        //   int32 seq | int32 t_ms | 9 x float32 clean (acc, gyro, mag) | [9 x float32 raw]
        private const val HEADER_BYTES = 8
        private const val CLEAN_BYTES = 9 * 4
        private const val RAW_BYTES = 9 * 4
        private const val SIZE_CLEAN = HEADER_BYTES + CLEAN_BYTES  // 44
        private const val SIZE_FULL = SIZE_CLEAN + RAW_BYTES       // 80
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
        listOf(
            Sensor.TYPE_ACCELEROMETER,
            Sensor.TYPE_GYROSCOPE,
            Sensor.TYPE_MAGNETIC_FIELD,
        ).forEach { type ->
            val sensor = sensorManager.getDefaultSensor(type)
            if (sensor != null) {
                sensorManager.registerListener(this, sensor, SENSOR_DELAY_US)
            } else {
                onStatus("Missing sensor: $type")
            }
        }
    }

    private fun startSending(ble: BleClient) {
        sendJob = scope.launch {
            try {
                val denoiser = if (DENOISE_ON_WATCH)
                    WaveletDenoiser(nChannels = 9, window = 64, delay = 4) else null

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

                    val raw = floatArrayOf(
                        acc[0], acc[1], acc[2],
                        gyro[0], gyro[1], gyro[2],
                        mag[0], mag[1], mag[2],
                    )
                    // senza denoiser "clean" è il grezzo stesso
                    val clean: FloatArray? = if (denoiser != null) denoiser.update(raw) else raw

                    if (clean == null) {
                        onStatus("Filling filter…")
                    } else {
                        val payload = ble.maxPayload
                        val withRaw = DENOISE_ON_WATCH && SEND_RAW && payload >= SIZE_FULL

                        if (payload < SIZE_CLEAN) {
                            onStatus("MTU too small ($payload B)")
                        } else {
                            val bytes = pack(
                                seq++,
                                SystemClock.elapsedRealtime().toInt(),
                                clean,
                                if (withRaw) raw else null,
                            )
                            if (ble.send(bytes)) {
                                onStatus("Streaming (BLE${if (withRaw) " + raw" else ""})")
                            } else {
                                onStatus("BLE busy")
                            }
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

    private fun pack(seq: Int, t: Int, clean: FloatArray, raw: FloatArray?): ByteArray {
        val bb = ByteBuffer.allocate(if (raw != null) SIZE_FULL else SIZE_CLEAN)
            .order(ByteOrder.LITTLE_ENDIAN)
        bb.putInt(seq)
        bb.putInt(t)
        for (v in clean) bb.putFloat(v)
        if (raw != null) for (v in raw) bb.putFloat(v)
        return bb.array()
    }

    override fun onSensorChanged(event: SensorEvent) {
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> acc = event.values.clone()
            Sensor.TYPE_GYROSCOPE -> gyro = event.values.clone()
            Sensor.TYPE_MAGNETIC_FIELD -> mag = event.values.clone()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}