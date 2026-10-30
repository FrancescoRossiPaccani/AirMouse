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
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class SessionManager(context: Context) {

    companion object {
        const val DPI_LEVELS = 6      // deve coincidere con AirMouse.SENSITIVITY sul PC
        const val DPI_DEFAULT = 2
    }

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

    private val _isPaused = MutableStateFlow(false)
    val isPaused: StateFlow<Boolean> = _isPaused.asStateFlow()

    private val _laser = MutableStateFlow(false)
    private val _dpi = MutableStateFlow(DPI_DEFAULT)
    val laser: StateFlow<Boolean> = _laser.asStateFlow()
    val dpi: StateFlow<Int> = _dpi.asStateFlow()

    @Volatile private var started = false
    @Volatile private var closed = false
    @Volatile private var autoReconnect = false
    @Volatile private var lastDeviceId: String? = null
    private var receiverRegistered = false

    // Coda ordinata per i comandi CTRL
    private val ctrlQueue = Channel<String>(Channel.UNLIMITED)
    private fun sendCtrl(msg: String) { ctrlQueue.trySend(msg) }

    private val streamer = SensorStreamer(appContext) { _streamStatus.value = it }

    val ble: BleClient = BleClient(
        context = appContext,
        onConnected = { device ->
            _isPaused.value = false
            lastDeviceId = device.id
            autoReconnect = true
            streamer.start(ble)
            syncState()
        },
        onLost = {
            _isPaused.value = false
            streamer.stop()
        },
    )

    init {
        // Svuota la coda dei comandi, ritentando se la scrittura BLE risulta occupata
        ioScope.launch {
            for (msg in ctrlQueue) {
                var tries = 0
                while (tries < 10 && !ble.sendCtrl(msg.toByteArray(Charsets.UTF_8))) {
                    delay(40)
                    tries++
                }
            }
        }
        // Se la connessione cade, si riconnette da sola all'ultimo dispositivo
        ioScope.launch {
            ble.devices.collect { list ->
                val id = lastDeviceId
                if (autoReconnect && id != null && !closed && ble.state.value is PairState.Searching) {
                    list.firstOrNull { it.id == id }?.let { ble.connect(it) }
                }
            }
        }
    }

    // comandi
    fun togglePause() = if (_isPaused.value) resume() else pause()

    fun pause() {
        if (_isPaused.value) return
        _isPaused.value = true
        streamer.pause()
        sendCtrl("pause")
    }

    fun resume() {
        if (!_isPaused.value) return
        _isPaused.value = false
        streamer.resume()
        sendCtrl("resume")
    }

    fun toggleLaser() {
        _laser.value = !_laser.value
        sendCtrl("mode:${if (_laser.value) "laser" else "mouse"}")
    }

    fun dpiUp() = setDpi(_dpi.value + 1)
    fun dpiDown() = setDpi(_dpi.value - 1)

    private fun setDpi(v: Int) {
        val n = v.coerceIn(0, DPI_LEVELS - 1)
        if (n != _dpi.value) {
            _dpi.value = n
            sendCtrl("dpi:$n")
        }
    }

    // Riallinea il PC allo stato dell'orologio
    private fun syncState() =
        sendCtrl("sync:${if (_laser.value) "laser" else "mouse"}:${_dpi.value}")

    //chiude la connessione e torna alla lista dei dispositivi
    fun disconnectToList() {
        autoReconnect = false
        _isPaused.value = false
        ioScope.launch {
            streamer.stop()
            ble.disconnect()   // invia "bye"
            ble.start()
        }
    }

    // BLE
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

    suspend fun shutdown() {
        if (closed) return
        autoReconnect = false
        closed = true
        streamer.stop()
        ble.disconnect()
        ble.stop()
        if (receiverRegistered) {
            runCatching { appContext.unregisterReceiver(btReceiver) }
            receiverRegistered = false
        }
    }

    fun release() {
        if (!closed) ioScope.launch { shutdown() }
    }
}