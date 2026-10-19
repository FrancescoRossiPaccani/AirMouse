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

    // ultimi valori letti (sostituiti per intero ad ogni evento)
    @Volatile private var acc = FloatArray(3)
    @Volatile private var gyro = FloatArray(3)
    @Volatile private var mag = FloatArray(3)

    companion object {
        const val RATE_HZ = 20
        const val SEND_RAW = true // metti false quando non ti serve più il confronto
        private const val SENSOR_DELAY_US = 1_000_000 / RATE_HZ // 50 ms

        // Formato pacchetto (little endian):
        //   int32 seq | int32 t_ms | 9 x float32 clean (acc, gyro, mag) | [9 x float32 raw]
        private const val HEADER_BYTES = 8
        private const val CLEAN_BYTES = 9 * 4                      // 36
        private const val RAW_BYTES = 9 * 4                        // 36
        private const val SIZE_CLEAN = HEADER_BYTES + CLEAN_BYTES  // 44
        private const val SIZE_FULL = SIZE_CLEAN + RAW_BYTES       // 80
    }

    // --- START [18/10/2026] Step 9: Controllo dello streaming con modalità Pausa / Ripresa ---
    @Volatile var isPaused: Boolean = false
        private set

    fun pause(ble: BleClient? = null) {
        if (isPaused) return
        isPaused = true
        ble?.sendCtrl("pause".toByteArray(Charsets.UTF_8))
        onStatus("PAUSA (Streaming Sospeso)")
    }

    fun resume(ble: BleClient? = null) {
        if (!isPaused) return
        isPaused = false
        ble?.sendCtrl("resume".toByteArray(Charsets.UTF_8))
        onStatus("Ripresa...")
    }
    // --- END [18/10/2026] Step 9: Controllo dello streaming con modalità Pausa / Ripresa ---

    fun start(ble: BleClient) {
        stop()
        startSensors()
        startSending(ble)
    }

    fun stop() {
        // --- START [18/10/2026] Step 9: Reset stato pausa allo stop ---
        isPaused = false
        // --- END [18/10/2026] Step 9: Reset stato pausa allo stop ---
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
                val denoiser = WaveletDenoiser(nChannels = 9, window = 64, delay = 4)

                val periodMs = 1000L / RATE_HZ
                var seq = 0
                var next = SystemClock.elapsedRealtime()

                while (isActive) {
                    // --- START [18/10/2026] Step 9: Sospensione campionamento e invio in pausa ---
                    if (isPaused) {
                        delay(100)
                        next = SystemClock.elapsedRealtime()
                        continue
                    }
                    // --- END [18/10/2026] Step 9: Sospensione campionamento e invio in pausa ---

                    val raw = floatArrayOf(
                        acc[0], acc[1], acc[2],
                        gyro[0], gyro[1], gyro[2],
                        mag[0], mag[1], mag[2],
                    )
                    val clean = denoiser.update(raw)

                    if (clean == null) {
                        onStatus("Filling filter…")
                    } else {
                        // il raw viene incluso solo se l'MTU negoziato lo permette
                        val payload = ble.maxPayload
                        val withRaw = SEND_RAW && payload >= SIZE_FULL

                        if (payload < SIZE_CLEAN) {
                            onStatus("MTU too small ($payload B)")
                        } else {
                            val bytes = pack(seq++, SystemClock.elapsedRealtime().toInt(), clean, if (withRaw) raw else null)
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