# --- START [18/10/2026] Step 11: Server BLE Integrato Motion Tracking & Gesture Recognition (ble-serverV1.py) ---
"""
ble-serverV1.py: Server BLE GATT unificato che orchestra Motion Tracking ultra-fluido
a 120 Hz e Riconoscimento Gesti Real-Time con esecuzione di azioni mouse cross-platform.

Architettura completamente modulare:
- motionTrackingModule: AHRSFilter, MouseController, MouseMapper, ScreenCalibrator,
                        SpatialBubbleStabilizer, SmoothCursorEngine.
- gestureRecognitionUtils: ForestPredictor, OnlineGestureDetector, GestureActionDispatcher, train (T).
- ble-serverV1.py: Server BLE GATT (Bless), unpack dei pacchetti binari, loop asincrono e HUD.
"""

import asyncio
import logging
import os
import struct
import sys
import time

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
from motionTrackingModule.mouse_controller import MouseController
from motionTrackingModule.mouse_mapper import MouseMapper
from motionTrackingModule.screen_calibrator import ScreenCalibrator
from motionTrackingModule.stabilizer import SpatialBubbleStabilizer

# --- Moduli di Gesture Recognition e Azioni Desktop (gestureRecognitionUtils) ---
import gestureRecognitionUtils.train as T
from gestureRecognitionUtils.action_dispatcher import GestureActionDispatcher
from gestureRecognitionUtils.detector import ForestPredictor, OnlineGestureDetector

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
# True: usa i dati filtrati dal WaveletDenoiser dello smartwatch
# False: usa il flusso grezzo raw a latenza zero (consigliato per reattività istantanea)
USE_DENOISED_STREAM = False
AHRS_BETA = 0.10                   # Guadagno convergenza filtro Madgwick
CALIBRATION_DURATION_SEC = 2.0     # Durata calibrazione statica iniziale (40 campioni a 20 Hz)

# --- 3. Mappatura Cinematica Cursore (Control-Display Gain) ---
ENABLE_MOUSE_CONTROL = True        # True: muove fisicamente il mouse sul sistema operativo
SCALE_FACTOR = 1.00                # Moltiplicatore globale sensibilità
MAX_YAW_DEG = 25.0                 # Escursione orizzontale confortevole gomito (gradi)
MAX_PITCH_DEG = 18.0               # Escursione verticale confortevole gomito (gradi)
DEADZONE_DEG = 0.08                # Dead-zone angolare della Sigmoide (gradi)

# --- 4. Motore di Interpolazione a 120 Hz e Stabilizzazione Spaziale ---
ENABLE_SMOOTH_120HZ = True         # Abilita thread interpolatore a 120 FPS
CURSOR_ENGINE_HZ = 120.0           # Frequenza di campionamento del thread cursore
SMOOTH_TIME_S = 0.026              # Costante di tempo smorzamento SmoothDamp (~26 ms)
HIGH_PRECISION_TIMER = True        # Win32 timeBeginPeriod(1) a 1 ms

# Parametri Bolla Spaziale Soft-Edge
BUBBLE_ENABLED = True
BUBBLE_INNER_RADIUS_PX = 2.5       # Raggio interno: soppressione totale del tremolio a riposo (pixel)
BUBBLE_OUTER_RADIUS_PX = 7.0       # Raggio esterno: transizione Hermite morbida continua (pixel)
BUBBLE_STILL_TIME_S = 0.15         # Tempo minimo di fermo per ricentrare la bolla (secondi)

# --- 5. Riconoscimento Gesti (Online Gesture Classifier) ---
GESTURE_MODEL_PATH = os.path.join(_GEST_DIR, "trainedTree", "rf.json")
GESTURE_PEAK_THRESH = 0.40         # Soglia minima di ampiezza picco/valle angolare (rad)
GESTURE_MIN_CONFIDENCE = 0.50      # Soglia minima di confidenza della Random Forest (0.0 - 1.0)
GESTURE_COOLDOWN_SAMPLES = 30      # Campioni di cooldown post-gesto (30 campioni = 1.5 s a 20 Hz)
GESTURE_FREEZE_DURATION_SEC = 0.40 # Tempo di congelamento anti-jumping del cursore durante il gesto

# --- 6. Mappatura Gesto -> Azione Mouse Cross-Platform ---
#   'RLB': Rotate-Left-Back  -> Click Sinistro / Selezione (Select) o rilascio drag
#   'RRB': Rotate-Right-Back -> Click Destro / Menu Contestuale (Context Menu)
#   'UDB': Up-Down-Back      -> Toggle Trascinamento / Selezione Multipla (Drag & Drop)
#   'MLB': Move-Left-Back    -> Scroll rotellina in alto (Scroll Up)
#   'MRB': Move-Right-Back   -> Scroll rotellina in basso (Scroll Down)
GESTURE_ACTION_MAP = {
    "RLB": "select",
    "RRB": "right_click",
    "UDB": "drag_toggle",
    "MLB": "scroll_up",
    "MRB": "scroll_down",
}
SCROLL_STEPS = 3                   # Scatti di scroll verticale per ogni gesto


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
        self.freeze_until = 0.0

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
            gesture_detector.reset()
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

    # 3. VERIFICA CONGELAMENTO ANTI-JUMPING POST-GESTO
    now_time = time.time()
    is_gesture_frozen = (now_time < state.freeze_until)

    # 4. FUSIONE SENSORIALE MADGWICK AHRS
    gyro_calibrated = screen_calibrator.apply_bias_correction(gyro_input)
    euler = ahrs_filter.update(acc_input, gyro_calibrated, mag_input, dt=dt)
    state.yaw = euler["yaw"]
    state.pitch = euler["pitch"]
    state.roll = euler["roll"]

    # 5. MAPPATURA CINEMATICA SCHERMO C-D GAIN
    raw_tx, raw_ty = mouse_mapper.map_absolute(
        yaw=state.yaw,
        pitch=state.pitch,
        zero_yaw=screen_calibrator.zero_euler["yaw"],
        zero_pitch=screen_calibrator.zero_euler["pitch"],
        is_frozen=is_gesture_frozen,
        dt=dt,
    )

    # 6. STABILIZZAZIONE SPAZIALE (Hermite Smoothstep)
    target_x, target_y, stab_state = bubble_stabilizer.update(raw_tx, raw_ty, is_frozen=is_gesture_frozen)
    state.target_x = target_x
    state.target_y = target_y
    state.stabilizer_state = stab_state

    # 7. INVIO AL MOTORE INTERPOLATORE 120 HZ
    if ENABLE_MOUSE_CONTROL:
        smooth_engine.set_target(target_x, target_y)

    # 8. RICONOSCIMENTO GESTI ONLINE (Random Forest)
    if forest_model is not None:
        cand = gesture_detector.push(acc_input, gyro_input, mag_input)
        if cand is not None:
            window, info = cand
            feats = T.feats(window)
            label, conf = forest_model.predict(feats)

            if conf >= GESTURE_MIN_CONFIDENCE:
                # Congela temporaneamente il puntatore per evitare salti sul bersaglio
                state.freeze_until = time.time() + GESTURE_FREEZE_DURATION_SEC

                # Esegue l'azione mouse cross-platform tramite il Dispatcher
                action_desc = action_dispatcher.execute_gesture(label, conf, info)

                print("\n" + "=" * 80)
                print(f"  >>> [GESTO RILEVATO] {label} (Confidenza: {conf * 100:.1f}% | Asse: {info['axis']} | Score: {info['score']:.2f} rad)")
                print(f"  >>> [AZIONE ESEGUITA] {action_desc} (OS: {sys.platform})")
                print("=" * 80 + "\n")

    # 9. CONSOLE HUD THROTTLED A 10 HZ
    now = time.time()
    if now - state.last_hud >= 0.10:
        freq = state.window_count / max(0.001, now - state.last_report) if (now - state.last_report) > 0.0 else 20.0
        drag_str = "[DRAG ON]" if action_dispatcher.is_dragging else "[DRAG OFF]"
        freeze_str = "[FREEZE]" if is_gesture_frozen else f"[{stab_state}]"
        print(
            f"  [BLE {freq:4.1f} Hz] {drag_str} {freeze_str} "
            f"Pos: ({target_x:4.0f}, {target_y:4.0f}) px | "
            f"Ultimo Gesto: {action_dispatcher.last_gesture} ({action_dispatcher.last_confidence * 100:.0f}%) -> {action_dispatcher.last_action_desc[:24]}",
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
        if action_dispatcher.is_dragging:
            mouse_controller.release("left")
            action_dispatcher.is_dragging = False
        screen_calibrator.start_static_calibration()
        ahrs_filter.reset()
        gesture_detector.reset()

    elif msg == b"pause":
        state.is_paused = True
        smooth_engine.pause()
        bubble_stabilizer.disable_anchor()
        if action_dispatcher.is_dragging:
            mouse_controller.release("left")
            action_dispatcher.is_dragging = False
        print("\n  ⏸️  [BLE ctrl] STREAMING IN PAUSA: Cerchi concentrici disattivati | Mouse libero ovunque.")

    elif msg == b"resume":
        state.is_paused = False
        state.prev_t_ms = None
        cur_x, cur_y = mouse_controller.get_position()
        smooth_engine.snap_to(cur_x, cur_y)
        bubble_stabilizer.reset(cur_x, cur_y)
        smooth_engine.resume()
        print(f"\n  ▶️  [BLE ctrl] STREAMING RIPRESO dallo smartwatch: Motion tracking e cerchi concentrici riattivati a ({cur_x}, {cur_y}).")


def on_write(characteristic: BlessGATTCharacteristic, value, **kwargs):
    uuid = str(characteristic.uuid).lower()
    data = bytes(value)
    if uuid == DATA_UUID:
        handle_data(data)
    elif uuid == CTRL_UUID:
        handle_ctrl(data)


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
# MAIN ASYNC BLE GATT SERVER
# ==============================================================================
async def main():
    print("=" * 80)
    print("      AirMouse - BLE Server V1 (Motion Tracking + Gesture Recognition)")
    print("=" * 80)
    print(f"  Sistema Operativo Rilevato : {sys.platform} (Backend: {mouse_controller.backend_name})")
    print(f"  Display Attivo             : {screen_calibrator.screen_width} x {screen_calibrator.screen_height} px")
    print(f"  Motore Cursore 120 Hz      : {'ATTIVO' if ENABLE_SMOOTH_120HZ else 'DISATTIVATO'}")
    print(f"  Stabilizzatore Bolla       : {'ATTIVO' if BUBBLE_ENABLED else 'DISATTIVATO'} (R_in: {BUBBLE_INNER_RADIUS_PX}px, R_out: {BUBBLE_OUTER_RADIUS_PX}px)")
    print(f"  Flusso Sensori IMU         : {'DENOISED (Wavelet)' if USE_DENOISED_STREAM else 'RAW (0 ms Latenza)'}")
    print(f"  Mappatura Gesti            : {GESTURE_ACTION_MAP}")
    print("=" * 80)
    print("  CONTROLLI RUNTIME:")
    print("    [P]                   -> Pausa / Ripresa (libera il mouse e rimuove cerchi concentrici)")
    print("    [SPAZIO] / [C]        -> Quick Re-Center (centra il cursore)")
    print("    [Q] / [ESC]           -> Uscita sicura")
    print("=" * 80)

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
                    print(f"\n  [RE-CENTER] Cursore ricentrato su Monitor {screen_calibrator.active_monitor_index + 1}!")
                elif key in (b'p', b'P'):
                    state.is_paused = not state.is_paused
                    if state.is_paused:
                        smooth_engine.pause()
                        bubble_stabilizer.disable_anchor()
                        if action_dispatcher.is_dragging:
                            mouse_controller.release("left")
                            action_dispatcher.is_dragging = False
                        print("\n  ⏸️  [PAUSA/RIPRESA] In pausa da tastiera: Cerchi concentrici disattivati | Mouse libero ovunque.")
                    else:
                        state.prev_t_ms = None
                        cur_x, cur_y = mouse_controller.get_position()
                        smooth_engine.snap_to(cur_x, cur_y)
                        bubble_stabilizer.reset(cur_x, cur_y)
                        smooth_engine.resume()
                        print(f"\n  ▶️  [PAUSA/RIPRESA] Tracking ripreso da tastiera: Cerchi concentrici riattivati a ({cur_x}, {cur_y}).")
            await asyncio.sleep(0.02)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        print("\n\n  Arresto del server BLE in corso...")
        smooth_engine.stop()
        if action_dispatcher.is_dragging:
            mouse_controller.release("left")
        await server.stop()

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
# --- END [18/10/2026] Step 11: Server BLE Integrato Motion Tracking & Gesture Recognition (ble-serverV1.py) ---
