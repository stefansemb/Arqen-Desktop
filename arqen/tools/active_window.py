import ctypes
from ctypes import wintypes
from typing import Any

from arqen.tools.base import Tool


class ActiveWindowTool(Tool):
    name = "active_window"
    description = "Returns the title and process of the currently focused window on Windows."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        if not hasattr(ctypes, "windll"):
            return "Active window detection is currently supported on Windows only."

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "No active window detected."

        title_buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        title = title_buffer.value or "Untitled window"

        process_name = "unknown process"
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        try:
            import psutil

            process_name = psutil.Process(process_id.value).name()
        except Exception:
            pass
        return f"Window: {title} | Process: {process_name}"
