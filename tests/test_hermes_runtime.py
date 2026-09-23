import subprocess

import pytest

from arqen.mission import HermesRuntime


def test_hermes_runtime_uses_argument_list_without_shell(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="klart\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert HermesRuntime("hermes", "C:/agents", 12).run("gör jobbet") == "klart"
    assert calls[0][0] == ["hermes", "gör jobbet"]
    assert calls[0][1]["shell"] is False


def test_hermes_runtime_reports_process_errors(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 2, stdout="", stderr="bad config")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="bad config"):
        HermesRuntime("hermes").run("test")


def test_hermes_runtime_health_reports_ready(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "Hermes 1", ""))
    assert HermesRuntime("hermes").health() == {"status": "ready", "detail": "Hermes 1"}
