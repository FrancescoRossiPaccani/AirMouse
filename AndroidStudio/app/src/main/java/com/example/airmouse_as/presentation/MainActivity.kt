package com.example.airmouse_as.presentation

import android.os.Bundle
// --- START [11/10/2026]: Import per terminazione forzata del processo e rimozione dalle app recenti ---
import android.os.Process
import kotlin.system.exitProcess
// --- END [11/10/2026]: Import per terminazione forzata del processo e rimozione dalle app recenti ---
// --- START [10/10/2026] Pairing: Import per gestione eventi tasti fisici e finestra di visualizzazione ---
import android.view.KeyEvent
import android.view.WindowManager
// --- END [10/10/2026] Pairing: Import per gestione eventi tasti fisici e finestra di visualizzazione ---
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
// --- START [10/10/2026] Pairing: Import Jetpack Compose per interfaccia dinamica e stati reattivi ---
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
// --- END [10/10/2026] Pairing: Import Jetpack Compose per interfaccia dinamica e stati reattivi ---
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.AppScaffold
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ListHeader
// --- START [10/10/2026] Pairing: Import stili MaterialTheme Wear OS ---
import androidx.wear.compose.material3.MaterialTheme
// --- END [10/10/2026] Pairing: Import stili MaterialTheme Wear OS ---
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.example.airmouse_as.presentation.theme.AirMouseASTheme
// --- START [10/10/2026] Pairing: Coroutine per gestione pressione prolungata pulsante di uscita ---
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
// --- END [10/10/2026] Pairing: Coroutine per gestione pressione prolungata pulsante di uscita ---

// --- START [10/10/2026] Pairing & [11/10/2026]: Finestra temporale per doppio click del tasto fisico ---
private const val DOUBLE_PRESS_WINDOW_MS = 2000L
// --- END [10/10/2026] Pairing & [11/10/2026]: Finestra temporale per doppio click del tasto fisico ---

class MainActivity : ComponentActivity() {

    // --- START [10/10/2026] Pairing & [11/10/2026]: Gestione sessione e doppio click tasto fisico inferiore ---
    private lateinit var session: SessionManager
    private val uiScope = MainScope()
    private var closing by mutableStateOf(false)
    private var exitPending by mutableStateOf(false)
    private var lastBackPressTime = 0L
    private var resetPendingJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        session = SessionManager(this)
        session.start()
        setContent {
            WearApp(
                session = session,
                exitPending = exitPending,
                closing = closing
            )
        }
    }

    // --- START [11/10/2026]: Intercettazione doppio click tasto fisico inferiore Wear OS (Galaxy Watch 5) ---
    // Riconosce sia il tasto Back standard sia i pulsanti multifunzione laterali (STEM) di Wear OS / Galaxy Watch.
    private fun isExitKey(keyCode: Int): Boolean {
        return keyCode == KeyEvent.KEYCODE_BACK ||
            keyCode == KeyEvent.KEYCODE_STEM_PRIMARY ||
            keyCode == KeyEvent.KEYCODE_STEM_1 ||
            keyCode == KeyEvent.KEYCODE_STEM_2 ||
            keyCode == KeyEvent.KEYCODE_STEM_3 ||
            keyCode == KeyEvent.KEYCODE_APP_SWITCH
    }

    private fun handleBackPress() {
        if (closing) return
        val now = System.currentTimeMillis()
        if (exitPending && (now - lastBackPressTime) < DOUBLE_PRESS_WINDOW_MS) {
            // Secondo click rapido entro 2 secondi: chiude la sessione e l'applicazione
            resetPendingJob?.cancel()
            exitPending = false
            exitApp()
        } else {
            // Primo click: richiede la seconda pressione di conferma entro 2 secondi
            lastBackPressTime = now
            exitPending = true
            resetPendingJob?.cancel()
            resetPendingJob = uiScope.launch {
                delay(DOUBLE_PRESS_WINDOW_MS)
                exitPending = false
            }
        }
    }

    // Intercetta la pressione del tasto fisico per evitare il lancio di app di sistema (es. Samsung Pay su Watch 5)
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (isExitKey(event.keyCode)) {
            if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) {
                handleBackPress()
            }
            return true // Consuma l'evento evitando l'apertura di scorciatoie di sistema
        }
        return super.dispatchKeyEvent(event)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (isExitKey(keyCode)) return true
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (isExitKey(keyCode)) return true
        return super.onKeyUp(keyCode, event)
    }

    private fun exitApp() {
        if (closing) return
        closing = true
        resetPendingJob?.cancel()
        exitPending = false
        uiScope.launch {
            try {
                session.shutdown() // invia "bye" al server e chiude stream e socket
            } catch (_: Exception) {}
            // --- START [11/10/2026]: Rimozione task da app recenti e kill definitivo del processo Linux ---
            finishAndRemoveTask()
            delay(150)
            Process.killProcess(Process.myPid())
            exitProcess(0)
            // --- END [11/10/2026]: Rimozione task da app recenti e kill definitivo del processo Linux ---
        }
    }

    override fun onDestroy() {
        uiScope.cancel()
        session.release()
        super.onDestroy()
        // --- START [11/10/2026]: Terminazione forzata del processo su onDestroy ---
        Process.killProcess(Process.myPid())
        // --- END [11/10/2026]: Terminazione forzata del processo su onDestroy ---
    }
    // --- END [10/10/2026] Pairing & [11/10/2026]: Gestione sessione e doppio click tasto fisico inferiore ---
}

// --- START [10/10/2026] Pairing & [11/10/2026]: Schermata WearApp adattiva guidata dagli stati di Pairing e Wi-Fi ---
@Composable
fun WearApp(
    session: SessionManager,
    exitPending: Boolean,
    closing: Boolean
) {
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

            val hint = when {
                closing -> "Chiusura in corso…"
                exitPending -> "Premi di nuovo per uscire"
                else -> "Premi 2 volte BACK per uscire"
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
                            item {
                                Text(
                                    text = hint,
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall,
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

                        // 3) selezione del dispositivo trovato in rete
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
// --- END [10/10/2026] Pairing: Schermata WearApp adattiva guidata dagli stati di Pairing e Wi-Fi ---