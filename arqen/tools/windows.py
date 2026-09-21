import ctypes
from ctypes import wintypes
from typing import Any

from arqen.tools.base import Tool


class OpenWindowsTool(Tool):
    name = "open_windows"
    description = "Lists visible top-level windows on Windows."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        if not hasattr(ctypes, "windll"):
            return "Window listing is currently supported on Windows only."

        user32 = ctypes.windll.user32
        rows: list[str] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            title_buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, length + 1)
            rows.append(f"{title_buffer.value} (HWND {hwnd})")
            return True

        user32.EnumWindows(callback_type(callback), 0)
        return "Open windows:\n" + "\n".join(rows[:50]) if rows else "No visible windows found."
