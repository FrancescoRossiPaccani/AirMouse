# --- START [09/10/2026] Step 3: Modulo Driver Movimento Cursore PC (MouseController) ---
"""
mouse_controller.py: Esegue lo spostamento del cursore del mouse sul sistema operativo.
Supporta nativamente sia la libreria 'pynput' (se installata) sia l'API Win32 'ctypes.mouse_event'
per garantire il funzionamento immediato su Windows con latenza minima e zero dipendenze esterne.
"""
import sys

class MouseController:
    """
    Controllore per lo spostamento fisico del mouse del sistema operativo.
    """

    def __init__(self):
        self._backend = None
        self._pynput_mouse = None
        self._user32 = None
        self._x11 = None
        self._x11_display = None
        self._quartz = None

        # --- START [18/10/2026] Step 8: Supporto Cross-Platform Universale Lato Server (Windows, Linux, macOS) ---
        self._pressed_buttons = set()

        # 1. Riconoscimento del Sistema Operativo e selezione del backend nativo
        if sys.platform == "win32":
            # Windows nativo tramite Win32 User32 (zero dipendenze esterne, latenza minima)
            try:
                import ctypes
                self._user32 = ctypes.windll.user32
                self.MOUSEEVENTF_MOVE = 0x0001
                self.MOUSEEVENTF_LEFTDOWN = 0x0002
                self.MOUSEEVENTF_LEFTUP = 0x0004
                self.MOUSEEVENTF_RIGHTDOWN = 0x0008
                self.MOUSEEVENTF_RIGHTUP = 0x0010
                self.MOUSEEVENTF_MIDDLEDOWN = 0x0020
                self.MOUSEEVENTF_MIDDLEUP = 0x0040
                self.MOUSEEVENTF_WHEEL = 0x0800
                self.MOUSEEVENTF_HWHEEL = 0x1000
                self._backend = "win32_ctypes"
            except Exception:
                pass

        elif sys.platform.startswith("linux"):
            # Linux nativo tramite libX11 + libXtst
            try:
                import ctypes
                self._x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
                self._x11_display = self._x11.XOpenDisplay(None)
                if self._x11_display:
                    self._x11_root = self._x11.XDefaultRootWindow(self._x11_display)
                    self._backend = "linux_x11"
                try:
                    self._xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
                except Exception:
                    self._xtst = None
            except Exception:
                pass

        elif sys.platform == "darwin":
            # macOS nativo tramite Quartz / ApplicationServices
            try:
                import ctypes
                from ctypes import util
                framework = util.find_library("ApplicationServices") or "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
                self._quartz = ctypes.cdll.LoadLibrary(framework)
                class CGPoint(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
                self._CGPoint = CGPoint
                self._backend = "darwin_quartz"
            except Exception:
                pass

        # 2. Fallback universale su libreria cross-platform 'pynput'
        if self._backend is None:
            try:
                from pynput.mouse import Controller
                self._pynput_mouse = Controller()
                self._backend = "pynput"
            except ImportError:
                pass

        if self._backend is None:
            self._backend = "dummy"
        # --- END [18/10/2026] Step 8: Supporto Cross-Platform Universale Lato Server (Windows, Linux, macOS) ---

    @property
    def backend_name(self) -> str:
        return self._backend

    def move(self, dx: int, dy: int):
        """
        Muove il cursore del mouse di un offset relativo (dx, dy) in pixel.
        :param dx: pixel orizzontali (positivo = destra, negativo = sinistra)
        :param dy: pixel verticali (positivo = basso, negativo = alto)
        """
        if dx == 0 and dy == 0:
            return

        # --- START [18/10/2026] Step 8: Movimento relativo cross-platform ---
        if self._backend == "win32_ctypes":
            self._user32.mouse_event(self.MOUSEEVENTF_MOVE, int(dx), int(dy), 0, 0)
        elif self._backend == "linux_x11":
            try:
                # XWarpPointer con src/dest relativi
                self._x11.XWarpPointer(self._x11_display, 0, 0, 0, 0, 0, 0, int(dx), int(dy))
                self._x11.XFlush(self._x11_display)
            except Exception:
                pass
        elif self._backend == "darwin_quartz":
            cur_x, cur_y = self.get_position()
            self.set_position(cur_x + dx, cur_y + dy)
        elif self._backend == "pynput":
            self._pynput_mouse.move(dx, dy)
        # --- END [18/10/2026] Step 8: Movimento relativo cross-platform ---

    # --- START [11/10/2026] Step 5: Posizionamento assoluto e ricentramento del cursore ---
    def set_position(self, x: int, y: int):
        """
        Imposta la posizione assoluta (x, y) del cursore del mouse in pixel sullo schermo.
        """
        # --- START [18/10/2026] Step 8: Posizionamento assoluto cross-platform ---
        if self._backend == "win32_ctypes":
            self._user32.SetCursorPos(int(x), int(y))
        elif self._backend == "linux_x11":
            try:
                self._x11.XWarpPointer(self._x11_display, 0, self._x11_root, 0, 0, 0, 0, int(x), int(y))
                self._x11.XFlush(self._x11_display)
            except Exception:
                pass
        elif self._backend == "darwin_quartz":
            try:
                pt = self._CGPoint(float(x), float(y))
                self._quartz.CGWarpMouseCursorPosition(pt)
            except Exception:
                pass
        elif self._backend == "pynput":
            self._pynput_mouse.position = (int(x), int(y))
        # --- END [18/10/2026] Step 8: Posizionamento assoluto cross-platform ---

    def center_cursor(self, center_x: int, center_y: int):
        """
        Centra il cursore del mouse alle coordinate specificate (center_x, center_y).
        Supporta nativamente sistemi multi-monitor con origini virtuali arbitrarie.
        """
        self.set_position(center_x, center_y)
    # --- END [11/10/2026] Step 5: Posizionamento assoluto e ricentramento del cursore ---

    # --- START [18/10/2026] Step 8: Metodo get_position cross-platform ---
    def get_position(self) -> tuple:
        """
        Restituisce la posizione corrente (x, y) del cursore del mouse in pixel sullo schermo.
        Supporta Windows (Win32), Linux (X11), macOS (Quartz) e pynput.
        """
        if self._backend == "win32_ctypes":
            try:
                import ctypes
                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
                pt = POINT()
                self._user32.GetCursorPos(ctypes.byref(pt))
                return int(pt.x), int(pt.y)
            except Exception:
                return (0, 0)
        elif self._backend == "linux_x11":
            try:
                import ctypes
                root_ret = ctypes.c_ulong()
                child_ret = ctypes.c_ulong()
                root_x = ctypes.c_int()
                root_y = ctypes.c_int()
                win_x = ctypes.c_int()
                win_y = ctypes.c_int()
                mask = ctypes.c_uint()
                self._x11.XQueryPointer(
                    self._x11_display, self._x11_root,
                    ctypes.byref(root_ret), ctypes.byref(child_ret),
                    ctypes.byref(root_x), ctypes.byref(root_y),
                    ctypes.byref(win_x), ctypes.byref(win_y),
                    ctypes.byref(mask)
                )
                return int(root_x.value), int(root_y.value)
            except Exception:
                return (0, 0)
        elif self._backend == "darwin_quartz":
            try:
                import ctypes
                event = self._quartz.CGEventCreate(None)
                loc = self._quartz.CGEventGetLocation(event)
                return int(loc.x), int(loc.y)
            except Exception:
                return (0, 0)
        elif self._backend == "pynput" and self._pynput_mouse:
            try:
                pos = self._pynput_mouse.position
                return int(pos[0]), int(pos[1])
            except Exception:
                return (0, 0)
        return (0, 0)

    # --- START [18/10/2026] Step 8: Azioni Mouse Cross-Platform (Click, Drag, Scroll) ---
    def press(self, button: str = "left"):
        """
        Esegue la pressione continua del tasto del mouse (mouse_down) cross-platform.
        Ideale per operazioni di selezione multipla e trascinamento (drag & drop).
        :param button: 'left', 'right', oppure 'middle'
        """
        btn = button.lower()
        self._pressed_buttons.add(btn)

        if self._backend == "win32_ctypes":
            flag = self.MOUSEEVENTF_LEFTDOWN if btn == "left" else (
                self.MOUSEEVENTF_RIGHTDOWN if btn == "right" else self.MOUSEEVENTF_MIDDLEDOWN
            )
            self._user32.mouse_event(flag, 0, 0, 0, 0)

        elif self._backend == "linux_x11":
            if self._xtst and self._x11_display:
                btn_code = 1 if btn == "left" else (3 if btn == "right" else 2)
                self._xtst.XTestFakeButtonEvent(self._x11_display, btn_code, 1, 0)
                self._x11.XFlush(self._x11_display)
            elif self._pynput_mouse:
                from pynput.mouse import Button
                pbtn = Button.left if btn == "left" else (Button.right if btn == "right" else Button.middle)
                self._pynput_mouse.press(pbtn)

        elif self._backend == "darwin_quartz":
            try:
                cur_x, cur_y = self.get_position()
                pt = self._CGPoint(float(cur_x), float(cur_y))
                evt_type = 1 if btn == "left" else (3 if btn == "right" else 25)
                mbtn = 0 if btn == "left" else (1 if btn == "right" else 2)
                ev = self._quartz.CGEventCreateMouseEvent(None, evt_type, pt, mbtn)
                self._quartz.CGEventPost(0, ev)
                self._quartz.CFRelease(ev)
            except Exception:
                if self._pynput_mouse:
                    from pynput.mouse import Button
                    pbtn = Button.left if btn == "left" else (Button.right if btn == "right" else Button.middle)
                    self._pynput_mouse.press(pbtn)

        elif self._backend == "pynput" and self._pynput_mouse:
            from pynput.mouse import Button
            pbtn = Button.left if btn == "left" else (Button.right if btn == "right" else Button.middle)
            self._pynput_mouse.press(pbtn)

    def release(self, button: str = "left"):
        """
        Rilascia il tasto del mouse premuto in precedenza (mouse_up) cross-platform.
        """
        btn = button.lower()
        self._pressed_buttons.discard(btn)

        if self._backend == "win32_ctypes":
            flag = self.MOUSEEVENTF_LEFTUP if btn == "left" else (
                self.MOUSEEVENTF_RIGHTUP if btn == "right" else self.MOUSEEVENTF_MIDDLEUP
            )
            self._user32.mouse_event(flag, 0, 0, 0, 0)

        elif self._backend == "linux_x11":
            if self._xtst and self._x11_display:
                btn_code = 1 if btn == "left" else (3 if btn == "right" else 2)
                self._xtst.XTestFakeButtonEvent(self._x11_display, btn_code, 0, 0)
                self._x11.XFlush(self._x11_display)
            elif self._pynput_mouse:
                from pynput.mouse import Button
                pbtn = Button.left if btn == "left" else (Button.right if btn == "right" else Button.middle)
                self._pynput_mouse.release(pbtn)

        elif self._backend == "darwin_quartz":
            try:
                cur_x, cur_y = self.get_position()
                pt = self._CGPoint(float(cur_x), float(cur_y))
                evt_type = 2 if btn == "left" else (4 if btn == "right" else 26)
                mbtn = 0 if btn == "left" else (1 if btn == "right" else 2)
                ev = self._quartz.CGEventCreateMouseEvent(None, evt_type, pt, mbtn)
                self._quartz.CGEventPost(0, ev)
                self._quartz.CFRelease(ev)
            except Exception:
                if self._pynput_mouse:
                    from pynput.mouse import Button
                    pbtn = Button.left if btn == "left" else (Button.right if btn == "right" else Button.middle)
                    self._pynput_mouse.release(pbtn)

        elif self._backend == "pynput" and self._pynput_mouse:
            from pynput.mouse import Button
            pbtn = Button.left if btn == "left" else (Button.right if btn == "right" else Button.middle)
            self._pynput_mouse.release(pbtn)

    def click(self, button: str = "left"):
        """
        Esegue un singolo click completo (press + release) cross-platform.
        """
        import time
        self.press(button)
        time.sleep(0.015)
        self.release(button)

    def double_click(self, button: str = "left"):
        """
        Esegue un doppio click rapido cross-platform.
        """
        import time
        self.click(button)
        time.sleep(0.06)
        self.click(button)

    def toggle_drag(self, button: str = "left") -> bool:
        """
        Alterna lo stato di trascinamento (drag mode). Se il tasto non è premuto,
        lo preme (inizia il drag/selezione). Se è già premuto, lo rilascia (termina il drag).
        Restituisce True se il tasto è attualmente premuto (in drag), False altrimenti.
        """
        btn = button.lower()
        if btn in self._pressed_buttons:
            self.release(btn)
            return False
        else:
            self.press(btn)
            return True

    def is_pressed(self, button: str = "left") -> bool:
        return button.lower() in self._pressed_buttons

    def scroll(self, dx: int = 0, dy: int = 0):
        """
        Esegue lo scroll della rotellina del mouse cross-platform.
        :param dy: scroll verticale (positivo = su, negativo = giù)
        :param dx: scroll orizzontale
        """
        if dx == 0 and dy == 0:
            return

        if self._backend == "win32_ctypes":
            if dy != 0:
                self._user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, int(dy * 120), 0)
            if dx != 0:
                self._user32.mouse_event(self.MOUSEEVENTF_HWHEEL, 0, 0, int(dx * 120), 0)

        elif self._backend == "linux_x11":
            if self._xtst and self._x11_display:
                btn = 4 if dy > 0 else (5 if dy < 0 else (7 if dx > 0 else 6))
                steps = abs(dy) if dy != 0 else abs(dx)
                for _ in range(max(1, steps)):
                    self._xtst.XTestFakeButtonEvent(self._x11_display, btn, 1, 0)
                    self._xtst.XTestFakeButtonEvent(self._x11_display, btn, 0, 0)
                self._x11.XFlush(self._x11_display)
            elif self._pynput_mouse:
                self._pynput_mouse.scroll(dx, dy)

        elif self._backend == "darwin_quartz":
            try:
                ev = self._quartz.CGEventCreateScrollWheelEvent(None, 0, 1, int(dy))
                self._quartz.CGEventPost(0, ev)
                self._quartz.CFRelease(ev)
            except Exception:
                if self._pynput_mouse:
                    self._pynput_mouse.scroll(dx, dy)

        elif self._backend == "pynput" and self._pynput_mouse:
            self._pynput_mouse.scroll(dx, dy)
    # --- END [18/10/2026] Step 8: Azioni Mouse Cross-Platform (Click, Drag, Scroll) ---

    def __del__(self):
        if hasattr(self, '_x11') and hasattr(self, '_x11_display') and self._x11_display:
            try:
                self._x11.XCloseDisplay(self._x11_display)
            except Exception:
                pass
    # --- END [18/10/2026] Step 8: Metodo get_position cross-platform ---
# --- END [09/10/2026] Step 3: Modulo Driver Movimento Cursore PC (MouseController) ---
