package com.example.airmouse_as.presentation

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class SessionManager(context: Context) {

    private val appContext = context.applicationContext
    private val adapter: BluetoothAdapter? =
        (appContext.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)?.adapter
    private val ioScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _bleReady = MutableStateFlow(false)
    private val _notice = MutableStateFlow<String?>("Looking for Bluetooth…")
    private val _streamStatus = MutableStateFlow("")
    val bleReady: StateFlow<Boolean> = _bleReady.asStateFlow()
    val notice: StateFlow<String?> = _notice.asStateFlow()
    val streamStatus: StateFlow<String> = _streamStatus.asStateFlow()

    @Volatile private var started = false   // true solo dopo la concessione dei permessi
    @Volatile private var closed = false
    private var receiverRegistered = false

    private val streamer = SensorStreamer(appContext) { _streamStatus.value = it }

    val ble: BleClient = BleClient(
        context = appContext,
        onConnected = { streamer.start(ble) },
        onLost = { streamer.stop() },
    )

    // Reagisce all'accensione / spegnimento del Bluetooth mentre l'app è aperta.
    private val btReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, intent: Intent) {
            if (intent.action != BluetoothAdapter.ACTION_STATE_CHANGED) return
            when (intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR)) {
                BluetoothAdapter.STATE_ON -> applyBluetoothState()
                BluetoothAdapter.STATE_TURNING_OFF,
                BluetoothAdapter.STATE_OFF -> bluetoothOff()
            }
        }
    }

    /** Da chiamare dopo che i permessi BLE sono stati concessi. */
    fun start() {
        if (closed) return
        started = true
        if (!receiverRegistered) {
            ContextCompat.registerReceiver(
                appContext,
                btReceiver,
                IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED),
                ContextCompat.RECEIVER_NOT_EXPORTED,
            )
            receiverRegistered = true
        }
        applyBluetoothState()
    }

    /** Chiamata da MainActivity se l'utente nega i permessi. */
    fun onPermissionDenied() {
        _bleReady.value = false
        _notice.value = "Bluetooth permission required"
    }

    private fun applyBluetoothState() {
        if (!started || closed) return
        val a = adapter
        when {
            a == null -> {
                _bleReady.value = false
                _notice.value = "Bluetooth not available"
            }
            !a.isEnabled -> bluetoothOff()
            else -> if (!_bleReady.value) {
                _notice.value = null
                _bleReady.value = true
                ble.start()
            }
        }
    }

    private fun bluetoothOff() {
        if (closed) return
        streamer.stop()
        ble.stop()
        _bleReady.value = false
        _notice.value = "Bluetooth off"
    }

    /** Graceful shutdown: stop streaming, tell the PC "bye", release Bluetooth. */
    suspend fun shutdown() {
        if (closed) return
        closed = true
        streamer.stop()
        ble.disconnect()
        ble.stop()
        if (receiverRegistered) {
            runCatching { appContext.unregisterReceiver(btReceiver) }
            receiverRegistered = false
        }
    }

    /** For onDestroy (not suspending). */
    fun release() {
        if (!closed) ioScope.launch { shutdown() }
    }
}