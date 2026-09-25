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


def telegram_recent_chats(credentials: dict[str, str]) -> list[tuple[str, str]]:
    """Chats that recently wrote to the bot, newest first, as (chat id, description).

    Reads the bot's pending updates without confirming them (no offset) and
    without changing its settings (no allowed_updates), so another program
    reading the same bot still gets every message.
    """
    token = credentials.get("bot_token", "").strip()
    if not token:
        raise ServiceError("Fill in the bot token first.")
    try:
        updates = (request_json("GET", f"https://api.telegram.org/bot{token}/getUpdates?timeout=0&limit=100") or {}).get("result") or []
    except ServiceError as exc:
        text = str(exc)
        if "webhook" in text:
            raise ServiceError("The bot delivers its messages to a webhook, so Arqen cannot read them. "
                               "Use @userinfobot to find your chat id.") from None
        if "getUpdates" in text or "HTTP 409" in text:
            raise ServiceError("Another program is reading this bot's messages right now. "
                               "Use @userinfobot to find your chat id.") from None
        raise
    chats: dict[str, str] = {}
    for update in reversed(updates):
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat") or {}
            if "id" not in chat:
                continue
            name = chat.get("title") or " ".join(filter(None, (chat.get("first_name"), chat.get("last_name")))) or "?"
            if chat.get("username"):
                name += f" (@{chat['username']})"
            chats.setdefault(str(chat["id"]), f"{name} – {chat.get('type', 'chat')}")
    return list(chats.items())


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
                        help="Skriv något till boten i Telegram och tryck HÄMTA CHATT-ID, "
                             "eller hämta ditt id via @userinfobot.",
                        lookup=telegram_recent_chats, lookup_label="FETCH CHAT ID"),
    ),
    test=_telegram_test,
    notify=telegram_send,
)
