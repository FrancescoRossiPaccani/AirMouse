# --- Step 12: Server BLE Integrato Motion Tracking & Gesture Recognition (ble-serverV2.py) ---
"""
ble-serverV2.py: Server BLE GATT unificato che orchestra Motion Tracking ultra-fluido
a 120 Hz e Riconoscimento Gesti Real-Time con esecuzione di azioni mouse cross-platform.

Novita' rispetto a V1:
- Filtro One Euro sul target del cursore (stabilita' da fermo, nessun lag in movimento)
- Parametri di precisione ritarati (guadagno, guard, smorzamento, bolla, beta AHRS)
- Mappatura gesti: click sx / click dx / doppio click / lock sx / lock dx
- Lettura tastiera immediata su Linux/macOS (cbreak), senza premere Invio
"""

import asyncio
from collections import deque
import logging
import math
import os
import struct
import sys
import time

import numpy as np

# Configurazione path del progetto
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

_GEST_DIR = os.path.join(_ROOT_DIR, "gestureRecognitionUtils")
if _GEST_DIR not in sys.path:
    sys.path.insert(0, _GEST_DIR)

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

# --- Moduli di Motion Tracking e Controllo Mouse (motionTrackingModule) ---
from motionTrackingModule.ahrs import AHRSFilter
from motionTrackingModule.cursor_engine import SmoothCursorEngine
from motionTrackingModule.mouse_controller_pyautogui import MouseController, GestureActionDispatcher
from motionTrackingModule.mouse_mapper import MouseMapper
from motionTrackingModule.screen_calibrator import ScreenCalibrator
from motionTrackingModule.stabilizer import SpatialBubbleStabilizer

# --- Moduli di Gesture Recognition (gestureRecognitionUtils) ---
import gestureRecognitionUtils.train as T
from gestureRecognitionUtils.detector import ForestPredictor, OnlineGestureDetector
from gestureRecognitionUtils.gesture_guard import GestureGuard

logging.basicConfig(level=logging.WARNING)


# ==============================================================================
# PARAMETRI DI CONFIGURAZIONE (MODIFICABILI ESCLUSIVAMENTE DA CODICE)
# ==============================================================================

# --- 1. Parametri BLE GATT Server ---
BLE_SERVER_NAME = "AirMouse-PC"
SERVICE_UUID = "7a1c0001-4f5e-4b8a-9d3c-2e6f1a0b5c01"
DATA_UUID = "7a1c0002-4f5e-4b8a-9d3c-2e6f1a0b5c01"
CTRL_UUID = "7a1c0003-4f5e-4b8a-9d3c-2e6f1a0b5c01"
PACKET_SIZE_CLEAN = 44
PACKET_SIZE_FULL = 80

# --- 2. Flusso Sensori e Fusione AHRS ---
# True: usa i dati filtrati dal WaveletDenoiser dello smartwatch (piu' puliti, un po' meno reattivi)
# False: usa il flusso grezzo raw a latenza zero
USE_DENOISED_STREAM = False
AHRS_BETA = 0.05                   # Guadagno Madgwick (piu' basso = meno rumore accelerometro sul pitch)
CALIBRATION_DURATION_SEC = 2.0     # Durata calibrazione statica iniziale (40 campioni a 20 Hz)

# --- 3. Mappatura Cinematica Cursore (Control-Display Gain) ---
ENABLE_MOUSE_CONTROL = True        # True: muove fisicamente il mouse sul sistema operativo
SCALE_FACTOR = 1.00                # Moltiplicatore globale sensibilita'
MAX_YAW_DEG = 35.0                 # Escursione orizzontale (piu' alta = guadagno minore = piu' precisione)
MAX_PITCH_DEG = 25.0               # Escursione verticale
DEADZONE_DEG = 0.15                # Dead-zone angolare della Sigmoide (gradi)

# --- 4. Motore di Interpolazione a 120 Hz e Stabilizzazione Spaziale ---
ENABLE_SMOOTH_120HZ = True         # Abilita thread interpolatore a 120 FPS
CURSOR_ENGINE_HZ = 120.0           # Frequenza di campionamento del thread cursore
SMOOTH_TIME_S = 0.045              # Costante di tempo SmoothDamp (copre l'intervallo di 50 ms tra campioni)
HIGH_PRECISION_TIMER = True        # Win32 timeBeginPeriod(1) a 1 ms

# Parametri Bolla Spaziale Soft-Edge
BUBBLE_ENABLED = True
BUBBLE_INNER_RADIUS_PX = 4.0       # Raggio interno: soppressione totale del tremolio a riposo (pixel)
BUBBLE_OUTER_RADIUS_PX = 10.0      # Raggio esterno: transizione Hermite morbida continua (pixel)
BUBBLE_STILL_TIME_S = 0.15         # Tempo minimo di fermo per ricentrare la bolla (secondi)

# Filtro One Euro sul target (adattivo: forte da fermo, trasparente in movimento)
ONE_EURO_ENABLED = True
ONE_EURO_MIN_CUTOFF = 0.8          # Piu' basso = piu' stabile da fermo (ma piu' lag lento)
ONE_EURO_BETA = 0.01               # Piu' alto = meno lag quando ti muovi veloce

# --- 5. Riconoscimento Gesti (Online Gesture Classifier) ---
GESTURE_MODEL_PATH = os.path.join(_GEST_DIR, "trainedTree", "rf.json")
GESTURE_PEAK_THRESH = 0.25         # Soglia minima di ampiezza picco/valle angolare (rad)
GESTURE_MIN_CONFIDENCE = 0.50      # Soglia minima di confidenza della Random Forest (0.0 - 1.0)
GESTURE_COOLDOWN_SAMPLES = 30      # Campioni di cooldown post-gesto (30 campioni = 1.5 s a 20 Hz)

# --- 5b. Gesture guard (cursor freeze) and gyro bias trim ---
GUARD_ENABLED = True
GUARD_RATE_ON_DPS = 100.0          # velocita' angolare che avvia il freeze (deg/s)
GUARD_RATE_OFF_DPS = 40.0          # sotto questa soglia la mano e' considerata calma (deg/s)
GUARD_LOOKBACK = 2                 # campioni da ripercorrere per trovare la posizione pre-gesto
GUARD_SETTLE_SAMPLES = 5           # campioni calmi prima del rilascio (0.25 s)
GUARD_MAX_FREEZE_SAMPLES = 25      # rilascio di sicurezza (1.25 s)
BIAS_STILL_DPS = 1.0               # sotto questa soglia la mano e' ferma (deg/s)
BIAS_STILL_SAMPLES = 30            # 1.5 s di fermo prima di correggere il bias del giroscopio
BIAS_ALPHA = 0.005                 # velocita' di correzione per campione

# --- 6. Mappatura Gesto -> Azione Mouse ---
#   'RLB': Rotate-Left-Back  -> Click sinistro
#   'RRB': Rotate-Right-Back -> Click destro
#   'UDB': Up-Down-Back      -> Doppio click sinistro
#   'MLB': Move-Left-Back    -> Blocca / rilascia pulsante sinistro
#   'MRB': Move-Right-Back   -> Blocca / rilascia pulsante destro
GESTURE_ACTION_MAP = {
    "RLB": "left_click",
    "RRB": "right_click",
    "UDB": "double_click",
    "MLB": "left_lock_toggle",
    "MRB": "right_lock_toggle",
}
SCROLL_STEPS = 3                   # Usato solo se mappi scroll_up / scroll_down


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
# FILTRO ONE EURO
# ==============================================================================
class OneEuro:
    """Filtro passa-basso adattivo (Casiez et al., 2012)."""

    def __init__(self, min_cutoff=0.8, beta=0.01, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self):
        self.x = None
        self.dx = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, dt):
        if self.x is None:
            self.x = x
            return x
        dx = (x - self.x) / dt
        self.dx += self._alpha(self.d_cutoff, dt) * (dx - self.dx)
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        self.x += self._alpha(cutoff, dt) * (x - self.x)
        return self.x


# ==============================================================================
# INIZIALIZZAZIONE COMPONENTI MODULARI
# ==============================================================================
class ServerState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.expected_seq = 0
        self.received = 0
        self.lost = 0
        self.prev_t_ms = None
        self.is_paused = False
        self.bias_trim = np.zeros(3)
        self.still = 0
        self.jit = deque(maxlen=40)

        # Metriche frequenza
        self.window_count = 0
        self.last_report = time.time()
        self.last_hud = time.time()

        # Coordinate e assetto correnti
        self.yaw = 0.0
        self.pitch = 0.0
        self.roll = 0.0
        self.target_x = 0.0
        self.target_y = 0.0
        self.stabilizer_state = "INIT"


state = ServerState()

# 1. Driver Mouse & Calibratore Schermo
mouse_controller = MouseController()
screen_calibrator = ScreenCalibrator(
    ref_width=1920,
    ref_height=1080,
    base_lambda=60.0,
    max_yaw_deg=MAX_YAW_DEG,
    max_pitch_deg=MAX_PITCH_DEG,
    calibration_samples=int(CALIBRATION_DURATION_SEC * 20.0),
)

# 2. Mappatore Cinematico C-D Gain
mouse_mapper = MouseMapper(
    screen_width=screen_calibrator.screen_width,
    screen_height=screen_calibrator.screen_height,
    origin_x=screen_calibrator.origin_x,
    origin_y=screen_calibrator.origin_y,
    max_yaw_deg=MAX_YAW_DEG,
    max_pitch_deg=MAX_PITCH_DEG,
    deadzone_deg=DEADZONE_DEG,
    scale_factor=SCALE_FACTOR,
)

# 3. Filtro Orientamento AHRS Madgwick
ahrs_filter = AHRSFilter(sample_rate_hz=20.0, beta=AHRS_BETA, use_magnetometer=False)

# 4. Stabilizzatore a Bolla Spaziale Soft-Edge
bubble_stabilizer = SpatialBubbleStabilizer(
    r_inner_px=BUBBLE_INNER_RADIUS_PX,
    r_outer_px=BUBBLE_OUTER_RADIUS_PX,
    still_time_s=BUBBLE_STILL_TIME_S,
    enabled=BUBBLE_ENABLED,
)

# 4b. Filtri One Euro (asse X e Y)
filter_x = OneEuro(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA)
filter_y = OneEuro(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA)


def reset_filters():
    filter_x.reset()
    filter_y.reset()


# 5. Motore di Interpolazione Ultra-Fluido a 120 Hz
smooth_engine = SmoothCursorEngine(
    controller=mouse_controller,
    update_hz=CURSOR_ENGINE_HZ,
    smooth_time_s=SMOOTH_TIME_S,
    enabled=ENABLE_SMOOTH_120HZ,
)

# 6. Modello Random Forest, Online Detector e Dispatcher Azioni
action_dispatcher = GestureActionDispatcher(
    mouse_controller=mouse_controller,
    action_map=GESTURE_ACTION_MAP,
    scroll_steps=SCROLL_STEPS,
)
gesture_detector = OnlineGestureDetector(
    thresh=GESTURE_PEAK_THRESH,
    cooldown=GESTURE_COOLDOWN_SAMPLES,
)
gesture_guard = GestureGuard(
    rate_on_dps=GUARD_RATE_ON_DPS, rate_off_dps=GUARD_RATE_OFF_DPS,
    lookback=GUARD_LOOKBACK, settle_samples=GUARD_SETTLE_SAMPLES,
    max_freeze_samples=GUARD_MAX_FREEZE_SAMPLES, enabled=GUARD_ENABLED,
)

try:
    forest_model = ForestPredictor(GESTURE_MODEL_PATH)
    print(f"  [OK] Modello Gesti caricato da: {GESTURE_MODEL_PATH}")
    print(f"       Classi riconosciute: {forest_model.classes} ({len(forest_model.trees)} alberi)")
except Exception as e:
    forest_model = None
    print(f"  [WARN] Modello Gesti non disponibile: {e}")


# ==============================================================================
# DECODIFICA PACCHETTO BINARIO BLE GATT
# ==============================================================================
def parse_packet(data: bytes):
    """
    Decodifica il pacchetto binario Little-Endian trasmesso da BleClient.kt:
    int32 seq | int32 t_ms | 9x float32 clean | [9x float32 raw]
    """
    if len(data) < PACKET_SIZE_CLEAN:
        return None
    seq, t_ms, *clean = struct.unpack_from("<ii9f", data, 0)
    raw = struct.unpack_from("<9f", data, PACKET_SIZE_CLEAN) if len(data) >= PACKET_SIZE_FULL else None
    return seq, t_ms, clean, raw


# ==============================================================================
# PIPELINE ELABORAZIONE CAMPIONE (TRACKING & GESTURE RECOGNITION)
# ==============================================================================
def process_sample(seq: int, t_ms: int, clean: list, raw: list | None):
    # Gestione sequenza e pacchetti persi
    if seq < state.expected_seq:
        state.reset()
    if seq > state.expected_seq:
        state.lost += seq - state.expected_seq
    state.expected_seq = seq + 1
    state.received += 1
    state.window_count += 1

    # Selezione flusso dati (Denoised vs Raw 0 ms)
    acc_clean, gyro_clean, mag_clean = clean[0:3], clean[3:6], clean[6:9]
    if raw is not None and not USE_DENOISED_STREAM:
        acc_input, gyro_input, mag_input = raw[0:3], raw[3:6], raw[6:9]
    else:
        acc_input, gyro_input, mag_input = acc_clean, gyro_clean, mag_clean

    # Calcolo delta temporale dt reale
    if state.prev_t_ms is not None and t_ms > state.prev_t_ms:
        dt = (t_ms - state.prev_t_ms) / 1000.0
        dt = max(0.01, min(0.15, dt))
    else:
        dt = 0.05
    state.prev_t_ms = t_ms

    # 1. FASE DI CALIBRAZIONE STATICA INIZIALE (2.0 SECONDI)
    if not screen_calibrator.is_calibrated:
        temp_euler = ahrs_filter.update(acc_input, gyro_input, mag_input, dt=dt)
        is_completed = screen_calibrator.add_calibration_sample(gyro_input, temp_euler)
        pct = screen_calibrator.progress_percentage
        print(f"  [CALIBRAZIONE IN CORSO] {pct:5.1f}% | campioni: {screen_calibrator._samples_count}/{screen_calibrator.calibration_samples}", end="\r")

        if is_completed:
            print("\n" + "=" * 80)
            print("  [OK] CALIBRAZIONE STATICA COMPLETATA CON SUCCESSO!")
            print(f"  Bias Giroscopio (rad/s): [{screen_calibrator.gyro_bias[0]:+.4f}, "
                  f"{screen_calibrator.gyro_bias[1]:+.4f}, {screen_calibrator.gyro_bias[2]:+.4f}]")
            print(f"  Posa Neutra Centro: Yaw={screen_calibrator.zero_euler['yaw']:+.1f}°, "
                  f"Pitch={screen_calibrator.zero_euler['pitch']:+.1f}°")
            print(f"  Centro Monitor {screen_calibrator.active_monitor_index + 1}: "
                  f"({screen_calibrator.center_x}, {screen_calibrator.center_y})")
            print(f"  Backend Driver Mouse: {mouse_controller.backend_name}")
            print("=" * 80 + "\n")

            mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
            mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
            smooth_engine.snap_to(screen_calibrator.center_x, screen_calibrator.center_y)
            bubble_stabilizer.reset(screen_calibrator.center_x, screen_calibrator.center_y)
            reset_filters()
            gesture_detector.reset()
            gesture_guard.reset()
            state.prev_t_ms = t_ms
            state.last_report = time.time()
            state.last_hud = time.time()
        return

    # 2. GESTIONE PAUSA STREAMING DALLO SMARTWATCH
    if state.is_paused:
        now = time.time()
        if now - state.last_report >= 0.5:
            print(f"  ⏸️  [PAUSA STREAMING] Cerchi concentrici rimossi | Mouse libero ovunque", end="\r")
            state.last_report = now
        return

    # 3. GYRO: bias correction + slow bias trim, and angular speed
    gyro_cal = (np.asarray(screen_calibrator.apply_bias_correction(gyro_input), dtype=float)
                - state.bias_trim)
    rate_dps = float(np.degrees(np.linalg.norm(gyro_cal)))
    if rate_dps < BIAS_STILL_DPS:
        state.still += 1
        if state.still >= BIAS_STILL_SAMPLES:
            state.bias_trim += BIAS_ALPHA * gyro_cal      # residual rate while still = bias
    else:
        state.still = 0

    # 4. MADGWICK AHRS
    euler = ahrs_filter.update(acc_input, gyro_cal, mag_input, dt=dt)
    state.yaw, state.pitch, state.roll = euler["yaw"], euler["pitch"], euler["roll"]

    # 5. GESTURE GUARD: freezes the cursor at the first fast sample
    is_gesture_frozen = gesture_guard.update(
        rate_dps, state.yaw, state.pitch, dragging=action_dispatcher.is_dragging)
    off_yaw, off_pitch = gesture_guard.offsets

    # 6. KINEMATIC MAPPING (zero shifted by the angle travelled while frozen)
    raw_tx, raw_ty = mouse_mapper.map_absolute(
        yaw=state.yaw,
        pitch=state.pitch,
        zero_yaw=screen_calibrator.zero_euler["yaw"] + off_yaw,
        zero_pitch=screen_calibrator.zero_euler["pitch"] + off_pitch,
        is_frozen=is_gesture_frozen,
        dt=dt,
    )

    # 6b. ONE EURO FILTER (solo quando il cursore non e' congelato dal guard)
    if ONE_EURO_ENABLED and not is_gesture_frozen:
        raw_tx = filter_x(raw_tx, dt)
        raw_ty = filter_y(raw_ty, dt)

    # 7. SPATIAL STABILIZATION
    target_x, target_y, stab_state = bubble_stabilizer.update(
        raw_tx, raw_ty, is_frozen=is_gesture_frozen)
    if is_gesture_frozen:
        target_x, target_y = gesture_guard.hold_xy       # exactly the pre-gesture position
    else:
        gesture_guard.record(state.yaw, state.pitch, target_x, target_y)
        state.jit.append((target_x, target_y))
    state.target_x, state.target_y, state.stabilizer_state = target_x, target_y, stab_state

    if ENABLE_MOUSE_CONTROL:
        smooth_engine.set_target(target_x, target_y)

    # 8. GESTURE RECOGNITION: ALWAYS on the denoised stream (the model was trained on it)
    if forest_model is not None:
        cand = gesture_detector.push(acc_clean, gyro_clean, mag_clean)
        if cand is not None:
            window, info = cand
            label, conf = forest_model.predict(T.feats(window))
            if conf >= GESTURE_MIN_CONFIDENCE:
                action_desc = action_dispatcher.execute_gesture(label, conf, info)
                print("\n" + "=" * 80)
                print(f"  >>> [GESTO RILEVATO] {label} (Confidenza: {conf * 100:.1f}% | "
                      f"Asse: {info['axis']} | Score: {info['score']:.2f} rad)")
                print(f"  >>> [AZIONE ESEGUITA] {action_desc} (OS: {sys.platform})")
                print("=" * 80 + "\n")

    # 9. CONSOLE HUD THROTTLED A 10 HZ
    now = time.time()
    if now - state.last_hud >= 0.10:
        freq = state.window_count / max(0.001, now - state.last_report) if (now - state.last_report) > 0.0 else 20.0
        drag_str = "[LOCK ON]" if action_dispatcher.is_dragging else "[LOCK OFF]"
        freeze_str = "[GUARD]" if is_gesture_frozen else f"[{stab_state}]"
        jx, jy = np.std(state.jit, axis=0) if len(state.jit) >= 10 else (0.0, 0.0)
        print(
            f"  [BLE {freq:4.1f} Hz] {drag_str} {freeze_str} "
            f"Pos: ({target_x:4.0f}, {target_y:4.0f}) px | jit {jx:3.1f}/{jy:3.1f}px | "
            f"rate {rate_dps:5.1f}°/s | "
            f"Ultimo: {action_dispatcher.last_gesture} ({action_dispatcher.last_confidence * 100:.0f}%)",
            end="\r",
        )
        state.last_hud = now

    if now - state.last_report >= 1.0:
        state.window_count = 0
        state.last_report = now


# ==============================================================================
# CALLBACK GATT SERVER BLE (bless)
# ==============================================================================
def handle_data(data: bytes):
    pkt = parse_packet(data)
    if pkt is not None:
        seq, t_ms, clean, raw = pkt
        process_sample(seq, t_ms, clean, raw)


def handle_ctrl(data: bytes):
    msg = data.strip().lower()
    if msg == b"bye":
        print("\n\n  [BLE ctrl] Lo smartwatch ha inviato 'bye'. Connessione terminata.")
        state.reset()
        action_dispatcher.release_all()
        screen_calibrator.start_static_calibration()
        ahrs_filter.reset()
        reset_filters()
        gesture_detector.reset()
        gesture_guard.reset()

    elif msg == b"pause":
        state.is_paused = True
        smooth_engine.pause()
        bubble_stabilizer.disable_anchor()
        action_dispatcher.release_all()
        print("\n  ⏸️  [BLE ctrl] STREAMING IN PAUSA: Cerchi concentrici disattivati | Mouse libero ovunque.")

    elif msg == b"resume":
        state.is_paused = False
        state.prev_t_ms = None
        cur_x, cur_y = mouse_controller.get_position()
        smooth_engine.snap_to(cur_x, cur_y)
        bubble_stabilizer.reset(cur_x, cur_y)
        reset_filters()
        gesture_guard.reset()
        smooth_engine.resume()
        print(f"\n  ▶️  [BLE ctrl] STREAMING RIPRESO dallo smartwatch: Motion tracking e cerchi concentrici riattivati a ({cur_x}, {cur_y}).")


def on_write(characteristic: BlessGATTCharacteristic, value, **kwargs):
    uuid = str(characteristic.uuid).lower()
    data = bytes(value)
    if uuid == DATA_UUID:
        handle_data(data)
    elif uuid == CTRL_UUID:
        handle_ctrl(data)


# ==============================================================================
# TASTIERA NON BLOCCANTE (Windows: msvcrt | Linux/macOS: cbreak, niente Invio)
# ==============================================================================
try:
    import msvcrt
except ImportError:
    msvcrt = None

_term_state = None


def term_setup():
    """Linux/macOS: legge i tasti subito, senza dover premere Invio."""
    global _term_state
    if sys.platform == "win32":
        return
    try:
        import termios
        import tty
        if sys.stdin.isatty():
            fd = sys.stdin.fileno()
            _term_state = (fd, termios.tcgetattr(fd))
            tty.setcbreak(fd)
    except Exception:
        _term_state = None


def term_restore():
    global _term_state
    if _term_state is None:
        return
    try:
        import termios
        fd, old = _term_state
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        pass
    _term_state = None


def poll_keyboard_key():
    """Legge un carattere da tastiera in modo non bloccante (cross-platform)."""
    if msvcrt and msvcrt.kbhit():
        return msvcrt.getch()
    if sys.platform != "win32":
        try:
            import select
            if select.select([sys.stdin], [], [], 0)[0]:
                return os.read(sys.stdin.fileno(), 1)
        except Exception:
            pass
    return None


# ==============================================================================
# MAIN ASYNC BLE GATT SERVER
# ==============================================================================
async def main():
    print("=" * 80)
    print("      AirMouse - BLE Server V2 (Motion Tracking + Gesture Recognition)")
    print("=" * 80)
    print(f"  Sistema Operativo Rilevato : {sys.platform} (Backend: {mouse_controller.backend_name})")
    print(f"  Display Attivo             : {screen_calibrator.screen_width} x {screen_calibrator.screen_height} px")
    print(f"  Motore Cursore 120 Hz      : {'ATTIVO' if ENABLE_SMOOTH_120HZ else 'DISATTIVATO'}")
    print(f"  Stabilizzatore Bolla       : {'ATTIVO' if BUBBLE_ENABLED else 'DISATTIVATO'} (R_in: {BUBBLE_INNER_RADIUS_PX}px, R_out: {BUBBLE_OUTER_RADIUS_PX}px)")
    print(f"  Filtro One Euro            : {'ATTIVO' if ONE_EURO_ENABLED else 'DISATTIVATO'} (min_cutoff: {ONE_EURO_MIN_CUTOFF}, beta: {ONE_EURO_BETA})")
    print(f"  Flusso Sensori IMU         : {'DENOISED (Wavelet)' if USE_DENOISED_STREAM else 'RAW (0 ms Latenza)'}")
    print(f"  Mappatura Gesti            : {GESTURE_ACTION_MAP}")
    print("=" * 80)
    print("  CONTROLLI RUNTIME:")
    print("    [P]                   -> Pausa / Ripresa (libera il mouse e rimuove cerchi concentrici)")
    print("    [SPAZIO] / [C]        -> Quick Re-Center (centra il cursore)")
    print("    [Q] / [ESC]           -> Uscita sicura")
    print("=" * 80)

    term_setup()

    # Avvio motore di interpolazione a 120 Hz
    smooth_engine.start()

    loop = asyncio.get_running_loop()
    server = BlessServer(name=BLE_SERVER_NAME, loop=loop)
    server.write_request_func = on_write

    await server.add_new_service(SERVICE_UUID)

    wnr = GATTCharacteristicProperties.write_without_response
    wr = GATTCharacteristicProperties.write
    perms = GATTAttributePermissions.writeable

    await server.add_new_characteristic(SERVICE_UUID, DATA_UUID, wnr, None, perms)
    await server.add_new_characteristic(SERVICE_UUID, CTRL_UUID, wnr | wr, None, perms)

    await server.start()
    print(f"\n  [BLE] Advertising avviato come '{BLE_SERVER_NAME}' (Servizio: {SERVICE_UUID})")
    print("  [BLE] In attesa di connessione dallo smartwatch... Premi [P] per pausa, [Q] per uscire.\n")

    try:
        while True:
            key = poll_keyboard_key()
            if key is not None:
                if key in (b'q', b'Q', b'\x1b'):
                    print("\n\n  Uscita richiesta dall'utente. Arresto server BLE...")
                    break
                elif key in (b' ', b'c', b'C'):
                    mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
                    mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
                    smooth_engine.snap_to(screen_calibrator.center_x, screen_calibrator.center_y)
                    bubble_stabilizer.reset(screen_calibrator.center_x, screen_calibrator.center_y)
                    reset_filters()
                    gesture_guard.reset()
                    print(f"\n  [RE-CENTER] Cursore ricentrato su Monitor {screen_calibrator.active_monitor_index + 1}!")
                elif key in (b'p', b'P'):
                    state.is_paused = not state.is_paused
                    if state.is_paused:
                        smooth_engine.pause()
                        bubble_stabilizer.disable_anchor()
                        action_dispatcher.release_all()
                        print("\n  ⏸️  [PAUSA/RIPRESA] In pausa da tastiera: Cerchi concentrici disattivati | Mouse libero ovunque.")
                    else:
                        state.prev_t_ms = None
                        cur_x, cur_y = mouse_controller.get_position()
                        smooth_engine.snap_to(cur_x, cur_y)
                        bubble_stabilizer.reset(cur_x, cur_y)
                        reset_filters()
                        gesture_guard.reset()
                        smooth_engine.resume()
                        print(f"\n  ▶️  [PAUSA/RIPRESA] Tracking ripreso da tastiera: Cerchi concentrici riattivati a ({cur_x}, {cur_y}).")
            await asyncio.sleep(0.02)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        print("\n\n  Arresto del server BLE in corso...")
        smooth_engine.stop()
        action_dispatcher.release_all()
        await server.stop()
        term_restore()

        if sys.platform == "win32" and HIGH_PRECISION_TIMER:
            try:
                import ctypes
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass

        print("  [OK] Server BLE e risorse rilasciate correttamente.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        term_restore()