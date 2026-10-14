# --- START [09/10/2026] Step 2: Modulo Macchina a Stati e Rilevamento Gesture (Anti-Jumping) ---
"""
gesture_detector.py: Macchina a stati e rilevamento causale real-time dei picchi di velocità angolare.
Implementa il meccanismo Anti-Jumping di Magic-Hand: quando viene rilevato uno scatto del polso
(click intenzionale o gesture), il sistema congela lo spostamento del mouse per evitare salti involontari.
"""
import math

class GestureDetector:
    """
    Gestisce la macchina a stati:
      - MOTION_TRACKING: normale movimento e tracciamento del cursore.
      - GESTURE_FREEZE:  rilevato scatto rapido/gesture, cursore congelato (delta forzati a 0).
    """

    STATE_MOTION_TRACKING = "MOTION_TRACKING"
    STATE_GESTURE_FREEZE = "GESTURE_FREEZE"

    def __init__(
        self,
        sample_rate_hz: float = 20.0,
        roll_speed_threshold_deg: float = 100.0,   # Soglia velocità angolare su Roll in °/s
        gyro_norm_threshold_rad: float = 2.2,     # Soglia magnitudine velocità angolare in rad/s
        freeze_hold_time_s: float = 0.35,         # Tempo di permanenza/stabilizzazione minima sotto soglia (350 ms)
        # --- START [11/10/2026] Step 6: Parametro freeze_on_roll_only (Default False per versione base) ---
        freeze_on_roll_only: bool = False
        # --- END [11/10/2026] Step 6: Parametro freeze_on_roll_only (Default False per versione base) ---
    ):
        self.sample_rate_hz = sample_rate_hz
        self.dt_default = 1.0 / sample_rate_hz
        self.roll_speed_threshold_deg = roll_speed_threshold_deg
        self.gyro_norm_threshold_rad = gyro_norm_threshold_rad
        self.freeze_hold_time_s = freeze_hold_time_s
        self.freeze_on_roll_only = freeze_on_roll_only

        # Stato corrente
        self.state = self.STATE_MOTION_TRACKING

        # Ultimi angoli registrati per il calcolo dei delta
        self.prev_pitch = None
        self.prev_yaw = None
        self.prev_roll = None

        # Contatore tempo di stabilizzazione sotto soglia
        self.stable_time_s = 0.0

    @staticmethod
    def normalize_delta_degrees(delta_deg: float) -> float:
        """
        Normalizza una differenza angolare nell'intervallo [-180°, +180°]
        per gestire l'attraversamento della discontinuità angolare (unwrapping).
        """
        d = delta_deg % 360.0
        if d > 180.0:
            d -= 360.0
        elif d < -180.0:
            d += 360.0
        return d

    def reset(self):
        """Ripristina lo stato iniziale della macchina a stati."""
        self.state = self.STATE_MOTION_TRACKING
        self.prev_pitch = None
        self.prev_yaw = None
        self.prev_roll = None
        self.stable_time_s = 0.0

    def update(self, pitch: float, yaw: float, roll: float, gyro=None, dt: float = None):
        """
        Aggiorna la macchina a stati con i nuovi angoli e la lettura del giroscopio.
        
        :param pitch: angolo Pitch attuale in gradi
        :param yaw:   angolo Yaw attuale in gradi
        :param roll:  angolo Roll attuale in gradi
        :param gyro:  lettura giroscopio [gx, gy, gz] in rad/s (opzionale)
        :param dt:    intervallo di tempo dal campione precedente in secondi
        :return: (state, is_frozen, deltas) dove:
                 - state: stringa ("MOTION_TRACKING" o "GESTURE_FREEZE")
                 - is_frozen: booleano (True se il cursore deve essere bloccato)
                 - deltas: dict con {"d_pitch": float, "d_yaw": float, "d_roll": float}
        """
        if dt is None or dt <= 0:
            dt = self.dt_default

        # Se è il primo campione, inizializza le variabili e mantieni MOTION_TRACKING
        if self.prev_pitch is None:
            self.prev_pitch = pitch
            self.prev_yaw = yaw
            self.prev_roll = roll
            deltas = {"d_pitch": 0.0, "d_yaw": 0.0, "d_roll": 0.0}
            return self.state, False, deltas

        # 1. Calcolo delta angolari con unwrapping
        d_pitch = self.normalize_delta_degrees(pitch - self.prev_pitch)
        d_yaw = self.normalize_delta_degrees(yaw - self.prev_yaw)
        d_roll = self.normalize_delta_degrees(roll - self.prev_roll)

        self.prev_pitch = pitch
        self.prev_yaw = yaw
        self.prev_roll = roll

        deltas = {
            "d_pitch": d_pitch,
            "d_yaw": d_yaw,
            "d_roll": d_roll
        }

        # 2. Calcolo indicatori di velocità angolare (scatto/jerk)
        roll_speed = abs(d_roll) / dt  # Velocità angolare su Roll in °/s

        # ==============================================================================
        # BASE (Step 2): Rilevamento Anti-Jumping standard su velocità Roll e norma Giroscopio
        # ==============================================================================
        gyro_norm = 0.0
        if gyro is not None and len(gyro) >= 3:
            gyro_norm = math.sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)

        is_spike = (roll_speed >= self.roll_speed_threshold_deg) or (gyro_norm >= self.gyro_norm_threshold_rad)

        # ==============================================================================
        # --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): Isolamento dell'asse Roll ---
        # Per attivare l'ottimizzazione Step 6 (evita freeze accidentali su monitor Ultrawide durante sweep orizzontali),
        # decommenta il blocco sottostante e commenta il calcolo di is_spike sopra:
        # if self.freeze_on_roll_only:
        #     roll_gyro_rad = abs(gyro[0]) if (gyro is not None and len(gyro) >= 3) else 0.0
        #     roll_thresh_rad = self.roll_speed_threshold_deg * (math.pi / 180.0)
        #     is_spike = (roll_speed >= self.roll_speed_threshold_deg) or (roll_gyro_rad >= roll_thresh_rad)
        # ==============================================================================

        # 3. Transizioni della Macchina a Stati (Causale Real-Time)
        if self.state == self.STATE_MOTION_TRACKING:
            if is_spike:
                # Transizione immediata in GESTURE_FREEZE: blocco del cursore
                self.state = self.STATE_GESTURE_FREEZE
                self.stable_time_s = 0.0
        elif self.state == self.STATE_GESTURE_FREEZE:
            if is_spike:
                # Il movimento repentino è ancora in corso: reset tempo di stabilizzazione
                self.stable_time_s = 0.0
            else:
                # Il segnale è tornato sotto soglia: accumula tempo di stabilità
                self.stable_time_s += dt
                if self.stable_time_s >= self.freeze_hold_time_s:
                    # Stabilizzazione completata: rientro in MOTION_TRACKING
                    self.state = self.STATE_MOTION_TRACKING
                    self.stable_time_s = 0.0

        is_frozen = (self.state == self.STATE_GESTURE_FREEZE)
        return self.state, is_frozen, deltas
# --- END [09/10/2026] Step 2: Modulo Macchina a Stati e Rilevamento Gesture (Anti-Jumping) ---
