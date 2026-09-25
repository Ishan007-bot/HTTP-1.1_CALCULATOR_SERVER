"""
router.py
---------
Decides the status code + body for one already-framed, already-parsed
request. No socket code lives here — it's pure logic, easy to unit test
on its own.

Check order (this is a spec decision worth stating explicitly, since the
assignment's own test cases don't force one particular order):

    1. method allowed at all?        -> 405
    2. path a known operation?       -> 404
    3. Host header present?          -> 400   (only required for HTTP/1.1;
                                                 HTTP/1.0 never had this rule)
    4. a and b present and numeric?  -> 400
    5. division by zero?             -> 400
    6. compute                       -> 200

Method is checked before path because this service has exactly one
supported method (GET) for every route it has — "you used the wrong verb"
is a blanket fact about the service, not something specific to the
resource. Path existence is checked next because Host and the query
params are only meaningful once we know we're talking about a real
resource at all.
"""

SUPPORTED_METHODS = {"GET"}
SUPPORTED_PATHS = {"/add", "/sub", "/mul", "/div"}


def route(request: dict) -> tuple[int, str]:
    method = request["method"]
    path = request["path"]
    query = request["query"]
    headers = request["headers"]
    version = request["version"]

    if method not in SUPPORTED_METHODS:
        return 405, f"method not allowed: {method}"

    if path not in SUPPORTED_PATHS:
        return 404, f"no such operation: {path}"

    if version == "HTTP/1.1" and "host" not in headers:
        return 400, "missing Host header"

    if "a" not in query or "b" not in query:
        return 400, "missing query parameter(s): a and/or b"

    a = _parse_number(query["a"])
    if a is None:
        return 400, f"non-numeric value for a: {query['a']!r}"

    b = _parse_number(query["b"])
    if b is None:
        return 400, f"non-numeric value for b: {query['b']!r}"

    if path == "/div" and b == 0:
        return 400, "division by zero"

    result = {
        "/add": lambda: a + b,
        "/sub": lambda: a - b,
        "/mul": lambda: a * b,
        "/div": lambda: a / b,
    }[path]()

    return 200, _format_number(result)


def _parse_number(raw: str):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _format_number(n) -> str:
    """Print 5 instead of 5.0, but keep real decimals when they matter."""
    if float(n).is_integer():
        return str(int(n))
    return str(n)
