# --- START [18/10/2026] Step 11: Modulo Riconoscimento Gesti (ForestPredictor & OnlineGestureDetector) ---
"""
detector.py: Classificatore Random Forest nativo (rf.json) e Detector online causale
per il riconoscimento in tempo reale dei gesti da segnali IMU (accelerometro, giroscopio, magnetometro).
Basato sui principi del paper Magic-Hand (Bi et al., 2021).
"""

import json
import os
import sys
from collections import deque
import numpy as np

# Import del modulo di training per l'estrazione delle feature
_CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if _CUR_DIR not in sys.path:
    sys.path.insert(0, _CUR_DIR)

try:
    import train as T
except ImportError:
    from gestureRecognitionUtils import train as T


class ForestPredictor:
    """
    Classificatore Random Forest ad inferenza istantanea (0 ms) senza dipendenze pesanti a runtime.
    Carica la struttura gerarchica degli alberi decisionali esportata nel file JSON (rf.json).
    """

    def __init__(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Modello Random Forest non trovato nel percorso specificato: {path}")

        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)

        assert d["window"] == T.W, "La dimensione della finestra in rf.json differisce da train.py W"
        assert d["n_candidates"] == len(T.NAMES), "Il numero di feature candidate in rf.json differisce da train.py"

        self.classes = d["classes"]
        self.sel = np.array(d["selected"], dtype=int)
        self.trees = [
            (
                np.array(t["left"], dtype=int),
                np.array(t["right"], dtype=int),
                np.array(t["feat"], dtype=int),
                np.array(t["thr"], dtype=np.float32),
                np.array(t["proba"], dtype=np.float32),
            )
            for t in d["trees"]
        ]

    def predict(self, f: np.ndarray) -> tuple[str, float]:
        """
        Classifica il vettore delle feature estratte e restituisce la tupla:
        (classe_predetta, punteggio_confidenza)
        """
        x = np.asarray(f)[self.sel].astype(np.float32)  # sklearn valuta i nodi in float32
        acc = np.zeros(len(self.classes), dtype=np.float32)
        for left, right, feat, thr, proba in self.trees:
            n = 0
            while left[n] != -1:
                n = left[n] if x[feat[n]] <= thr[n] else right[n]
            acc += proba[n]
        acc /= len(self.trees)
        k = int(acc.argmax())
        return self.classes[k], float(acc[k])


class OnlineGestureDetector:
    """
    Rilevatore causale online di picchi e valli per l'individuazione di gesti.
    Mantiene un buffer circolare di campioni e angoli stimati per estrarre
    una finestra di 32 campioni centrata sul picco del movimento.
    """

    def __init__(self, thresh: float = 0.40, cooldown: int = 30, buf_size: int = 64):
        self.thresh = float(thresh)
        self.cooldown = int(cooldown)
        self.buf_size = int(buf_size)
        self.reset()

    def reset(self):
        """Azzera lo stato del quaternione, i buffer e i contatori."""
        self.q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
        self.n = 0
        self.block_abs = -1
        self.gyro = deque(maxlen=self.buf_size)
        self.ang = deque(maxlen=self.buf_size)
        self.max_score = 0.0

    def push(self, acc: list, gyro: list, mag: list) -> tuple | None:
        """
        Alimenta un singolo campione (acc, gyro, mag) al detector causale.
        Restituisce (window_32, info_dict) quando un gesto candidato è individuato,
        oppure None se non ci sono picchi o durante la fase di warm-up/cooldown.
        """
        beta = T.BETA_INIT if self.n < T.INIT_SAMPLES else T.BETA
        self.q = T.madgwick_step(
            self.q,
            np.array(gyro, dtype=np.float64),
            np.array(acc, dtype=np.float64),
            np.array(mag, dtype=np.float64),
            beta,
            T.DT,
        )
        w, x, y, z = self.q
        roll = np.arctan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        pitch = np.arcsin(np.clip(2 * (w * y - z * x), -1.0, 1.0))
        yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))

        self.ang.append((roll, pitch, yaw))
        self.gyro.append(gyro)
        self.n += 1

        # Attesa riempimento buffer iniziale
        if len(self.ang) < self.buf_size or self.n < T.INIT_SAMPLES + self.buf_size:
            return None

        ang = np.unwrap(np.array(self.ang), axis=0)
        ang = ang - np.median(ang, axis=0)  # Rimozione baseline

        # Finestra per candidati validi con 32 campioni
        lo, hi = T.W // 2, self.buf_size - 1 - T.W // 2
        lo = max(lo, self.block_abs - (self.n - self.buf_size) + 1)
        if lo > hi:
            return None

        best = None
        for ax in range(3):
            wp, wv = T.peak_valley_weights(ang[:, ax], T.PEAK_K)
            score = np.maximum(wp, -wv)
            i = lo + int(score[lo:hi + 1].argmax())
            self.max_score = max(self.max_score, float(score[i]))
            local_max = score[i] >= score[max(0, i - T.PEAK_K):i + T.PEAK_K + 1].max()
            if score[i] > self.thresh and local_max and (best is None or score[i] > best[0]):
                best = (float(score[i]), ax, i)

        if best is None:
            return None

        sc, ax, p = best
        h = T.INTERVAL // 2
        s, e = max(0, p - h), min(self.buf_size, p + h)
        r = T.refine_interval(ang[s:e, ax], T.SLOPE_K, T.FIT_ERR)
        center = p if r is None else s + (r[0] + r[1]) // 2
        start = int(np.clip(center - T.W // 2, 0, self.buf_size - T.W))
        window = np.array(self.gyro)[start:start + T.W]

        # Cooldown per ignorare picchi successivi (incluso il ritorno del movimento)
        self.block_abs = (self.n - self.buf_size + p) + self.cooldown
        return window, dict(score=sc, axis=("roll", "pitch", "yaw")[ax], refined=r is not None)
# --- END [18/10/2026] Step 11: Modulo Riconoscimento Gesti (ForestPredictor & OnlineGestureDetector) ---
