from typing import Any

from arqen.tools.base import Tool


class RunningProcessesTool(Tool):
    name = "running_processes"
    description = "Lists the most CPU-intensive running processes on the local computer."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("Process listing requires the psutil package") from exc

        import time
        cpu_count = psutil.cpu_count() or 1

        processes = list(psutil.process_iter(["name", "pid", "memory_percent"]))
        for process in processes:
            try:
                process.cpu_percent(None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(0.15)

        rows = []
        for process in processes:
            try:
                rows.append((
                    process.info["name"] or "unknown",
                    process.info["pid"],
                    process.cpu_percent(None) / cpu_count,
                    process.info["memory_percent"] or 0.0,
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        rows.sort(key=lambda row: max(row[2], row[3]), reverse=True)
        lines = [
            f"{name} (PID {pid}) | CPU: {cpu:.1f}% | Memory: {memory:.1f}%"
            for name, pid, cpu, memory in rows[:15]
        ]
        return "Running processes:\n" + "\n".join(lines) if lines else "No running processes found."
