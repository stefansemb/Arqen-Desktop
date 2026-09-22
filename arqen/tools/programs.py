import shutil
import subprocess
import os
from pathlib import Path
from typing import Any

from arqen.tools.base import Tool


class LaunchProgramTool(Tool):
    name = "launch_program"
    description = "Starts a locally installed program found on the Windows PATH."
    requires_confirmation = False
    arguments_schema = {"program": str}

    def _resolve(self, program: str) -> str | None:
        name = program.strip().strip('"')
        found = shutil.which(name) or shutil.which(f"{name}.exe")
        if found:
            return found

        aliases = {
            "brave": "BraveSoftware\\Brave-Browser\\Application\\brave.exe",
            "chrome": "Google\\Chrome\\Application\\chrome.exe",
            "edge": "Microsoft\\Edge\\Application\\msedge.exe",
            "msedge": "Microsoft\\Edge\\Application\\msedge.exe",
        }
        relative = aliases.get(name.lower())
        if not relative:
            return None
        candidates = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / relative,
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / relative,
            Path(os.environ.get("LOCALAPPDATA", "")) / relative,
        ]
        return next((str(path) for path in candidates if path.is_file()), None)

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        if not self._resolve(arguments["program"]):
            return f"Program not found on PATH: {arguments['program']}"
        return None

    def run(self, arguments: dict[str, Any]) -> str:
        resolved = self._resolve(arguments["program"])
        if not resolved:
            raise FileNotFoundError(f"Program not found on PATH: {arguments['program']}")
        subprocess.Popen([resolved], close_fds=True)
        return f"Started: {resolved}"
