"""Small JSON-over-HTTPS helper shared by the integrations.

Errors never include the URL: a Discord webhook or a Telegram bot address
carries its secret inside it.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TIMEOUT = 15


class ServiceError(RuntimeError):
    """A service answered with an error, or could not be reached."""


def _error_detail(raw: bytes) -> str:
    """The readable part of an error body, in the shapes the services use."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        # Google APIs: {"error": {"code": 403, "message": "..."}}
        return str(error.get("message") or "")
    if isinstance(error, str):
        # OAuth token endpoint: {"error": "invalid_grant", "error_description": "..."}
        description = payload.get("error_description")
        return f"{error}: {description}" if description else error
    return str(payload.get("message") or payload.get("description") or "")


def request_bytes(method: str, url: str, headers: dict[str, str] | None = None, body: dict | None = None,
                  form: dict[str, str] | None = None, timeout: float = TIMEOUT,
                  max_bytes: int | None = None) -> bytes:
    """Send a request and return the raw answer.

    ``body`` is sent as JSON, ``form`` as an HTML form; ``max_bytes`` stops
    reading a large download early.
    """
    if form is not None:
        data, content_type = urlencode(form).encode("utf-8"), "application/x-www-form-urlencoded"
    elif body is not None:
        data, content_type = json.dumps(body).encode("utf-8"), "application/json"
    else:
        data, content_type = None, None
    request = Request(url, data=data, method=method, headers={
        "User-Agent": "Arqen",
        **({"Content-Type": content_type} if content_type else {}),
        **(headers or {}),
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read() if max_bytes is None else response.read(max_bytes)
    except HTTPError as exc:
        detail = _error_detail(exc.read())
        raise ServiceError(f"HTTP {exc.code}{': ' + detail if detail else ''}") from None
    except URLError as exc:
        raise ServiceError(f"Could not reach the service ({type(exc.reason).__name__}).") from None
    except TimeoutError:
        raise ServiceError("The service did not answer in time.") from None


def request_json(method: str, url: str, headers: dict[str, str] | None = None, body: dict | None = None,
                 form: dict[str, str] | None = None, timeout: float = TIMEOUT):
    raw = request_bytes(method, url, headers=headers, body=body, form=form, timeout=timeout).decode("utf-8")
    return json.loads(raw) if raw.strip() else None
