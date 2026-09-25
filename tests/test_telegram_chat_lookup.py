"""Finding a Telegram chat id from the bot token, without reaching Telegram."""

import io
import json
from urllib.error import HTTPError

import pytest

import arqen.connectors.http as http
from arqen.connectors.http import ServiceError
from arqen.connectors.messaging import TELEGRAM, telegram_recent_chats

TOKEN = "123456:ABCdefGHIjkl"


class FakeResponse:
    def __init__(self, payload) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self, limit=None):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def telegram(monkeypatch):
    seen: list[str] = []
    answer: dict = {}

    def fake_urlopen(request, timeout=None):
        seen.append(request.full_url)
        if isinstance(answer.get("value"), Exception):
            raise answer["value"]
        return FakeResponse(answer.get("value", {"ok": True, "result": []}))

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    return seen, answer


def _conflict(description: str) -> HTTPError:
    body = json.dumps({"ok": False, "error_code": 409, "description": description}).encode()
    return HTTPError("https://api.telegram.org", 409, "Conflict", {}, io.BytesIO(body))


def test_the_chat_id_field_offers_a_lookup():
    field = next(item for item in TELEGRAM.fields if item.name == "chat_id")
    assert field.lookup is telegram_recent_chats


def test_recent_chats_come_newest_first_without_duplicates(telegram):
    seen, answer = telegram
    answer["value"] = {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": 7377448330, "type": "private", "first_name": "Stefan", "username": "stefan"}}},
        {"update_id": 2, "message": {"chat": {"id": -100123, "type": "supergroup", "title": "Arqen-gänget"}}},
        {"update_id": 3, "edited_message": {"chat": {"id": 7377448330, "type": "private", "first_name": "Stefan"}}},
    ]}

    chats = telegram_recent_chats({"bot_token": TOKEN})

    assert chats == [("7377448330", "Stefan – private"), ("-100123", "Arqen-gänget – supergroup")]
    # Read only: no offset (which would confirm the updates for everyone) and
    # no allowed_updates (which would change the bot's settings).
    assert "offset" not in seen[0] and "allowed_updates" not in seen[0]


def test_a_bot_nobody_wrote_to_finds_nothing(telegram):
    assert telegram_recent_chats({"bot_token": TOKEN}) == []


def test_the_bot_token_is_needed_first(telegram):
    seen, _ = telegram
    with pytest.raises(ServiceError, match="bot token"):
        telegram_recent_chats({"bot_token": " "})
    assert seen == []


@pytest.mark.parametrize("description, hint", [
    ("Conflict: can't use getUpdates method while webhook is active; use deleteWebhook to delete the webhook first", "webhook"),
    ("Conflict: terminated by other getUpdates request; make sure that only one bot instance is running", "Another program"),
])
def test_a_bot_read_elsewhere_points_to_userinfobot(telegram, description, hint):
    _, answer = telegram
    answer["value"] = _conflict(description)
    with pytest.raises(ServiceError, match=hint) as error:
        telegram_recent_chats({"bot_token": TOKEN})
    assert "@userinfobot" in str(error.value)
    assert TOKEN not in str(error.value)
