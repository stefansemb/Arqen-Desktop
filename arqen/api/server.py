import json
import glob
import os
import shutil
import subprocess
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from arqen.application.service import ArqenApplication
from arqen.config import paths
from arqen.mission import Approval, Event, MissionRunner, MissionStore, Task


class ArqenHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], application: ArqenApplication, token: str) -> None:
        super().__init__(server_address, ArqenRequestHandler)
        self.application = application
        self.token = token
        self.mission_store = MissionStore(paths.data_dir() / "mission.sqlite3")
        self.mission_runner = MissionRunner(self.mission_store, application._engine_factory)


class ArqenRequestHandler(BaseHTTPRequestHandler):
    server: ArqenHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path == "/":
                self._send_html(MOBILE_PAGE)
                return
            if path == "/control":
                self._send_html(CONTROL_PAGE)
                return
            if path == "/api/v1/health":
                self._send_json(HTTPStatus.OK, {"data": {"status": "ok"}})
                return
            self._require_auth()
            if path == "/api/v1/status":
                self._send_json(HTTPStatus.OK, {"data": self._as_json(self.server.application.status())})
                return
            if path == "/api/v1/control/status":
                self._send_json(HTTPStatus.OK, {"data": self._control_status()})
                return
            if path == "/api/v1/mission/tasks":
                tasks = self.server.mission_store.list_tasks()
                self._send_json(HTTPStatus.OK, {"data": [self._as_json(item) for item in tasks]})
                return
            if path == "/api/v1/mission/agents":
                agents = self.server.mission_store.list_agents()
                data = []
                for agent in agents:
                    item = self._as_json(agent)
                    item["runtime_status"] = self.server.mission_runner.runtime_status(agent.id)
                    data.append(item)
                self._send_json(HTTPStatus.OK, {"data": data})
                return
            if path == "/api/v1/mission/approvals":
                approvals = self.server.mission_store.list_approvals()
                self._send_json(HTTPStatus.OK, {"data": [self._as_json(item) for item in approvals]})
                return
            if path.startswith("/api/v1/mission/tasks/"):
                task_id = path.removeprefix("/api/v1/mission/tasks/").strip("/")
                if not task_id or "/" in task_id:
                    raise FileNotFoundError(task_id)
                task = self.server.mission_store.get_task(task_id)
                if task is None:
                    raise FileNotFoundError(task_id)
                self._send_json(HTTPStatus.OK, {"data": {"task": self._as_json(task), "events": self._as_json(self.server.mission_store.list_events(task_id))}})
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
            if path == "/api/v1/mission/tasks":
                title = str(payload.get("title", "")).strip()
                prompt = str(payload.get("prompt", "")).strip()
                if not title or not prompt:
                    raise ValueError("title och prompt krävs.")
                task = Task.create(title, prompt, payload.get("agent_id"))
                self.server.mission_store.save_task(task)
                self.server.mission_store.add_event(Event.create(task.id, "created", "Task created"))
                self._send_json(HTTPStatus.CREATED, {"data": self._as_json(task)})
                return
            if path == "/api/v1/mission/agents":
                agent_id = str(payload.get("id", "")).strip()
                name = str(payload.get("name", "")).strip()
                role = str(payload.get("role", "")).strip()
                if not agent_id or not name or not role:
                    raise ValueError("id, name och role krävs.")
                from arqen.mission import Agent
                agent = Agent(agent_id, name, role, str(payload.get("runtime", "arqen")), bool(payload.get("enabled", True)))
                self.server.mission_store.save_agent(agent)
                self._send_json(HTTPStatus.CREATED, {"data": self._as_json(agent)})
                return
            if path == "/api/v1/mission/approvals":
                task_id = str(payload.get("task_id", "")).strip()
                action = str(payload.get("action", "")).strip()
                if not task_id or not action:
                    raise ValueError("task_id och action krävs.")
                approval = Approval(__import__("uuid").uuid4().hex, task_id, action, dict(payload.get("payload", {})))
                self.server.mission_store.save_approval(approval)
                self._send_json(HTTPStatus.CREATED, {"data": self._as_json(approval)})
                return
            if path.startswith("/api/v1/mission/approvals/") and path.endswith("/decision"):
                approval_id = path.removeprefix("/api/v1/mission/approvals/").removesuffix("/decision").strip("/")
                self.server.mission_store.decide_approval(approval_id, str(payload.get("status", "")))
                approval = self.server.mission_store.get_approval(approval_id)
                if approval is None:
                    raise FileNotFoundError(approval_id)
                self._send_json(HTTPStatus.OK, {"data": self._as_json(approval)})
                return
            if path.endswith("/run") and path.startswith("/api/v1/mission/tasks/"):
                task_id = path.removeprefix("/api/v1/mission/tasks/").removesuffix("/run").strip("/")
                result = self.server.mission_runner.run(task_id)
                self._send_json(HTTPStatus.OK, {"data": {"task_id": task_id, "result": result}})
                return
            if path.endswith("/resume") and path.startswith("/api/v1/mission/tasks/"):
                task_id = path.removeprefix("/api/v1/mission/tasks/").removesuffix("/resume").strip("/")
                result = self.server.mission_runner.resume(task_id)
                self._send_json(HTTPStatus.OK, {"data": {"task_id": task_id, "result": result}})
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

    def _control_status(self) -> dict[str, Any]:
        disk = shutil.disk_usage("/")
        memory = "unknown"
        try:
            memory = subprocess.check_output(["free", "-h"], text=True, timeout=2).splitlines()[1].split()[2]
        except (OSError, IndexError, subprocess.SubprocessError):
            pass
        try:
            ollama = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=3).stdout.strip()
            ollama_status = "online" if ollama else "idle"
        except (OSError, subprocess.SubprocessError):
            ollama_status = "offline"
        timer_status = "unknown"
        last_health = "unknown"
        try:
            timer_status = subprocess.run(
                ["systemctl", "is-active", "arqen-healthcheck.timer"],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip() or "inactive"
            last_health = subprocess.run(
                ["journalctl", "-t", "arqen-health", "-n", "1", "--no-pager", "-o", "cat"],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            pass
        status = self._as_json(self.server.application.status())
        backups = sorted(glob.glob("/var/backups/arqen/arqen-*.tar.gz"), reverse=True)
        backup_age = "unknown"
        if backups:
            backup_age = f"{round((__import__('time').time() - os.path.getmtime(backups[0])) / 3600, 1)} h"
        return {"api": "online", "model": status.get("model", ""), "ollama": ollama_status,
                "memory_used": memory, "disk_used_percent": round(disk.used / disk.total * 100),
                "sessions": len(self.server.application.list_sessions()), "healthcheck": timer_status,
                "last_health": last_health, "telegram": "configured" if os.path.exists("/etc/arqen-telegram.env") else "not configured",
                "latest_backup": os.path.basename(backups[0]) if backups else "none", "backup_age": backup_age}

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
        if isinstance(value, list):
            return [ArqenRequestHandler._as_json(item) for item in value]
        if isinstance(value, dict):
            return {key: ArqenRequestHandler._as_json(item) for key, item in value.items()}
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


CONTROL_PAGE = r"""<!doctype html><html lang="sv"><head>
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Arqen Control</title>
<style>*{box-sizing:border-box}body{margin:0;background:#101214;color:#e9eee8;font:16px system-ui,sans-serif}main{max-width:980px;margin:auto;padding:28px 18px}h1{color:#b7ff18;letter-spacing:.1em}input,button{padding:12px;border:1px solid #343b37;border-radius:8px;background:#1d2220;color:#fff;font:inherit}input{width:70%}button{background:#b7ff18;color:#101214;font-weight:700;cursor:pointer}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-top:22px}.card{background:#191d1b;border:1px solid #303832;border-radius:12px;padding:18px}.label{color:#89958c;font-size:.85rem}.value{font-size:1.35rem;margin-top:7px;color:#b7ff18}#message{margin-top:18px;color:#aab5ad}</style></head>
<body><main><h1>ARQEN CONTROL</h1><p>VPS-status och driftöversikt</p><input id="token" type="password" placeholder="API-token"><button onclick="loadStatus()">ANSLUT</button><div id="message">Ange token för att läsa status.</div><section class="grid" id="grid"></section></main>
<script>async function loadStatus(){const token=document.getElementById('token').value;try{const r=await fetch('/api/v1/control/status',{headers:{Authorization:'Bearer '+token}});const j=await r.json();if(!r.ok)throw Error(j.error?.message||'Fel');const d=j.data;const rows=[['API',d.api],['Ollama',d.ollama],['Modell',d.model],['RAM använd',d.memory_used],['Disk',d.disk_used_percent+'%'],['Sessioner',d.sessions],['Healthcheck',d.healthcheck],['Telegram',d.telegram],['Backup',d.latest_backup],['Backupålder',d.backup_age],['Senaste kontroll',d.last_health]];document.getElementById('grid').innerHTML=rows.map(x=>'<div class="card"><div class="label">'+x[0]+'</div><div class="value">'+x[1]+'</div></div>').join('');document.getElementById('message').textContent='Senast uppdaterad: '+new Date().toLocaleTimeString()}catch(e){document.getElementById('message').textContent=e.message}}setInterval(()=>{if(document.getElementById('token').value)loadStatus()},30000)</script></body></html>"""
