"""
connection.py
-------------
Manages one persistent TCP connection: this is where the actual "hard
part" of the assignment lives.

Key responsibilities:
  - Keep a per-connection receive buffer.
  - Read from the socket until the header delimiter \\r\\n\\r\\n is found.
  - Read exactly Content-Length body bytes — never more, never less —
    so byte n+1 is left untouched for the next request.
  - Preserve any leftover bytes in the buffer for the next request
    (this is also what makes pipelining work: several requests that
    arrive back-to-back in one TCP segment still get parsed and
    answered one at a time, in order).
  - Route each request and send its response.
  - Loop until the client disconnects, asks to close, goes idle too
    long, or a framing error makes the stream untrustworthy.

Design note — framing errors vs semantic errors:
  A 400 for "division by zero" or "a is not a number" means we read a
  complete, well-formed request and disagreed with its *content*. The
  bytes after it are still trustworthy, so the connection stays open.
  A framing error (can't find \\r\\n\\r\\n, a header line with no colon,
  a garbage Content-Length) means we can no longer be sure where the
  current request ends — so we have no safe place to resume, and we
  must close the connection after replying.
"""

import socket

from http_parser import parse_request
from http_response import build_response
from router import route

RECV_SIZE = 4096
MAX_HEADER_SIZE = 64 * 1024  # sanity cap so a headerless stream can't hang us forever
IDLE_TIMEOUT_SECONDS = 30  # defensive: don't hold a thread open on a silent client


def handle_connection(conn: socket.socket, addr: tuple) -> None:
    conn.settimeout(IDLE_TIMEOUT_SECONDS)
    buf = b""

    try:
        while True:
            try:
                header_bytes, buf = _read_headers(conn, buf)
            except _PeerClosed:
                return  # clean disconnect, nothing more to do
            except socket.timeout:
                return  # idle too long; close quietly, no response owed
            except ValueError as exc:
                _send_framing_error(conn, str(exc))
                return

            try:
                request = parse_request(header_bytes)
            except ValueError as exc:
                _send_framing_error(conn, str(exc))
                return

            try:
                content_length = _parse_content_length(request["headers"])
            except ValueError as exc:
                _send_framing_error(conn, str(exc))
                return

            if content_length > 0:
                try:
                    _body, buf = _read_body(conn, buf, content_length)
                except _PeerClosed:
                    return
                except socket.timeout:
                    return

            status, body = route(request)

            extra_headers = {"Allow": "GET"} if status == 405 else None
            client_wants_close = request["headers"].get("connection", "").lower() == "close"
            response = build_response(
                status, body, extra_headers=extra_headers, keep_alive=not client_wants_close
            )
            conn.sendall(response)

            if client_wants_close:
                return

    except OSError:
        pass  # peer reset the connection etc. — nothing to send, just clean up
    finally:
        conn.close()


class _PeerClosed(Exception):
    """The client closed its write side with no more data pending."""


def _recv_more(conn: socket.socket, buf: bytes) -> bytes:
    data = conn.recv(RECV_SIZE)
    if not data:
        raise _PeerClosed()
    return buf + data


def _read_headers(conn: socket.socket, buf: bytes) -> tuple[bytes, bytes]:
    """Read until \\r\\n\\r\\n. Returns (header_bytes, remainder_after_it)."""
    while True:
        idx = buf.find(b"\r\n\r\n")
        if idx != -1:
            return buf[:idx], buf[idx + 4:]
        if len(buf) > MAX_HEADER_SIZE:
            raise ValueError("header section too large")
        buf = _recv_more(conn, buf)


def _read_body(conn: socket.socket, buf: bytes, length: int) -> tuple[bytes, bytes]:
    """Read exactly `length` bytes. Returns (body, remainder_after_it)."""
    while len(buf) < length:
        buf = _recv_more(conn, buf)
    return buf[:length], buf[length:]


def _parse_content_length(headers: dict) -> int:
    raw = headers.get("content-length", "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"invalid Content-Length: {raw!r}")
    if value < 0:
        raise ValueError(f"negative Content-Length: {raw!r}")
    return value


def _send_framing_error(conn: socket.socket, detail: str) -> None:
    try:
        conn.sendall(build_response(400, f"bad request: {detail}", keep_alive=False))
    except OSError:
        pass
