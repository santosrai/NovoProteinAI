"""Quick, low-level Redis connectivity + auth check (does NOT touch the schema).

Opens a raw socket and speaks RESP directly so we can separately tell apart:
  * network reachability (can we connect?)
  * server liveness   (does PING return -NOAUTH or +PONG fast?)
  * credentials       (does AUTH return +OK or -WRONGPASS?)

Uses short timeouts and a few retries so a lossy network path fails fast.
"""

import os
import socket
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

HOST = os.getenv("REDIS_HOST")
PORT = int(os.getenv("REDIS_PORT", "6379"))
USERNAME = os.getenv("REDIS_USERNAME", "default")
PASSWORD = os.getenv("REDIS_PASSWORD") or ""

TIMEOUT = 4
ATTEMPTS = 8


def _resp_cmd(*args: str) -> bytes:
    out = [f"*{len(args)}\r\n".encode()]
    for a in args:
        b = a.encode()
        out.append(f"${len(b)}\r\n".encode() + b + b"\r\n")
    return b"".join(out)


def probe() -> bool:
    start = time.time()
    s = socket.create_connection((HOST, PORT), timeout=TIMEOUT)
    s.settimeout(TIMEOUT)
    try:
        s.sendall(_resp_cmd("AUTH", USERNAME, PASSWORD))
        auth = s.recv(200)
        s.sendall(_resp_cmd("PING"))
        ping = s.recv(200)
        s.sendall(_resp_cmd("SET", "foo", "bar"))
        setr = s.recv(200)
        s.sendall(_resp_cmd("GET", "foo"))
        getr = s.recv(200)
    finally:
        s.close()
    print(f"  AUTH={auth!r} PING={ping!r} SET={setr!r} GET={getr!r}")
    ok = auth.startswith(b"+OK") and ping.startswith(b"+PONG")
    print(f"  ({time.time() - start:.2f}s) -> {'AUTH OK' if ok else 'AUTH/PROTO PROBLEM'}")
    return ok


def main() -> None:
    print(f"target {HOST}:{PORT} user={USERNAME}")
    for attempt in range(1, ATTEMPTS + 1):
        try:
            if probe():
                print("REDIS OK")
                return
            print("REDIS REACHABLE BUT AUTH FAILED")
            return
        except Exception as exc:
            print(f"[{attempt}] {type(exc).__name__}: {exc}")
            time.sleep(1)
    print("REDIS FAILED after all attempts (intermittent/unreachable endpoint)")


if __name__ == "__main__":
    main()
