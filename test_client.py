#!/usr/bin/env python3
"""
test_client.py — exercises server.py over a SINGLE TCP connection.

This checks more than "does GET /add?a=2&b=3 return 5" — it checks the
actual hard part of the assignment: that the server frames requests
correctly even when they're split across small reads, arrive
back-to-back in one packet (pipelined), or carry a body whose exact
byte boundary must be respected.

Usage:
    python3 test_client.py [host] [port]
"""

import socket
import sys
import time

PASS = 0
FAIL = 0


class BufferedSocket:
    """A socket wrapper that remembers leftover bytes between reads,
    the same way the server has to."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buf = b""

    def sendall(self, data: bytes) -> None:
        self.sock.sendall(data)

    def recv_response(self) -> tuple[int, dict, str]:
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("server closed the connection")
            self.buf += chunk
        head, rest = self.buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split(" ")[1])
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        content_length = int(headers.get("content-length", "0") or 0)
        while len(rest) < content_length:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            rest += chunk
        body = rest[:content_length].decode("utf-8", "replace")
        self.buf = rest[content_length:]
        return status, headers, body.strip()

    def close(self) -> None:
        self.sock.close()


def connect(host: str, port: int) -> BufferedSocket:
    return BufferedSocket(socket.create_connection((host, port)))


def make_get(path: str, host: str = "localhost", version: str = "HTTP/1.1", extra: str = "") -> bytes:
    lines = [f"GET {path} {version}"]
    if host is not None:
        lines.append(f"Host: {host}")
    if extra:
        lines.append(extra)
    lines.append("")
    lines.append("")
    return "\r\n".join(lines).encode("utf-8")


def make_post(path: str, body: str = "", host: str = "localhost") -> bytes:
    body_bytes = body.encode("utf-8")
    lines = [
        f"POST {path} HTTP/1.1",
        f"Host: {host}",
        f"Content-Length: {len(body_bytes)}",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("utf-8") + body_bytes


def check(label: str, actual, expected) -> None:
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  ok    {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  (expected {expected!r}, got {actual!r})")


def test_basic_operations(bs: BufferedSocket) -> None:
    print("basic operations")
    cases = [
        ("/add?a=2&b=3", 200, "5"),
        ("/sub?a=10&b=4", 200, "6"),
        ("/mul?a=6&b=7", 200, "42"),
        ("/div?a=9&b=3", 200, "3"),
    ]
    for path, expected_status, expected_body in cases:
        bs.sendall(make_get(path))
        status, _, body = bs.recv_response()
        check(f"GET {path} status", status, expected_status)
        check(f"GET {path} body", body, expected_body)


def test_errors(bs: BufferedSocket) -> None:
    print("error cases")
    bs.sendall(make_get("/div?a=1&b=0"))
    status, _, _ = bs.recv_response()
    check("division by zero -> 400", status, 400)

    bs.sendall(make_get("/add?a=x&b=3"))
    status, _, _ = bs.recv_response()
    check("non-numeric a -> 400", status, 400)

    bs.sendall(make_get("/pow?a=2&b=8"))
    status, _, _ = bs.recv_response()
    check("unknown path -> 404", status, 404)

    bs.sendall(make_post("/add"))
    status, headers, _ = bs.recv_response()
    check("POST /add -> 405", status, 405)
    check("405 carries Allow header", "allow" in headers, True)

    bs.sendall(make_get("/add", host=None))
    status, _, _ = bs.recv_response()
    check("missing Host (HTTP/1.1) -> 400", status, 400)


def test_connection_stays_open_after_400(bs: BufferedSocket) -> None:
    print("connection survives a 400")
    bs.sendall(make_get("/div?a=1&b=0"))
    status, _, _ = bs.recv_response()
    check("div by zero -> 400", status, 400)
    bs.sendall(make_get("/add?a=1&b=1"))
    status, _, body = bs.recv_response()
    check("next request still answered -> 200", status, 200)
    check("next request body correct", body, "2")


def test_http10_no_host_required(bs: BufferedSocket) -> None:
    print("HTTP/1.0 does not require Host")
    bs.sendall(make_get("/add?a=1&b=1", host=None, version="HTTP/1.0"))
    status, _, body = bs.recv_response()
    check("HTTP/1.0, no Host -> 200", status, 200)
    check("HTTP/1.0 body correct", body, "2")


def test_pipelined_requests(bs: BufferedSocket) -> None:
    print("pipelined (concatenated) requests answered in order")
    combined = (
        make_get("/add?a=1&b=1")
        + make_get("/mul?a=3&b=3")
        + make_get("/sub?a=5&b=2")
    )
    bs.sendall(combined)
    expected = [("2"), ("9"), ("3")]
    for exp_body in expected:
        status, _, body = bs.recv_response()
        check(f"pipelined response body {exp_body}", body, exp_body)
        check(f"pipelined response status for {exp_body}", status, 200)


def test_fragmented_request(bs: BufferedSocket) -> None:
    print("request split across several small sends")
    full = make_get("/mul?a=6&b=6")
    for i in range(0, len(full), 5):
        bs.sendall(full[i : i + 5])
        time.sleep(0.01)
    status, _, body = bs.recv_response()
    check("fragmented request status", status, 200)
    check("fragmented request body", body, "36")


def test_body_boundary_exact(bs: BufferedSocket) -> None:
    """
    The assignment's core warning: byte n+1 belongs to somebody else.
    Send a POST with a body, immediately followed (same TCP write) by a
    fresh GET — if the server over-reads the body by even one byte, the
    next GET will come back malformed.
    """
    print("exact Content-Length boundary (byte n+1 test)")
    post = make_post("/add", body="ignored-body")
    following_get = make_get("/sub?a=9&b=4")
    bs.sendall(post + following_get)

    status, _, _ = bs.recv_response()
    check("POST /add -> 405 (method not allowed, body still consumed)", status, 405)

    status, _, body = bs.recv_response()
    check("following GET not corrupted by body over-read", status, 200)
    check("following GET body correct", body, "5")


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080

    bs = connect(host, port)
    print(f"1 TCP handshake to {host}:{port}\n")

    test_basic_operations(bs)
    test_errors(bs)
    test_connection_stays_open_after_400(bs)
    test_http10_no_host_required(bs)
    test_pipelined_requests(bs)
    test_fragmented_request(bs)
    test_body_boundary_exact(bs)

    print(f"\nsocket still open: {bs.sock.fileno() != -1}")
    print(f"{PASS} passed, {FAIL} failed")
    bs.close()
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
