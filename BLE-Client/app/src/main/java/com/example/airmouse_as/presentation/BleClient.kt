package com.example.airmouse_as.presentation

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.BluetoothStatusCodes
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.ParcelUuid
import android.os.SystemClock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.UUID

data class Device(
    val id: String,          // indirizzo MAC
    val name: String,
    val rssi: Int,
    val bt: BluetoothDevice,
    val lastSeen: Long = 0L,
)

sealed interface PairState {
    object Searching : PairState
    data class Connecting(val device: Device) : PairState
    data class Connected(val device: Device) : PairState
}

/**
 * Scan BLE + connessione GATT verso il PC (che fa da GATT server)
 * Il watch è il central: scansiona il service UUID, si connette e scrive i pacchetti
 * dei sensori sulla characteristic DATA con Write Without Response.
 */
@SuppressLint("MissingPermission") // i permessi vengono chiesti in MainActivity
class BleClient(
    private val context: Context,
    private val onConnected: (Device) -> Unit,
    private val onLost: () -> Unit,
) {
    companion object {
        // Devono essere identici sul PC.
        val SERVICE_UUID: UUID = UUID.fromString("7a1c0001-4f5e-4b8a-9d3c-2e6f1a0b5c01")
        val DATA_UUID: UUID = UUID.fromString("7a1c0002-4f5e-4b8a-9d3c-2e6f1a0b5c01") // write no response
        val CTRL_UUID: UUID = UUID.fromString("7a1c0003-4f5e-4b8a-9d3c-2e6f1a0b5c01") // opzionale ("bye")

        private const val DEVICE_TTL_MS = 5000L
        private const val CONNECT_TIMEOUT_MS = 10_000L
        private const val REQUESTED_MTU = 247
        private val BYE = "bye".toByteArray(Charsets.UTF_8)
    }

    private val adapter =
        (context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)?.adapter

    private val _devices = MutableStateFlow<List<Device>>(emptyList())
    private val _state = MutableStateFlow<PairState>(PairState.Searching)
    private val _message = MutableStateFlow<String?>(null)
    val devices: StateFlow<List<Device>> = _devices.asStateFlow()
    val state: StateFlow<PairState> = _state.asStateFlow()
    val message: StateFlow<String?> = _message.asStateFlow()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile private var gatt: BluetoothGatt? = null
    @Volatile private var dataChar: BluetoothGattCharacteristic? = null
    @Volatile private var ctrlChar: BluetoothGattCharacteristic? = null
    @Volatile private var target: Device? = null
    @Volatile private var closing = false
    @Volatile private var scanning = false
    @Volatile private var failReason: String? = null

    /** MTU negoziato; i byte utili per scrittura sono mtu - 3. */
    @Volatile var mtu: Int = 23
        private set
    val maxPayload: Int get() = mtu - 3

    private var pruneJob: Job? = null
    private var timeoutJob: Job? = null



    fun start() {
        closing = false
        _message.value = null
        startScan()
    }

    fun stop() {
        closing = true
        timeoutJob?.cancel(); timeoutJob = null
        stopScan()
        gatt?.let { runCatching { it.close() } }
        gatt = null
        dataChar = null
        ctrlChar = null
        target = null
        _devices.value = emptyList()
        _state.value = PairState.Searching
    }

    suspend fun disconnect() {
        closing = true
        timeoutJob?.cancel(); timeoutJob = null
        stopScan()
        val g = gatt
        val c = ctrlChar
        if (g != null) {
            if (c != null) {
                write(c, BYE)
                delay(150) // lascia partire il pacchetto prima di chiudere
            }
            runCatching { g.disconnect() }
            delay(200)
            runCatching { g.close() }
        }
        gatt = null
        dataChar = null
        ctrlChar = null
        target = null
        _state.value = PairState.Searching
    }

    //Scan devices
    private val scanCb = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, r: ScanResult) {
            val d = Device(
                id = r.device.address,
                name = r.scanRecord?.deviceName ?: r.device.name ?: "Unknown",
                rssi = r.rssi,
                bt = r.device,
                lastSeen = SystemClock.elapsedRealtime(),
            )
            _devices.update { l -> (l.filter { it.id != d.id } + d).sortedBy { it.name.lowercase() } }
        }

        override fun onScanFailed(errorCode: Int) {
            scanning = false
            _message.value = "Scan failed: $errorCode"
        }
    }

    private fun startScan() {
        if (scanning) return
        val scanner = adapter?.bluetoothLeScanner ?: run {
            _message.value = "Bluetooth not available"
            return
        }
        val filter = ScanFilter.Builder().setServiceUuid(ParcelUuid(SERVICE_UUID)).build()
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()
        try {
            scanner.startScan(listOf(filter), settings, scanCb)
            scanning = true
        } catch (e: Exception) {
            _message.value = "Scan error: ${e.message}"
            return
        }

        // rimuove dalla lista i dispositivi non più visti
        pruneJob?.cancel()
        pruneJob = scope.launch {
            while (isActive) {
                delay(1000)
                if (_state.value is PairState.Searching) {
                    val now = SystemClock.elapsedRealtime()
                    _devices.update { l -> l.filter { now - it.lastSeen < DEVICE_TTL_MS } }
                }
            }
        }
    }

    private fun stopScan() {
        pruneJob?.cancel(); pruneJob = null
        if (scanning) {
            runCatching { adapter?.bluetoothLeScanner?.stopScan(scanCb) }
            scanning = false
        }
    }


    fun connect(device: Device) {
        if (_state.value !is PairState.Searching) return
        closing = false
        failReason = null
        target = device
        _message.value = null
        _state.value = PairState.Connecting(device)
        stopScan() // scan e connect insieme danno problemi

        gatt = device.bt.connectGatt(context, false, gattCb, BluetoothDevice.TRANSPORT_LE)

        timeoutJob?.cancel()
        timeoutJob = scope.launch {
            delay(CONNECT_TIMEOUT_MS)
            if (_state.value is PairState.Connecting) {
                failReason = "timeout"
                gatt?.let { handleDisconnect(it, -1) }
            }
        }
    }

    private val gattCb = object : BluetoothGattCallback() {

        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                if (!g.requestMtu(REQUESTED_MTU)) {
                    g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
                    g.discoverServices()
                }
            } else {
                handleDisconnect(g, status)
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) this@BleClient.mtu = mtu
            g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
            g.discoverServices()
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            val service = g.getService(SERVICE_UUID)
            val data = service?.getCharacteristic(DATA_UUID)
            if (status != BluetoothGatt.GATT_SUCCESS || data == null) {
                failReason = "service not found"
                g.disconnect()
                return
            }
            dataChar = data
            ctrlChar = service.getCharacteristic(CTRL_UUID)

            val d = target ?: return
            timeoutJob?.cancel(); timeoutJob = null
            _state.value = PairState.Connected(d)
            onConnected(d)
        }
    }

    private fun handleDisconnect(g: BluetoothGatt, status: Int) {
        val current = gatt
        if (current != null && current !== g) { // callback di una connessione vecchia
            runCatching { g.close() }
            return
        }
        val wasConnected = _state.value is PairState.Connected
        timeoutJob?.cancel(); timeoutJob = null
        runCatching { g.close() }
        gatt = null
        dataChar = null
        ctrlChar = null
        target = null
        if (closing) return

        val reason = failReason ?: "status $status"
        failReason = null
        _state.value = PairState.Searching
        _message.value = if (wasConnected) "Connection lost" else "Connection failed: $reason"
        if (wasConnected) onLost()
        startScan() // riprende la ricerca
    }


    //Scrive un pacchetto sulla characteristic DATA
    fun send(bytes: ByteArray): Boolean {
        val c = dataChar ?: return false
        return write(c, bytes)
    }

    // Scrive un comando sulla characteristic CTRL
    fun sendCtrl(bytes: ByteArray): Boolean {
        val c = ctrlChar ?: return false
        return write(c, bytes)
    }


    private fun write(c: BluetoothGattCharacteristic, bytes: ByteArray): Boolean {
        val g = gatt ?: return false
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                g.writeCharacteristic(
                    c, bytes, BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                ) == BluetoothStatusCodes.SUCCESS
            } else {
                @Suppress("DEPRECATION")
                run {
                    c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                    c.value = bytes
                    g.writeCharacteristic(c)
                }
            }
        } catch (_: Exception) {
            false
        }
    }
}