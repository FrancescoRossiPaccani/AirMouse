import json
import socket
import time
from collections import deque

import numpy as np

import train as T                                   # same code used for training
from pairing import PairingServer                   # PAIRING

HOST = "0.0.0.0"
PORT = 5005

MODEL_PATH = "trainedTree/rf.json"
SHOW_STREAM = False     # True: also print every sensor packet
DEBUG = True            # True: print the max peak weight every second (to tune THRESH)

BUF = 64                # samples kept in the buffers (3.2 s)
COOLDOWN = 30           # samples after a detected peak in which new candidates are ignored (1.5 s)
THRESH = 0.4            # min peak/valley weight on the angles (rad)   <- to be tuned
MIN_CONF = 0.5          # discard predictions with lower forest confidence


def fmt(v, w=8, d=3):
    return " ".join(f"{x:{w}.{d}f}" for x in v)


# ------------------------------------------------------------ model (rf.json)
class ForestPredictor:
    def __init__(self, path):
        d = json.load(open(path))
        assert d["window"] == T.W, "rf.json window differs from train.py W"
        assert d["n_candidates"] == len(T.NAMES), "rf.json and train.py features differ"
        self.classes = d["classes"]
        self.sel = np.array(d["selected"])
        self.trees = [(np.array(t["left"]), np.array(t["right"]), np.array(t["feat"]),
                       np.array(t["thr"]), np.array(t["proba"])) for t in d["trees"]]

    def predict(self, f):
        x = np.asarray(f)[self.sel].astype(np.float32)      # sklearn compares in float32
        acc = np.zeros(len(self.classes))
        for left, right, feat, thr, proba in self.trees:
            n = 0
            while left[n] != -1:
                n = left[n] if x[feat[n]] <= thr[n] else right[n]
            acc += proba[n]
        acc /= len(self.trees)
        k = int(acc.argmax())
        return self.classes[k], float(acc[k])


# ------------------------------------------------------------ online detector
class GestureDetector:
    def __init__(self, thresh):
        self.thresh = thresh
        self.reset()

    def reset(self):
        self.q = np.array([1.0, 0.0, 0.0, 0.0])
        self.n = 0                  # total samples received
        self.block_abs = -1         # absolute index up to which candidates are ignored
        self.gyro = deque(maxlen=BUF)
        self.ang = deque(maxlen=BUF)
        self.max_score = 0.0

    def push(self, acc, gyro, mag):
        """Feed one sample. Returns (window, info) when a gesture window is ready."""
        beta = T.BETA_INIT if self.n < T.INIT_SAMPLES else T.BETA
        self.q = T.madgwick_step(self.q, np.array(gyro), np.array(acc), np.array(mag),
                                 beta, T.DT)
        w, x, y, z = self.q
        self.ang.append((np.arctan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)),
                         np.arcsin(np.clip(2 * (w * y - z * x), -1.0, 1.0)),
                         np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))))
        self.gyro.append(gyro)
        self.n += 1

        if len(self.ang) < BUF or self.n < T.INIT_SAMPLES + BUF:    # warm-up
            return None

        ang = np.unwrap(np.array(self.ang), axis=0)
        ang = ang - np.median(ang, axis=0)                           # baseline

        # buffer position i corresponds to the absolute sample index (self.n - BUF + i)
        lo, hi = T.W // 2, BUF - 1 - T.W // 2    # candidates whose 32-sample window fits
        lo = max(lo, self.block_abs - (self.n - BUF) + 1)            # skip peaks already handled
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
        s, e = max(0, p - h), min(BUF, p + h)
        r = T.refine_interval(ang[s:e, ax], T.SLOPE_K, T.FIT_ERR)
        center = p if r is None else s + (r[0] + r[1]) // 2
        start = int(np.clip(center - T.W // 2, 0, BUF - T.W))
        window = np.array(self.gyro)[start:start + T.W]

        # ignore every candidate up to COOLDOWN samples after this peak
        # (also covers the opposite peak of the "return" movement)
        self.block_abs = (self.n - BUF + p) + COOLDOWN
        return window, dict(score=sc, axis=("roll", "pitch", "yaw")[ax], refined=r is not None)


# ------------------------------------------------------------------- main
model = ForestPredictor(MODEL_PATH)
det = GestureDetector(THRESH)
print(f"Model: {len(model.trees)} trees, classes {model.classes}")

pairing = PairingServer(name="AirMouse receiver", udp_port=PORT)   # PAIRING
pairing.start()                                                    # PAIRING

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((HOST, PORT))
sock.settimeout(0.5)                                    # PAIRING (per controllare lo stato)

try:
    while True:
        print("Waiting for a watch to pair...")                    # PAIRING
        pairing.wait_until_paired()                                # PAIRING
        det.reset()
        count, lost, last_seq = 0, 0, None
        last_report = last_dbg = time.time()
        print("Paired. Warming up (AHRS + buffer, about 5 s)...")

        while pairing.paired:                                      # PAIRING (era: while True)
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:                                 # PAIRING
                continue                                           # PAIRING
            if not pairing.is_paired_addr(addr):                   # PAIRING
                continue                                           # PAIRING
            try:
                p = json.loads(data.decode("utf-8"))
                a, g, m = p["acc"], p["gyro"], p["mag"]
            except (ValueError, KeyError):
                continue

            if last_seq is not None and p["seq"] > last_seq + 1:
                lost += p["seq"] - last_seq - 1
            last_seq = p["seq"]

            if SHOW_STREAM:
                print(f"#{p['seq']:6d} t={p['t']:10d}ms | "
                      f"ACC [{fmt(a)}] | GYR [{fmt(g)}] | MAG [{fmt(m, 8, 2)}]")

            # ---- gesture detection + classification
            out = det.push(a, g, m)
            if out is not None:
                window, info = out
                label, conf = model.predict(T.feats(window))
                if conf >= MIN_CONF:
                    print(f">>> {label}  (confidence {conf:.2f}, peak {info['score']:.2f} rad "
                          f"on {info['axis']}{'' if info['refined'] else ', not refined'})")
                else:
                    print(f"    ignored: low confidence ({label} {conf:.2f})")

            count += 1
            now = time.time()
            if DEBUG and now - last_dbg >= 1.0:
                print(f"    [debug] max peak weight in last second: {det.max_score:.3f} rad "
                      f"(thresh {THRESH})")
                det.max_score, last_dbg = 0.0, now
            if now - last_report >= 5.0:
                print(f"--- {count / (now - last_report):.1f} Hz da {addr[0]} | persi: {lost} ---")
                count, last_report = 0, now
except KeyboardInterrupt:
    pass
finally:
    pairing.stop()                                                 # PAIRING