from typing import Any

from arqen.tools.base import Tool
from arqen.tools.speech import stop_speech


class StopSpeechTool(Tool):
    name = "stop_speech"
    description = "Stops current Arqen speech playback."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        stop_speech()
        return "Speech stopped."
