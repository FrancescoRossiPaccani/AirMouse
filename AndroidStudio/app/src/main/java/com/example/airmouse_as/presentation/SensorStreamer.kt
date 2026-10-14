package com.example.airmouse_as.presentation

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.SystemClock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

class SensorStreamer(
    context: Context,
    private val host: String,
    private val port: Int,
    private val onStatus: (String) -> Unit,
) : SensorEventListener {

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val connectivityManager =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var sendJob: Job? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    private val denoiser = WaveletDenoiser(nChannels = 9, window = 64, delay = 4)

    // ultimi valori letti (sostituiti per intero ad ogni evento)
    @Volatile private var acc = FloatArray(3)
    @Volatile private var gyro = FloatArray(3)
    @Volatile private var mag = FloatArray(3)

    companion object {
        const val RATE_HZ = 20
        const val SEND_RAW = true // metti false quando non ti serve più il confronto
        private const val SENSOR_DELAY_US = 1_000_000 / RATE_HZ // 50 ms
    }

    fun start() {
        if (networkCallback != null) return
        onStatus("Cerco Wi-Fi...")

        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .build()

        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                startSensors()
                startSending(network)
            }

            override fun onLost(network: Network) {
                onStatus("Wi-Fi perso")
            }

            override fun onUnavailable() {
                onStatus("Wi-Fi non disponibile")
                stop()
            }
        }
        networkCallback = cb
        connectivityManager.requestNetwork(request, cb, 10_000)
    }

    fun stop() {
        sensorManager.unregisterListener(this)
        sendJob?.cancel()
        sendJob = null
        networkCallback?.let {
            try { connectivityManager.unregisterNetworkCallback(it) } catch (_: Exception) {}
        }
        networkCallback = null
        onStatus("Fermo")
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
                onStatus("Sensore mancante: $type")
            }
        }
    }

    private fun startSending(network: Network) {
        sendJob?.cancel()
        sendJob = scope.launch {
            var socket: DatagramSocket? = null
            try {
                // riparte con la finestra del filtro vuota
                denoiser.reset()

                socket = DatagramSocket()
                network.bindSocket(socket) // forza il traffico sul Wi-Fi
                val address = InetAddress.getByName(host)
                val periodMs = 1000L / RATE_HZ
                var seq = 0L
                var next = SystemClock.elapsedRealtime()

                while (isActive) {
                    val raw = floatArrayOf(
                        acc[0], acc[1], acc[2],
                        gyro[0], gyro[1], gyro[2],
                        mag[0], mag[1], mag[2],
                    )
                    val clean = denoiser.update(raw)

                    if (clean == null) {
                        onStatus("Riempimento filtro...")
                    } else {
                        val json = JSONObject().apply {
                            put("seq", seq++)
                            put("t", SystemClock.elapsedRealtime())
                            put("acc", JSONArray(clean.copyOfRange(0, 3).map { it.toDouble() }))
                            put("gyro", JSONArray(clean.copyOfRange(3, 6).map { it.toDouble() }))
                            put("mag", JSONArray(clean.copyOfRange(6, 9).map { it.toDouble() }))
                            if (SEND_RAW) put("raw", JSONArray(raw.map { it.toDouble() }))
                        }
                        val bytes = json.toString().toByteArray(Charsets.UTF_8)
                        socket.send(DatagramPacket(bytes, bytes.size, address, port))
                        onStatus("Invio a $host:$port")
                    }

                    next += periodMs
                    val wait = next - SystemClock.elapsedRealtime()
                    if (wait > 0) delay(wait) else next = SystemClock.elapsedRealtime()
                }
            } catch (e: Exception) {
                onStatus("Errore: ${e.message}")
            } finally {
                socket?.close()
            }
        }
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