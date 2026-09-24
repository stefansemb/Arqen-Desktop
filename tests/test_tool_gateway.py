import json

from arqen.tools.base import Tool
from arqen.tools.executor import ToolExecutor
from arqen.tools.gateway import ToolGateway, ToolPolicy
from arqen.tools.registry import ToolRegistry


class EchoTool(Tool):
    name = "echo"
    description = "Echoes text"
    arguments_schema = {"text": str}

    def run(self, arguments):
        return arguments["text"]


def test_gateway_applies_policy_and_audits(tmp_path):
    registry = ToolRegistry()
    registry.register(EchoTool())
    audit = tmp_path / "audit.jsonl"
    gateway = ToolGateway(ToolExecutor(registry), audit)
    gateway.set_policy("scout", ToolPolicy(allowed_tools=frozenset()))

    result = gateway.execute("echo", {"text": "secret"}, agent="scout")
    assert not result.ok
    entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
    assert entry["tool"] == "echo"
    assert entry["status"] == "failed"
    assert "secret" not in audit.read_text(encoding="utf-8")


def test_gateway_exposes_catalogue_and_recent_audit(tmp_path):
    registry = ToolRegistry()
    registry.register(EchoTool())
    gateway = ToolGateway(ToolExecutor(registry), tmp_path / "audit.jsonl")
    gateway.execute("echo", {"text": "hello"})
    assert gateway.catalog()[0]["name"] == "echo"
    assert gateway.catalog()[0]["risk"] == "low"
    assert gateway.audit_entries(1)[0]["status"] == "ok"


def test_gateway_policy_view_is_safe():
    registry = ToolRegistry()
    registry.register(EchoTool())
    gateway = ToolGateway(ToolExecutor(registry))
    gateway.set_policy("scout", ToolPolicy(allowed_tools=frozenset({"echo"})))
    assert gateway.policy_view() == [{"agent": "scout", "allowed_tools": ["echo"], "denied_tools": []}]
