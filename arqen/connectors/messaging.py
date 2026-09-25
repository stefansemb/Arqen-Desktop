"""Discord (webhook) and Telegram (bot) for sending messages and notifications."""

from __future__ import annotations

import re

from arqen.connectors.base import Connector, CredentialField
from arqen.connectors.http import ServiceError, request_json

_DISCORD_WEBHOOK = re.compile(r"^https://(?:discord|discordapp)\.com/api/webhooks/\d+/[\w-]+$")
_LIMIT = {"discord": 2000, "telegram": 4096}


def _clip(text: str, service: str) -> str:
    limit = _LIMIT[service]
    return text if len(text) <= limit else text[: limit - 1] + "…"


def discord_send(credentials: dict[str, str], text: str) -> None:
    url = credentials["webhook_url"].strip()
    if not _DISCORD_WEBHOOK.match(url):
        raise ServiceError("That is not a Discord webhook address.")
    request_json("POST", url, body={"content": _clip(text, "discord")})


def _discord_test(credentials: dict[str, str]) -> str:
    url = credentials["webhook_url"].strip()
    if not _DISCORD_WEBHOOK.match(url):
        raise ServiceError("That is not a Discord webhook address.")
    # Reading a webhook returns its details without posting anything.
    info = request_json("GET", url) or {}
    return info.get("name") or "webhook"


def telegram_send(credentials: dict[str, str], text: str) -> None:
    token, chat = credentials["bot_token"].strip(), credentials["chat_id"].strip()
    request_json("POST", f"https://api.telegram.org/bot{token}/sendMessage",
                 body={"chat_id": chat, "text": _clip(text, "telegram")})


def _telegram_test(credentials: dict[str, str]) -> str:
    token = credentials["bot_token"].strip()
    bot = (request_json("GET", f"https://api.telegram.org/bot{token}/getMe") or {}).get("result") or {}
    if not bot.get("username"):
        raise ServiceError("Telegram did not recognise this bot token.")
    return "@" + bot["username"]


DISCORD = Connector(
    id="discord",
    name="Discord",
    category="Meddelanden",
    description="Skicka meddelanden till en kanal via webhook, t.ex. när en uppgift är klar.",
    tools=("discord_send_message",),
    auth="token",
    builtin=False,
    icon="Dc",
    fields=(CredentialField(
        "webhook_url", "Webhook-adress",
        placeholder="https://discord.com/api/webhooks/…",
        help="Kanalinställningar → Integrationer → Webhooks → Ny webhook → Kopiera adress.",
    ),),
    test=_discord_test,
    notify=discord_send,
)

TELEGRAM = Connector(
    id="telegram",
    name="Telegram",
    category="Meddelanden",
    description="Skicka meddelanden via en egen bot, t.ex. när en uppgift är klar.",
    tools=("telegram_send_message",),
    auth="token",
    builtin=False,
    icon="T",
    fields=(
        CredentialField("bot_token", "Bot-token", placeholder="123456:ABC…",
                        help="Skapa en bot hos @BotFather i Telegram och kopiera token."),
        CredentialField("chat_id", "Chatt-id", secret=False, placeholder="123456789",
                        help="Skriv till boten först; chatt-id får du t.ex. via @userinfobot."),
    ),
    test=_telegram_test,
    notify=telegram_send,
)
