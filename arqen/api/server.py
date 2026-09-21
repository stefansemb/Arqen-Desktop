import json
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from arqen.application.service import ArqenApplication


class ArqenHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], application: ArqenApplication, token: str) -> None:
        super().__init__(server_address, ArqenRequestHandler)
        self.application = application
        self.token = token


class ArqenRequestHandler(BaseHTTPRequestHandler):
    server: ArqenHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path == "/":
                self._send_html(MOBILE_PAGE)
                return
            if path == "/api/v1/health":
                self._send_json(HTTPStatus.OK, {"data": {"status": "ok"}})
                return
            self._require_auth()
            if path == "/api/v1/status":
                self._send_json(HTTPStatus.OK, {"data": self._as_json(self.server.application.status())})
                return
            if path == "/api/v1/sessions":
                sessions = self.server.application.list_sessions()
                self._send_json(HTTPStatus.OK, {"data": [self._as_json(item) for item in sessions]})
                return
            if path.startswith("/api/v1/sessions/"):
                session_id = self._session_id(path)
                session = self.server.application.get_session(session_id)
                self._send_json(HTTPStatus.OK, {"data": self._as_json(session)})
                return
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Resursen finns inte.")
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Sessionen finns inte.")
        except PermissionError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, "unauthorized", str(exc))
        except Exception:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "Ett internt fel uppstod.")

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        try:
            self._require_auth()
            payload = self._read_json()
            if path == "/api/v1/sessions":
                result = self.server.application.create_session(str(payload.get("title", "Ny chatt")))
                self._send_json(HTTPStatus.CREATED, {"data": self._as_json(result)})
                return
            if path.endswith("/messages") and path.startswith("/api/v1/sessions/"):
                session_id = path.removeprefix("/api/v1/sessions/").removesuffix("/messages").strip("/")
                result = self.server.application.send_message(session_id, str(payload.get("content", "")))
                self._send_json(HTTPStatus.OK, {"data": self._as_json(result)})
                return
            if path == "/api/v1/voice/stop":
                self._send_json(HTTPStatus.OK, {"data": {"status": "stop_requested"}})
                return
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Resursen finns inte.")
        except ValueError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error", str(exc))
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Sessionen finns inte.")
        except PermissionError as exc:
            self._error(HTTPStatus.UNAUTHORIZED, "unauthorized", str(exc))
        except Exception:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "Ett internt fel uppstod.")

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        try:
            self._require_auth()
            if not path.startswith("/api/v1/sessions/"):
                self._error(HTTPStatus.NOT_FOUND, "not_found", "Resursen finns inte.")
                return
            payload = self._read_json()
            result = self.server.application.rename_session(self._session_id(path), str(payload.get("title", "")))
            self._send_json(HTTPStatus.OK, {"data": self._as_json(result)})
        except ValueError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error", str(exc))
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Sessionen finns inte.")
        except Exception:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "Ett internt fel uppstod.")

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        try:
            self._require_auth()
            self.server.application.delete_session(self._session_id(path))
            self._send_json(HTTPStatus.OK, {"data": {"status": "deleted"}})
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Sessionen finns inte.")
        except Exception:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "Ett internt fel uppstod.")

    def _require_auth(self) -> None:
        expected = self.server.token
        if not expected:
            return
        authorization = self.headers.get("Authorization", "")
        if authorization != f"Bearer {expected}":
            raise PermissionError("Giltig Bearer-token krävs.")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("JSON-body saknas eller är för stor.")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON-body måste vara ett objekt.")
        return payload

    def _session_id(self, path: str) -> str:
        value = path.removeprefix("/api/v1/sessions/").strip("/")
        if not value or "/" in value:
            raise FileNotFoundError(value)
        return value

    def _send_json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_html(self, html: str) -> None:
        encoded = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._send_json(status, {"error": {"code": code, "message": message}})

    @staticmethod
    def _as_json(value: Any) -> Any:
        if is_dataclass(value):
            result = asdict(value)
            if "messages" in result:
                result["messages"] = [ArqenRequestHandler._as_json(item) for item in value.messages]
            return result
        return value


def create_server(application: ArqenApplication, host: str = "127.0.0.1", port: int = 8765, token: str = "") -> ArqenHTTPServer:
    """Create a local API server; call serve_forever() from the host process."""
    return ArqenHTTPServer((host, port), application, token)


MOBILE_PAGE = r"""<!doctype html>
<html lang="sv">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#17191b">
<title>Arqen</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; background: #17191b; color: #d5d8d3; font: 16px system-ui, sans-serif; }
main { max-width: 720px; min-height: 100vh; margin: auto; padding: 20px 16px; display: flex; flex-direction: column; gap: 14px; }
h1 { margin: 0; color: #b7ff18; letter-spacing: .08em; font-size: 1.25rem; }
input, textarea, button { width: 100%; border: 1px solid #353a3d; border-radius: 8px; background: #202326; color: #eef1eb; padding: 12px; font: inherit; }
button { background: #b7ff18; color: #111; border: 0; font-weight: 700; }
textarea { min-height: 90px; resize: vertical; }
#log { flex: 1; min-height: 280px; white-space: pre-wrap; border: 1px solid #303538; border-radius: 8px; padding: 14px; background: #111315; overflow-wrap: anywhere; }
.muted { color: #8d9690; font-size: .9rem; }
</style>
</head>
<body><main>
<h1>ARQEN</h1>
<div class="muted">Mobiltest // lokal anslutning</div>
<input id="token" type="password" placeholder="API-token">
<button id="start">STARTA NY CHATT</button>
<div id="log">Ange token och starta en chatt.</div>
<textarea id="message" placeholder="Skriv ett meddelande..."></textarea>
<button id="send">SKICKA</button>
</main>
<script>
const token = document.querySelector('#token');
const log = document.querySelector('#log');
const message = document.querySelector('#message');
let sessionId = '';
const headers = () => ({'Authorization': 'Bearer ' + token.value, 'Content-Type': 'application/json'});
const write = text => { log.textContent += (log.textContent ? '\n\n' : '') + text; log.scrollTop = log.scrollHeight; };
document.querySelector('#start').onclick = async () => {
  const response = await fetch('/api/v1/sessions', {method: 'POST', headers: headers(), body: JSON.stringify({title: 'Mobilchatt'})});
  const body = await response.json();
  if (!response.ok) { write('Fel: ' + (body.error?.message || response.status)); return; }
  sessionId = body.data.session_id; log.textContent = 'Ny mobilchatt startad.';
};
document.querySelector('#send').onclick = async () => {
  if (!sessionId) { write('Starta en chatt först.'); return; }
  const content = message.value.trim(); if (!content) return;
  write('DU: ' + content); message.value = '';
  const response = await fetch('/api/v1/sessions/' + sessionId + '/messages', {method: 'POST', headers: headers(), body: JSON.stringify({content})});
  const body = await response.json();
  write(response.ok ? 'ARQEN: ' + body.data.assistant_message : 'Fel: ' + (body.error?.message || response.status));
};
</script></body></html>"""
