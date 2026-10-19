# --- START [11/10/2026] Step 5: Modulo di Calibrazione Sensori e Schermo Adattivo (C-D Gain) ---
"""
screen_calibrator.py: Calibrazione iniziale dei sensori e mappatura adattiva dello schermo.
Implementa i principi di Human-Computer Interaction (HCI) per il Control-Display Gain (C-D Gain):
1. Calibrazione Statica Sensori (Zero-Bias):
   - Stima e rimozione del bias statico del giroscopio MEMS a riposo per eliminare il drift/creep.
   - Definizione dell'assetto neutro (Boresight Zero) con braccio teso al centro dello schermo.
2. Calibrazione Adattiva Schermo (Gain Statico & Biomeccanico):
   - Rilevamento automatico della risoluzione del monitor (DPI-aware).
   - Scaling dei parametri di saturazione (lambda_x, lambda_y) e pendenza (rx, ry) della Sigmoide
     per consentire la copertura completa dello schermo entro l'escursione confortevole del braccio,
     prevenendo l'affaticamento ("Gorilla Arm Syndrome").
"""
import json
import math
import os
import sys

class ScreenCalibrator:
    """
    Gestisce la calibrazione statica del giroscopio e il calcolo dei parametri di C-D Gain
    adattati alla risoluzione reale dello schermo e ai vincoli biomeccanici dell'utente.
    """

    def __init__(
        self,
        ref_width: int = 1920,
        ref_height: int = 1080,
        base_lambda: float = 60.0,
        max_yaw_deg: float = 25.0,
        max_pitch_deg: float = 18.0,
        calibration_samples: int = 40  # 40 campioni a 20 Hz = 2.0 secondi di calibrazione a riposo
    ):
        self.ref_width = ref_width
        self.ref_height = ref_height
        self.base_lambda = base_lambda
        self.max_yaw_deg = max_yaw_deg
        self.max_pitch_deg = max_pitch_deg
        self.calibration_samples = calibration_samples

        # Rilevamento di tutti i monitor connessi
        self.monitors = self.detect_all_monitors()
        # Seleziona automaticamente il monitor su cui si trova il mouse dell'utente
        self.active_monitor_index = self.get_monitor_at_cursor(self.monitors)
        active_mon = self.monitors[self.active_monitor_index]

        self.screen_width = active_mon["width"]
        self.screen_height = active_mon["height"]
        self.origin_x = active_mon["left"]
        self.origin_y = active_mon["top"]
        self.center_x = active_mon["center_x"]
        self.center_y = active_mon["center_y"]

        # Parametri calcolati del C-D Gain
        self.cd_params = self.compute_sigmoid_params(
            self.screen_width, self.screen_height, self.max_yaw_deg, self.max_pitch_deg
        )

        # Stato della calibrazione statica dei sensori
        self.is_calibrated = False
        self.gyro_bias = [0.0, 0.0, 0.0]  # [bx, by, bz] in rad/s
        self.zero_euler = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}

        # Accumulatori temporanei per la calibrazione statica
        self._gyro_acc = [0.0, 0.0, 0.0]
        self._euler_acc = [0.0, 0.0, 0.0]
        self._samples_count = 0

    @staticmethod
    def detect_all_monitors() -> list:
        """
        Rileva tutti i monitor connessi con le rispettive coordinate virtuali e risoluzioni reali DPI-aware.
        Supporta configurazioni multi-monitor cross-platform (Windows, Linux, macOS).
        """
        # --- START [18/10/2026] Step 8: Rilevamento monitor multi-piattaforma ---
        # 1. Rilevamento DPI-Aware nativo su Windows
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception:
                    try:
                        ctypes.windll.user32.SetProcessDPIAware()
                    except Exception:
                        pass
                user32 = ctypes.windll.user32

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ('left', ctypes.c_long), ('top', ctypes.c_long),
                        ('right', ctypes.c_long), ('bottom', ctypes.c_long)
                    ]

                class MONITORINFO(ctypes.Structure):
                    _fields_ = [
                        ('cbSize', wintypes.DWORD),
                        ('rcMonitor', RECT),
                        ('rcWork', RECT),
                        ('dwFlags', wintypes.DWORD)
                    ]

                monitors = []
                def _enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    user32.GetMonitorInfoW(hMonitor, ctypes.byref(mi))
                    rc = mi.rcMonitor
                    is_primary = (mi.dwFlags & 1) != 0
                    w = rc.right - rc.left
                    h = rc.bottom - rc.top
                    monitors.append({
                        'index': len(monitors),
                        'handle': hMonitor,
                        'left': int(rc.left),
                        'top': int(rc.top),
                        'right': int(rc.right),
                        'bottom': int(rc.bottom),
                        'width': int(w),
                        'height': int(h),
                        'center_x': int(rc.left + w // 2),
                        'center_y': int(rc.top + h // 2),
                        'is_primary': is_primary
                    })
                    return 1

                MonitorEnumProc = ctypes.WINFUNCTYPE(
                    ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM
                )
                proc = MonitorEnumProc(_enum_proc)
                user32.EnumDisplayMonitors(None, None, proc, 0)
                if monitors:
                    return monitors
            except Exception:
                pass

        # 2. Rilevamento cross-platform tramite libreria screeninfo (Linux / macOS / fallback Windows)
        try:
            import screeninfo
            s_monitors = screeninfo.get_monitors()
            if s_monitors:
                monitors = []
                for idx, m in enumerate(s_monitors):
                    monitors.append({
                        'index': idx,
                        'handle': None,
                        'left': int(m.x),
                        'top': int(m.y),
                        'right': int(m.x + m.width),
                        'bottom': int(m.y + m.height),
                        'width': int(m.width),
                        'height': int(m.height),
                        'center_x': int(m.x + m.width // 2),
                        'center_y': int(m.y + m.height // 2),
                        'is_primary': getattr(m, 'is_primary', idx == 0)
                    })
                return monitors
        except Exception:
            pass

        # 3. Fallback grafico cross-platform (tkinter)
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            w = root.winfo_screenwidth()
            h = root.winfo_screenheight()
            root.destroy()
            if w > 0 and h > 0:
                return [{
                    'index': 0,
                    'handle': None,
                    'left': 0,
                    'top': 0,
                    'right': int(w),
                    'bottom': int(h),
                    'width': int(w),
                    'height': int(h),
                    'center_x': int(w // 2),
                    'center_y': int(h // 2),
                    'is_primary': True
                }]
        except Exception:
            pass
        # --- END [18/10/2026] Step 8: Rilevamento monitor multi-piattaforma ---

        return [{
            'index': 0,
            'handle': None,
            'left': 0,
            'top': 0,
            'right': 1920,
            'bottom': 1080,
            'width': 1920,
            'height': 1080,
            'center_x': 960,
            'center_y': 540,
            'is_primary': True
        }]

    @staticmethod
    def get_monitor_at_cursor(monitors: list) -> int:
        """
        Rileva l'indice del monitor su cui si trova attualmente il cursore del mouse.
        Supporta Windows nativo (Win32) e pynput (cross-platform).
        """
        if not monitors:
            return 0

        # --- START [18/10/2026] Step 8: Rilevamento posizione cursore per monitor attivo cross-platform ---
        # Metodo 1: Win32 nativo su Windows
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                pt = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                for m in monitors:
                    if m['left'] <= pt.x < m['right'] and m['top'] <= pt.y < m['bottom']:
                        return m['index']
            except Exception:
                pass

        # Metodo 2: Cross-platform via pynput
        try:
            from pynput.mouse import Controller
            cur_pos = Controller().position
            cur_x, cur_y = int(cur_pos[0]), int(cur_pos[1])
            for m in monitors:
                if m['left'] <= cur_x < m['right'] and m['top'] <= cur_y < m['bottom']:
                    return m['index']
        except Exception:
            pass
        # --- END [18/10/2026] Step 8: Rilevamento posizione cursore per monitor attivo cross-platform ---
        return 0

    def sync_active_monitor_from_cursor(self) -> bool:
        """
        Verifica se il mouse si trova su un monitor diverso da quello attualmente attivo.
        Se sì, aggiorna automaticamente il monitor attivo e ricalcola i parametri C-D Gain.
        :return: True se il monitor è cambiato, False altrimenti.
        """
        current_idx = self.get_monitor_at_cursor(self.monitors)
        if current_idx != self.active_monitor_index:
            self.switch_monitor(current_idx)
            return True
        return False

    def switch_monitor(self, target_index: int = None) -> dict:
        """
        Passa a un altro monitor (a rotazione ciclica o all'indice target specificato)
        e ricalcola i parametri di C-D Gain per la nuova risoluzione.
        """
        if not self.monitors:
            return self.get_active_monitor_info()

        if target_index is not None:
            self.active_monitor_index = target_index % len(self.monitors)
        else:
            self.active_monitor_index = (self.active_monitor_index + 1) % len(self.monitors)

        active_mon = self.monitors[self.active_monitor_index]
        self.screen_width = active_mon["width"]
        self.screen_height = active_mon["height"]
        self.origin_x = active_mon["left"]
        self.origin_y = active_mon["top"]
        self.center_x = active_mon["center_x"]
        self.center_y = active_mon["center_y"]

        self.cd_params = self.compute_sigmoid_params(
            self.screen_width, self.screen_height, self.max_yaw_deg, self.max_pitch_deg
        )
        return self.get_active_monitor_info()

    def get_active_monitor_info(self) -> dict:
        """Restituisce le informazioni del monitor attualmente attivo."""
        return self.monitors[self.active_monitor_index]

    @staticmethod
    def detect_screen_resolution() -> tuple:
        """Rileva la risoluzione nativa in pixel dello schermo primario su Windows con DPI Awareness."""
        mons = ScreenCalibrator.detect_all_monitors()
        primary = next((m for m in mons if m['is_primary']), mons[0])
        return primary['width'], primary['height']

    def compute_sigmoid_params(
        self,
        width: int,
        height: int,
        max_yaw: float = None,
        max_pitch: float = None
    ) -> dict:
        """
        Calcola i parametri ottimali della Sigmoide Modificata (C-D Gain) basati
        sulla risoluzione reale dello schermo e sull'escursione angolare confortevole del gomito/braccio.
        Include sia i parametri per la Modalità Assoluta (Boresight) che per la Modalità Relativa (Delta).
        """
        yaw_limit = max_yaw if max_yaw is not None else self.max_yaw_deg
        pitch_limit = max_pitch if max_pitch is not None else self.max_pitch_deg

        # 1. Pendenza cinematica della sigmoide (rx, ry):
        # ln(19) ~= 2.9444 garantisce che all'angolo limite max_yaw/max_pitch si raggiunga il 95% della saturazione
        rx = round(2.9444 / max(yaw_limit, 5.0), 4)
        ry = round(2.9444 / max(pitch_limit, 5.0), 4)

        # 2. Modalità Assoluta (Boresight): saturazione all'intera dimensione dello schermo
        lambda_x = float(width)
        lambda_y = float(height)

        def _sig_val(angle, r, lam):
            return (lam / (1.0 + math.exp(-r * angle))) - (lam / 2.0)

        # Fattore correttivo per raggiungere esattamente il margine (100% della semi-larghezza/altezza) a max_yaw / max_pitch
        factor_x = round((width / 2.0) / _sig_val(yaw_limit, rx, width), 4)
        factor_y = round((height / 2.0) / _sig_val(pitch_limit, ry, height), 4)

        # 3. Modalità Relativa (Delta): scaling proporzionale delle velocità per campionamento a 20 Hz
        scale_x = width / float(self.ref_width)
        scale_y = height / float(self.ref_height)
        delta_lambda_x = round(self.base_lambda * scale_x, 2)
        delta_lambda_y = round(self.base_lambda * scale_y, 2)

        return {
            "screen_width": width,
            "screen_height": height,
            "max_yaw_deg": yaw_limit,
            "max_pitch_deg": pitch_limit,
            "lambda_x": lambda_x,
            "lambda_y": lambda_y,
            "rx": rx,
            "ry": ry,
            "factor_x": factor_x,
            "factor_y": factor_y,
            "deadzone_deg": 0.15,
            "scale_x": round(scale_x, 3),
            "scale_y": round(scale_y, 3),
            "delta_lambda_x": delta_lambda_x,
            "delta_lambda_y": delta_lambda_y
        }

    def start_static_calibration(self):
        """Reimposta gli accumulatori per iniziare una nuova sessione di calibrazione statica."""
        self._gyro_acc = [0.0, 0.0, 0.0]
        self._euler_acc = [0.0, 0.0, 0.0]
        self._samples_count = 0
        self.is_calibrated = False

    def add_calibration_sample(self, gyro_xyz: list, euler_dict: dict) -> bool:
        """
        Aggiunge un campione alla calibrazione statica.
        :param gyro_xyz: [gx, gy, gz] in rad/s
        :param euler_dict: {"pitch": p, "yaw": y, "roll": r} in gradi
        :return: True se la calibrazione ha raggiunto il numero di campioni richiesto ed è completata.
        """
        for i in range(3):
            self._gyro_acc[i] += gyro_xyz[i]
        self._euler_acc[0] += euler_dict.get("yaw", 0.0)
        self._euler_acc[1] += euler_dict.get("pitch", 0.0)
        self._euler_acc[2] += euler_dict.get("roll", 0.0)
        self._samples_count += 1

        if self._samples_count >= self.calibration_samples:
            n = float(self._samples_count)
            self.gyro_bias = [self._gyro_acc[i] / n for i in range(3)]
            self.zero_euler = {
                "yaw": self._euler_acc[0] / n,
                "pitch": self._euler_acc[1] / n,
                "roll": self._euler_acc[2] / n
            }
            self.is_calibrated = True
            return True
        return False

    @property
    def progress_percentage(self) -> float:
        """Percentuale di avanzamento della calibrazione statica (0.0 - 100.0)."""
        if self.calibration_samples <= 0:
            return 100.0
        return min(100.0, (self._samples_count / float(self.calibration_samples)) * 100.0)

    def apply_bias_correction(self, raw_gyro: list) -> list:
        """Sottrae il bias statico calibrato alle velocità angolari del giroscopio."""
        if not self.is_calibrated:
            return raw_gyro
        return [
            raw_gyro[0] - self.gyro_bias[0],
            raw_gyro[1] - self.gyro_bias[1],
            raw_gyro[2] - self.gyro_bias[2]
        ]

    def recenter_pose(self, current_euler: dict):
        """Aggiorna istantaneamente la posa neutra di riferimento (Quick Re-Center)."""
        self.zero_euler = dict(current_euler)

    def save_profile(self, filepath: str = "calibration_profile.json") -> bool:
        """Salva il profilo di calibrazione su file JSON."""
        data = {
            "screen": {
                "width": self.screen_width,
                "height": self.screen_height
            },
            "cd_params": self.cd_params,
            "gyro_bias": self.gyro_bias,
            "zero_euler": self.zero_euler,
            "is_calibrated": self.is_calibrated
        }
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            return True
        except Exception:
            return False

    def load_profile(self, filepath: str = "calibration_profile.json") -> bool:
        """Carica un profilo di calibrazione precedentemente salvato."""
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.screen_width = data["screen"]["width"]
            self.screen_height = data["screen"]["height"]
            self.cd_params = data["cd_params"]
            self.gyro_bias = data.get("gyro_bias", [0.0, 0.0, 0.0])
            self.zero_euler = data.get("zero_euler", {"yaw": 0.0, "pitch": 0.0, "roll": 0.0})
            self.is_calibrated = data.get("is_calibrated", False)
            return True
        except Exception:
            return False
# --- END [11/10/2026] Step 5: Modulo di Calibrazione Sensori e Schermo Adattivo (C-D Gain) ---
