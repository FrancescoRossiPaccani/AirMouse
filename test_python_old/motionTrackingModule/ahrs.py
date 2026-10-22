# --- START [09/10/2026] Step 1: Modulo Filtro AHRS Madgwick (6-DOF / 9-DOF) per PC ---
"""
ahrs.py: Filtro di orientamento e fusione sensoriale Madgwick (6-DOF IMU e 9-DOF MARG).
Calcola il quaternione di assetto e lo converte in angoli di Eulero (Pitch, Yaw, Roll)
utilizzati per il controllo del cursore del mouse.
"""
import math

class AHRSFilter:
    """
    Implementazione del filtro AHRS di Madgwick per la fusione sensoriale (6-DOF IMU e 9-DOF MARG).
    Calcola l'orientamento 3D espresso in quaternioni e converte in angoli di Eulero (Pitch, Yaw, Roll).
    """

    def __init__(self, sample_rate_hz: float = 20.0, beta: float = 0.1, use_magnetometer: bool = False):
        self.sample_period = 1.0 / sample_rate_hz
        self.beta = beta
        self.use_magnetometer = use_magnetometer
        
        # Quaternione normalizzato [q0, q1, q2, q3] dove q0 = w, q1 = x, q2 = y, q3 = z
        self.q0 = 1.0
        self.q1 = 0.0
        self.q2 = 0.0
        self.q3 = 0.0

    def reset(self):
        """Reimposta l'assetto al quaternione identità."""
        self.q0 = 1.0
        self.q1 = 0.0
        self.q2 = 0.0
        self.q3 = 0.0

    # --- START [11/10/2026] Step 6: Supporto dt dinamico e Beta adattivo (COMMENTATI PER STUDIO) ---
    def update(self, acc, gyro, mag=None, dt: float = None):
        """
        Aggiorna il filtro con una nuova lettura.
        :param acc: [ax, ay, az] in m/s^2
        :param gyro: [gx, gy, gz] in rad/s
        :param mag: [mx, my, mz] in uT (opzionale)
        :param dt: intervallo temporale effettivo in secondi (opzionale per ottimizzazione Step 6)
        :return: dict con {"pitch": float, "yaw": float, "roll": float} in gradi
        """
        ax, ay, az = acc[0], acc[1], acc[2]
        gx, gy, gz = gyro[0], gyro[1], gyro[2]

        # ==============================================================================
        # BASE (Step 1): Esecuzione con sample_period nominale
        # ==============================================================================
        if self.use_magnetometer and mag is not None and len(mag) >= 3:
            self._update_9dof(ax, ay, az, gx, gy, gz, mag[0], mag[1], mag[2])
        else:
            self._update_6dof(ax, ay, az, gx, gy, gz)

        # ==============================================================================
        # --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): Passaggio del dt dinamico reale ---
        # Per attivare l'ottimizzazione Step 6, decommenta il blocco sottostante e commenta quello sopra:
        # period = dt if (dt is not None and dt > 0) else self.sample_period
        # if self.use_magnetometer and mag is not None and len(mag) >= 3:
        #     self._update_9dof(ax, ay, az, gx, gy, gz, mag[0], mag[1], mag[2], period)
        # else:
        #     self._update_6dof(ax, ay, az, gx, gy, gz, period)
        # ==============================================================================

        return self.to_euler()

    def _update_6dof(self, ax, ay, az, gx, gy, gz, dt: float = None):
        """Algoritmo Madgwick 6-DOF (IMU: accelerometro + giroscopio)."""
        # ==============================================================================
        # BASE (Step 1): Integrazione temporale con sample_period nominale (1/20 s)
        # ==============================================================================
        period = self.sample_period

        # ==============================================================================
        # --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): dt dinamico effettivo ---
        # Per attivare l'ottimizzazione Step 6, decommenta le 2 righe sottostanti:
        # if dt is not None and dt > 0:
        #     period = dt
        # ==============================================================================

        q0, q1, q2, q3 = self.q0, self.q1, self.q2, self.q3

        # Derivata del quaternione dal giroscopio: qDot = 0.5 * q x omega
        qDot1 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz)
        qDot2 = 0.5 * ( q0 * gx + q2 * gz - q3 * gy)
        qDot3 = 0.5 * ( q0 * gy - q1 * gz + q3 * gx)
        qDot4 = 0.5 * ( q0 * gz + q1 * gy - q2 * gx)

        # Correzione con gradiente dell'accelerometro se non nullo
        norm_a = math.sqrt(ax * ax + ay * ay + az * az)
        if norm_a > 1e-4:
            # ==============================================================================
            # BASE (Step 1): Beta costante standard Madgwick
            # ==============================================================================
            effective_beta = self.beta

            # ==============================================================================
            # --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): Beta Adattivo Anti-Accelerazione Lineare ---
            # Per attivare l'ottimizzazione Step 6, decommenta il blocco sottostante:
            # acc_err = abs(norm_a - 9.80665)
            # if acc_err > 1.2:
            #     decay = max(0.08, 1.0 - (acc_err - 1.2) / 4.0)
            #     effective_beta = self.beta * decay
            # ==============================================================================

            recip_a = 1.0 / norm_a
            ax *= recip_a
            ay *= recip_a
            az *= recip_a

            _2q0 = 2.0 * q0
            _2q1 = 2.0 * q1
            _2q2 = 2.0 * q2
            _2q3 = 2.0 * q3
            _4q0 = 4.0 * q0
            _4q1 = 4.0 * q1
            _4q2 = 4.0 * q2
            _8q1 = 8.0 * q1
            _8q2 = 8.0 * q2
            q0q0 = q0 * q0
            q1q1 = q1 * q1
            q2q2 = q2 * q2
            q3q3 = q3 * q3

            # Gradiente della funzione obiettivo per la gravità
            s0 = _4q0 * q2q2 + _2q2 * ax + _4q0 * q1q1 - _2q1 * ay
            s1 = _4q1 * q3q3 - _2q3 * ax + 4.0 * q0q0 * q1 - _2q0 * ay - _4q1 + _8q1 * q1q1 + _8q1 * q2q2 + _4q1 * az
            s2 = 4.0 * q0q0 * q2 + _2q0 * ax + _4q2 * q3q3 - _2q3 * ay - _4q2 + _8q2 * q1q1 + _8q2 * q2q2 + _4q2 * az
            s3 = 4.0 * q1q1 * q3 - _2q1 * ax + 4.0 * q2q2 * q3 - _2q2 * ay

            norm_s = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
            if norm_s > 1e-4:
                recip_s = 1.0 / norm_s
                s0 *= recip_s
                s1 *= recip_s
                s2 *= recip_s
                s3 *= recip_s

                # Applicazione gradiente pesato da effective_beta
                qDot1 -= effective_beta * s0
                qDot2 -= effective_beta * s1
                qDot3 -= effective_beta * s2
                qDot4 -= effective_beta * s3

        # Integrazione numerica
        self.q0 += qDot1 * period
        self.q1 += qDot2 * period
        self.q2 += qDot3 * period
        self.q3 += qDot4 * period

        self._normalize_quaternion()

    def _update_9dof(self, ax, ay, az, gx, gy, gz, mx, my, mz, dt: float = None):
        """Algoritmo Madgwick 9-DOF (MARG: accelerometro + giroscopio + magnetometro)."""
        # ==============================================================================
        # BASE (Step 1): Integrazione temporale con sample_period nominale (1/20 s)
        # ==============================================================================
        period = self.sample_period

        # ==============================================================================
        # --- OTTIMIZZAZIONE STEP 6 (Commentata per studio): dt dinamico effettivo ---
        # Per attivare l'ottimizzazione Step 6, decommenta le 2 righe sottostanti:
        # if dt is not None and dt > 0:
        #     period = dt
        # ==============================================================================
        q0, q1, q2, q3 = self.q0, self.q1, self.q2, self.q3

        qDot1 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz)
        qDot2 = 0.5 * ( q0 * gx + q2 * gz - q3 * gy)
        qDot3 = 0.5 * ( q0 * gy - q1 * gz + q3 * gx)
        qDot4 = 0.5 * ( q0 * gz + q1 * gy - q2 * gx)

        norm_a = math.sqrt(ax * ax + ay * ay + az * az)
        norm_m = math.sqrt(mx * mx + my * my + mz * mz)

        if norm_a > 1e-4 and norm_m > 1e-4:
            ax /= norm_a
            ay /= norm_a
            az /= norm_a
            mx /= norm_m
            my /= norm_m
            mz /= norm_m

            # Direzione di riferimento del flusso magnetico terrestre
            _2q0mx = 2.0 * q0 * mx
            _2q0my = 2.0 * q0 * my
            _2q0mz = 2.0 * q0 * mz
            _2q1mx = 2.0 * q1 * mx

            hx = mx * (q0*q0 + q1*q1 - q2*q2 - q3*q3) + 2.0 * (my*(q1*q2 - q0*q3) + mz*(q1*q3 + q0*q2))
            hy = 2.0 * (mx*(q1*q2 + q0*q3) + mz*(q2*q3 - q0*q1)) + my * (q0*q0 - q1*q1 + q2*q2 - q3*q3)
            _2bx = math.sqrt(hx * hx + hy * hy)
            _2bz = -2.0 * (mx*(q1*q3 - q0*q2) + my*(q2*q3 + q0*q1)) + mz * (q0*q0 - q1*q1 - q2*q2 + q3*q3)
            _4bx = 2.0 * _2bx
            _4bz = 2.0 * _2bz

            _2q0 = 2.0 * q0
            _2q1 = 2.0 * q1
            _2q2 = 2.0 * q2
            _2q3 = 2.0 * q3
            _4q0 = 4.0 * q0
            _4q1 = 4.0 * q1
            _4q2 = 4.0 * q2
            _8q1 = 8.0 * q1
            _8q2 = 8.0 * q2
            q0q0 = q0 * q0
            q1q1 = q1 * q1
            q2q2 = q2 * q2
            q3q3 = q3 * q3

            s0 = (_4q0 * q2q2 + _2q2 * ax + _4q0 * q1q1 - _2q1 * ay -
                  _2bz * q2 * (_2bx * (0.5 - q2q2 - q3q3) + _2bz * (q1q3 - q0q2) - mx) +
                  (-_2bx * q3 + _2bz * q1) * (_2bx * (q1q2 - q0q3) + _2bz * (q0q1 + q2q3) - my) +
                  _2bx * q2 * (_2bx * (q0q2 + q1q3) + _2bz * (0.5 - q1q1 - q2q2) - mz))

            s1 = (_4q1 * q3q3 - _2q3 * ax + 4.0 * q0q0 * q1 - _2q0 * ay - _4q1 + _8q1 * q1q1 + _8q1 * q2q2 + _4q1 * az +
                  _2bz * q3 * (_2bx * (0.5 - q2q2 - q3q3) + _2bz * (q1q3 - q0q2) - mx) +
                  (_2bx * q2 + _2bz * q0) * (_2bx * (q1q2 - q0q3) + _2bz * (q0q1 + q2q3) - my) +
                  (_2bx * q3 - _4bz * q1) * (_2bx * (q0q2 + q1q3) + _2bz * (0.5 - q1q1 - q2q2) - mz))

            s2 = (4.0 * q0q0 * q2 + _2q0 * ax + _4q2 * q3q3 - _2q3 * ay - _4q2 + _8q2 * q1q1 + _8q2 * q2q2 + _4q2 * az +
                  (-_4bx * q2 - _2bz * q0) * (_2bx * (0.5 - q2q2 - q3q3) + _2bz * (q1q3 - q0q2) - mx) +
                  (_2bx * q1 + _2bz * q3) * (_2bx * (q1q2 - q0q3) + _2bz * (q0q1 + q2q3) - my) +
                  (_2bx * q0 - _4bz * q2) * (_2bx * (q0q2 + q1q3) + _2bz * (0.5 - q1q1 - q2q2) - mz))

            s3 = (4.0 * q1q1 * q3 - _2q1 * ax + 4.0 * q2q2 * q3 - _2q2 * ay +
                  (-_4bx * q3 + _2bz * q1) * (_2bx * (0.5 - q2q2 - q3q3) + _2bz * (q1q3 - q0q2) - mx) +
                  (-_2bx * q0 + _2bz * q2) * (_2bx * (q1q2 - q0q3) + _2bz * (q0q1 + q2q3) - my) +
                  _2bx * q1 * (_2bx * (q0q2 + q1q3) + _2bz * (0.5 - q1q1 - q2q2) - mz))

            norm_s = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
            if norm_s > 1e-4:
                recip_s = 1.0 / norm_s
                s0 *= recip_s
                s1 *= recip_s
                s2 *= recip_s
                s3 *= recip_s

                qDot1 -= self.beta * s0
                qDot2 -= self.beta * s1
                qDot3 -= self.beta * s2
                qDot4 -= self.beta * s3

        self.q0 += qDot1 * period
        self.q1 += qDot2 * period
        self.q2 += qDot3 * period
        self.q3 += qDot4 * period

        self._normalize_quaternion()
    # --- END [11/10/2026] Step 6: Supporto dt dinamico e Beta adattivo anti-accelerazione lineare ---

    def _normalize_quaternion(self):
        norm = math.sqrt(self.q0**2 + self.q1**2 + self.q2**2 + self.q3**2)
        if norm > 1e-6:
            inv = 1.0 / norm
            self.q0 *= inv
            self.q1 *= inv
            self.q2 *= inv
            self.q3 *= inv
        else:
            self.reset()

    def to_euler(self):
        """
        Converte il quaternione in angoli di Eulero (Pitch, Yaw, Roll) in gradi.
        Convenzione standard Tait-Bryan Z-Y-X:
          Pitch: rotazione attorno all'asse Y (movimento verticale cursore)
          Yaw:   rotazione attorno all'asse Z (movimento orizzontale cursore)
          Roll:  rotazione attorno all'asse X (torsione polso per gesture)
        """
        q0, q1, q2, q3 = self.q0, self.q1, self.q2, self.q3

        # Roll (asse X)
        sinr_cosp = 2.0 * (q0 * q1 + q2 * q3)
        cosr_cosp = 1.0 - 2.0 * (q1 * q1 + q2 * q2)
        roll_rad = math.atan2(sinr_cosp, cosr_cosp)

        # Pitch (asse Y)
        sinp = 2.0 * (q0 * q2 - q3 * q1)
        if abs(sinp) >= 1.0:
            pitch_rad = math.copysign(math.pi / 2.0, sinp)
        else:
            pitch_rad = math.asin(sinp)

        # Yaw (asse Z)
        siny_cosp = 2.0 * (q0 * q3 + q1 * q2)
        cosy_cosp = 1.0 - 2.0 * (q2 * q2 + q3 * q3)
        yaw_rad = math.atan2(siny_cosp, cosy_cosp)

        rad_to_deg = 180.0 / math.pi
        return {
            "pitch": pitch_rad * rad_to_deg,
            "yaw": yaw_rad * rad_to_deg,
            "roll": roll_rad * rad_to_deg
        }
# --- END [09/10/2026] Step 1: Modulo Filtro AHRS Madgwick (6-DOF / 9-DOF) per PC ---
