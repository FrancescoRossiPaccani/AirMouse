import json
import socket
import time

HOST = "0.0.0.0"   # ascolta su tutte le interfacce
PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((HOST, PORT))
print(f"In ascolto su UDP {HOST}:{PORT} ...")

count = 0
last_report = time.time()
last_seq = None
lost = 0

while True:
    data, addr = sock.recvfrom(2048)
    try:
        p = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        print("Pacchetto non valido:", data)
        continue

    # conteggio pacchetti persi
    if last_seq is not None and p["seq"] > last_seq + 1:
        lost += p["seq"] - last_seq - 1
    last_seq = p["seq"]

    a, g, m = p["acc"], p["gyro"], p["mag"]
    print(
        f"#{p['seq']:6d} t={p['t']:10d}ms | "
        f"ACC [{a[0]:7.3f} {a[1]:7.3f} {a[2]:7.3f}] m/s² | "
        f"GYR [{g[0]:7.3f} {g[1]:7.3f} {g[2]:7.3f}] rad/s | "
        f"MAG [{m[0]:7.2f} {m[1]:7.2f} {m[2]:7.2f}] µT"
    )

    count += 1
    now = time.time()
    if now - last_report >= 1.0:
        print(f"--- {count / (now - last_report):.1f} Hz da {addr[0]} | persi: {lost} ---")
        count = 0
        last_report = now