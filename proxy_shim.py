#!/usr/bin/env python3
"""Puente de proxy local para la JVM.

La salida a internet de esta maquina pasa por un proxy HTTP cuyo formato de
respuesta al CONNECT rompe el tunel HTTPS de Java (NoSuchElementException en
HttpURLConnection.doTunneling). Este puente escucha en 127.0.0.1:18080 sin
autenticacion, reenvia el CONNECT al proxy real (leido de $https_proxy, con
sus credenciales si las trae) y le responde a Java en el formato exacto que
espera. Despues copia bytes en ambas direcciones.
"""
import base64
import os
import select
import socket
import threading
import urllib.parse

LISTEN = ("127.0.0.1", 18080)


def upstream_target():
    raw = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""
    u = urllib.parse.urlparse(raw)
    host = u.hostname or "127.0.0.1"
    port = u.port or 3128
    auth = None
    if u.username:
        cred = f"{urllib.parse.unquote(u.username)}:{urllib.parse.unquote(u.password or '')}"
        auth = base64.b64encode(cred.encode()).decode()
    return host, port, auth


def relay(a, b):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 300)
            if not r:
                break
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


import time

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy_shim.log")


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def handle(client):
    try:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = client.recv(4096)
            if not chunk:
                client.close()
                return
            buf += chunk
        log(f"REQ {buf.split(bytes([13, 10]), 1)[0]!r}")
        line = buf.split(b"\r\n", 1)[0].decode("latin1")
        parts = line.split(" ")
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            client.close()
            return
        target = parts[1]
        host, port, auth = upstream_target()
        up = socket.create_connection((host, port), timeout=30)
        req = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
        if auth:
            req += f"Proxy-Authorization: Basic {auth}\r\n"
        req += "Proxy-Connection: keep-alive\r\n\r\n"
        up.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = up.recv(4096)
            if not chunk:
                up.close()
                client.close()
                return
            resp += chunk
        log(f"UP {target} -> {resp.split(bytes([13, 10]), 1)[0]!r} resp_len={len(resp)}")
        status = resp.split(b"\r\n", 1)[0]
        if b" 200 " not in status:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            up.close()
            client.close()
            return
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        relay(client, up)
    except OSError:
        try:
            client.close()
        except OSError:
            pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(LISTEN)
    srv.listen(64)
    print(f"proxy-shim escuchando en {LISTEN[0]}:{LISTEN[1]}", flush=True)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
