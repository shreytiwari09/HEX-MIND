"""A tiny HTTPS egress proxy that only lets a sandboxed install reach package registries.

The install container sits on a Docker `--internal` network that has no route out; this proxy
is the only other container on that network and the only one with a route out. It speaks just
enough HTTP `CONNECT` for npm, pip and similar tools and allows:

  * port 443 only,
  * hosts that match the allowlist exactly or are a subdomain of an entry,
  * only addresses that are public (no loopback, LAN, link-local or metadata addresses), so an
    allowed name that resolves to an internal address is still refused.

Everything else gets `403`. It uses only the standard library because it runs inside a stock
`python:3.11-slim` container (see sandbox/runner.py); it is also imported by the backend tests.

    python egress_proxy.py            # ALLOW_HOSTS=a.com,b.org  PORT=3128
"""

import asyncio
import ipaddress
import os
import socket
import sys

DEFAULT_PORT = 3128
MAX_HEADER_BYTES = 8192
CONNECT_TIMEOUT_S = 15
IDLE_TIMEOUT_S = 120


def host_allowed(host: str, allow: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == entry or host.endswith("." + entry) for entry in allow)


def public_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await asyncio.wait_for(reader.read(65536), IDLE_TIMEOUT_S):
            writer.write(data)
            await writer.drain()
    except (OSError, TimeoutError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


async def _deny(writer: asyncio.StreamWriter, status: str, why: str) -> None:
    print(f"denied: {why}", flush=True)
    writer.write(f"HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode())
    try:
        await writer.drain()
    finally:
        writer.close()


def make_handler(allow: list[str]):  # type: ignore[no-untyped-def]
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), CONNECT_TIMEOUT_S)
        except (asyncio.LimitOverrunError, asyncio.IncompleteReadError, TimeoutError):
            return await _deny(writer, "400 Bad Request", "unreadable request")
        if len(head) > MAX_HEADER_BYTES:
            return await _deny(writer, "431 Request Header Fields Too Large", "headers too big")
        parts = head.split(b"\r\n", 1)[0].decode("latin-1").split()
        if len(parts) != 3 or parts[0].upper() != "CONNECT":
            return await _deny(writer, "405 Method Not Allowed", "only CONNECT is allowed")
        host, _, port = parts[1].rpartition(":")
        if port != "443" or not host:
            return await _deny(writer, "403 Forbidden", f"only port 443 is allowed: {parts[1]}")
        if not host_allowed(host, allow):
            return await _deny(writer, "403 Forbidden", f"host not on the allowlist: {host}")
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            return await _deny(writer, "502 Bad Gateway", f"cannot resolve {host}")
        addresses = [str(info[4][0]) for info in infos]
        if not addresses or not all(public_address(a) for a in addresses):
            return await _deny(writer, "403 Forbidden", f"{host} resolves to a non-public address")
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(addresses[0], 443), CONNECT_TIMEOUT_S
            )
        except (OSError, TimeoutError):
            return await _deny(writer, "502 Bad Gateway", f"cannot connect to {host}")
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(
            _pipe(reader, upstream_writer), _pipe(upstream_reader, writer), return_exceptions=True
        )

    return handle


async def serve(allow: list[str], port: int = DEFAULT_PORT, host: str = "0.0.0.0") -> None:  # noqa: S104
    server = await asyncio.start_server(make_handler(allow), host, port)
    print(f"listening on {port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    allowed = [h.strip().lower() for h in os.environ.get("ALLOW_HOSTS", "").split(",") if h.strip()]
    try:
        asyncio.run(serve(allowed, int(os.environ.get("PORT", DEFAULT_PORT))))
    except KeyboardInterrupt:
        sys.exit(0)
