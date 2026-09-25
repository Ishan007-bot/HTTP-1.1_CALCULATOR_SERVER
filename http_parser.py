"""
http_parser.py
---------------
Turns the raw bytes of one request's headers (everything up to, but not
including, the blank line) into a structured dict.

Raises ValueError for anything that makes the request line or headers
themselves unreadable — that's a FRAMING problem, not an application
problem, and connection.py treats the two very differently (see there).
"""

from urllib.parse import urlparse, parse_qs


def parse_request(header_bytes: bytes) -> dict:
    try:
        text = header_bytes.decode("latin-1")
    except Exception as exc:
        raise ValueError(f"could not decode request headers: {exc}")

    lines = text.split("\r\n")
    request_line = lines[0]
    parts = request_line.split(" ")
    if len(parts) != 3:
        raise ValueError(f"malformed request line: {request_line!r}")

    method, raw_target, version = parts
    if not method or not raw_target or not version.startswith("HTTP/1."):
        raise ValueError(f"malformed request line: {request_line!r}")

    parsed = urlparse(raw_target)
    path = parsed.path or "/"
    qs_dict = parse_qs(parsed.query, keep_blank_values=True)
    query = {k: v[0] for k, v in qs_dict.items()}

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if line == "":
            continue
        if ":" not in line:
            raise ValueError(f"malformed header line: {line!r}")
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()

    return {
        "method": method,
        "path": path,
        "query": query,
        "version": version,
        "headers": headers,
    }
