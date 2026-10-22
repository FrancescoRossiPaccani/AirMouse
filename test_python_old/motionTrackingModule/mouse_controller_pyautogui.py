"""
mouse_controller_pyautogui.py
MouseController per AirMouse (Windows / macOS / Linux X11).

- Windows : percorso veloce via ctypes (SetCursorPos / mouse_event), ~10x piu' leggero
            di pyautogui, adatto al thread cursore a 120 Hz. Supporta multi-monitor
            (desktop virtuale con coordinate negative).
- macOS/Linux : fallback su pyautogui.

Thread-safe: il thread SmoothCursorEngine (120 Hz) muove il cursore mentre il
thread BLE esegue click/scroll/drag, quindi ogni operazione e' protetta da un lock.

Installazione:
    pip install pyautogui          # necessario solo su macOS / Linux
    # Linux (Xorg): sudo apt install python3-xlib python3-tk python3-dev scrot
"""

import sys
import threading

_WIN = sys.platform == "win32"

if _WIN:
    import ctypes
    from ctypes import wintypes

    try:
        ctypes.windll.user32.SetProcessDPIAware()   # pixel reali con scaling DPI > 100%
    except Exception:
        pass

    _user32 = ctypes.windll.user32
    _user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_size_t]

    _EVT = {
        "left": (0x0002, 0x0004),     # LEFTDOWN, LEFTUP
        "right": (0x0008, 0x0010),    # RIGHTDOWN, RIGHTUP
        "middle": (0x0020, 0x0040),   # MIDDLEDOWN, MIDDLEUP
    }
    _WHEEL = 0x0800
    _WHEEL_DELTA = 120

    def _virtual_bounds():
        """Rettangolo del desktop virtuale (tutti i monitor)."""
        x = _user32.GetSystemMetrics(76)
        y = _user32.GetSystemMetrics(77)
        w = _user32.GetSystemMetrics(78)
        h = _user32.GetSystemMetrics(79)
        return x, y, x + w - 1, y + h - 1
else:
    import pyautogui

    # CRITICO per il tracking a 120 Hz: default PAUSE = 0.1 s dopo ogni chiamata
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = False
    pyautogui.MINIMUM_DURATION = 0


class MouseController:
    def __init__(self):
        self._lock = threading.RLock()
        self._last = None                      # ultima posizione inviata (evita chiamate inutili)
        self._down = set()                     # pulsanti attualmente premuti da noi
        self.backend_name = f"{'win32 ctypes' if _WIN else 'pyautogui'} ({sys.platform})"

        if _WIN:
            self._x0, self._y0, self._x1, self._y1 = _virtual_bounds()
        else:
            w, h = pyautogui.size()
            self._x0, self._y0, self._x1, self._y1 = 0, 0, w - 1, h - 1

    # ---- Limiti schermo ----
    def set_screen_size(self, w, h, origin_x=0, origin_y=0):
        """Restringe il movimento a un singolo monitor (opzionale, retrocompatibile)."""
        self._x0, self._y0 = int(origin_x), int(origin_y)
        self._x1, self._y1 = self._x0 + int(w) - 1, self._y0 + int(h) - 1

    # ---- Posizione ----
    def move_to(self, x, y):
        x = max(self._x0, min(self._x1, int(round(x))))
        y = max(self._y0, min(self._y1, int(round(y))))
        if self._last == (x, y):
            return
        with self._lock:
            if _WIN:
                _user32.SetCursorPos(x, y)
            else:
                pyautogui.moveTo(x, y, duration=0, _pause=False)
            self._last = (x, y)

    move = set_position = move_absolute = move_to

    def get_position(self):
        with self._lock:
            if _WIN:
                p = wintypes.POINT()
                _user32.GetCursorPos(ctypes.byref(p))
                return int(p.x), int(p.y)
            p = pyautogui.position()
            return int(p.x), int(p.y)

    def center_cursor(self, x, y):
        self._last = None          # forza l'invio anche se coincide con l'ultima posa
        self.move_to(x, y)

    # ---- Pulsanti ----
    @staticmethod
    def _btn(button):
        return button if button in ("left", "right", "middle") else "left"

    def press(self, button="left"):
        b = self._btn(button)
        with self._lock:
            if _WIN:
                _user32.mouse_event(_EVT[b][0], 0, 0, 0, 0)
            else:
                pyautogui.mouseDown(button=b, _pause=False)
            self._down.add(b)

    def release(self, button="left"):
        b = self._btn(button)
        with self._lock:
            if _WIN:
                _user32.mouse_event(_EVT[b][1], 0, 0, 0, 0)
            else:
                pyautogui.mouseUp(button=b, _pause=False)
            self._down.discard(b)

    def is_pressed(self, button="left"):
        """True se il pulsante e' premuto (Windows: stato reale del sistema;
        Linux/macOS: stato tracciato da press()/release())."""
        b = self._btn(button)
        if _WIN:
            vk = {"left": 0x01, "right": 0x02, "middle": 0x04}[b]
            return bool(_user32.GetAsyncKeyState(vk) & 0x8000)
        return b in self._down

    def click(self, button="left", clicks=1):
        b = self._btn(button)
        with self._lock:
            for _ in range(max(1, int(clicks))):
                if _WIN:
                    _user32.mouse_event(_EVT[b][0], 0, 0, 0, 0)
                    _user32.mouse_event(_EVT[b][1], 0, 0, 0, 0)
                else:
                    pyautogui.click(button=b, _pause=False)

    def left_click(self):
        self.click("left")

    def right_click(self):
        self.click("right")

    def double_click(self):
        self.click("left", clicks=2)

    # ---- Scroll (steps > 0 = su, < 0 = giu') ----
    def scroll(self, steps=1):
        steps = int(steps)
        if steps == 0:
            return
        with self._lock:
            if _WIN:
                _user32.mouse_event(_WHEEL, 0, 0, (steps * _WHEEL_DELTA) & 0xFFFFFFFF, 0)
            else:
                pyautogui.scroll(steps, _pause=False)

    def scroll_up(self, steps=1):
        self.scroll(abs(steps))

    def scroll_down(self, steps=1):
        self.scroll(-abs(steps))

    def close(self):
        pass


# ==============================================================================
# GESTURE ACTION DISPATCHER (gesto -> azione mouse)
# Azioni: left_click, right_click, double_click, left_lock_toggle,
#         right_lock_toggle, scroll_up, scroll_down
# Alias: select = left_click, drag_toggle = left_lock_toggle
# Se un pulsante e' bloccato, ogni gesto di click rilascia prima il blocco.
# ==============================================================================
_ALIASES = {
    "select": "left_click",
    "drag_toggle": "left_lock_toggle",
}


class GestureActionDispatcher:
    def __init__(self, mouse_controller, action_map, scroll_steps=3):
        self.mouse = mouse_controller
        self.action_map = {k: _ALIASES.get(v, v) for k, v in action_map.items()}
        self.scroll_steps = scroll_steps
        self.left_locked = False
        self.right_locked = False
        self.last_gesture = "Nessuno"
        self.last_confidence = 0.0

    # --- compatibilita' con il server: is_dragging = qualunque pulsante bloccato ---
    @property
    def is_dragging(self):
        return self.left_locked or self.right_locked

    @is_dragging.setter
    def is_dragging(self, value):
        if not value:
            # il server rilascia "left" per conto suo; qui sistemiamo il resto
            self.left_locked = False
            if self.right_locked:
                self.mouse.release("right")
                self.right_locked = False

    def release_all(self):
        if self.left_locked:
            self.mouse.release("left")
            self.left_locked = False
        if self.right_locked:
            self.mouse.release("right")
            self.right_locked = False

    def _toggle_lock(self, button):
        attr = f"{button}_locked"
        if getattr(self, attr):
            self.mouse.release(button)
            setattr(self, attr, False)
            return f"Pulsante {button} RILASCIATO"
        self.mouse.press(button)
        setattr(self, attr, True)
        return f"Pulsante {button} BLOCCATO (hold)"

    def execute_gesture(self, label, confidence, info=None):
        self.last_gesture = label
        self.last_confidence = confidence
        action = self.action_map.get(label)
        if action is None:
            return f"Gesto {label} non mappato"

        # Lock/toggle: sempre eseguiti
        if action == "left_lock_toggle":
            return self._toggle_lock("left")
        if action == "right_lock_toggle":
            return self._toggle_lock("right")

        # Qualsiasi altra azione con un pulsante bloccato -> rilascia e basta
        if self.is_dragging:
            self.release_all()
            return "Blocco pulsanti RILASCIATO (gesto di sicurezza)"

        if action == "left_click":
            self.mouse.click("left")
            return "Click sinistro"
        if action == "right_click":
            self.mouse.click("right")
            return "Click destro"
        if action == "double_click":
            self.mouse.double_click()
            return "Doppio click sinistro"
        if action == "scroll_up":
            self.mouse.scroll_up(self.scroll_steps)
            return f"Scroll su ({self.scroll_steps})"
        if action == "scroll_down":
            self.mouse.scroll_down(self.scroll_steps)
            return f"Scroll giu' ({self.scroll_steps})"
        return f"Azione sconosciuta: {action}"