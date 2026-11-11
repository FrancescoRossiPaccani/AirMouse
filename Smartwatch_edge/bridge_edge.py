"""
Bridge BLE -> UDP (versione Edge).
Il PC fa da GATT server BLE: inoltra i comandi dello smartwatch a serverBle-Edge su UDP 127.0.0.1:9000.
Primo byte del pacchetto: 0 = comando mouse (DATA), 1 = controllo (CTRL).
Su Windows usare Python 3.11 (bless non funziona con 3.14): py -3.11 bridge_edge.py
"""

import asyncio, socket, sys
from bless import BlessServer, GATTAttributePermissions, GATTCharacteristicProperties

if sys.platform == "win32":
    # Workaround per BLEAdapter del backend WinRT di bless (CreateFile fallisce)
    import bless.backends.winrt.server as bless_winrt

    class DummyAdapter:
        def __init__(self, *a, **kw): pass
        def __getattr__(self, name):
            return lambda *a, **kw: None

    bless_winrt.BLEAdapter = DummyAdapter

# Devono essere identici a quelli di BleClient.kt sul watch
SERVICE_UUID = "7a1c0001-4f5e-4b8a-9d3c-2e6f1a0b5c01"
DATA_UUID    = "7a1c0002-4f5e-4b8a-9d3c-2e6f1a0b5c01"
CTRL_UUID    = "7a1c0003-4f5e-4b8a-9d3c-2e6f1a0b5c01"
PREFIX = {DATA_UUID: b"\x00", CTRL_UUID: b"\x01"}

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
DEST = ("127.0.0.1", 9000)


def on_write(characteristic, value, **kw):
    prefix = PREFIX.get(str(characteristic.uuid).lower())
    if prefix:
        sock.sendto(prefix + bytes(value), DEST)


async def main():
    server = BlessServer(name="AirMouse-PC", loop=asyncio.get_running_loop())
    server.write_request_func = on_write
    await server.add_new_service(SERVICE_UUID)
    wnr, wr = GATTCharacteristicProperties.write_without_response, GATTCharacteristicProperties.write
    perms = GATTAttributePermissions.writeable
    await server.add_new_characteristic(SERVICE_UUID, DATA_UUID, wnr, None, perms)
    await server.add_new_characteristic(SERVICE_UUID, CTRL_UUID, wnr | wr, None, perms)
    await server.start()
    print("Bridge BLE attivo: in attesa dello smartwatch")
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
