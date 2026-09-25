# HTTP/1.1 Calculator Server

A calculator you talk to over HTTP, on a connection that stays open for
every request — no framework, just a raw TCP socket.

## What it does

```
GET /add?a=2&b=3   -> 200   5
GET /sub?a=10&b=4  -> 200   6
GET /mul?a=6&b=7   -> 200   42
GET /div?a=9&b=3   -> 200   3
```

Errors:

| Status | When |
|---|---|
| 400 | malformed request, missing `Host` header (HTTP/1.1 only), missing/non-numeric `a` or `b`, division by zero |
| 404 | path isn't `/add`, `/sub`, `/mul`, or `/div` |
| 405 | path is known but the method isn't `GET` |

The connection is **not** closed after each response. One TCP handshake
can carry any number of requests, in order, including ones sent
back-to-back (pipelined) or split across several small reads.

## Files

All six files live together in one folder — they import each other, so
don't rename or separate them.

| File | Responsibility |
|---|---|
| `server.py` | entry point — binds the socket, accepts connections, hands each one to `connection.py` |
| `connection.py` | the actual hard part: buffers bytes, finds where one request ends and the next begins, and decides whether a connection can safely stay open after an error |
| `http_parser.py` | turns raw request bytes into a structured dict (method, path, query, headers) |
| `router.py` | pure logic — given a parsed request, decides the status code and body |
| `http_response.py` | formats a status code + body into raw HTTP/1.1 response bytes |
| `test_client.py` | opens one connection and runs 30+ checks against it |

## Requirements

Python 3.9+. No third-party packages — only the standard library
(`socket`, `threading`, `urllib.parse`).

## Running it

Start the server in one terminal:

```bash
python3 server.py 8080
```

You should see:

```
[server] listening on 0.0.0.0:8080
```

Run the test client in a second terminal, against the same port:

```bash
python3 test_client.py localhost 8080
```

Expected output ends with something like:

```
socket still open: True
30 passed, 0 failed
```

Or poke it by hand with curl while the server is running:

```bash
curl -v "http://localhost:8080/add?a=2&b=3"
```

Stop the server with Ctrl+C. If a port is already in use, just run it
again with a different port number.

## Design decisions

**Why does the connection stay open at all?**
HTTP/1.0 answered "where does a request end?" with "at EOF, because
we're about to close the socket." HTTP/1.1 gives that up for
performance, so the server has to work it out from the bytes
themselves: read until the blank line (`\r\n\r\n`) that ends the
headers, then, if there's a body, read *exactly* `Content-Length` more
bytes — not one byte more, since anything past that boundary belongs to
the next request on the same connection. `connection.py` keeps a
per-connection buffer specifically so leftover bytes (from a pipelined
request, or a body that arrived together with the next request's
headers) are never lost or misattributed.

**Check order in `router.py`:** method → path → Host → query params.
The assignment's own test cases don't force one particular order, so
this is a stated choice, not an accident:
- Method is checked first because this service supports exactly one
  method (`GET`) everywhere — "wrong verb" is a fact about the whole
  service, not about any specific resource.
- Path existence comes next, because `Host` and the query parameters
  are only meaningful once we know we're talking about a real resource.
- `Host` is only required when the request declares `HTTP/1.1` — that
  requirement didn't exist in HTTP/1.0.

**Framing errors vs. semantic errors close the connection differently.**
A 400 for "`a` isn't a number" or "division by zero" means the request
was read correctly and we simply disagreed with its content — the
bytes after it are still trustworthy, so the connection stays open. A
framing error (can't find the end of headers, a header line with no
colon, a garbage `Content-Length`) means we can no longer trust where
the current request actually ends, so there's no safe point to resume
from — the server replies `400` and closes.

**Extras beyond the minimum:**
- A per-connection idle timeout (30s) so a silent client doesn't hold a
  thread open forever.
- The server honors a client-sent `Connection: close` header.
- One thread per connection, so more than one real client can be
  connected at once. This doesn't change how any single connection is
  framed or answered — a single-threaded, blocking accept loop would
  pass the grading harness just as well, since it only ever opens one
  connection at a time.

## What `test_client.py` actually checks

Beyond the basic arithmetic and error cases, it specifically tests the
part of the assignment that's easy to get wrong:

- the connection survives a 400 and keeps answering afterward
- HTTP/1.0 requests are *not* required to send a `Host` header
- three requests sent back-to-back in a single write (pipelining) are
  each answered correctly, in order
- a request split across many small `send()` calls is still parsed
  correctly
- a POST body followed immediately by a fresh GET, in the same TCP
  write, doesn't let the server over-read into the next request — the
  "byte n+1 belongs to somebody else" case the assignment calls out
  explicitly

## Not implemented (out of scope for this assignment)

- Chunked transfer encoding — every response here has a body with a
  known length, so it was never needed.
