from datetime import datetime
from typing import Any

from arqen.tools.base import Tool


class CurrentTimeTool(Tool):
    name = "current_time"
    description = "Returns the current local date and time."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

