# --- START [09/10/2026] Step 3: Modulo Mappatura Cinematica Sigmoide Modificata (MouseMapper) ---
"""
mouse_mapper.py: Trasformazione cinematica dei delta angolari (Yaw, Pitch) in spostamenti pixel del mouse.
Implementa la Funzione Sigmoide Modificata con Dead-Zone (Magic-Hand) e un accumulatore frazionario
per garantire movimenti lenti ultra-fluidi (sub-pixel precision).
"""
import math

# ==============================================================================
# --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): Modulo Filtro 1€ (One Euro Filter) ---
# Per studiare la versione base, il filtro sottostante è commentato.
# Per attivare l'ottimizzazione Step 6, decommenta la classe sottostante:
# class OneEuroFilter:
#     """
#     Filtro 1€ (Casiez, Roussel, Vogel - ACM CHI 2012).
#     Filtro passa-basso adattivo standard di riferimento nell'HCI (Human-Computer Interaction):
#     - A basse velocità: cutoff dinamico scende (0.8 Hz) eliminando il tremolio.
#     - Ad alte velocità: cutoff aumenta proporzionalmente alla velocità (zero lag).
#     """
#     def __init__(self, min_cutoff: float = 0.8, beta: float = 0.015, d_cutoff: float = 1.0):
#         self.min_cutoff = float(min_cutoff)
#         self.beta = float(beta)
#         self.d_cutoff = float(d_cutoff)
#         self.x_prev = None
#         self.dx_prev = 0.0
#
#     def _alpha(self, cutoff: float, dt: float) -> float:
#         tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-4))
#         return 1.0 / (1.0 + tau / max(dt, 1e-5))
#
#     def filter(self, x: float, dt: float = 0.05) -> float:
#         if self.x_prev is None:
#             self.x_prev = float(x)
#             self.dx_prev = 0.0
#             return float(x)
#         dx = (float(x) - self.x_prev) / max(dt, 1e-5)
#         alpha_d = self._alpha(self.d_cutoff, dt)
#         dx_hat = alpha_d * dx + (1.0 - alpha_d) * self.dx_prev
#         self.dx_prev = dx_hat
#         cutoff = self.min_cutoff + self.beta * abs(dx_hat)
#         alpha = self._alpha(cutoff, dt)
#         x_hat = alpha * float(x) + (1.0 - alpha) * self.x_prev
#         self.x_prev = x_hat
#         return x_hat
#
#     def reset(self, x: float = None):
#         self.x_prev = float(x) if x is not None else None
#         self.dx_prev = 0.0
# ==============================================================================

class MouseMapper:
    """
    Mappa i delta angolari (Pitch, Yaw) negli incrementi in pixel (dx, dy) del cursore del mouse.
    Formula (Sigmoide Modificata con segno bidirezionale):
        dx = (lambda_x / (1 + exp(-rx * (dYaw - offset_yaw)))) - (lambda_x / 2)  se |dYaw| >= deadzone
        dy = (lambda_y / (1 + exp(-ry * (dPitch - offset_pitch)))) - (lambda_y / 2) se |dPitch| >= deadzone
    """

    def __init__(
        self,
        screen_width: int = 1920,
        screen_height: int = 1080,
        origin_x: int = 0,            # Coordinata X angolo in alto a sinistra del monitor (per multi-monitor)
        origin_y: int = 0,            # Coordinata Y angolo in alto a sinistra del monitor (per multi-monitor)
        max_yaw_deg: float = 25.0,
        max_pitch_deg: float = 18.0,
        rx: float = None,             # Pendenza / sensibilità asse orizzontale (Yaw)
        ry: float = None,             # Pendenza / sensibilità asse verticale (Pitch)
        lambda_x: float = None,       # Ampiezza massima asse X (pixel)
        lambda_y: float = None,       # Ampiezza massima asse Y (pixel)
        factor_x: float = None,       # Fattore correttivo per raggiungere esattamente i bordi a max_yaw
        factor_y: float = None,       # Fattore correttivo per raggiungere esattamente i bordi a max_pitch
        deadzone_deg: float = 0.15,   # Soglia dead-zone (in gradi) per eliminare il tremolio a riposo
        offset_yaw: float = 0.0,      # Trim offset Yaw
        offset_pitch: float = 0.0,    # Trim offset Pitch
        invert_x: bool = True,        # Inversione asse X (True: movimento verso destra muove il mouse a destra)
        invert_y: bool = True,        # Inversione asse Y (True: Pitch up muove il mouse verso l'alto)
        scale_factor: float = 1.0,    # Fattore di moltiplicazione globale della sensibilità
        smooth_min_alpha: float = 0.30,  # Alpha EMA a riposo (massima stabilità, zero tremolio)
        smooth_max_alpha: float = 0.85,  # Alpha EMA in movimento rapido (massima reattività, zero lag)
        # --- START [11/10/2026] Step 6: Configurazione 1€ Filter (Default False per versione base) ---
        use_one_euro: bool = False,
        one_euro_min_cutoff: float = 0.8,
        one_euro_beta: float = 0.015
        # --- END [11/10/2026] Step 6: Configurazione 1€ Filter (Default False per versione base) ---
    ):
        self.screen_width = int(screen_width)
        self.screen_height = int(screen_height)
        self.origin_x = int(origin_x)
        self.origin_y = int(origin_y)
        self.max_yaw_deg = float(max_yaw_deg)
        self.max_pitch_deg = float(max_pitch_deg)

        # Se non specificati, calcola i valori ottimali di default
        self.rx = float(rx) if rx is not None else round(2.9444 / max(self.max_yaw_deg, 5.0), 4)
        self.ry = float(ry) if ry is not None else round(2.9444 / max(self.max_pitch_deg, 5.0), 4)
        self.lambda_x = float(lambda_x) if lambda_x is not None else float(self.screen_width)
        self.lambda_y = float(lambda_y) if lambda_y is not None else float(self.screen_height)

        # Calcolo fattori di scala al bordo
        if factor_x is not None:
            self.factor_x = float(factor_x)
        else:
            sig_max_x = self._sigmoid_calc(self.max_yaw_deg, self.rx, self.lambda_x, 0.0)
            self.factor_x = round((self.screen_width / 2.0) / sig_max_x, 4) if sig_max_x > 0 else 1.0

        if factor_y is not None:
            self.factor_y = float(factor_y)
        else:
            sig_max_y = self._sigmoid_calc(self.max_pitch_deg, self.ry, self.lambda_y, 0.0)
            self.factor_y = round((self.screen_height / 2.0) / sig_max_y, 4) if sig_max_y > 0 else 1.0

        self.deadzone_deg = deadzone_deg
        self.offset_yaw = offset_yaw
        self.offset_pitch = offset_pitch
        self.invert_x = invert_x
        self.invert_y = invert_y
        self.scale_factor = scale_factor
        self.smooth_min_alpha = smooth_min_alpha
        self.smooth_max_alpha = smooth_max_alpha

        # ==============================================================================
        # --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): Inizializzazione 1€ Filter ---
        # Per attivare l'ottimizzazione Step 6, decommenta le 5 righe sottostanti:
        # self.use_one_euro = use_one_euro
        # self.one_euro_min_cutoff = one_euro_min_cutoff
        # self.one_euro_beta = one_euro_beta
        # self.one_euro_x = OneEuroFilter(min_cutoff=self.one_euro_min_cutoff, beta=self.one_euro_beta)
        # self.one_euro_y = OneEuroFilter(min_cutoff=self.one_euro_min_cutoff, beta=self.one_euro_beta)
        self.use_one_euro = False
        # ==============================================================================

        # Stato per Mappatura Assoluta e Smoothing EMA (centrato sul monitor specificato)
        self.curr_x = float(self.origin_x + self.screen_width / 2.0)
        self.curr_y = float(self.origin_y + self.screen_height / 2.0)
        self.prev_d_yaw = 0.0
        self.prev_d_pitch = 0.0
        self._has_init_pos = False

        # Accumulatori frazionari per modalità relativa (delta)
        self.frac_x = 0.0
        self.frac_y = 0.0

    # --- START [11/10/2026] Step 5: Aggiornamento dinamico parametri C-D Gain e Schermo ---
    def update_params(
        self,
        screen_width: int = None,
        screen_height: int = None,
        origin_x: int = None,
        origin_y: int = None,
        max_yaw_deg: float = None,
        max_pitch_deg: float = None,
        rx: float = None,
        ry: float = None,
        lambda_x: float = None,
        lambda_y: float = None,
        factor_x: float = None,
        factor_y: float = None,
        offset_yaw: float = None,
        offset_pitch: float = None,
        scale_factor: float = None,
        # --- START [11/10/2026] Step 6: Parametri aggiornamento a caldo 1€ Filter ---
        use_one_euro: bool = None,
        one_euro_min_cutoff: float = None,
        one_euro_beta: float = None
        # --- END [11/10/2026] Step 6: Parametri aggiornamento a caldo 1€ Filter ---
    ):
        """Aggiorna a caldo i parametri di sensibilità cinematica, C-D Gain e coordinate schermo."""
        if screen_width is not None:
            self.screen_width = int(screen_width)
        if screen_height is not None:
            self.screen_height = int(screen_height)
        if origin_x is not None:
            self.origin_x = int(origin_x)
        if origin_y is not None:
            self.origin_y = int(origin_y)
        if max_yaw_deg is not None:
            self.max_yaw_deg = float(max_yaw_deg)
        if max_pitch_deg is not None:
            self.max_pitch_deg = float(max_pitch_deg)
        if rx is not None:
            self.rx = float(rx)
        if ry is not None:
            self.ry = float(ry)
        if lambda_x is not None:
            self.lambda_x = float(lambda_x)
        if lambda_y is not None:
            self.lambda_y = float(lambda_y)
        if factor_x is not None:
            self.factor_x = float(factor_x)
        if factor_y is not None:
            self.factor_y = float(factor_y)
        if offset_yaw is not None:
            self.offset_yaw = float(offset_yaw)
        if offset_pitch is not None:
            self.offset_pitch = float(offset_pitch)
        if scale_factor is not None:
            self.scale_factor = float(scale_factor)
        if use_one_euro is not None:
            self.use_one_euro = bool(use_one_euro)
        if one_euro_min_cutoff is not None:
            self.one_euro_min_cutoff = float(one_euro_min_cutoff)
            self.one_euro_x.min_cutoff = self.one_euro_min_cutoff
            self.one_euro_y.min_cutoff = self.one_euro_min_cutoff
        if one_euro_beta is not None:
            self.one_euro_beta = float(one_euro_beta)
            self.one_euro_x.beta = self.one_euro_beta
            self.one_euro_y.beta = self.one_euro_beta
    # --- END [11/10/2026] Step 5: Aggiornamento dinamico parametri C-D Gain e Schermo ---

    def recenter(self, x: float = None, y: float = None):
        """Ripristina istantaneamente la posizione del cursore al centro dello schermo attivo."""
        self.curr_x = float(x) if x is not None else float(self.origin_x + self.screen_width / 2.0)
        self.curr_y = float(y) if y is not None else float(self.origin_y + self.screen_height / 2.0)
        self.prev_d_yaw = 0.0
        self.prev_d_pitch = 0.0
        self.frac_x = 0.0
        self.frac_y = 0.0
        self._has_init_pos = True
        # ==============================================================================
        # --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): Reset filtri 1€ Filter ---
        # Per attivare l'ottimizzazione Step 6, decommenta le 3 righe sottostanti:
        # if hasattr(self, 'one_euro_x'):
        #     self.one_euro_x.reset(self.curr_x)
        #     self.one_euro_y.reset(self.curr_y)
        # ==============================================================================

    def _sigmoid_calc(self, delta_angle: float, r: float, lambda_param: float, offset: float) -> float:
        """Calcola il valore della sigmoide modificata centrata in zero."""
        val = delta_angle - offset
        try:
            # Protezione da overflow esponenziale per grandi variazioni
            exp_term = math.exp(-r * val)
        except OverflowError:
            exp_term = 0.0 if val > 0 else float("inf")

        if exp_term == float("inf"):
            return -lambda_param / 2.0
        
        return (lambda_param / (1.0 + exp_term)) - (lambda_param / 2.0)

    # --- START [11/10/2026] Step 5: Mappatura Assoluta Boresight ---
    def map_absolute(
        self,
        yaw: float,
        pitch: float,
        zero_yaw: float,
        zero_pitch: float,
        is_frozen: bool = False,
        dt: float = 0.05
    ) -> tuple:
        """
        Mappatura Assoluta Boresight: trasforma l'orientamento angolare relativo alla posa neutra
        calibrata in coordinate pixel assolute (X, Y) sullo schermo [0, W-1] x [0, H-1].
        
        - All'angolo neutro (zero_yaw, zero_pitch) -> cursore esattamente al centro (W/2, H/2).
        - Al massimo angolo confortevole del gomito (max_yaw_deg, max_pitch_deg) -> bordi dello schermo.
        - Filtro 1€ Filter: elimina il tremolio fisiologico a riposo senza introdurre lag nei movimenti rapidi.
        - Se is_frozen == True: il cursore viene bloccato istantaneamente nella posizione corrente (Anti-Jumping).
        """
        if is_frozen:
            return int(round(self.curr_x)), int(round(self.curr_y))

        # 1. Delta rispetto alla posa neutra con normalizzazione unwrapping [-180°, +180°]
        d_yaw = (yaw - zero_yaw) % 360.0
        if d_yaw > 180.0:
            d_yaw -= 360.0
        elif d_yaw < -180.0:
            d_yaw += 360.0

        d_pitch = (pitch - zero_pitch) % 360.0
        if d_pitch > 180.0:
            d_pitch -= 360.0
        elif d_pitch < -180.0:
            d_pitch += 360.0

        # Trim offset
        d_yaw -= self.offset_yaw
        d_pitch -= self.offset_pitch

        # ==============================================================================
        # BASE (Step 3/Step 5): Dead-zone micro per eliminare il tremolio a riposo
        # ==============================================================================
        if not self.use_one_euro:
            if abs(d_yaw) < self.deadzone_deg:
                d_yaw = 0.0
            if abs(d_pitch) < self.deadzone_deg:
                d_pitch = 0.0

        # 3. Calcolo Sigmoide Modificata scalata (C-D Gain)
        sig_x = self._sigmoid_calc(d_yaw, self.rx, self.lambda_x, 0.0) * self.factor_x * self.scale_factor
        sig_y = self._sigmoid_calc(d_pitch, self.ry, self.lambda_y, 0.0) * self.factor_y * self.scale_factor

        # 4. Applicazione orientamento assi (Tait-Bryan Z-Y-X):
        # Rotazione braccio a destra: Yaw decresce (d_yaw < 0) -> X sullo schermo deve aumentare (verso destra)
        center_x = self.origin_x + (self.screen_width / 2.0)
        center_y = self.origin_y + (self.screen_height / 2.0)

        if self.invert_x:
            target_x = center_x - sig_x
        else:
            target_x = center_x + sig_x

        # Inclinazione braccio in alto: Pitch aumenta (d_pitch > 0) -> Y sullo schermo deve diminuire (verso l'alto)
        if self.invert_y:
            target_y = center_y - sig_y
        else:
            target_y = center_y + sig_y

        # ==============================================================================
        # BASE (Step 5): Filtraggio Adattivo EMA Standard (Attivo)
        # ==============================================================================
        delta_mov = math.hypot(d_yaw - self.prev_d_yaw, d_pitch - self.prev_d_pitch)
        speed_deg_s = delta_mov / max(dt, 0.001)
        self.prev_d_yaw = d_yaw
        self.prev_d_pitch = d_pitch

        norm_v = min(1.0, speed_deg_s / 20.0)
        alpha = self.smooth_min_alpha + (self.smooth_max_alpha - self.smooth_min_alpha) * (norm_v ** 2)

        if not self._has_init_pos:
            self.curr_x = target_x
            self.curr_y = target_y
            self._has_init_pos = True
        else:
            self.curr_x = alpha * target_x + (1.0 - alpha) * self.curr_x
            self.curr_y = alpha * target_y + (1.0 - alpha) * self.curr_y

        # ==============================================================================
        # --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): Filtro 1€ (One Euro Filter ACM CHI 2012) ---
        # Per attivare l'ottimizzazione Step 6, decommenta il blocco sottostante e commenta il blocco EMA sopra:
        # if not self._has_init_pos:
        #     self.curr_x = target_x
        #     self.curr_y = target_y
        #     self.one_euro_x.reset(target_x)
        #     self.one_euro_y.reset(target_y)
        #     self._has_init_pos = True
        # else:
        #     self.curr_x = self.one_euro_x.filter(target_x, dt)
        #     self.curr_y = self.one_euro_y.filter(target_y, dt)
        # ==============================================================================

        # 6. Clamping ai confini fisici dello schermo attivo
        min_x = self.origin_x
        max_x = self.origin_x + self.screen_width - 1
        min_y = self.origin_y
        max_y = self.origin_y + self.screen_height - 1

        clamped_x = max(min_x, min(max_x, int(round(self.curr_x))))
        clamped_y = max(min_y, min(max_y, int(round(self.curr_y))))

        return clamped_x, clamped_y
    # --- END [11/10/2026] Step 5: Mappatura Assoluta Boresight ---

    def map_delta(self, d_yaw: float, d_pitch: float, is_frozen: bool = False):
        """
        Calcola gli spostamenti pixel float relativi (dx, dy).
        Se is_frozen == True (stato GESTURE_FREEZE), restituisce (0.0, 0.0).
        """
        # Se siamo in freeze (scatto del polso / click gesture), blocca qualsiasi movimento
        if is_frozen:
            self.frac_x = 0.0
            self.frac_y = 0.0
            return 0.0, 0.0

        # Mappatura asse X (Yaw)
        if abs(d_yaw) >= self.deadzone_deg:
            dx = self._sigmoid_calc(d_yaw, self.rx, self.lambda_x, self.offset_yaw)
        else:
            dx = 0.0

        # Mappatura asse Y (Pitch)
        if abs(d_pitch) >= self.deadzone_deg:
            dy = self._sigmoid_calc(d_pitch, self.ry, self.lambda_y, self.offset_pitch)
        else:
            dy = 0.0

        # Applicazione scala e inversioni
        if self.invert_x:
            dx = -dx
        if self.invert_y:
            dy = -dy

        dx *= self.scale_factor
        dy *= self.scale_factor

        return dx, dy

    def get_pixel_steps(self, dx_float: float, dy_float: float):
        """
        Converte gli spostamenti continui in passi discreti interi (pixel),
        accumulando i resti frazionari per garantire la continuità dei micro-movimenti.
        """
        self.frac_x += dx_float
        self.frac_y += dy_float

        step_x = int(self.frac_x)
        step_y = int(self.frac_y)

        self.frac_x -= step_x
        self.frac_y -= step_y

        return step_x, step_y
# --- END [09/10/2026] Step 3: Modulo Mappatura Cinematica Sigmoide Modificata (MouseMapper) ---
