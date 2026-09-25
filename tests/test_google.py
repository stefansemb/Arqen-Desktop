"""Google connection: sign-in, tokens and tools, without reaching Google."""

import base64
import hashlib
import io
import json
import threading
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import ProxyHandler, build_opener

import pytest

import arqen.connectors.google as google
import arqen.connectors.http as http
from arqen.connectors import store
from arqen.connectors.external import connector_by_id
from arqen.connectors.http import ServiceError
from arqen.tools.builtins import create_builtin_registry
from arqen.tools.executor import ToolExecutor
from arqen.tools.gateway import ToolGateway
from arqen.tools.schema import build_tool_schemas

CLIENT = {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-testsecret"}
SIGNED_IN = {**CLIENT, "refresh_token": "1//refresh-token-xyz"}


class FakeResponse:
    def __init__(self, payload) -> None:
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self, limit=None):
        return self._raw if limit is None else self._raw[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def fresh_token_cache(monkeypatch):
    monkeypatch.setattr(google, "_ACCESS", {})


@pytest.fixture
def web(monkeypatch):
    """Record requests and answer each from a script keyed by URL fragment.

    Longer fragments win, so '/messages/m1' can answer differently from '/messages?'.
    An answer that is an exception is raised instead.
    """
    calls: list[dict] = []
    answers: dict[str, object] = {"oauth2.googleapis.com/token": {"access_token": "ya29.access", "expires_in": 3599}}

    def fake_urlopen(request, timeout=None):
        body = request.data.decode("utf-8") if request.data else ""
        headers = dict(request.header_items())
        if headers.get("Content-type") == "application/x-www-form-urlencoded":
            parsed = {key: values[0] for key, values in parse_qs(body).items()}
        else:
            parsed = json.loads(body) if body else None
        calls.append({"method": request.get_method(), "url": request.full_url, "body": parsed, "headers": headers})
        for fragment in sorted(answers, key=len, reverse=True):
            if fragment in request.full_url:
                answer = answers[fragment]
                if isinstance(answer, Exception):
                    raise answer
                return FakeResponse(answer)
        return FakeResponse({})

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    return calls, answers


def _http_error(code: int, payload: dict) -> HTTPError:
    return HTTPError("https://oauth2.googleapis.com/token", code, "error", {}, io.BytesIO(json.dumps(payload).encode()))


def _browser(answer):
    """A stand-in for the user's browser: follows Google's redirect with ``answer(params)``."""
    seen: dict = {}

    def open_url(url: str) -> None:
        params = {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}
        seen.update(params)
        query = answer(params)
        if query is None:
            return

        def visit() -> None:
            # Straight to the loopback listener, past any system proxy.
            with build_opener(ProxyHandler({})).open(f"{params['redirect_uri']}/?{query}", timeout=5) as response:
                seen["page"] = response.read().decode("utf-8")

        seen["visit"] = threading.Thread(target=visit, daemon=True)
        seen["visit"].start()

    return open_url, seen


# --- Sign-in -----------------------------------------------------------------

def test_sign_in_uses_pkce_on_the_loopback_address(web):
    calls, answers = web
    answers["oauth2.googleapis.com/token"] = {
        "access_token": "ya29.access", "expires_in": 3599, "refresh_token": "1//new-refresh",
        "scope": " ".join(google.SCOPES),
    }
    answers["/gmail/v1/users/me/profile"] = {"emailAddress": "stefan@example.com"}
    open_url, seen = _browser(lambda params: f"state={params['state']}&code=auth-code-1")

    result = google.authorize(CLIENT, open_url=open_url, timeout=10)

    assert urlparse(seen["redirect_uri"]).hostname == "127.0.0.1"
    assert seen["code_challenge_method"] == "S256"
    assert seen["access_type"] == "offline"
    assert set(seen["scope"].split()) == set(google.SCOPES)
    seen["visit"].join(5)
    assert "Arqen" in seen["page"]
    exchange = calls[0]["body"]
    assert exchange["code"] == "auth-code-1"
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["redirect_uri"] == seen["redirect_uri"]
    # The verifier sent to Google is the one the challenge was made from.
    digest = hashlib.sha256(exchange["code_verifier"].encode("ascii")).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == seen["code_challenge"]
    assert result == {
        "refresh_token": "1//new-refresh",
        "settings": {"account": "stefan@example.com", "scopes": list(google.SCOPES), "needs_reconnect": False},
        "missing": [],
    }


def test_sign_in_reports_unticked_scopes(web):
    _, answers = web
    answers["oauth2.googleapis.com/token"] = {
        "access_token": "ya29.access", "refresh_token": "1//r", "scope": google.SCOPES[2],
    }
    open_url, _ = _browser(lambda params: f"state={params['state']}&code=c")

    result = google.authorize(CLIENT, open_url=open_url, timeout=10)

    assert result["settings"]["account"] == "" and result["settings"]["scopes"] == [google.SCOPES[2]]
    assert result["missing"] == ["gmail.readonly", "gmail.compose", "drive.readonly"]


def test_sign_in_rejects_a_forged_state(web):
    calls, _ = web
    open_url, _ = _browser(lambda params: "state=someone-else&code=stolen")
    with pytest.raises(ServiceError):
        google.authorize(CLIENT, open_url=open_url, timeout=10)
    assert calls == []  # the code was never exchanged


def test_sign_in_explains_a_refusal(web):
    open_url, _ = _browser(lambda params: f"state={params['state']}&error=access_denied")
    with pytest.raises(ServiceError, match="not granted"):
        google.authorize(CLIENT, open_url=open_url, timeout=10)


def test_sign_in_can_be_cancelled(web):
    cancel = threading.Event()
    cancel.set()
    open_url, _ = _browser(lambda params: None)
    with pytest.raises(ServiceError, match="cancelled"):
        google.authorize(CLIENT, cancel=cancel, open_url=open_url, timeout=10)


# --- Tokens ------------------------------------------------------------------

def test_access_token_is_refreshed_once_and_cached(web):
    calls, _ = web
    assert google.access_token(SIGNED_IN) == "ya29.access"
    assert google.access_token(SIGNED_IN) == "ya29.access"
    assert len(calls) == 1
    assert calls[0]["body"] == {**SIGNED_IN, "grant_type": "refresh_token"}


def test_an_expired_grant_asks_for_a_new_sign_in(web):
    _, answers = web
    answers["oauth2.googleapis.com/token"] = _http_error(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
    with pytest.raises(ServiceError, match="Sign in again"):
        google.access_token(SIGNED_IN)


def test_google_api_errors_are_readable(web):
    _, answers = web
    answers["/drive/v3/files"] = _http_error(403, {"error": {"code": 403, "message": "Insufficient Permission"}})
    with pytest.raises(ServiceError, match="HTTP 403: Insufficient Permission"):
        google.google_json("GET", f"{google.DRIVE}/files", SIGNED_IN)


def test_disconnecting_revokes_the_grant(web):
    calls, _ = web
    google.revoke(SIGNED_IN)
    assert calls[-1]["url"] == google.REVOKE_URL
    assert calls[-1]["body"] == {"token": SIGNED_IN["refresh_token"]}


# --- Connection state ----------------------------------------------------------

def test_google_needs_a_sign_in_not_just_a_client():
    registry = create_builtin_registry()
    connector = connector_by_id("google")
    store.save_credentials("google", CLIENT)
    assert not connector.is_connected()
    assert "gmail_search_messages" not in {s["function"]["name"] for s in build_tool_schemas(registry)}
    store.save_credentials("google", SIGNED_IN)
    assert connector.is_connected()
    assert "gmail_search_messages" in {s["function"]["name"] for s in build_tool_schemas(registry)}


@pytest.fixture
def gateway():
    store.save_credentials("google", SIGNED_IN)
    return ToolGateway(ToolExecutor(create_builtin_registry()))


# --- Gmail ---------------------------------------------------------------------

def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode().rstrip("=")


def test_gmail_search_lists_messages(web, gateway):
    calls, answers = web
    answers["/messages?"] = {"messages": [{"id": "m1"}]}
    answers["/messages/m1"] = {
        "id": "m1", "labelIds": ["UNREAD"], "snippet": "Hej &amp; välkommen",
        "payload": {"headers": [
            {"name": "From", "value": "Anna <anna@example.com>"},
            {"name": "Subject", "value": "Möte"},
            {"name": "Date", "value": "Thu, 24 Sep 2026 10:00:00 +0200"},
        ]},
    }

    result = gateway.execute("gmail_search_messages", {"query": "from:anna"})

    assert result.ok
    assert "[m1]" in result.output and "Anna <anna@example.com>" in result.output
    assert "Möte (unread)" in result.output and "Hej & välkommen" in result.output
    assert "q=from%3Aanna" in calls[1]["url"]
    assert calls[1]["headers"]["Authorization"] == "Bearer ya29.access"


def test_gmail_read_prefers_plain_text_and_lists_attachments(web, gateway):
    _, answers = web
    answers["/messages/m2"] = {"payload": {
        "headers": [{"name": "Subject", "value": "Faktura"}],
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("Hej Stefan, här är fakturan.")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>Hej</p>")}},
            ]},
            {"mimeType": "application/pdf", "filename": "faktura.pdf", "body": {"attachmentId": "a1"}},
        ],
    }}

    output = gateway.execute("gmail_read_message", {"message_id": "m2"}).output

    assert "Subject: Faktura" in output
    assert "Attachments: faktura.pdf" in output
    assert output.endswith("Hej Stefan, här är fakturan.")


def test_gmail_draft_needs_approval_and_is_never_sent(web, gateway):
    calls, answers = web
    answers["/drafts"] = {"id": "d1"}
    arguments = {"to": "anna@example.com", "subject": "Möte i morgon", "body": "Hej Anna!"}

    first = gateway.execute("gmail_create_draft", arguments)
    assert first.confirmation_required and calls == []

    result = gateway.executor.confirm_pending(True)

    assert result.ok and "has not been sent" in result.output
    assert calls[-1]["url"] == f"{google.GMAIL}/drafts"
    raw = base64.urlsafe_b64decode(calls[-1]["body"]["message"]["raw"]).decode("utf-8")
    assert "To: anna@example.com" in raw
    assert all("/send" not in call["url"] for call in calls)


def test_gmail_draft_rejects_a_bad_address(gateway):
    result = gateway.execute("gmail_create_draft", {"to": "anna, bo@example.com", "subject": "x", "body": "y"})
    assert not result.ok and not result.confirmation_required
    assert "anna" in result.output


# --- Calendar ------------------------------------------------------------------

def test_calendar_lists_upcoming_events(web, gateway):
    calls, answers = web
    answers["/events?"] = {"items": [
        {"summary": "Tandläkare", "start": {"date": "2026-09-28"}, "end": {"date": "2026-09-29"}},
    ]}

    output = gateway.execute("calendar_list_events", {"days": "7"}).output

    assert "Tandläkare" in output and "2026-09-28 (all day)" in output
    params = parse_qs(urlparse(calls[-1]["url"]).query)
    assert params["singleEvents"] == ["true"] and params["orderBy"] == ["startTime"]


def test_calendar_event_needs_approval_and_sends_local_time(web, gateway):
    calls, answers = web
    answers["/calendars/primary/events"] = {"summary": "Möte", "start": {"dateTime": "2026-09-30T14:00:00+02:00"}}

    first = gateway.execute("calendar_create_event", {
        "title": "Möte", "start": "2026-09-30T14:00", "end": "2026-09-30T15:00", "description": "",
    })
    assert first.confirmation_required
    result = gateway.executor.confirm_pending(True)

    assert result.ok and "Event created: Möte" in result.output
    body = calls[-1]["body"]
    assert body["summary"] == "Möte" and "description" not in body
    assert body["start"]["dateTime"].startswith("2026-09-30T14:00:00")
    assert body["start"]["dateTime"][19:]  # carries the local UTC offset


def test_all_day_events_end_the_day_after(web, gateway):
    calls, _ = web
    gateway.execute("calendar_create_event", {"title": "Semester", "start": "2026-10-05", "end": "2026-10-09", "description": "Italien"})
    gateway.executor.confirm_pending(True)
    body = calls[-1]["body"]
    assert body["start"] == {"date": "2026-10-05"} and body["end"] == {"date": "2026-10-10"}
    assert body["description"] == "Italien"


def test_calendar_event_must_end_after_it_starts(gateway):
    result = gateway.execute("calendar_create_event", {
        "title": "Möte", "start": "2026-09-30T15:00", "end": "2026-09-30T14:00", "description": "",
    })
    assert not result.confirmation_required and "end after" in result.output


# --- Drive ---------------------------------------------------------------------

def test_drive_search_escapes_the_query(web, gateway):
    calls, answers = web
    answers["/drive/v3/files?"] = {"files": [
        {"id": "f1", "name": "Budget 2026", "mimeType": "application/vnd.google-apps.spreadsheet", "modifiedTime": "2026-09-20T08:00:00Z"},
    ]}

    output = gateway.execute("drive_search_files", {"query": "Stefan's budget"}).output

    assert "[f1] Budget 2026 — spreadsheet, changed 2026-09-20" in output
    query = parse_qs(urlparse(calls[-1]["url"]).query)["q"][0]
    assert "name contains 'Stefan\\'s budget'" in query and "trashed = false" in query


def test_drive_reads_a_google_doc_as_text(web, gateway):
    calls, answers = web
    answers["/files/doc1?fields"] = {"id": "doc1", "name": "Anteckningar", "mimeType": "application/vnd.google-apps.document"}
    answers["/files/doc1/export"] = "﻿Rad ett\nRad två".encode("utf-8")

    output = gateway.execute("drive_read_file", {"file_id": "doc1"}).output

    assert output == "Anteckningar\n\nRad ett\nRad två"
    assert "mimeType=text%2Fplain" in calls[-1]["url"]


def test_drive_declines_binary_files(web, gateway):
    _, answers = web
    answers["/files/img?fields"] = {"id": "img", "name": "bild.png", "mimeType": "image/png"}
    output = gateway.execute("drive_read_file", {"file_id": "img"}).output
    assert "cannot be read as text" in output


def test_google_secrets_never_reach_tool_output(web, gateway):
    _, answers = web
    answers["/messages?"] = _http_error(400, {"error": {"message": f"bad client {CLIENT['client_secret']} {SIGNED_IN['refresh_token']}"}})
    result = gateway.execute("gmail_search_messages", {"query": ""})
    assert not result.ok
    assert CLIENT["client_secret"] not in result.output
    assert SIGNED_IN["refresh_token"] not in result.output


def test_an_expired_grant_marks_the_card_until_signed_in_again(web):
    _, answers = web
    store.save_credentials("google", SIGNED_IN)
    connector = connector_by_id("google")
    answers["oauth2.googleapis.com/token"] = _http_error(400, {"error": "invalid_grant"})

    with pytest.raises(ServiceError):
        google.access_token(SIGNED_IN)
    assert connector.needs_reconnect()

    # A later refresh that works (e.g. a new sign-in) clears the mark.
    answers["oauth2.googleapis.com/token"] = {"access_token": "ya29.new", "expires_in": 3599}
    google.access_token(SIGNED_IN)
    assert not connector.needs_reconnect()


def test_a_fresh_sign_in_clears_the_reconnect_mark(web):
    _, answers = web
    answers["oauth2.googleapis.com/token"] = {"access_token": "a", "refresh_token": "1//r", "scope": ""}
    open_url, _ = _browser(lambda params: f"state={params['state']}&code=c")
    assert google.authorize(CLIENT, open_url=open_url, timeout=10)["settings"]["needs_reconnect"] is False


def test_a_disconnected_card_never_asks_to_reconnect():
    store.save_settings("google", needs_reconnect=True)
    assert not connector_by_id("google").needs_reconnect()
