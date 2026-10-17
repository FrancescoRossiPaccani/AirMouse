"""
Air Mouse - ricevitore BLE (GATT server) per il PC.

Il PC fa advertising del servizio, lo smartwatch (central) si connette e scrive
i pacchetti dei sensori sulla characteristic DATA (Write Without Response).

Formato pacchetto (little endian):
    int32 seq | int32 t_ms | 9 x float32 clean | [9 x float32 raw]
    -> 44 byte, oppure 80 byte se c'è anche il raw.

Installazione: pip install bless
Avvio:        python airmouse_server.py
"""

import asyncio
import logging
import struct
import time

from bless import (
    BlessGATTCharacteristic,
    BlessServer,
    GATTAttributePermissions,
    GATTCharacteristicProperties,
)

# Devono essere identici a quelli di BleClient.kt
SERVICE_UUID = "7a1c0001-4f5e-4b8a-9d3c-2e6f1a0b5c01"
DATA_UUID = "7a1c0002-4f5e-4b8a-9d3c-2e6f1a0b5c01"
CTRL_UUID = "7a1c0003-4f5e-4b8a-9d3c-2e6f1a0b5c01"

SERVER_NAME = "AirMouse-PC"

SHOW_RAW = True

SIZE_CLEAN = 44
SIZE_FULL = 80

logging.basicConfig(level=logging.WARNING)


# ---------------------------------------------------------------------
# Formattazione: identica al primo programma
# ---------------------------------------------------------------------

def fmt(v, w=8, d=3):
    return " ".join(f"{x:{w}.{d}f}" for x in v)


# ---------------------------------------------------------------------
# Statistiche
# ---------------------------------------------------------------------

class Stats:
    def __init__(self):
        self.reset()

    def reset(self):
        self.expected_seq = 0
        self.received = 0
        self.lost = 0
        self.last_rx = 0.0
        self.last_sample = None
        self.window_count = 0
        self.last_report = time.time()


stats = Stats()


# ---------------------------------------------------------------------
# Parsing del pacchetto binario BLE
# ---------------------------------------------------------------------

def parse_packet(data: bytes):
    """
    Ritorna:
        (seq, t_ms, clean[9], raw[9] | None)

    clean = [ax, ay, az, gx, gy, gz, mx, my, mz]
    raw   = [ax, ay, az, gx, gy, gz, mx, my, mz]
    """

    if len(data) < SIZE_CLEAN:
        return None

    seq, t_ms, *clean = struct.unpack_from("<ii9f", data, 0)

    raw = (
        struct.unpack_from("<9f", data, SIZE_CLEAN)
        if len(data) >= SIZE_FULL
        else None
    )

    return seq, t_ms, clean, raw


# ---------------------------------------------------------------------
# Elaborazione dei campioni
# ---------------------------------------------------------------------

def process_sample(seq, t_ms, clean, raw):
    """
    Inserisci qui la futura logica di controllo del mouse.
    """
    pass


# ---------------------------------------------------------------------
# Ricezione e stampa: formato identico al primo programma
# ---------------------------------------------------------------------

def handle_data(data: bytes):
    pkt = parse_packet(data)

    if pkt is None:
        return

    seq, t_ms, clean, raw = pkt

    # Gestione del riavvio della sequenza dopo una riconnessione.
    if seq < stats.expected_seq:
        stats.reset()

    # Conteggio dei pacchetti persi.
    if seq > stats.expected_seq:
        stats.lost += seq - stats.expected_seq

    stats.expected_seq = seq + 1

    # Separazione dei sensori.
    a, g, m = clean[0:3], clean[3:6], clean[6:9]

    # Stampa dei dati puliti: identica al primo programma.
    print(
        f"#{seq:6d} t={t_ms:10d}ms | "
        f"ACC [{fmt(a)}] | GYR [{fmt(g)}] | MAG [{fmt(m, 8, 2)}]"
    )

    # Stampa dei dati grezzi: identica al primo programma.
    if SHOW_RAW and raw is not None:
        r = raw

        print(
            f"{'raw':>7s} {'':14s} | "
            f"ACC [{fmt(r[0:3])}] | "
            f"GYR [{fmt(r[3:6])}] | "
            f"MAG [{fmt(r[6:9], 8, 2)}]"
        )

    # Aggiornamento delle statistiche.
    stats.received += 1
    stats.window_count += 1
    stats.last_rx = time.time()
    stats.last_sample = (seq, t_ms, clean, raw)

    # Elaborazione del campione.
    process_sample(seq, t_ms, clean, raw)

    # Riepilogo della frequenza: stessa logica del primo programma.
    now = time.time()

    if now - stats.last_report >= 1.0:
        print(
            f"--- {stats.window_count / (now - stats.last_report):.1f} "
            f"Hz | persi: {stats.lost} ---"
        )

        stats.window_count = 0
        stats.last_report = now


# ---------------------------------------------------------------------
# Gestione del comando di disconnessione
# ---------------------------------------------------------------------

def handle_ctrl(data: bytes):
    if data.strip() == b"bye":
        print("\n[ctrl] il watch si è disconnesso (bye)")
        stats.reset()


# ---------------------------------------------------------------------
# Callback BLE
# ---------------------------------------------------------------------

def on_write(
    characteristic: BlessGATTCharacteristic,
    value,
    **kwargs
):
    uuid = str(characteristic.uuid).lower()
    data = bytes(value)

    if uuid == DATA_UUID:
        handle_data(data)

    elif uuid == CTRL_UUID:
        handle_ctrl(data)


# ---------------------------------------------------------------------
# Avvio del server BLE
# ---------------------------------------------------------------------

async def main():
    loop = asyncio.get_running_loop()

    server = BlessServer(
        name=SERVER_NAME,
        loop=loop,
    )

    server.write_request_func = on_write

    await server.add_new_service(SERVICE_UUID)

    wnr = GATTCharacteristicProperties.write_without_response
    wr = GATTCharacteristicProperties.write
    perms = GATTAttributePermissions.writeable

    await server.add_new_characteristic(
        SERVICE_UUID,
        DATA_UUID,
        wnr,
        None,
        perms,
    )

    await server.add_new_characteristic(
        SERVICE_UUID,
        CTRL_UUID,
        wnr | wr,
        None,
        perms,
    )

    await server.start()

    print(f"Advertising come '{SERVER_NAME}' (servizio {SERVICE_UUID})")
    print("In attesa del watch... Ctrl+C per uscire.\n")

    try:
        while True:
            await asyncio.sleep(1.0)

    except (asyncio.CancelledError, KeyboardInterrupt):
        pass

    finally:
        await server.stop()
        print("\nServer fermato.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass