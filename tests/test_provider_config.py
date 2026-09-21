import json

from arqen.config.settings import load_provider_config
from arqen.providers.config import ProviderConfig
from arqen.providers.factory import create_provider
from arqen.providers.local import LocalProvider


def test_missing_config_uses_local_defaults(tmp_path) -> None:
    config = load_provider_config(tmp_path / "missing.json")
    assert config.name == "local"
    assert isinstance(create_provider(config), LocalProvider)


def test_config_can_select_demo(tmp_path) -> None:
    path = tmp_path / "arqen.json"
    path.write_text(json.dumps({"provider": {"name": "demo"}}), encoding="utf-8")
    config = load_provider_config(path)
    assert config == ProviderConfig(name="demo")
