import ctypes
from ctypes import wintypes
from typing import Any

from arqen.tools.base import Tool


class FocusWindowTool(Tool):
    name = "focus_window"
    description = "Brings a visible Windows window matching a title to the foreground."
    requires_confirmation = False
    arguments_schema = {"title": str}

    def run(self, arguments: dict[str, Any]) -> str:
        if not hasattr(ctypes, "windll"):
            return "Window focus is currently supported on Windows only."

        user32 = ctypes.windll.user32
        wanted = arguments["title"].strip().casefold()
        matches: list[tuple[int, str]] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            if wanted in title.casefold():
                matches.append((hwnd, title))
            return True

        user32.EnumWindows(callback_type(callback), 0)
        if not matches:
            return f"No visible window found matching: {arguments['title']}"
        hwnd, title = matches[0]
        user32.SetForegroundWindow(hwnd)
        return f"Focused window: {title}"
