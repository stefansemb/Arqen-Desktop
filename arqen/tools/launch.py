import os
from pathlib import Path
from typing import Any

from arqen.tools.base import Tool


class LaunchPathTool(Tool):
    name = "launch_path"
    description = "Opens an existing local file or folder with the Windows default application."
    requires_confirmation = False
    arguments_schema = {"path": str}

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        target = Path(arguments["path"]).expanduser()
        if not target.exists():
            return f"Path not found: {target}"
        return None

    def run(self, arguments: dict[str, Any]) -> str:
        target = Path(arguments["path"]).expanduser().resolve()
        os.startfile(str(target))
        return f"Opened: {target}"
