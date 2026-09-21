from typing import Any

from arqen.tools.base import Tool


class SystemResourcesTool(Tool):
    name = "system_resources"
    description = "Returns current CPU and memory usage of the local computer."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("System resources require the psutil package") from exc

        cpu = psutil.cpu_percent(interval=0.2)
        memory = psutil.virtual_memory()
        return f"CPU: {cpu:.1f}% | Memory: {memory.percent:.1f}% used"

