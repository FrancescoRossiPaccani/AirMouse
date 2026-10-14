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
        self._ctypes_mouse = None

        # Tentativo 1: verifica disponibilità libreria pynput
        try:
            from pynput.mouse import Controller
            self._pynput_mouse = Controller()
            self._backend = "pynput"
        except ImportError:
            pass

        # Tentativo 2: fallback nativo su Windows tramite ctypes (user32.mouse_event)
        if self._backend is None and sys.platform == "win32":
            try:
                import ctypes
                self._user32 = ctypes.windll.user32
                # Costante MOUSEEVENTF_MOVE = 0x0001 (movimento relativo del mouse)
                self.MOUSEEVENTF_MOVE = 0x0001
                self._backend = "win32_ctypes"
            except Exception:
                pass

        if self._backend is None:
            self._backend = "dummy"

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

        if self._backend == "win32_ctypes":
            # API nativa Windows: esecuzione diretta nel kernel di Windows a latenza zero
            self._user32.mouse_event(self.MOUSEEVENTF_MOVE, int(dx), int(dy), 0, 0)
        elif self._backend == "pynput":
            self._pynput_mouse.move(dx, dy)
        else:
            # Backend dummy o non supportato
            pass

    # --- START [11/10/2026] Step 5: Posizionamento assoluto e ricentramento del cursore ---
    def set_position(self, x: int, y: int):
        """
        Imposta la posizione assoluta (x, y) del cursore del mouse in pixel sullo schermo.
        """
        if self._backend == "win32_ctypes":
            self._user32.SetCursorPos(int(x), int(y))
        elif self._backend == "pynput":
            self._pynput_mouse.position = (int(x), int(y))

    def center_cursor(self, center_x: int, center_y: int):
        """
        Centra il cursore del mouse alle coordinate specificate (center_x, center_y).
        Supporta nativamente sistemi multi-monitor con origini virtuali arbitrarie.
        """
        self.set_position(center_x, center_y)
    # --- END [11/10/2026] Step 5: Posizionamento assoluto e ricentramento del cursore ---

    # ==============================================================================
    # --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): Metodo get_position ---
    # Per attivare l'ottimizzazione Step 6, decommenta il metodo sottostante:
    # def get_position(self) -> tuple:
    #     """
    #     Restituisce la posizione corrente (x, y) del cursore del mouse in pixel sullo schermo.
    #     """
    #     if self._backend == "win32_ctypes":
    #         try:
    #             import ctypes
    #             class POINT(ctypes.Structure):
    #                 _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    #             pt = POINT()
    #             self._user32.GetCursorPos(ctypes.byref(pt))
    #             return int(pt.x), int(pt.y)
    #         except Exception:
    #             return (0, 0)
    #     elif self._backend == "pynput":
    #         try:
    #             pos = self._pynput_mouse.position
    #             return int(pos[0]), int(pos[1])
    #         except Exception:
    #             return (0, 0)
    #     return (0, 0)
    # ==============================================================================
# --- END [09/10/2026] Step 3: Modulo Driver Movimento Cursore PC (MouseController) ---
