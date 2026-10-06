import json
import socket
import time

HOST = "0.0.0.0"
PORT = 5005

SHOW_RAW = True  # metti False per stampare solo i dati puliti


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # non invia nulla, serve solo a scegliere l'interfaccia
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def fmt(v, w=8, d=3):
    return " ".join(f"{x:{w}.{d}f}" for x in v)


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((HOST, PORT))

ip = get_local_ip()
print("=" * 50)
print(f"  IP del PC:  {ip}")
print(f"  Porta UDP:  {PORT}")
print(f'  Nell\'app Android imposta: PC_IP = "{ip}"')
print("=" * 50)

count, lost, last_seq = 0, 0, None
last_report = time.time()

while True:
    data, addr = sock.recvfrom(2048)
    try:
        p = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        continue

    if last_seq is not None and p["seq"] > last_seq + 1:
        lost += p["seq"] - last_seq - 1
    last_seq = p["seq"]

    a, g, m = p["acc"], p["gyro"], p["mag"]
    print(
        f"#{p['seq']:6d} t={p['t']:10d}ms | "
        f"ACC [{fmt(a)}] | GYR [{fmt(g)}] | MAG [{fmt(m, 8, 2)}]"
    )

    if SHOW_RAW and "raw" in p:
        r = p["raw"]
        print(
            f"{'raw':>7s} {'':14s} | "
            f"ACC [{fmt(r[0:3])}] | GYR [{fmt(r[3:6])}] | MAG [{fmt(r[6:9], 8, 2)}]"
        )

    count += 1
    now = time.time()
    if now - last_report >= 1.0:
        print(f"--- {count / (now - last_report):.1f} Hz da {addr[0]} | persi: {lost} ---")
        count, last_report = 0, now