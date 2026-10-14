// --- START [10/10/2026] Pairing: Gestione Sessione di Rete, Wi-Fi e Ciclo di Vita dello Streaming ---
package com.example.airmouse_as.presentation

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class SessionManager(context: Context) {

    private val appContext = context.applicationContext
    private val cm = appContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private val ioScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _wifiReady = MutableStateFlow(false)
    private val _notice = MutableStateFlow<String?>("Looking for Wi-Fi…")
    private val _streamStatus = MutableStateFlow("")
    val wifiReady: StateFlow<Boolean> = _wifiReady.asStateFlow()
    val notice: StateFlow<String?> = _notice.asStateFlow()
    val streamStatus: StateFlow<String> = _streamStatus.asStateFlow()

    @Volatile private var network: Network? = null
    @Volatile private var closed = false
    private var callback: ConnectivityManager.NetworkCallback? = null

    private val streamer = SensorStreamer(appContext) { _streamStatus.value = it }

    val pairing = PairingClient(
        connectivityManager = cm,
        onConnected = { d -> network?.let { streamer.start(it, d.ip, d.udpPort) } },
        onLost = { streamer.stop() },
    )

    fun start() {
        if (callback != null || closed) return
        _notice.value = "Looking for Wi-Fi…"
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .build()

        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(n: Network) {
                network = n
                _notice.value = null
                _wifiReady.value = true
                pairing.start(n)
            }

            override fun onLost(n: Network) {
                if (network != n) return
                network = null
                streamer.stop()
                pairing.stop()
                _wifiReady.value = false
                _notice.value = "Wi-Fi lost"
            }

            override fun onUnavailable() {
                _notice.value = "Wi-Fi not available, retrying…"
                runCatching { cm.unregisterNetworkCallback(this) }
                callback = null
                ioScope.launch {
                    delay(2000)
                    start()
                }
            }
        }
        callback = cb
        cm.requestNetwork(request, cb, 10_000)
    }

    /** Graceful shutdown: stop streaming, tell the server "bye", release Wi-Fi. */
    suspend fun shutdown() {
        if (closed) return
        closed = true
        streamer.stop()
        pairing.disconnect()
        pairing.stop()
        callback?.let { runCatching { cm.unregisterNetworkCallback(it) } }
        callback = null
    }

    /** For onDestroy (not suspending). */
    fun release() {
        if (!closed) ioScope.launch { shutdown() }
    }
}
// --- END [10/10/2026] Pairing: Gestione Sessione di Rete, Wi-Fi e Ciclo di Vita dello Streaming ---
