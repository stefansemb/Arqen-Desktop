from typing import Any

from arqen.tools.base import Tool


class CloseProgramTool(Tool):
    name = "close_program"
    description = "Terminates one running local process by PID or exact process name."
    requires_confirmation = False
    arguments_schema = {"target": str}

    def _matches(self, target: str):
        import psutil

        target = target.strip()
        if target.isdigit():
            try:
                process = psutil.Process(int(target))
                return [process]
            except psutil.NoSuchProcess:
                return []
        normalized = target.casefold()
        if normalized.endswith(".exe"):
            normalized = normalized[:-4]
        return [
            process for process in psutil.process_iter(["name"])
            if (process.info.get("name") or "").casefold().removesuffix(".exe") == normalized
        ]

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        matches = self._matches(arguments["target"])
        if not matches:
            return f"Running process not found: {arguments['target']}"
        if len(matches) > 1 and not arguments["target"].strip().isdigit():
            pids = ", ".join(str(process.pid) for process in matches)
            return f"Multiple processes found for {arguments['target']}. Use a PID: {pids}"
        return None

    def run(self, arguments: dict[str, Any]) -> str:
        matches = self._matches(arguments["target"])
        if not matches:
            raise RuntimeError(f"Running process not found: {arguments['target']}")
        process = matches[0]
        pid = process.pid
        process.terminate()
        return f"Termination requested for PID {pid} ({process.name()})"
