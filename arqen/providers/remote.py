"""Provider for the public Arqen API."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from arqen.core.contracts import Message, ProviderResponse
from arqen.providers.base import AIProvider


class ArqenRemoteProvider(AIProvider):
    def __init__(self, base_url: str, timeout: float, api_key: str, model: str = "qwen3:8b") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        self.model = model
        self.provider_name = "arqen-remote"
        self._session_id = ""
        self._sent_user_messages = 0

    def _request(self, path: str, payload: dict) -> dict:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            detail = getattr(exc, "reason", str(exc))
            if isinstance(exc, HTTPError):
                try:
                    detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", detail)
                except (OSError, json.JSONDecodeError):
                    pass
            raise RuntimeError(f"Arqen Remote kunde inte svara: {detail}") from exc

    def respond(self, messages: list[Message]) -> ProviderResponse:
        users = [message.content for message in messages if message.role == "user"]
        if not users:
            return ProviderResponse("")
        if len(users) < self._sent_user_messages:
            self._session_id = ""
            self._sent_user_messages = 0
        if not self._session_id:
            created = self._request("/api/v1/sessions", {"title": "Desktopchatt"})
            self._session_id = created["data"]["session_id"]
        response = None
        for content in users[self._sent_user_messages:]:
            response = self._request(
                f"/api/v1/sessions/{self._session_id}/messages",
                {"content": content},
            )
            self._sent_user_messages += 1
        return ProviderResponse(response["data"]["assistant_message"] if response else "")
