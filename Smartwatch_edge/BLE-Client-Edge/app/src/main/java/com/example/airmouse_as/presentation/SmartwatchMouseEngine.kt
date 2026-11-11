package com.example.airmouse_as.presentation

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

private const val TAG = "SmartwatchMouseEngine"
private const val RATE_HZ = 20
private const val PERIOD_US = 1_000_000 / RATE_HZ
private const val PERIOD_MS = 1000 / RATE_HZ

class SmartwatchMouseEngine(
    context: Context,
    private val onStatus: (String) -> Unit,
) : SensorEventListener {

    private val sensorManager by lazy { context.getSystemService(Context.SENSOR_SERVICE) as SensorManager }
    private val vibrator by lazy { context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator }

    private val guard = GestureGuard()
    private val tracking = TrackingModule()
    private val recognizer: GestureRecognizer? = try {
        GestureRecognizer(ForestModel.loadFromAsset(context))
    } catch (e: Exception) {
        Log.e(TAG, "Impossibile caricare rf.json", e)
        onStatus("Errore modello: ${e.message}")
        null
    }

    private var ble: BleClient? = null
    private var running = false
    private var paused = false
    private var lastSampleMs = 0L

    private var leftLocked = false
    private var rightLocked = false

    private val _lastGesture = MutableStateFlow("Nessun gesto recente")
    val lastGesture: StateFlow<String> = _lastGesture.asStateFlow()

    fun setDpi(level: Int) = tracking.setDpi(level)

    fun start(client: BleClient) {
        ble = client
        running = true
        paused = false
        leftLocked = false
        rightLocked = false
        lastSampleMs = 0L
        guard.reset()
        tracking.reset()

        val gyro = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        if (gyro == null) {
            onStatus("Giroscopio non trovato!")
            return
        }
        sensorManager.registerListener(this, gyro, PERIOD_US)
        onStatus("Edge attivo")
    }

    fun pause() {
        paused = true
        onStatus("PAUSA")
    }

    fun resume() {
        guard.reset()
        tracking.reset()
        lastSampleMs = 0L
        paused = false
        onStatus("Edge attivo")
    }

    fun stop() {
        running = false
        paused = false
        sensorManager.unregisterListener(this)
        guard.reset()
        tracking.reset()
        releaseDrags()
        ble = null
        onStatus("Fermato")
    }

    private fun releaseDrags() {
        if (leftLocked) send(MouseCommand.Drag(MouseCommand.Button.LEFT, false))
        if (rightLocked) send(MouseCommand.Drag(MouseCommand.Button.RIGHT, false))
        leftLocked = false
        rightLocked = false
    }

    private fun send(cmd: MouseCommand) {
        ble?.send(cmd.toPayload().toByteArray(Charsets.UTF_8))
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (!running || paused) return

        // Il sensore può consegnare più eventi del richiesto: la logica è tarata su 20 Hz
        val now = SystemClock.elapsedRealtime()
        if (now - lastSampleMs < PERIOD_MS - 5) return
        lastSampleMs = now

        val s = GyroSample(now.toInt(), event.values[0], event.values[1], event.values[2])

        val before = guard.mode
        val decision = guard.update(s)

        if (before == Mode.TRACKING && guard.mode == Mode.GESTURE) {
            val (ux, uy) = tracking.rewind(2)   // annulla i campioni dell'inizio dello scatto
            if (ux != 0 || uy != 0) send(MouseCommand.Undo(ux, uy))
        }

        when (decision) {
            GuardDecision.Tracking -> {
                val (dx, dy) = tracking.onSample(s)
                if (dx != 0 || dy != 0) send(MouseCommand.Move(dx, dy))
            }
            GuardDecision.Buffering -> Unit
            is GuardDecision.GestureComplete -> {
                val pred = recognizer?.classify(decision.window)
                if (pred == null) _lastGesture.value = "Gesto non riconosciuto" else execute(pred)
            }
        }
    }

    private fun execute(pred: Prediction) {
        val L = MouseCommand.Button.LEFT
        val R = MouseCommand.Button.RIGHT
        val action = when (pred.label) {
            "RLB" -> { send(MouseCommand.Click(L)); buzz(40); "click sinistro" }
            "RRB" -> { send(MouseCommand.Click(R)); buzz(40); "click destro" }
            "UDB" -> { send(MouseCommand.DoubleClick); buzz(35, 60, 35); "doppio click" }
            "MLB" -> {
                leftLocked = !leftLocked
                send(MouseCommand.Drag(L, leftLocked)); buzz(100)
                if (leftLocked) "blocco sinistro ON" else "blocco sinistro OFF"
            }
            "MRB" -> {
                rightLocked = !rightLocked
                send(MouseCommand.Drag(R, rightLocked)); buzz(100)
                if (rightLocked) "blocco destro ON" else "blocco destro OFF"
            }
            else -> "nessuna azione per ${pred.label}"
        }
        _lastGesture.value = "${pred.label} (${(pred.confidence * 100).toInt()}%) -> $action"
    }

    /** Vibra: un solo valore = impulso, più valori = durate alternate on/off/on... */
    private fun buzz(vararg ms: Long) {
        val timings = longArrayOf(0, *ms)
        vibrator?.vibrate(VibrationEffect.createWaveform(timings, -1))
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}
