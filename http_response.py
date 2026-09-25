"""
http_response.py
-----------------
Builds raw HTTP/1.1 response bytes. No socket code, no logic about what
status code to use — just formatting.
"""

REASON_PHRASES = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
}


def build_response(
    status: int,
    body: str,
    *,
    extra_headers: dict | None = None,
    keep_alive: bool = True,
) -> bytes:
    reason = REASON_PHRASES.get(status, "Unknown")
    body_bytes = (body + "\n").encode("utf-8")

    headers = [
        f"HTTP/1.1 {status} {reason}",
        "Content-Type: text/plain; charset=utf-8",
        f"Content-Length: {len(body_bytes)}",
        f"Connection: {'keep-alive' if keep_alive else 'close'}",
    ]
    if extra_headers:
        for name, value in extra_headers.items():
            headers.append(f"{name}: {value}")

    raw = "\r\n".join(headers) + "\r\n\r\n"
    return raw.encode("utf-8") + body_bytes
