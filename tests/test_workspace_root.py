import json
from pathlib import Path

from arqen.config import paths
from arqen.config.paths import APP_ROOT, set_workspace_root
from arqen.config.settings import (
    load_provider_config,
    load_workspace_root,
    save_provider_config,
    save_workspace_root,
)
from arqen.providers.config import ProviderConfig
from arqen.tools.registry import ToolRegistry
from arqen.tools.workspace_files import ReadWorkspaceFileTool, WorkspaceFilesTool


def test_settings_survive_being_started_from_another_directory(tmp_path, monkeypatch) -> None:
    """The shortcut's start folder used to decide whether Arqen found its config.

    Started elsewhere it fell back to the defaults, so a configured cloud
    provider quietly turned back into local Ollama with no key.
    """
    from_app_root = load_provider_config()
    monkeypatch.chdir(tmp_path)
    assert load_provider_config() == from_app_root


def test_config_and_data_follow_the_installation_not_the_cwd(tmp_path, monkeypatch) -> None:
    # conftest redirects data_dir so tests stay out of the real app data.
    # This one is about the production behaviour, so it drops that first.
    monkeypatch.undo()
    monkeypatch.chdir(tmp_path)
    assert paths.config_dir() == APP_ROOT / "config"
    assert paths.data_dir() == APP_ROOT / "data"


def test_the_tools_work_in_the_chosen_workspace(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "arbetsyta"
    workspace.mkdir()
    (workspace / "anteckning.txt").write_text("hej", encoding="utf-8")
    elsewhere = tmp_path / "annanstans"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(paths, "workspace_root", lambda: workspace)

    assert "anteckning.txt" in WorkspaceFilesTool().run({})
    assert ReadWorkspaceFileTool().run({"path": "anteckning.txt"}) == "hej"


def test_an_unusable_workspace_falls_back_to_the_app_root(tmp_path) -> None:
    assert set_workspace_root(tmp_path / "finns-inte") == APP_ROOT
    assert set_workspace_root("") == APP_ROOT
    assert set_workspace_root(tmp_path) == tmp_path.resolve()
    set_workspace_root(None)


def test_saving_a_provider_keeps_the_chosen_workspace(tmp_path) -> None:
    config_path = tmp_path / "arqen.json"
    workspace = tmp_path / "arbetsyta"
    workspace.mkdir()
    save_workspace_root(workspace, config_path)
    assert load_workspace_root(config_path) == workspace.resolve()

    save_provider_config(ProviderConfig(name="openrouter", model="m"), config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert Path(saved["workspace"]) == workspace.resolve(), "a provider save must not reset the workspace"
    set_workspace_root(None)
