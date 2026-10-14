import json
import socket
import sys
import time
# --- START [09/10/2026] Step 1: Modulo Filtro AHRS Madgwick ---
from ahrs import AHRSFilter
# --- END [09/10/2026] Step 1: Modulo Filtro AHRS Madgwick ---
# --- START [09/10/2026] Step 2: Import modulo GestureDetector per Anti-Jumping ---
from gesture_detector import GestureDetector
# --- END [09/10/2026] Step 2: Import modulo GestureDetector per Anti-Jumping ---
# --- START [09/10/2026] Step 3: Import moduli Mappatura Sigmoide e Movimento Mouse PC ---
from mouse_mapper import MouseMapper
from mouse_controller import MouseController
# --- END [09/10/2026] Step 3: Import moduli Mappatura Sigmoide e Movimento Mouse PC ---
# --- START [10/10/2026] Pairing: Import server di discovery e pairing per smartwatch ---
from pairing import PairingServer
# --- END [10/10/2026] Pairing: Import server di discovery e pairing per smartwatch ---
# --- START [11/10/2026] Step 5: Import modulo Calibrazione Sensori e Schermo Adattivo (C-D Gain) ---
from screen_calibrator import ScreenCalibrator

try:
    import msvcrt
except ImportError:
    msvcrt = None
# --- END [11/10/2026] Step 5: Import modulo Calibrazione Sensori e Schermo Adattivo (C-D Gain) ---

HOST = "0.0.0.0"
PORT = 5005

SHOW_RAW = True  # metti False per stampare solo i dati puliti

# --- START [09/10/2026] Step 1: Configurazione Filtro AHRS ---
# Inizializzazione filtro Madgwick AHRS a 20 Hz
# use_magnetometer=False attiva la modalità 6-DOF (IMU pura), consigliata per uso indoor vicino al PC
ahrs_filter = AHRSFilter(sample_rate_hz=20.0, beta=0.1, use_magnetometer=False)

# Seleziona quale segnale dare in pasto all'AHRS:
# True: dati puliti dal WaveletDenoiser
# False: dati raw a latenza zero
USE_DENOISED_FOR_AHRS = True
# --- END [09/10/2026] Step 1: Configurazione Filtro AHRS ---

# --- START [09/10/2026] Step 2: Inizializzazione Macchina a Stati Anti-Jumping ---
# roll_speed_threshold_deg: 100.0 °/s soglia scatto polso
# gyro_norm_threshold_rad: 2.2 rad/s soglia picco velocità angolare
# freeze_hold_time_s: 0.35 s (350 ms) tempo di stabilizzazione minima prima di riprendere il tracciamento
gesture_detector = GestureDetector(
    sample_rate_hz=20.0,
    roll_speed_threshold_deg=100.0,
    gyro_norm_threshold_rad=2.2,
    freeze_hold_time_s=0.35
)
prev_t_ms = None
# --- END [09/10/2026] Step 2: Inizializzazione Macchina a Stati Anti-Jumping ---

# --- START [11/10/2026] Step 5: Inizializzazione Calibratore Schermo e Control-Display Gain ---
# Rileva la risoluzione reale del monitor e calcola i parametri adattivi della Sigmoide
screen_calibrator = ScreenCalibrator(
    ref_width=1920,
    ref_height=1080,
    base_lambda=60.0,
    max_yaw_deg=25.0,
    max_pitch_deg=18.0,
    calibration_samples=40  # 40 campioni a 20 Hz = 2.0 s di fermo per zero-bias
)
# --- END [11/10/2026] Step 5: Inizializzazione Calibratore Schermo e Control-Display Gain ---

# --- START [09/10/2026] Step 3 & [11/10/2026] Step 5: Configurazione MouseMapper e Controller Movimento Mouse ---
# ENABLE_MOUSE_CONTROL: se True muove fisicamente la freccia del mouse sullo schermo del PC
ENABLE_MOUSE_CONTROL = True

# USE_ABSOLUTE_BORESIGHT:
# True:  Modalità Assoluta (Boresight) -> C-D Gain con mappatura diretta angolo braccio su coordinate schermo (centro = posa neutra, bordi = max angolo gomito)
# False: Modalità Relativa (Delta)     -> C-D Gain con spostamento relativo frame-by-frame
USE_ABSOLUTE_BORESIGHT = True

# Parametri Sigmoide Modificata inizializzati con i valori calcolati dal C-D Gain dello Step 5:
# lambda_x, lambda_y scalati su risoluzione schermo; origin_x, origin_y per posizionamento corretto su multi-monitor
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
# --- END [09/10/2026] Step 3 & [11/10/2026] Step 5: Configurazione MouseMapper e Controller Movimento Mouse ---

# --- START [10/10/2026] Pairing: Inizializzazione e avvio PairingServer (Discovery UDP 5006, TCP 5007) ---
pairing = PairingServer(name="AirMouse receiver", udp_port=PORT)
pairing.start()
# --- END [10/10/2026] Pairing: Inizializzazione e avvio PairingServer (Discovery UDP 5006, TCP 5007) ---




def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # non invia nulla, serve solo a scegliere l'interfaccia
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def fmt(v, w=8, d=3):
    return " ".join(f"{x:{w}.{d}f}" for x in v)


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((HOST, PORT))
# --- START [10/10/2026] Pairing: Timeout socket per permettere verifica non bloccante dello stato paired ---
sock.settimeout(0.5)
# --- END [10/10/2026] Pairing: Timeout socket per permettere verifica non bloccante dello stato paired ---

ip = get_local_ip()
mouse_status_str = f"ATTIVO ({mouse_controller.backend_name})" if ENABLE_MOUSE_CONTROL else "DISATTIVATO"

print("=" * 78)
print(f"  IP del PC:              {ip}")
print(f"  Porta UDP Dati:         {PORT}")
print(f"  Protocollo Pairing:     ATTIVO (Discovery UDP {pairing.discovery_port}, Pairing TCP {pairing.tcp_port})")
print(f"  Controllo Mouse PC:     {mouse_status_str}")
# --- START [11/10/2026] Step 5: Informazioni Multi-Monitor, C-D Gain e Risoluzione a Console ---
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
# --- END [11/10/2026] Step 5: Informazioni Multi-Monitor, C-D Gain e Risoluzione a Console ---
print(f"  Macchina a Stati:       Anti-Jumping attivo (MOTION_TRACKING / GESTURE_FREEZE)")
print("=" * 78)

try:
    while True:
        # --- START [10/10/2026] Pairing: Attesa connessione e associazione dello smartwatch ---
        print("\nIn attesa di associazione con uno smartwatch...")
        pairing.wait_until_paired()
        peer = pairing.peer
        if peer:
            print(f"Smartwatch associato: \"{peer.get('name', 'Watch')}\" ({peer.get('ip', 'N/D')})\n")
        count, lost, last_seq = 0, 0, None
        last_report = time.time()
        prev_t_ms = None
        # --- END [10/10/2026] Pairing: Attesa connessione e associazione dello smartwatch ---

        # --- START [11/10/2026] Step 5: Preparazione Calibrazione Statica Sensori e Sincronizzazione Monitor ---
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
            print(f"  🖥️  Rilevato cursore su Monitor {screen_calibrator.active_monitor_index + 1} "
                  f"({screen_calibrator.screen_width}x{screen_calibrator.screen_height} px) -> Monitor sincronizzato!")

        screen_calibrator.start_static_calibration()
        ahrs_filter.reset()
        gesture_detector.reset()

        print("=" * 78)
        print("  🎯 CALIBRAZIONE STATICA INIZIALE (Zero-Bias e Posa Neutra) 🎯")
        print(f"  Punta il braccio dritto in avanti al centro del Monitor {screen_calibrator.active_monitor_index + 1} ({screen_calibrator.screen_width}x{screen_calibrator.screen_height} px).")
        print("  Rimani immobile per 2 secondi...")
        print("=" * 78)
        # --- END [11/10/2026] Step 5: Preparazione Calibrazione Statica Sensori e Sincronizzazione Monitor ---

        # --- START [10/10/2026] Pairing: Loop di ricezione dati vincolato allo stato pairing.paired ---
        while pairing.paired:
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue

            # Filtra i pacchetti per assicurarsi che provengano dallo smartwatch associato
            if not pairing.is_paired_addr(addr):
                continue
            # --- END [10/10/2026] Pairing: Loop di ricezione dati vincolato allo stato pairing.paired ---

            try:
                p = json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                continue

            if last_seq is not None and p["seq"] > last_seq + 1:
                lost += p["seq"] - last_seq - 1
            last_seq = p["seq"]

            a, g, m = p["acc"], p["gyro"], p["mag"]
            raw = p.get("raw", [])
            
            acc_raw = raw[0:3] if len(raw) >= 3 else a
            gyro_raw = raw[3:6] if len(raw) >= 6 else g

            acc_input = a if USE_DENOISED_FOR_AHRS else acc_raw
            gyro_input = g if USE_DENOISED_FOR_AHRS else gyro_raw
            mag_input = m

            # --- START [11/10/2026] Step 5: Fase di Calibrazione Statica a Riposo ---
            if not screen_calibrator.is_calibrated:
                # Esegue stima preliminare orientamento
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

                    # Posizionamento del cursore al centro esatto dello schermo attivo e reset mapper
                    mouse_controller.center_cursor(screen_calibrator.center_x, screen_calibrator.center_y)
                    mouse_mapper.recenter(screen_calibrator.center_x, screen_calibrator.center_y)

                    # Reset dell'anti-jumping e riallineamento temporale
                    gesture_detector.reset()
                    gesture_detector.prev_yaw = temp_euler["yaw"]
                    gesture_detector.prev_pitch = temp_euler["pitch"]
                    gesture_detector.prev_roll = temp_euler["roll"]
                    prev_t_ms = p["t"]
                    last_report = time.time()
                continue
            # --- END [11/10/2026] Step 5: Fase di Calibrazione Statica a Riposo ---

            # --- START [11/10/2026] Step 5: Gestione Quick Re-Center e Controlli Dinamici da tastiera ---
            if msvcrt and msvcrt.kbhit():
                key = msvcrt.getch()
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
            # --- END [11/10/2026] Step 5: Gestione Quick Re-Center e Controlli Dinamici da tastiera ---

            # --- START [11/10/2026] Step 5: Applicazione correzione bias statico giroscopio ---
            gyro_calibrated = screen_calibrator.apply_bias_correction(gyro_input)
            # --- END [11/10/2026] Step 5: Applicazione correzione bias statico giroscopio ---

            # --- START [09/10/2026] Step 1: Calcolo orientamento 3D (AHRS Madgwick con gyro corretto) ---
            euler = ahrs_filter.update(acc_input, gyro_calibrated, mag_input)
            pitch = euler["pitch"]
            yaw = euler["yaw"]
            roll = euler["roll"]
            # --- END [09/10/2026] Step 1: Calcolo orientamento 3D (AHRS Madgwick con gyro corretto) ---

            # --- START [09/10/2026] Step 2: Valutazione Macchina a Stati e Anti-Jumping (Freeze) ---
            t_ms = p["t"]
            dt = (t_ms - prev_t_ms) / 1000.0 if prev_t_ms is not None and (t_ms > prev_t_ms) else 0.05
            prev_t_ms = t_ms

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
            # --- END [09/10/2026] Step 2: Valutazione Macchina a Stati e Anti-Jumping (Freeze) ---

            # --- START [09/10/2026] Step 3 & [11/10/2026] Step 5: Mappatura Cinematica C-D Gain e Controllo Cursore PC ---
            if USE_ABSOLUTE_BORESIGHT:
                # Modalità Assoluta (Boresight): mapping diretto dell'orientamento del braccio sui pixel dello schermo attivo
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
                # Modalità Relativa (Delta): spostamento incrementale con accumulatore sub-pixel
                dx_float, dy_float = mouse_mapper.map_delta(
                    d_yaw=d_yaw,
                    d_pitch=d_pitch,
                    is_frozen=is_frozen
                )
                step_x, step_y = mouse_mapper.get_pixel_steps(dx_float, dy_float)
                if ENABLE_MOUSE_CONTROL and (step_x != 0 or step_y != 0):
                    mouse_controller.move(step_x, step_y)
            # --- END [09/10/2026] Step 3 & [11/10/2026] Step 5: Mappatura Cinematica C-D Gain e Controllo Cursore PC ---



            # --- START [09/10/2026] Step 2 & [11/10/2026] Step 5: Formattazione Stato Anti-Jumping su Console ---
            state_tag = "[FREEZE]" if is_frozen else "[TRACK ]"
            mouse_info = f"POS [{step_x:4d}, {step_y:4d}]" if USE_ABSOLUTE_BORESIGHT else f"DELTA [dx:{dx_float:+5.1f} dy:{dy_float:+5.1f}]"
            print(
                f"#{p['seq']:6d} t={p['t']:10d}ms | "
                f"{state_tag} {state:<16} | "
                f"MOUSE {mouse_info} | "
                f"EULER [P:{pitch:+6.1f}° Y:{yaw:+6.1f}° R:{roll:+6.1f}°] | "
                f"ACC [{fmt(a)}] | GYR [{fmt(gyro_calibrated)}]"
            )
            # --- END [09/10/2026] Step 2 & [11/10/2026] Step 5: Formattazione Stato Anti-Jumping su Console ---

            if SHOW_RAW and "raw" in p:
                r = p["raw"]
                print(
                    f"{'raw':>7s} {'':14s} | "
                    f"{'':25s} | "
                    f"{'':27s} | "
                    f"{'':34s} | "
                    f"ACC [{fmt(r[0:3])}] | GYR [{fmt(r[3:6])}] | MAG [{fmt(r[6:9], 8, 2)}]"
                )

            count += 1
            now = time.time()
            if now - last_report >= 1.0:
                print(f"--- {count / (now - last_report):.1f} Hz da {addr[0]} | persi: {lost} ---")
                count, last_report = 0, now

except KeyboardInterrupt:
    print("\n\nChiusura ricevitore UDP.")
finally:
    # --- START [10/10/2026] Pairing: Chiusura server di pairing e thread di background ---
    pairing.stop()
    # --- END [10/10/2026] Pairing: Chiusura server di pairing e thread di background ---
    # --- START [09/10/2026] Step 1: Chiusura sicura delle risorse (socket) ---
    sock.close()
    # --- END [09/10/2026] Step 1: Chiusura sicura delle risorse (socket) ---