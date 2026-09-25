"""A small MCP (Model Context Protocol) client: Streamable HTTP and stdio.

Only what Arqen needs: initialize, list tools and call a tool.  Every
operation opens its own short session, which keeps the client stateless and
means a restarted or flaky server simply works on the next call.
"""

from __future__ import annotations

import json
import os
import queue
import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from arqen.connectors.http import ServiceError

PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "Arqen", "version": "1.0"}
TIMEOUT = 30


@dataclass(frozen=True)
class McpToolSpec:
    name: str
    description: str
    input_schema: dict
    read_only: bool

    def to_json(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema, "read_only": self.read_only}

    @classmethod
    def from_json(cls, data: dict) -> "McpToolSpec":
        return cls(str(data["name"]), str(data.get("description", "")),
                   dict(data.get("input_schema") or {"type": "object", "properties": {}}),
                   bool(data.get("read_only", False)))


def _spec(tool: dict) -> McpToolSpec:
    annotations = tool.get("annotations") or {}
    schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
    return McpToolSpec(str(tool["name"]), str(tool.get("description") or tool.get("title") or ""),
                       schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
                       bool(annotations.get("readOnlyHint", False)))


def result_text(result: dict) -> str:
    """The readable part of a tools/call result."""
    parts = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "resource":
            resource = item.get("resource") or {}
            parts.append(str(resource.get("text") or f"[resource {resource.get('uri', '')}]"))
        else:
            parts.append(f"[{kind} content]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    text = "\n".join(parts).strip() or "(no content)"
    if result.get("isError"):
        raise ServiceError(text[:500])
    return text


class _Session:
    """JSON-RPC over one transport; subclasses implement ``_send``."""

    def __init__(self) -> None:
        self._next_id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}}
        reply = self._send(message, expect_reply=True)
        if reply is None:
            raise ServiceError(f"The MCP server did not answer {method}.")
        if "error" in reply:
            error = reply["error"] or {}
            raise ServiceError(f"MCP error {error.get('code', '')}: {error.get('message', '')}".strip())
        return reply.get("result") or {}

    def notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method}, expect_reply=False)

    def open(self) -> dict:
        info = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO,
        })
        self.notify("notifications/initialized")
        return info

    def list_tools(self) -> list[McpToolSpec]:
        tools, cursor = [], None
        for _ in range(20):  # pagination, with a ceiling
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(_spec(tool) for tool in result.get("tools") or [] if tool.get("name"))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call(self, name: str, arguments: dict) -> str:
        return result_text(self.request("tools/call", {"name": name, "arguments": arguments}))

    def close(self) -> None:
        pass

    def _send(self, message: dict, expect_reply: bool) -> dict | None:
        raise NotImplementedError


class HttpSession(_Session):
    """Streamable HTTP: POST JSON-RPC, answered with JSON or a short SSE stream."""

    def __init__(self, url: str, token: str = "") -> None:
        super().__init__()
        if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ServiceError("Use an https:// address (plain http only for this computer).")
        self.url, self.token, self.session_id = url, token, None

    def _send(self, message: dict, expect_reply: bool) -> dict | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL_VERSION, "User-Agent": "Arqen"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = Request(self.url, data=json.dumps(message).encode("utf-8"), method="POST", headers=headers)
        try:
            with urlopen(request, timeout=TIMEOUT) as response:
                self.session_id = response.headers.get("Mcp-Session-Id") or self.session_id
                kind = response.headers.get("Content-Type", "")
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raise ServiceError(f"HTTP {exc.code} from the MCP server.") from None
        except URLError as exc:
            raise ServiceError(f"Could not reach the MCP server ({type(exc.reason).__name__}).") from None
        except TimeoutError:
            raise ServiceError("The MCP server did not answer in time.") from None
        if not expect_reply or not raw.strip():
            return None
        if "text/event-stream" in kind:
            return _from_sse(raw, message.get("id"))
        reply = json.loads(raw)
        if isinstance(reply, list):  # a batch; pick ours
            reply = next((item for item in reply if item.get("id") == message.get("id")), None)
        return reply


def _from_sse(raw: str, wanted_id) -> dict | None:
    """The JSON-RPC reply with ``wanted_id`` from a server-sent event stream."""
    data: list[str] = []
    for line in raw.splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            try:
                event = json.loads("\n".join(data))
            except json.JSONDecodeError:
                event = None
            data = []
            if isinstance(event, dict) and event.get("id") == wanted_id:
                return event
    return None


class StdioSession(_Session):
    """A local MCP server started as a program, speaking JSON lines on stdin/stdout."""

    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> None:
        super().__init__()
        executable = shutil.which(command) or command
        try:
            self.process = subprocess.Popen(
                [executable, *(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
                env={**os.environ, **(env or {})},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise ServiceError(f"Could not start {command}: {exc.strerror or exc}") from None
        self.lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True, name="arqen-mcp-stdio").start()

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _send(self, message: dict, expect_reply: bool) -> dict | None:
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except OSError:
            raise ServiceError("The MCP program closed unexpectedly.") from None
        if not expect_reply:
            return None
        while True:
            try:
                line = self.lines.get(timeout=TIMEOUT)
            except queue.Empty:
                raise ServiceError("The MCP program did not answer in time.") from None
            if line is None:
                raise ServiceError("The MCP program exited before answering.")
            try:
                reply = json.loads(line)
            except json.JSONDecodeError:
                continue  # logging on stdout; skip it
            if isinstance(reply, dict) and reply.get("id") == message["id"] and "method" not in reply:
                return reply

    def close(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=3)
        except Exception:
            self.process.kill()


def open_session(server: dict, token: str = "") -> _Session:
    if server.get("transport") == "stdio":
        # posix=False keeps Windows backslashes; the quotes it leaves are removed.
        args = [part.strip('"') for part in shlex.split(str(server.get("args", "")), posix=False)]
        return StdioSession(str(server.get("command", "")), args)
    return HttpSession(str(server.get("url", "")), token)


def with_session(server: dict, token: str, work):
    """Open, initialize, run ``work(session)`` and always close."""
    session = open_session(server, token)
    try:
        session.open()
        return work(session)
    finally:
        session.close()
