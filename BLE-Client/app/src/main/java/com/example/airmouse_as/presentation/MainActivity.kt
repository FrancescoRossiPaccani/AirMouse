package com.example.airmouse_as.presentation

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.AppScaffold
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.example.airmouse_as.presentation.theme.AirMouseASTheme
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.cos
import kotlin.math.sin

private const val HOLD_SECONDS = 3

class MainActivity : ComponentActivity() {

    private lateinit var session: SessionManager
    private val uiScope = MainScope()
    private var holdJob: Job? = null
    private var closing = false
    private var holdSeconds by mutableStateOf<Int?>(null)

    private val blePermissions: Array<String> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT,
            )
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
            if (result.values.all { it }) session.start()
            else session.onPermissionDenied()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        session = SessionManager(this)
        setContent { WearApp(session, holdSeconds) }

        if (hasBlePermissions()) session.start()
        else permissionLauncher.launch(blePermissions)
    }

    override fun onResume() {
        super.onResume()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun hasBlePermissions() = blePermissions.all {
        ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
    }

    // Pressione prolungata (3 s)
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode == KeyEvent.KEYCODE_BACK ||
            event.keyCode == KeyEvent.KEYCODE_STEM_PRIMARY
        ) {
            if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) startHold()
            else if (event.action == KeyEvent.ACTION_UP) cancelHold()
            return true
        }
        return super.dispatchKeyEvent(event)
    }

    private fun startHold() {
        if (holdJob != null) return
        holdJob = uiScope.launch {
            for (s in HOLD_SECONDS downTo 1) {
                holdSeconds = s
                delay(1000)
            }
            closing = true
            holdSeconds = 0
            session.shutdown()
            finishAffinity()
        }
    }

    private fun cancelHold() {
        if (closing) return
        holdJob?.cancel()
        holdJob = null
        holdSeconds = null
    }

    override fun onDestroy() {
        uiScope.cancel()
        session.release()
        super.onDestroy()
    }
}

@Composable
fun WearApp(session: SessionManager, holdSeconds: Int?) {
    AirMouseASTheme {
        AppScaffold {
            val pairState by session.ble.state.collectAsState()
            if (pairState is PairState.Connected) {
                ControlScreen(session, holdSeconds)
            } else {
                PairingScreen(session, holdSeconds)
            }
        }
    }
}

private val COL_MOUSE = Color(0xFF2563EB)
private val COL_LASER = Color(0xFFDC2626)
private val COL_DARK = Color(0xFF2B2B2B)
private val COL_PAUSE = Color(0xFFD97706)
private val COL_CONTINUE = Color(0xFF16A34A)
private val COL_STOP = Color(0xFF7F1D1D)

@Composable
fun ControlScreen(session: SessionManager, holdSeconds: Int?) {
    val laser by session.laser.collectAsState()
    val dpi by session.dpi.collectAsState()
    val isPaused by session.isPaused.collectAsState()

    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val s: Dp = if (maxWidth < maxHeight) maxWidth else maxHeight

        val bigSize = s * 0.34f
        val smallSize = s * 0.15f
        val bottomH = s * 0.14f
        val bottomW = s * 0.30f
        val gap = s * 0.03f

        val status = when {
            holdSeconds != null && holdSeconds > 0 -> "Chiusura in $holdSeconds…"
            holdSeconds == 0 -> "Chiusura…"
            isPaused -> "IN PAUSA"
            else -> "Attivo"
        }

        Column(
            modifier = Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            // 1) stato
            Text(
                text = status,
                fontSize = 11.sp,
                textAlign = TextAlign.Center,
                maxLines = 1,
            )
            Spacer(Modifier.height(gap))

            // 2) Modalità cursore
            Box(
                modifier = Modifier
                    .size(bigSize)
                    .clip(CircleShape)
                    .background(if (laser) COL_LASER else COL_MOUSE)
                    .clickable { session.toggleLaser() },
                contentAlignment = Alignment.Center,
            ) {
                Canvas(Modifier.size(bigSize * 0.6f)) {
                    if (laser) drawLaserIcon() else drawMouseIcon()
                }
            }
            Spacer(Modifier.height(gap))

            // 3) DPI
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center,
            ) {
                RoundTinyButton(
                    size = smallSize,
                    enabled = dpi > 0,
                    onClick = { session.dpiDown() },
                    icon = { drawMinus() },
                )
                Text(
                    text = "${dpi + 1}/${SessionManager.DPI_LEVELS}",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.width(smallSize * 1.9f),
                )
                RoundTinyButton(
                    size = smallSize,
                    enabled = dpi < SessionManager.DPI_LEVELS - 1,
                    onClick = { session.dpiUp() },
                    icon = { drawPlus() },
                )
            }
            Spacer(Modifier.height(gap))

            // 4) STOP e PAUSA/CONTINUA
            Row(
                horizontalArrangement = Arrangement.spacedBy(gap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ActionButton(
                    label = "STOP",
                    color = COL_STOP,
                    width = bottomW,
                    height = bottomH,
                    onClick = { session.disconnectToList() },
                    icon = { drawStopIcon() },
                )
                ActionButton(
                    label = if (isPaused) "CONTINUA" else "PAUSA",
                    color = if (isPaused) COL_CONTINUE else COL_PAUSE,
                    width = bottomW,
                    height = bottomH,
                    onClick = { session.togglePause() },
                    icon = { if (isPaused) drawPlayIcon() else drawPauseIcon() },
                )
            }
        }
    }
}

@Composable
private fun RoundTinyButton(
    size: Dp,
    enabled: Boolean,
    onClick: () -> Unit,
    icon: DrawScope.() -> Unit,
) {
    Box(
        modifier = Modifier
            .size(size)
            .clip(CircleShape)
            .background(if (enabled) COL_DARK else COL_DARK.copy(alpha = 0.4f))
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.size(size * 0.5f)) { icon() }
    }
}

@Composable
private fun ActionButton(
    label: String,
    color: Color,
    width: Dp,
    height: Dp,
    onClick: () -> Unit,
    icon: DrawScope.() -> Unit,
) {
    Row(
        modifier = Modifier
            .width(width)
            .height(height)
            .clip(RoundedCornerShape(50))
            .background(color)
            .clickable(onClick = onClick),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        Canvas(Modifier.size(height * 0.38f)) { icon() }
        Spacer(Modifier.width(3.dp))
        Text(
            text = label,
            fontSize = 9.sp,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
            color = Color.White,
        )
    }
}

// Icone
private fun DrawScope.drawMouseIcon() {
    val w = size.width
    val h = size.height
    val sw = w * 0.09f
    val bw = w * 0.62f
    val bh = h * 0.92f
    val left = (w - bw) / 2f
    val top = (h - bh) / 2f
    drawRoundRect(
        color = Color.White,
        topLeft = Offset(left, top),
        size = Size(bw, bh),
        cornerRadius = CornerRadius(bw / 2f, bw / 2f),
        style = Stroke(width = sw),
    )
    drawLine(Color.White, Offset(w / 2f, top), Offset(w / 2f, top + bh * 0.42f), sw)
    drawLine(Color.White, Offset(left, top + bh * 0.42f), Offset(left + bw, top + bh * 0.42f), sw)
}

private fun DrawScope.drawLaserIcon() {
    val c = Offset(size.width / 2f, size.height / 2f)
    val r = size.width * 0.17f
    val sw = size.width * 0.08f
    drawCircle(Color.White.copy(alpha = 0.35f), radius = r * 1.9f, center = c)
    for (i in 0 until 8) {
        val a = Math.toRadians(i * 45.0)
        val from = Offset(c.x + (r * 1.6f * cos(a)).toFloat(), c.y + (r * 1.6f * sin(a)).toFloat())
        val to = Offset(c.x + (size.width * 0.46f * cos(a)).toFloat(), c.y + (size.width * 0.46f * sin(a)).toFloat())
        drawLine(Color.White, from, to, sw, StrokeCap.Round)
    }
    drawCircle(Color.White, radius = r, center = c)
}

private fun DrawScope.drawMinus() {
    val sw = size.width * 0.16f
    drawLine(Color.White, Offset(0f, size.height / 2f), Offset(size.width, size.height / 2f), sw, StrokeCap.Round)
}

private fun DrawScope.drawPlus() {
    val sw = size.width * 0.16f
    drawLine(Color.White, Offset(0f, size.height / 2f), Offset(size.width, size.height / 2f), sw, StrokeCap.Round)
    drawLine(Color.White, Offset(size.width / 2f, 0f), Offset(size.width / 2f, size.height), sw, StrokeCap.Round)
}

private fun DrawScope.drawStopIcon() {
    drawRect(
        Color.White,
        topLeft = Offset(size.width * 0.1f, size.height * 0.1f),
        size = Size(size.width * 0.8f, size.height * 0.8f),
    )
}

private fun DrawScope.drawPauseIcon() {
    val bw = size.width * 0.32f
    drawRect(Color.White, Offset(size.width * 0.08f, 0f), Size(bw, size.height))
    drawRect(Color.White, Offset(size.width * 0.60f, 0f), Size(bw, size.height))
}

private fun DrawScope.drawPlayIcon() {
    val path = Path().apply {
        moveTo(size.width * 0.15f, 0f)
        lineTo(size.width, size.height / 2f)
        lineTo(size.width * 0.15f, size.height)
        close()
    }
    drawPath(path, Color.White)
}

// Schermata handshake
@Composable
fun PairingScreen(session: SessionManager, holdSeconds: Int?) {
    val bleReady by session.bleReady.collectAsState()
    val notice by session.notice.collectAsState()
    val devices by session.ble.devices.collectAsState()
    val pairState by session.ble.state.collectAsState()
    val message by session.ble.message.collectAsState()
    val connecting = pairState as? PairState.Connecting

    val hint = when (holdSeconds) {
        null -> "Hold BACK $HOLD_SECONDS s to exit"
        0 -> "Closing…"
        else -> "Closing in $holdSeconds…"
    }

    val listState = rememberTransformingLazyColumnState()
    val spec = rememberTransformationSpec()

    ScreenScaffold(scrollState = listState) { padding ->
        TransformingLazyColumn(contentPadding = padding, state = listState) {
            if (!bleReady) {
                item {
                    ListHeader(
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        transformation = SurfaceTransformation(spec),
                    ) { Text("Air Mouse BLE") }
                }
                item {
                    Text(
                        text = notice ?: "Looking for Bluetooth…",
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                    )
                }
            } else {
                item {
                    ListHeader(
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        transformation = SurfaceTransformation(spec),
                    ) { Text("Select device") }
                }
                if (devices.isEmpty()) {
                    item {
                        Text(
                            text = "Searching…",
                            textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                }
                devices.forEach { d ->
                    item(key = d.id) {
                        Button(
                            onClick = { session.ble.connect(d) },
                            enabled = connecting == null,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec),
                        ) {
                            Column {
                                Text(d.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(
                                    "BLE · ${d.rssi} dBm",
                                    style = MaterialTheme.typography.bodySmall,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }
                    }
                }
                connecting?.let { c ->
                    item {
                        Text(
                            text = "Connecting to ${c.device.name}…",
                            textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                }
                message?.let { m ->
                    item {
                        Text(
                            text = m,
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                }
            }
            item {
                Text(
                    text = hint,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                )
            }
        }
    }
}