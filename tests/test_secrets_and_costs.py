"""Keys stay out of tool output and the key file, and tool costs reach the audit log."""

import base64
import json

import pytest

from arqen.config import secrets
from arqen.tools import image_generation
from arqen.tools.base import Tool
from arqen.tools.costs import report_cost
from arqen.tools.executor import ToolExecutor
from arqen.tools.gateway import ToolGateway
from arqen.tools.registry import ToolRegistry
from arqen.tools.workspace_files import ReadWorkspaceFileTool, SearchWorkspaceContentTool, WriteWorkspaceFileTool

OPENROUTER_KEY = "sk-or-v1-abcdef123456"


def _store_keys() -> None:
    path = secrets.secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "providers": {"openrouter": OPENROUTER_KEY, "ollama": ""},
        "connectors": {"github": {"token": "ghp_testtoken123"}},
    }), encoding="utf-8")


class LeakyTool(Tool):
    name = "leaky"
    description = "Echoes text"
    arguments_schema = {"text": str}

    def run(self, arguments):
        return arguments["text"]


class PaidTool(Tool):
    name = "paid"
    description = "Costs money"
    requires_confirmation = True

    def run(self, arguments):
        report_cost(0.04)
        report_cost("0.01")
        report_cost(None)  # a service that did not say what it cost
        return "done"


def _gateway(tmp_path, *tools):
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolGateway(ToolExecutor(registry), tmp_path / "audit.jsonl")


def test_provider_keys_come_from_one_place():
    _store_keys()
    assert secrets.provider_key("openrouter") == OPENROUTER_KEY
    assert LeakyTool().provider_key("openrouter") == OPENROUTER_KEY
    assert secrets.provider_key("gemini") == ""
    assert OPENROUTER_KEY in secrets.secret_values() and "ghp_testtoken123" in secrets.secret_values()


def test_the_gateway_scrubs_model_provider_keys_too(tmp_path):
    _store_keys()
    gateway = _gateway(tmp_path, LeakyTool())
    result = gateway.execute("leaky", {"text": f"key={OPENROUTER_KEY} token=ghp_testtoken123"})
    assert result.output == "key=•••• token=••••"


def test_file_tools_cannot_reach_the_key_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the workspace holds config/, as the app folder does
    _store_keys()
    (tmp_path / "backup").mkdir()
    (tmp_path / "backup" / "arqen-secrets.json").write_text(json.dumps({"api_key": "copied-key-999"}), encoding="utf-8")

    for path in ("config/arqen-secrets.json", "backup/arqen-secrets.json", "config/../config/arqen-secrets.json"):
        with pytest.raises(PermissionError, match="key file"):
            ReadWorkspaceFileTool().run({"path": path})
    with pytest.raises(PermissionError):
        WriteWorkspaceFileTool().run({"path": "config/arqen-secrets.json", "content": "{}"})
    assert "arqen-secrets" not in SearchWorkspaceContentTool().run({"query": "sk-or"})


def test_a_reported_cost_lands_in_the_audit_log(tmp_path):
    gateway = _gateway(tmp_path, PaidTool(), LeakyTool())

    assert gateway.execute("paid", {}).confirmation_required
    gateway.confirm_pending(True)
    gateway.execute("leaky", {"text": "free"})

    approval, paid, free = gateway.audit_entries()
    assert "cost_usd" not in approval
    assert paid["cost_usd"] == 0.05
    assert "cost_usd" not in free


def test_a_cost_outside_the_gateway_goes_nowhere():
    report_cost(1.0)  # no gateway call is collecting; must not raise


def test_generated_images_log_openrouters_own_cost(tmp_path, monkeypatch):
    _store_keys()
    sent = {}

    class Response:
        def read(self):
            return json.dumps({
                "data": [{"b64_json": base64.b64encode(b"png").decode()}],
                "usage": {"cost": 0.039},
            }).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        sent["auth"] = request.get_header("Authorization")
        return Response()

    monkeypatch.setattr(image_generation, "urlopen", fake_urlopen)
    gateway = _gateway(tmp_path, image_generation.GenerateImageTool())

    gateway.execute("generate_image", {"prompt": "en röd panda"})
    result = gateway.confirm_pending(True)

    assert result.ok and "arqen-image-" in result.output
    assert sent["auth"] == f"Bearer {OPENROUTER_KEY}"
    assert gateway.audit_entries()[-1]["cost_usd"] == 0.039
    assert OPENROUTER_KEY not in gateway.audit_path.read_text(encoding="utf-8")
