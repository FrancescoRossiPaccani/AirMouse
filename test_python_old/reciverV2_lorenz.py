# --- START [18/10/2026] Ottimizzazioni Fluidita' Estrema & Parametri Solo Lato Codice (reciverV2_lorenz.py) ---
"""
reciverV2_lorenz.py: Ricevitore AirMouse Ultra-Fluido con Stabilizzatore a Bolla Spaziale Soft-Edge,
Interpolazione Critically Damped (SmoothDamp a 120 Hz) e Timer ad Alta Risoluzione Win32 (1 ms).

Miglioramenti chiave implementati per la massima fluidità:
1. Timer ad Alta Risoluzione Win32 (timeBeginPeriod a 1 ms):
   Elimina il vincolo del timer a 15.6 ms di Windows, garantendo cadenza esatta a 120 FPS.
2. SmoothCursorEngine con SmoothDamp (Molla Criticamente Smorzata di 2° ordine):
   Sostituisce il decadimento esponenziale semplice. Traccia simultaneamente posizione e velocità
   (continuità C^1), eliminando i micro-rallentamenti a 20 Hz e l'effetto elastico.
3. Stabilizzatore Spaziale Soft-Edge con Funzione Hermite Smoothstep:
   Zona di quiete a riposo (r_inner = 2.5 px) per azzerare il tremolio fisiologico,
   con transizione continua e morbida verso il movimento libero (r_outer = 7.0 px) senza scalini di breakout.
   Integrazione istantanea con l'Anti-Jumping gesture freeze.
4. De-stratificazione del Filtraggio (Zero Phase Lag):
   La mappatura cinematica opera alla massima reattività, delegando l'interpolazione continua
   esclusivamente al motore ad alta frequenza a 120 Hz.
5. Parametri Configurabili Solo Lato Codice:
   Tutti i parametri operativi sono raggruppati all'inizio del file. A runtime sono attivi
   esclusivamente i comandi minimi di sistema ([SPAZIO/C] per ricentrare e [Q/ESC] per uscire).
"""

import asyncio
import collections
import logging
import math
import os
import struct
import sys
import threading
import time

# Assicura che la root del progetto sia in sys.path
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

# Configura codifica UTF-8 su console Windows per evitare problemi di encoding
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Fix per bless su Windows: evita l'apertura a basso livello di BLEAdapter
try:
    import bless.backends.winrt.server
    bless.backends.winrt.server.BLEAdapter = lambda: None
except Exception:
    pass

from bless import (
    BlessGATTCharacteristic,
    BlessServer,
    GATTAttributePermissions,
    GATTCharacteristicProperties,
)

# Moduli interni del tracking (dal package motionTrackingModule)
from motionTrackingModule.ahrs import AHRSFilter
from motionTrackingModule.gesture_detector import GestureDetector
from motionTrackingModule.mouse_mapper import MouseMapper
from motionTrackingModule.mouse_controller import MouseController
from motionTrackingModule.screen_calibrator import ScreenCalibrator

try:
    import msvcrt
except ImportError:
    msvcrt = None


def poll_keyboard_key():
    """Legge un carattere da tastiera in modo non bloccante (cross-platform)."""
    if msvcrt and msvcrt.kbhit():
        return msvcrt.getch()
    if sys.platform != "win32":
        try:
            import select
            if select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1)
                return ch.encode("utf-8", errors="ignore")
        except Exception:
            pass
    return None


# ==============================================================================
# PARAMETRI DI CONFIGURAZIONE APPLICAZIONE (CONFIGURABILI ESCLUSIVAMENTE QUI)
# ==============================================================================

# 1. Configurazione Server BLE GATT (Identici allo smartwatch BleClient.kt)
SERVER_NAME            = "AirMouse-PC"
SERVICE_UUID           = "7a1c0001-4f5e-4b8a-9d3c-2e6f1a0b5c01"
DATA_UUID              = "7a1c0002-4f5e-4b8a-9d3c-2e6f1a0b5c01"
CTRL_UUID              = "7a1c0003-4f5e-4b8a-9d3c-2e6f1a0b5c01"
SIZE_CLEAN             = 44     # seq (4) + t (4) + 9 floats puliti (36)
SIZE_FULL              = 80     # 44 + 9 floats raw (36)

# 2. Controllo e Modalità del Mouse
ENABLE_MOUSE_CONTROL   = True   # True: pilota fisicamente il mouse del PC; False: solo visualizzazione
USE_ABSOLUTE_BORESIGHT = True   # True: Assoluta Boresight (consigliata); False: Relativa Delta

# 3. Flusso Dati Sensori Smartwatch
USE_DENOISED_STREAM    = False  # False: ZERO-LATENCY RAW (0 ms delay); True: WAVELET DENOISED (~200 ms lag)

# 4. Motore ad Altissima Fluidità (SmoothCursorEngine 120 Hz con SmoothDamp)
CURSOR_ENGINE_ENABLED  = True   # True: interpolatore continuo attivo; False: aggiornamento diretto 20 Hz
CURSOR_ENGINE_HZ       = 120.0  # Frequenza interpolazione (120.0, 144.0, o 240.0 Hz)
SMOOTH_DAMP_TIME_S     = 0.026  # Costante di tempo SmoothDamp in secondi (0.022 - 0.032 s per fluidità massima)
HIGH_PRECISION_TIMER   = True   # True: forza il timer di Windows a 1.0 ms (timeBeginPeriod)

# 5. Stabilizzatore a Bolla Spaziale Soft-Edge (Zero Tremolio & Uscita Fluida)
BUBBLE_ENABLED         = True   # True: elimina il tremolio a riposo con deadzone Hermite Smoothstep
BUBBLE_INNER_RADIUS_PX = 2.5    # Raggio interno (pixel): sotto questa distanza il cursore è immobile al 100%
BUBBLE_OUTER_RADIUS_PX = 7.0    # Raggio esterno (pixel): oltre questa distanza movimento libero al 100%
BUBBLE_STILL_TIME_S    = 0.15   # Tempo a riposo (secondi) per fissare una nuova ancora

# 6. Sensibilità e Parametri Cinematici C-D Gain (MouseMapper)
SCALE_FACTOR           = 1.00   # Fattore di moltiplicazione della sensibilità complessiva (es. 0.8x, 1.0x, 1.25x)
DEADZONE_DEG           = 0.06   # Micro-deadzone angolare del braccio in gradi (0.05° - 0.10°)
MAX_YAW_DEG            = 25.0   # Angolo massimo orizzontale del gomito in gradi
MAX_PITCH_DEG          = 18.0   # Angolo massimo verticale del gomito in gradi

# 7. Macchina a Stati Anti-Jumping & Rilevamento Gesture
GESTURE_GYRO_NORM_RAD  = 1.8    # Soglia magnitudine velocità angolare in rad/s (~103°/s) per freeze click/gesto
GESTURE_ROLL_SPEED_DEG = 100.0  # Soglia velocità angolare su asse Roll in °/s
GESTURE_FREEZE_HOLD_S  = 0.35   # Durata minima del blocco cursore durante il gesto (350 ms)

# 8. Console HUD
VERBOSE_HUD            = False  # False: HUD compatto su riga singola (\r); True: scroll dettagliato


# ==============================================================================
# TIMER AD ALTA PRECISIONE WINDOWS (1.0 ms)
# ==============================================================================
if sys.platform == "win32" and HIGH_PRECISION_TIMER:
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass


# ==============================================================================
# MODULO: STABILIZZATORE A BOLLA SPAZIALE SOFT-EDGE (Hermite Smoothstep)
# ==============================================================================
class SpatialBubbleStabilizer:
    """
    Stabilizzatore spaziale Soft-Edge con transizione Hermite Smoothstep continua C^1.
    
    - Sotto r_inner (es. 2.5 px): soppressione 100% (zero tremolio fisiologico a riposo).
    - Tra r_inner e r_outer: transizione sigmoidea dolce (w = 3t^2 - 2t^3) che elimina ogni scalino di breakout.
    - Oltre r_outer: movimento libero e reattivo al 100%.
    - Se is_frozen == True: blocco istantaneo dell'ancoraggio per tutta la durata del gesto.
    """

    def __init__(self, r_inner_px: float = 2.5, r_outer_px: float = 7.0, still_time_s: float = 0.15):
        self.enabled = BUBBLE_ENABLED
        self.r_inner_px = float(r_inner_px)
        self.r_outer_px = max(float(r_inner_px) + 0.5, float(r_outer_px))
        self.still_time_s = float(still_time_s)

        self.is_anchored = False
        self.anchor_x = 0.0
        self.anchor_y = 0.0
        self.last_target_x = 0.0
        self.last_target_y = 0.0
        self.last_move_time = time.perf_counter()

    @staticmethod
    def _smoothstep(e0: float, e1: float, x: float) -> float:
        """Funzione di interpolazione Hermite cubica con derivata nulla agli estremi."""
        t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
        return t * t * (3.0 - 2.0 * t)

    def reset(self, initial_x: float, initial_y: float):
        """Re-inizializza l'ancoraggio su una coordinata specificata."""
        self.anchor_x = float(initial_x)
        self.anchor_y = float(initial_y)
        self.last_target_x = float(initial_x)
        self.last_target_y = float(initial_y)
        self.is_anchored = True
        self.last_move_time = time.perf_counter()

    def disable_anchor(self):
        """Disattiva i cerchi concentrici dello stabilizzatore (es. durante la pausa)."""
        self.is_anchored = False

    def update(self, raw_target_x: float, raw_target_y: float, is_frozen: bool = False) -> tuple[float, float, str]:
        """
        Processa la coordinata calcolata dal MouseMapper applicando la deadzone morbida.
        Ritorna: (out_x, out_y, stato_stringa)
        """
        if not self.enabled:
            return raw_target_x, raw_target_y, "BYPASS"

        raw_x = float(raw_target_x)
        raw_y = float(raw_target_y)

        # 1. Blocco prioritario durante gesture / click (Anti-Jumping)
        if is_frozen:
            self.anchor_x = raw_x
            self.anchor_y = raw_y
            self.last_target_x = raw_x
            self.last_target_y = raw_y
            self.is_anchored = True
            self.last_move_time = time.perf_counter()
            return self.anchor_x, self.anchor_y, "GEST_FREEZE"

        now = time.perf_counter()
        dist = math.hypot(raw_x - self.anchor_x, raw_y - self.anchor_y)
        self.last_target_x = raw_x
        self.last_target_y = raw_y

        # 2. Zona di quiete assoluta (Zero Tremolio)
        if dist <= self.r_inner_px:
            self.is_anchored = True
            return self.anchor_x, self.anchor_y, "ANCHOR_STILL"

        # 3. Zona di transizione morbida continua (Smoothstep)
        elif dist < self.r_outer_px:
            w = self._smoothstep(self.r_inner_px, self.r_outer_px, dist)
            out_x = self.anchor_x + w * (raw_x - self.anchor_x)
            out_y = self.anchor_y + w * (raw_y - self.anchor_y)
            # Trascina dolcemente l'ancora nella direzione del movimento
            self.anchor_x += (out_x - self.anchor_x) * 0.20
            self.anchor_y += (out_y - self.anchor_y) * 0.20
            self.is_anchored = False
            return out_x, out_y, "SOFT_TRANS"

        # 4. Movimento libero (l'ancora segue fedelmente il cursore)
        else:
            self.is_anchored = False
            self.anchor_x = raw_x
            self.anchor_y = raw_y
            self.last_move_time = now
            return raw_x, raw_y, "MOVING"


# ==============================================================================
# MOTORE DI INTERPOLAZIONE AD ALTA FLUIDITÀ 120 HZ (SmoothDamp Second-Order)
# ==============================================================================
class SmoothCursorEngine:
    """
    Motore asincrono ad alta frequenza (120 Hz) basato su Second-Order Critically
    Damped Spring (SmoothDamp) per il movimento continuo e ultra-fluido del cursore del mouse.
    Garantisce continuità sia di posizione che di velocità (C^1), eliminando i micro-scalini a 20 Hz.
    """

    def __init__(self, controller: MouseController, update_hz: float = 120.0, smooth_time_s: float = 0.026):
        self.controller = controller
        self.update_interval = 1.0 / max(30.0, float(update_hz))
        self.smooth_time_s = float(smooth_time_s)
        self.enabled = CURSOR_ENGINE_ENABLED
        self.is_paused = False

        self.target_x = 0.0
        self.target_y = 0.0
        self.current_x = 0.0
        self.current_y = 0.0
        self.vel_x = 0.0
        self.vel_y = 0.0

        self.delta_pool_x = 0.0
        self.delta_pool_y = 0.0
        self.is_absolute_mode = True

        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._last_tick = time.perf_counter()

    @staticmethod
    def _smooth_damp_1d(current: float, target: float, current_vel: float, smooth_time: float, dt: float) -> tuple[float, float]:
        """
        Calcola lo smorzamento critico di secondo ordine per una dimensione.
        Garantisce raggiungimento morbido del target senza oscillazioni o overshoot.
        """
        smooth_time = max(0.0001, smooth_time)
        omega = 2.0 / smooth_time
        x = omega * dt
        exp = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
        change = current - target
        temp = (current_vel + omega * change) * dt
        new_vel = (current_vel - omega * temp) * exp
        new_pos = target + (change + temp) * exp
        return new_pos, new_vel

    def start(self):
        """Avvia il thread di interpolazione ad alta frequenza."""
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

    def pause(self):
        """Mette in pausa l'interpolatore rilasciando il controllo del cursore per lasciare libero il mouse."""
        with self._lock:
            self.is_paused = True

    def resume(self):
        """Riprende il ciclo di interpolazione del cursore dopo una pausa."""
        with self._lock:
            self.is_paused = False
            self.vel_x = 0.0
            self.vel_y = 0.0
            self._last_tick = time.perf_counter()

    def set_target(self, x: float, y: float, is_absolute: bool = True):
        """Aggiorna le coordinate bersaglio ricevute dal thread di ricezione BLE."""
        with self._lock:
            self.is_absolute_mode = is_absolute
            if is_absolute:
                self.target_x = float(x)
                self.target_y = float(y)
            else:
                self.delta_pool_x += float(x)
                self.delta_pool_y += float(y)

    def snap_to(self, x: float, y: float):
        """Riallinea istantaneamente la posizione del cursore e azzera la velocità residua."""
        with self._lock:
            self.current_x = float(x)
            self.current_y = float(y)
            self.target_x = float(x)
            self.target_y = float(y)
            self.vel_x = 0.0
            self.vel_y = 0.0
            self.delta_pool_x = 0.0
            self.delta_pool_y = 0.0
            self._last_tick = time.perf_counter()
            paused = self.is_paused
        if not paused and self.controller:
            self.controller.set_position(int(round(x)), int(round(y)))

    def _loop(self):
        """Loop di interpolazione ultra-fluida continuo a 120 Hz."""
        while self._running:
            t_start = time.perf_counter()
            dt = t_start - self._last_tick
            self._last_tick = t_start
            dt = max(0.001, min(0.05, dt))

            with self._lock:
                paused = self.is_paused
            if paused:
                time.sleep(0.01)
                continue

            if self.enabled:
                with self._lock:
                    if self.is_absolute_mode:
                        self.current_x, self.vel_x = self._smooth_damp_1d(
                            self.current_x, self.target_x, self.vel_x, self.smooth_time_s, dt
                        )
                        self.current_y, self.vel_y = self._smooth_damp_1d(
                            self.current_y, self.target_y, self.vel_y, self.smooth_time_s, dt
                        )
                        out_x = int(round(self.current_x))
                        out_y = int(round(self.current_y))
                        send_absolute = True
                    else:
                        decay = 1.0 - math.exp(-32.0 * dt)
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

            elapsed = time.perf_counter() - t_start
            sleep_time = self.update_interval - elapsed
            if sleep_time > 0.0005:
                time.sleep(sleep_time)


# ==============================================================================
# INIZIALIZZAZIONE COMPONENTI DI SISTEMA
# ==============================================================================
ahrs_filter = AHRSFilter(sample_rate_hz=20.0, beta=0.1, use_magnetometer=False)

gesture_detector = GestureDetector(
    sample_rate_hz=20.0,
    roll_speed_threshold_deg=GESTURE_ROLL_SPEED_DEG,
    gyro_norm_threshold_rad=GESTURE_GYRO_NORM_RAD,
    freeze_hold_time_s=GESTURE_FREEZE_HOLD_S,
    freeze_on_roll_only=False
)

screen_calibrator = ScreenCalibrator(
    ref_width=1920,
    ref_height=1080,
    base_lambda=60.0,
    max_yaw_deg=MAX_YAW_DEG,
    max_pitch_deg=MAX_PITCH_DEG,
    calibration_samples=40  # 40 campioni = 2 secondi a riposo per calibrare bias
)

mouse_controller = MouseController()

# Configurazione MouseMapper: alpha elevato (0.90 - 1.0) per eliminare il ritardo di fase,
# delegando la fluidità temporale interamente a SmoothCursorEngine a 120 Hz
mouse_mapper = MouseMapper(
    screen_width=screen_calibrator.screen_width,
    screen_height=screen_calibrator.screen_height,
    origin_x=screen_calibrator.origin_x,
    origin_y=screen_calibrator.origin_y,
    max_yaw_deg=MAX_YAW_DEG,
    max_pitch_deg=MAX_PITCH_DEG,
    rx=screen_calibrator.cd_params["rx"],
    ry=screen_calibrator.cd_params["ry"],
    lambda_x=screen_calibrator.cd_params["lambda_x"],
    lambda_y=screen_calibrator.cd_params["lambda_y"],
    factor_x=screen_calibrator.cd_params["factor_x"],
    factor_y=screen_calibrator.cd_params["factor_y"],
    deadzone_deg=DEADZONE_DEG,
    invert_x=True,
    invert_y=True,
    scale_factor=SCALE_FACTOR,
    smooth_min_alpha=0.90,
    smooth_max_alpha=1.00
)

# Inizializzazione dello Stabilizzatore Spaziale Soft-Edge
bubble_stabilizer = SpatialBubbleStabilizer(
    r_inner_px=BUBBLE_INNER_RADIUS_PX,
    r_outer_px=BUBBLE_OUTER_RADIUS_PX,
    still_time_s=BUBBLE_STILL_TIME_S
)

# Inizializzazione Motore SmoothDamp a 120 Hz
smooth_engine = SmoothCursorEngine(
    controller=mouse_controller if ENABLE_MOUSE_CONTROL else None,
    update_hz=CURSOR_ENGINE_HZ,
    smooth_time_s=SMOOTH_DAMP_TIME_S
)
if ENABLE_MOUSE_CONTROL and CURSOR_ENGINE_ENABLED:
    smooth_engine.start()


# ==============================================================================
# STATO DI SESSIONE E TRACKING
# ==============================================================================
class SessionState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.count = 0
        self.lost = 0
        self.last_seq = None
        self.last_report = time.time()
        self.last_hud_time = time.time()
        self.prev_t_ms = None
        self.yaw = 0.0
        self.pitch = 0.0
        self.roll = 0.0
        self.use_denoised = USE_DENOISED_STREAM
        self.verbose_hud = VERBOSE_HUD
        self.is_paused = False


state = SessionState()


def parse_packet(data: bytes):
    """Estrae i dati dal pacchetto binario ricevuto via BLE GATT."""
    if len(data) < SIZE_CLEAN:
        return None
    seq, t_ms, *clean = struct.unpack_from("<ii9f", data, 0)
    raw = (
        struct.unpack_from("<9f", data, SIZE_CLEAN)
        if len(data) >= SIZE_FULL
        else None
    )
    return seq, t_ms, clean, raw


# ==============================================================================
# ELABORAZIONE DEI CAMPIONI IMU
# ==============================================================================
def process_sample(seq, t_ms, clean, raw):
    global USE_ABSOLUTE_BORESIGHT

    if state.last_seq is not None and seq > state.last_seq + 1:
        state.lost += seq - state.last_seq - 1
    state.last_seq = seq

    a = clean[0:3]
    g = clean[3:6]
    m = clean[6:9]

    acc_raw = raw[0:3] if raw is not None else a
    gyro_raw = raw[3:6] if raw is not None else g

    acc_input = a if state.use_denoised else acc_raw
    gyro_input = g if state.use_denoised else gyro_raw
    mag_input = m

    # Calcolo intervallo temporale dt effettivo
    if state.prev_t_ms is not None and t_ms > state.prev_t_ms:
        dt = (t_ms - state.prev_t_ms) / 1000.0
        dt = max(0.01, min(0.15, dt))
    else:
        dt = 0.05
    state.prev_t_ms = t_ms

    # 1. Fase di Calibrazione Statica (2 secondi iniziali)
    if not screen_calibrator.is_calibrated:
        temp_euler = ahrs_filter.update(acc_input, gyro_input, mag_input, dt=dt)
        is_completed = screen_calibrator.add_calibration_sample(gyro_input, temp_euler)
        pct = screen_calibrator.progress_percentage
        print(f"  Calibrazione in corso: {pct:5.1f}% | campioni: {screen_calibrator._samples_count}/{screen_calibrator.calibration_samples}", end="\r")

        if is_completed:
            print("\n" + "=" * 82)
            print("  [OK] CALIBRAZIONE COMPLETATA CON SUCCESSO!")
            print(f"  Bias Giroscopio (rad/s): [{screen_calibrator.gyro_bias[0]:+.4f}, "
                  f"{screen_calibrator.gyro_bias[1]:+.4f}, {screen_calibrator.gyro_bias[2]:+.4f}]")
            print(f"  Posa Neutra Centro: Yaw={screen_calibrator.zero_euler['yaw']:+.1f}°, "
                  f"Pitch={screen_calibrator.zero_euler['pitch']:+.1f}°")
            print(f"  Centro Monitor {screen_calibrator.active_monitor_index + 1}: "
                  f"({screen_calibrator.center_x}, {screen_calibrator.center_y})")
            print("  TRACKING ULTRA-FLUIDO ATTIVO! [Premi SPAZIO o C per ricentrare]")
            print("=" * 82 + "\n")

            mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
            mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
            smooth_engine.snap_to(screen_calibrator.center_x, screen_calibrator.center_y)
            bubble_stabilizer.reset(screen_calibrator.center_x, screen_calibrator.center_y)

            gesture_detector.reset()
            gesture_detector.prev_yaw = temp_euler["yaw"]
            gesture_detector.prev_pitch = temp_euler["pitch"]
            gesture_detector.prev_roll = temp_euler["roll"]
            state.prev_t_ms = t_ms
            state.last_report = time.time()
            state.last_hud_time = time.time()
        return

    # Gestione Pausa Streaming dallo smartwatch
    if state.is_paused:
        now = time.time()
        if now - state.last_report >= 0.5:
            print(f"  ⏸️  [PAUSA STREAMING] Cerchi concentrici rimossi | Mouse libero ovunque", end="\r")
            state.last_report = now
        return

    # 2. Correzione Bias ed Esecuzione AHRS Madgwick
    gyro_calibrated = screen_calibrator.apply_bias_correction(gyro_input)
    euler = ahrs_filter.update(acc_input, gyro_calibrated, mag_input, dt=dt)
    pitch = euler["pitch"]
    yaw = euler["yaw"]
    roll = euler["roll"]
    state.pitch, state.yaw, state.roll = pitch, yaw, roll

    # 3. Rilevamento Gesture ed Anti-Jumping
    gesture_state, is_frozen, deltas = gesture_detector.update(
        pitch=pitch,
        yaw=yaw,
        roll=roll,
        gyro=gyro_calibrated,
        dt=dt
    )
    d_pitch = deltas["d_pitch"]
    d_yaw = deltas["d_yaw"]

    # 4. Mappatura C-D Gain Diretta
    if USE_ABSOLUTE_BORESIGHT:
        zero_yaw = screen_calibrator.zero_euler["yaw"]
        zero_pitch = screen_calibrator.zero_euler["pitch"]
        raw_x, raw_y = mouse_mapper.map_absolute(
            yaw=yaw,
            pitch=pitch,
            zero_yaw=zero_yaw,
            zero_pitch=zero_pitch,
            is_frozen=is_frozen,
            dt=dt
        )
    else:
        dx, dy = mouse_mapper.map_delta(
            d_yaw=d_yaw,
            d_pitch=d_pitch,
            is_frozen=is_frozen,
            dt=dt
        )
        raw_x = smooth_engine.current_x + dx
        raw_y = smooth_engine.current_y + dy

    # 5. Stabilizzazione Spaziale Soft-Edge con Hermite Smoothstep
    stable_x, stable_y, bubble_state = bubble_stabilizer.update(raw_x, raw_y, is_frozen=is_frozen)

    # 6. Invio coordinate bersaglio al Motore Continuo SmoothDamp a 120 Hz
    if ENABLE_MOUSE_CONTROL:
        smooth_engine.set_target(stable_x, stable_y, is_absolute=True)

    target_x = int(round(stable_x))
    target_y = int(round(stable_y))

    # 7. Console HUD non-bloccante
    state.count += 1
    now = time.time()

    if state.verbose_hud:
        state_tag = ">>> FREEZE GESTO <<<" if is_frozen else "TRACK"
        stream_tag = "WAV" if state.use_denoised else "RAW"
        print(
            f"#{seq:6d} t={t_ms:10d}ms | {state_tag:<20} | "
            f"POS [{target_x:4d}, {target_y:4d}] | "
            f"BOLLA [{bubble_state:<12}] | "
            f"YAW: {yaw:+5.1f}° PIT: {pitch:+5.1f}°"
        )
    else:
        if (now - state.last_hud_time >= 0.10) or is_frozen:
            state_tag = ">>> [FREEZE GESTO] <<<" if is_frozen else "    [TRACK NORMAL]    "
            if is_frozen:
                bubble_tag = "GESTO BLOCCATO"
            elif not bubble_stabilizer.enabled:
                bubble_tag = "BOLLA OFF     "
            elif bubble_stabilizer.is_anchored:
                bubble_tag = "ANCHOR (FERMO)"
            else:
                bubble_tag = "MOVE  (FLUIDO)"

            stream_str = "WAV" if state.use_denoised else "RAW"
            print(
                f"  {state_tag} | POS: ({target_x:4d}, {target_y:4d}) | "
                f"BOLLA: [{bubble_tag}] | "
                f"YAW: {yaw:+5.1f}° PIT: {pitch:+5.1f}° | "
                f"IMU: [{stream_str}]",
                end="\r"
            )
            state.last_hud_time = now

    if now - state.last_report >= 1.0:
        state.count = 0
        state.last_report = now


# ==============================================================================
# GESTIONE COMANDI TASTIERA A RUNTIME (SOLO COMANDI MINIMI DI SISTEMA)
# ==============================================================================
def handle_keyboard(key):
    """
    Gestione comandi da tastiera a runtime.
    Come richiesto: nessun parametro operativo è modificabile da tastiera,
    tutti i parametri sono configurabili esclusivamente lato codice a monte.
    """
    yaw, pitch, roll = state.yaw, state.pitch, state.roll

    # Quick Re-Center su richiesta dell'utente
    if key in (b' ', b'c', b'C'):
        mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
        screen_calibrator.recenter_pose({"yaw": yaw, "pitch": pitch, "roll": roll})
        mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
        smooth_engine.snap_to(screen_calibrator.center_x, screen_calibrator.center_y)
        bubble_stabilizer.reset(screen_calibrator.center_x, screen_calibrator.center_y)
        print(f"\n  [RE-CENTER] Cursore ricentrato su Monitor {screen_calibrator.active_monitor_index + 1} "
              f"({screen_calibrator.center_x}, {screen_calibrator.center_y})!")

    # Pausa / Ripresa da tastiera PC (hotkey P)
    elif key in (b'p', b'P'):
        state.is_paused = not state.is_paused
        if state.is_paused:
            smooth_engine.pause()
            bubble_stabilizer.disable_anchor()
            print("\n  ⏸️  [PAUSA/RIPRESA] In pausa da tastiera: Cerchi concentrici disattivati | Mouse libero ovunque.")
        else:
            state.prev_t_ms = None
            cur_x, cur_y = mouse_controller.get_position()
            smooth_engine.snap_to(cur_x, cur_y)
            bubble_stabilizer.reset(cur_x, cur_y)
            smooth_engine.resume()
            print(f"\n  ▶️  [PAUSA/RIPRESA] Tracking ripreso da tastiera: Cerchi concentrici riattivati a ({cur_x}, {cur_y}).")


# ==============================================================================
# CALLBACK BLE GATT
# ==============================================================================
def handle_data(data: bytes):
    pkt = parse_packet(data)
    if pkt is None:
        return
    seq, t_ms, clean, raw = pkt
    process_sample(seq, t_ms, clean, raw)


def handle_ctrl(data: bytes):
    msg = data.strip()
    if msg == b"bye":
        print("\n\n  [BLE ctrl] Smartwatch disconnesso (bye). In attesa di nuova connessione...")
        state.reset()
        screen_calibrator.start_static_calibration()
        ahrs_filter.reset()
        gesture_detector.reset()
        mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
        smooth_engine.snap_to(screen_calibrator.center_x, screen_calibrator.center_y)
        bubble_stabilizer.reset(screen_calibrator.center_x, screen_calibrator.center_y)
    elif msg == b"pause":
        state.is_paused = True
        smooth_engine.pause()
        bubble_stabilizer.disable_anchor()
        print("\n  ⏸️  [BLE ctrl] STREAMING IN PAUSA: Cerchi concentrici disattivati | Mouse libero ovunque.")
    elif msg == b"resume":
        state.is_paused = False
        state.prev_t_ms = None
        cur_x, cur_y = mouse_controller.get_position()
        smooth_engine.snap_to(cur_x, cur_y)
        bubble_stabilizer.reset(cur_x, cur_y)
        smooth_engine.resume()
        print(f"\n  ▶️  [BLE ctrl] STREAMING RIPRESO: Cerchi concentrici riagganciati a ({cur_x}, {cur_y}) | Tracking attivo.")


def on_write(characteristic: BlessGATTCharacteristic, value, **kwargs):
    uuid = str(characteristic.uuid).lower()
    data = bytes(value)
    if uuid == DATA_UUID:
        handle_data(data)
    elif uuid == CTRL_UUID:
        handle_ctrl(data)


def print_banner():
    print("=" * 82)
    print("  AIRMOUSE V2 LORENZ - ULTRA-FLUID PRO ENGINE (120 Hz + SMOOTHDAMP)")
    print("=" * 82)
    print(f"  Server BLE GATT:        ATTIVO ('{SERVER_NAME}')")
    print(f"  Driver Mouse:           {mouse_controller.backend_name.upper()} (Zero-Latency)")
    print(f"  Motore Interpolazione:  SmoothDamp C1 a {CURSOR_ENGINE_HZ:.0f} Hz (Timer 1ms Win32)")
    print(f"  Stabilizzatore Bolla:   Soft-Edge Hermite [{BUBBLE_INNER_RADIUS_PX:.1f}px - {BUBBLE_OUTER_RADIUS_PX:.1f}px]")
    print(f"  Stream IMU:             {'WAVELET DENOISED' if USE_DENOISED_STREAM else 'ZERO-LATENCY RAW (0 ms lag)'}")
    print(f"  Sensibilita' C-D Gain:  {SCALE_FACTOR:.2f}x (Max Gomito: Yaw +/-{MAX_YAW_DEG:.0f} deg, Pitch +/-{MAX_PITCH_DEG:.0f} deg)")
    print(f"  Anti-Jumping Gesture:   ATTIVO (Soglia Gyro: {GESTURE_GYRO_NORM_RAD:.1f} rad/s, Roll: {GESTURE_ROLL_SPEED_DEG:.0f} deg/s)")
    print("-" * 82)
    print("  CONTROLLI RUNTIME DA TASTIERA (Tutti i parametri sono impostabili lato codice):")
    print("    [P]                   -> Pausa / Ripresa (libera il mouse e rimuove cerchi concentrici)")
    print("    [SPAZIO] / [C]        -> Quick Re-Center (centra cursore sul monitor)")
    print("    [Q] / [ESC]           -> Chiusura sicura applicazione")
    print("=" * 82)


# ==============================================================================
# AVVIO SERVER BLE E ASYNC EVENT LOOP
# ==============================================================================
async def main():
    loop = asyncio.get_running_loop()

    server = BlessServer(name=SERVER_NAME, loop=loop)
    server.write_request_func = on_write

    await server.add_new_service(SERVICE_UUID)

    wnr = GATTCharacteristicProperties.write_without_response
    wr = GATTCharacteristicProperties.write
    read = GATTCharacteristicProperties.read
    write_perms = GATTAttributePermissions.writeable

    await server.add_new_characteristic(
        SERVICE_UUID,
        DATA_UUID,
        wnr | wr,
        None,
        write_perms,
    )

    await server.add_new_characteristic(
        SERVICE_UUID,
        CTRL_UUID,
        wnr | wr | read,
        None,
        write_perms,
    )

    logging.getLogger("bless").setLevel(logging.WARNING)

    # Sincronizzazione monitor attivo rilevando dove si trova fisicamente il cursore all'avvio
    screen_calibrator.sync_active_monitor_from_cursor()
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
        factor_y=screen_calibrator.cd_params["factor_y"],
        scale_factor=SCALE_FACTOR
    )
    mouse_mapper.deadzone_deg = float(DEADZONE_DEG)

    print_banner()

    await server.start()
    print("  In attesa di connessione dallo smartwatch Wear OS...\n")

    try:
        while True:
            key = poll_keyboard_key()
            if key is not None:
                if key in (b'q', b'Q', b'\x1b'):
                    print("\n\n  Uscita richiesta dall'utente. Arresto server BLE...")
                    break
                handle_keyboard(key)
            await asyncio.sleep(0.02)

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nInterruzione da tastiera...")

    finally:
        # Ripristino risoluzione timer sistema operativo Windows
        if sys.platform == "win32" and HIGH_PRECISION_TIMER:
            try:
                import ctypes
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass

        try:
            smooth_engine.stop()
            await server.stop()
        except Exception:
            pass
        print("Server BLE terminato correttamente.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
# --- END [18/10/2026] Ottimizzazioni Fluidita' Estrema & Parametri Solo Lato Codice (reciverV2_lorenz.py) ---
