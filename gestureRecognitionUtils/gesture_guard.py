"""
Speculative cursor freeze around gestures (Magic-Hand, sec. 5.1:
"avoid jumping in the click process").

Gestures are faster than cursor movement, so a high angular rate freezes the cursor
at the position it had just before the onset. On release the angular zero is shifted
by the angle travelled while frozen, so the cursor resumes from the recorded position.
Assumes yaw/pitch in degrees and a mapper that is a function of (angle - zero_angle).
"""
from collections import deque


class GestureGuard:
    def __init__(self, rate_on_dps=80.0, rate_off_dps=30.0, lookback=2,
                 settle_samples=5, max_freeze_samples=25, drag_factor=1.5,
                 enabled=True, verbose=True):
        self.rate_on = rate_on_dps
        self.rate_off = rate_off_dps
        self.lookback = lookback
        self.settle = settle_samples
        self.max_freeze = max_freeze_samples
        self.drag_factor = drag_factor      # less sensitive while dragging
        self.enabled = enabled
        self.verbose = verbose
        self.reset()

    def reset(self):
        self._hist = deque(maxlen=32)       # (yaw, pitch, x, y) of the live samples
        self.frozen = False
        self.hold = None                    # (yaw, pitch, x, y) at gesture onset
        self._calm = 0
        self._n = 0
        self._peak = 0.0
        self.off_yaw = 0.0
        self.off_pitch = 0.0
        self.n_freezes = 0

    @property
    def offsets(self):
        return self.off_yaw, self.off_pitch

    @property
    def hold_xy(self):
        return self.hold[2], self.hold[3]

    @staticmethod
    def _wrap(a):
        return (a + 180.0) % 360.0 - 180.0

    def record(self, yaw, pitch, x, y):
        """Call with the live (unfrozen) position of every sample."""
        self._hist.append((yaw, pitch, x, y))

    def update(self, rate_dps, yaw, pitch, dragging=False):
        """Call once per sample BEFORE mapping. Returns True while the cursor must stay frozen."""
        if not self.enabled:
            return False

        if not self.frozen:
            on = self.rate_on * (self.drag_factor if dragging else 1.0)
            if rate_dps > on and self._hist:
                self.hold = self._hist[-min(self.lookback, len(self._hist))]
                self.frozen = True
                self._calm = self._n = 0
                self._peak = rate_dps
                self.n_freezes += 1
                if self.verbose:
                    print(f"\n  [GUARD] freeze at {rate_dps:.0f} deg/s")
            return self.frozen

        self._n += 1
        self._peak = max(self._peak, rate_dps)
        self._calm = self._calm + 1 if rate_dps < self.rate_off else 0
        if self._calm >= self.settle or self._n >= self.max_freeze:
            # resume from the recorded position, not from where the hand points
            self.off_yaw += self._wrap(yaw - self.hold[0])
            self.off_pitch += pitch - self.hold[1]
            self.frozen = False
            if self.verbose:
                why = "timeout" if self._calm < self.settle else "settled"
                print(f"\n  [GUARD] release ({why}) after {self._n} samples, "
                      f"peak {self._peak:.0f} deg/s")
        return self.frozen