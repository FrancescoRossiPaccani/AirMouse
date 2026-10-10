package com.example.airmouse_as.presentation

import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.SystemClock
import kotlinx.coroutines.CancellationException
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
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.io.OutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.util.UUID

data class Device(
    val id: String,
    val name: String,
    val type: String,
    val ip: String,
    val tcpPort: Int,
    val udpPort: Int,
    val lastSeen: Long = 0L,
)

sealed interface PairState {
    object Searching : PairState
    data class Connecting(val device: Device) : PairState
    data class Connected(val device: Device) : PairState
}

/**
 * Discovery (UDP broadcast) + pairing (TCP) towards the PC.
 * The network used must be the Wi-Fi one, otherwise traffic may go through the phone proxy.
 */
class PairingClient(
    private val connectivityManager: ConnectivityManager,
    private val onConnected: (Device) -> Unit,
    private val onLost: () -> Unit,
) {
    private companion object {
        const val PROTO = 1
        const val DISCOVERY_PORT = 5006
        const val DISCOVERY_INTERVAL_MS = 1000L
        const val DEVICE_TTL_MS = 4000L
        const val HEARTBEAT_MS = 2000L
        const val READ_TIMEOUT_MS = 6000
    }

    private val _devices = MutableStateFlow<List<Device>>(emptyList())
    private val _state = MutableStateFlow<PairState>(PairState.Searching)
    private val _message = MutableStateFlow<String?>(null)
    val devices: StateFlow<List<Device>> = _devices.asStateFlow()
    val state: StateFlow<PairState> = _state.asStateFlow()
    val message: StateFlow<String?> = _message.asStateFlow()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val clientId = UUID.randomUUID().toString()
    private val clientName: String = Build.MODEL
    private val writeLock = Any()

    @Volatile private var network: Network? = null
    @Volatile private var sock: Socket? = null
    @Volatile private var closing = false
    private var discoveryJob: Job? = null
    private var connJob: Job? = null

    // ------------------------------------------------------------ lifecycle
    fun start(net: Network) {
        stop()
        closing = false
        network = net
        _message.value = null
        discoveryJob = scope.launch { discoveryLoop(net) }
    }

    /** Abrupt stop (e.g. Wi-Fi lost). */
    fun stop() {
        closing = true
        discoveryJob?.cancel(); discoveryJob = null
        connJob?.cancel(); connJob = null
        val s = sock
        sock = null
        if (s != null) scope.launch { runCatching { s.close() } }
        _devices.value = emptyList()
        _state.value = PairState.Searching
    }

    /** Graceful close: tells the server we are leaving. */
    suspend fun disconnect() = withContext(Dispatchers.IO) {
        closing = true
        val s = sock
        if (s != null) {
            runCatching { writeLine(s.getOutputStream(), """{"type":"bye"}""") }
            runCatching { s.close() }
        }
        sock = null
        connJob?.cancel(); connJob = null
        _state.value = PairState.Searching
    }

    // ------------------------------------------------------------ discovery
    private suspend fun discoveryLoop(net: Network) {
        var socket: DatagramSocket? = null
        try {
            socket = DatagramSocket()
            net.bindSocket(socket)
            socket.broadcast = true
            socket.soTimeout = 200
            val request = JSONObject().apply {
                put("type", "discover")
                put("proto", PROTO)
                put("id", clientId)
                put("name", clientName)
            }.toString().toByteArray(Charsets.UTF_8)
            val buf = ByteArray(1024)
            var nextSend = 0L

            while (scope.isActive && discoveryJob?.isActive != false) {
                if (_state.value is PairState.Connected) { // connected: stay quiet
                    delay(300)
                    continue
                }
                val now = SystemClock.elapsedRealtime()
                if (now >= nextSend) {
                    nextSend = now + DISCOVERY_INTERVAL_MS
                    for (target in broadcastTargets(net)) {
                        try {
                            socket.send(DatagramPacket(request, request.size, target, DISCOVERY_PORT))
                        } catch (_: IOException) { }
                    }
                    _devices.update { l -> l.filter { now - it.lastSeen < DEVICE_TTL_MS } }
                }
                try {
                    val p = DatagramPacket(buf, buf.size)
                    socket.receive(p)
                    handleOffer(p)
                } catch (_: SocketTimeoutException) { }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _message.value = "Discovery error: ${e.message}"
        } finally {
            socket?.close()
        }
    }

    private fun broadcastTargets(net: Network): List<InetAddress> {
        val out = mutableListOf(InetAddress.getByName("255.255.255.255"))
        connectivityManager.getLinkProperties(net)?.linkAddresses?.forEach { la ->
            val a = la.address
            if (a is Inet4Address && la.prefixLength in 1..31) {
                val ip = a.address
                val v = ((ip[0].toInt() and 255) shl 24) or ((ip[1].toInt() and 255) shl 16) or
                        ((ip[2].toInt() and 255) shl 8) or (ip[3].toInt() and 255)
                val mask = -1 shl (32 - la.prefixLength)
                val b = v or mask.inv()
                out += InetAddress.getByAddress(
                    byteArrayOf((b ushr 24).toByte(), (b ushr 16).toByte(), (b ushr 8).toByte(), b.toByte())
                )
            }
        }
        return out.distinct()
    }

    private fun handleOffer(p: DatagramPacket) {
        try {
            val j = JSONObject(String(p.data, 0, p.length, Charsets.UTF_8))
            if (j.optString("type") != "offer" || j.optInt("proto") != PROTO) return
            val ip = p.address?.hostAddress ?: return
            val d = Device(
                id = j.getString("id"),
                name = j.optString("name", "Unknown"),
                type = j.optString("device", ""),
                ip = ip,
                tcpPort = j.getInt("tcp_port"),
                udpPort = j.getInt("udp_port"),
                lastSeen = SystemClock.elapsedRealtime(),
            )
            _devices.update { l -> (l.filter { it.id != d.id } + d).sortedBy { it.name.lowercase() } }
        } catch (_: Exception) { }
    }

    // ------------------------------------------------------------- pairing
    fun connect(device: Device) {
        val net = network ?: return
        if (_state.value !is PairState.Searching) return
        _state.value = PairState.Connecting(device)
        _message.value = null
        closing = false

        connJob = scope.launch {
            var s: Socket? = null
            var connected = false
            var reason = "connection closed"
            try {
                s = Socket()
                net.bindSocket(s)
                s.connect(InetSocketAddress(device.ip, device.tcpPort), 4000)
                s.soTimeout = READ_TIMEOUT_MS
                s.keepAlive = true
                s.tcpNoDelay = true
                sock = s
                val out = s.getOutputStream()
                val reader = s.getInputStream().bufferedReader(Charsets.UTF_8)

                writeLine(out, JSONObject().apply {
                    put("type", "pair")
                    put("proto", PROTO)
                    put("id", clientId)
                    put("name", clientName)
                }.toString())

                val reply = JSONObject(reader.readLine() ?: throw IOException("closed by server"))
                when (reply.optString("type")) {
                    "ack" -> Unit
                    "busy" -> throw IOException("${device.name} is already paired")
                    else -> throw IOException("unexpected reply")
                }

                connected = true
                _state.value = PairState.Connected(device)
                onConnected(device)

                // heartbeat: ping -> pong every 2 s
                while (isActive) {
                    writeLine(out, """{"type":"ping"}""")
                    val line = reader.readLine() ?: throw IOException("closed by server")
                    if (JSONObject(line).optString("type") == "bye") throw IOException("closed by server")
                    delay(HEARTBEAT_MS)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                reason = e.message ?: e.javaClass.simpleName
            } finally {
                runCatching { s?.close() }
                if (sock === s) sock = null
                if (!closing) {
                    _state.value = PairState.Searching
                    if (connected) {
                        _message.value = "Connection lost: $reason"
                        onLost()
                    } else {
                        _message.value = "Connection failed: $reason"
                    }
                }
            }
        }
    }

    private fun writeLine(out: OutputStream, text: String) = synchronized(writeLock) {
        out.write((text + "\n").toByteArray(Charsets.UTF_8))
        out.flush()
    }
}