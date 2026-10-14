# --- START [11/10/2026] Step 6: Ricevitore Avanzato reciverV2.py con 120Hz Smooth Interpolator, 1€ Filter e Zero-Latency Stream ---
"""
reciverV2.py: Ricevitore avanzato per il sistema AirMouse (Wear OS -> PC).
Implementa le ottimizzazioni di performance, sensibilità e fluidità continua (Step 6):
1. Motore di Interpolazione a 120 Hz (SmoothCursorEngine): fluidità burrosa continua a 120 FPS
   tra i pacchetti a 20 Hz ricevuti dallo smartwatch.
2. Filtro 1€ (One Euro Filter): abbattimento completo del tremolio fisiologico a riposo e
   risposta istantanea 1-a-1 ad alte velocità senza lag percettivo.
3. Zero-Latency Stream: selezione dinamica tra flusso IMU grezzo a latenza zero e flusso Wavelet.
4. Madgwick AHRS Adattivo: integrazione del dt reale di campionamento e scalatura di beta sotto accelerazione.
5. Anti-Jumping Roll-Isolated: protezione contro congelamenti accidentali durante rapidi scorrimenti orizzontali.
6. Console HUD Non-Bloccante a 10 Hz: eliminazione del collo di bottiglia dell'I/O terminale di Windows.
7. Suite completa di scorciatoie da tastiera interattive per calibrazione, monitor, modalità e sensibilità.
"""
import json
import math
import socket
import sys
import threading
import time

# Moduli interni del progetto AirMouse
from ahrs import AHRSFilter
from gesture_detector import GestureDetector
from mouse_mapper import MouseMapper
from mouse_controller import MouseController
from pairing import PairingServer
from screen_calibrator import ScreenCalibrator

try:
    import msvcrt
except ImportError:
    msvcrt = None


# ==============================================================================
# CONFIGURAZIONE GENERALE E COSTANTI DI RETE
# ==============================================================================
HOST = "0.0.0.0"
PORT = 5005

# Seleziona quale segnale dare in pasto all'AHRS per il tracking del cursore:
# False (Consigliato per puntamento reattivo): dati grezzi a latenza zero (0 ms delay),
#       filtrati dal bias statico calcolato e dal Filtro 1€.
# True: dati puliti dal WaveletDenoiser dello smartwatch (ritardo buffer intrinseco di 4 campioni = 200 ms).
USE_DENOISED_DEFAULT = False

# Abilitazione controllo fisico del mouse sul sistema operativo
ENABLE_MOUSE_CONTROL = True

# Modalità di default: Assoluta Boresight (True) vs Relativa Delta (False)
USE_ABSOLUTE_BORESIGHT = True


# ==============================================================================
# MOTORE DI INTERPOLAZIONE E FLUIDITÀ CONTINUA A 120 HZ (SmoothCursorEngine)
# ==============================================================================
class SmoothCursorEngine:
    """
    Motore asincrono ad alta frequenza (120 Hz / ~8.3 ms) per il movimento continuo e fluido del cursore.
    
    Poiché lo smartwatch trasmette a 20 Hz (~50 ms), l'aggiornamento diretto del puntatore
    genererebbe scatti evidenti (stepping) su display a 60 Hz / 120 Hz / 144 Hz.
    Questo motore esegue un'interpolazione esponenziale a smorzamento critico (critically-damped glide)
    verso le coordinate bersaglio aggiornate dai pacchetti UDP:
        x(t + dt) = x(t) + (x_target - x(t)) * (1 - exp(-lambda * dt))
    Garantisce una traiettoria fluida come il burro (liquid smooth), zero overshoot e reattività istantanea.
    """
    def __init__(self, controller: MouseController, update_hz: float = 120.0, smoothing_lambda: float = 32.0):
        self.controller = controller
        self.update_interval = 1.0 / max(30.0, update_hz)
        self.smoothing_lambda = float(smoothing_lambda)
        self.enabled = True

        # Coordinate correnti e bersaglio (in pixel float)
        self.target_x = 0.0
        self.target_y = 0.0
        self.current_x = 0.0
        self.current_y = 0.0

        # Pool per modalità relativa (delta sub-pixel)
        self.delta_pool_x = 0.0
        self.delta_pool_y = 0.0
        self.is_absolute_mode = True

        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._last_tick = time.perf_counter()

    def start(self):
        """Avvia il thread in background a 120 Hz."""
        if self._running:
            return
        self._running = True
        self._last_tick = time.perf_counter()
        self._thread = threading.Thread(target=self._loop, name="SmoothCursorEngine", daemon=True)
        self._thread.start()

    def stop(self):
        """Arresta il thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def set_target(self, x: float, y: float, is_absolute: bool = True):
        """Aggiorna le coordinate bersaglio ricevute dal thread di rete."""
        with self._lock:
            self.is_absolute_mode = is_absolute
            if is_absolute:
                self.target_x = float(x)
                self.target_y = float(y)
            else:
                self.delta_pool_x += float(x)
                self.delta_pool_y += float(y)

    def snap_to(self, x: float, y: float):
        """Riallinea istantaneamente la posizione corrente sul bersaglio (es. ricentramento)."""
        with self._lock:
            self.current_x = float(x)
            self.current_y = float(y)
            self.target_x = float(x)
            self.target_y = float(y)
            self.delta_pool_x = 0.0
            self.delta_pool_y = 0.0
        if self.controller:
            self.controller.set_position(int(round(x)), int(round(y)))

    def _loop(self):
        """Loop di interpolazione ad alta risoluzione a 120 FPS."""
        while self._running:
            t_start = time.perf_counter()
            dt = t_start - self._last_tick
            self._last_tick = t_start

            if self.enabled:
                with self._lock:
                    if self.is_absolute_mode:
                        # Interpolazione esponenziale verso il bersaglio assoluto
                        decay = 1.0 - math.exp(-self.smoothing_lambda * dt)
                        dx = (self.target_x - self.current_x) * decay
                        dy = (self.target_y - self.current_y) * decay

                        self.current_x += dx
                        self.current_y += dy

                        # Snap sub-pixel se vicinissimi al bersaglio per evitare micro-jitter
                        if abs(self.target_x - self.current_x) < 0.3:
                            self.current_x = self.target_x
                        if abs(self.target_y - self.current_y) < 0.3:
                            self.current_y = self.target_y

                        out_x = int(round(self.current_x))
                        out_y = int(round(self.current_y))
                        send_absolute = True
                    else:
                        # Svuotamento fluido del pool di delta relativi
                        decay = 1.0 - math.exp(-self.smoothing_lambda * dt)
                        step_x_f = self.delta_pool_x * decay
                        step_y_f = self.delta_pool_y * decay
                        self.delta_pool_x -= step_x_f
                        self.delta_pool_y -= step_y_f

                        step_x = int(round(step_x_f))
                        step_y = int(round(step_y_f))
                        send_absolute = False

                if self.controller:
                    if send_absolute:
                        self.controller.set_position(out_x, out_y)
                    elif step_x != 0 or step_y != 0:
                        self.controller.move(step_x, step_y)

            # Controllo cadenza ad alta precisione
            elapsed = time.perf_counter() - t_start
            sleep_time = self.update_interval - elapsed
            if sleep_time > 0.001:
                time.sleep(sleep_time)


# ==============================================================================
# INIZIALIZZAZIONE COMPONENTI DI SISTEMA
# ==============================================================================
# 1. Filtro AHRS Madgwick (IMU 6-DOF con beta dinamico adattivo)
ahrs_filter = AHRSFilter(sample_rate_hz=20.0, beta=0.1, use_magnetometer=False)

# 2. Rivelatore Gesture Anti-Jumping con isolamento asse Roll
gesture_detector = GestureDetector(
    sample_rate_hz=20.0,
    roll_speed_threshold_deg=100.0,
    gyro_norm_threshold_rad=2.2,
    freeze_hold_time_s=0.35,
    freeze_on_roll_only=True
)

# 3. Calibratore Schermo Multi-Monitor e C-D Gain
screen_calibrator = ScreenCalibrator(
    ref_width=1920,
    ref_height=1080,
    base_lambda=60.0,
    max_yaw_deg=25.0,
    max_pitch_deg=18.0,
    calibration_samples=40  # 40 campioni = 2 secondi di fermo a 20 Hz
)

# 4. Controller Hardware Cursore Mouse PC
mouse_controller = MouseController()

# 5. Mappatore Cinematica con 1€ Filter e Sigmoide Modificata
mouse_mapper = MouseMapper(
    screen_width=screen_calibrator.screen_width,
    screen_height=screen_calibrator.screen_height,
    origin_x=screen_calibrator.origin_x,
    origin_y=screen_calibrator.origin_y,
    max_yaw_deg=screen_calibrator.max_yaw_deg,
    max_pitch_deg=screen_calibrator.max_pitch_deg,
    rx=screen_calibrator.cd_params["rx"],
    ry=screen_calibrator.cd_params["ry"],
    lambda_x=screen_calibrator.cd_params["lambda_x"],
    lambda_y=screen_calibrator.cd_params["lambda_y"],
    factor_x=screen_calibrator.cd_params["factor_x"],
    factor_y=screen_calibrator.cd_params["factor_y"],
    deadzone_deg=0.12,
    invert_x=True,
    invert_y=True,
    scale_factor=1.0,
    use_one_euro=True,
    one_euro_min_cutoff=0.8,
    one_euro_beta=0.015
)

# 6. Motore di Interpolazione a 120 Hz
smooth_engine = SmoothCursorEngine(
    controller=mouse_controller if ENABLE_MOUSE_CONTROL else None,
    update_hz=120.0,
    smoothing_lambda=32.0
)
if ENABLE_MOUSE_CONTROL:
    smooth_engine.start()

# 7. Server di Pairing Automatico
pairing = PairingServer(name="AirMouse receiver V2", udp_port=PORT)
pairing.start()



def get_local_ip() -> str:
    """Restituisce l'IP locale della scheda di rete attiva."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def print_banner(ip: str):
    """Stampa l'intestazione grafica e la guida ai comandi da tastiera."""
    print("=" * 82)
    print("  🚀 AIRMOUSE RECEIVER V2 - ULTRA-FLUID & HIGH-PRECISION TRACKING 🚀")
    print("=" * 82)
    print(f"  IP del PC:              {ip}")
    print(f"  Porta UDP Dati:         {PORT}")
    print(f"  Pairing Server:         ATTIVO (UDP {pairing.discovery_port}, TCP {pairing.tcp_port})")
    print(f"  Driver Mouse:           {mouse_controller.backend_name.upper()} (Win32 Zero-Latency)")
    print(f"  Motore Interpolazione:  120 Hz SmoothCursorEngine (ATTIVO)")
    print(f"  Filtro Anti-Jitter:     Filtro 1€ (One Euro Filter ACM CHI 2012) [ATTIVO]")
    print(f"  Stream IMU:             ZERO-LATENCY RAW (0 ms delay) [R: toggle Wavelet]")
    print(f"  Monitor Rilevati:       {len(screen_calibrator.monitors)}")
    for m in screen_calibrator.monitors:
        active_tag = " [*ATTIVO*]" if m['index'] == screen_calibrator.active_monitor_index else ""
        prim_tag = " (Primario)" if m['is_primary'] else " (Secondario)"
        print(f"    - Monitor {m['index']+1}{prim_tag}: {m['width']}x{m['height']} px | "
              f"origin: ({m['left']}, {m['top']}) | centro: ({m['center_x']}, {m['center_y']}){active_tag}")
    print(f"  C-D Gain Parametri:     Max Gomito: [Yaw: ±{screen_calibrator.max_yaw_deg}°, Pitch: ±{screen_calibrator.max_pitch_deg}°]")
    print("-" * 82)
    print("  COMANDI RAPIDI DA TASTIERA:")
    print("    [SPAZIO] / [C]        -> Quick Re-Center (centra il cursore e resetta l'assetto)")
    print("    [S] / [TAB]           -> Switch Monitor (cambia display attivo ciclicamente)")
    print("    [M]                   -> Toggle Modalità (Assoluta Boresight <-> Relativa Delta)")
    print("    [F]                   -> Toggle 120 Hz Smooth Engine (Fluidità ON / OFF)")
    print("    [O]                   -> Toggle Filtro 1€ vs EMA Adattivo")
    print("    [R]                   -> Toggle Stream IMU: Zero-Latency Raw vs Wavelet")
    print("    [+] / [-]             -> Regolazione fine sensibilità (±0.05)")
    print("    [1] / [2] / [3]       -> Preset: [1] Precisione (0.7x), [2] Bilanciato (1.0x), [3] Veloce (1.35x)")
    print("    [V]                   -> Toggle Verbose Console HUD")
    print("    [Q] / [ESC]           -> Chiusura sicura applicazione")
    print("=" * 82)


# ==============================================================================
# CICLO PRINCIPALE DI RICEZIONE E TRACKING
# ==============================================================================
def main():
    global USE_DENOISED_DEFAULT, USE_ABSOLUTE_BORESIGHT

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    sock.settimeout(0.5)

    ip = get_local_ip()
    print_banner(ip)

    use_denoised = USE_DENOISED_DEFAULT
    verbose_hud = False
    running = True

    try:
        while running:
            # 1. Attesa connessione e associazione dello smartwatch tramite pairing TCP
            print("\nIn attesa di associazione con lo smartwatch Wear OS...")
            pairing.wait_until_paired()
            peer = pairing.peer
            if peer:
                print(f"  Smartwatch Connesso: \"{peer.get('name', 'Watch')}\" ({peer.get('ip', 'N/D')})\n")

            # 2. Sincronizzazione monitor attivo rilevando dove si trova il cursore dell'utente
            if screen_calibrator.sync_active_monitor_from_cursor():
                mouse_mapper.update_params(
                    screen_width=screen_calibrator.screen_width,
                    screen_height=screen_calibrator.screen_height,
                    origin_x=screen_calibrator.origin_x,
                    origin_y=screen_calibrator.origin_y,
                    rx=screen_calibrator.cd_params["rx"],
                    ry=screen_calibrator.cd_params["ry"],
                    lambda_x=screen_calibrator.cd_params["lambda_x"],
                    lambda_y=screen_calibrator.cd_params["lambda_y"],
                    factor_x=screen_calibrator.cd_params["factor_x"],
                    factor_y=screen_calibrator.cd_params["factor_y"]
                )
                print(f"  🖥️  Rilevato cursore su Monitor {screen_calibrator.active_monitor_index + 1} "
                      f"({screen_calibrator.screen_width}x{screen_calibrator.screen_height} px) -> Sincronizzato!")

            # 3. Avvio calibrazione statica iniziale (2 secondi a braccio fermo)
            screen_calibrator.start_static_calibration()
            ahrs_filter.reset()
            gesture_detector.reset()

            print("=" * 82)
            print("  🎯 FASE DI CALIBRAZIONE STATICA INIZIALE (2.0 Secondi) 🎯")
            print(f"  Punta il braccio dritto in avanti al centro del Monitor {screen_calibrator.active_monitor_index + 1}.")
            print("  Rimani immobile per calcolare lo zero-bias del giroscopio e la posa neutra...")
            print("=" * 82)

            count, lost, last_seq = 0, 0, None
            last_report = time.time()
            last_hud_time = time.time()
            prev_t_ms = None
            yaw, pitch, roll = 0.0, 0.0, 0.0

            # 4. Loop ricezione pacchetti UDP per lo smartwatch correntemente associato
            while pairing.paired and running:
                try:
                    data, addr = sock.recvfrom(2048)
                except socket.timeout:
                    # Controllo tasti durante attesa socket
                    if msvcrt and msvcrt.kbhit():
                        k = msvcrt.getch()
                        if k in (b'q', b'Q', b'\x1b'):
                            running = False
                            break
                    continue

                if not pairing.is_paired_addr(addr):
                    continue

                try:
                    p = json.loads(data.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                # Calcolo sequenza pacchetti persi
                if last_seq is not None and p["seq"] > last_seq + 1:
                    lost += p["seq"] - last_seq - 1
                last_seq = p["seq"]

                # Estrazione dati IMU
                a, g, m = p["acc"], p["gyro"], p["mag"]
                raw = p.get("raw", [])
                acc_raw = raw[0:3] if len(raw) >= 3 else a
                gyro_raw = raw[3:6] if len(raw) >= 6 else g

                acc_input = a if use_denoised else acc_raw
                gyro_input = g if use_denoised else gyro_raw
                mag_input = m

                # Calcolo intervallo temporale esatto dt dal timestamp dell'orologio
                t_ms = p["t"]
                if prev_t_ms is not None and t_ms > prev_t_ms:
                    dt = (t_ms - prev_t_ms) / 1000.0
                    # Protezione da jitter anomali o perdita prolungata
                    dt = max(0.01, min(0.15, dt))
                else:
                    dt = 0.05
                prev_t_ms = t_ms

                # --------------------------------------------------------------
                # FASE A: Calibrazione Statica a Riposo (2 secondi)
                # --------------------------------------------------------------
                if not screen_calibrator.is_calibrated:
                    temp_euler = ahrs_filter.update(acc_input, gyro_input, mag_input, dt=dt)
                    is_completed = screen_calibrator.add_calibration_sample(gyro_input, temp_euler)
                    pct = screen_calibrator.progress_percentage
                    print(f"  Calibrazione in corso: {pct:5.1f}% | campioni: {screen_calibrator._samples_count}/{screen_calibrator.calibration_samples}", end="\r")

                    if is_completed:
                        print("\n" + "=" * 82)
                        print("  ✅ CALIBRAZIONE COMPLETATA CON SUCCESSO!")
                        print(f"  Bias Giroscopio (rad/s): [{screen_calibrator.gyro_bias[0]:+.4f}, "
                              f"{screen_calibrator.gyro_bias[1]:+.4f}, {screen_calibrator.gyro_bias[2]:+.4f}]")
                        print(f"  Posa Neutra Centro: Yaw={screen_calibrator.zero_euler['yaw']:+.1f}°, "
                              f"Pitch={screen_calibrator.zero_euler['pitch']:+.1f}°")
                        print(f"  Cursore posizionato al centro del Monitor {screen_calibrator.active_monitor_index + 1} "
                              f"({screen_calibrator.center_x}, {screen_calibrator.center_y})")
                        print("  MOTION TRACKING ULTRA-FLUIDO ATTIVO! [Premi SPAZIO per ricentrare]")
                        print("=" * 82 + "\n")

                        # Centra fisicamente il cursore e allinea interpolatore e filtri
                        mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
                        mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
                        smooth_engine.snap_to(screen_calibrator.center_x, screen_calibrator.center_y)

                        yaw = temp_euler["yaw"]
                        pitch = temp_euler["pitch"]
                        roll = temp_euler["roll"]
                        gesture_detector.prev_yaw = yaw
                        gesture_detector.prev_pitch = pitch
                        gesture_detector.prev_roll = roll
                        last_report = time.time()
                    continue

                # --------------------------------------------------------------
                # FASE B: Gestione Interattiva Tastiera (Hotkeys)
                # --------------------------------------------------------------
                if msvcrt and msvcrt.kbhit():
                    key = msvcrt.getch()

                    if key in (b' ', b'c', b'C'):
                        # Quick Re-Center istantaneo
                        mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
                        screen_calibrator.recenter_pose({"yaw": yaw, "pitch": pitch, "roll": roll})
                        mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
                        smooth_engine.snap_to(screen_calibrator.center_x, screen_calibrator.center_y)
                        gesture_detector.prev_yaw = yaw
                        gesture_detector.prev_pitch = pitch
                        gesture_detector.prev_roll = roll
                        print(f"\n  🎯 [RE-CENTER] Cursore ricentrato al centro del Monitor {screen_calibrator.active_monitor_index + 1}!")

                    elif key in (b's', b'S', b'\t'):
                        # Switch Monitor Ciclico
                        screen_calibrator.switch_monitor()
                        mouse_mapper.update_params(
                            screen_width=screen_calibrator.screen_width,
                            screen_height=screen_calibrator.screen_height,
                            origin_x=screen_calibrator.origin_x,
                            origin_y=screen_calibrator.origin_y,
                            rx=screen_calibrator.cd_params["rx"],
                            ry=screen_calibrator.cd_params["ry"],
                            lambda_x=screen_calibrator.cd_params["lambda_x"],
                            lambda_y=screen_calibrator.cd_params["lambda_y"],
                            factor_x=screen_calibrator.cd_params["factor_x"],
                            factor_y=screen_calibrator.cd_params["factor_y"]
                        )
                        mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
                        mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
                        smooth_engine.snap_to(screen_calibrator.center_x, screen_calibrator.center_y)
                        screen_calibrator.recenter_pose({"yaw": yaw, "pitch": pitch, "roll": roll})
                        gesture_detector.prev_yaw = yaw
                        gesture_detector.prev_pitch = pitch
                        gesture_detector.prev_roll = roll
                        print(f"\n  🖥️ [SWITCH MONITOR] Passato a Monitor {screen_calibrator.active_monitor_index + 1} "
                              f"({screen_calibrator.screen_width}x{screen_calibrator.screen_height} px)")

                    elif key in (b'm', b'M'):
                        # Toggle Modalità Assoluta / Relativa
                        USE_ABSOLUTE_BORESIGHT = not USE_ABSOLUTE_BORESIGHT
                        mode_str = "ASSOLUTA (Boresight C-D Gain)" if USE_ABSOLUTE_BORESIGHT else "RELATIVA (Delta Accumulator)"
                        print(f"\n  🔄 [MODALITÀ] Attivata: {mode_str}")

                    elif key in (b'f', b'F'):
                        # Toggle 120 Hz Smooth Engine
                        smooth_engine.enabled = not smooth_engine.enabled
                        state_str = "ATTIVATO (120 FPS Interpolation)" if smooth_engine.enabled else "DISATTIVATO (20 FPS Direct)"
                        print(f"\n  ✨ [SMOOTH ENGINE] {state_str}")

                    elif key in (b'o', b'O'):
                        # Toggle Filtro 1€ vs EMA
                        mouse_mapper.use_one_euro = not mouse_mapper.use_one_euro
                        filter_str = "1€ Filter (Adaptive ACM CHI 2012)" if mouse_mapper.use_one_euro else "Filtro Adattivo EMA Standard"
                        print(f"\n  🛡️ [FILTRO ANTI-JITTER] Selezionato: {filter_str}")

                    elif key in (b'r', b'R'):
                        # Toggle Zero-Latency Raw vs Wavelet
                        use_denoised = not use_denoised
                        stream_str = "WAVELET DENOISED (200 ms buffer)" if use_denoised else "ZERO-LATENCY RAW (0 ms delay)"
                        print(f"\n  ⚡ [STREAM IMU] Selezionato: {stream_str}")

                    elif key in (b'+', b'='):
                        # Aumento sensibilità
                        mouse_mapper.scale_factor = round(mouse_mapper.scale_factor + 0.05, 2)
                        print(f"\n  📈 [SENSIBILITÀ] scale_factor = {mouse_mapper.scale_factor:.2f}")

                    elif key in (b'-', b'_'):
                        # Diminuzione sensibilità
                        mouse_mapper.scale_factor = max(0.2, round(mouse_mapper.scale_factor - 0.05, 2))
                        print(f"\n  📉 [SENSIBILITÀ] scale_factor = {mouse_mapper.scale_factor:.2f}")

                    elif key == b'1':
                        # Preset Precisione
                        mouse_mapper.scale_factor = 0.70
                        mouse_mapper.deadzone_deg = 0.18
                        print(f"\n  🎯 [PRESET 1] Precisione / Desktop Standard (scale: 0.70, deadzone: 0.18°)")

                    elif key == b'2':
                        # Preset Bilanciato
                        mouse_mapper.scale_factor = 1.00
                        mouse_mapper.deadzone_deg = 0.12
                        print(f"\n  ⚖️ [PRESET 2] Bilanciato (scale: 1.00, deadzone: 0.12°)")

                    elif key == b'3':
                        # Preset Veloce
                        mouse_mapper.scale_factor = 1.35
                        mouse_mapper.deadzone_deg = 0.08
                        print(f"\n  ⚡ [PRESET 3] Veloce / Schermi Grandi & Ultrawide (scale: 1.35, deadzone: 0.08°)")

                    elif key in (b'v', b'V'):
                        verbose_hud = not verbose_hud
                        print(f"\n  📊 [CONSOLE HUD] Verbose = {verbose_hud}")

                    elif key in (b'q', b'Q', b'\x1b'):
                        print("\nRichiesta chiusura da tastiera...")
                        running = False
                        break

                # --------------------------------------------------------------
                # FASE C: Correzione Bias e Stima Orientamento AHRS Madgwick
                # --------------------------------------------------------------
                gyro_calibrated = screen_calibrator.apply_bias_correction(gyro_input)

                # Madgwick con dt reale e scalatura adattiva di beta
                euler = ahrs_filter.update(acc_input, gyro_calibrated, mag_input, dt=dt)
                pitch = euler["pitch"]
                yaw = euler["yaw"]
                roll = euler["roll"]

                # --------------------------------------------------------------
                # FASE D: Valutazione Macchina a Stati Anti-Jumping
                # --------------------------------------------------------------
                state, is_frozen, deltas = gesture_detector.update(
                    pitch=pitch,
                    yaw=yaw,
                    roll=roll,
                    gyro=gyro_calibrated,
                    dt=dt
                )
                d_pitch = deltas["d_pitch"]
                d_yaw = deltas["d_yaw"]
                d_roll = deltas["d_roll"]

                # --------------------------------------------------------------
                # FASE E: Mappatura Cinematica C-D Gain e Movimento Mouse
                # --------------------------------------------------------------
                if USE_ABSOLUTE_BORESIGHT:
                    zero_yaw = screen_calibrator.zero_euler["yaw"]
                    zero_pitch = screen_calibrator.zero_euler["pitch"]

                    target_x, target_y = mouse_mapper.map_absolute(
                        yaw=yaw,
                        pitch=pitch,
                        zero_yaw=zero_yaw,
                        zero_pitch=zero_pitch,
                        is_frozen=is_frozen,
                        dt=dt
                    )
                    dx_float = float(target_x - screen_calibrator.center_x)
                    dy_float = float(target_y - screen_calibrator.center_y)

                    if ENABLE_MOUSE_CONTROL:
                        if smooth_engine.enabled:
                            smooth_engine.set_target(target_x, target_y, is_absolute=True)
                        else:
                            mouse_controller.set_position(target_x, target_y)
                else:
                    dx_float, dy_float = mouse_mapper.map_delta(
                        d_yaw=d_yaw,
                        d_pitch=d_pitch,
                        is_frozen=is_frozen
                    )
                    if ENABLE_MOUSE_CONTROL:
                        if smooth_engine.enabled:
                            smooth_engine.set_target(dx_float, dy_float, is_absolute=False)
                        else:
                            step_x, step_y = mouse_mapper.get_pixel_steps(dx_float, dy_float)
                            if step_x != 0 or step_y != 0:
                                mouse_controller.move(step_x, step_y)
                    target_x = int(round(mouse_mapper.curr_x))
                    target_y = int(round(mouse_mapper.curr_y))


                # --------------------------------------------------------------
                # FASE G: Console HUD Throttled a 10 Hz (Non-Bloccante)
                # --------------------------------------------------------------
                now = time.time()
                count += 1

                if verbose_hud:
                    state_tag = "[FREEZE]" if is_frozen else "[TRACK ]"
                    print(
                        f"#{p['seq']:6d} | {state_tag} {state:<14} | "
                        f"POS [{target_x:4d}, {target_y:4d}] | "
                        f"ANG [P:{pitch:+5.1f}° Y:{yaw:+5.1f}° R:{roll:+5.1f}°] | "
                        f"SCALE {mouse_mapper.scale_factor:.2f}"
                    )
                else:
                    if now - last_hud_time >= 0.10:  # 10 Hz refresh
                        state_tag = "❄️ FREEZE" if is_frozen else "🎯 TRACK "
                        stream_tag = "WAVELET" if use_denoised else "RAW 0ms"
                        interp_tag = "120Hz" if smooth_engine.enabled else "20Hz"
                        filt_tag = "1€" if mouse_mapper.use_one_euro else "EMA"

                        print(
                            f"  {state_tag} | POS: ({target_x:4d}, {target_y:4d}) | "
                            f"YAW: {yaw:+5.1f}° PIT: {pitch:+5.1f}° | "
                            f"SCALE: {mouse_mapper.scale_factor:.2f} | "
                            f"[{interp_tag} | {filt_tag} | {stream_tag}]",
                            end="\r"
                        )
                        last_hud_time = now

                # Statistiche periodiche throughput a 1.0s
                if now - last_report >= 1.0:
                    fps = count / (now - last_report)
                    count = 0
                    last_report = now
                    if verbose_hud:
                        print(f"--- Throughput: {fps:.1f} Hz da {addr[0]} | Pacchetti persi: {lost} ---")

            if running and not pairing.paired:
                print("\n\n  ⚠️ Smartwatch disconnesso o sessione terminata. Ritorno in attesa di pairing...")
                mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
                smooth_engine.snap_to(screen_calibrator.center_x, screen_calibrator.center_y)

    except KeyboardInterrupt:
        print("\n\nInterruzione utente (Ctrl+C).")
    finally:
        print("\nChiusura ordinata delle risorse in corso...")
        smooth_engine.stop()
        pairing.stop()
        sock.close()
        print("Sessione completata.")


if __name__ == "__main__":
    main()
# --- END [11/10/2026] Step 6: Ricevitore Avanzato reciverV2.py con 120Hz Smooth Interpolator, 1€ Filter e Zero-Latency Stream ---
