# --- START [18/10/2026] Step 11: Modulo Stabilizzatore Bolla Spaziale Soft-Edge ---
"""
stabilizer.py: Stabilizzatore spaziale Soft-Edge per Motion Tracking con transizione Hermite Smoothstep.
Elimina completamente il micro-tremolio neuromuscolare e il rumore dei sensori MEMS a mano ferma
senza introdurre alcuno scalino brusco al momento di iniziare un movimento intenzionale.
"""

import math
import time


class SpatialBubbleStabilizer:
    """
    Stabilizzatore spaziale Soft-Edge con transizione Hermite Smoothstep continua C^1.
    - Sotto r_inner (es. 2.5 px): soppressione 100% (zero tremolio fisiologico a riposo).
    - Tra r_inner e r_outer (es. 2.5-7.0 px): transizione continua graduale (w = 3t^2 - 2t^3).
    - Oltre r_outer (es. > 7.0 px): movimento libero e reattivo al 100%.
    - Se is_frozen == True: congelamento istantaneo dell'ancoraggio (Anti-Jumping durante gesture/click).
    """

    def __init__(self, r_inner_px: float = 2.5, r_outer_px: float = 7.0, still_time_s: float = 0.15, enabled: bool = True):
        self.enabled = bool(enabled)
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
        """Disattiva i cerchi concentrici e rimuove l'ancora (es. durante la pausa)."""
        self.is_anchored = False

    def update(self, raw_target_x: float, raw_target_y: float, is_frozen: bool = False) -> tuple[float, float, str]:
        """
        Processa la coordinata target calcolata dalla cinematica applicando la bolla a doppio raggio.
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

        # 2. Zona di quiete assoluta (Zero Tremolio a riposo)
        if dist <= self.r_inner_px:
            self.is_anchored = True
            return self.anchor_x, self.anchor_y, "ANCHOR_STILL"

        # 3. Zona di transizione morbida continua (Smoothstep Hermite)
        elif dist < self.r_outer_px:
            w = self._smoothstep(self.r_inner_px, self.r_outer_px, dist)
            out_x = self.anchor_x + w * (raw_x - self.anchor_x)
            out_y = self.anchor_y + w * (raw_y - self.anchor_y)
            # Trascina dolcemente l'ancora nella direzione del movimento
            self.anchor_x += (out_x - self.anchor_x) * 0.20
            self.anchor_y += (out_y - self.anchor_y) * 0.20
            self.is_anchored = False
            return out_x, out_y, "SOFT_TRANS"

        # 4. Movimento libero (l'ancora segue fedelmente il cursore a piena velocità)
        else:
            self.is_anchored = False
            self.anchor_x = raw_x
            self.anchor_y = raw_y
            self.last_move_time = now
            return raw_x, raw_y, "MOVING"
# --- END [18/10/2026] Step 11: Modulo Stabilizzatore Bolla Spaziale Soft-Edge ---
