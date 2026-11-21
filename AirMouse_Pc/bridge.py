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

SERVICE_UUID = "7a1c0001-4f5e-4b8a-9d3c-2e6f1a0b5c01"
DATA_UUID    = "7a1c0002-4f5e-4b8a-9d3c-2e6f1a0b5c01"
CTRL_UUID    = "7a1c0003-4f5e-4b8a-9d3c-2e6f1a0b5c01"
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
DEST = ("127.0.0.1", 9000)

def on_write(characteristic, value, **kw):
    uuid = str(characteristic.uuid).lower()
    if uuid == DATA_UUID:
        sock.sendto(b"\x00" + bytes(value), DEST)   # 0 = campione
    elif uuid == CTRL_UUID:
        sock.sendto(b"\x01" + bytes(value), DEST)   # 1 = controllo (pause/resume/bye)

async def main():
    server = BlessServer(name="AirMouse-PC", loop=asyncio.get_running_loop())
    server.write_request_func = on_write
    await server.add_new_service(SERVICE_UUID)
    wnr, wr = GATTCharacteristicProperties.write_without_response, GATTCharacteristicProperties.write
    perms = GATTAttributePermissions.writeable
    await server.add_new_characteristic(SERVICE_UUID, DATA_UUID, wnr, None, perms)
    await server.add_new_characteristic(SERVICE_UUID, CTRL_UUID, wnr | wr, None, perms)
    await server.start()
    print("Bridge BLE attivo")
    await asyncio.Event().wait()

asyncio.run(main())
