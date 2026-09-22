"""Where Arqen keeps its own files, and where the user's files live.

These used to be the same directory.  Everything resolved against the
process working directory, so the shortcut that started Arqen decided both
where its settings lived and which files the tools could reach -- and
pointing it somewhere else silently took the provider configuration, the
API keys and the chat history along with it.

They are two separate things now.  ``APP_ROOT`` follows the installation,
so Arqen finds its own files no matter where it was started from, and the
workspace the file tools work in is a setting the user chooses.
"""

from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]

_workspace_root: Path = APP_ROOT


def config_dir() -> Path:
    """The directory holding ``arqen.json`` and ``arqen-secrets.json``."""
    return APP_ROOT / "config"


def data_dir() -> Path:
    """The directory holding sessions, memory, undo history and generated files."""
    return APP_ROOT / "data"


def workspace_root() -> Path:
    """The only directory the file tools are allowed to work in."""
    return _workspace_root


def set_workspace_root(path: Path | str | None) -> Path:
    """Point the file tools at ``path`` and return what they ended up with.

    An empty, missing or unreadable path falls back to the app root rather
    than failing: a workspace that has been moved or unplugged should not
    stop Arqen from starting.
    """
    global _workspace_root
    if not path:
        _workspace_root = APP_ROOT
        return _workspace_root
    try:
        candidate = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        candidate = APP_ROOT
    _workspace_root = candidate if candidate.is_dir() else APP_ROOT
    return _workspace_root
