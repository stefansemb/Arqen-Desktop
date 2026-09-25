"""A tiny MCP server for tests: stdio when run as a program, HTTP via ``serve_http``."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = [
    {"name": "echo", "description": "Echoes text back.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "create.note", "description": "Creates a note.",
     "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}}},
]


def handle(message: dict) -> dict | None:
    if "id" not in message:
        return None  # a notification
    method, params = message.get("method"), message.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        arguments = params.get("arguments") or {}
        if params.get("name") == "echo":
            result = {"content": [{"type": "text", "text": f"echo: {arguments.get('text')}"}]}
        else:
            result = {"content": [{"type": "text", "text": "not allowed"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "unknown method"}}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def serve_stdio() -> None:
    print("fake server starting", flush=True)  # stdout noise a client must skip
    for line in sys.stdin:
        reply = handle(json.loads(line))
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


def serve_http(use_sse: bool, token: str = ""):
    seen_auth: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen_auth.append(self.headers.get("Authorization", ""))
            if token and self.headers.get("Authorization") != f"Bearer {token}":
                self.send_response(401)
                self.end_headers()
                return
            message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = handle(message)
            if reply is None:
                self.send_response(202)
                self.end_headers()
                return
            if use_sse:
                body = f"event: message\ndata: {json.dumps(reply)}\n\n".encode("utf-8")
                kind = "text/event-stream"
            else:
                body, kind = json.dumps(reply).encode("utf-8"), "application/json"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Mcp-Session-Id", "session-1")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen_auth


if __name__ == "__main__":
    serve_stdio()
