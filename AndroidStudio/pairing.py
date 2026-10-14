"""
pairing.py - Discovery / pairing server for the AirMouse smartwatch.

Minimal integration:

    from pairing import PairingServer

    pairing = PairingServer(name="My PC", udp_port=5005)
    pairing.start()
    pairing.wait_until_paired()          # blocks until a watch is paired
    ...                                  # existing UDP receive code, unchanged
    while pairing.paired: ...            # False when the watch disconnects
    pairing.stop()

Network ports (open them in the firewall):
    UDP 5006  discovery (broadcast requests from the watch)
    TCP 5007  pairing + heartbeat
    UDP 5005  sensor data (unchanged)
"""
# --- START [10/10/2026] Pairing: Modulo Server di Discovery e Pairing UDP/TCP per PC ---
import json
import platform
import socket
import threading
import time
import uuid

PROTO = 1
DISCOVERY_PORT = 5006
TCP_PORT = 5007
HEARTBEAT_TIMEOUT = 6.0  # s without a ping -> watch considered gone


class PairingServer:
    def __init__(self, name=None, device_type=None, udp_port=5005,
                 tcp_port=TCP_PORT, discovery_port=DISCOVERY_PORT,
                 on_paired=None, on_unpaired=None, verbose=True):
        self.name = name or socket.gethostname()
        self.device_type = device_type or f"PC ({platform.system()})"
        self.udp_port = udp_port
        self.tcp_port = tcp_port
        self.discovery_port = discovery_port
        self.on_paired = on_paired        # callback(peer: dict)
        self.on_unpaired = on_unpaired    # callback()
        self.verbose = verbose

        self._id = uuid.uuid4().hex
        self._lock = threading.Lock()
        self._peer = None
        self._conn = None
        self._paired_evt = threading.Event()
        self._unpaired_evt = threading.Event()
        self._unpaired_evt.set()
        self._stop = threading.Event()
        self._seen = set()
        self._socks = []

    # ------------------------------------------------------------ public API
    @property
    def paired(self):
        return self._peer is not None

    @property
    def peer(self):
        """dict(id, name, ip) of the paired watch, or None."""
        p = self._peer
        return dict(p) if p else None

    def is_paired_addr(self, addr):
        """True if addr (as returned by recvfrom) belongs to the paired watch."""
        p = self._peer
        return p is not None and addr[0] == p["ip"]

    def wait_until_paired(self, timeout=None):
        return self._wait(self._paired_evt, timeout)

    def wait_until_unpaired(self, timeout=None):
        return self._wait(self._unpaired_evt, timeout)

    def start(self):
        self._stop.clear()
        for target in (self._discovery_loop, self._tcp_loop):
            threading.Thread(target=target, daemon=True).start()
        self._log(f'"{self.name}" ready. Discovery UDP {self.discovery_port}, '
                  f'pairing TCP {self.tcp_port}, data UDP {self.udp_port}.')
        return self

    def stop(self):
        self._stop.set()
        conn = self._conn
        if conn is not None:
            try:
                conn.sendall(b'{"type":"bye"}\n')
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for s in self._socks:
            try:
                s.close()
            except OSError:
                pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # -------------------------------------------------------------- internals
    def _log(self, msg):
        if self.verbose:
            print(f"[pairing] {msg}", flush=True)

    @staticmethod
    def _wait(evt, timeout):
        # sliced wait so that Ctrl+C works everywhere
        end = None if timeout is None else time.monotonic() + timeout
        while not evt.is_set():
            left = 0.2 if end is None else min(0.2, end - time.monotonic())
            if left <= 0:
                return False
            evt.wait(left)
        return True

    @staticmethod
    def _ip_towards(remote_ip):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((remote_ip, 9))      # sends nothing, just picks the interface
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            s.close()

    def _discovery_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.discovery_port))
        sock.settimeout(0.5)
        self._socks.append(sock)
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if self.paired:                 # paired: ignore connection requests
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if msg.get("type") != "discover" or msg.get("proto") != PROTO:
                continue
            wid = msg.get("id", addr[0])
            if wid not in self._seen:
                self._seen.add(wid)
                self._log(f'Watch "{msg.get("name", "?")}" ({addr[0]}) is looking for a device')
            offer = {"type": "offer", "proto": PROTO, "id": self._id,
                     "name": self.name, "device": self.device_type,
                     "ip": self._ip_towards(addr[0]),
                     "tcp_port": self.tcp_port, "udp_port": self.udp_port}
            try:
                sock.sendto(json.dumps(offer).encode("utf-8"), addr)
            except OSError:
                pass

    def _tcp_loop(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", self.tcp_port))
        srv.listen(4)
        srv.settimeout(0.5)
        self._socks.append(srv)
        while not self._stop.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn, addr), daemon=True).start()

    @staticmethod
    def _send(conn, obj):
        conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    def _handle(self, conn, addr):
        conn.settimeout(HEARTBEAT_TIMEOUT)
        paired_here = False
        reason = "connection closed"
        try:
            rf = conn.makefile("rb")
            line = rf.readline(4096)
            msg = json.loads(line.decode("utf-8")) if line else {}
            if msg.get("type") != "pair" or msg.get("proto") != PROTO:
                return
            peer = {"id": msg.get("id", addr[0]), "name": msg.get("name", "watch"), "ip": addr[0]}
            with self._lock:
                busy = self._peer is not None
                if not busy:
                    self._peer = peer
                    self._conn = conn
                    self._unpaired_evt.clear()
                    self._paired_evt.set()
            if busy:
                self._send(conn, {"type": "busy"})
                return
            paired_here = True
            self._send(conn, {"type": "ack"})
            self._log(f'PAIRED with "{peer["name"]}" ({peer["ip"]})')
            if self.on_paired:
                self.on_paired(dict(peer))

            while not self._stop.is_set():
                line = rf.readline(4096)
                if not line:
                    break
                t = json.loads(line.decode("utf-8")).get("type")
                if t == "ping":
                    self._send(conn, {"type": "pong"})
                elif t == "bye":
                    reason = "watch said bye"
                    break
        except socket.timeout:
            reason = "heartbeat timeout"
        except (OSError, ValueError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            if paired_here:
                with self._lock:
                    self._peer = None
                    self._conn = None
                    self._paired_evt.clear()
                    self._unpaired_evt.set()
                self._log(f"NOT PAIRED ({reason}). Waiting for a watch...")
                if self.on_unpaired:
                    self.on_unpaired()
# --- END [10/10/2026] Pairing: Modulo Server di Discovery e Pairing UDP/TCP per PC ---
