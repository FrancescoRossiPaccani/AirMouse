package com.example.airmouse_as.presentation

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.AppScaffold
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.example.airmouse_as.presentation.theme.AirMouseASTheme

// >>> CAMBIA CON L'IP DEL TUO PC <<<
private const val PC_IP = "10.45.165.88"
private const val PC_PORT = 5005

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { WearApp() }
    }
}

@Composable
fun WearApp() {
    AirMouseASTheme {
        AppScaffold {
            val context = LocalContext.current
            val view = LocalView.current
            var status by remember { mutableStateOf("Fermo") }
            var running by remember { mutableStateOf(false) }

            val streamer = remember {
                SensorStreamer(context.applicationContext, PC_IP, PC_PORT) { status = it }
            }

            // tiene lo schermo acceso mentre si trasmette
            DisposableEffect(running) {
                view.keepScreenOn = running
                onDispose { view.keepScreenOn = false }
            }
            DisposableEffect(Unit) { onDispose { streamer.stop() } }

            val listState = rememberTransformingLazyColumnState()
            val spec = rememberTransformationSpec()

            ScreenScaffold(scrollState = listState) { padding ->
                TransformingLazyColumn(contentPadding = padding, state = listState) {
                    item {
                        ListHeader(
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec),
                        ) { Text("Air Mouse") }
                    }
                    item {
                        Text(
                            text = status,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                    item {
                        Button(
                            onClick = {
                                if (running) streamer.stop() else streamer.start()
                                running = !running
                            },
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec),
                        ) { Text(if (running) "Stop" else "Start") }
                    }
                }
            }
        }
    }
}