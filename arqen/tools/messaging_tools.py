from typing import Any

from arqen.connectors.messaging import discord_send, telegram_send
from arqen.tools.base import Tool


class _SendTool(Tool):
    # A message leaves the computer and cannot be taken back.
    requires_confirmation = True
    arguments_schema = {"text": str}

    def preflight(self, arguments: dict[str, Any]) -> str | None:
        return None if str(arguments["text"]).strip() else "The message is empty."


class DiscordSendMessageTool(_SendTool):
    name = "discord_send_message"
    description = "Sends a message to the user's connected Discord channel."
    connector_id = "discord"

    def run(self, arguments: dict[str, Any]) -> str:
        discord_send(self.credentials(), str(arguments["text"]))
        return "Message sent to Discord."


class TelegramSendMessageTool(_SendTool):
    name = "telegram_send_message"
    description = "Sends a message to the user through their connected Telegram bot."
    connector_id = "telegram"

    def run(self, arguments: dict[str, Any]) -> str:
        telegram_send(self.credentials(), str(arguments["text"]))
        return "Message sent to Telegram."
