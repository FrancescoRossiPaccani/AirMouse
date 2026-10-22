"""
reciverV1.py - Ricevitore AirMouse PC con connessione BLE (GATT Server).

Il PC fa advertising del servizio GATT, lo smartwatch Wear OS (central) si connette
e invia i dati dei sensori in streaming sulla characteristic DATA.
Utilizza la stessa architettura BLE di ble-serverV0.py e BLE-Client.

Formato pacchetto (little endian):
    int32 seq | int32 t_ms | 9 x float32 clean (acc, gyro, mag) | [9 x float32 raw]
    -> 44 byte, oppure 80 byte se è presente anche il raw.
"""

import asyncio
import logging
import os
import struct
import sys
import time

# Assicura che la cartella root del progetto sia nel sys.path
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

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

# --- START [18/10/2026] Step 8: Input da tastiera non-bloccante cross-platform ---
def poll_keyboard_key():
    """
    Legge un carattere da tastiera in modo non bloccante.
    Supporta Windows (msvcrt) e Linux/macOS (select su sys.stdin).
    """
    if msvcrt and msvcrt.kbhit():
        return msvcrt.getch()
    if sys.platform != "win32":
        try:
            import select
            if select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1)
                return ch.encode('utf-8', errors='ignore')
        except Exception:
            pass
    return None
# --- END [18/10/2026] Step 8: Input da tastiera non-bloccante cross-platform ---


# ==============================================================================
# CONFIGURAZIONE BLE (Identici a BleClient.kt e ble-serverV0.py)
# ==============================================================================
SERVICE_UUID = "7a1c0001-4f5e-4b8a-9d3c-2e6f1a0b5c01"
DATA_UUID = "7a1c0002-4f5e-4b8a-9d3c-2e6f1a0b5c01"
CTRL_UUID = "7a1c0003-4f5e-4b8a-9d3c-2e6f1a0b5c01"

SERVER_NAME = "AirMouse-PC"

SIZE_CLEAN = 44
SIZE_FULL = 80

SHOW_RAW = True  # metti False per stampare solo i dati puliti


# ==============================================================================
# CONFIGURAZIONE TRACKING E FUSIONE SENSORIALE
# ==============================================================================
# Filtro Madgwick AHRS a 20 Hz (IMU pura 6-DOF per uso indoor vicino al PC)
ahrs_filter = AHRSFilter(sample_rate_hz=20.0, beta=0.1, use_magnetometer=False)

# True: usa i dati filtrati dal WaveletDenoiser dello smartwatch
# False: usa i dati grezzi raw a latenza zero
USE_DENOISED_FOR_AHRS = True

# Macchina a Stati Anti-Jumping
gesture_detector = GestureDetector(
    sample_rate_hz=20.0,
    roll_speed_threshold_deg=100.0,
    gyro_norm_threshold_rad=2.2,
    freeze_hold_time_s=0.35
)

# Calibratore Schermo e Control-Display Gain
screen_calibrator = ScreenCalibrator(
    ref_width=1920,
    ref_height=1080,
    base_lambda=60.0,
    max_yaw_deg=25.0,
    max_pitch_deg=18.0,
    calibration_samples=40  # 40 campioni a 20 Hz = 2.0 s per zero-bias
)

ENABLE_MOUSE_CONTROL = True
USE_ABSOLUTE_BORESIGHT = True

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
    deadzone_deg=0.15,
    invert_x=True,
    invert_y=True,
    scale_factor=1.0,
    smooth_min_alpha=0.30,
    smooth_max_alpha=0.85
)
mouse_controller = MouseController()


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
        self.prev_t_ms = None
        self.yaw = 0.0
        self.pitch = 0.0
        self.roll = 0.0
        # --- START [18/10/2026] Step 9: Stato Pausa streaming ---
        self.is_paused = False
        # --- END [18/10/2026] Step 9: Stato Pausa streaming ---


state = SessionState()


def fmt(v, w=8, d=3):
    return " ".join(f"{x:{w}.{d}f}" for x in v)


def parse_packet(data: bytes):
    """
    Ritorna:
        (seq, t_ms, clean[9], raw[9] | None)
    clean = [ax, ay, az, gx, gy, gz, mx, my, mz]
    raw   = [ax, ay, az, gx, gy, gz, mx, my, mz]
    """
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
# ELABORAZIONE CAMPIONI (PIPELINE TRACKING IDENTICA A PRIMA)
# ==============================================================================
def process_sample(seq, t_ms, clean, raw):
    global USE_ABSOLUTE_BORESIGHT

    # Conteggio pacchetti persi
    if state.last_seq is not None and seq > state.last_seq + 1:
        state.lost += seq - state.last_seq - 1
    state.last_seq = seq

    a = clean[0:3]
    g = clean[3:6]
    m = clean[6:9]

    acc_raw = raw[0:3] if raw is not None else a
    gyro_raw = raw[3:6] if raw is not None else g

    acc_input = a if USE_DENOISED_FOR_AHRS else acc_raw
    gyro_input = g if USE_DENOISED_FOR_AHRS else gyro_raw
    mag_input = m

    # 1. Fase di Calibrazione Statica a Riposo (2 secondi)
    if not screen_calibrator.is_calibrated:
        temp_euler = ahrs_filter.update(acc_input, gyro_input, mag_input)
        is_completed = screen_calibrator.add_calibration_sample(gyro_input, temp_euler)
        pct = screen_calibrator.progress_percentage
        print(f"  Calibrazione in corso: {pct:5.1f}% | campioni: {screen_calibrator._samples_count}/{screen_calibrator.calibration_samples}", end="\r")

        if is_completed:
            print("\n" + "=" * 78)
            print("  ✅ CALIBRAZIONE COMPLETATA CON SUCCESSO!")
            print(f"  Bias Giroscopio (rad/s): [{screen_calibrator.gyro_bias[0]:+.4f}, "
                  f"{screen_calibrator.gyro_bias[1]:+.4f}, {screen_calibrator.gyro_bias[2]:+.4f}]")
            print(f"  Posa Neutra Centro: Yaw={screen_calibrator.zero_euler['yaw']:+.1f}°, "
                  f"Pitch={screen_calibrator.zero_euler['pitch']:+.1f}°")
            print(f"  Cursore posizionato al centro del Monitor {screen_calibrator.active_monitor_index + 1} "
                  f"({screen_calibrator.center_x}, {screen_calibrator.center_y})")
            print("  MOTION TRACKING ATTIVO. [Premi SPAZIO o C per ricentrare, S o TAB per cambiare monitor]")
            print("=" * 78 + "\n")

            mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
            mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)

            gesture_detector.reset()
            gesture_detector.prev_yaw = temp_euler["yaw"]
            gesture_detector.prev_pitch = temp_euler["pitch"]
            gesture_detector.prev_roll = temp_euler["roll"]
            state.prev_t_ms = t_ms
            state.last_report = time.time()
        return

    # --- START [18/10/2026] Step 9: Sospensione del tracking e blocco cursore in Pausa ---
    if state.is_paused:
        now = time.time()
        if now - state.last_report >= 0.5:
            print(f"  [PAUSA STREAMING] Cursore congelato a ({mouse_mapper.current_x:.0f}, {mouse_mapper.current_y:.0f})", end="\r")
            state.last_report = now
        return
    # --- END [18/10/2026] Step 9: Sospensione del tracking e blocco cursore in Pausa ---

    # 2. Correzione Bias Giroscopio e Aggiornamento Orientamento AHRS
    gyro_calibrated = screen_calibrator.apply_bias_correction(gyro_input)
    euler = ahrs_filter.update(acc_input, gyro_calibrated, mag_input)
    pitch = euler["pitch"]
    yaw = euler["yaw"]
    roll = euler["roll"]

    state.pitch, state.yaw, state.roll = pitch, yaw, roll

    # 3. Intervallo Temporale dt e Anti-Jumping
    dt = (t_ms - state.prev_t_ms) / 1000.0 if state.prev_t_ms is not None and (t_ms > state.prev_t_ms) else 0.05
    state.prev_t_ms = t_ms

    gesture_state, is_frozen, deltas = gesture_detector.update(
        pitch=pitch,
        yaw=yaw,
        roll=roll,
        gyro=gyro_calibrated,
        dt=dt
    )
    d_pitch = deltas["d_pitch"]
    d_yaw = deltas["d_yaw"]

    # 4. Mappatura Movimento C-D Gain e Controllo Mouse
    if USE_ABSOLUTE_BORESIGHT:
        zero_yaw = screen_calibrator.zero_euler["yaw"]
        zero_pitch = screen_calibrator.zero_euler["pitch"]
        screen_x, screen_y = mouse_mapper.map_absolute(
            yaw=yaw,
            pitch=pitch,
            zero_yaw=zero_yaw,
            zero_pitch=zero_pitch,
            is_frozen=is_frozen,
            dt=dt
        )
        dx_float = float(screen_x - screen_calibrator.center_x)
        dy_float = float(screen_y - screen_calibrator.center_y)
        step_x = screen_x
        step_y = screen_y

        if ENABLE_MOUSE_CONTROL:
            mouse_controller.set_position(screen_x, screen_y)
    else:
        dx_float, dy_float = mouse_mapper.map_delta(
            d_yaw=d_yaw,
            d_pitch=d_pitch,
            is_frozen=is_frozen
        )
        step_x, step_y = mouse_mapper.get_pixel_steps(dx_float, dy_float)
        if ENABLE_MOUSE_CONTROL and (step_x != 0 or step_y != 0):
            mouse_controller.move(step_x, step_y)

    # 5. Output Console Formattato
    state_tag = "[FREEZE]" if is_frozen else "[TRACK ]"
    mouse_info = f"POS [{step_x:4d}, {step_y:4d}]" if USE_ABSOLUTE_BORESIGHT else f"DELTA [dx:{dx_float:+5.1f} dy:{dy_float:+5.1f}]"
    #print(
        #f"#{seq:6d} t={t_ms:10d}ms | "
        #f"{state_tag} {gesture_state:<16} | "
        #f"MOUSE {mouse_info} | "
        #f"EULER [P:{pitch:+6.1f}° Y:{yaw:+6.1f}° R:{roll:+6.1f}°] | "
        #f"ACC [{fmt(a)}] | GYR [{fmt(gyro_calibrated)}]"
    #)

    if SHOW_RAW and raw is not None:
        r = raw
        #print(
            #f"{'raw':>7s} {'':14s} | "
            #f"{'':25s} | "
            #f"{'':27s} | "
            #f"{'':34s} | "
            #f"ACC [{fmt(r[0:3])}] | GYR [{fmt(r[3:6])}] | MAG [{fmt(r[6:9], 8, 2)}]"
        #)

    state.count += 1
    now = time.time()
    if now - state.last_report >= 1.0:
        print(f"--- {state.count / (now - state.last_report):.1f} Hz (BLE) | persi: {state.lost} ---")
        state.count = 0
        state.last_report = now


# ==============================================================================
# GESTIONE COMANDI TASTIERA
# ==============================================================================
def handle_keyboard(key):
    global USE_ABSOLUTE_BORESIGHT

    yaw, pitch, roll = state.yaw, state.pitch, state.roll

    if key in (b' ', b'c', b'C'):
        mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
        screen_calibrator.recenter_pose({"yaw": yaw, "pitch": pitch, "roll": roll})
        mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)
        gesture_detector.prev_yaw = yaw
        gesture_detector.prev_pitch = pitch
        gesture_detector.prev_roll = roll
        print(f"\n  🎯 [RE-CENTER] Cursore ricentrato su Monitor {screen_calibrator.active_monitor_index + 1} "
              f"({screen_calibrator.center_x}, {screen_calibrator.center_y})!")
    elif key in (b's', b'S', b'\t'):
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
        screen_calibrator.recenter_pose({"yaw": yaw, "pitch": pitch, "roll": roll})
        gesture_detector.prev_yaw = yaw
        gesture_detector.prev_pitch = pitch
        gesture_detector.prev_roll = roll
        print(f"\n  🖥️ [SWITCH MONITOR] Passato a Monitor {screen_calibrator.active_monitor_index + 1} "
              f"({screen_calibrator.screen_width}x{screen_calibrator.screen_height} px) "
              f"| Centro: ({screen_calibrator.center_x}, {screen_calibrator.center_y})")
    elif key in (b'm', b'M'):
        USE_ABSOLUTE_BORESIGHT = not USE_ABSOLUTE_BORESIGHT
        mode_name = "ASSOLUTA (Boresight)" if USE_ABSOLUTE_BORESIGHT else "RELATIVA (Delta)"
        print(f"\n  🔄 [MODALITÀ MOUSE] Switch a: {mode_name}")
    elif key in (b'+', b'='):
        mouse_mapper.scale_factor = round(mouse_mapper.scale_factor + 0.1, 2)
        print(f"\n  📈 [SENSIBILITÀ] scale_factor = {mouse_mapper.scale_factor:.2f}")
    elif key in (b'-', b'_'):
        mouse_mapper.scale_factor = max(0.2, round(mouse_mapper.scale_factor - 0.1, 2))
        print(f"\n  📉 [SENSIBILITÀ] scale_factor = {mouse_mapper.scale_factor:.2f}")
    # --- START [18/10/2026] Step 9: Hotkey Pausa/Ripresa su PC ---
    elif key in (b'p', b'P'):
        state.is_paused = not state.is_paused
        status_str = "IN PAUSA (Cursore Bloccato)" if state.is_paused else "RIPRESO (Tracking Attivo)"
        if not state.is_paused:
            state.prev_t_ms = None  # Reset dt per evitare sbalzi
        print(f"\n  ⏸️  [PAUSA/RIPRESA] Toggle da tastiera PC: {status_str}")
    # --- END [18/10/2026] Step 9: Hotkey Pausa/Ripresa su PC ---


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
        print("\n  [BLE ctrl] Lo smartwatch si è disconnesso (bye). In attesa di nuova connessione...")
        state.reset()
        screen_calibrator.start_static_calibration()
        ahrs_filter.reset()
        gesture_detector.reset()
    # --- START [18/10/2026] Step 9: Gestione messaggi CTRL di Pausa e Ripresa ---
    elif msg == b"pause":
        state.is_paused = True
        print("\n  ⏸️  [BLE ctrl] STREAMING IN PAUSA dallo smartwatch. Cursore congelato.")
    elif msg == b"resume":
        state.is_paused = False
        state.prev_t_ms = None
        print("\n  ▶️  [BLE ctrl] STREAMING RIPRESO dallo smartwatch. Tracking riattivato.")
    # --- END [18/10/2026] Step 9: Gestione messaggi CTRL di Pausa e Ripresa ---


def on_write(characteristic: BlessGATTCharacteristic, value, **kwargs):
    uuid = str(characteristic.uuid).lower()
    data = bytes(value)

    if uuid == DATA_UUID:
        handle_data(data)
    elif uuid == CTRL_UUID:
        handle_ctrl(data)


def print_banner():
    mouse_status_str = f"ATTIVO ({mouse_controller.backend_name})" if ENABLE_MOUSE_CONTROL else "DISATTIVATO"
    print("=" * 78)
    print("  🚀 AIRMOUSE RECEIVER V1 (BLE) - MOTION TRACKING 🚀")
    print("=" * 78)
    print(f"  Server BLE GATT:        ATTIVO (Nome: '{SERVER_NAME}')")
    print(f"  Servizio UUID:          {SERVICE_UUID}")
    print(f"  Caratteristica Dati:    {DATA_UUID}")
    print(f"  Caratteristica Ctrl:    {CTRL_UUID}")
    print(f"  Controllo Mouse PC:     {mouse_status_str}")
    print(f"  Monitor Rilevati:       {len(screen_calibrator.monitors)}")
    for m in screen_calibrator.monitors:
        active_tag = " [*ATTIVO*]" if m['index'] == screen_calibrator.active_monitor_index else ""
        prim_tag = " (Primario)" if m['is_primary'] else " (Secondario)"
        print(f"    - Monitor {m['index']+1}{prim_tag}: {m['width']}x{m['height']} px | "
              f"origin: ({m['left']}, {m['top']}) | centro: ({m['center_x']}, {m['center_y']}){active_tag}")
    print(f"  Parametri C-D Gain:     Max Gomito: [Yaw: ±{screen_calibrator.max_yaw_deg}°, Pitch: ±{screen_calibrator.max_pitch_deg}°] | "
          f"r=[X:{screen_calibrator.cd_params['rx']}, Y:{screen_calibrator.cd_params['ry']}]")
    print(f"  Modalità Movimento:     ASSOLUTA (Boresight) [M: toggle Assoluta/Relativa, S/TAB: switch monitor, +/-: sensibilità]")
    print(f"  Calibrazione Sensori:   Automatica (2 s a braccio fermo dritto al centro del monitor attivo)")
    print(f"  Comando Re-Center:      Premi [SPAZIO] o [C] durante il tracking per ricentrare")
    print(f"  Macchina a Stati:       Anti-Jumping attivo (MOTION_TRACKING / GESTURE_FREEZE)")
    print("=" * 78)


# ==============================================================================
# AVVIO SERVER BLE E LOOP EVENTI
# ==============================================================================
async def main():
    loop = asyncio.get_running_loop()

    server = BlessServer(name=SERVER_NAME, loop=loop)
    server.write_request_func = on_write

    await server.add_new_service(SERVICE_UUID)

    wnr = GATTCharacteristicProperties.write_without_response
    wr = GATTCharacteristicProperties.write
    perms = GATTAttributePermissions.writeable

    await server.add_new_characteristic(SERVICE_UUID, DATA_UUID, wnr, None, perms)
    await server.add_new_characteristic(SERVICE_UUID, CTRL_UUID, wnr | wr, None, perms)

    await server.start()

    print_banner()

    # Sincronizza il monitor attivo rilevando dove si trova fisicamente il cursore dell'utente all'avvio
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

    screen_calibrator.start_static_calibration()
    ahrs_filter.reset()
    gesture_detector.reset()

    print("\nAdvertising BLE avviato.")
    print("In attesa dello smartwatch Wear OS... [Q] o [ESC] per uscire.\n")

    try:
        while True:
            # --- START [18/10/2026] Step 8: Input da tastiera non-bloccante cross-platform ---
            key = poll_keyboard_key()
            if key is not None:
                if key in (b'q', b'Q', b'\x1b'):
                    break
                handle_keyboard(key)
            # --- END [18/10/2026] Step 8: Input da tastiera non-bloccante cross-platform ---
            await asyncio.sleep(0.02)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await server.stop()
        print("\nServer BLE arrestato con successo.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass