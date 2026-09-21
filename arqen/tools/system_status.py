import platform
import sys
from typing import Any

from arqen.tools.base import Tool


class SystemStatusTool(Tool):
    name = "system_status"
    description = "Returns basic local operating system and Python runtime information."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        return (
            f"OS: {platform.system()} {platform.release()} | "
            f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )

