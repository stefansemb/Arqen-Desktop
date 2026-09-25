"""Small JSON-over-HTTPS helper shared by the integrations.

Errors never include the URL: a Discord webhook or a Telegram bot address
carries its secret inside it.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TIMEOUT = 15


class ServiceError(RuntimeError):
    """A service answered with an error, or could not be reached."""


def request_json(method: str, url: str, headers: dict[str, str] | None = None, body: dict | None = None,
                 timeout: float = TIMEOUT):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=data, method=method, headers={
        "User-Agent": "Arqen",
        **({"Content-Type": "application/json"} if data is not None else {}),
        **(headers or {}),
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = payload.get("message") or payload.get("description") or ""
        except Exception:
            pass
        raise ServiceError(f"HTTP {exc.code}{': ' + detail if detail else ''}") from None
    except URLError as exc:
        raise ServiceError(f"Could not reach the service ({type(exc.reason).__name__}).") from None
    except TimeoutError:
        raise ServiceError("The service did not answer in time.") from None
    return json.loads(raw) if raw.strip() else None
