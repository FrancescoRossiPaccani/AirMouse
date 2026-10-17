package com.example.airmouse_as.presentation

import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
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

private const val HOLD_SECONDS = 3

class MainActivity : ComponentActivity() {

    private lateinit var session: SessionManager
    private val uiScope = MainScope()
    private var holdJob: Job? = null
    private var closing = false
    private var holdSeconds by mutableStateOf<Int?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        session = SessionManager(this)
        session.start()
        setContent { WearApp(session, holdSeconds) }
    }

    override fun onResume() {
        super.onResume()
        // Garantisce che lo schermo rimanga sempre acceso per un confronto equo del consumo
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    // Pressione prolungata (3 s) del pulsante: chiude connessione e app.
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
            closing = true            // da qui il rilascio del pulsante non annulla più
            holdSeconds = 0
            session.shutdown()        // invia "bye" al server e chiude tutto
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
            val wifiReady by session.wifiReady.collectAsState()
            val notice by session.notice.collectAsState()
            val devices by session.pairing.devices.collectAsState()
            val pairState by session.pairing.state.collectAsState()
            val message by session.pairing.message.collectAsState()
            val streamStatus by session.streamStatus.collectAsState()

            val connected = pairState as? PairState.Connected
            val connecting = pairState as? PairState.Connecting

            val hint = when (holdSeconds) {
                null -> "Hold BACK ${HOLD_SECONDS} s to exit"
                0 -> "Closing…"
                else -> "Closing in $holdSeconds…"
            }

            val listState = rememberTransformingLazyColumnState()
            val spec = rememberTransformationSpec()

            ScreenScaffold(scrollState = listState) { padding ->
                TransformingLazyColumn(contentPadding = padding, state = listState) {
                    when {
                        // 1) in attesa del Wi-Fi
                        !wifiReady -> {
                            item {
                                ListHeader(
                                    modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                                    transformation = SurfaceTransformation(spec),
                                ) { Text("Air Mouse") }
                            }
                            item {
                                Text(
                                    text = notice ?: "Looking for Wi-Fi…",
                                    textAlign = TextAlign.Center,
                                    modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                                )
                            }
                        }

                        // 2) connesso: streaming attivo
                        connected != null -> {
                            item {
                                ListHeader(
                                    modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                                    transformation = SurfaceTransformation(spec),
                                ) { Text("Connected") }
                            }
                            item {
                                Text(
                                    text = connected.device.name,
                                    textAlign = TextAlign.Center,
                                    modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                                )
                            }
                            item {
                                Text(
                                    text = connected.device.ip,
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall,
                                    modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                                )
                            }
                            item {
                                Text(
                                    text = streamStatus,
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall,
                                    modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                                )
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

                        // 3) selezione del dispositivo
                        else -> {
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
                                        onClick = { session.pairing.connect(d) },
                                        enabled = connecting == null,
                                        modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                                        transformation = SurfaceTransformation(spec),
                                    ) {
                                        Column {
                                            Text(d.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                            Text(
                                                "${d.type} · ${d.ip}",
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
            }
        }
    }
}