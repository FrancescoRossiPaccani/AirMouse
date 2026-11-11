package com.example.airmouse_as.presentation

import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sign
import kotlin.math.sqrt

class TrackingModule(
    private val horizontalAxis: Int = 2,   // 0=x, 1=y, 2=z del giroscopio
    private val verticalAxis: Int = 1,
    private val horizontalSign: Double = -1.0,
    private val verticalSign: Double = -1.0,
    private val basePxPerDeg: Double = 18.0, // sensibilità base
    private val deadzoneDps: Double = 0.7,
    // Curva non-lineare a tre zone (in gradi/s)
    private val slowDps: Double = 15.0,      // sotto: guadagno di precisione
    private val fastDps: Double = 60.0,      // sopra: guadagno di velocità
    private val slowGain: Double = 0.5,
    private val fastGain: Double = 1.5,
    private val fastSlope: Double = 0.01,    // crescita oltre fastDps
    // Stima del bias del giroscopio
    private val stillDps: Double = 3.0,      // sotto: mano considerata ferma
    private val stillSamples: Int = 20,      // campioni fermi prima dell'aggiornamento
    private val historySize: Int = 10,
) {
    private var prevTMs: Int? = null
    private val history = ArrayDeque<Pair<Int, Int>>()

    // Accumulo per frazioni di pixel (evita perdite per arrotondamento nei movimenti lenti)
    private var subPixelX = 0.0
    private var subPixelY = 0.0

    // Sensibilità regolabile tramite DPI
    private var dpiMultiplier = 1.0

    // Bias del giroscopio per asse, in gradi/s
    private val bias = DoubleArray(3)
    private var stillCount = 0
    private var biasUpdates = 0

    fun setDpi(dpiLevel: Int, maxLevels: Int = SessionManager.DPI_LEVELS) {
        // Mappa il livello DPI [0..5] in un moltiplicatore di velocità [0.5 .. 1.75]
        dpiMultiplier = 0.5 + (dpiLevel.coerceIn(0, maxLevels - 1) * 0.25)
    }

    fun onSample(s: GyroSample): Pair<Int, Int> {
        val g = doubleArrayOf(
            Math.toDegrees(s.gx.toDouble()),
            Math.toDegrees(s.gy.toDouble()),
            Math.toDegrees(s.gz.toDouble())
        )
        updateBias(g)

        val dt = prevTMs?.let { ((s.tMs - it) / 1000.0).coerceIn(0.01, 0.15) } ?: 0.05
        prevTMs = s.tMs

        val rateH = g[horizontalAxis] - bias[horizontalAxis]
        val rateV = g[verticalAxis] - bias[verticalAxis]

        val pxPerDeg = basePxPerDeg * dpiMultiplier

        val rawDx = horizontalSign * curve(rateH) * dt * pxPerDeg
        val rawDy = verticalSign * curve(rateV) * dt * pxPerDeg

        subPixelX += rawDx
        subPixelY += rawDy

        val stepX = subPixelX.roundToInt()
        val stepY = subPixelY.roundToInt()

        subPixelX -= stepX
        subPixelY -= stepY

        // Salva nella cronologia dei passi per consentire il rewind in caso di scatto
        history.addLast(stepX to stepY)
        while (history.size > historySize) {
            history.removeFirst()
        }

        return stepX to stepY
    }

    private fun updateBias(g: DoubleArray) {
        val rate = sqrt((0..2).sumOf { (g[it] - bias[it]) * (g[it] - bias[it]) })
        if (rate < stillDps) {
            if (++stillCount >= stillSamples) {
                val alpha = if (biasUpdates < 40) 0.1 else 0.02
                for (i in 0..2) {
                    bias[i] += alpha * (g[i] - bias[i])
                }
                biasUpdates++
            }
        } else {
            stillCount = 0
        }
    }

    private fun curve(rateDps: Double): Double {
        val m = abs(rateDps)
        if (m < deadzoneDps) return 0.0
        val gain = when {
            m < slowDps -> slowGain
            m < fastDps -> slowGain + (m - slowDps) / (fastDps - slowDps) * (fastGain - slowGain)
            else -> fastGain + (m - fastDps) * fastSlope
        }
        return sign(rateDps) * m * gain
    }

    fun rewind(samples: Int): Pair<Int, Int> {
        val count = samples.coerceAtMost(history.size)
        var totalX = 0
        var totalY = 0
        repeat(count) {
            if (history.isNotEmpty()) {
                val (hx, hy) = history.removeLast()
                totalX += hx
                totalY += hy
            }
        }
        return totalX to totalY
    }

    fun reset() {
        prevTMs = null
        stillCount = 0
        subPixelX = 0.0
        subPixelY = 0.0
        history.clear()
    }
}

