# --- START [18/10/2026] Step 11: Modulo Dispatcher Azioni Mouse Cross-Platform ---
"""
action_dispatcher.py: Mappatore ed esecutore di azioni mouse a livello di sistema operativo
a partire dai gesti classificati (RLB, RRB, UDB, MLB, MRB).
Supporta nativamente Windows, Linux e macOS tramite il driver MouseController.
"""

from motionTrackingModule.mouse_controller import MouseController


class GestureActionDispatcher:
    """
    Dispatcher per l'esecuzione di azioni mouse (click, drag, scroll)
    in risposta ai gesti riconosciuti dallo smartwatch.
    """

    def __init__(self, mouse_controller: MouseController, action_map: dict, scroll_steps: int = 3):
        self.mouse = mouse_controller
        self.action_map = action_map
        self.scroll_steps = int(scroll_steps)
        self.last_gesture = "Nessuno"
        self.last_confidence = 0.0
        self.last_action_desc = "In attesa"
        self.is_dragging = False

    def execute_gesture(self, label: str, confidence: float, info: dict) -> str:
        """
        Esegue l'azione mouse corrispondente al gesto specificato.
        Restituisce una stringa descrittiva dell'azione eseguita.
        """
        action = self.action_map.get(label, "none").lower()
        desc = f"Gesto '{label}' senza azione associata"

        # 1. Selezione / Click Sinistro (RLB)
        if action in ("select", "click", "left_click"):
            if self.is_dragging or self.mouse.is_pressed("left"):
                self.mouse.release("left")
                self.is_dragging = False
                desc = "RILASCIO DRAG (Left Up)"
            else:
                self.mouse.click(button="left")
                desc = "CLICK SINISTRO (Select)"

        # 2. Menu Contestuale / Click Destro (RRB)
        elif action in ("right_click", "context_menu"):
            if self.is_dragging:
                self.mouse.release("left")
                self.is_dragging = False
            self.mouse.click(button="right")
            desc = "CLICK DESTRO (Context Menu)"

        # 3. Toggle Trascinamento / Drag & Drop (UDB)
        elif action in ("drag_toggle", "drag", "select_drag"):
            self.is_dragging = self.mouse.toggle_drag(button="left")
            desc = "TRASCINAMENTO ATTIVATO (Drag Mode ON)" if self.is_dragging else "TRASCINAMENTO RILASCIATO (Drag Mode OFF)"

        # 4. Doppio Click Sinistro
        elif action == "double_click":
            if self.is_dragging:
                self.mouse.release("left")
                self.is_dragging = False
            self.mouse.double_click(button="left")
            desc = "DOPPIO CLICK (Open)"

        # 5. Scroll Rotellina in Alto (MLB)
        elif action == "scroll_up":
            self.mouse.scroll(dx=0, dy=self.scroll_steps)
            desc = f"SCROLL IN ALTO (+{self.scroll_steps})"

        # 6. Scroll Rotellina in Basso (MRB)
        elif action == "scroll_down":
            self.mouse.scroll(dx=0, dy=-self.scroll_steps)
            desc = f"SCROLL IN BASSO (-{self.scroll_steps})"

        self.last_gesture = label
        self.last_confidence = confidence
        self.last_action_desc = desc
        return desc
# --- END [18/10/2026] Step 11: Modulo Dispatcher Azioni Mouse Cross-Platform ---
