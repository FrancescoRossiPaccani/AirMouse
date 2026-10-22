# --- START [18/10/2026] Step 11: Modulo Motore Interpolatore Cursore 120 Hz (SmoothCursorEngine) ---
"""
cursor_engine.py: Motore asincrono a 120 Hz per il movimento ultra-fluido del cursore del mouse.
Utilizza un modello di molla a smorzamento critico di secondo ordine (SmoothDamp) per calcolare
traiettorie continue e lisce in posizione e velocità (C^1), eliminando i microscatti a 20 Hz.
"""

import threading
import time
from motionTrackingModule.mouse_controller import MouseController


class SmoothCursorEngine:
    """
    Motore asincrono ad alta frequenza (120 Hz) basato su Second-Order Critically
    Damped Spring (SmoothDamp) per il movimento continuo e ultra-fluido del cursore del mouse.
    """

    def __init__(self, controller: MouseController, update_hz: float = 120.0, smooth_time_s: float = 0.026, enabled: bool = True):
        self.controller = controller
        self.update_interval = 1.0 / max(30.0, float(update_hz))
        self.smooth_time_s = float(smooth_time_s)
        self.enabled = bool(enabled)

        self.is_paused = False

        self.target_x = 0.0
        self.target_y = 0.0
        self.current_x = 0.0
        self.current_y = 0.0
        self.vel_x = 0.0
        self.vel_y = 0.0

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
        """Mette in pausa l'interpolatore disattivando il controllo del cursore per lasciare libero il mouse."""
        with self._lock:
            self.is_paused = True

    def resume(self):
        """Riprende l'interpolatore dopo una pausa."""
        with self._lock:
            self.is_paused = False
            self.vel_x = 0.0
            self.vel_y = 0.0
            self._last_tick = time.perf_counter()

    def set_target(self, x: float, y: float):
        """Aggiorna le coordinate bersaglio ricevute dal thread di ricezione BLE."""
        with self._lock:
            self.target_x = float(x)
            self.target_y = float(y)

    def snap_to(self, x: float, y: float):
        """Riallinea istantaneamente la posizione del cursore e azzera la velocità residua."""
        with self._lock:
            self.current_x = float(x)
            self.current_y = float(y)
            self.target_x = float(x)
            self.target_y = float(y)
            self.vel_x = 0.0
            self.vel_y = 0.0
            self._last_tick = time.perf_counter()
            paused = self.is_paused
        if not paused and self.controller:
            self.controller.set_position(int(round(x)), int(round(y)))

    def _loop(self):
        """Loop di interpolazione ultra-fluida continuo a 120 Hz."""
        while self._running:
            now = time.perf_counter()
            dt = now - self._last_tick
            self._last_tick = now

            if dt <= 0.0:
                dt = self.update_interval
            elif dt > 0.10:
                dt = 0.10

            with self._lock:
                paused = self.is_paused
                target_x = self.target_x
                target_y = self.target_y
                cur_x = self.current_x
                cur_y = self.current_y
                vel_x = self.vel_x
                vel_y = self.vel_y

            if paused:
                time.sleep(0.01)
                continue

            if self.enabled:
                new_x, new_vel_x = self._smooth_damp_1d(cur_x, target_x, vel_x, self.smooth_time_s, dt)
                new_y, new_vel_y = self._smooth_damp_1d(cur_y, target_y, vel_y, self.smooth_time_s, dt)
            else:
                new_x, new_y = target_x, target_y
                new_vel_x, new_vel_y = 0.0, 0.0

            with self._lock:
                self.current_x = new_x
                self.current_y = new_y
                self.vel_x = new_vel_x
                self.vel_y = new_vel_y

            if self.controller:
                px = int(round(new_x))
                py = int(round(new_y))
                self.controller.set_position(px, py)

            elapsed = time.perf_counter() - now
            sleep_time = self.update_interval - elapsed
            if sleep_time > 0.001:
                time.sleep(sleep_time)
# --- END [18/10/2026] Step 11: Modulo Motore Interpolatore Cursore 120 Hz (SmoothCursorEngine) ---
