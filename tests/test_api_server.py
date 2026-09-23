import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from arqen.api.server import create_server
from arqen.application.service import ArqenApplication
from arqen.core.engine import ConversationEngine
from arqen.core.session_store import SessionStore
from arqen.providers.demo import DemoProvider


def make_server(tmp_path: Path):
    app = ArqenApplication(lambda: ConversationEngine(DemoProvider()), SessionStore(tmp_path / "sessions"))
    server = create_server(app, port=0, token="test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def request(server, method: str, path: str, body: dict | None = None, token: str = "test-token"):
    connection = HTTPConnection("127.0.0.1", server.server_port)
    headers = {"Authorization": f"Bearer {token}"}
    encoded = None
    if body is not None:
        encoded = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(encoded))
    connection.request(method, path, encoded, headers)
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, payload


def test_api_health_does_not_require_auth(tmp_path: Path) -> None:
    server, thread = make_server(tmp_path)
    try:
        status, payload = request(server, "GET", "/api/v1/health", token="")
        assert status == 200
        assert payload["data"]["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_api_creates_session_and_sends_message(tmp_path: Path) -> None:
    server, thread = make_server(tmp_path)
    try:
        status, created = request(server, "POST", "/api/v1/sessions", {"title": "Mobiltest"})
        session_id = created["data"]["session_id"]
        assert status == 201
        status, result = request(server, "POST", f"/api/v1/sessions/{session_id}/messages", {"content": "Hej Arqen"})
        assert status == 200
        assert result["data"]["assistant_message"] == "Jag tog emot: Hej Arqen"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_api_rejects_missing_token(tmp_path: Path) -> None:
    server, thread = make_server(tmp_path)
    try:
        status, payload = request(server, "GET", "/api/v1/status", token="wrong")
        assert status == 401
        assert payload["error"]["code"] == "unauthorized"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_api_creates_reads_and_runs_mission_task(tmp_path: Path) -> None:
    server, thread = make_server(tmp_path)
    try:
        status, created = request(server, "POST", "/api/v1/mission/tasks", {"title": "Test", "prompt": "Hej"})
        assert status == 201
        task_id = created["data"]["id"]
        status, result = request(server, "POST", f"/api/v1/mission/tasks/{task_id}/run", {})
        assert status == 200
        assert result["data"]["result"] == "Jag tog emot: Hej"
        status, details = request(server, "GET", f"/api/v1/mission/tasks/{task_id}")
        assert status == 200
        assert details["data"]["task"]["status"] == "completed"
        assert [event["kind"] for event in details["data"]["events"]] == ["created", "started", "completed"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
